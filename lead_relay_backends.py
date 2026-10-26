"""What the wake-up relay knows about sessions and processes (#113).

Split out of `lead_relay.py` to keep each module within the per-file view
budget (`authored_change.DEFAULT_FILE_VIEW`). Section numbers refer to
`docs/design/113-lead-relay.md`. `lead_relay` re-exports every name here.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import lead_chat

log = logging.getLogger("lead_relay")

# --- Process facts (§5, §6) ------------------------------------------------------


class ProcessApi:
    """Is a pid alive, and is it still the process that was recorded?

    A pid alone is not identity: Windows reuses them. The creation time is,
    and Claude Code records the same value (`procStart`, FILETIME ticks).
    """

    def creation_time(self, pid: int) -> Optional[str]:
        if os.name != "nt":
            try:
                with open(f"/proc/{pid}/stat", encoding="utf-8") as stat:
                    return stat.read().rsplit(")", 1)[1].split()[19]
            except (OSError, IndexError):
                return None

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                            ctypes.byref(kernel), ctypes.byref(user)):
                return None
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:
                return None  # STILL_ACTIVE is 259; anything else has exited
            return str(created.value)
        finally:
            kernel32.CloseHandle(handle)

    def is_same(self, pid: Optional[int], proc_start: Optional[str]) -> bool:
        return bool(pid) and bool(proc_start) and self.creation_time(pid) == proc_start

    def snapshot(self) -> list["Proc"]:
        """Every process on the host, in one read. Raises when it can't be read.

        Windows: one `NtQuerySystemInformation` call, which gives each
        process's pid, parent pid, image name and creation time without
        opening it, so a process this user may not open (205 of 484 on the
        lead host) is still seen. POSIX: `/proc`.
        """
        return _nt_snapshot() if os.name == "nt" else _proc_snapshot()

    def job_members(self, name: str) -> Optional[list[int]]:
        """The live pids in the named job, or None when the job no longer
        exists. Raises on any other failure (access denied is not absence)."""
        if os.name != "nt":
            raise OSError("a Windows job can only be queried on Windows")
        return _job_members(name)

    def kill_tree(self, pid: int) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            try:
                os.killpg(os.getpgid(pid), 9)
            except OSError:
                pass


# --- Backends (§7) ---------------------------------------------------------------

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"


@dataclass
class Session:
    recipient: str
    backend: str
    session_id: str
    workspace: str
    cli: Optional[str]
    enabled: bool


class ClaudeBackend:
    """`claude -p --resume <id>`; ownership from `~/.claude/sessions/<pid>.json`.

    That file is internal to Claude Code, not a documented API. Anything it
    does not recognise is UNKNOWN, which holds the delivery (§7: unknown is busy).
    """

    name = "claude"
    REQUIRED = ("pid", "sessionId", "procStart", "kind")

    def __init__(self, processes: ProcessApi, sessions_dir: Optional[Path] = None):
        self.processes = processes
        self.sessions_dir = sessions_dir or Path.home() / ".claude" / "sessions"

    def ownership(self, session: Session) -> str:
        try:
            records = list(self.sessions_dir.glob("*.json"))
        except OSError:
            return UNKNOWN

        matched = []
        for path in records:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return UNKNOWN  # an unreadable record could be this session
            if not isinstance(record, dict) or not all(k in record for k in self.REQUIRED):
                return UNKNOWN
            if record["sessionId"] == session.session_id:
                matched.append(record)

        if not matched:
            return CLOSED

        for record in matched:
            try:
                pid = int(record["pid"])
            except (TypeError, ValueError):
                return UNKNOWN
            if self.processes.is_same(pid, str(record["procStart"])):
                return OPEN
        # A record for this session whose process is gone, or whose pid now
        # names another process: stale, and stale is not proof of idle.
        return UNKNOWN

    def command(self, session: Session) -> list[str]:
        """The prompt is not here: `claude -p` reads it from stdin when no
        prompt argument is given, which keeps the message and its token out
        of argv (Codex design §4; checked on 2.1.303 with and without --resume)."""
        return [session.cli or "claude", "-p", "--resume", session.session_id,
                "--output-format", "json"]

    def transcript_mentions(self, session: Session, token: str) -> Optional[bool]:
        projects = Path.home() / ".claude" / "projects"
        try:
            for path in projects.glob(f"*/{session.session_id}.jsonl"):
                with open(path, encoding="utf-8", errors="replace") as handle:
                    return any(token in line for line in handle)
        except OSError:
            return None
        return None


# `CodexBackend` is in `lead_relay_codex.py`.


# --- Locks, keys and the child process (§5, §6, §8) ----------------------------


class AlreadyRunning(Exception):
    """Another live relay owns this database."""


def acquire_lock(path: Path) -> int:
    """Hold an OS lock on `path` for this process's lifetime, or AlreadyRunning.

    The kernel releases it when the process dies, so a crashed relay leaves
    no stale lock behind. The descriptor is returned so the caller keeps it open.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise AlreadyRunning(f"another relay holds {path}") from None
    return fd


