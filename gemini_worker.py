"""Poll an agent hub for messages addressed to Gemini and answer them.

Third sibling of ``claude_worker.py`` and ``chatgpt_worker.py``, built to
match them: same hub (default ``http://192.168.42.50:8050``), same confirmed
message schema, same state-file de-duplication, same resilient poll loop and
graceful shutdown. It calls Google's Gemini API to generate each reply.

Trust boundary -- like the ChatGPT worker, narrower than the Claude worker's
----------------------------------------------------------------------------

This daemon does NOT execute anything on this machine: it reads messages,
sends conversation text to the Gemini API, and posts the model's reply back.
Two standing caveats, the second sharper now that three answering workers
are in play:

* **Hub content leaves the LAN.** Everything in the context window is sent
  to the Gemini API to generate each reply. Inherent to the task; stated so
  it is not a surprise.
* **The swarm can drive itself.** With Gemini, ChatGPT and ClaudeCode all
  triggering on ``@``-mentions and all referencing one another, a single
  message can set off an unbounded round of replies with no human in the
  loop -- each one a paid API call. Three brakes now apply, in order of
  bluntness:

  1. This worker never answers its own messages (``sender == "Gemini"`` is
     skipped). That stops a self-loop, but not a Gemini -> ChatGPT ->
     Gemini ping-pong.
  2. A per-sender **cooldown** (``REPLY_COOLDOWN_SECONDS``): at most one
     reply to any given automated peer per cooldown period.
  3. A swarm-wide **burst cap** (``MAX_REPLIES_PER_WINDOW`` per
     ``REPLY_WINDOW_SECONDS``): once tripped, this worker stops answering
     automated peers until the window drains.

  Both new brakes apply only to senders in ``AGENT_HANDLES``. Messages from
  a human (``@Admin``, or anyone else not listed) are always answered, so
  throttling can never lock the operator out of their own swarm. A
  throttled message is dropped silently rather than answered with a "rate
  limited" notice -- posting anything at all would be another turn of the
  same loop.

The API key
-----------

``GEMINI_API_KEY`` is read from the environment and handed to the SDK
client. It is never logged, echoed, or posted to the hub; startup logs only
that a key is present.

Hub schema (confirmed, shared across the workers)
-------------------------------------------------

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
from collections import deque
from pathlib import Path
from typing import Any

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")
HUB_TOKEN = os.environ.get("HUB_TOKEN")

# Who this worker is and answers for.
SENDER_NAME = "Gemini"
# Compared case-insensitively with a leading '@' stripped, against a
# message's target and against '@name' mentions in its content.
SELF_HANDLES = {"gemini"}

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "gemini_worker.state"
LOG_FILE = HERE / "gemini_worker.log"

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))

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

# Senders treated as automated peers, and so subject to the loop brakes
# below. Compared case-insensitively with a leading '@' stripped. Anyone not
# listed -- notably the human Admin -- is never throttled.
AGENT_HANDLES = {
    handle.strip().lstrip("@").lower()
    for handle in os.environ.get(
        "AGENT_HANDLES", "gemini,chatgpt,claudecode"
    ).split(",")
    if handle.strip()
}

# Minimum seconds between replies to the same automated peer. This is the
# brake on a two-worker ping-pong: it does not stop the exchange, it slows
# it to a rate a human can notice and interrupt.
REPLY_COOLDOWN_SECONDS = float(os.environ.get("REPLY_COOLDOWN_SECONDS", "60"))

# Ceiling on replies to automated peers within a rolling window, counted
# across all of them. This is the brake on a multi-worker storm, where each
# peer stays individually under its cooldown but the swarm as a whole does
# not. Set MAX_REPLIES_PER_WINDOW to 0 to refuse automated peers entirely.
MAX_REPLIES_PER_WINDOW = int(os.environ.get("MAX_REPLIES_PER_WINDOW", "10"))
REPLY_WINDOW_SECONDS = float(os.environ.get("REPLY_WINDOW_SECONDS", "600"))

# --- verification gate: a stop on the swarm running unattended too long ----
#
# The cooldown and burst cap above slow an agent-to-agent loop; they do not
# stop it -- a swarm well under both limits can still run for hours without
# a human ever weighing in. This counts consecutive hub messages from
# AGENT_HANDLES senders, across every message this worker observes (not only
# ones addressed to it, since the loop this guards against can hop between
# any of the three workers and this worker would otherwise undercount it).
# Any message from outside AGENT_HANDLES -- an operator, or an unknown
# sender -- resets the count and clears a pending pause: a human turn is
# exactly what this gate is waiting for.
CONSECUTIVE_AGENT_LIMIT = int(os.environ.get("CONSECUTIVE_AGENT_LIMIT", "5"))

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


def is_for_gemini(message: dict) -> bool:
    """Whether this worker should answer `message`.

    True when the target is @Gemini, or when the content mentions
    ``@Gemini``. A message this worker sent itself is never a trigger --
    the one structural brake on the content-mention rule feeding this
    worker's own output back in.
    """
    sender = message.get("sender")
    if isinstance(sender, str) and (
        sender.strip().lstrip("@").lower() in SELF_HANDLES
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
    Only the last `limit` are kept, bounding the request size.
    """
    messages = fetch_messages(requests, 0)
    return messages[-limit:] if limit > 0 else messages


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


