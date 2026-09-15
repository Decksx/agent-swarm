"""Answer operator-issued activations with the OpenAI API, and narrate to the hub.

Sibling of ``claude_worker.py`` and deliberately built to match it: same hub
(default ``http://192.168.42.50:8050``), same confirmed message schema, same
state-file de-duplication, same poll loop and graceful shutdown, and the same
Phase 0 containment. The one structural difference is what it does with an
activation -- it calls the OpenAI Chat Completions API rather than a local CLI.

Trust boundary
--------------

This daemon does not execute anything on this machine, so it never carried the
Claude worker's remote-code-execution surface. What it did carry was an
unauthenticated way to spend money and to leak: before Phase 0 it answered any
message whose target named it *or* whose content merely contained the substring
``@chatgpt`` anywhere, and it pasted the last twenty hub messages into every
prompt. Any hub client could therefore drive this account's billing, and
anything posted to the hub was forwarded to OpenAI.

Both are closed:

* **Chat cannot start anything.** Not by ``target``, not by ``@mention``, not
  from any sender. Messages are fetched and recorded to the local narration log
  so they stay readable; they carry no authority.
* **Prompts come from the local control directory** (see ``swarm_control``),
  which the hub cannot reach, and from nowhere else. No hub content is fed to
  the model at all now that ``fetch_recent()`` is gone -- narration is written
  to disk for a human to read, never routed back into a model.
* **The pause flag is checked before each claim.**
* **Identity is bound from local configuration** and never adopted from an
  inbound message.
* Replies are addressed to ``@Admin``, never to a peer worker.

**Hub content still leaves the LAN** when an operator's activation text is sent
to the OpenAI API. That is inherent to the task; it is now bounded by what the
operator wrote rather than by whatever happened to be on the stream.

The API key
-----------

``OPENAI_API_KEY`` is read from the environment only -- there is no file
fallback, and ``.env*`` is excluded from version control so it cannot be
committed. It is validated at startup through ``swarm_control.load_credential``
so a blank or placeholder value is refused here rather than surfacing as a 401
much later, and the refusal never carries the value: a key that reaches a log
has to be treated as exposed and rotated. Startup logs only that a key is
present.

Hub schema (confirmed, shared with claude_worker.py)
----------------------------------------------------

* ``GET /messages`` returns a bare JSON **list** of objects with ``id``,
  ``sender``, ``target``, ``content`` and ``timestamp``.
* ``POST /send`` takes ``sender``, ``target`` and ``content``.

``POST /send`` accepts an optional ``token``, but ``GET /messages`` never
returns one, which is why the pre-Phase-0 ``token_ok()`` check could refuse
traffic but never admit it. De-duplication is by ``id``.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import authored_change
import authored_edits
import controller_client
import publication
import repo_registry
import swarm_control
import worktrees

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")

# Bound from local configuration and never adopted from an inbound message.
# `sender` is free text on an unauthenticated hub, so reading an identity out
# of a message would let any writer decide who this process claims to be.
AGENT_IDENTITY = swarm_control.bind_identity(
    os.environ.get("AGENT_IDENTITY", "chatgpt")
)

# Retained only so the narration log and the operator CLI can still recognise
# this worker's own handle. It is no longer compared against message targets
# or against '@name' mentions, because neither can start work any more.
SELF_HANDLES = {"chatgpt"}

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "chatgpt_worker.state"
LOG_FILE = HERE / "chatgpt_worker.log"

# One source, chosen at startup. Same reasoning as the other two workers.
ACTIVATION_SOURCE = os.environ.get("ACTIVATION_SOURCE", "directory").strip().lower()
VALID_SOURCES = ("directory", "controller")

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", HUB_URL)

# The registered project this worker authors for. A name, resolved through
# repos.json -- never a path. Authoring happens in a worktree created at the
# task's own base_sha, so the canonical checkout is only ever read from: it is
# where a person works, it is normally dirty, and committing on top of that
# would put somebody's unfinished edits into a model's commit.
AUTHOR_PROJECT = os.environ.get("AUTHOR_PROJECT", "")

# Where a candidate is published, and what it is proposed against. Both empty
# by default, and an empty slug means publication is skipped entirely rather
# than guessed at -- a worker that inferred a remote from the checkout's
# `origin` would push a model's commit to whatever that happened to be.
PUBLISH_REPO_SLUG = os.environ.get("PUBLISH_REPO_SLUG", "").strip()
PUBLISH_TARGET_REF = os.environ.get(
    "PUBLISH_TARGET_REF", "refs/heads/master"
).strip()

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))
OPENAI_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "120"))

# The context-window clamp that used to sit here is gone with fetch_recent().
# It bounded how much untrusted hub history was pasted into each prompt; no hub
# history reaches the model any more, so there is nothing left for it to bound.


# Replies are truncated so a very long model answer cannot wedge the hub or
# the transport.
MAX_REPLY_CHARS = 60_000

SYSTEM_PROMPT = (
    "You are ChatGPT, one agent in a small multi-agent engineering swarm "
    "that coordinates over a shared message hub. The other participants "
    "include Gemini (lead architect), ClaudeCode (local execution), and a "
    "human Admin. You are addressed as @ChatGPT. Messages below are the "
    "recent hub conversation, each labelled with who sent it and to whom. "
    "Reply as ChatGPT with a single, direct message suitable for posting "
    "back to the hub -- no role-play of other agents, no @-prefix on your "
    "own name."
)

# Set once in main() from HUB_SECRET. Module-level rather than threaded
# through every call because HUB_URL and the timeouts already are, and a
# worker authenticates as exactly one component for its whole life.
_HUB_AUTH: tuple | None = None

log = logging.getLogger("chatgpt_worker")


def ensure_dependencies() -> tuple[Any, Any]:
    """Import ``requests`` and the OpenAI SDK, installing once if missing.

    Returns ``(requests_module, OpenAI_class)``. Installation is a side
    effect worth being explicit about, so it happens at most once, says what
    it is doing, and gives up with an actionable message rather than looping.
    """
    missing: list[str] = []

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")

    if missing:
        print(f"installing missing packages ({', '.join(missing)}) into",
              sys.executable)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *missing],
            check=False,
        )
        if result.returncode != 0:
            sys.exit(
                "Could not install "
                f"{', '.join(missing)} automatically. Install manually with: "
                f"{sys.executable} -m pip install {' '.join(missing)}"
            )

    import requests
    from openai import OpenAI

    return requests, OpenAI


def configure_logging() -> None:
    """Log to both the console and an append-only audit file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


