"""Phase 0 containment: the only thing in this repository allowed to start work.

Why this module exists
----------------------

Before Phase 0 the three workers took their instructions from the hub's chat
stream. ``claude_worker`` ran ``claude -p`` with ``Bash,Read,Edit``
pre-authorized whenever a message arrived whose ``target`` named it, and the
other two called their model APIs whenever ``target`` named them *or* the
substring ``@chatgpt`` / ``@gemini`` appeared anywhere in a message's text.

Three properties of the hub made that unsafe, and all three were measured
against the running service on 2026-09-08 rather than assumed:

* ``GET /messages`` answered ``200`` with the full backlog to a caller holding
  no credential at all.
* ``sender`` was a free-text field in the ``POST /send`` body. Nothing derived
  it from an authenticated identity, so any writer could claim to be ``Admin``.
* Workers post their own results back into the same stream, so one worker's
  output was another worker's trigger.

The first two were closed on 2026-09-09: ``hub/hub.py`` authenticates every
route and derives ``sender`` from the credential. They are written in the past
tense here because they are the reason this module exists, not because they are
still true. The third is closed on this side -- results are addressed to
``@Admin``, and no inbound message reaches a model at all.

Together those mean the chat stream is an unauthenticated remote-execution
channel, and that an agent -- or anything else on the network -- can start a
model run on this host. Phase 0 closes that.

The containment rule
--------------------

**Chat never activates anything.** Not by ``target``, not by ``@mention``, not
from any sender, not with any content. Messages are still fetched, recorded
and readable, because narration is useful and losing it would be a real cost;
they simply carry no authority.

Work is instead started only through a *local control directory* that the hub
cannot reach. The trust boundary is the operating system's filesystem
permissions on this host, not a shared secret travelling over an open network.
That distinction is the whole point: a secret transmitted through the hub is
readable by every hub client, whereas a directory on OFFICEPC is writable only
by whoever already has an account on OFFICEPC.

This is deliberately stronger than "authenticate the chat stream", and it
stays that way now that the hub does authenticate. ``hub/hub.py`` is in this
repository and was deployed to Tower on 2026-09-09, so ``sender`` is finally
evidence of something -- but a chat field being trustworthy is not a reason to
let it start work, and the containment rule above is unchanged by it. What the
authenticated hub buys is the *option* of restoring Admin-over-chat, not its
restoration.

What this costs
---------------

Admin can no longer drive a worker by typing in the chat UI, and still cannot
as of 2026-09-09. The precondition for restoring it has been met -- the hub
authenticates callers and derives ``sender`` from the credential, so "only obey
Admin" is now enforceable where it previously was not -- but the capability was
deliberately not restored with it. Activation is moving to the controller
(``SWARM_PROTOCOL_v7.md`` section 13), and re-opening a second, chat-shaped path
to it would give back exactly the property Phase 0 removed. Admin drives workers
through the control directory -- see ``docs/PHASE0_CONTAINMENT.md``.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

# --- Layout -----------------------------------------------------------------
#
# Everything lives under one directory so an operator can reason about the
# trust boundary by looking at one ACL. SWARM_CONTROL_DIR is honoured mainly so
# tests can point at a tmpdir; in production the default is the right answer.

HERE = Path(__file__).resolve().parent
CONTROL_DIR = Path(os.environ.get("SWARM_CONTROL_DIR", HERE / "control"))

ACTIVATIONS_DIR = CONTROL_DIR / "activations"
CONSUMED_DIR = CONTROL_DIR / "consumed"
NARRATION_PATH = CONTROL_DIR / "narration.jsonl"
PAUSE_PATH = CONTROL_DIR / "PAUSED"
STATUS_PATH = CONTROL_DIR / "status.json"

# Chat is narration. This is a named constant rather than a bare ``False``
# scattered through the workers so that the property is greppable and so a
# future change has to edit something that says what it means.
CHAT_IS_AUTHORITATIVE = False


class ContainmentError(Exception):
    """Base class for refusals raised by this module."""


class MissingCredential(ContainmentError):
    """A required credential was absent from the environment."""


class InvalidCredential(ContainmentError):
    """A credential was present but not usable."""


class IdentityViolation(ContainmentError):
    """Something tried to act as, or speak as, an identity it does not hold."""


class ActivationRejected(ContainmentError):
    """An activation record was malformed, replayed, or not for this agent."""


# --- Credentials ------------------------------------------------------------
#
# Loaded from the environment only. There is deliberately no file fallback and
# no default value: a worker that silently ran with an empty key would fail
# later, further from the cause, and a worker that read a key from a file in
# this directory would make it committable.

# Values that are syntactically present but are obviously not a credential.
# These show up when a launcher exports an unset variable or someone pastes a
# placeholder, and they otherwise produce a confusing 401 from the provider
# much later.
_PLACEHOLDER_CREDENTIALS = {
    "",
    "none",
    "null",
    "changeme",
    "your-api-key",
    "your_api_key",
    "xxx",
    "todo",
    "sk-...",
}


def load_credential(env_var: str, *, env: dict | None = None) -> str:
    """Return the credential in `env_var`, or refuse.

    Raises `MissingCredential` when the variable is absent and
    `InvalidCredential` when it is present but blank or a placeholder.

    Neither exception carries the value. That is not decoration: these
    propagate into logs and into hub messages, and a credential that reaches a
    log has to be treated as exposed and rotated.
    """
    source = os.environ if env is None else env
    raw = source.get(env_var)

    if raw is None:
        raise MissingCredential(
            f"{env_var} is not set. Export it in the shell that launches the "
            f"worker; it is deliberately not read from any file in this "
            f"repository."
        )

    value = raw.strip()

    if value.lower() in _PLACEHOLDER_CREDENTIALS:
        raise InvalidCredential(
            f"{env_var} is set but is empty or a placeholder. Refusing to "
            f"start rather than failing against the provider later."
        )

    return value


# Matches the credential shapes this project actually handles, so redact() can
# scrub a string that is about to be logged or posted to the hub. This is a
# backstop, not a licence to pass secrets around: nothing in this repository
# should be constructing a string containing a key in the first place.
_SECRET_RE = re.compile(
    r"(sk-proj-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,})"
)


def redact(text: str) -> str:
    """Replace anything credential-shaped in `text` with a marker.

    Applied to worker output before it is logged or posted. A model that has
    been handed a shell can print the environment, so the fact that this
    repository never logs a key itself is not sufficient.
    """
    return _SECRET_RE.sub("[REDACTED-CREDENTIAL]", text)


def hub_auth(bound_identity: str) -> tuple:
    """The HTTP Basic pair this worker authenticates to the hub with.

    The username is the worker's own bound identity, so the name the hub
    derives the message `sender` from is the same name this process is
    configured to be. There is no way to authenticate as one component and
    speak as another, because they are the same string.

    The secret comes from `HUB_SECRET` in the environment, with no file
    fallback: a secret in a file next to the workers is one `git add` or one
    backup away from being shared. Missing means the worker refuses to start
    rather than polling an authenticated hub and logging a 401 every three
    seconds forever.
    """
    return (bound_identity, load_credential("HUB_SECRET"))


# --- Identity ---------------------------------------------------------------


def bind_identity(configured_agent: str) -> str:
    """Return the normalized handle this process is allowed to act as.

    A worker's identity comes from its own configuration, never from a field
    in a message it received. `outbound_envelope` enforces the same rule on
    the way out, so a worker cannot be talked into speaking as someone else.
    """
    handle = normalize_handle(configured_agent)

    if not handle:
        raise IdentityViolation("worker identity is empty; refusing to start")

    return handle


def normalize_handle(name: Any) -> str:
    """A handle reduced to its comparable form: no '@', trimmed, lowercased."""
    if not isinstance(name, str):
        return ""

    return name.strip().lstrip("@").strip().lower()


def outbound_envelope(
    bound_identity: str, target: str, content: str
) -> dict[str, str]:
    """Build a hub payload whose `sender` is this process's bound identity.

    `content` is redacted here rather than at each call site so that a new
    caller cannot forget. The `token` field the pre-Phase-0 workers attached
    is gone: `GET /messages` never returns a `token`, so that field never
    authenticated anything inbound, and putting a shared secret into a message
    body on a stream every client can read is how a shared secret stops being
    one.
    """
    return {
        "sender": bound_identity,
        "target": target,
        "content": redact(content),
    }


# --- Global pause / drain ---------------------------------------------------


def pause_reason(*, env: dict | None = None) -> str | None:
    """Why no new work may start, or None when the host is running.

    Two independent stops, because they fail in different directions. The
    sentinel file survives a restart and is what an operator reaches for; the
    environment variable is process-local and is what a launcher or a test
    uses. Either one alone is sufficient to hold the host.

    Checked *before* an activation is consumed, so a pause leaves the queue
    intact rather than eating the work it declined to run.
    """
    source = os.environ if env is None else env

    flag = source.get("SWARM_PAUSED", "").strip().lower()
    if flag not in ("", "0", "false", "no"):
        return f"SWARM_PAUSED={flag} in the worker environment"

    try:
        if PAUSE_PATH.exists():
            note = PAUSE_PATH.read_text(encoding="utf-8").strip()
            return f"{PAUSE_PATH.name} present" + (f": {note}" if note else "")
    except OSError as exc:
        # A pause flag that cannot be read is treated as engaged. The safe
        # direction for an unreadable stop signal is "stopped": the cost of a
        # spurious pause is a delay, and the cost of a missed one is an
        # unattended model run with Bash authority.
        return f"{PAUSE_PATH.name} unreadable ({exc}); failing closed"

    return None


def is_paused(*, env: dict | None = None) -> bool:
    return pause_reason(env=env) is not None


def engage_pause(note: str = "") -> None:
    """Write the durable pause sentinel."""
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_PATH.write_text(note, encoding="utf-8")


def release_pause() -> None:
    """Remove the durable pause sentinel. Does not clear SWARM_PAUSED."""
    PAUSE_PATH.unlink(missing_ok=True)


# --- Narration --------------------------------------------------------------


def record_narration(messages: Iterable[dict]) -> int:
    """Append hub messages to the local narration log; return how many.

    Chat is kept readable and durable precisely because it no longer carries
    authority: taking away its power to start work is not a reason to stop
    being able to read it. Nothing downstream of this function may make a
    control decision from what it writes.
    """
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    with NARRATION_PATH.open("a", encoding="utf-8") as handle:
        for message in messages:
            handle.write(
                json.dumps(
                    {
                        "id": message.get("id"),
                        "sender": message.get("sender"),
                        "target": message.get("target"),
                        "content": redact(str(message.get("content", ""))),
                        "timestamp": message.get("timestamp"),
                        "recorded_at": time.time(),
                        # Stamped on every row so that a reader of this file,
                        # or anything that later ingests it, cannot mistake
                        # narration for an instruction.
                        "authoritative": False,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1

    return written


def read_narration(limit: int | None = None) -> list[dict]:
    """Return recorded narration, oldest first. Missing log reads as empty."""
    try:
        lines = NARRATION_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    rows = [json.loads(line) for line in lines if line.strip()]

    return rows[-limit:] if limit else rows


# --- Activation -------------------------------------------------------------


def chat_message_activates(message: dict) -> bool:
    """Whether `message` may start work. Always False, by construction.

    This exists as a real, called function rather than as deleted code so the
    property has somewhere to be tested. The tests assert across mentions,
    targets, spoofed Admin senders and control-looking payloads that this
    returns False, which is a claim that keeps being checked; a deleted branch
    would just be absent, and absence silently stops being true when somebody
    adds a shortcut back.
    """
    return CHAT_IS_AUTHORITATIVE


def issue_activation(agent: str, task: str, *, issued_by: str = "admin") -> str:
    """Place one activation in the control directory and return its id.

    This is the Admin path. It is a filesystem write on the execution host,
    which is exactly why it is trustworthy: the hub has no route to it.
    """
    ACTIVATIONS_DIR.mkdir(parents=True, exist_ok=True)

    activation_id = uuid.uuid4().hex
    record = {
        "activation_id": activation_id,
        "agent": normalize_handle(agent),
        "task": task,
        "issued_by": issued_by,
        "issued_at": time.time(),
    }

    # Written to a temporary name and renamed, so a worker polling this
    # directory can never observe a half-written record and treat a truncated
    # task string as the whole task.
    staged = ACTIVATIONS_DIR / f".{activation_id}.tmp"
    staged.write_text(json.dumps(record), encoding="utf-8")
    staged.rename(ACTIVATIONS_DIR / f"{activation_id}.json")

    return activation_id


def claim_activation(bound_identity: str) -> dict | None:
    """Claim at most one activation for `bound_identity`, or None.

    Claiming moves the record into `consumed/` before it is returned. The
    rename is the idempotency boundary: it is atomic on both NTFS and POSIX,
    so two polls -- or two processes -- cannot both win the same record, and a
    duplicate poll of an already-claimed activation finds nothing to run. That
    is what makes repeated polling free rather than repeatedly chargeable.

    A record whose `agent` is not this worker is left alone rather than
    consumed, so one worker cannot starve another by draining the queue.
    """
    if not ACTIVATIONS_DIR.exists():
        return None

    CONSUMED_DIR.mkdir(parents=True, exist_ok=True)

    for path in sorted(ACTIVATIONS_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Quarantined rather than deleted: a malformed activation is
            # evidence about whoever wrote it, and deleting it would destroy
            # the only copy.
            _quarantine(path, "unreadable")
            continue

        if not isinstance(record, dict) or not record.get("task"):
            _quarantine(path, "malformed")
            continue

        if normalize_handle(record.get("agent")) != bound_identity:
            continue

        claimed = CONSUMED_DIR / path.name
        try:
            path.rename(claimed)
        except OSError:
            # Lost the race to another poll or process. Not an error: the
            # other claimant owns it, and this one simply has no work.
            continue

        record["claimed_at"] = time.time()
        return record

    return None


def _quarantine(path: Path, why: str) -> None:
    CONSUMED_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path.rename(CONSUMED_DIR / f"{why}-{path.name}")
    except OSError:
        pass


# --- Control status ---------------------------------------------------------


def control_status(bound_identity: str = "") -> dict:
    """A readable snapshot of what containment is currently doing.

    Phase 0 asks for a visible control status. The hub has no such endpoint --
    `GET /control/status` answers 404 -- and the hub is not in this
    repository, so this is the host-side half: the same facts, readable
    locally and writable to `status.json` for anything that wants to display
    them.
    """
    reason = pause_reason()
    pending = (
        len(list(ACTIVATIONS_DIR.glob("*.json")))
        if ACTIVATIONS_DIR.exists()
        else 0
    )
    consumed = (
        len(list(CONSUMED_DIR.glob("*.json"))) if CONSUMED_DIR.exists() else 0
    )

    return {
        "identity": bound_identity,
        "paused": reason is not None,
        "pause_reason": reason,
        "chat_is_authoritative": CHAT_IS_AUTHORITATIVE,
        "activation_source": str(ACTIVATIONS_DIR),
        "pending_activations": pending,
        "consumed_activations": consumed,
        "narration_rows": len(read_narration()),
        "observed_at": time.time(),
    }


def write_status(bound_identity: str = "") -> dict:
    """Persist `control_status()` to status.json and return it."""
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    status = control_status(bound_identity)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def _main(argv: list[str]) -> int:
    """Small operator CLI: status, pause, resume, issue."""
    command = argv[1] if len(argv) > 1 else "status"

    if command == "status":
        print(json.dumps(control_status(), indent=2))
        return 0

    if command == "pause":
        engage_pause(" ".join(argv[2:]) or "paused by operator")
        print(json.dumps(control_status(), indent=2))
        return 0

    if command == "resume":
        release_pause()
        print(json.dumps(control_status(), indent=2))
        return 0

    if command == "issue":
        if len(argv) < 4:
            print("usage: swarm_control.py issue <agent> <task...>")
            return 2
        activation_id = issue_activation(argv[2], " ".join(argv[3:]))
        print(activation_id)
        return 0

    print(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv))
