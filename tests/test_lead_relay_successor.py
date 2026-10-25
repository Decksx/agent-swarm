"""Rebinding a lead past a run the relay proved terminal.

The contract is docs/design/relay-successor-transition.md; section numbers
refer to it. The relay fakes come from `test_lead_relay`. The scenario is
codex-lead's on 2026-10-24: a headless run killed by the run timeout, ACKed,
usage charged, whose conversation never reads idle again (an orphaned
`inProgress` turn), so its reservation is never released.

The process table is modelled by `Host`: a pid, its parent, its creation
time (FILETIME-like ticks and epoch seconds) and whether that time can be
read. It serves both the real `ProcessApi`'s low-level hooks and `snapshot`,
so a check that misses a survivor misses it here for the same reason it
would on the host.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time

import pytest

import lead_relay
import lead_relay_backends
import lead_relay_cli
import lead_relay_successor
from lead_relay import CLOSED, UNKNOWN
from lead_relay_backends import Proc
from test_lead_relay import FakeBackend, FakePopen, FakeProcesses, World, started

OLD = "11111111-2222-3333-4444-555555555555"     # claude-lead's binding in World
NEW = "77777777-2222-3333-4444-555555555555"
OTHER = "99999999-2222-3333-4444-555555555555"   # codex-lead's binding in World
FRESH = "88888888-2222-3333-4444-555555555555"

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Windows job objects and process table")


@pytest.fixture(autouse=True)
def default_policy(monkeypatch):
    """The relay's policy defaults, whatever LEAD_RELAY_* the shell exported:
    an inherited cap override must not decide these tests."""
    for name, value in (("RUN_TIMEOUT", 45 * 60.0), ("LIVE_ACK_SECONDS", 600.0),
                        ("MAX_WAKES_PER_HOUR", 20), ("MAX_WAKES_PER_DAY", 160),
                        ("MAX_CHAIN", 80)):
        monkeypatch.setattr(lead_relay, name, value)


class Host(FakeProcesses, lead_relay.ProcessApi):
    """`FakeProcesses` with parents, creation times, unreadable entries and jobs."""

    def __init__(self, alive=None):
        super().__init__()
        self.alive.update(alive or {})
        self.parent, self.created, self.names = {}, {}, {}
        self.denied, self.jobs, self.fail = set(), {}, None

    def add(self, pid, ppid, start, created, name=None):
        self.alive[pid] = str(start)
        self.parent[pid], self.created[pid] = ppid, created
        self.names[pid] = name or f"proc{pid}.exe"

    def creation_time(self, pid):
        return None if pid in self.denied else self.alive.get(pid)

    def is_same(self, pid, start):
        return bool(pid) and start is not None and self.creation_time(pid) == start

    def _windows_table(self):   # the hook b7ade88's descendants() walked
        if self.fail:
            raise self.fail
        return [(pid, self.parent.get(pid, 1)) for pid in self.alive]

    def snapshot(self):
        if self.fail:
            raise self.fail
        return [Proc(pid, self.parent.get(pid, 1), None if pid in self.denied else start,
                     self.names.get(pid, f"proc{pid}.exe"),
                     None if pid in self.denied else self.created.get(pid, 0.0))
                for pid, start in self.alive.items()]

    def job_members(self, name):
        found = self.jobs.get(name)
        if isinstance(found, Exception):
            raise found
        return found


class HostWorld(World):
    """`World` on a `Host`, with numeric creation times like the real ones."""

    def __init__(self, tmp_path, **kwargs):
        super().__init__(tmp_path, **kwargs)
        self.processes = Host(self.processes.alive)
        self.relay.processes = self.processes

    def spawn(self, command, session, attempt_id):
        pid = 4000 + len(self.spawned)
        self.processes.add(pid, os.getpid(), pid * 1000, self.t[0])
        self.spawned.append(command)
        return pid, str(pid * 1000), FakePopen(self.processes, pid), "log"


class PerSession(FakeBackend):
    """Ownership per conversation: the orphaned one stays UNKNOWN for good."""

    def __init__(self):
        super().__init__(CLOSED)
        self.by_session = {}
        self.asked = []

    def ownership(self, session):
        self.asked.append(session.session_id)
        return self.by_session.get(session.session_id, self.state)


def world(tmp_path):
    w = HostWorld(tmp_path)
    w.backend = PerSession()
    w.relay.backends = {"claude": w.backend}
    return w


def orphaned(tmp_path):
    """A timed-out, ACKed, charged run whose conversation stays UNKNOWN, and
    a later handoff held behind its reservation."""
    w = world(tmp_path)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.tick(advance=lead_relay.RUN_TIMEOUT + 1)
    w.tick(advance=lead_relay.EXIT_ACK_GRACE + 1)
    held = w.hub.add("codex-lead", "HANDOFF @claude-lead: next")
    w.tick()
    w.mid, w.held = mid, held
    w.aid = attempt_id(w)
    assert w.processes.killed == [4000] and len(w.recorded) == 1
    assert w.delivery(mid) == ("delivered", "ack")
    assert w.delivery(held) == ("held", "reserved")
    return w


def attempt_id(w):
    return w.relay.db.execute("SELECT attempt_id FROM attempts ORDER BY created_at").fetchone()[0]


def attempt(w):
    return w.relay._attempt(w.aid)


def in_window(w, seconds=60):
    return attempt(w)["launched_at"] + seconds


def rebind(w, *, session=NEW, confirm=True, attempt=None, workspace="C:/git",
           reason="orphaned turn; David, hive #2735", **kw):
    aid = attempt or w.aid
    return lead_relay_successor.transition(
        w.relay.db, "claude-lead", aid, session, workspace, reason, processes=w.processes,
        confirm=(aid if confirm is True else confirm or None), now=lambda: w.t[0], **kw)


def snapshot(w):
    db = w.relay.db
    db.executescript(lead_relay_successor.RETIRED)
    return {t: sorted(tuple(r) for r in db.execute(f"SELECT * FROM {t}"))
            for t in ("attempts", "deliveries", "reservations", "sessions", "wakes", "meta",
                      "retired_reservations")}


def refused(w, words, **kw):
    before = snapshot(w)
    code, text = rebind(w, **kw)
    assert code == 1 and text.startswith("REFUSED") and words in text, text
    assert snapshot(w) == before
    return text


# --- §3 the success path -------------------------------------------------------------


def test_a_dry_run_changes_nothing_and_names_the_proof(tmp_path):
    w = orphaned(tmp_path)
    before = snapshot(w)
    code, text = rebind(w, confirm=None)
    assert code == 0 and text.startswith("DRY RUN"), text
    assert "killed by the run timeout" in text and "recorded by its timeout path" in text
    assert "no live process was created during its run window" in text
    assert f"--confirm {w.aid}" in text
    assert snapshot(w) == before


def test_the_rebind_retires_the_reservation_as_evidence_and_binds_disabled(tmp_path):
    w = orphaned(tmp_path)
    before = snapshot(w)
    reservation = before["reservations"]
    code, text = rebind(w)
    assert code == 0 and text.startswith("done"), text
    after = snapshot(w)

    assert after["attempts"] == before["attempts"], "no attempt row changed"
    assert after["deliveries"] == before["deliveries"], "no delivery row changed"
    assert after["wakes"] == before["wakes"] and after["meta"] == before["meta"]
    assert after["reservations"] == []
    retired = lead_relay_successor.retired(w.relay.db)
    assert len(retired) == 1
    row = retired[0]
    assert (row["session_key"], row["recipient"], row["attempt_id"], row["acquired_at"]) \
        == tuple(reservation[0])
    assert row["successor_key"] == f"claude:{NEW}" and row["reason"].startswith("orphaned")
    assert OLD in row["previous_binding"] and row["retired_at"] == w.t[0]
    binding = w.relay.session("claude-lead")
    assert (binding.session_id, binding.enabled, binding.cli) == (NEW, False, None)
    assert w.relay.session("codex-lead").session_id == OTHER, "the other lead is untouched"
    assert len(w.recorded) == 1


def test_after_enable_the_held_delivery_goes_to_the_successor_only(tmp_path):
    w = orphaned(tmp_path)
    assert rebind(w)[0] == 0
    w.backend.asked.clear()
    w.tick(advance=60)
    assert w.delivery(w.held) == ("held", "backend-disabled")
    assert len(w.spawned) == 1
    old = w.relay._attempt(w.aid)
    assert old["state"] == "done", "the retired run ends as every released run does"

    w.relay.db.execute("UPDATE sessions SET enabled = 1 WHERE recipient = 'claude-lead'")
    w.tick(advance=60)
    assert w.delivery(w.held) == ("running", None)
    assert len(w.spawned) == 2 and NEW in w.spawned[-1] and OLD not in w.spawned[-1]
    assert OLD not in w.backend.asked, "the old conversation was never judged again"
    keys = [r[0] for r in w.relay.db.execute("SELECT session_key FROM reservations")]
    assert keys == [f"claude:{NEW}"]
    assert w.processes.killed == [4000], "nothing was killed or launched against the old run"
    assert len(w.recorded) == 1, "the old run was charged exactly once"
    assert w.delivery(w.mid) == ("delivered", "ack")


def test_a_late_ack_for_the_retired_run_changes_nothing(tmp_path):
    w = orphaned(tmp_path)
    assert rebind(w)[0] == 0
    w.ack(w.mid, w.token(w.mid))
    w.tick()
    assert w.delivery(w.mid) == ("delivered", "ack") and len(w.spawned) == 1


def test_running_it_again_is_refused(tmp_path):
    w = orphaned(tmp_path)
    assert rebind(w)[0] == 0
    for session in (NEW, FRESH):
        refused(w, "already retired", session=session)


# --- §2 every precondition refuses, and changes nothing ---------------------------------


def db_exec(sql, *args):
    return lambda w: w.relay.db.execute(sql, args)


def retired_row(recipient, session):
    def apply(w):
        w.relay.db.executescript(lead_relay_successor.RETIRED)
        w.relay.db.execute("INSERT INTO retired_reservations VALUES "
                           "('a0', ?, ?, 0, 0, 'r', 'k', '{}')", (f"claude:{session}", recipient))
    return apply


def root_alive(w):
    w.processes.add(4000, os.getpid(), attempt(w)["proc_start"], attempt(w)["launched_at"])


def child_alive(w):
    w.processes.add(4100, 4000, 4000 * 1000 + 5, in_window(w))


def unreadable_table(w):
    w.processes.fail = OSError("snapshot failed")


REFUSALS = {
    "bad-uuid": (None, dict(session="not-a-uuid"), "UUID"),
    "relative-workspace": (None, dict(workspace="git"), "absolute"),
    "blank-reason": (None, dict(reason="  "), "reason is required"),
    "unregistered": (db_exec("DELETE FROM sessions WHERE recipient = 'claude-lead'"), {},
                     "not registered"),
    "no-reservation": (None, dict(attempt="0123456789abcdef"), "no reservation"),
    "reservation-of-another-lead": (
        db_exec("UPDATE reservations SET recipient = 'codex-lead'"), {}, "belongs to codex-lead"),
    "reservation-not-current-binding": (
        db_exec("UPDATE sessions SET session_id = '55555555-2222-3333-4444-555555555555' "
                "WHERE recipient = 'claude-lead'"), {}, "not claude-lead's current binding"),
    "another-reservation": (
        db_exec("INSERT INTO reservations VALUES ('claude:x', 'claude-lead', 'other1', 0)"), {},
        "other reservations"),
    "successor-reserved": (
        db_exec(f"INSERT INTO reservations VALUES ('claude:{NEW}', 'codex-lead', 'other2', 0)"),
        {}, "other reservations"),
    "no-attempt-row": (db_exec("UPDATE reservations SET attempt_id = 'ghost'"),
                       dict(attempt="ghost"), "no attempts row"),
    "not-headless": (db_exec("UPDATE attempts SET path = 'live'"), {}, "headless run"),
    "other-conversation": (db_exec("UPDATE attempts SET session_id = ?", NEW), {}, "headless run"),
    "still-running": (db_exec("UPDATE attempts SET state = 'running', ended_at = NULL"), {},
                      "is running, not proven terminal"),
    "no-ended-at": (db_exec("UPDATE attempts SET ended_at = NULL"), {}, "no ended_at"),
    "no-pid": (db_exec("UPDATE attempts SET pid = NULL"), {}, "no pid"),
    "no-proc-start": (db_exec("UPDATE attempts SET proc_start = NULL"), {}, "no proc_start"),
    "short-without-exit-code": (
        db_exec("UPDATE attempts SET ended_at = launched_at + 60"), {}, "recorded no timeout kill"),
    "recovered-uncertain": (
        db_exec("UPDATE deliveries SET state = 'uncertain', reason = 'process gone after restart' "
                "WHERE recipient = 'claude-lead' AND attempt_id IS NOT NULL"), {},
        "recorded no timeout kill"),
    "ended-by-exit": (db_exec("UPDATE attempts SET ended_by = 'exit'"), {},
                      "recorded no timeout kill (ended_by exit)"),
    "ended-by-recovery": (db_exec("UPDATE attempts SET ended_by = 'recovery'"), {},
                          "(ended_by recovery)"),
    "usage-unrecorded": (db_exec("UPDATE attempts SET usage_recorded = 0"), {}, "usage"),
    "delivery-active": (
        db_exec("UPDATE deliveries SET state = 'exited' WHERE recipient = 'claude-lead' "
                "AND attempt_id IS NOT NULL"), {}, "still exited"),
    "root-alive": (root_alive, {}, "still alive (same pid"),
    "descendant-alive": (child_alive, {}, "pid 4100 proc4100.exe"),
    "table-unreadable": (unreadable_table, {}, "process table could not be read"),
    "same-conversation": (None, dict(session=OLD.upper()), "different conversation"),
    "registered-to-other-lead": (None, dict(session=OTHER), "already registered to codex-lead"),
    "retired-conversation-other-lead": (retired_row("codex-lead", NEW), {}, "retired reservation"),
    "retired-conversation-same-lead": (retired_row("claude-lead", NEW), {},
                                       "retired reservation"),
    "wrong-confirmation": (None, dict(confirm="e7c8dfdf2210c057"), "--confirm must name"),
}


@pytest.mark.parametrize("name", list(REFUSALS))
def test_each_failed_precondition_is_refused_with_its_reason(tmp_path, name):
    setup, kwargs, reason = REFUSALS[name]
    w = orphaned(tmp_path)
    if setup:
        setup(w)
    refused(w, reason, **kwargs)
    if setup is None or name == "descendant-alive":
        # The same world passes once the one failed condition is put right.
        w.processes.alive.pop(4100, None)
        assert rebind(w)[0] == 0


def test_a_reused_pid_is_not_the_run(tmp_path):
    w = orphaned(tmp_path)
    w.processes.add(4000, 1, 9_999_999, in_window(w, 5000))   # same pid, later process
    assert rebind(w)[0] == 0


@pytest.mark.parametrize("how", ["quit-unrecovered", "quit-recovered"])
def test_a_quit_run_is_refused_unless_proven_terminal(tmp_path, how):
    """2026-10-21: a turn that was quit is not proof. Gone while the relay was
    down, the run is `running` until recovery, then `exited` with no exit
    code, `ended_by = 'recovery'` and less than the timeout behind it."""
    w = world(tmp_path)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.exit()                                    # quit; the relay hasn't seen it yet
    if how == "quit-recovered":
        w.restart()
        w.tick(advance=30)
    w.aid = attempt_id(w)
    refused(w, "is running" if how == "quit-unrecovered" else "(ended_by recovery)")


def test_a_quit_the_relay_reaped_has_an_exit_code_and_is_terminal(tmp_path):
    w = world(tmp_path)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.backend.by_session[OLD] = UNKNOWN
    w.exit()
    w.tick()
    w.aid = attempt_id(w)
    code, text = rebind(w)
    assert code == 0 and "exited with code 0" in text, text


# --- Gap 1: a timeout kill is recorded by the timeout path, never inferred -------------


def test_the_timeout_path_records_its_kill_in_the_exit_statement(tmp_path):
    w = orphaned(tmp_path)
    row = attempt(w)
    assert (row["state"], row["exit_code"], row["ended_by"]) == ("exited", None, "timeout")


def test_a_run_that_quit_after_a_restart_past_the_timeout_is_not_a_timeout_kill(tmp_path):
    """codex-lead's reproduction at b7ade88: a restart loses the Popen handle,
    the child then quits on its own, and the next tick is past RUN_TIMEOUT.
    `supervise` records a NULL exit code and a runtime >= RUN_TIMEOUT, which
    b7ade88 called "killed by the run timeout". Nothing was killed."""
    w = world(tmp_path)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.restart()                                 # the Popen handle is gone
    w.exit()                                    # the child quits by itself
    w.tick(advance=lead_relay.RUN_TIMEOUT + 1)
    w.tick(advance=lead_relay.EXIT_ACK_GRACE + 1)
    w.aid = attempt_id(w)
    row = attempt(w)
    assert w.processes.killed == [], "the fixture killed nothing"
    assert row["exit_code"] is None and row["ended_at"] - row["launched_at"] \
        >= lead_relay.RUN_TIMEOUT and row["usage_recorded"] == 1
    assert w.delivery(mid) == ("delivered", "ack")
    text = refused(w, "recorded no timeout kill (ended_by exit)")
    assert "killed by the run timeout" not in text
    refused(w, "recorded no timeout kill", historical=True)   # not historical either


def historical(w, *, since_offset=1.0):
    """The production shape: ended before this database recorded `ended_by`."""
    w.relay.db.execute("UPDATE attempts SET ended_by = NULL")
    w.relay.db.execute("UPDATE meta SET value = ? WHERE key = 'provenance_since'",
                       (repr(attempt(w)["ended_at"] + since_offset),))


def test_a_run_from_before_provenance_needs_the_historical_flag(tmp_path):
    w = orphaned(tmp_path)
    historical(w)
    text = refused(w, "add --historical-evidence")
    assert "not proof of a timeout kill" in text
    code, text = rebind(w, confirm=None, historical=True)
    assert code == 0, text
    assert "historical evidence only: ended, no exit code, ran 45.0 min >= RUN_TIMEOUT" in text
    assert "no termination provenance recorded" in text and "not proven a timeout kill" in text
    assert "killed by the run timeout" not in text
    assert rebind(w, historical=True)[0] == 0


@pytest.mark.parametrize("change, reason", [
    (db_exec("UPDATE attempts SET ended_at = launched_at + 60"), "recorded no timeout kill"),
    (db_exec("UPDATE deliveries SET state = 'uncertain' WHERE recipient = 'claude-lead' "
             "AND attempt_id IS NOT NULL"), "recorded no timeout kill"),
    (db_exec("UPDATE meta SET value = '0' WHERE key = 'provenance_since'"),
     "recorded no timeout kill (ended_by not recorded)"),
], ids=["short", "uncertain", "after-provenance"])
def test_the_historical_route_accepts_only_what_it_names(tmp_path, change, reason):
    w = orphaned(tmp_path)
    historical(w)
    change(w)
    refused(w, reason, historical=True)


def test_without_a_provenance_record_nothing_is_historical(tmp_path):
    w = orphaned(tmp_path)
    historical(w)
    with pytest.raises(lead_relay_successor.Refused, match="recorded no timeout kill"):
        lead_relay_successor.terminal(attempt(w), None, lead_relay.RUN_TIMEOUT, None, True)


def test_an_older_database_gains_provenance_columns_once(tmp_path):
    """The repo's migration pattern: PRAGMA, ALTER, idempotent."""
    db = sqlite3.connect(tmp_path / "relay.db")
    db.executescript(lead_relay.SCHEMA)
    db.execute("INSERT INTO attempts (attempt_id, message_id, recipient, token, path, state, "
               "created_at, launched_at, ended_at, backend) VALUES "
               "('old', 1, 'codex-lead', 'tok', 'headless', 'exited', 0, 10, 2800, 'codex')")
    db.commit()
    db.close()
    w = World(tmp_path, register=False)
    db = w.relay.db
    columns = [r[1] for r in db.execute("PRAGMA table_info(attempts)")]
    assert columns[-2:] == ["ended_by", "container"]
    row = db.execute("SELECT * FROM attempts WHERE attempt_id = 'old'").fetchone()
    assert (row["ended_by"], row["container"], row["ended_at"]) == (None, None, 2800)
    since = db.execute("SELECT value FROM meta WHERE key = 'provenance_since'").fetchone()[0]
    assert float(since) > row["ended_at"]
    lead_relay.migrate(db)
    lead_relay.migrate(db)
    assert [r[1] for r in db.execute("PRAGMA table_info(attempts)")] == columns
    assert db.execute("SELECT value FROM meta WHERE key = 'provenance_since'").fetchone()[0] \
        == since, "provenance_since is set once"