def message_content(message: dict) -> str | None:
    """The text of `message`, or None if absent or empty.

    Empty string counts as absent, and a non-string content is treated as
    absent too, so callers never have to re-check the type.
    """
    content = message.get("content")

    if isinstance(content, str) and content != "":
        return content

    return None


def load_last_seen_id() -> int:
    """Resume point, so a restart does not replay the whole backlog.

    A corrupt or missing state file resets to 0 -- noisy (it re-reads
    history) but the failure direction that loses no message.
    """
    try:
        return int(STATE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def save_last_seen_id(message_id: int) -> None:
    try:
        STATE_FILE.write_text(str(message_id), encoding="utf-8")
    except OSError as exc:
        log.warning("could not persist last_seen_id=%s: %s", message_id, exc)


# is_for_chatgpt() and token_ok() are gone rather than tightened.
#
# is_for_chatgpt() started a model call whenever a message's target named this
# worker OR the substring "@chatgpt" appeared anywhere in its content, which
# meant any hub client -- including another agent quoting a handle in passing
# -- could spend this account's budget. token_ok() compared an inbound `token`
# field that the hub never returns on GET /messages, so it could refuse
# traffic but never admit it.
#
# Both read fields off an unauthenticated stream, so neither could be repaired
# where it stood. Whether a message may start work is now answered in one
# place, for all three workers, by swarm_control.chat_message_activates().
# It returns False.


# The reply governor and the verification gate that used to sit here have
# been removed, not disabled.
#
# Both existed to bound a loop in which each worker answered the others'
# messages: a per-sender cooldown, a rolling rate cap, and a stop after N
# consecutive agent-only exchanges. All three were advisory, in-memory and
# cleared by a restart, and all three are now unreachable -- chat cannot
# start work at all, and replies are addressed to @Admin rather than to a
# peer, so there is no exchange left for them to count.
#
# They are deleted rather than left in place because an inert safety gate is
# worse than none: the next reader takes it for the mechanism providing
# safety, when the real reason the loop cannot form is that the trigger is
# gone. A guard that fails nothing when bypassed was never load-bearing.


def fetch_messages(requests: Any, since_id: int) -> list[dict]:
    """Messages newer than `since_id`, or [] on any hub error.

    Transport failures are logged and swallowed: the hub being briefly
    unreachable is expected for a daemon, not a reason to exit.
    """
    try:
        response = requests.get(
            f"{HUB_URL}/messages",
            params={"since_id": since_id},
            timeout=HTTP_TIMEOUT,
            auth=_HUB_AUTH,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("poll failed: %s", exc)
        return []

    if not isinstance(payload, list):
        log.warning(
            "poll returned a non-list payload (%s); ignoring",
            type(payload).__name__,
        )
        return []

    return payload


# fetch_recent() is removed. It pulled the last N hub messages into the model
# prompt, which meant untrusted stream content -- written by anyone able to
# POST to an unauthenticated hub -- was fed to the model as context on every
# turn. The prompt now comes from the activation and nothing else. Narration is
# recorded to disk for a human to read, not routed back into a model.


def build_chat_messages(context: list[dict]) -> list[dict]:
    """Map hub messages onto the OpenAI chat format.

    This worker's own past messages become ``assistant`` turns; everyone
    else's become ``user`` turns tagged with who said them and to whom, so
    the model can follow attribution in a multi-party thread it would
    otherwise see as one undifferentiated voice.
    """
    chat: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    for message in context:
        text = message_content(message)
        if text is None:
            continue

        sender = str(message.get("sender", "unknown"))
        # The instant, ahead of the speaker. A transcript without it is a flat
        # list of turns, and a model continuing a thread cannot tell that the
        # last three messages arrived after an overnight gap -- which is
        # exactly when whatever it is being asked about has moved on.
        when = swarm_control.message_stamp(message)

        if sender.strip().lstrip("@").lower() in SELF_HANDLES:
            # This worker's own past replies. Stamped too: the gap before its
            # own last message is as informative as the gap before anyone
            # else's, and an unstamped line in a stamped transcript reads as a
            # message with no time rather than as one of its own.
            chat.append({"role": "assistant", "content": f"[{when}] {text}"})
        else:
            target = str(message.get("target", ""))
            chat.append(
                {
                    "role": "user",
                    "content": f"[{when}] {sender} (to {target}): {text}",
                }
            )

    return chat


def generate_reply(client: Any, context: list[dict]) -> str | None:
    """Ask the model for one reply, or None if there is nothing to post.

    Any SDK/API failure is caught rather than propagated -- one failed
    generation must not kill the daemon -- but it is recorded *here*, in
    this worker's log, and not returned as text.

    Returning an error string would post it to the hub as an ordinary
    ChatGPT reply, indistinguishable from a real answer: peers then read
    "[ChatGPT worker: generation failed: ...]" as content and respond to it,
    so a transient 429 becomes a conversation. An outage is an operator's
    problem, visible in the log; silence is the honest thing to put on the
    hub. (This mirrors the Gemini worker, which was hardened the same way.)

    The response extraction is inside the try as well: an empty ``choices``
    list would make ``choices[0]`` raise, and that must fail to None like
    any other API problem rather than crash the poll loop.
    """
    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=build_chat_messages(context),
            timeout=OPENAI_TIMEOUT,
        )
        reply = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        # exc_info, because the message alone loses which SDK call failed --
        # and this is now the only record of the failure anywhere.
        log.error("OpenAI request failed: %s", exc, exc_info=True)
        return None

    if not reply:
        log.warning("OpenAI returned an empty reply; nothing to post")
        return None

    return reply


def post_reply(requests: Any, target: str, body: str, message_id: Any) -> None:
    """Post one reply back to the hub, addressed to `target`.

    The payload is exactly the hub's request schema -- sender, target,
    content -- plus the shared token only when auth is configured.
    """
    if len(body) > MAX_REPLY_CHARS:
        body = body[:MAX_REPLY_CHARS] + (
            f"\n[truncated at {MAX_REPLY_CHARS} characters]"
        )

    payload = swarm_control.outbound_envelope(AGENT_IDENTITY, target, body)

    try:
        response = requests.post(
            f"{HUB_URL}/send",
            json=payload,
            timeout=HTTP_TIMEOUT,
            auth=_HUB_AUTH,
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("failed to post reply for message %s: %s", message_id, exc)


# reply_target_for() is removed. It addressed each reply back at whoever sent
# the triggering message, so a message from a peer produced a reply aimed at
# that peer -- the return leg of the loop. Replies now go to @Admin, which is
# a constant at the one call site rather than a function of untrusted input.


def execute_author(client: Any, activation: dict, queue: Any) -> None:
    """Author one change. Exactly one model call, then a deterministic commit.

    The split matters: the model supplies file contents and this function
    applies them. It has no shell, so there is no path by which the model
    itself can run anything -- what it returns is text, and the only thing done
    with that text is writing files whose paths were validated first.

    Every failure ends in a submitted outcome rather than a return, so a task
    never sits in AUTHORING waiting out a lease because the worker gave up
    quietly.
    """
    activation_id = activation.get("activation_id")
    task_id = activation.get("task_id") or "task"
    task_record = activation.get("task_record") or {}

    if not AUTHOR_PROJECT:
        log.error("AUTHOR_PROJECT is not set; cannot author %s", activation_id)
        queue.report(activation_id, outcome="blocked",
                     payload={"reason": "AUTHOR_PROJECT is not configured on this host"})
        return

    try:
        project = repo_registry.get(AUTHOR_PROJECT)
    except repo_registry.RegistryError as exc:
        log.error("activation %s: %s", activation_id, exc)
        queue.report(activation_id, outcome="blocked",
                     payload={"reason": f"repository registry: {exc}"})
        return

    # The baseline comes from the controller, not from this host. A worker
    # deciding for itself what to branch from is a worker deciding what was
    # reviewed.
    base_sha = str(task_record.get("base_sha") or "").strip()

    if len(base_sha) != 40:
        log.error("activation %s carries no usable base_sha", activation_id)
        queue.report(activation_id, outcome="blocked", payload={
            "reason": f"the task's base_sha is {base_sha!r}, not a commit",
        })
        return

    # What the contract authorises this task to write. Refused here, before
    # the model is called, if it does not say: a contract nobody can read is
    # not a contract, and the previous reading of it -- unparseable means
    # unrestricted -- turned every parser gap into repository-wide write
    # access. AUTHOR_BLOCKED rather than failed, because the fix is a human
    # editing the contract, not a retry.
    #
    # `require_contract` rather than `parse_scope`, which is what this used to
    # call: the paths are not the whole contract. The prompt now states the
    # base commit, the proof mode and the contract hash the author is bound
    # by, and those come from the task record rather than the contract text.
    # Parsing only the paths left a record missing any of them to reach the
    # renderer and fail there, mid-activation, on a field nobody had checked.
    # The same check the CLI author already makes, and fail-closed for the
    # same reason: a task whose proof mode nobody recorded must not be
    # authored under a guess at one.
    try:
        scope = authored_change.require_contract(task_record)
    except authored_change.ContractDefect as exc:
        log.error("activation %s has no usable contract: %s", activation_id, exc)
        queue.report(activation_id, outcome="blocked", payload={
            "reason": f"contract unusable: {exc}",
        })
        return

    if scope.unrestricted:
        log.warning(
            "activation %s authorises the ENTIRE repository of %s",
            activation_id, project.name,
        )

    # A private tree at the baseline, before the model is called. The old
    # check -- refuse if the shared checkout is dirty -- was the right
    # instinct in the wrong place: it made a person's unsaved work into an
    # obstacle, which is how a safety check gets switched off. Nothing here
    # touches that checkout.
    try:
        workspace = worktrees.create(project, base_sha, activation_id)
    except worktrees.WorktreeError as exc:
        log.error("no workspace for activation %s: %s", activation_id, exc)
        queue.report(activation_id, outcome="blocked", payload={
            "reason": f"could not prepare an isolated worktree: {exc}",
        })
        return

    log.info(
        "activation %s: worktree %s at %s", activation_id, workspace, base_sha[:12]
    )

    # Fail closed before the model is called, not after.
    #
    # A candidate nobody can publish is a candidate no reviewer can reach and
    # no CI can run against, so the task stops at READY_REVIEW having spent a
    # model call to get there. Checked here rather than at the publication
    # step because the cost of the misconfiguration is the call, and the call
    # is about to happen.
    #
    # Where the candidate goes is `publication.target_for`: the project's
    # `publish` block in repos.json, else this host's PUBLISH_REPO_SLUG, else
    # nowhere -- which only a `branch_only` task may accept (#32). The proof
    # mode is the task's own, from the controller's `task_versions`.
    try:
        publish_target = publication.target_for(
            project, task_record.get("proof_mode"),
            fallback_slug=PUBLISH_REPO_SLUG,
            fallback_target_ref=PUBLISH_TARGET_REF,
        )
    except publication.PublicationError as exc:
        log.error("activation %s: %s", activation_id, exc)

        try:
            worktrees.remove(project, activation_id)
        except worktrees.WorktreeError as rm_exc:
            log.warning("could not remove the worktree for %s: %s",
                        activation_id, rm_exc)

        queue.report(activation_id, outcome="blocked",
                     payload={"reason": str(exc)})
        return

    # What the files it may change look like right now. Without this an author
    # with no shell has to invent the parts of a file it was not shown, and
    # the output format requires the whole file.
    existing = authored_change.existing_in_scope(str(workspace), base_sha, scope)

    if existing:
        log.info(
            "activation %s: showing %d in-scope file(s) to the author",
            activation_id, len(existing),
        )

    # The read-only reading list: the imports, interfaces and tests the change
    # has to fit. Read from the task's own base commit, in the private
    # worktree, so the author and the reviewer are looking at the same bytes.
    context = authored_change.context_at(str(workspace), base_sha, scope)

    # A context path that is not there is a defect in the plan, not in the
    # attempt. The planner named a file at a commit where it does not exist,
    # which means the plan was written against a repository that no longer
    # matches -- and the author cannot discover that, because from inside the
    # prompt a shorter reading list looks exactly like a shorter reading list.
    #
    # Blocked before the model is called, for the same reason an unreadable
    # contract is: the fix is somebody correcting the task, and a retry would
    # spend an attempt reproducing the same absence. Silence here would be the
    # worse failure -- the author would proceed without the file it was
    # promised and produce something plausible, which is the exact shape of
    # the candidate the reviewer had to reject.
    if context["missing"]:
        named = ", ".join(entry["path"] for entry in context["missing"])
        log.error(
            "activation %s: required context missing at %s: %s",
            activation_id, base_sha[:12], named,
        )

        try:
            worktrees.remove(project, activation_id)
        except worktrees.WorktreeError as exc:
            log.warning("could not remove the worktree for %s: %s", activation_id, exc)

        queue.report(activation_id, outcome="blocked", payload={
            "reason": (
                f"context_paths name {len(context['missing'])} path(s) that do "
                f"not exist at {base_sha[:12]}: {named}. The task was planned "
                "against a different tree; it needs correcting, not retrying."
            ),
            "missing_context": context["missing"],
            "base_sha": base_sha,
        })
        return

    if context["files"]:
        log.info(
            "activation %s: showing %d read-only context file(s)%s",
            activation_id, len(context["files"]),
            (f", {len(context['omitted'])} omitted for budget"
             if context["omitted"] else ""),
        )

    if context["omitted"]:
        # Not blocked: the author may not need them, and it has been told in
        # the prompt to answer CANNOT_AUTHOR if it does. Logged at warning
        # because a task whose context does not fit is a task that wants
        # decomposing, and that judgment belongs to a person.
        log.warning(
            "activation %s: %d context file(s) did not fit and were not shown",
            activation_id, len(context["omitted"]),
        )

    prompt = authored_change.render_author_prompt(
        {**task_record, "task_id": task_id, "allowed_paths": list(scope.paths),
         # From the activation, not the task record: it is an input the
         # controller handed to *this* attempt, and a task record shared
         # across attempts is the wrong place for something scoped to one.
         "operator_context": activation.get("operator_context")},
        existing,
        context,
        scope=scope,
    )

    log.info("AUTHORING activation %s for task %s", activation_id, task_id)
    started = time.monotonic()

    conversation = [
        {"sender": "controller", "target": "@" + AGENT_IDENTITY, "content": prompt},
    ]
    reply = generate_reply(client, conversation)
    repaired = False

    while True:
        elapsed = time.monotonic() - started

        if reply is None:
            log.warning("no reply for activation %s after %.1fs", activation_id, elapsed)
            queue.report(activation_id, outcome="blocked",
                         payload={"reason": "the model returned nothing"})
            return

        # Existing files change only through EDIT blocks, resolved against the
        # base before anything is written (#35); see `authored_edits`.
        try:
            files = authored_edits.resolve(
                str(workspace), base_sha, authored_edits.parse_answer(reply), scope)
            break
        except authored_edits.EditRefused as exc:
            if repaired:
                failure = f"{exc} (after one repair)"
            else:
                # Once, inside this activation. A SEARCH copied with the wrong
                # indentation is a transcription slip, not a verdict on the
                # change, and should not cost an author attempt; the second
                # answer that cannot be applied does.
                log.warning("activation %s: answer not applicable, asking once "
                            "more: %s", activation_id, exc)
                conversation += [
                    {"sender": AGENT_IDENTITY, "target": "@controller", "content": reply},
                    {"sender": "controller", "target": "@" + AGENT_IDENTITY,
                     "content": authored_edits.repair_prompt(exc, str(workspace), base_sha)},
                ]
                reply = generate_reply(client, conversation)
                repaired = True
                continue
        except authored_change.AuthoringError as exc:
            failure = str(exc)

        # `failed` rather than `blocked`: the model answered, and the answer
        # was not usable. That is a fact about the attempt, which is what
        # CHANGES_REQUESTED is for.
        log.error("activation %s produced an unusable answer: %s", activation_id, failure)

        try:
            worktrees.remove(project, activation_id)
        except worktrees.WorktreeError as rm_exc:
            log.warning("could not remove the worktree for %s: %s", activation_id, rm_exc)

        queue.report(activation_id, outcome="failed", payload={
            "reason": failure,
            "reply_excerpt": swarm_control.redact(reply)[:1000],
            "elapsed_seconds": round(elapsed, 1),
            "repaired": repaired,
        })
        return

    # The branch the controller named at issue time, so a retry after a
    # rejection lands on its own branch rather than colliding with the
    # candidate that was rejected -- which is still the evidence for that
    # review and must not be moved.
    branch = (activation.get("expected_branch") or f"task/{task_id}").strip()

    try:
        result = authored_change.apply_and_commit(
            str(workspace),
            branch=branch,
            base=base_sha,
            files=files,
            message=f"{task_id}: {task_record.get('title', 'authored change')}",
            scope=scope,
        )
    except authored_change.AuthoringError as exc:
        # apply_and_commit rolls back on failure, but whether it succeeded is
        # checked rather than assumed. "The attempt failed" and "the attempt
        # failed and left the repository unusable" need different responses,
        # and the second one must not be reported as the first.
        clean = authored_change.worktree_is_clean(str(workspace))

        if not clean:
            log.error(
                "activation %s failed AND left %s dirty; it needs a human",
                activation_id, workspace,
            )

        log.error("could not apply activation %s: %s", activation_id, exc)

        if clean:
            worktrees.remove(project, activation_id)
        else:
            # Left on disk deliberately. A tree that could not be rolled back
            # is the only record of what went wrong, and removing it would
            # destroy the evidence for the state it just reported.
            log.error("worktree kept for inspection: %s", workspace)

        queue.report(
            activation_id,
            # A dirty worktree is an environment problem, not a verdict on the
            # attempt: no further authoring can happen here until it is fixed,
            # and AUTHOR_BLOCKED is the state an operator releases.
            outcome="failed" if clean else "blocked",
            payload={
                "reason": str(exc),
                "worktree_clean": clean,
                "elapsed_seconds": round(elapsed, 1),
            },
        )
        return

    # The commit lives in the shared object store and the branch points at it,
    # so the worktree has done its job. Removing it keeps the root from filling
    # with one directory per attempt, and a reviewer reads the range from the
    # canonical checkout without needing a working copy at all.
    try:
        worktrees.remove(project, activation_id)
    except worktrees.WorktreeError as exc:
        log.warning("candidate is safe on %s but %s", result["branch"], exc)

    log.info(
        "COMPLETED activation %s: %s at %s (%d file(s)) in %.1fs",
        activation_id, result["branch"], result["candidate_sha"][:12],
        len(result["files"]), elapsed,
    )

    # Publish before reporting. A candidate nobody outside this machine can
    # see is a candidate no reviewer can review and no CI can run against, and
    # every run so far needed a person to push the branch and open the pull
    # request between authoring and review. Neither step is a judgment.
    #
    # Before the report rather than after, so the ledger's
    # `candidate_submitted` payload says where the candidate went. A report
    # that landed first and a push that then failed would leave a task in
    # READY_REVIEW pointing at a branch that does not exist anywhere a
    # reviewer can reach.
    published = {}

    if publish_target is not None:
        try:
            published = publication.publish_for(
                project, publish_target,
                branch=result["branch"],
                candidate_sha=result["candidate_sha"],
                task_record={**task_record, "task_id": task_id},
                activation_id=str(activation_id),
            )
            log.info(
                "published %s as PR #%s%s",
                result["branch"], published.get("pr_number"),
                " (already existed)" if not published.get("created") else "",
            )
        except publication.PublicationError as exc:
            # Blocked, not failed. The candidate is good and committed; what
            # went wrong is the environment around it, and an operator fixing
            # a remote is not a reason to make the author write the file again.
            log.error("could not publish %s: %s", result["branch"], exc)
            queue.report(activation_id, outcome="blocked", payload={
                "reason": f"the candidate was authored but could not be "
                          f"published: {exc}",
                "elapsed_seconds": round(elapsed, 1),
                **result,
            })
            return

    queue.report(activation_id, outcome="candidate", payload={
        "elapsed_seconds": round(elapsed, 1),
        **result,
        **published,
    })


def execute_activation(requests: Any, client: Any, activation: dict) -> None:
    """Answer one operator-issued activation.

    The prompt comes from the local control directory, not from the hub, so
    the model is never invoked because another agent posted a message. The
    caller has already checked the pause flag and won the claim.
    """
    activation_id = activation.get("activation_id")
    task = activation.get("task")

    if not isinstance(task, str) or not task.strip():
        log.error("activation %s has no runnable prompt; dropped", activation_id)
        return

    log.info(
        "ANSWERING activation %s from %s (%d chars)",
        activation_id,
        activation.get("issued_by", "unknown"),
        len(task),
    )

    started = time.monotonic()

    # Shaped like a hub message so the existing prompt builder is reused
    # unchanged, but sourced from the activation rather than from the stream.
    context = [
        {
            "sender": activation.get("issued_by", "admin"),
            "target": "@" + AGENT_IDENTITY,
            "content": task,
        }
    ]

    reply = generate_reply(client, context)
    elapsed = time.monotonic() - started

    if reply is None:
        log.warning(
            "NO REPLY for activation %s after %.1fs; nothing posted",
            activation_id,
            elapsed,
        )
        return

    log.info(
        "REPLIED to activation %s (%d chars) in %.1fs",
        activation_id,
        len(reply),
        elapsed,
    )

    # Addressed to the operator, never to a peer worker: a reply aimed at
    # another agent is what made the swarm self-driving.
    post_reply(requests, "@Admin", reply, activation_id)


def main() -> int:
    configure_logging()

    requests, OpenAI = ensure_dependencies()

    # Resolved before anything polls. A worker that started without a
    # credential would poll an authenticated hub forever, logging a 401 every
    # POLL_SECONDS and doing no work, which reads as a broken hub rather than
    # as unconfigured credentials.
    global _HUB_AUTH
    try:
        _HUB_AUTH = swarm_control.hub_auth(AGENT_IDENTITY)
    except swarm_control.ContainmentError as exc:
        log.error("%s", exc)
        return 1


    # Containment invariant, checked at startup rather than assumed.
    #
    # Nothing below reads CHAT_IS_AUTHORITATIVE -- the reason chat cannot start
    # work is that no code path leads from a message to execution. That is a
    # structural property, and structural properties are exactly the kind that
    # get reintroduced by accident. This check makes the constant load-bearing:
    # turning chat authoritative again means deleting a refusal in three files,
    # which is a visible act in review, rather than flipping one flag.
    if swarm_control.CHAT_IS_AUTHORITATIVE:
        log.error(
            "refusing to start: swarm_control.CHAT_IS_AUTHORITATIVE is True, "
            "but this worker has no audited path for chat-driven activation"
        )
        return 2


    # Validated before the client is built, so a blank or placeholder key is
    # refused here rather than surfacing as a 401 from the provider much later.
    # The exception deliberately never carries the value: a credential that
    # reaches a log has to be treated as exposed and rotated.
    try:
        swarm_control.load_credential("OPENAI_API_KEY")
    except swarm_control.ContainmentError as exc:
        log.error("%s", exc)
        return 1

    # The SDK reads OPENAI_API_KEY from the environment itself; the key is
    # never handled, logged, or posted by this script.
    client = OpenAI(timeout=OPENAI_TIMEOUT)

    if ACTIVATION_SOURCE not in VALID_SOURCES:
        log.error(
            "refusing to start: ACTIVATION_SOURCE=%r is not one of %s",
            ACTIVATION_SOURCE, ", ".join(VALID_SOURCES),
        )
        return 3

    queue = None

    if ACTIVATION_SOURCE == "controller":
        queue = controller_client.ControllerQueue(
            requests, base_url=CONTROLLER_URL, auth=_HUB_AUTH,
            agent=AGENT_IDENTITY, timeout=HTTP_TIMEOUT,
        )

    log.info("hub        : %s", HUB_URL)
    log.info("work from  : %s", ACTIVATION_SOURCE)
    log.info(
        "author for : %s", AUTHOR_PROJECT or "(unset -- authoring will block)"
    )
    log.info("model      : %s", OPENAI_MODEL)
    log.info("openai_key : present")
    log.info("identity   : %s (bound locally, never from a message)", AGENT_IDENTITY)
    log.info("activations: %s", swarm_control.ACTIVATIONS_DIR)
    log.info("chat       : narration only; it cannot start work")
    paused = swarm_control.pause_reason()
    log.info("pause      : %s", paused or "not paused")

    # One worker per identity, per host. Duplicates are not dangerous -- an
    # activation is claimed atomically, so a second worker polls and finds
    # nothing -- but they authenticate, they poll, and on a per-token provider
    # a duplicate that does claim something spends money. They also make
    # "exactly one model call" unmeasurable, which is the measurement every
    # live run rests on.
    instance = swarm_control.SingleInstance(AGENT_IDENTITY)

    try:
        instance.acquire()
    except swarm_control.AlreadyRunning as exc:
        log.error("%s", exc)
        return 5

    running = True

    def stop(signum, _frame):
        nonlocal running
        log.info("signal %s received; shutting down after this poll", signum)
        running = False

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    last_seen_id = load_last_seen_id()
    log.info("resuming from message id %s", last_seen_id)

    # Logged on transition rather than every poll, so a long pause leaves a
    # readable log instead of one line every POLL_SECONDS.
    was_paused = None

    while running:
        # 1. Chat. Fetched and recorded, never obeyed. There is deliberately no
        #    branch below that can reach execute_activation().
        messages = fetch_messages(requests, last_seen_id)

        for message in messages:
            raw_id = message.get("id")

            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                log.error("message with unusable id %r; skipping", raw_id)
                continue

            if message_id > last_seen_id:
                last_seen_id = message_id
                save_last_seen_id(last_seen_id)

        if messages:
            swarm_control.record_narration(messages)

        # 2. Work. Claimed from the local control directory only.
        paused = swarm_control.pause_reason()

        if paused is not None:
            if was_paused != paused:
                log.warning("PAUSED: %s; starting no new work", paused)
                was_paused = paused
        else:
            if was_paused is not None:
                log.info("pause released; accepting activations again")
                was_paused = None

            # Checked before the claim, so a pause engaged mid-poll leaves the
            # queue intact rather than consuming what it declined to run.
            if queue is not None:
                try:
                    activation = queue.claim()
                except (
                    controller_client.Unauthenticated,
                    controller_client.ClaimForbidden,
                ) as exc:
                    log.error("fatal: %s", exc)
                    return 4
            else:
                activation = swarm_control.claim_activation(AGENT_IDENTITY)

            if activation is not None:
                stage = activation.get("stage")

                if queue is not None and stage == "author":
                    execute_author(client, activation, queue)
                elif queue is not None:
                    # This worker authors. A review activation belongs to the
                    # verifier, and answering one here would produce a verdict
                    # from something that never looked at a diff.
                    log.error(
                        "activation %s has stage %r, which this worker does "
                        "not handle", activation.get("activation_id"), stage,
                    )
                    queue.report(
                        activation.get("activation_id"), outcome="blocked",
                        payload={"reason": f"unsupported stage {stage!r}"},
                    )
                else:
                    execute_activation(requests, client, activation)

        swarm_control.write_status(AGENT_IDENTITY)

        wait = POLL_SECONDS

        if queue is not None:
            wait = max(wait, getattr(queue, "retry_after", 0.0), queue.backoff.current)

        time.sleep(wait)

    instance.release()
    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
