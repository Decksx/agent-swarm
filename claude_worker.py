"""Execute operator-issued activations for Claude Code, and narrate to the hub.

TRUST BOUNDARY -- read this before running
------------------------------------------

This daemon runs ``claude -p`` with ``Bash``, ``Read`` and ``Edit``
pre-authorized, which is the configuration that never prompts. Anything able
to start a task here can run commands as the user running this script.

Before Phase 0 the thing able to start a task was *the hub's chat stream*, and
the hub was measured to answer ``GET /messages`` with ``200`` to a caller
holding no credential, with ``sender`` a free-text field that nothing derives
from an authenticated identity. That made this daemon an unauthenticated
remote-execution endpoint for this machine.

It no longer takes work from the hub at all:

* **Chat cannot start anything.** Not by ``target``, not by ``@mention``, not
  from any sender, not with any content. Messages are fetched, recorded to the
  local narration log and readable; they carry no authority.
* **Work is claimed from a local control directory** (see ``swarm_control``),
  which the hub has no route to. The boundary is this host's filesystem
  permissions, not a secret sent over an open network.
* **The global pause flag is checked before each claim**, so engaging it leaves
  queued work intact rather than consuming what it declined to run.
* **Identity is bound from local configuration.** This process speaks only as
  ``AGENT_IDENTITY`` and never adopts a name from an inbound message.
* Results are addressed to ``@Admin``, never to a peer worker. Posting results
  to ``@Gemini`` is what made the swarm self-driving.
* Every accepted activation is appended to ``claude_worker.log`` with its id,
  issuer and exit code, so there is a record of what ran, and output is passed
  through ``swarm_control.redact`` before it is logged or posted.

The task string is passed to ``subprocess.run`` as a **list element**, never
interpolated into a shell string, so quotes, ``$(...)`` and ``;`` in a task are
one argument to ``claude`` rather than shell syntax.

What this costs: Admin can no longer drive this worker by typing in the chat
UI. That returns when the hub authenticates callers and derives ``sender``
server-side -- the half of Phase 0 that lives on Tower. Until then "obey only
Admin" is not enforceable, because anyone may claim to be Admin. See
``docs/PHASE0_CONTAINMENT.md`` for the operator workflow.

Hub schema
----------

Confirmed against the running hub:

* ``GET /messages`` returns a bare JSON **list** of message objects, each with
  ``id``, ``sender``, ``target``, ``content`` and ``timestamp``.
* ``POST /send`` takes ``sender``, ``target`` and ``content``.

The hub's own OpenAPI schema (it serves ``/openapi.json`` unauthenticated)
shows ``POST /send`` *accepts* an optional ``token``, but the ``Message`` model
returned by ``GET /messages`` has no such field. So a token can be sent and is
never handed back, which is why the pre-Phase-0 inbound ``token_ok()`` check
could refuse traffic but could never admit it. Whether the hub validates that
token on write is still unmeasured; nothing here depends on the answer.
De-duplication of narration is by ``id``.
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

import controller_client
import swarm_control

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")

# This worker's identity is bound from its own configuration and is the only
# name it may speak as. It is never read from an inbound message: `sender` is
# a free-text field on an unauthenticated hub, so believing it would let any
# writer decide who this process claims to be.
AGENT_IDENTITY = swarm_control.bind_identity(
    os.environ.get("AGENT_IDENTITY", "claudecode")
)

# Results go to the operator, not to a peer worker. The pre-containment value
# was "@Gemini", so every completed task posted a message that target-triggered
# Gemini, whose reply re-triggered this worker: the loop was not an emergent
# misuse of the design, it was wired in. Nothing this worker emits is addressed
# to another agent any more.
REPLY_TARGET = "@Admin"

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", HERE / "workspace"))
STATE_FILE = HERE / "claude_worker.state"

# Written before a model is invoked and removed after the result is reported.
# Its presence at startup means the process died mid-task. See main().
INFLIGHT_PATH = HERE / "claude_worker.inflight"
LOG_FILE = HERE / "claude_worker.log"
HANDOFF_PATH = WORKSPACE / "HANDOFF.md"

# --- Where work comes from ---------------------------------------------------
#
# Exactly one source, chosen at startup and named in the log. "directory" is
# the Phase 0 local control directory; "controller" is the HTTP API on the hub.
#
# Never both. A worker polling two queues can hold two activations at once,
# and neither queue would know about the other's -- the controller's host
# capacity would be counting one while a second ran beside it. The default
# stays "directory" so a worker started by hand behaves as it did yesterday;
# converting one is a deliberate act in the launcher.
ACTIVATION_SOURCE = os.environ.get("ACTIVATION_SOURCE", "directory").strip().lower()
VALID_SOURCES = ("directory", "controller")

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", HUB_URL)

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

# Set once in main() from HUB_SECRET. Module-level rather than threaded
# through every call because HUB_URL and the timeouts already are, and a
# worker authenticates as exactly one component for its whole life.
_HUB_AUTH: tuple | None = None

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


# is_for_us() and token_ok() are gone rather than tightened.
#
# is_for_us() decided activation from the inbound `target` field; token_ok()
# compared an inbound `token` field against a shared secret. Neither could be
# repaired in place. Both read fields off an unauthenticated stream, and the
# hub never returns a `token` on GET /messages, so an inbound message never
# carries one -- that check could refuse traffic but could never admit it.
# Tightening a test on a field that cannot be trusted only moves the hole.
#
# Whether a message may start work is now answered in one place, for all three
# workers, by swarm_control.chat_message_activates(). It returns False.


# The reply governor that used to sit here has been removed, not disabled.
#
# It existed to brake a loop where each worker triggered on the others'
# messages: a per-sender cooldown plus a rolling rate cap, both advisory,
# both in-memory, both cleared by a restart. That loop cannot form any more,
# because chat cannot start work at all and results are addressed to @Admin
# rather than to a peer. Keeping a dead brake would be worse than having
# none: a reader would take the throttle for the thing making the swarm
# safe, when what makes it safe is that the trigger is gone.
#
# The 5-hour usage guard below is NOT part of that and still applies -- it
# bounds spend against a real external limit, which containment does not.

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
    payload = swarm_control.outbound_envelope(
        AGENT_IDENTITY,
        REPLY_TARGET,
        f"[task {message_id} exit={exit_code}]\n{body}",
    )

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
            auth=_HUB_AUTH,
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


def clear_inflight() -> None:
    """Forget the in-flight marker. Safe to call when there is none."""
    try:
        INFLIGHT_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("could not clear the in-flight marker: %s", exc)


def execute_activation(
    requests: Any, claude_binary: str, activation: dict, queue: Any = None
) -> None:
    """Run one operator-issued activation and post its result.

    `activation` came from the local control directory. It did not come from
    the hub, and no field on it was supplied by a hub client, which is what
    makes it safe to hand to a `claude -p` process holding Bash authority.

    The caller has already checked the pause flag and won the claim, so this
    function's remaining guards are about budget and about task text, not
    about authorization.
    """
    activation_id = activation.get("activation_id")
    task = activation.get("task")

    if not isinstance(task, str) or not task.strip():
        # Claimed and then refused rather than skipped: the record is already
        # in consumed/, so a malformed activation is recorded as having been
        # seen instead of being re-read on every poll forever.
        log.error("activation %s has no runnable task; dropped", activation_id)
        _report(queue, activation_id, "blocked", {"reason": "no runnable task"})
        return

    if ERROR_ENVELOPE_RE.match(task.lstrip()):
        # Retained from the chat era. It can no longer fire on a peer's error
        # message, because peers cannot reach this path at all, but it still
        # catches an operator pasting a worker's error envelope back in as a
        # task, which is where the text would otherwise come from.
        log.warning(
            "activation %s looks like a worker error envelope, not a task: %s",
            activation_id,
            task[:200],
        )
        _report(queue, activation_id, "blocked",
                {"reason": "task text is a worker error envelope"})
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
                "DROPPED activation %s: rate limit guard active", activation_id
            )

        # Reported as blocked rather than failed: nothing about the task is
        # wrong, this host cannot run it right now. AUTHOR_BLOCKED is the state
        # an operator can release; CHANGES_REQUESTED would blame the task.
        _report(queue, activation_id, "blocked", {"reason": rate_reason})
        return

    log.info(
        "ACCEPTED activation %s from %s (%d chars)",
        activation_id,
        activation.get("issued_by", "unknown"),
        len(task),
    )

    if HANDOFF_PATH.exists():
        log.info(
            "HANDOFF.md present (%d bytes) ahead of activation %s",
            HANDOFF_PATH.stat().st_size,
            activation_id,
        )

    # Written before the model is invoked, not after. The marker exists to
    # answer "did this process die while a task was running", and a marker
    # written after the run would answer it wrongly in exactly the case that
    # matters.
    if activation_id:
        try:
            INFLIGHT_PATH.write_text(str(activation_id), encoding="utf-8")
        except OSError as exc:
            log.warning("could not record the in-flight marker: %s", exc)

    started = time.monotonic()
    output, exit_code = run_task(claude_binary, HANDOFF_PREAMBLE + task)
    elapsed = time.monotonic() - started

    log.info(
        "COMPLETED activation %s exit=%s in %.1fs",
        activation_id,
        exit_code,
        elapsed,
    )

    # Redacted before it is logged or posted. The task ran with Bash, so the
    # output can contain anything the shell could print, including the
    # environment this process was started with.
    post_reply(requests, swarm_control.redact(output), exit_code, activation_id)

    # The controller is told the outcome; chat is told the story. Only the
    # first can move a task, which is why the narration above can be lossy and
    # this cannot.
    _report(
        queue,
        activation_id,
        "candidate" if exit_code == 0 else "failed",
        {
            "exit_code": exit_code,
            "elapsed_seconds": round(elapsed, 1),
            "output_excerpt": swarm_control.redact(output)[:2000],
        },
    )

    clear_inflight()


def _report(queue: Any, activation_id: Any, outcome: str, payload: dict) -> None:
    """Tell the controller how an activation ended, if there is one.

    A no-op on the directory source, where the record moving into consumed/ is
    the whole of the bookkeeping and there is nothing to report to.
    """
    if queue is None or not activation_id:
        return

    queue.report(activation_id, outcome=outcome, payload=payload)
    clear_inflight()


def main() -> int:
    configure_logging()

    requests = ensure_requests()

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


    # Resolved rather than invoked by bare name: on Windows the CLI is
    # usually a .cmd shim, which a non-shell subprocess will not find on
    # PATH without PATHEXT resolution.
    claude_binary = shutil.which("claude")

    if claude_binary is None:
        log.error("no 'claude' executable on PATH; nothing could be run")
        return 127

    if ACTIVATION_SOURCE not in VALID_SOURCES:
        log.error(
            "refusing to start: ACTIVATION_SOURCE=%r is not one of %s",
            ACTIVATION_SOURCE,
            ", ".join(VALID_SOURCES),
        )
        return 3

    queue = None

    if ACTIVATION_SOURCE == "controller":
        queue = controller_client.ControllerQueue(
            requests,
            base_url=CONTROLLER_URL,
            auth=_HUB_AUTH,
            agent=AGENT_IDENTITY,
            timeout=HTTP_TIMEOUT,
        )

    # A marker left over from a previous process means this worker died with a
    # model running. It is NOT resumed: there is no way to know whether the run
    # finished, whether it wrote anything, or what its result was, so the
    # activation is left alone, its lease expires, and the controller's sweep
    # recovers the task.
    #
    # **This is fail-safe, not exactly-once, and the difference matters.** What
    # it guarantees is that the *controller's* state stays consistent: no
    # result is invented for a run nobody observed, and the task returns to a
    # state the controller and the operator agree on. What it cannot guarantee
    # is that the model did nothing before the crash. `claude -p` runs with
    # Bash, so it may already have written files, committed, or pushed -- and
    # once the lease expires, a replacement activation runs the same task
    # again, on top of whatever the first attempt left behind.
    #
    # Exactly-once model execution is not achievable across process failure by
    # any bookkeeping on this side. Making it safe requires recovery to inspect
    # the expected branch and artifacts before reissuing, which is not built.
    # Until it is, this path takes harmless tasks on unique per-task branches
    # only. See docs/PHASE1_MVP_LIMITS.md.
    if INFLIGHT_PATH.exists():
        try:
            orphan = INFLIGHT_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            orphan = "unreadable"

        log.warning(
            "previous process died running activation %s. Not resuming it; its "
            "lease will expire and the controller will recover the task. NOTE: "
            "the model may already have changed the repository before the "
            "crash, and a reissued activation will run the task again on top "
            "of whatever it left. Check the task branch before relying on it.",
            orphan,
        )
        clear_inflight()

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    log.info("hub        : %s", HUB_URL)
    log.info("work from  : %s", ACTIVATION_SOURCE)
    log.info("claude     : %s", claude_binary)
    log.info("workspace  : %s", WORKSPACE)
    log.info("identity   : %s (bound locally, never from a message)", AGENT_IDENTITY)
    log.info(
        "activations: %s",
        f"{CONTROLLER_URL}/controller/activations/claim"
        if ACTIVATION_SOURCE == "controller"
        else swarm_control.ACTIVATIONS_DIR,
    )
    log.info("chat        : narration only; it cannot start work")
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

    # Logged on transition rather than every poll, so a long pause leaves a
    # readable log instead of one line every POLL_SECONDS.
    was_paused = None

    while running:
        # 1. Chat. Fetched and recorded, never obeyed. The loop below advances
        #    the high-water mark and stores narration; there is deliberately
        #    no branch here that can reach execute_activation(), which is the
        #    whole of Phase 0 containment in this file.
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
            # queue intact rather than consuming the work it declined to run.
            # True of both sources: the controller hands out an activation on
            # claim, so asking it while paused would consume one exactly as
            # renaming the directory record would.
            if queue is not None:
                try:
                    activation = queue.claim()
                except (
                    controller_client.Unauthenticated,
                    controller_client.ClaimForbidden,
                ) as exc:
                    # Not retried and not backed off. Neither a rejected
                    # credential nor a refusal to let this component take work
                    # can change while this process runs, so polling on would
                    # produce a worker that is alive, logging, and incapable of
                    # ever doing anything -- which is harder to spot than an
                    # exit. Distinct code so a supervisor can tell it from a
                    # crash or a missing binary.
                    log.error("fatal: %s", exc)
                    log.error(
                        "check this worker's HUB_SECRET matches the %r "
                        "component secret on the hub",
                        AGENT_IDENTITY,
                    )
                    return 4
            else:
                activation = swarm_control.claim_activation(AGENT_IDENTITY)

            if activation is not None:
                execute_activation(requests, claude_binary, activation, queue)

        swarm_control.write_status(AGENT_IDENTITY)

        # The server's own interval wins when it named one, then a backoff
        # while the controller is unreachable, then the ordinary cadence.
        # Taking the maximum rather than a branch means a 429 during an outage
        # still honours whichever asked for longer.
        wait = POLL_SECONDS

        if queue is not None:
            wait = max(wait, getattr(queue, "retry_after", 0.0), queue.backoff.current)

        time.sleep(wait)

    log.info("stopped at message id %s", last_seen_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