# --- Gap 2: a survivor behind an exited wrapper is not invisible ------------------------


def test_a_survivor_of_an_exited_wrapper_is_found_by_creation_time(tmp_path):
    """root 4000 -> wrapper 4200 -> worker 4300; root and wrapper gone. The
    parent chain from 4000 cannot reach 4300, so b7ade88 called the tree
    gone. With no container, every live process created during the run's
    window is a refusal, listed for the operator."""
    w = orphaned(tmp_path)
    w.processes.add(4300, 4200, 4000 * 1000 + 50, in_window(w), "codex.exe")
    text = refused(w, "1 live process(es) were created during its run window")
    assert "pid 4300 codex.exe created" in text and "--inspected-pids 4300" in text


def test_inspected_pids_must_cover_every_process_in_the_window(tmp_path):
    w = orphaned(tmp_path)
    w.processes.add(4300, 4200, 4000 * 1000 + 50, in_window(w), "codex.exe")
    w.processes.add(4400, 1, 4000 * 1000 + 60, in_window(w, 120), "chrome.exe")
    text = refused(w, "pid 4300", inspected=[4400])
    assert "pid 4400" not in text and "--inspected-pids 4300" in text
    code, text = rebind(w, confirm=None, inspected=[4300, 4400])
    assert code == 0 and "other than the operator-inspected 4300, 4400" in text, text


