"""Poll an agent hub for tasks addressed to Claude Code and execute them.

Bridges a message hub (default ``http://192.168.42.50:8050``) to a local
``claude`` CLI: it long-polls ``/messages``, picks out messages targeted at
this worker, runs each task non-interactively, and posts the result back to
``/send``.

TRUST BOUNDARY -- read this before running
------------------------------------------

This daemon turns the hub into a remote-execution endpoint for this machine.
Every message it accepts is passed to ``claude -p`` with ``Bash``, ``Read``
and ``Edit`` pre-authorized, which is the configuration that never prompts.
Anything able to POST to the hub can therefore run commands as the user
running this script, unattended, for as long as it is up.

That is the requested design and it is a reasonable one on a LAN you control.
Three things narrow the blast radius without changing the protocol:

* ``HUB_TOKEN`` -- if set, a message must carry a matching ``token`` field or
  it is refused and logged. Unset means no authentication, which is the
  default and is stated here rather than left to be discovered.
* ``WORKSPACE`` -- tasks run with this as their working directory, so a task
  that writes relative paths cannot land in whatever directory the daemon
  happened to be started from. It does NOT confine the task: ``Bash`` can
  reach the whole filesystem.
* Every accepted task is appended to ``claude_worker.log`` with its message
  id, sender and exit code, so there is a record of what ran.

The task string is passed to ``subprocess.run`` as a **list element**, never
interpolated into a shell string. A task containing quotes, ``$(...)`` or
``;`` is one argument to ``claude``, not shell syntax. Running this through a
shell would add a second, entirely avoidable injection layer underneath the
one the design already accepts.

Hub schema
----------

Confirmed against the running hub:

* ``GET /messages`` returns a bare JSON **list** of message objects, each
  with ``id``, ``sender``, ``target``, ``content`` and ``timestamp``.
* ``POST /send`` takes ``sender``, ``target`` and ``content``.

Field names are matched exactly. An earlier draft tried several spellings
per field because the host was unreachable when this was written; that
tolerance has been removed now that the shape is known -- carrying it
forward would only be extra ways to silently mis-read a message.
``timestamp`` is present on responses but unused here: de-duplication is by
``id``. A message addressed to us with empty or missing content is logged
whole rather than dropped, because a lost task and an empty one look
identical from the hub's side.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")
HUB_TOKEN = os.environ.get("HUB_TOKEN")

# Targets this worker answers to, compared case-insensitively with any
# leading '@' stripped.
TARGETS = {"claudecode", "claude"}

SENDER_NAME = "ClaudeCode"
REPLY_TARGET = "@Gemini"

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", HERE / "workspace"))
STATE_FILE = HERE / "claude_worker.state"
LOG_FILE = HERE / "claude_worker.log"
HANDOFF_PATH = WORKSPACE / "HANDOFF.md"

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))
TASK_TIMEOUT = float(os.environ.get("TASK_TIMEOUT", "900"))

# --- HANDOFF.md resume protocol --------------------------------------------
#
# Each task is a fresh, one-shot `claude -p` process (see run_task): there is
# no persistent session for a multi-step task to carry state across separate
# hub messages, and TASK_TIMEOUT can cut one off mid-work with nothing to
# show for it. This preamble is prepended to every task's text so the model
# itself -- the only thing that can see its own turn/context budget -- can
# checkpoint a large task into HANDOFF_PATH before it runs out, and a later
# task (triggered by the next hub message continuing the work) picks it back
# up. It costs a small, fixed amount of extra prompt on every task, including
# ones that never need it.
HANDOFF_PREAMBLE = (
    "Before starting, check whether HANDOFF.md exists in the working "
    "directory -- if it does, it is a resume note this same task left "
    "behind on a previous run that ran out of time or turns, and you should "
    "read it first. If this task is large enough that you might not finish "
    "in one run, write or update HANDOFF.md before you stop: state the "
    "objective, what's done, files touched, any blockers, and the exact "
    "next command to run. Once the objective HANDOFF.md describes is fully "
    "done, delete it.\n\nTask: "
)

# --- 5-hour usage guardrail -------------------------------------------------
#
# Anthropic's usage limits are enforced server-side and this worker cannot
# see them directly; what it CAN see is its own wall-clock uptime, which is
# a coarse but honest proxy since every accepted task spends real time
# running `claude -p`. Once continuous uptime crosses the warn threshold,
# new tasks stop being accepted (a task already running is unaffected) and
# the hub gets a single alert. Restarting the process is what clears this,
# matching the "restart to clear a stuck throttle" pattern used elsewhere in
# this swarm.
RATE_LIMIT_WARN_SECONDS = float(
    os.environ.get("RATE_LIMIT_WARN_SECONDS", str(4.5 * 3600))
)

# Replies are truncated so a task that prints a large file cannot wedge the
# hub or the transport.
MAX_REPLY_CHARS = 60_000

# A peer worker's error envelope, e.g. "[Gemini worker: generation failed:
# 429 RESOURCE_EXHAUSTED]" or "[ChatGPT worker: model returned an empty
# reply]". These are status reports about a worker, not instructions, and
# executing one means handing `claude -p` whatever text an upstream API put
# in its error message.
#
# Anchored at the start of the content, so it matches a message that *is* an
# envelope and not one that merely quotes it -- "investigate why [Gemini
# worker: ...] keeps appearing" is a real task and still runs.
ERROR_ENVELOPE_RE = re.compile(r"^\[[^\]\n]{0,80}\bworker\s*:", re.IGNORECASE)

log = logging.getLogger("claude_worker")


def ensure_requests() -> Any:
    """Import ``requests``, installing it once if it is missing.

    Returns the module. Installing from inside a script is a side effect
    worth being explicit about, so it happens exactly once, reports what it
    is doing, and gives up with an actionable message rather than retrying.
    """
    try:
        import requests
    except ImportError:
        print("requests not found; installing into", sys.executable)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "requests"],
            check=False,
        )

        if result.returncode != 0:
            sys.exit(
                "Could not install 'requests' automatically. Install it "
                f"manually with: {sys.executable} -m pip install requests"
            )

        import requests

    return requests


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
    """The task text of `message`, or None if absent or empty.

    Empty string counts as absent: the hub sending ``content: ""`` and
    omitting the field mean the same thing here, and a non-string content
    is treated as absent too, so the caller never has to re-check the type.
    """
    content = message.get("content")

    if isinstance(content, str) and content != "":
        return content

    return None


def load_last_seen_id() -> int:
    """Resume point, so a restart does not replay the whole backlog.

    A corrupt or missing state file resets to 0 rather than crashing. Zero
    means "everything is new", which re-runs history -- noisy, but the
    failure direction that loses no work.
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


