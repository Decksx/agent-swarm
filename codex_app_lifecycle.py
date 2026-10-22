"""Close and reopen the Codex desktop app around a bounded CLOSED proof (#113).

David agreed (hive #1893) that Claude closes the app gracefully once its work
is finished, and reopens it once the proof has cleaned up. This module does
only that:

- `status` reports what it would act on, read-only.
- `close` waits a bounded time for the app's current work to finish, rechecks
  the main process's identity, asks Windows' Restart Manager to shut it down
  WITHOUT the force flag (the logoff path), and then verifies that the app
  and its app-server really exited. There is no force fallback: if the app
  does not go, it is left as it is and the failure reported.
- `reopen` launches the app through the CLI's own `codex app <workspace>`,
  and only once codex-lead is disabled, no proof run is alive, no
  reservation is held and no proof is claimed and unfinished.

It never edits Codex's data and never touches a Codex process it did not
identify as the desktop app (the VS Code extension's app-server included).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
PACKAGE_DIR = "OpenAI.Codex_"          # WindowsApps\OpenAI.Codex_<ver>_x64__<publisher>
MAIN_IMAGE = "ChatGPT.exe"
IDLE_WAIT = 10 * 60      # close: how long to wait for the app's work to finish
EXIT_WAIT = 120          # close: how long the app gets to exit after the request
OPEN_WAIT = 120          # reopen: how long the app-server gets to appear
POLL = 3


def _plain(p: str) -> str:
    return p[4:] if p.startswith("\\\\?\\") else p


class Host:
    """Every side effect, replaceable in tests."""

    def __init__(self, db: Path):
        from lead_relay_backends import ProcessApi
        from lead_relay_codex import CodexBackend, desktop_app_server
        self.db_path = db
        self.processes = ProcessApi()
        self.backend = CodexBackend()
        self.app_server = desktop_app_server

    @property
    def home(self) -> Path:
        """The same Codex data directory the backend's ownership check reads."""
        return self.backend.home

    def now(self) -> float:
        return time.time()

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def say(self, line: str) -> None:
        print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {line}", flush=True)

    def processes_list(self) -> list:
        """[{pid, image, cmd}] for every ChatGPT.exe, via CIM."""
        script = ("Get-CimInstance Win32_Process -Filter \"Name='ChatGPT.exe'\" | ForEach-Object "
                  "{ [pscustomobject]@{pid=$_.ProcessId; image=$_.ExecutablePath; cmd=$_.CommandLine} } "
                  "| ConvertTo-Json -Compress")
        run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30, check=False)
        if run.returncode != 0:
            # A failed query is not an absent app: raise, and the caller refuses.
            raise OSError(f"process query failed ({run.returncode}): {run.stderr.strip()[:200]}")
        out = run.stdout.strip()
        rows = json.loads(out) if out else []
        return rows if isinstance(rows, list) else [rows]

    def rm_shutdown(self, pid: int, created: str, dry_run: bool = False, last_check=None) -> dict:
        """One Restart Manager session for exactly this process. RmGetList must
        show only it, with no reboot reason, before RmShutdown(flags=0): never
        RmForceShutdown, never RmRestart. The session always ends."""
        rm = ctypes.WinDLL("rstrtmgr")

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("pid", ctypes.c_uint32), ("start", FILETIME)]

        class RM_PROCESS_INFO(ctypes.Structure):
            _fields_ = [("process", RM_UNIQUE_PROCESS), ("app_name", ctypes.c_wchar * 256),
                        ("service", ctypes.c_wchar * 64), ("app_type", ctypes.c_int),
                        ("status", ctypes.c_uint32), ("ts_session", ctypes.c_uint32),
                        ("restartable", ctypes.c_int)]

        ticks = int(created)
        proc = RM_UNIQUE_PROCESS(pid, FILETIME(ticks & 0xFFFFFFFF, ticks >> 32))
        session = ctypes.c_uint32()
        key = ctypes.create_unicode_buffer(64)
        rc = rm.RmStartSession(ctypes.byref(session), 0, key)
        if rc:
            return dict(stage="start", rc=rc)
        try:
            rc = rm.RmRegisterResources(session, 0, None, 1, ctypes.byref(proc), 0, None)
            if rc:
                return dict(stage="register", rc=rc)
            needed, count, reasons = ctypes.c_uint32(), ctypes.c_uint32(8), ctypes.c_uint32()
            infos = (RM_PROCESS_INFO * 8)()
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos,
                              ctypes.byref(reasons))
            if rc:
                return dict(stage="list", rc=rc)
            affected = [dict(pid=i.process.pid,
                             created=str((i.process.start.hi << 32) | i.process.start.lo),
                             app_type=i.app_type, service=i.service, name=i.app_name)
                        for i in infos[:count.value]]
            problem = rm_list_problem(affected, reasons.value, pid, created)
            if problem:
                return dict(stage="list", rc=None, problem=problem, affected=affected)
            if dry_run:
                return dict(stage="list", rc=0, affected=affected, reasons=reasons.value)
            # The last word, at the shutdown boundary itself: work that started
            # during the identity check or the list stops it (Codex, 18a7b6b).
            why = last_check() if last_check else None
            if why:
                return dict(stage="list", rc=None, problem=why, affected=affected)
            rc = rm.RmShutdown(session, 0, None)          # 0: never RmForceShutdown
            return dict(stage="shutdown", rc=rc, affected=affected)
        finally:
            rm.RmEndSession(session)

    def ownership(self, b: dict) -> str:
        """The relay backend's own answer for the bound thread: open, closed or unknown."""
        from lead_relay_backends import Session
        return self.backend.ownership(Session("codex-lead", "codex", b["session_id"], b["workspace"],
                                              b["cli"], bool(b["enabled"])))

    def file_sha256(self, path: str) -> str:
        import hashlib
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def launch(self, cli: str, workspace: str) -> int:
        return subprocess.Popen([cli, "app", workspace], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)).pid

    def relay_rows(self, sql: str, *params) -> list:
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def codex_rows(self, sql: str, *params) -> list:
        db = self.home / "thread_history_1.sqlite"
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()