def test_inspection_never_overrides_a_member_of_the_parent_chain(tmp_path):
    w = orphaned(tmp_path)
    child_alive(w)
    refused(w, "part of its process tree is still alive: pid 4100", inspected=[4100])


@pytest.mark.parametrize("created, passes", [(-11, True), (-9, False), (9, False), (11, True)])
def test_the_window_is_the_run_plus_a_small_skew(tmp_path, created, passes):
    w = orphaned(tmp_path)
    row = attempt(w)
    edge = row["launched_at"] if created < 0 else row["ended_at"]
    w.processes.add(4300, 1, 1, edge + created)
    assert (rebind(w, confirm=None)[0] == 0) is passes


def test_an_unreadable_creation_time_refuses_the_window_check(tmp_path):
    w = orphaned(tmp_path)
    w.processes.add(4300, 1, 1, None)
    refused(w, "no container was recorded for this run, and the creation time of pid 4300")


def contained(w, container):
    w.relay.db.execute("UPDATE attempts SET container = ?", (container,))


JOB = "job:Global\\lead-relay-x"


@pytest.mark.parametrize("members, ok, words", [
    (None, True, "no longer exists; it was created kill-on-close"),
    ([], True, "has no live process"),
    ([4300], False, "still has 1 live process(es): pid 4300 codex.exe"),
    (OSError("error 5"), False, "could not be queried (OSError: error 5)"),
], ids=["destroyed", "empty", "survivor", "query-failed"])
def test_a_contained_run_is_judged_by_its_job(tmp_path, members, ok, words):
    w = orphaned(tmp_path)
    contained(w, JOB)
    w.processes.add(4300, 4200, 4000 * 1000 + 50, in_window(w), "codex.exe")
    w.processes.jobs["Global\\lead-relay-x"] = members
    if ok:
        code, text = rebind(w, confirm=None)
        assert code == 0 and words in text, text
    else:
        refused(w, words)


