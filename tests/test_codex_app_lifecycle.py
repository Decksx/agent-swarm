"""Closing and reopening the Codex desktop app around a CLOSED proof (#113)."""
from __future__ import annotations

import json
import sqlite3

import pytest

import codex_app_lifecycle as life
import lead_relay

IMAGE = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"
SUCCESSOR = "01a1609d-cd64-7bd1-9880-2b5b488509d4"
WORKSPACE = r"C:\git\agent-swarm"
CLI = r"C:\codex\bin\pinned\codex.exe"
HASH = "c" * 64


class Procs:
    def __init__(self):
        self.alive = {}            # pid -> creation ticks

    def creation_time(self, pid):
        return self.alive.get(pid)

    def is_same(self, pid, start):
        return bool(pid) and self.alive.get(pid) == start


class FakeHost:
    def __init__(self, tmp_path):
        self.t, self.lines, self.events = 1000.0, [], []
        self.processes = Procs()
        self.procs = [dict(pid=100, image=IMAGE, cmd=f'"{IMAGE}"'),
                      dict(pid=101, image=IMAGE, cmd=f'"{IMAGE}" --type=renderer'),
                      dict(pid=102, image=IMAGE, cmd=f'"{IMAGE}" --type=gpu-process')]
        self.processes.alive.update({100: "9000", 101: "9001", 102: "9002"})
        self.server = r"C:\codex\bin\x\codex.exe"
        self.turns = [dict(thread_id=SUCCESSOR, turn_id="t-done", status="completed")]
        self.rm_calls, self.rm_result = [], None
        self.during_list, self.shutdowns = None, 0
        self.launches = []
        self.own = "closed"
        self.cli_hash = HASH
        self.db_path = tmp_path / "lead_relay.db"
        db = sqlite3.connect(self.db_path, isolation_level=None)
        db.executescript(lead_relay.SCHEMA)
        db.execute("INSERT INTO sessions VALUES ('codex-lead', 'codex', ?, ?, ?, 0, 0)",
                   (SUCCESSOR, WORKSPACE, CLI))
        db.close()

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        due = [e for e in self.events if e[0] <= self.t]
        self.events = [e for e in self.events if e[0] > self.t]
        for _, fn in due:
            fn()

    def say(self, line):
        self.lines.append(line)

    def processes_list(self):
        return [p for p in self.procs if p["pid"] in self.processes.alive]

    def app_server(self):
        return self.server

    def ownership(self, b):
        if isinstance(self.own, Exception):
            raise self.own
        return "open" if self.server is not None else self.own

    def file_sha256(self, path):
        return self.cli_hash

    def rm_shutdown(self, pid, created, dry_run=False, last_check=None):
        self.rm_calls.append((pid, created, dry_run))
        if self.during_list:
            self.during_list()                  # something happens while the list is read
        if self.rm_result is not None:
            return self.rm_result
        if not dry_run and last_check:
            why = last_check()
            if why:
                return dict(stage="list", rc=None, problem=why, affected=[])
        if not dry_run:                         # the app agrees and exits
            self.shutdowns += 1
            self.at(self.t + 6, self.quit_app)
        return dict(stage="shutdown", rc=0, affected=[])

    def quit_app(self):
        for p in (100, 101, 102):
            self.processes.alive.pop(p, None)
        self.server = None

    def launch(self, cli, workspace):
        self.launches.append((cli, workspace))
        self.at(self.t + 4, lambda: setattr(self, "server", r"C:\codex\bin\x\codex.exe"))
        return 4242

    def codex_rows(self, sql, *params):
        if isinstance(self.turns, Exception):
            raise self.turns
        return [dict(r) for r in self.turns]

    def relay_rows(self, sql, *params):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def sql(self, sql, *params):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute(sql, params)
        conn.close()

    def at(self, t, fn):
        self.events.append((t, fn))


@pytest.fixture
def h(tmp_path):
    return FakeHost(tmp_path)


def closed(h):
    h.quit_app()
    return h


