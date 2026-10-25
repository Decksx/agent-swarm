"""What the wake-up relay knows about sessions and processes (#113).

Split out of `lead_relay.py` to keep each module within the per-file view
budget (`authored_change.DEFAULT_FILE_VIEW`). Section numbers refer to
`docs/design/113-lead-relay.md`. `lead_relay` re-exports every name here.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import lead_chat

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

    def descendants(self, pid: int, proc_start: str) -> list[int]:
        """Live processes that may still belong to the tree rooted at
        (pid, proc_start). Raises when the process table can't be read.

        Windows keeps a dead parent's pid in each child's entry, so the tree
        is followed by parent pid, counting only processes created after
        their parent: a reused pid's own children are newer than the reuse,
        so they still count, which is a refusal, never a false "gone". On
        POSIX a woken run is its own process group (`separate_process_group`).
        """
        if os.name != "nt":
            members = []
            for stat in Path("/proc").glob("[0-9]*/stat"):
                try:
                    fields = stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
                except (OSError, IndexError):
                    continue  # exited while we looked
                if int(fields[2]) == pid and int(stat.parent.name) != pid:
                    members.append(int(stat.parent.name))
            return members
        children: dict[int, list[int]] = {}
        for child, parent in self._windows_table():
            children.setdefault(parent, []).append(child)
        found, todo = [], [(pid, int(proc_start))]
        while todo:
            parent, born = todo.pop()
            for child in children.get(parent, ()):
                start = self.creation_time(child)
                if child not in found and start is not None and int(start) >= born:
                    found.append(child)
                    todo.append((child, int(start)))
        return found

    @staticmethod
    def _windows_table() -> list[tuple[int, int]]:
        """(pid, parent pid) for every process, from a Toolhelp snapshot."""
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry, rows = Entry(), []
            entry.dwSize = ctypes.sizeof(Entry)
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                rows.append((entry.th32ProcessID, entry.th32ParentProcessID))
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            if not rows:
                raise OSError("the process snapshot was empty")
            return rows
        finally:
            kernel32.CloseHandle(snapshot)

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