def test_a_posix_session_container_lists_its_members(tmp_path):
    w = orphaned(tmp_path)
    contained(w, "session:4000")
    assert rebind(w, confirm=None)[0] == 0
    w.processes.add(4300, 1, 1, 0.0)
    snap = w.processes.snapshot
    w.processes.snapshot = lambda: [p if p.pid != 4300 else Proc(4300, 1, "1", "w", 0.0, 4000, 9)
                                    for p in snap()]
    refused(w, "its session 4000 still has live processes: pid 4300")


def test_an_unknown_container_is_refused(tmp_path):
    w = orphaned(tmp_path)
    contained(w, "cgroup:/x")
    refused(w, "is not one this relay knows how to check")


def test_the_launch_records_the_container_with_the_pid(tmp_path):
    w = world(tmp_path)

    def spawn(command, session, attempt_id):
        handle = FakePopen(w.processes, 4000)
        handle.container = f"job:Global\\lead-relay-{attempt_id}"
        w.processes.add(4000, os.getpid(), 4_000_000, w.t[0])
        return 4000, "4000000", handle, "log"

    w.relay.spawn = spawn
    started(w)
    row = w.relay.db.execute("SELECT * FROM attempts").fetchone()
    assert row["container"] == f"job:Global\\lead-relay-{row['attempt_id']}"
    assert row["pid"] == 4000