def attempt(h, alive=False, usage=1):
    h.sql("INSERT INTO attempts (attempt_id, message_id, recipient, token, path, state, created_at, "
          "launched_at, pid, proc_start, usage_recorded, backend) VALUES ('a1', 1, 'codex-lead', 't', "
          "'headless', 'done', 0, 1, 555, 's555', ?, 'codex')", usage)
    if alive:
        h.processes.alive[555] = "s555"


# --- finding the app ------------------------------------------------------------

def test_the_main_process_is_the_packaged_app_without_a_type_argument(h):
    assert life.desktop_main(h) == dict(pid=100, image=IMAGE, created="9000")


@pytest.mark.parametrize("change", ["vscode", "other-package", "renderer-only"])
def test_nothing_else_is_taken_for_the_app(h, change):
    if change == "vscode":
        h.procs = [dict(pid=100, image=r"c:\Users\d\.vscode\extensions\openai\ChatGPT.exe", cmd="x")]
    elif change == "other-package":
        h.procs = [dict(pid=100, image=r"C:\Program Files\WindowsApps\Other_1\app\ChatGPT.exe", cmd="x")]
    else:
        h.procs = [p for p in h.procs if p["pid"] != 100]
    assert life.desktop_main(h) is None


def test_two_main_processes_are_ambiguous(h):
    h.procs.append(dict(pid=200, image=IMAGE, cmd=f'"{IMAGE}"'))
    h.processes.alive[200] = "9100"
    assert life.desktop_main(h) == {"ambiguous": [100, 200]}
    assert life.close(h) == 1 and h.rm_calls == []


def test_a_failed_process_query_is_never_an_absent_app(h):
    def broken():
        raise OSError("process query failed (1)")
    h.processes_list = broken
    assert life.close(h) == 1 and h.rm_calls == []
    h.server = None
    assert life.reopen(h, HASH, None) == 1 and h.launches == []
    assert "process query failed" in h.lines[-1]


# --- live work ------------------------------------------------------------------

def test_only_the_exact_retired_orphan_is_excluded(h):
    h.turns = [dict(thread_id="01a14068-d723-76a0-a86d-c7d7b34c1b30",
                    turn_id="01a1607c-84c8-7d63-bc2b-bb91fa4eb312", status="inProgress"),
               dict(thread_id="01a14068-d723-76a0-a86d-c7d7b34c1b30", turn_id="other", status="inProgress"),
               dict(thread_id=SUCCESSOR, turn_id="01a1607c-84c8-7d63-bc2b-bb91fa4eb312",
                    status="inProgress")]
    assert life.live_turns(h) == ["other", "01a1607c-84c8-7d63-bc2b-bb91fa4eb312"]


def test_an_unknown_turn_status_is_not_idle(h):
    h.turns = [dict(thread_id=SUCCESSOR, turn_id="t", status="paused")]
    with pytest.raises(LookupError):
        life.live_turns(h)
    assert life.close(h) == 1 and h.rm_calls == [] and "cannot read" in h.lines[-1]


def test_unreadable_turns_refuse(h):
    h.turns = sqlite3.OperationalError("database is locked")
    assert life.close(h) == 1 and h.rm_calls == []


# --- the binding ----------------------------------------------------------------

@pytest.mark.parametrize("session, workspace", [
    ("01a14068-d723-76a0-a86d-c7d7b34c1b30", WORKSPACE),
    (SUCCESSOR, r"C:\Users\david\Documents\Codex"),
])
def test_close_and_reopen_refuse_a_binding_that_is_not_the_successor(h, session, workspace):
    h.sql("UPDATE sessions SET session_id = ?, workspace = ?", session, workspace)
    assert life.close(h) == 1 and h.rm_calls == []
    closed(h)
    assert life.reopen(h, HASH, None) == 1 and h.launches == []
    assert "not the successor" in h.lines[-1]


# --- close ----------------------------------------------------------------------