def is_for_us(message: dict) -> bool:
    target = message.get("target")

    if not isinstance(target, str):
        return False

    return target.strip().lstrip("@").lower() in TARGETS


def token_ok(message: dict) -> bool:
    """Whether `message` carries the shared secret, when one is configured.

    No token configured means every message is accepted; that is the default
    and the docstring at the top says so.
    """
    if not HUB_TOKEN:
        return True

    return str(message.get("token", "")) == HUB_TOKEN


# --- reply governor: a brake on the swarm's self-driving loop -------------
#
# The answering workers trigger on @-mentions and address one another, so
# left unchecked they ping-pong indefinitely -- and every turn HERE is a
# `claude -p` run with Bash/Edit, not merely a chat message. Two limits
# bound it, both checked BEFORE the task runs so a suppressed turn is free:
#
#   * per-sender COOLDOWN -- after acting on a message from X, ignore X
#     again for REPLY_COOLDOWN_SECONDS. The direct brake on an A<->B loop.
#   * rolling rate CAP -- at most MAX_REPLIES_PER_WINDOW tasks in any
#     REPLY_WINDOW_SECONDS, across all senders. The backstop for when several
#     peers drive this one worker at once.
#
# To restore the old always-run behaviour: REPLY_COOLDOWN_SECONDS=0 and a
# very large MAX_REPLIES_PER_WINDOW.
REPLY_COOLDOWN_SECONDS = float(os.environ.get("REPLY_COOLDOWN_SECONDS", "45"))
MAX_REPLIES_PER_WINDOW = int(os.environ.get("MAX_REPLIES_PER_WINDOW", "8"))
REPLY_WINDOW_SECONDS = float(os.environ.get("REPLY_WINDOW_SECONDS", "300"))

# Only automated peers are throttled. A loop needs two machines in it, and a
# brake that could silence the human operator would be worse than the loop
# it prevents -- the operator has to be able to say "stop" and be heard.
# Anyone not in this set (Admin, an unknown human) is never suppressed.
AGENT_HANDLES = {"gemini", "chatgpt", "claudecode", "claude"}

# Module-level because the poll loop is single-threaded: handle() runs to
# completion before the next message, so there is no concurrent mutation.
_recent_actions: list[float] = []
_last_action_by_sender: dict[str, float] = {}


def _sender_key(sender: str) -> str:
    return sender.strip().lstrip("@").lower()