# --- Gap 3: a failed process query refuses ----------------------------------------------


def test_an_unreadable_child_refuses_and_an_exited_one_does_not(tmp_path):
    w = orphaned(tmp_path)
    child_alive(w)
    w.processes.denied.add(4100)            # OpenProcess / GetProcessTimes failed
    refused(w, "creation time of pid 4100 (proc4100.exe), a child of 4000, could not be read")
    w.processes.alive.pop(4100)             # the control: it exited
    assert rebind(w)[0] == 0


def test_an_unreadable_root_identity_refuses(tmp_path):
    w = orphaned(tmp_path)
    root_alive(w)
    w.processes.denied.add(4000)
    refused(w, "pid 4000 is live and its creation time could not be read")


# --- Gap 4: a retired conversation is never registered again ---------------------------


def register(w, lead, session, backend="claude"):
    return lead_relay_cli.main(["--db", str(w.db_path), "register", "--lead", lead,
                                "--backend", backend, "--session", session,
                                "--workspace", "C:/git"])


@pytest.mark.parametrize("lead", ["claude-lead", "codex-lead"])
@pytest.mark.parametrize("spelling", [str.lower, str.upper])
def test_register_refuses_a_retired_conversation(tmp_path, capsys, lead, spelling):
    w = orphaned(tmp_path)
    assert rebind(w)[0] == 0
    before = snapshot(w)
    capsys.readouterr()
    assert register(w, lead, spelling(OLD)) == 1
    out = capsys.readouterr().out
    assert out.startswith("REFUSED") and f"retired (attempt {w.aid}, claude-lead)" in out, out
    assert snapshot(w) == before
    assert register(w, lead, FRESH) == 0, "a new conversation still registers"