def test_close_waits_for_live_work_then_closes_gracefully(h):
    h.turns = [dict(thread_id=SUCCESSOR, turn_id="busy", status="inProgress")]
    h.at(1030, lambda: setattr(h, "turns", [dict(thread_id=SUCCESSOR, turn_id="busy",
                                                 status="completed")]))
    assert life.close(h) == 0
    assert h.rm_calls == [(100, "9000", False)] and h.t >= 1030
    assert "CLOSED" in h.lines[-1]


def test_close_gives_up_on_busy_work_without_touching_the_app(h):
    h.turns = [dict(thread_id=SUCCESSOR, turn_id="busy", status="inProgress")]
    assert life.close(h) == 1
    assert h.rm_calls == [] and 100 in h.processes.alive
    assert h.t - 1000 >= life.IDLE_WAIT


def test_close_refuses_when_the_app_is_not_running(h):
    h.processes.alive.clear()
    assert life.close(h) == 1 and h.rm_calls == []


def test_a_relaunched_app_is_never_the_target(h):
    """Identity is rechecked right before the request."""
    h.turns = [dict(thread_id=SUCCESSOR, turn_id="busy", status="inProgress")]

    def relaunch():
        h.processes.alive[100] = "9999"                   # same pid, new process
        h.turns = []
    h.at(1010, relaunch)
    assert life.close(h) == 1 and h.rm_calls == []


@pytest.mark.parametrize("result, word", [
    (dict(stage="list", rc=None, problem="would affect 2 processes"), "REFUSED before shutdown"),
    (dict(stage="register", rc=5), "FAILED at Restart Manager register"),
    (dict(stage="shutdown", rc=1053), "FAILED at Restart Manager shutdown"),
])
def test_a_restart_manager_refusal_leaves_the_app_alone(h, result, word):
    h.rm_result = result
    assert life.close(h) == 1
    assert word in h.lines[-1] and 100 in h.processes.alive


def test_an_app_that_only_hides_is_a_failure_not_a_close(h):
    h.rm_result = dict(stage="shutdown", rc=0, affected=[])      # accepted, but stays up
    assert life.close(h) == 1
    assert "main alive" in h.lines[-1] and h.t - 1000 >= life.EXIT_WAIT


def test_the_app_server_must_go_too(h):
    def half_quit():
        h.processes.alive.pop(100, None)                          # main gone, server stays
    h.rm_result = dict(stage="shutdown", rc=0, affected=[])
    h.at(1006, half_quit)
    assert life.close(h) == 1 and "app-server running" in h.lines[-1]


@pytest.mark.parametrize("after", ["own-unknown", "turn-starts", "own-raises"])
def test_close_succeeds_only_once_the_successor_is_closed_and_idle(h, after):
    if after == "own-unknown":
        h.own = "unknown"
    elif after == "turn-starts":
        h.at(1005, lambda: setattr(h, "turns", [dict(thread_id=SUCCESSOR, turn_id="new",
                                                     status="inProgress")]))
    else:
        h.own = RuntimeError("lock probe failed")
    assert life.close(h) == 1
    assert "FAILED: not closed" in h.lines[-1]


# --- the Restart Manager list gate ---------------------------------------------

GOOD = [dict(pid=100, created="9000", app_type=1, service="", name="Codex")]


@pytest.mark.parametrize("affected, reasons, why", [
    (GOOD, 0, None),
    ([dict(GOOD[0], app_type=2)], 0, None),
    (GOOD, 1, "reboot reasons"),
    (GOOD + [dict(pid=7, created="1", app_type=1, service="", name="x")], 0, "affect 2"),
    ([], 0, "affect 0"),
    ([dict(GOOD[0], pid=101)], 0, "not the app"),
    ([dict(GOOD[0], created="9001")], 0, "not the app"),
    ([dict(GOOD[0], app_type=3)], 0, "type 3"),
    ([dict(GOOD[0], app_type=1000)], 0, "type 1000"),
    ([dict(GOOD[0], service="svc")], 0, "service"),
])
def test_rm_list_gate(affected, reasons, why):
    problem = life.rm_list_problem(affected, reasons, 100, "9000")
    assert (problem is None) if why is None else (why in problem)


