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

    def command(self, session: Session, prompt: str) -> list[str]:
        return [session.cli or "claude", "-p", "--resume", session.session_id,
                "--output-format", "json", prompt]

    def transcript_mentions(self, session: Session, token: str) -> Optional[bool]:
        projects = Path.home() / ".claude" / "projects"
        try:
            for path in projects.glob(f"*/{session.session_id}.jsonl"):
                with open(path, encoding="utf-8", errors="replace") as handle:
                    return any(token in line for line in handle)
        except OSError:
            return None
        return None


class CodexBackend:
    """`codex exec resume <id>`. Provisional: ownership is not yet established
    (§7), so it is always UNKNOWN and nothing is ever launched into it."""

    name = "codex"

    def ownership(self, session: Session) -> str:
        return UNKNOWN

    def command(self, session: Session, prompt: str) -> list[str]:
        return [session.cli or "codex", "exec", "resume", session.session_id, prompt, "--json"]

    def transcript_mentions(self, session: Session, token: str) -> Optional[bool]:
        return None


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
