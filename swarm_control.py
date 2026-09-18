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

import contextlib
import json
import os
import posixpath
import re
import shlex
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

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

# --- Who runs what ----------------------------------------------------------
#
# The one place an identity is turned into the script that identity runs.
#
# It lived in ``supervisor.py`` while only the supervisor needed it, and moved
# here when the lock did. ``SingleInstance`` has to answer "is the process in
# this lock file really this identity's worker", and a lock that had to import
# the supervisor to find out would make the worker depend on the thing that
# supervises it. Two copies of the mapping is the other way to arrange it, and
# a mapping that disagrees with itself is a lock that protects one name and
# terminates another.

WORKER_SCRIPTS = {
    "chatgpt": "chatgpt_worker.py",
    "gemini": "gemini_worker.py",
    "claudecode": "claude_worker.py",
}

# The supervisor is not a worker, but it has a pid file for the same reason
# and it goes stale the same way.
SUPERVISOR = "supervisor"
SUPERVISOR_SCRIPT = "supervisor.py"


def script_for(name: str) -> Optional[str]:
    """The script `name` runs -- a worker identity, or "supervisor"."""
    if name == SUPERVISOR:
        return SUPERVISOR_SCRIPT

    return WORKER_SCRIPTS.get(name)


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
    r"(sk-proj-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}"
    # GitHub tokens, now that workers push and open pull requests (#32).
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
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


UNKNOWN_TIME = "unknown"