class FakeRm:
    """rstrtmgr.dll, as ctypes sees it: records every call."""

    def __init__(self, listed, reasons=0, shutdown_rc=0, register_rc=0):
        self.listed, self.reasons, self.shutdown_rc, self.register_rc = listed, reasons, shutdown_rc, register_rc
        self.calls = []

    def RmStartSession(self, session, flags, key):
        session._obj.value = 7
        self.calls.append(("start", flags))
        return 0

    def RmRegisterResources(self, session, nfiles, files, nprocs, procs, nsvcs, svcs):
        p = procs._obj
        self.calls.append(("register", nfiles, files, nprocs, nsvcs, svcs, p.pid,
                           (p.start.hi << 32) | p.start.lo))
        return self.register_rc

    def RmGetList(self, session, needed, count, infos, reasons):
        for i, (pid, created, app_type, service) in enumerate(self.listed):
            infos[i].process.pid = pid
            infos[i].process.start.lo, infos[i].process.start.hi = created & 0xFFFFFFFF, created >> 32
            infos[i].app_type, infos[i].service = app_type, service
        count._obj.value = len(self.listed)
        reasons._obj.value = self.reasons
        self.calls.append(("list",))
        return 0

    def RmShutdown(self, session, flags, callback):
        self.calls.append(("shutdown", flags, callback))
        return self.shutdown_rc

    def RmEndSession(self, session):
        self.calls.append(("end", session.value))
        return 0


def real_host_with(monkeypatch, rm):
    monkeypatch.setattr(life.ctypes, "WinDLL", lambda name: rm if name == "rstrtmgr" else None,
                        raising=False)
    return life.Host.__new__(life.Host)


TICKS = 134370941984741074


def test_rm_shutdown_registers_only_the_process_and_never_forces(monkeypatch):
    rm = FakeRm([(48052, TICKS, 1, "")])
    out = real_host_with(monkeypatch, rm).rm_shutdown(48052, str(TICKS))
    assert out["stage"] == "shutdown" and out["rc"] == 0
    assert ("register", 0, None, 1, 0, None, 48052, TICKS) in rm.calls
    assert ("shutdown", 0, None) in rm.calls
    assert rm.calls[-1] == ("end", 7)


@pytest.mark.parametrize("listed, reasons", [
    ([(48052, TICKS, 1, ""), (9, 1, 1, "")], 0),
    ([(48052, TICKS, 3, "svc")], 0),
    ([(48052, TICKS + 1, 1, "")], 0),
    ([(48052, TICKS, 1, "")], 0x2),
])
def test_rm_shutdown_never_runs_on_a_wrong_list(monkeypatch, listed, reasons):
    rm = FakeRm(listed, reasons)
    out = real_host_with(monkeypatch, rm).rm_shutdown(48052, str(TICKS))
    assert out.get("problem") and not any(c[0] == "shutdown" for c in rm.calls)
    assert rm.calls[-1] == ("end", 7)


def test_dry_run_stops_before_shutdown_and_still_ends_the_session(monkeypatch):
    rm = FakeRm([(48052, TICKS, 1, "")])
    out = real_host_with(monkeypatch, rm).rm_shutdown(48052, str(TICKS), dry_run=True)
    assert out["stage"] == "list" and out["rc"] == 0
    assert not any(c[0] == "shutdown" for c in rm.calls) and rm.calls[-1] == ("end", 7)


def test_a_register_failure_ends_the_session_without_shutdown(monkeypatch):
    rm = FakeRm([(48052, TICKS, 1, "")], register_rc=5)
    out = real_host_with(monkeypatch, rm).rm_shutdown(48052, str(TICKS))
    assert out == dict(stage="register", rc=5)
    assert not any(c[0] in ("list", "shutdown") for c in rm.calls) and rm.calls[-1] == ("end", 7)


# --- reopen ---------------------------------------------------------------------

def test_reopen_launches_only_the_registered_cli_and_workspace(h, tmp_path):
    closed(h)
    state = tmp_path / "proof.json"
    state.write_text(json.dumps({"status": "finished"}))
    assert life.reopen(h, HASH, state) == 0
    assert h.launches == [(CLI, WORKSPACE)] and "OPEN" in h.lines[-1]