def session_key(session: "Session") -> str:
    """One actual conversation, whichever lead name it is registered under."""
    return f"{session.backend}:{session.session_id.lower()}"


def separate_process_group(system: str = os.name) -> dict:
    """Popen options that put a woken run in its own process group, so a
    timeout's tree kill can never reach the relay or its siblings (review bot,
    #116 at 2bd1623). Windows: a new group with no console window."""
    if system == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | 0x08000000}
    return {"start_new_session": True}


def child_environment(environ, recipient: str) -> dict:
    """The woken lead's environment: the user's, minus every hub credential
    except its own. The supervisor's environment carries `HUB_SECRET` (admin)
    and the workers' secrets, and none of them belongs to a woken lead."""
    own = lead_chat.IDENTITIES[recipient]
    return {k: v for k, v in environ.items()
            if k.upper() == own
            or not (k.upper() == "HUB_SECRET" or k.upper().endswith("_HUB_SECRET"))}


# --- Termination provenance, containment and the process table --------------------
# docs/design/relay-successor-transition.md §2.5, §2.8 and §3.


def migrate_provenance(db, columns) -> None:
    """`lead_relay.migrate`'s step for the successor transition. Idempotent.

    `attempts.ended_by` is how the relay itself saw a run end, written in the
    same statement that marks it `exited`: `timeout` only from the timeout
    path's kill, else `exit`, `spawn-io` or `recovery`. `attempts.container`
    names the durable container the run was launched into (`popen_contained`).
    Rows from before have neither. `meta.provenance_since` is when this
    database began recording `ended_by`, so a run that ended earlier is known
    to predate provenance rather than to lack it.
    """
    db.execute("INSERT OR IGNORE INTO meta VALUES ('provenance_since', ?)", (repr(time.time()),))
    for column in ("ended_by", "container"):
        if column not in columns:
            db.execute(f"ALTER TABLE attempts ADD COLUMN {column} TEXT")


@dataclass(frozen=True)
class Proc:
    """One live process. `start` is in `proc_start`'s units, `created` in
    epoch seconds. Either is None when it could not be read, which the
    successor check refuses on, never reads as absence."""
    pid: int
    ppid: int
    start: Optional[str]
    name: str
    created: Optional[float]
    group: Optional[int] = None     # POSIX process group
    session: Optional[int] = None   # POSIX session


# Global, so the job is the same object from any logon session (a `Local`
# name would read as "not found" from another one, which is not absence).
JOB_PREFIX = "Global\\lead-relay-"
FILETIME_EPOCH = 116444736000000000   # 1601-01-01 to 1970-01-01 in 100 ns ticks
CREATE_SUSPENDED = 0x4