def message_stamp(message: Any) -> str:
    """When one hub message was sent, as ISO-8601 UTC, for a transcript line.

    Every worker prefixes its transcript lines with this, so a model reading a
    thread can tell an exchange from five minutes ago from one from Tuesday.
    Without it a transcript is a flat list of turns, and a model asked to
    continue a conversation cannot tell that the last three messages arrived
    after an overnight gap -- which is exactly when the state it is being
    asked about has moved on underneath it.

    UTC in the transcript, deliberately, where the browser shows local time.
    A worker's transcript is read by a model and archived in a log that is
    read on another machine in another zone; a local rendering there would be
    local to whichever host happened to build the prompt.

    The hub is the authority and sends `timestamp_utc` ready-made. The Unix
    fallback is for one case only: a worker running against a hub that has not
    yet been redeployed with the field. It computes the same instant the same
    way rather than dropping the prefix, because a transcript where some lines
    are stamped and some are not is harder to read than either.
    """
    if not isinstance(message, dict):
        return UNKNOWN_TIME

    stated = str(message.get("timestamp_utc") or "").strip()

    if stated:
        return stated

    raw = message.get("timestamp")

    if raw is None:
        return UNKNOWN_TIME

    try:
        moment = datetime.fromtimestamp(float(raw), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        # Never guessed at. A bad value rendered as the epoch would put 1970
        # in the transcript and read as a time somebody could reason about.
        return UNKNOWN_TIME

    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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


class AlreadyRunning(ContainmentError):
    """Another process is already running as this identity."""


if os.name == "nt":
    import msvcrt
else:
    import fcntl


# How long to wait for another process to leave the acquisition section.
#
# Generous, because the section contains an identity check and that check
# shells out -- reading a Windows process's command line can take seconds. A
# waiter that gave up in under that would report a conflict that is not one.
MUTEX_TIMEOUT = 45.0


@contextlib.contextmanager
def _exclusive(path: Path, *, timeout: float = MUTEX_TIMEOUT):
    """Hold an operating-system lock on `path` for the duration of the block.

    The acquisition section reads the pid file, decides whether its holder is
    real, removes it if it is not, and creates a new one. Those are four
    filesystem operations, and comparing the file's contents before removing
    it does not bind the comparison to the removal: a racer can replace the
    file in between, and the comparison was about a file that no longer
    exists. Two workers for one identity got through exactly that gap.

    So the whole sequence runs under a lock the operating system arbitrates,
    which is the only thing here that is genuinely atomic. `LockFile` on
    Windows and `flock` on POSIX both attach to the open handle, so a process
    that is killed rather than shut down has its lock released by the kernel
    -- there is no stale mutex to inherit, which is the property that makes
    this safe to hold across a section that can block.

    The mutex file is created and never removed. On POSIX the lock lives on
    the inode, so a process that unlinked it would leave the next one locking
    a file nobody else can see; keeping it costs an empty file per identity in
    a directory that is already per-host runtime state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)

    try:
        deadline = time.monotonic() + timeout

        while True:
            try:
                os.lseek(handle, 0, os.SEEK_SET)

                if os.name == "nt":
                    msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AlreadyRunning(
                        f"could not take the acquisition lock at {path} "
                        f"within {timeout:.0f}s; another process is holding "
                        f"it. Refusing to start rather than race for it."
                    )

                time.sleep(0.05)

        try:
            yield
        finally:
            try:
                os.lseek(handle, 0, os.SEEK_SET)

                if os.name == "nt":
                    msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                # Closing the handle below releases it regardless. This is
                # tidiness, not the guarantee.
                pass
    finally:
        os.close(handle)


class SingleInstance:
    """Refuse to start a second worker for the same identity.

    Four Gemini workers were found alive at once on 2026-09-09, left behind by
    launchers whose supervisor was killed without killing the python child.
    They did no damage -- an activation is claimed atomically, so duplicates
    poll and find nothing -- but that is a guarantee about the controller, not
    about the host. What duplicates do cost is real: every one of them polls,
    every one authenticates, and on a per-token provider every one that claims
    something spends money. They also make "exactly one model call" unmeasurable,
    which is worse than the waste, because it is the measurement the whole
    review rests on.

    The lock is a file holding a pid, and a stale one is taken over, because
    refusing to start after a crash would turn one bad shutdown into an
    outage. Stale means two things, and reading only the first cost an
    identity its worker: the pid is gone, *or* the pid is alive and running
    something that is not this identity's script. A crashed worker leaves its
    number behind and the host reissues it, so a lock file is a claim about
    the past and the process behind it is the only evidence about now.

    A holder that cannot be identified is left standing. Failing to read a
    process is not evidence that it is not the worker, and starting a second
    one beside it is the duplicate this exists to prevent.
    """

    def __init__(self, identity: str, directory: Optional[Path] = None) -> None:
        self.identity = identity
        base = CONTROL_DIR if directory is None else Path(directory)
        self.path = base / f"{identity}.pid"
        # The mutex, not the record. `self.path` stays the lifetime pid file
        # that every other tool reads; this is held only while that file is
        # being read, judged and replaced.
        self.mutex_path = base / f"{identity}.acquire"

    def _raw(self) -> Optional[str]:
        """The lock file's exact contents, or None if there is no file."""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _recorded_pid(self) -> Optional[int]:
        """The number written in the lock file, whatever it may since mean."""
        raw = self._raw()

        if raw is None:
            return None

        try:
            return int(raw.strip())
        except ValueError:
            # Unreadable content is treated as no holder rather than as a
            # holder that cannot be checked: the alternative is a lock nothing
            # can ever clear.
            return None

    def _holder(self) -> Optional[int]:
        """The pid holding this lock, or None if nothing this identity's is.

        Liveness was the whole test here, and liveness is not the question.
        The number in the file was a worker's when it was written; a worker
        that died without releasing leaves it behind, and the operating system
        hands it to whatever starts next.

        That happened on the first live start. `chatgpt.pid` held a number
        from the previous run, Windows had just reissued it to the claudecode
        worker two seconds earlier, and so the chatgpt worker read a live pid
        out of its own lock file and refused to start. Not once -- nothing
        rewrites a lock nobody can take, so chatgpt was locked out
        permanently, by a file describing a process that had been dead for an
        hour and a half.

        So a live holder has to be running this identity's script to count.
        One that is definitively running something else is a stale lock with a
        recycled number in it, and is taken over exactly like a lock whose
        process is gone.

        A holder that cannot be identified still counts. "I cannot read that
        process" is not evidence of absence, and starting a second worker on
        it is the duplicate this class exists to prevent.
        """
        pid = self._recorded_pid()

        if pid is None or not pid_is_alive(pid):
            return None

        if pid == os.getpid():
            # This process. Whatever it is running, it is what holds the lock,
            # and `release` has to be able to recognise its own.
            return pid

        script = script_for(self.identity)

        if script is None:
            # An identity with no known script -- nothing here can identify
            # it, so a live holder is left standing.
            return pid

        return None if process_is_script(pid, script) is False else pid

    def acquire(self) -> None:
        """Take the lock, or refuse because somebody else genuinely holds it.

        The whole decision runs inside an operating-system lock. Reading the
        pid file, judging its holder, removing it if it is stale and creating
        the replacement are four separate filesystem operations, and any gap
        between them is a gap two workers can both walk through.

        The gap was real and the narrower versions did not close it. A
        check-then-write let every racer judge one stale lock and all of them
        write. Creating the file exclusively fixed that and left the clearing
        step: all of them still judged it stale, all of them removed it, and
        one removed the lock another had just taken. Comparing the contents
        before removing looked like it bound the two together and did not --
        the comparison is about a file that a racer can replace before the
        removal reaches it. Thirty clean races only measured how narrow that
        had become.

        Nothing composed out of separate filesystem calls can close it, so the
        arbiter is the kernel. Inside `_exclusive` there is no interleaving to
        reason about: one process at a time reads, judges, clears and creates.
        """
        with _exclusive(self.mutex_path):
            holder = self._holder()

            if holder is not None and holder != os.getpid():
                raise AlreadyRunning(
                    f"another {self.identity!r} worker is already running as "
                    f"pid {holder}; refusing to start a second one. Stop it "
                    f"first, or remove {self.path} if you are certain it is "
                    f"gone."
                )

            # Stale, ours from an earlier acquire, or absent. Removed under
            # the mutex, so the file being removed is necessarily the file
            # that was just judged -- nothing else can have replaced it.
            try:
                self.path.unlink()
            except OSError:
                pass

            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(str(os.getpid()))

    def release(self) -> None:
        """Give up the lock, but only if it is still ours.

        Under the mutex, for the same reason as acquiring. Reading the file
        and then removing it is the same unbound pair: a worker that checked,
        was replaced by a racer taking over its stale lock, and then removed
        the file would delete a lock somebody else legitimately holds -- and
        the next process would find nothing there and start a duplicate.

        A shorter wait than an acquisition gets, and no deletion at all if the
        mutex cannot be had. Releasing happens on the way out, often while an
        operator is waiting for a stop, and a lock file left behind is
        harmless: it names a process that is about to be gone, and the next
        acquirer identifies it as stale. Blocking a shutdown to tidy up is the
        worse trade.
        """
        try:
            with _exclusive(self.mutex_path, timeout=5.0):
                if self._holder() == os.getpid():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
        except AlreadyRunning:
            pass


def pid_is_alive(pid: int) -> bool:
    """Whether `pid` names a running process, on Windows or POSIX.

    Errs towards "alive" only when it genuinely cannot tell. Reporting a live
    process as dead would let a second worker start beside it, which is the
    thing this exists to prevent.
    """
    if pid <= 0:
        return False

    if os.name == "nt":
        # No signal 0 on Windows. tasklist is present on every install and
        # needs no extra dependency in a worker that must stay importable with
        # the standard library alone.
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=15, check=False,
            )
        except Exception:
            return True

        return str(pid) in (result.stdout or "")

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists and belongs to somebody else.
        return True
    except OSError:
        return True

    return True