def normalize_handle(name: str) -> str:
    """A sender name reduced to its comparable form."""
    return name.strip().lstrip("@").lower()


def is_automated(sender: str) -> bool:
    """Whether `sender` is a peer worker rather than a human.

    Only automated peers are throttled: a loop needs two machines in it, and
    a brake that could silence the human operator would be worse than the
    loop it prevents.
    """
    return normalize_handle(sender) in AGENT_HANDLES


# Verification-gate state, in-memory like the throttle bookkeeping above: a
# restart is an operator action and should clear it, the same way restarting
# clears a stuck cooldown.
_consecutive_agent_exchanges = 0
_verification_pending = False


def observe_sender(sender: str) -> None:
    """Update the verification gate's counter for one observed hub message.

    Call this for every message the poll returns, whether or not it is
    addressed to this worker -- the count is meant to reflect the whole
    hub's traffic, not just this worker's own turns.
    """
    global _consecutive_agent_exchanges, _verification_pending

    if is_automated(sender):
        _consecutive_agent_exchanges += 1
    else:
        _consecutive_agent_exchanges = 0
        _verification_pending = False


def verification_needed() -> bool:
    """Whether the gate has just tripped and no alert has been sent for it.

    False once `trip_verification_gate()` has been called for this run of
    consecutive exchanges, so the alert is sent once, not on every message
    while the swarm keeps talking to itself.
    """
    return (
        _consecutive_agent_exchanges >= CONSECUTIVE_AGENT_LIMIT
        and not _verification_pending
    )


def trip_verification_gate() -> None:
    """Record that the verification alert has been sent for this run."""
    global _verification_pending
    _verification_pending = True


def throttle_reason(sender: str, now: float) -> str | None:
    """Why a message from `sender` must go unanswered, or None to answer it.

    Deliberately state-in-memory rather than persisted: a restart is an
    operator action, and an operator restarting the worker to clear a stuck
    throttle should get exactly that.
    """
    if not is_automated(sender):
        return None

    handle = normalize_handle(sender)

    last = _last_reply_at.get(handle)
    if last is not None and now - last < REPLY_COOLDOWN_SECONDS:
        return (
            f"cooldown -- last reply to {handle} was {now - last:.0f}s ago, "
            f"minimum is {REPLY_COOLDOWN_SECONDS:.0f}s"
        )

    while _recent_replies and now - _recent_replies[0] >= REPLY_WINDOW_SECONDS:
        _recent_replies.popleft()

    if len(_recent_replies) >= MAX_REPLIES_PER_WINDOW:
        return (
            f"burst cap -- {len(_recent_replies)} replies to agents in the "
            f"last {REPLY_WINDOW_SECONDS:.0f}s, limit is "
            f"{MAX_REPLIES_PER_WINDOW}"
        )

    return None


def record_reply(sender: str, now: float) -> None:
    """Book a reply to `sender` against both brakes.

    Called at the moment this worker commits to answering, not after the
    reply lands: a generation that fails or a post that the hub rejects has
    still consumed an API call, and must still count against the cap.
    """
    if not is_automated(sender):
        return

    _last_reply_at[normalize_handle(sender)] = now
    _recent_replies.append(now)


def handle(requests: Any, client: Any, types: Any, message: dict) -> None:
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

    started = time.monotonic()

    reason = throttle_reason(str(sender), started)
    if reason is not None:
        # Dropped without a reply on purpose: answering "I am rate limited"
        # would be one more turn of the loop being braked.
        log.info(
            "THROTTLED message %s from %s: %s", message_id, sender, reason
        )
        return

    record_reply(str(sender), started)

    log.info("ANSWERING message %s from %s", message_id, sender)

    context = fetch_recent(requests, CONTEXT_WINDOW)

    reply = generate_reply(client, types, context)
    elapsed = time.monotonic() - started

    if reply is None:
        # generate_reply has already logged the specific cause. The reply was
        # booked against the throttle before generation on purpose (see
        # record_reply): a failed call still spent an API request.
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

    requests, genai, types = ensure_dependencies()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.error(
            "GEMINI_API_KEY is not set; nothing can be generated. Set it in "
            "the environment and restart."
        )
        return 1

    # The key is passed to the client and never logged or posted.
    client = genai.Client(api_key=api_key)

    log.info("hub        : %s", HUB_URL)
    log.info("model      : %s", GEMINI_MODEL)
    log.info("gemini_key : present")
    log.info(
        "hub auth   : %s",
        "shared token required" if HUB_TOKEN else "NONE (any sender accepted)",
    )
    log.info("agents     : %s", ", ".join(sorted(AGENT_HANDLES)) or "none")
    log.info(
        "throttle   : %.0fs cooldown per agent, max %d replies per %.0fs",
        REPLY_COOLDOWN_SECONDS,
        MAX_REPLIES_PER_WINDOW,
        REPLY_WINDOW_SECONDS,
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

            if is_for_gemini(message):
                handle(requests, client, types, message)

        time.sleep(POLL_SECONDS)

    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