def popen_contained(attempt_id: str, command: list[str], **options) -> subprocess.Popen:
    """Start a woken run inside a durable container. `handle.container` names
    it (None when it could not be made), and is stored with the pid.

    POSIX: the run's own session (`separate_process_group`), `session:<pid>`.
    Windows: a job, `job:<name>`, created KILL_ON_JOB_CLOSE with one
    inheritable handle that only the child inherits. The child is created
    suspended and assigned before it runs, so every process it ever starts is
    in the job (breakaway is not allowed). The relay closes its own handle at
    once, so the job outlives a relay restart for as long as some member
    holds it. When the last holder ends, the kernel ends every other member
    and destroys the job. So "the job no longer exists" proves nothing of the
    run is alive, and "it exists" lists exactly what is.
    """
    if os.name != "nt":
        handle = subprocess.Popen(command, **options)
        handle.container = f"session:{handle.pid}" if options.get("start_new_session") else None
        return handle
    name = JOB_PREFIX + attempt_id
    job = _new_job(name)
    if job is None:
        handle = subprocess.Popen(command, **options)
        handle.container = None
        return handle
    kernel32 = _kernel32()
    try:
        options["creationflags"] = options.get("creationflags", 0) | CREATE_SUSPENDED
        options["startupinfo"] = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [job]})
        handle = subprocess.Popen(command, **options)
        if not hasattr(handle, "_handle"):   # a test double: nothing was started
            handle.container = None
            return handle
        assigned = bool(kernel32.AssignProcessToJobObject(job, int(handle._handle)))
        if not assigned:
            log.warning("could not assign %s to its job (error %s); it runs uncontained",
                      attempt_id, ctypes.get_last_error())
        if not _resume(handle.pid):
            handle.kill()
            raise OSError("the suspended run could not be resumed")
        handle.container = f"job:{name}" if assigned else None
        return handle
    finally:
        kernel32.CloseHandle(job)


def _kernel32():
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name in ("CreateJobObjectW", "OpenJobObjectW", "OpenProcess", "OpenThread",
                 "CreateToolhelp32Snapshot"):
        getattr(kernel32, name).restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    return kernel32


def _new_job(name: str):
    """An inheritable KILL_ON_JOB_CLOSE job handle, or None (a WARNING; the
    run then goes uncontained and falls under the window check, §2.8).

    Kill-on-close is what makes "no such job" proof. A job's name lives only
    as long as some handle to it: with root -> wrapper -> worker, once the
    root (the only holder) exits, the job can no longer be opened by name
    although the worker is still in it (checked on the lead host; see
    `test_without_kill_on_close_a_live_member_does_not_keep_the_job_name`)."""
    from ctypes import wintypes

    class Security(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = _kernel32()
    security = Security(ctypes.sizeof(Security), None, True)
    ctypes.set_last_error(0)
    job = kernel32.CreateJobObjectW(ctypes.byref(security), name)
    error = ctypes.get_last_error()
    if not job or error == 183:   # ERROR_ALREADY_EXISTS: not ours to vouch for
        if job:
            kernel32.CloseHandle(job)
        log.warning("could not create job %s (error %s); the run is uncontained", name, error)
        return None
    limits = Extended()
    limits.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        log.warning("could not make job %s kill-on-close (error %s); the run is uncontained",
                  name, ctypes.get_last_error())
        kernel32.CloseHandle(job)
        return None
    return job


def _resume(pid: int) -> bool:
    """Resume the threads of a process created suspended (its main thread)."""
    from ctypes import wintypes

    class Thread(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD)]

    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(0x4, 0)   # TH32CS_SNAPTHREAD
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return False
    resumed = 0
    try:
        entry = Thread()
        entry.dwSize = ctypes.sizeof(Thread)
        more = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)  # SUSPEND_RESUME
                if thread:
                    resumed += kernel32.ResumeThread(thread) != 0xFFFFFFFF
                    kernel32.CloseHandle(thread)
            more = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return resumed > 0