def powershell_executable() -> str:
    r"""Where PowerShell is, not what PATH happens to call it (#50).

    `process_command_line` invoked `powershell.exe` by bare name, which
    resolves in a developer's shell and does not resolve under Task
    Scheduler, whose environment carries no System32 on PATH. The lookup
    failed, `process_arguments` answered None, `identifies_script` answered
    False -- and every caller reads that as "this pid is not what the file
    says", because a check that guesses when it fails is not a check.

    The visible cost was the #48 scheduled task trying to start a second
    supervisor every five minutes against a perfectly healthy one, each
    attempt refused by the single-instance lock and each logged as an error.
    `swarm_ctl.sh stop` and `status` ask the same question through
    `--identify` and would have been wrong in the same environment.

    The absolute path is used when it exists, and the bare name otherwise:
    a host where System32 is somewhere else, or a PowerShell reached some
    other way, is no worse off than before.
    """
    absolute = Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
        "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

    return str(absolute) if absolute.exists() else "powershell.exe"


def process_command_line(pid: int) -> Optional[str]:
    """The command line `pid` was started with, or None if it cannot be read.

    None means "cannot tell", and every caller treats that as a refusal to act
    rather than as permission. That direction is the whole point: this exists
    so that a pid read out of a lock file can be checked against the process
    actually holding it before anything terminates it, and a check that
    guesses when it fails is not a check.

    A lock file is not evidence on its own. It records the pid of a worker
    that was alive when it was written, and pids are reused -- so a worker
    that died without releasing leaves a number that may by then belong to
    anything on the host. `pid_is_alive` cannot tell the difference, because
    the recycled process is genuinely alive.
    """
    if pid <= 0:
        return None

    if os.name == "nt":
        # PowerShell rather than wmic: wmic is gone from current Windows 11
        # builds, and this has to work on the host it actually runs on.
        try:
            result = subprocess.run(
                [
                    powershell_executable(), "-NoProfile", "-NonInteractive",
                    "-Command",
                    "(Get-CimInstance Win32_Process -Filter "
                    f"'ProcessId={pid}').CommandLine",
                ],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=30, check=False,
            )
        except Exception:
            return None

        text = (result.stdout or "").strip()
        return text or None

    # /proc first because it needs no subprocess and is exact. Its arguments
    # are NUL-separated; they are joined with spaces because every caller
    # matches substrings rather than parsing arguments back out.
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        raw = b""

    if raw:
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip() or None

    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=15, check=False,
        )
    except Exception:
        return None

    text = (result.stdout or "").strip()
    return text or None


