"""The Codex lead's backend for the wake-up relay: the CLOSED path (#113).

The contract is `docs/design/113-codex-ownership.md` (approved at b9f9f17).
Section numbers below refer to it. Only the headless `codex exec resume` path
is here. The OPEN-path queue stays disabled: no safe attachment to the
desktop-owned thread was shown (#120, comment 6274464189), so an OPEN Codex
lead gets today's notice-only live path and nothing in this module submits
work into an open thread.

Everything read here is Codex's internal storage, not a public API. Anything
unexpected is UNKNOWN, which holds the delivery. Nothing here ever writes to
the Codex data directory: no lock file is removed and no turn row is changed
to make a thread look idle (§2).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional

from lead_relay_backends import CLOSED, OPEN, UNKNOWN, Session

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
THREAD_COLUMNS = {"id", "rollout_path", "cwd"}
TURN_COLUMNS = {"thread_id", "status"}
HELD, FREE = "held", "free"


def probe_lock(path: Path) -> str:
    """HELD if another process holds the thread's writer lock, else FREE.

    A non-blocking lock attempt, released before returning: this never keeps
    the lock across a return, let alone across a spawn (§2). A crashed writer
    leaves the file behind but the OS drops its lock, so the probe, unlike a
    file-existence check, does not mistake a stale file for an open thread.
    Any other failure raises, and the caller answers UNKNOWN.
    """
    if not path.exists():
        return FREE
    fd = os.open(path, os.O_RDONLY)
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (13, 36):   # EACCES, EDEADLOCK: held by another process
                    return HELD
                raise
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return HELD
            fcntl.flock(fd, fcntl.LOCK_UN)
        return FREE
    finally:
        os.close(fd)


def _read_only(db: Path):
    """A read-only connection that is CLOSED on exit. (`with sqlite3.connect()`
    alone only commits; it would leave a handle open on Codex's database.)"""
    if not db.is_file():
        raise FileNotFoundError(db)
    return closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2))


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _plain(path: str) -> str:
    """Codex stores Windows paths in extended-length form (`\\\\?\\C:\\...`)."""
    return path[4:] if path.startswith("\\\\?\\") else path


def _same_path(a: str, b: str) -> bool:
    norm = lambda p: os.path.normcase(os.path.normpath(_plain(p)))  # noqa: E731
    return norm(a) == norm(b)


def desktop_app_server() -> Optional[str]:
    """The ExecutablePath of a running desktop `codex.exe app-server`, if any."""
    if os.name != "nt":
        return None
    script = ("Get-CimInstance Win32_Process -Filter \"Name='codex.exe'\" | Where-Object "
              "{ $_.CommandLine -match ' app-server' -and $_.ExecutablePath -match "
              "'\\\\OpenAI\\\\Codex\\\\bin\\\\' } | Select-Object -First 1 -ExpandProperty ExecutablePath")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=15, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