def desktop_main(host) -> Optional[dict]:
    """The desktop app's main process: the packaged ChatGPT.exe with no
    Chromium `--type=` argument. None if the app is not running."""
    mains = [p for p in host.processes_list()
             if p.get("image") and PACKAGE_DIR in p["image"] and p["image"].endswith(MAIN_IMAGE)
             and "--type=" not in (p.get("cmd") or "")]
    if len(mains) != 1:
        return None if not mains else {"ambiguous": [p["pid"] for p in mains]}
    m = mains[0]
    created = host.processes.creation_time(m["pid"])
    return dict(pid=m["pid"], image=m["image"], created=created) if created else None


RM_MAIN_WINDOW, RM_OTHER_WINDOW = 1, 2       # RM_APP_TYPE values for a windowed app


def rm_list_problem(affected: list, reasons: int, pid: int, created: str) -> Optional[str]:
    """Why RmShutdown must not run: anything but exactly the app, as a
    windowed non-service process, with no reboot reason."""
    if reasons:
        return f"Restart Manager reports reboot reasons {reasons:#x}"
    if len(affected) != 1:
        return f"Restart Manager would affect {len(affected)} processes: {affected}"
    a = affected[0]
    if (a["pid"], a["created"]) != (pid, created):
        return f"Restart Manager lists pid {a['pid']} created {a['created']}, not the app"
    if a["service"] or a["app_type"] not in (RM_MAIN_WINDOW, RM_OTHER_WINDOW):
        return f"Restart Manager classes it as type {a['app_type']} service {a['service']!r}"
    return None


# The one known orphan (#133): app quit mid-turn on the retired thread, left
# inProgress for good. Excluded from the live-work inventory by exact pair
# only; its row is never changed, and no successor turn is ever excluded.
RETIRED_ORPHAN = ("01a14068-d723-76a0-a86d-c7d7b34c1b30", "01a1607c-84c8-7d63-bc2b-bb91fa4eb312")
TURN_STATUSES = {"inProgress", "completed", "failed", "interrupted"}


