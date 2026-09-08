"""Poll an agent hub for messages addressed to ChatGPT and answer them.

Sibling of ``claude_worker.py`` and deliberately built to match it: same hub
(default ``http://192.168.42.50:8050``), same confirmed message schema, same
state-file de-duplication, same resilient poll loop and graceful shutdown.
The one structural difference is what it does with a message -- it calls the
OpenAI Chat Completions API rather than a local CLI.

Trust boundary -- narrower than the Claude worker's
---------------------------------------------------

This daemon does NOT execute anything on this machine. It reads messages,
sends conversation text to OpenAI, and posts the model's reply back. So the
remote-code-execution surface the Claude worker carries is absent here. Two
things are still worth stating plainly:

* **Hub content leaves the LAN.** Everything the agents post that lands in
  the context window is sent to the OpenAI API to generate each reply. That
  is inherent to the task, not a leak, but it is where the data goes.
* **It acts autonomously and can enter a conversational loop.** The trigger
  includes any message whose *content* mentions ``@ChatGPT``, not only ones
  targeted at it, so a reply that quotes ``@ChatGPT`` -- or another agent's
  message that does -- can prompt another answer. The one structural brake
  is that it never answers its own messages (``sender == "ChatGPT"`` is
  skipped). A busy swarm can still ping-pong; ``POLL_SECONDS`` and the
  de-dup-by-id state file bound the rate, not the total.

The API key
-----------

``OPENAI_API_KEY`` is read from the environment by the OpenAI SDK itself and
is never logged, echoed, or posted to the hub. Startup logs only whether a
key is present, not its value.

Hub schema (confirmed, shared with claude_worker.py)
----------------------------------------------------

* ``GET /messages`` returns a bare JSON **list** of objects with ``id``,
  ``sender``, ``target``, ``content`` and ``timestamp``.
* ``POST /send`` takes ``sender``, ``target`` and ``content``.

``timestamp`` is unused here; de-duplication is by ``id``.
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

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")
HUB_TOKEN = os.environ.get("HUB_TOKEN")

# Who this worker is and answers for.
SENDER_NAME = "ChatGPT"
# Compared case-insensitively with a leading '@' stripped, against a
# message's target and against '@name' mentions in its content.
SELF_HANDLES = {"chatgpt"}

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "chatgpt_worker.state"
LOG_FILE = HERE / "chatgpt_worker.log"

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))
OPENAI_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "120"))

# How many recent hub messages to send as context on each reply. Capped so
# a long-lived hub does not grow the request without bound. The ceiling is
# hard -- an operator raising CONTEXT_WINDOW in the environment cannot push
# it past CONTEXT_WINDOW_CEILING, since an unbounded window is exactly the
# runaway-usage risk this setting exists to prevent.
CONTEXT_WINDOW_CEILING = 20
_requested_context_window = int(os.environ.get("CONTEXT_WINDOW", "20"))
CONTEXT_WINDOW = min(_requested_context_window, CONTEXT_WINDOW_CEILING)

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


def is_for_chatgpt(message: dict) -> bool:
    """Whether this worker should answer `message`.

    True when the target is @ChatGPT, or when the content mentions
    ``@ChatGPT`` -- both per the requested trigger. A message this worker
    sent itself is never a trigger: that is the one structural brake on the
    content-mention rule feeding the swarm's own output back in.
    """
    sender = message.get("sender")
    if isinstance(sender, str) and sender.strip().lstrip("@").lower() in (
        SELF_HANDLES
    ):
        return False

    target = message.get("target")
    if isinstance(target, str) and (
        target.strip().lstrip("@").lower() in SELF_HANDLES
    ):
        return True

    content = message.get("content")
    if isinstance(content, str):
        lowered = content.lower()
        if any(f"@{handle}" in lowered for handle in SELF_HANDLES):
            return True

    return False


def token_ok(message: dict) -> bool:
    """Whether `message` carries the shared secret, when one is configured.

    No token configured means every message is accepted -- the default,
    matching the hub's current open posture.
    """
    if not HUB_TOKEN:
        return True

    return str(message.get("token", "")) == HUB_TOKEN


# --- reply governor: a brake on the swarm's self-driving loop -------------
#
# The answering workers trigger on @-mentions and address one another, so
# left unchecked they ping-pong indefinitely, each turn a paid API call. Two
# limits bound it, both checked BEFORE the model call so a suppressed turn is
# free:
#
#   * per-sender COOLDOWN -- after replying to X, ignore X again for
#     REPLY_COOLDOWN_SECONDS. The direct brake on an A<->B loop.
#   * rolling burst CAP -- at most MAX_REPLIES_PER_WINDOW replies in any
#     REPLY_WINDOW_SECONDS, across all agents. The backstop for when several
#     peers drive this one worker at once.
#
# Only automated peers are throttled; a human operator (Admin, anyone not in
# AGENT_HANDLES) is never suppressed, so the operator can always be heard.
# The three env knobs are shared by name with the sibling workers, so one
# setting governs the whole swarm. To restore always-answer:
# REPLY_COOLDOWN_SECONDS=0 with a large MAX_REPLIES_PER_WINDOW.
REPLY_COOLDOWN_SECONDS = float(os.environ.get("REPLY_COOLDOWN_SECONDS", "45"))
MAX_REPLIES_PER_WINDOW = int(os.environ.get("MAX_REPLIES_PER_WINDOW", "8"))
REPLY_WINDOW_SECONDS = float(os.environ.get("REPLY_WINDOW_SECONDS", "300"))

AGENT_HANDLES = {"gemini", "chatgpt", "claudecode", "claude"}

# Module-level: the poll loop is single-threaded, so handle() completes
# before the next message and there is no concurrent mutation.
_recent_actions: list[float] = []
_last_action_by_sender: dict[str, float] = {}


def _sender_key(sender: str) -> str:
    return sender.strip().lstrip("@").lower()


def is_automated(sender: str) -> bool:
    """Whether `sender` is a peer worker rather than a human."""
    return _sender_key(sender) in AGENT_HANDLES


# --- verification gate: a stop on the swarm running unattended too long ----
#
# The cooldown and burst cap above slow an agent-to-agent loop; they do not
# stop it -- a swarm well under both limits can still run for hours without
# a human ever weighing in. This counts consecutive hub messages from
# AGENT_HANDLES senders, across every message this worker observes (not only
# ones addressed to it, since the loop this guards against can hop between
# any of the three workers). Any message from outside AGENT_HANDLES resets
# the count and clears a pending pause: a human turn is exactly what this
# gate is waiting for.
CONSECUTIVE_AGENT_LIMIT = int(os.environ.get("CONSECUTIVE_AGENT_LIMIT", "5"))

_consecutive_agent_exchanges = 0
_verification_pending = False


def observe_sender(sender: str) -> None:
    """Update the verification gate's counter for one observed hub message.

    Call this for every message the poll returns, whether or not it is
    addressed to this worker, so the count reflects the whole hub's traffic.
    """
    global _consecutive_agent_exchanges, _verification_pending

    if is_automated(sender):
        _consecutive_agent_exchanges += 1
    else:
        _consecutive_agent_exchanges = 0
        _verification_pending = False


def verification_needed() -> bool:
    """Whether the gate has just tripped and no alert has been sent for it."""
    return (
        _consecutive_agent_exchanges >= CONSECUTIVE_AGENT_LIMIT
        and not _verification_pending
    )


def trip_verification_gate() -> None:
    """Record that the verification alert has been sent for this run."""
    global _verification_pending
    _verification_pending = True


def suppression_reason(sender: str) -> str | None:
    """Why this worker should stay quiet for `sender` now, or None to answer.

    A human operator is never throttled (see AGENT_HANDLES). Records nothing
    beyond pruning the rolling window, so deciding NOT to answer costs no
    budget: call `record_action()` only after actually answering.
    """
    if _sender_key(sender) not in AGENT_HANDLES:
        return None

    now = time.monotonic()

    cutoff = now - REPLY_WINDOW_SECONDS
    while _recent_actions and _recent_actions[0] < cutoff:
        _recent_actions.pop(0)

    last = _last_action_by_sender.get(_sender_key(sender))
    if last is not None and (now - last) < REPLY_COOLDOWN_SECONDS:
        return (
            f"cooling down on {sender} "
            f"({REPLY_COOLDOWN_SECONDS - (now - last):.0f}s left)"
        )

    if len(_recent_actions) >= MAX_REPLIES_PER_WINDOW:
        return (
            f"rate cap reached ({MAX_REPLIES_PER_WINDOW} replies in "
            f"{REPLY_WINDOW_SECONDS:.0f}s)"
        )

    return None


def record_action(sender: str) -> None:
    """Record that this worker answered `sender`, feeding the limits above."""
    now = time.monotonic()
    _recent_actions.append(now)
    _last_action_by_sender[_sender_key(sender)] = now


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


def fetch_recent(requests: Any, limit: int) -> list[dict]:
    """The tail of the hub's message log, for conversation context.

    Fetched fresh from ``since_id=0`` each time a reply is built rather than
    accumulated in memory, so a restart reconstructs context identically.
    Only the last `limit` are kept, bounding the request size on a long-run
    hub.
    """
    messages = fetch_messages(requests, 0)
    return messages[-limit:] if limit > 0 else messages


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

    payload = {
        "sender": SENDER_NAME,
        "target": target,
        "content": body,
    }

    if HUB_TOKEN:
        payload["token"] = HUB_TOKEN

    try:
        response = requests.post(
            f"{HUB_URL}/send", json=payload, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("failed to post reply for message %s: %s", message_id, exc)


def reply_target_for(message: dict) -> str:
    """Address the reply back to whoever sent the triggering message.

    Falls back to the hub-wide default if a sender is somehow missing, so a
    malformed trigger still gets an answer somewhere rather than crashing.
    """
    sender = message.get("sender")

    if isinstance(sender, str) and sender.strip():
        return "@" + sender.strip().lstrip("@")

    return "@Admin"


def handle(requests: Any, client: Any, message: dict) -> None:
    message_id = message.get("id")
    sender = message.get("sender") or "unknown"

    if not token_ok(message):
        log.warning(
            "REFUSED message %s from %s: bad or missing token",
            message_id,
            sender,
        )
        return

    if verification_needed():
        log.warning(
            "VERIFICATION GATE tripped: %d consecutive agent-only exchanges "
            "with no human input; alerting @Admin and going quiet",
            _consecutive_agent_exchanges,
        )
        post_reply(
            requests,
            "@Admin",
            f"{_consecutive_agent_exchanges} consecutive agent-only "
            "exchanges on the hub with no human input -- pausing replies "
            "to automated peers until you weigh in.",
            message_id,
        )
        trip_verification_gate()
        return

    if _verification_pending:
        # Already alerted for this run; stay quiet rather than repeat the
        # alert on every subsequent agent message until a human message
        # resets the gate via observe_sender().
        log.info(
            "SUPPRESSED message %s from %s: verification gate pending",
            message_id,
            sender,
        )
        return

    reason = suppression_reason(sender)
    if reason is not None:
        # Suppressed before the model call, so a throttled turn costs no API
        # request and posts no reply -- the reply is what re-triggers a peer.
        log.info(
            "SUPPRESSED message %s from %s: %s", message_id, sender, reason
        )
        return

    # Booked before generation on purpose: a failed or empty call still
    # spent an API request and should count against the cap, and a peer that
    # keeps failing should trip the cooldown rather than be retried on every
    # poll.
    record_action(sender)

    log.info("ANSWERING message %s from %s", message_id, sender)

    context = fetch_recent(requests, CONTEXT_WINDOW)

    started = time.monotonic()
    reply = generate_reply(client, context)
    elapsed = time.monotonic() - started

    if reply is None:
        # generate_reply already logged the cause. Posting an error string
        # would put "[ChatGPT worker: ...]" on the hub as if it were an
        # answer, and peers would reply to it -- a transient failure becoming
        # a conversation. Silence is the honest thing to post.
        log.warning(
            "NO REPLY for message %s from %s after %.1fs; nothing posted",
            message_id,
            sender,
            elapsed,
        )
        return

    target = reply_target_for(message)
    log.info(
        "REPLIED to message %s -> %s (%d chars) in %.1fs",
        message_id,
        target,
        len(reply),
        elapsed,
    )

    post_reply(requests, target, reply, message_id)


def main() -> int:
    configure_logging()

    requests, OpenAI = ensure_dependencies()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error(
            "OPENAI_API_KEY is not set; nothing can be generated. Set it in "
            "the environment and restart."
        )
        return 1

    # The SDK reads OPENAI_API_KEY from the environment itself; the key is
    # never handled, logged, or posted by this script.
    client = OpenAI(timeout=OPENAI_TIMEOUT)

    log.info("hub        : %s", HUB_URL)
    log.info("model      : %s", OPENAI_MODEL)
    log.info("openai_key : present")
    log.info(
        "hub auth   : %s",
        "shared token required" if HUB_TOKEN else "NONE (any sender accepted)",
    )
    log.info(
        "verify gate: pause after %d consecutive agent-only exchanges",
        CONSECUTIVE_AGENT_LIMIT,
    )
    if _requested_context_window > CONTEXT_WINDOW_CEILING:
        log.warning(
            "CONTEXT_WINDOW=%d requested, clamped to hard ceiling %d",
            _requested_context_window,
            CONTEXT_WINDOW_CEILING,
        )

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

    while running:
        for message in fetch_messages(requests, last_seen_id):
            raw_id = message.get("id")

            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                log.error("message with unusable id %r; skipping", raw_id)
                continue

            # Advanced before handling, not after: a message that crashes
            # the worker must not be retried forever on every restart.
            if message_id > last_seen_id:
                last_seen_id = message_id
                save_last_seen_id(last_seen_id)

            # Fed to the verification gate regardless of target: the loop it
            # guards against can hop between any of the three workers, so a
            # message not addressed here still counts toward it.
            observe_sender(str(message.get("sender") or "unknown"))

            if is_for_chatgpt(message):
                handle(requests, client, message)

        time.sleep(POLL_SECONDS)

    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
