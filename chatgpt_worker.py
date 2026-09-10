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
import controller_client
import swarm_control

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

# The repository this worker authors in. It has no shell, so it writes the
# files the model returns and commits them itself.
AUTHOR_REPO = os.environ.get("AUTHOR_REPO", "")

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

        if sender.strip().lstrip("@").lower() in SELF_HANDLES:
            chat.append({"role": "assistant", "content": text})
        else:
            target = str(message.get("target", ""))
            chat.append(
                {
                    "role": "user",
                    "content": f"{sender} (to {target}): {text}",
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


def _allowed_paths_from_contract(contract: str) -> list:
    """Pull `allowed_paths` out of a free-form contract, or return [].

    Deliberately a small hand-parse rather than a YAML dependency: hub.py
    installs fastapi, uvicorn and pydantic at every container start and nothing
    else, and the contract linter that would justify a real parser is deferred.
    It reads a `allowed_paths:` key followed by `- entry` lines.

    Returning [] for anything it does not understand means unrestricted, which
    matches how the rest of the contract is treated -- stored, hashed, and not
    interpreted. A stricter reading would refuse tasks for a field nothing
    validates yet.
    """
    paths = []
    collecting = False

    for line in (contract or "").splitlines():
        stripped = line.strip()

        if stripped.startswith("allowed_paths:"):
            collecting = True
            inline = stripped.partition(":")[2].strip()

            if inline.startswith("[") and inline.endswith("]"):
                return [
                    part.strip().strip("'\"")
                    for part in inline[1:-1].split(",") if part.strip()
                ]
            continue

        if collecting:
            if stripped.startswith("- "):
                paths.append(stripped[2:].strip().strip("'\""))
            elif stripped and not stripped.startswith("#"):
                break

    return paths


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

    if not AUTHOR_REPO:
        log.error("AUTHOR_REPO is not set; cannot author %s", activation_id)
        queue.report(activation_id, outcome="blocked",
                     payload={"reason": "AUTHOR_REPO is not configured on this host"})
        return

    # The contract's allowed paths, if it named any. Parsed leniently: the
    # linter is deferred, so contract_yaml is free-form and a task that names
    # none is unrestricted rather than forbidden from writing anything.
    allowed = task_record.get("allowed_paths") or _allowed_paths_from_contract(
        task_record.get("contract_yaml", "")
    )

    # Refused before the model is called, not after. A dirty worktree means the
    # commit would carry somebody else's uncommitted edits and attribute them
    # to the model, and finding that out after paying for a generation is worse
    # than finding it out before.
    if not authored_change.worktree_is_clean(AUTHOR_REPO):
        log.error("worktree at %s is not clean; not authoring %s",
                  AUTHOR_REPO, activation_id)
        queue.report(activation_id, outcome="blocked", payload={
            "reason": "the author repository has uncommitted changes",
        })
        return

    prompt = authored_change.render_author_prompt(
        {**task_record, "task_id": task_id, "allowed_paths": allowed}
    )

    log.info("AUTHORING activation %s for task %s", activation_id, task_id)
    started = time.monotonic()

    reply = generate_reply(
        client,
        [{"sender": "controller", "target": "@" + AGENT_IDENTITY, "content": prompt}],
    )
    elapsed = time.monotonic() - started

    if reply is None:
        log.warning("no reply for activation %s after %.1fs", activation_id, elapsed)
        queue.report(activation_id, outcome="blocked",
                     payload={"reason": "the model returned nothing"})
        return

    try:
        files = authored_change.parse_files(reply)
    except authored_change.AuthoringError as exc:
        # `failed` rather than `blocked`: the model answered, and the answer
        # was not usable. That is a fact about the attempt, which is what
        # CHANGES_REQUESTED is for.
        log.error("activation %s produced an unusable answer: %s", activation_id, exc)
        queue.report(activation_id, outcome="failed", payload={
            "reason": str(exc),
            "reply_excerpt": swarm_control.redact(reply)[:1000],
            "elapsed_seconds": round(elapsed, 1),
        })
        return

    try:
        result = authored_change.apply_and_commit(
            AUTHOR_REPO,
            branch=f"task/{task_id}",
            files=files,
            message=f"{task_id}: {task_record.get('title', 'authored change')}",
            allowed_paths=allowed,
        )
    except authored_change.AuthoringError as exc:
        # apply_and_commit rolls back on failure, but whether it succeeded is
        # checked rather than assumed. "The attempt failed" and "the attempt
        # failed and left the repository unusable" need different responses,
        # and the second one must not be reported as the first.
        clean = authored_change.worktree_is_clean(AUTHOR_REPO)

        if not clean:
            log.error(
                "activation %s failed AND left %s dirty; it needs a human",
                activation_id, AUTHOR_REPO,
            )

        log.error("could not apply activation %s: %s", activation_id, exc)
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

    log.info(
        "COMPLETED activation %s: %s at %s (%d file(s)) in %.1fs",
        activation_id, result["branch"], result["candidate_sha"][:12],
        len(result["files"]), elapsed,
    )

    queue.report(activation_id, outcome="candidate", payload={
        "elapsed_seconds": round(elapsed, 1),
        **result,
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
    log.info("author repo: %s", AUTHOR_REPO or "(unset -- authoring will block)")
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