def live_turns(host) -> list:
    """Every inProgress turn in Codex's history except the retired orphan.
    An unknown status raises: an unrecognised layout is not proof of idle."""
    rows = host.codex_rows("SELECT thread_id, turn_id, status FROM thread_turns")
    unknown = {r["status"] for r in rows} - TURN_STATUSES
    if unknown:
        raise LookupError(f"unknown turn status {sorted(map(str, unknown))}")
    return [r["turn_id"] for r in rows if r["status"] == "inProgress"
            and (str(r["thread_id"]).lower(), str(r["turn_id"]).lower()) != RETIRED_ORPHAN]


def binding(host) -> dict:
    """codex-lead's relay binding, which must be the reviewed successor pair."""
    import codex_closed_proof as proof
    rows = host.relay_rows("SELECT session_id, workspace, cli, enabled FROM sessions "
                           "WHERE recipient = 'codex-lead'")
    if len(rows) != 1:
        raise LookupError("codex-lead is not registered")
    b = rows[0]
    if b["session_id"].lower() != proof.THREAD or os.path.normcase(b["workspace"]) != \
            os.path.normcase(proof.WORKSPACE) or not b["cli"]:
        raise LookupError(f"codex-lead binding {b['session_id']} {b['workspace']} is not the successor")
    return b


def settled_problems(host, b: dict) -> list:
    """The successor thread is really free: no live turn, lock free, CLOSED."""
    problems = []
    busy = live_turns(host)
    if busy:
        problems.append(f"turns in progress {busy}")
    own = host.ownership(b)
    if own != "closed":
        problems.append(f"successor ownership is {own}")
    return problems


def close(host) -> int:
    try:
        b = binding(host)
        main = desktop_main(host)
    except Exception as exc:  # noqa: BLE001 -- unknown is not absent
        host.say(f"REFUSED: {type(exc).__name__}: {exc}; app left as is")
        return 1
    if main is None:
        host.say("REFUSED: the Codex desktop app is not running")
        return 1
    if "ambiguous" in main:
        host.say(f"REFUSED: more than one desktop main process {main['ambiguous']}")
        return 1
    host.say(f"desktop app pid {main['pid']} created {main['created']} ({main['image']})")
    deadline = host.now() + IDLE_WAIT
    while True:
        try:
            busy = live_turns(host)
        except Exception as exc:  # noqa: BLE001 -- unreadable is not idle
            host.say(f"REFUSED: cannot read Codex's turns ({type(exc).__name__}: {exc}); app left open")
            return 1
        if not busy:
            break
        if host.now() >= deadline:
            host.say(f"REFUSED: turns still in progress after {IDLE_WAIT // 60} min: {busy}; app left open")
            return 1
        host.sleep(POLL)
    # Identity again, immediately before the request: the same image, pid and
    # creation time, so a reused pid or a relaunched app is never the target.
    try:
        again = desktop_main(host)
    except Exception as exc:  # noqa: BLE001
        host.say(f"REFUSED: {type(exc).__name__}: {exc}; app left as is")
        return 1
    if again != main or not host.processes.is_same(main["pid"], main["created"]):
        host.say(f"REFUSED: the app is no longer the one checked ({again}); app left as is")
        return 1
    def last_check() -> Optional[str]:
        try:
            busy = live_turns(host)
        except Exception as exc:  # noqa: BLE001 -- unreadable is not idle
            return f"cannot read Codex's turns ({type(exc).__name__}: {exc})"
        if busy:
            return f"turns started before shutdown: {busy}"
        if not host.processes.is_same(main["pid"], main["created"]):
            return f"pid {main['pid']} is no longer the app"
        return None

    out = host.rm_shutdown(main["pid"], main["created"], last_check=last_check)
    if out.get("problem"):
        host.say(f"REFUSED before shutdown: {out['problem']}; app left open")
        return 1
    if out["stage"] != "shutdown" or out["rc"]:
        host.say(f"FAILED at Restart Manager {out['stage']} (rc {out['rc']}); nothing was forced, "
                 "app left as is")
        return 1
    host.say("graceful shutdown accepted (Restart Manager, flags 0)")
    deadline = host.now() + EXIT_WAIT
    last = None
    while host.now() < deadline:
        try:
            gone = not host.processes.is_same(main["pid"], main["created"])
            last = (["main alive"] if not gone else []) + \
                (["app-server running"] if host.app_server() is not None else []) + \
                (settled_problems(host, b) if gone else [])
        except Exception as exc:  # noqa: BLE001
            last = [f"{type(exc).__name__}: {exc}"]
        if not last:
            host.say("CLOSED: the app and its app-server exited; the successor is idle and CLOSED")
            return 0
        host.sleep(POLL)
    host.say(f"FAILED: not closed after {EXIT_WAIT}s ({'; '.join(last or [])}); nothing was forced")
    return 1