def test_register_still_rebinds_the_current_successor(tmp_path):
    w = orphaned(tmp_path)
    assert rebind(w)[0] == 0
    assert register(w, "claude-lead", NEW) == 0


# --- §4 the old run's code paths never judge the successor -----------------------------


def test_release_never_judges_a_reservation_by_another_binding(tmp_path):
    """A binding changed by any other route (a manual edit, a legacy row): the
    old run's reservation must not be released because the NEW conversation
    reads CLOSED."""
    w = world(tmp_path)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.relay.db.execute("UPDATE sessions SET session_id = ? WHERE recipient = 'claude-lead'", (NEW,))
    w.exit()
    for _ in range(3):
        w.tick(advance=60)
    keys = [r[0] for r in w.relay.db.execute("SELECT session_key FROM reservations")]
    assert keys == [f"claude:{OLD}"]
    assert w.relay.db.execute("SELECT state FROM attempts").fetchone()[0] == "exited"


# --- §1 the command line ------------------------------------------------------------------


def test_the_successor_command_line(tmp_path, capsys, monkeypatch):
    w = orphaned(tmp_path)
    monkeypatch.setattr(lead_relay_cli, "ProcessApi", lambda: w.processes)
    argv = ["--db", str(w.db_path), "successor", "--lead", "claude-lead", "--session", NEW,
            "--workspace", "C:/git", "--retire-attempt", w.aid, "--reason", "orphaned turn"]
    lock = lead_relay.acquire_lock(w.db_path.with_name(w.db_path.name + ".lock"))   # the daemon
    try:
        assert lead_relay_cli.main(argv) == 0
        assert capsys.readouterr().out.startswith("DRY RUN")
        assert lead_relay_cli.main(argv + ["--confirm", w.aid]) == 3
        assert "daemon is running" in capsys.readouterr().out
    finally:
        os.close(lock)
    assert lead_relay_cli.main(argv + ["--confirm", "nope"]) == 1
    assert "--confirm must name" in capsys.readouterr().out
    assert lead_relay_cli.main(argv + ["--confirm", w.aid]) == 0
    assert capsys.readouterr().out.startswith("done")
    assert lead_relay_cli.main(["--db", str(w.db_path), "status"]) == 0
    status = capsys.readouterr().out
    assert '"retired_reservations"' in status and w.aid in status and NEW in status
    assert lead_relay_cli.main(argv + ["--confirm", w.aid]) == 1
    assert "already retired" in capsys.readouterr().out