def _job_members(name: str) -> Optional[list[int]]:
    from ctypes import wintypes

    class PidList(ctypes.Structure):   # JOBOBJECT_BASIC_PROCESS_ID_LIST
        _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                    ("pids", ctypes.c_size_t * 4096)]

    kernel32 = _kernel32()
    job = kernel32.OpenJobObjectW(0x0004, False, name)   # JOB_OBJECT_QUERY
    if not job:
        error = ctypes.get_last_error()
        if error == 2:   # ERROR_FILE_NOT_FOUND: destroyed, every member ended
            return None
        raise OSError(f"could not open job {name} (error {error})")
    try:
        info = PidList()
        if not kernel32.QueryInformationJobObject(job, 3, ctypes.byref(info), ctypes.sizeof(info),
                                                  None):
            raise OSError(f"could not query job {name} (error {ctypes.get_last_error()})")
        if info.listed != info.assigned:
            raise OSError(f"job {name} lists {info.listed} of {info.assigned} processes")
        return [int(info.pids[i]) for i in range(info.listed)]
    finally:
        kernel32.CloseHandle(job)


def _nt_snapshot() -> list[Proc]:
    from ctypes import wintypes

    class Name(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_void_p)]

    class Entry(ctypes.Structure):   # SYSTEM_PROCESS_INFORMATION, as far as the parent pid
        _fields_ = [("NextEntryOffset", wintypes.ULONG), ("NumberOfThreads", wintypes.ULONG),
                    ("WorkingSetPrivateSize", ctypes.c_longlong),
                    ("HardFaultCount", wintypes.ULONG),
                    ("NumberOfThreadsHighWatermark", wintypes.ULONG),
                    ("CycleTime", ctypes.c_ulonglong), ("CreateTime", ctypes.c_longlong),
                    ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                    ("ImageName", Name), ("BasePriority", ctypes.c_long),
                    ("UniqueProcessId", ctypes.c_void_p),
                    ("InheritedFromUniqueProcessId", ctypes.c_void_p)]

    query = ctypes.WinDLL("ntdll").NtQuerySystemInformation
    query.restype = ctypes.c_long
    size, status = 1 << 20, -1
    for _ in range(8):
        buffer, needed = ctypes.create_string_buffer(size), ctypes.c_ulong()
        status = query(5, buffer, size, ctypes.byref(needed))   # SystemProcessInformation
        if status & 0xFFFFFFFF != 0xC0000004:                   # STATUS_INFO_LENGTH_MISMATCH
            break
        size = max(size * 2, needed.value + (1 << 16))
    if status != 0:
        raise OSError(f"NtQuerySystemInformation failed (0x{status & 0xFFFFFFFF:08x})")
    rows, offset, base = [], 0, ctypes.addressof(buffer)
    while True:
        entry = Entry.from_address(base + offset)
        pid = entry.UniqueProcessId or 0
        # Every entry counts as live. An exited process that something still
        # holds a handle to is not listed (checked on the lead host), and a
        # process with no threads (`Secure System`) is listed and is live.
        name = ctypes.wstring_at(entry.ImageName.Buffer, entry.ImageName.Length // 2) \
            if entry.ImageName.Buffer else ""
        rows.append(Proc(pid, entry.InheritedFromUniqueProcessId or 0, str(entry.CreateTime),
                         name, (entry.CreateTime - FILETIME_EPOCH) / 1e7))
        if not entry.NextEntryOffset:
            break
        offset += entry.NextEntryOffset
    return rows


def _proc_snapshot() -> list[Proc]:
    boot = next((float(line.split()[1]) for line in
                 Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                 if line.startswith("btime ")), None)
    if boot is None:
        raise OSError("/proc/stat has no btime")
    ticks, rows = os.sysconf("SC_CLK_TCK"), []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        pid = int(stat.parent.name)
        try:
            raw = stat.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, ProcessLookupError):
            continue   # exited while we looked
        except OSError:
            rows.append(Proc(pid, 0, None, "?", None))
            continue
        try:
            head, tail = raw.rsplit(")", 1)
            fields = tail.split()
            if fields[0] in ("Z", "X"):
                continue   # exited, not yet reaped
            rows.append(Proc(pid, int(fields[1]), fields[19], head.split("(", 1)[1],
                             boot + int(fields[19]) / ticks, int(fields[2]), int(fields[3])))
        except (IndexError, ValueError):
            rows.append(Proc(pid, 0, None, "?", None))
    if not rows:
        raise OSError("the process table was empty")
    return rows