def process_arguments(pid: int) -> Optional[list]:
    """The argument vector of `pid`, or None if it cannot be read.

    The list rather than the string, because the decision made from it is
    "which script is this process running", and that question has no answer in
    a flat string. `gemini_worker.py` appears inside `backup_gemini_worker.py`,
    inside `gemini_worker.py.bak`, and inside any command that merely mentions
    the name -- a substring test authorizes a force-kill on all three.

    Argument boundaries are taken from the operating system where it will give
    them. `/proc` holds the real argv, NUL-separated, so nothing has to be
    parsed back out of a rendering of it. Windows keeps only the string, so it
    is split the way a Windows shell would: `posix=False` leaves backslashes
    alone, which matters when every path in it is a Windows path.
    """
    if pid <= 0:
        return None

    if os.name != "nt":
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            raw = b""

        if raw:
            decoded = raw.decode("utf-8", "replace")
            return [arg for arg in decoded.split("\x00") if arg]

    command = process_command_line(pid)

    if command is None:
        return None

    return split_command_line(command) or None


def split_command_line(command: str):
    """A command-line string back into arguments, or None if it will not parse.

    Separate from `process_arguments` because it is the half that can be
    tested against a command line nobody has to spawn first, and because on
    Windows it is the only thing standing between a rendered string and a
    decision to terminate a process.

    `posix=False` leaves backslashes alone: on Windows every path in the
    string contains them, and the POSIX rules would read each one as an escape
    and quietly eat it.

    A string that does not parse answers None rather than falling back to
    splitting on whitespace. The fallback looked conservative and was not:
    `python -c "import x; y('gemini_worker.py` has no closing quote, and
    whitespace-splitting it manufactures `'gemini_worker.py` as an argument
    out of text that was never one. Refusing is the only answer that cannot
    invent a match.
    """
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        return None

    if os.name == "nt":
        parts = [part.strip('"') for part in parts]

    return [part for part in parts if part]


# python, python3, python3.11, pythonw, and the Windows `py` launcher --
# matched whole, because `python-helper.exe` and `pythonista` begin with it
# and are not it.
_INTERPRETER = re.compile(r"python[0-9]*(?:\.[0-9]+)*w?|pyw?")


def is_python_interpreter(name: str) -> bool:
    """Whether `name` is the file name of a python interpreter."""
    name = name.lower()

    if name.endswith(".exe"):
        name = name[:-len(".exe")]

    return _INTERPRETER.fullmatch(name) is not None


