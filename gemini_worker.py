"""Answer operator-issued activations with the Gemini API, and narrate to the hub.

Third sibling of ``claude_worker.py`` and ``chatgpt_worker.py``, built to match
them: same hub (default ``http://192.168.42.50:8050``), same confirmed message
schema, same state-file de-duplication, same poll loop and graceful shutdown,
and the same Phase 0 containment. It calls Google's Gemini API to generate each
reply.

Trust boundary
--------------

This daemon does not execute anything on this machine, so it never carried the
Claude worker's remote-code-execution surface. It carried a different one.

Before Phase 0, Gemini, ChatGPT and ClaudeCode all triggered on ``@``-mentions
and all addressed one another, so a single message could set off an unbounded
round of replies with no human in the loop -- each one a paid API call. That
was braked by a per-sender cooldown, a swarm-wide burst cap and a stop after N
agent-only exchanges: three advisory, in-memory limits, all cleared by a
restart. None of them was a boundary. Any hub client could still spend this
account's budget by posting the substring ``@gemini``, without authenticating.

The loop is now prevented rather than braked:

* **Chat cannot start anything.** Not by ``target``, not by ``@mention``, not
  from any sender. Messages are fetched and recorded to the local narration log
  so they stay readable; they carry no authority.
* **Prompts come from the local control directory** (see ``swarm_control``),
  which the hub cannot reach, and from nowhere else. No hub content reaches the
  model now that ``fetch_recent()`` is gone -- narration is written to disk for
  a human to read, never routed back into a model.
* **The pause flag is checked before each claim.**
* **Identity is bound from local configuration** and never adopted from an
  inbound message.
* Replies are addressed to ``@Admin``, never to a peer worker. That single
  change removes the return leg the brakes existed to slow down.

**Hub content still leaves the LAN** when an operator's activation text is sent
to the Gemini API. That is inherent to the task; it is now bounded by what the
operator wrote rather than by whatever happened to be on the stream.

The API key
-----------

``GEMINI_API_KEY`` is read from the environment only -- there is no file
fallback, and ``.env*`` is excluded from version control so it cannot be
committed. It is validated at startup through ``swarm_control.load_credential``
so a blank or placeholder value is refused here rather than surfacing as a 401
much later, and the refusal never carries the value: a key that reaches a log
has to be treated as exposed and rotated. Startup logs only that a key is
present.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import swarm_control

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")

# Bound from local configuration and never adopted from an inbound message.
# `sender` is free text on an unauthenticated hub, so reading an identity out
# of a message would let any writer decide who this process claims to be.
AGENT_IDENTITY = swarm_control.bind_identity(
    os.environ.get("AGENT_IDENTITY", "gemini")
)

# Retained only so the narration log and the operator CLI can still recognise
# this worker's own handle. It is no longer compared against message targets
# or against '@name' mentions, because neither can start work any more.
SELF_HANDLES = {"gemini"}

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "gemini_worker.state"
LOG_FILE = HERE / "gemini_worker.log"

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))

# Replies are truncated so a very long model answer cannot wedge the hub or
# the transport.
MAX_REPLY_CHARS = 60_000

SYSTEM_PROMPT = (
    "You are Gemini, the lead architect in a small multi-agent engineering "
    "swarm that coordinates over a shared message hub. The other "
    "participants include ClaudeCode (local execution and testing), ChatGPT "
    "(static drafting and GitHub), and a human Admin. You are addressed as "
    "@Gemini. The text below is the recent hub conversation, each line "
    "labelled with who sent it and to whom. Reply as Gemini with a single, "
    "direct message suitable for posting back to the hub -- no role-play of "
    "other agents, and no @-prefix on your own name."
)

# The context-window clamp, the AGENT_HANDLES set, the throttle values and
# the verification-gate limit that used to sit here are gone with the code
# that read them. The clamp bounded how much untrusted hub history was pasted
# into each prompt, and no hub history reaches the model any more; the rest
# configured brakes on a chat-driven loop that can no longer form.

log = logging.getLogger("gemini_worker")

# Loop-brake bookkeeping, in monotonic seconds: when this worker last
# replied to each automated peer, and every reply to any of them still
# inside the burst window.
_last_reply_at: dict[str, float] = {}
_recent_replies: deque[float] = deque()


def ensure_dependencies() -> tuple[Any, Any, Any]:
    """Import ``requests`` and the Gemini SDK, installing once if missing.

    Returns ``(requests_module, genai_module, genai_types)``. Installation
    is a side effect worth being explicit about, so it happens at most once,
    says what it is doing, and gives up with an actionable message rather
    than looping.
    """
    missing: list[str] = []

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        from google import genai  # noqa: F401
    except ImportError:
        # The distribution is 'google-genai'; the import is 'google.genai'.
        missing.append("google-genai")

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
    from google import genai
    from google.genai import types

    return requests, genai, types


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


# is_for_gemini() and token_ok() are gone rather than tightened.
#
# is_for_gemini() started a model call whenever a message's target named this
# worker OR the substring "@gemini" appeared anywhere in its content, so any
# hub client -- including another agent quoting the handle in passing -- could
# spend this account's budget without authenticating. token_ok() compared an
# inbound `token` field that the hub never returns on GET /messages, so it
# could refuse traffic but never admit it.
#
# Both read fields off an unauthenticated stream, so neither could be repaired
# where it stood. Whether a message may start work is now answered in one
# place, for all three workers, by swarm_control.chat_message_activates().
# It returns False.


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
# prompt, so untrusted stream content -- written by anyone able to POST to an
# unauthenticated hub -- was fed to the model as context on every turn. The
# prompt now comes from the activation and nothing else. Narration is recorded
# to disk for a human to read, not routed back into a model.


def build_transcript(context: list[dict]) -> str:
    """Render recent hub messages as one labelled transcript.

    A single labelled block rather than a role-tagged turn list: the hub is
    a multi-party thread (Admin, Gemini, ChatGPT, ClaudeCode), which does
    not fit Gemini's two-role user/model contents cleanly, and a leading or
    repeated 'model' turn can be rejected outright. A transcript sidesteps
    the role-ordering rules while keeping who-said-what explicit, and the
    speaker identity is what actually matters to the model here.
    """
    lines: list[str] = []

    for message in context:
        text = message_content(message)
        if text is None:
            continue

        sender = str(message.get("sender", "unknown"))
        target = str(message.get("target", ""))
        lines.append(f"{sender} (to {target}): {text}")

    return "\n".join(lines)


def generate_reply(
    client: Any,
    types: Any,
    context: list[dict],
) -> str | None:
    """Ask the model for one reply, or None if there is nothing to say.

    Any SDK/API failure is caught rather than propagated -- one failed
    generation must not kill the daemon -- but it is recorded *here*, in
    this worker's log, and not returned as text.

    Returning an error string would have posted it to the hub as an ordinary
    Gemini reply, indistinguishable from a real answer: peers then read "[Gemini
    worker: generation failed: ...]" as content and respond to it, so a
    transient 429 becomes a conversation. An outage is an operator's problem,
    visible in the log; silence is the honest thing to put on the hub.
    """
    transcript = build_transcript(context)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=transcript,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
            ),
        )
    except Exception as exc:
        # exc_info, because the message alone loses which SDK call failed --
        # and this is now the only record of the failure anywhere.
        log.error("Gemini request failed: %s", exc, exc_info=True)
        return None

    # response.text is None when the model returns no text part (e.g. a
    # safety block); treat that as an empty reply rather than crashing on
    # .strip().
    reply = (response.text or "").strip()

    if not reply:
        log.warning("Gemini returned an empty reply; nothing to post")
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
            f"{HUB_URL}/send", json=payload, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("failed to post reply for message %s: %s", message_id, exc)


# reply_target_for() is removed. It addressed each reply back at whoever sent
# the triggering message, so a message from a peer produced a reply aimed at
# that peer -- the return leg of the loop. Replies now go to @Admin, a constant
# at the one call site rather than a function of untrusted input.


# The throttle and the verification gate that used to sit here have been
# removed, not disabled.
#
# Both bounded a loop in which each worker answered the others' messages: a
# per-sender cooldown, a swarm-wide burst cap, and a stop after N consecutive
# agent-only exchanges. All three were advisory, in-memory and cleared by a
# restart, and all three are now unreachable -- chat cannot start work at all,
# and replies are addressed to @Admin rather than to a peer, so there is no
# exchange left for them to count.
#
# They are deleted rather than left in place because an inert safety gate is
# worse than none: the next reader takes it for the mechanism providing safety,
# when the real reason the loop cannot form is that the trigger is gone. A
# guard that fails nothing when bypassed was never load-bearing.
#
# workspace/throttle_check.py asserted this throttle's behaviour and is retired
# with it; see tests/ for the assertions that replace it.


def execute_activation(
    requests: Any, client: Any, types: Any, activation: dict
) -> None:
    """Answer one operator-issued activation.

    The prompt comes from the local control directory, not from the hub, so the
    model is never invoked because another agent posted a message. The caller
    has already checked the pause flag and won the claim.
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

    # Shaped like a hub message so the existing transcript builder is reused
    # unchanged, but sourced from the activation rather than from the stream.
    context = [
        {
            "sender": activation.get("issued_by", "admin"),
            "target": "@" + AGENT_IDENTITY,
            "content": task,
        }
    ]

    reply = generate_reply(client, types, context)
    elapsed = time.monotonic() - started

    if reply is None:
        # generate_reply has already logged the specific cause.
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

    requests, genai, types = ensure_dependencies()

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
        api_key = swarm_control.load_credential("GEMINI_API_KEY")
    except swarm_control.ContainmentError as exc:
        log.error("%s", exc)
        return 1

    # The key is passed to the client and never logged or posted.
    client = genai.Client(api_key=api_key)

    log.info("hub        : %s", HUB_URL)
    log.info("model      : %s", GEMINI_MODEL)
    log.info("gemini_key : present")
    log.info("identity   : %s (bound locally, never from a message)", AGENT_IDENTITY)
    log.info("activations: %s", swarm_control.ACTIVATIONS_DIR)
    log.info("chat       : narration only; it cannot start work")
    log.info("identity   : %s (bound locally, never from a message)", AGENT_IDENTITY)
    log.info("activations: %s", swarm_control.ACTIVATIONS_DIR)
    log.info("chat       : narration only; it cannot start work")
    log.info("pause      : %s", swarm_control.pause_reason() or "not paused")

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
            activation = swarm_control.claim_activation(AGENT_IDENTITY)

            if activation is not None:
                execute_activation(requests, client, types, activation)

        swarm_control.write_status(AGENT_IDENTITY)
        time.sleep(POLL_SECONDS)

    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
