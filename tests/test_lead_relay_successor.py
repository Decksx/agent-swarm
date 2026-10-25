"""Rebinding a lead past a run the relay proved terminal.

The contract is docs/design/relay-successor-transition.md; section numbers
refer to it. The relay fakes come from `test_lead_relay`. The scenario is
codex-lead's on 2026-10-24: a headless run killed by the run timeout, ACKed,
usage charged, whose conversation never reads idle again (an orphaned
`inProgress` turn), so its reservation is never released.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import lead_relay
import lead_relay_cli
import lead_relay_successor
from lead_relay import CLOSED, UNKNOWN
from test_lead_relay import FakeBackend, World, started

OLD = "11111111-2222-3333-4444-555555555555"     # claude-lead's binding in World
NEW = "77777777-2222-3333-4444-555555555555"
OTHER = "99999999-2222-3333-4444-555555555555"   # codex-lead's binding in World


class PerSession(FakeBackend):
    """Ownership per conversation: the orphaned one stays UNKNOWN for good."""

    def __init__(self):
        super().__init__(CLOSED)
        self.by_session = {}
        self.asked = []

    def ownership(self, session):
        self.asked.append(session.session_id)
        return self.by_session.get(session.session_id, self.state)


def orphaned(tmp_path):
    """A timed-out, ACKed, charged run whose conversation stays UNKNOWN, and
    a later handoff held behind its reservation."""
    w = World(tmp_path)
    w.backend = PerSession()
    w.relay.backends = {"claude": w.backend}
    w.tree = []
    w.processes.descendants = lambda pid, start: list(w.tree)
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.tick(advance=lead_relay.RUN_TIMEOUT + 1)
    w.tick(advance=lead_relay.EXIT_ACK_GRACE + 1)
    held = w.hub.add("codex-lead", "HANDOFF @claude-lead: next")
    w.tick()
    w.mid, w.held = mid, held
    w.aid = w.relay.db.execute("SELECT attempt_id FROM attempts WHERE message_id = ?",
                               (mid,)).fetchone()[0]
    assert w.processes.killed == [4000] and len(w.recorded) == 1
    assert w.delivery(mid) == ("delivered", "ack")
    assert w.delivery(held) == ("held", "reserved")
    return w


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


# --- §3 the success path -------------------------------------------------------------


def test_a_dry_run_changes_nothing_and_names_the_proof(tmp_path):
    w = orphaned(tmp_path)
    before = snapshot(w)
    code, text = rebind(w, confirm=None)
    assert code == 0 and text.startswith("DRY RUN"), text
    assert "killed by the run timeout" in text and f"--confirm {w.aid}" in text
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
    before = snapshot(w)
    for session in (NEW, "88888888-2222-3333-4444-555555555555"):
        code, text = rebind(w, session=session)
        assert code == 1 and "already retired" in text, text
    assert snapshot(w) == before


# --- §2 every precondition refuses, and changes nothing ---------------------------------


def db_exec(sql, *args):
    return lambda w: w.relay.db.execute(sql, args)


def with_tree(*pids):
    def apply(w):
        w.tree[:] = pids
    return apply


def unreadable_tree(w):
    def fail(pid, start):
        raise OSError("snapshot failed")
    w.processes.descendants = fail


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
        db_exec("UPDATE attempts SET ended_at = launched_at + 60"), {}, "not a timeout kill"),
    "recovered-uncertain": (
        db_exec("UPDATE deliveries SET state = 'uncertain', reason = 'process gone after restart' "
                "WHERE recipient = 'claude-lead' AND attempt_id IS NOT NULL"), {},
        "not a timeout kill"),
    "usage-unrecorded": (db_exec("UPDATE attempts SET usage_recorded = 0"), {}, "usage"),
    "delivery-active": (
        db_exec("UPDATE deliveries SET state = 'exited' WHERE recipient = 'claude-lead' "
                "AND attempt_id IS NOT NULL"), {}, "still exited"),
    "root-alive": (lambda w: w.processes.alive.__setitem__(4000, "start-4000"), {},
                   "still alive (same pid"),
    "descendant-alive": (with_tree(4100), {}, "pids [4100]"),
    "tree-unreadable": (unreadable_tree, {}, "could not be read"),
    "same-conversation": (None, dict(session=OLD.upper()), "different conversation"),
    "registered-to-other-lead": (None, dict(session=OTHER), "already registered to codex-lead"),
    "retired-conversation": (
        lambda w: (w.relay.db.executescript(lead_relay_successor.RETIRED), w.relay.db.execute(
            "INSERT INTO retired_reservations VALUES ('a0', ?, 'codex-lead', 0, 0, 'r', 'k', '{}')",
            (f"claude:{NEW}",))), {}, "retired reservation"),
    "wrong-confirmation": (None, dict(confirm="e7c8dfdf2210c057"), "--confirm must name"),
}


@pytest.mark.parametrize("name", list(REFUSALS))
def test_each_failed_precondition_is_refused_with_its_reason(tmp_path, name):
    setup, kwargs, reason = REFUSALS[name]
    w = orphaned(tmp_path)
    if setup:
        setup(w)
    before = snapshot(w)
    code, text = rebind(w, **kwargs)
    assert code == 1 and text.startswith("REFUSED") and reason in text, text
    assert snapshot(w) == before
    if setup is None or name == "descendant-alive":
        # The same world passes once the one failed condition is put right.
        w.tree[:] = []
        assert rebind(w)[0] == 0


def test_a_reused_pid_is_not_the_run(tmp_path):
    w = orphaned(tmp_path)
    w.processes.alive[4000] = "a-different-process"
    assert rebind(w)[0] == 0


@pytest.mark.parametrize("how", ["quit-unrecovered", "quit-recovered"])
def test_a_quit_run_is_refused_unless_proven_terminal(tmp_path, how):
    """2026-10-21: a turn that was quit is not proof. Gone while the relay was
    down, the run is `running` until recovery, then `exited` with no exit
    code and less than the timeout behind it."""
    w = World(tmp_path)
    w.backend = PerSession()
    w.relay.backends = {"claude": w.backend}
    w.processes.descendants = lambda pid, start: []
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.tick()
    w.backend.by_session[OLD] = UNKNOWN
    w.exit()                                    # quit; the relay hasn't seen it yet
    if how == "quit-recovered":
        w.restart()
        w.tick(advance=30)
    aid = w.relay.db.execute("SELECT attempt_id FROM attempts").fetchone()[0]
    w.aid = aid
    before = snapshot(w)
    code, text = rebind(w)
    assert code == 1, text
    assert ("is running" if how == "quit-unrecovered" else "not a timeout kill") in text, text
    assert snapshot(w) == before


def test_a_quit_the_relay_reaped_has_an_exit_code_and_is_terminal(tmp_path):
    w = World(tmp_path)
    w.backend = PerSession()
    w.relay.backends = {"claude": w.backend}
    w.processes.descendants = lambda pid, start: []
    mid = started(w)
    w.ack(mid, w.token(mid))
    w.backend.by_session[OLD] = UNKNOWN
    w.exit()
    w.tick()
    w.aid = w.relay.db.execute("SELECT attempt_id FROM attempts").fetchone()[0]
    code, text = rebind(w)
    assert code == 0 and "exited with code 0" in text, text


# --- §4 the old run's code paths never judge the successor -----------------------------


def test_release_never_judges_a_reservation_by_another_binding(tmp_path):
    """A binding changed by any other route (a manual edit, a legacy row): the
    old run's reservation must not be released because the NEW conversation
    reads CLOSED."""
    w = World(tmp_path)
    w.backend = PerSession()
    w.relay.backends = {"claude": w.backend}
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


# --- §2.8 the real process table ---------------------------------------------------------


def test_descendants_follow_an_orphaned_child_of_a_dead_root():
    """Host check of `ProcessApi.descendants`: the root dies, its child lives
    on, and the tree is not gone until the child is gone too."""
    api = lead_relay.ProcessApi()
    child = ("import subprocess, sys, time; "
             "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
             "stdout=subprocess.DEVNULL); print('ready', flush=True); time.sleep(60)")
    root = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True,
                            **lead_relay.separate_process_group())
    start = api.creation_time(root.pid)
    try:
        assert root.stdout.readline().strip() == "ready"   # the child has been started
        assert api.descendants(root.pid, start), "the child was never seen"
        root.kill()
        root.wait(timeout=10)
        assert not api.is_same(root.pid, start)
        assert lead_relay_successor.tree_gone(api, root.pid, start) is not None
    finally:
        root.stdout.close()
        api.kill_tree(root.pid)
        for pid in api.descendants(root.pid, start) if start else ():
            api.kill_tree(pid)
    deadline = time.time() + 20
    while lead_relay_successor.tree_gone(api, root.pid, start) and time.time() < deadline:
        time.sleep(0.2)
    assert lead_relay_successor.tree_gone(api, root.pid, start) is None