class CodexBackend:
    """`codex exec resume`, with ownership from the thread's writer lock (§2)."""

    name = "codex"
    # §2: `_hold_reason` asks every tick. Re-probe a held delivery at most this
    # often; only OPEN and UNKNOWN answers are reused, never CLOSED.
    probe_interval = 60.0

    def __init__(self, codex_home: Optional[Path] = None, *,
                 probe: Callable[[Path], str] = probe_lock,
                 app_server: Callable[[], Optional[str]] = desktop_app_server,
                 bin_dir: Optional[Path] = None):
        self.home = Path(codex_home) if codex_home else Path.home() / ".codex"
        self.probe = probe
        self.app_server = app_server
        self.bin_dir = bin_dir or Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"

    # --- §2 ownership

    def ownership(self, session: Session) -> str:
        try:
            thread = session.session_id.lower()
            if not UUID.fullmatch(thread) or not self.home.is_dir():
                return UNKNOWN
            if self._rollout(session) is None:
                return UNKNOWN
            if self.probe(self.home / "thread-writer-locks" / f"{thread}.lock") == HELD:
                return OPEN
            return UNKNOWN if self._turn_in_progress(thread) else CLOSED
        except Exception:  # noqa: BLE001 -- unreadable is not idle (§2)
            return UNKNOWN

    def _rollout(self, session: Session) -> Optional[Path]:
        """The thread's rollout, after checking the binding it records.

        The `threads` row must name this thread, its workspace must be the
        registered one, and its rollout must exist. A workspace that differs
        is not "unchanged" (§4), so it is UNKNOWN rather than a launch.
        """
        thread = session.session_id.lower()
        with _read_only(self.home / "state_5.sqlite") as conn:
            if not THREAD_COLUMNS <= _columns(conn, "threads"):
                return None
            row = conn.execute("SELECT rollout_path, cwd FROM threads WHERE lower(id) = ?",
                               (thread,)).fetchone()
        if row is None or not row[0] or not row[1] or not _same_path(row[1], session.workspace):
            return None
        rollout = Path(_plain(row[0]))
        if not rollout.is_file() or thread not in rollout.name.lower():
            return None
        return rollout

    def _turn_in_progress(self, thread: str) -> bool:
        """A turn row still `inProgress`. Raises when the table is not as expected."""
        with _read_only(self.home / "thread_history_1.sqlite") as conn:
            if not TURN_COLUMNS <= _columns(conn, "thread_turns"):
                raise LookupError("thread_turns schema changed")
            count = conn.execute("SELECT COUNT(*) FROM thread_turns WHERE lower(thread_id) = ? "
                                 "AND status = 'inProgress'", (thread,)).fetchone()[0]
        return count > 0

    # --- §4 launch

    def cli(self, session: Session) -> str:
        """Resolved at spawn, never cached: the bin\\<hash> folder moves on update."""
        if session.cli and Path(session.cli).is_file():
            return session.cli
        running = self.app_server()
        if running and Path(running).is_file():
            return running
        found = sorted(self.bin_dir.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime)
        if found:
            return str(found[-1])
        raise FileNotFoundError("no Codex CLI: none registered, running or installed")

    def command(self, session: Session) -> list[str]:
        """The prompt is not here: it goes on stdin (`-`), out of argv (§4)."""
        return [self.cli(session), "exec", "resume", "--json", session.session_id, "-"]

    def transcript_mentions(self, session: Session, token: str) -> Optional[bool]:
        try:
            rollout = self._rollout(session)
            if rollout is None or rollout.suffix != ".jsonl":
                return None   # missing, or compressed (.jsonl.zst): no evidence
            with open(rollout, encoding="utf-8", errors="replace") as handle:
                return any(token in line for line in handle)
        except Exception:  # noqa: BLE001 -- evidence only; never decides anything
            return None


# --- §5 a local duration guard for Codex runs ------------------------------------


def codex_usage(path: Path, *, budget_seconds: float, window_seconds: float = 5 * 3600,
                now: Callable[[], float] = time.time):
    """(check, record) over a small JSON file of (start, elapsed) runs.

    A local budget only: it bounds how much headless Codex time the relay
    starts in a window. It says nothing about the Codex account's own quota.
    An unreadable file raises from `check`, which the relay treats as
    `guard-unavailable` (fail closed), and from `record`, which it retries.
    """
    def load() -> list:
        if not path.exists():
            return []
        runs = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(runs, list):
            raise ValueError(f"{path} is not a list")
        return runs

    def check() -> Optional[str]:
        cutoff = now() - window_seconds
        used = sum(float(run[1]) for run in load() if float(run[0]) + float(run[1]) > cutoff)
        return "codex-budget" if used >= budget_seconds else None

    def record(start: float, elapsed: float) -> None:
        cutoff = now() - window_seconds
        runs = [run for run in load() if float(run[0]) + float(run[1]) > cutoff]
        runs.append([float(start), float(elapsed)])
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(runs), encoding="utf-8")
        os.replace(tmp, path)

    return check, record