def running_python_script(arguments):
    """The file name of the script `python <script>` is running, or None.

    Deliberately narrow: `interpreter script [script arguments]`, and nothing
    else. That is every shape this repository launches, and there are only
    four -- the supervisor spawning a worker at an absolute path, `worker_ctl`
    and `start_workers.bat` launching one by bare name from the repository,
    and `swarm_ctl` starting `supervisor.py` with flags after it.

    Narrow on purpose rather than for want of effort. A general reading of a
    python command line has to know which options take a value, that `-c` and
    `-m` end the options and mean no script is being run at all, and what a
    `-` argument means -- and each thing it gets wrong is a process this
    authorizes somebody to kill. `python -m editor gemini_worker.py` runs an
    editor, `python -c gemini_worker.py` runs that text as source code, and a
    reading that scans for the first `.py` calls both of them workers.

    So the script is argv[1] and only argv[1]. Anything beginning with `-`
    there is an interpreter option, which means this is not one of the four
    shapes, which means None. Two launches this repository does not use --
    `python -W ignore worker.py` and an executable `./worker.py` -- are
    refused for the same reason, and refusal costs a worker that is left
    running and reported, never a process killed by mistake.
    """
    if not arguments or len(arguments) < 2:
        return None

    if not is_python_interpreter(_file_name(arguments[0])):
        return None

    script = str(arguments[1])

    # An interpreter option, not a script. `-c` and `-m` are the two that
    # matter -- both consume what follows and run something that is not the
    # file named after them -- but no option at all belongs in the shapes this
    # accepts, so all of them are refused together.
    if script.startswith("-"):
        return None

    name = _file_name(script)

    return name if name.lower().endswith(".py") else None


def _file_name(argument) -> str:
    """The last path segment of an argument, on either platform's separators."""
    return posixpath.basename(str(argument).replace("\\", "/").rstrip("/"))


def process_is_script(pid: int, script: str) -> Optional[bool]:
    """Whether `pid` is running `script`: True, False, or None for cannot tell.

    Three answers rather than two, because the two callers want opposite
    things from the third one.

    True and False are the same fact read two ways. False is not "no worker
    here" in the abstract -- it is "this number is running something else",
    which is exactly what a lock file left by a crashed worker looks like once
    the operating system has reissued its pid.

    None is the honest answer when the command line cannot be read or will not
    parse, and it must never be collapsed into either. A caller deciding
    whether to start treats None as "there may be a worker here" and does not
    start beside it; a caller deciding whether to terminate treats None as "I
    cannot identify this" and does not kill it. Both stay on the safe side of
    the same uncertainty, which is only possible while it is still a distinct
    answer.
    """
    arguments = process_arguments(pid)

    if arguments is None:
        return None

    running = running_python_script(arguments)

    return running is not None and running.lower() == script.lower()


def terminate_pid(pid: int, *, timeout: float = 20.0) -> bool:
    """Stop a process this one did not spawn, and wait. Returns whether it is gone.

    `Popen.terminate` is the right tool for a child, and unavailable for
    anything else: a worker an operator started by hand, or one an earlier
    supervisor left behind, is a real process with no handle in this one.

    Reported rather than assumed. The caller's next line is an operator-facing
    claim about whether the swarm is stopped, and returning True without
    checking is how that claim becomes false.
    """
    if not pid_is_alive(pid):
        return True

    try:
        # On Windows this is TerminateProcess, which is what `Popen.terminate`
        # does to the supervisor's own children -- so an adopted worker is
        # stopped exactly as hard as a supervised one, not more.
        os.kill(pid, signal.SIGTERM)
    except Exception:
        # Already gone, or not ours to signal. Which one is settled by the
        # poll below rather than guessed at here, and nothing raised on the
        # way to stopping one worker may stop the others being stopped.
        pass

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return True

        time.sleep(1.0)

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=30, check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    deadline = time.monotonic() + 10.0

    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return True

        time.sleep(1.0)

    return not pid_is_alive(pid)


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
                        # The hub's instant, written out. `timestamp` is kept
                        # exactly as it arrived -- anything already reading
                        # this file expects a float there -- and this is the
                        # same moment in the form a person reading the log can
                        # act on. `recorded_at` below is a different fact: when
                        # this host wrote the line, which can be much later
                        # after a worker has been down, and the two being
                        # confusable is why both are now named unambiguously.
                        "timestamp_utc": message_stamp(message),
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