def test_the_command_line_passes_the_historical_and_inspection_flags(tmp_path, capsys,
                                                                     monkeypatch):
    w = orphaned(tmp_path)
    historical(w)
    w.processes.add(4300, 1, 1, in_window(w))
    monkeypatch.setattr(lead_relay_cli, "ProcessApi", lambda: w.processes)
    argv = ["--db", str(w.db_path), "successor", "--lead", "claude-lead", "--session", NEW,
            "--workspace", "C:/git", "--retire-attempt", w.aid, "--reason", "orphaned turn"]
    assert lead_relay_cli.main(argv) == 1
    assert "add --historical-evidence" in capsys.readouterr().out
    assert lead_relay_cli.main(argv + ["--historical-evidence"]) == 1
    assert "--inspected-pids 4300" in capsys.readouterr().out
    assert lead_relay_cli.main(argv + ["--historical-evidence", "--inspected-pids", "x"]) == 1
    assert "comma-separated pids" in capsys.readouterr().out
    assert lead_relay_cli.main(argv + ["--historical-evidence", "--inspected-pids", "4300"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN") and "historical evidence only" in out


# --- §2.8 the real host -----------------------------------------------------------------

WORKER = "import time; time.sleep(120)"
WRAPPER = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', %r], "
           "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
           "creationflags=0x8); "   # DETACHED_PROCESS: off the root's console
           "print(p.pid, flush=True)") % WORKER
# root -> wrapper -> worker: the wrapper exits at once, the root reports the
# worker's pid and waits for its stdin to close.
ROOT = ("import subprocess, sys; w = subprocess.run([sys.executable, '-c', %r], "
        "capture_output=True, text=True); print(w.stdout.strip(), flush=True); "
        "sys.stdin.read()") % WRAPPER


def wait_until(check, seconds=20.0):
    deadline = time.time() + seconds
    while not check() and time.time() < deadline:
        time.sleep(0.2)
    return check()


def run_row(api, handle, container, launched):
    return {"pid": handle.pid, "proc_start": api.creation_time(handle.pid),
            "container": container, "launched_at": launched, "ended_at": time.time()}


def live(api, pid):
    return any(p.pid == pid for p in api.snapshot())


@WINDOWS_ONLY
def test_the_host_snapshot_reads_creation_times_without_opening_processes():
    api = lead_relay.ProcessApi()
    table = api.snapshot()
    me = next(p for p in table if p.pid == os.getpid())
    assert me.start == api.creation_time(os.getpid()) and abs(me.created - time.time()) < 3600
    assert len(table) > 20 and all(p.start is not None for p in table)


@WINDOWS_ONLY
def test_a_contained_run_shows_a_survivor_behind_an_exited_wrapper_and_dies_with_its_job():
    """Host check: the job lists the worker the parent chain can't reach,
    survives the launcher closing its own handle (a relay restart), and ends
    the worker when the root, its last holder, ends."""
    api = lead_relay.ProcessApi()
    aid = f"test{os.getpid():x}{int(time.time() * 1000):x}"
    launched = time.time()
    root = lead_relay_backends.popen_contained(
        aid, [sys.executable, "-c", ROOT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, **lead_relay.separate_process_group())
    try:
        assert root.container == f"job:Global\\lead-relay-{aid}"
        worker = int(root.stdout.readline())
        name = root.container[4:]
        assert worker in api.job_members(name) and root.pid in api.job_members(name)
        table = api.snapshot()
        assert worker not in [p.pid for p in lead_relay_successor.tree_members(
            table, root.pid, api.creation_time(root.pid))], "the chain is broken, as on b7ade88"
        row = run_row(api, root, root.container, launched)
        with pytest.raises(lead_relay_successor.Refused, match="still alive"):
            lead_relay_successor.tree_proof(api, row)            # the root itself
        root.stdin.close()                                      # the root ends normally
        root.wait(timeout=20)
        assert wait_until(lambda: not live(api, worker)), "kill-on-close ended the worker"
        assert api.job_members(name) is None
        assert "no longer exists" in lead_relay_successor.tree_proof(api, row)
    finally:
        api.kill_tree(root.pid)
        root.stdout.close()


@WINDOWS_ONLY
def test_an_uncontained_survivor_is_listed_by_the_window_check():
    api = lead_relay.ProcessApi()
    launched = time.time()
    root = subprocess.Popen([sys.executable, "-c", ROOT], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True,
                            **lead_relay.separate_process_group())
    worker = None
    try:
        worker = int(root.stdout.readline())
        start = api.creation_time(root.pid)
        held = lead_relay_backends._kernel32().OpenProcess(0x1000, False, root.pid)
        root.kill()
        root.wait(timeout=10)
        assert held and not live(api, root.pid), "an exited root still held is not listed"
        lead_relay_backends._kernel32().CloseHandle(held)
        # Its console host outlives it briefly, a child the chain does reach.
        assert wait_until(lambda: not lead_relay_successor.tree_members(
            api.snapshot(), root.pid, start))
        row = {"pid": root.pid, "proc_start": start, "container": None,
               "launched_at": launched, "ended_at": time.time()}
        with pytest.raises(lead_relay_successor.Refused) as refusal:
            lead_relay_successor.tree_proof(api, row)
        assert f"pid {worker} python.exe" in str(refusal.value)
    finally:
        root.stdout.close()
        if worker:
            api.kill_tree(worker)
    assert wait_until(lambda: not live(api, worker))