def suppression_reason(sender: str) -> str | None:
    """Why this worker should stay quiet for `sender` now, or None to act.

    A human operator is never throttled (see AGENT_HANDLES). Apart from
    pruning the rolling window it records nothing, so deciding NOT to act
    consumes no budget: call `record_action()` only after actually acting,
    so a suppressed or failed turn does not count.
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
            f"rate cap reached ({MAX_REPLIES_PER_WINDOW} actions in "
            f"{REPLY_WINDOW_SECONDS:.0f}s)"
        )

    return None


def record_action(sender: str) -> None:
    """Record that this worker acted for `sender`, feeding the limits above."""
    now = time.monotonic()
    _recent_actions.append(now)
    _last_action_by_sender[_sender_key(sender)] = now


# Set once at import, which for this daemon is process start -- there is no
# earlier "first API call" to anchor to, since accepting a task IS the API
# call.
_process_started_at = time.monotonic()
_rate_limit_alert_sent = False


def rate_limit_reason() -> str | None:
    """Why a new task should not be accepted right now, or None to proceed."""
    elapsed = time.monotonic() - _process_started_at

    if elapsed >= RATE_LIMIT_WARN_SECONDS:
        return (
            f"worker uptime {elapsed / 3600:.1f}h has reached the "
            f"{RATE_LIMIT_WARN_SECONDS / 3600:.1f}h warn threshold"
        )

    return None


def record_rate_limit_alert_sent() -> None:
    global _rate_limit_alert_sent
    _rate_limit_alert_sent = True


def run_task(claude_binary: str, task: str) -> tuple[str, int]:
    """Run one task through the Claude CLI and return (output, exit code).

    `task` is a single argv element. It is never concatenated into a shell
    string, so its quoting and metacharacters are inert.

    A timeout returns the partial output with exit code 124, matching
    ``timeout(1)``, so the caller can tell "took too long" from "failed".
    """
    command = [
        claude_binary,
        "-p",
        task,
        "--allowedTools",
        "Bash,Read,Edit",
        "--output-format",
        "text",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            # Decode as UTF-8 with replacement rather than text=True, which
            # on Windows decodes through the locale codec (cp1252) and
            # crashes the stdout reader thread on any byte cp1252 cannot map
            # -- e.g. the smart quotes and em-dashes claude emits (byte
            # 0x9d). That crash silently truncated a task's captured output,
            # so the reply posted to the hub was missing content while the
            # exit code still read 0. errors="replace" keeps a decode
            # failure from losing the whole result. (encoding= implies text
            # mode, so text=True is not also needed.)
            encoding="utf-8",
            errors="replace",
            timeout=TASK_TIMEOUT,
            cwd=str(WORKSPACE),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return (
            f"[timed out after {TASK_TIMEOUT:.0f}s]\n{partial}",
            124,
        )
    except OSError as exc:
        return (f"[could not execute {claude_binary}: {exc}]", 127)

    output = completed.stdout or ""

    if completed.stderr:
        output = f"{output}\n[stderr]\n{completed.stderr}"

    return output.strip(), completed.returncode


def post_reply(requests: Any, body: str, exit_code: int, message_id: Any) -> None:
    """Post one task's result back to the hub."""
    if len(body) > MAX_REPLY_CHARS:
        body = (
            body[:MAX_REPLY_CHARS]
            + f"\n[truncated at {MAX_REPLY_CHARS} characters]"
        )

    # The hub's request schema is exactly sender/target/content, so the
    # exit code and originating message id are folded into the content text
    # rather than sent as separate fields.
    payload = {
        "sender": SENDER_NAME,
        "target": REPLY_TARGET,
        "content": f"[task {message_id} exit={exit_code}]\n{body}",
    }

    if HUB_TOKEN:
        # Added only when auth is configured; with HUB_TOKEN unset the
        # payload is exactly the three fields the hub expects.
        payload["token"] = HUB_TOKEN

    try:
        response = requests.post(
            f"{HUB_URL}/send", json=payload, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("failed to post reply for message %s: %s", message_id, exc)


def post_alert(requests: Any, target: str, body: str) -> None:
    """Post a standalone status message to the hub, not a task's result.

    Same schema and truncation as post_reply, but without the "[task N
    exit=M]" wrapper: an alert isn't a task result, and dressing it as one
    would make a peer that filters on that prefix miss it.
    """
    if len(body) > MAX_REPLY_CHARS:
        body = (
            body[:MAX_REPLY_CHARS]
            + f"\n[truncated at {MAX_REPLY_CHARS} characters]"
        )

    payload = {"sender": SENDER_NAME, "target": target, "content": body}

    if HUB_TOKEN:
        payload["token"] = HUB_TOKEN

    try:
        response = requests.post(
            f"{HUB_URL}/send", json=payload, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("failed to post alert to %s: %s", target, exc)


def fetch_messages(requests: Any, since_id: int) -> list[dict]:
    """Messages newer than `since_id`, or an empty list on any hub error.

    Transport failures are logged and swallowed: the hub being briefly down
    is an expected condition for a daemon, not a reason to exit.
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

    # GET /messages returns a bare JSON list. Anything else -- an error
    # object, an HTML page from a misrouted proxy -- is treated as "no
    # messages" so a malformed response cannot crash the poll loop.
    if not isinstance(payload, list):
        log.warning(
            "poll returned a non-list payload (%s); ignoring",
            type(payload).__name__,
        )
        return []

    return payload


def handle(requests: Any, claude_binary: str, message: dict) -> None:
    message_id = message.get("id")
    sender = message.get("sender") or "unknown"
    task = message_content(message)

    if not token_ok(message):
        log.warning(
            "REFUSED message %s from %s: bad or missing token",
            message_id,
            sender,
        )
        return

    if task is None:
        # Logged whole, because a dropped task and an empty one are
        # indistinguishable from the outside.
        log.error(
            "message %s from %s has empty or missing content; raw=%s",
            message_id,
            sender,
            json.dumps(message)[:2000],
        )
        return

    if ERROR_ENVELOPE_RE.match(task.lstrip()):
        # Dropped without a reply: replying would post another message to the
        # hub, which is what turns one worker's outage into a loop between
        # workers. The text is logged so the outage is still visible here.
        log.warning(
            "DROPPED message %s from %s: peer error envelope, not a task: %s",
            message_id,
            sender,
            task[:200],
        )
        return

    rate_reason = rate_limit_reason()
    if rate_reason is not None:
        if not _rate_limit_alert_sent:
            log.warning(
                "RATE LIMIT GUARD: %s; refusing new tasks until restart",
                rate_reason,
            )
            post_alert(
                requests,
                "@Admin",
                f"claude_worker pausing new tasks: {rate_reason}. Restart "
                "the process to clear this once usage has reset.",
            )
            record_rate_limit_alert_sent()
        else:
            log.info(
                "DROPPED message %s from %s: rate limit guard active",
                message_id,
                sender,
            )
        return

    reason = suppression_reason(sender)
    if reason is not None:
        # Suppressed before run_task, so a throttled turn costs no execution
        # and no reply -- the reply is what would re-trigger the peer.
        log.info(
            "SUPPRESSED message %s from %s: %s", message_id, sender, reason
        )
        return

    log.info(
        "ACCEPTED message %s from %s (%d chars)", message_id, sender, len(task)
    )

    if HANDOFF_PATH.exists():
        log.info(
            "HANDOFF.md present (%d bytes) ahead of message %s",
            HANDOFF_PATH.stat().st_size,
            message_id,
        )

    started = time.monotonic()
    output, exit_code = run_task(claude_binary, HANDOFF_PREAMBLE + task)
    elapsed = time.monotonic() - started

    log.info(
        "COMPLETED message %s exit=%s in %.1fs", message_id, exit_code, elapsed
    )

    post_reply(requests, output, exit_code, message_id)
    record_action(sender)


def main() -> int:
    configure_logging()

    requests = ensure_requests()

    # Resolved rather than invoked by bare name: on Windows the CLI is
    # usually a .cmd shim, which a non-shell subprocess will not find on
    # PATH without PATHEXT resolution.
    claude_binary = shutil.which("claude")

    if claude_binary is None:
        log.error("no 'claude' executable on PATH; nothing could be run")
        return 127

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    log.info("hub        : %s", HUB_URL)
    log.info("claude     : %s", claude_binary)
    log.info("workspace  : %s", WORKSPACE)
    log.info(
        "auth       : %s",
        "shared token required" if HUB_TOKEN else "NONE (any sender accepted)",
    )
    log.info("handoff    : %s", HANDOFF_PATH)
    log.info(
        "rate guard : pause new tasks after %.1fh continuous uptime",
        RATE_LIMIT_WARN_SECONDS / 3600,
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

            # Advanced before handling, not after: a task that crashes this
            # worker must not be retried forever on every restart.
            if message_id > last_seen_id:
                last_seen_id = message_id
                save_last_seen_id(last_seen_id)

            if is_for_us(message):
                handle(requests, claude_binary, message)

        time.sleep(POLL_SECONDS)

    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