@pytest.mark.parametrize("spoil, why", [
    ("enabled", "not confirmed disabled"),
    ("reservation", "has a reservation"),
    ("child", "is still alive"),
    ("usage", "usage for a1 is not recorded"),
    ("claimed", "claimed and not finished"),
    ("own", "successor ownership is unknown"),
    ("turn", "turns in progress"),
    ("hash", "does not have the expected sha256"),
])
def test_reopen_keeps_the_app_closed_until_cleanup_is_certain(h, tmp_path, spoil, why):
    closed(h)
    state = tmp_path / "proof.json"
    state.write_text(json.dumps({"status": "finished"}))
    if spoil == "enabled":
        h.sql("UPDATE sessions SET enabled = 1")
    elif spoil == "reservation":
        h.sql("INSERT INTO reservations VALUES ('codex:x', 'codex-lead', 'a', 0)")
    elif spoil == "child":
        attempt(h, alive=True)
    elif spoil == "usage":
        attempt(h, usage=0)
    elif spoil == "claimed":
        state.write_text(json.dumps({"status": "claimed"}))
    elif spoil == "own":
        h.own = "unknown"
    elif spoil == "turn":
        h.turns = [dict(thread_id=SUCCESSOR, turn_id="live", status="inProgress")]
    else:
        h.cli_hash = "d" * 64
    assert life.reopen(h, HASH, state) == 1
    assert h.launches == [] and why in h.lines[-1]


def test_a_finished_proof_run_does_not_block_reopen(h):
    closed(h)
    attempt(h)                                  # pid 555 not alive, usage recorded
    assert life.reopen(h, HASH, None) == 0


def test_reopen_refuses_over_a_running_app(h):
    assert life.reopen(h, HASH, None) == 1 and h.launches == []


def test_reopen_reports_an_app_that_never_comes_up(h):
    closed(h)
    h.launch = lambda cli, ws: h.launches.append((cli, ws)) or 1
    assert life.reopen(h, HASH, None) == 1
    assert "no desktop app-server" in h.lines[-1]


# --- Codex, local 18a7b6b: live work is rechecked at the shutdown boundary --------

def busy(h):
    h.turns = [dict(thread_id=SUCCESSOR, turn_id="sneaky", status="inProgress")]


def test_work_that_starts_during_the_identity_check_stops_the_shutdown(h):
    real = h.processes_list
    calls = []

    def listing():
        calls.append(1)
        if len(calls) == 2:          # the recheck right before the request
            busy(h)
        return real()
    h.processes_list = listing
    assert life.close(h) == 1
    assert h.shutdowns == 0 and 100 in h.processes.alive
    assert "turns started before shutdown" in h.lines[-1]


@pytest.mark.parametrize("event, why", [
    (busy, "turns started before shutdown"),
    (lambda h: setattr(h, "turns", sqlite3.OperationalError("locked")), "cannot read Codex's turns"),
    (lambda h: setattr(h, "turns", [dict(thread_id=SUCCESSOR, turn_id="t", status="paused")]),
     "cannot read Codex's turns"),
    (lambda h: h.processes.alive.__setitem__(100, "9999"), "no longer the app"),
])
def test_anything_changing_during_the_rm_list_stops_the_shutdown(h, event, why):
    h.during_list = lambda: event(h)
    assert life.close(h) == 1
    assert h.shutdowns == 0 and why in h.lines[-1]


def test_the_real_rm_path_runs_the_last_check_before_shutdown(monkeypatch):
    rm = FakeRm([(48052, TICKS, 1, "")])
    out = real_host_with(monkeypatch, rm).rm_shutdown(48052, str(TICKS),
                                                      last_check=lambda: "turns started")
    assert out["problem"] == "turns started"
    assert ("list",) in rm.calls and not any(c[0] == "shutdown" for c in rm.calls)
    assert rm.calls[-1] == ("end", 7)