def reopen_problems(host, b: dict, cli_sha256: str, state_path: Optional[Path]) -> list:
    """Why reopening the app now could collide with a proof; empty means safe."""
    problems = []
    if b["enabled"] != 0:
        problems.append("codex-lead is not confirmed disabled")
    if host.file_sha256(b["cli"]) != cli_sha256:
        problems.append(f"the registered cli {b['cli']} does not have the expected sha256")
    if host.relay_rows("SELECT 1 FROM reservations WHERE recipient = 'codex-lead'"):
        problems.append("codex-lead has a reservation")
    for a in host.relay_rows("SELECT attempt_id, pid, proc_start, usage_recorded FROM attempts "
                             "WHERE recipient = 'codex-lead' AND launched_at IS NOT NULL"):
        if host.processes.is_same(a["pid"], a["proc_start"]):
            problems.append(f"proof run {a['attempt_id']} (pid {a['pid']}) is still alive")
        if not a["usage_recorded"]:
            problems.append(f"usage for {a['attempt_id']} is not recorded")
    if state_path is not None and state_path.is_file():
        if json.loads(state_path.read_text(encoding="utf-8")).get("status") == "claimed":
            problems.append("a proof is claimed and not finished")
    problems += settled_problems(host, b)
    return problems


def reopen(host, cli_sha256: str, state_path: Optional[Path]) -> int:
    """Relaunch through the registered cli and workspace only (never caller-chosen)."""
    try:
        b = binding(host)
        running = desktop_main(host) is not None or host.app_server() is not None
        problems = [] if running else reopen_problems(host, b, cli_sha256, state_path)
    except Exception as exc:  # noqa: BLE001 -- unknown is not safe
        host.say(f"REFUSED, app left closed: {type(exc).__name__}: {exc}")
        return 1
    if running:
        host.say("REFUSED: the desktop app is already running")
        return 1
    if problems:
        host.say("REFUSED, app left closed: " + "; ".join(problems))
        return 1
    pid = host.launch(b["cli"], b["workspace"])
    host.say(f"launched `{b['cli']} app {b['workspace']}` (pid {pid})")
    deadline = host.now() + OPEN_WAIT
    while host.now() < deadline:
        if host.app_server() is not None:
            host.say("OPEN: the desktop app-server is running")
            return 0
        host.sleep(POLL)
    host.say(f"FAILED: no desktop app-server after {OPEN_WAIT}s")
    return 1


def status(host) -> int:
    try:
        turns = live_turns(host)
    except Exception as exc:  # noqa: BLE001
        turns = f"unreadable: {type(exc).__name__}: {exc}"
    main = desktop_main(host)
    # The same Restart Manager path `close` uses, stopping before RmShutdown.
    rm = host.rm_shutdown(main["pid"], main["created"], dry_run=True) \
        if main and "created" in main else None
    print(json.dumps(dict(main=main, app_server=host.app_server(), live_turns=turns,
                          restart_manager=rm), indent=1))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(HERE / "control" / "lead_relay.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("close")
    p = sub.add_parser("reopen")
    p.add_argument("--cli-sha256", required=True, help="expected sha256 of the registered cli")
    args = parser.parse_args(argv)
    db = Path(args.db)
    host = Host(db)
    if args.command == "status":
        return status(host)
    if args.command == "close":
        return close(host)
    import codex_closed_proof
    return reopen(host, args.cli_sha256.lower(), db.with_name(codex_closed_proof.STATE_NAME))


if __name__ == "__main__":
    sys.exit(main())
