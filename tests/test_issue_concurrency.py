"""Two callers issuing at once produce one activation, or none.

Sequential polling proved nothing about this. `advance` is idempotent when
called twice in a row because the first call moves the task out of the
advanceable state, and every earlier test exercised exactly that -- which is
the easy half, and not the half that goes wrong.

The hard half was a seam in `issue`: the activation was inserted and committed,
and the task transitioned in a *second* transaction. Two callers could both
insert before either transitioned, and the loser's activation sat live,
consuming host capacity, belonging to nobody, until its lease lapsed.

These run real threads against one database so the interleaving is the
database's rather than a mock's.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from controller import activations, db, engine, progression, states


LEASE = 900.0
DEADLINE = 5400.0
CAND = "1" * 40


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "controller.db")
    conn = db.connect(path)
    db.initialize(conn)
    activations.set_host_capacity(conn, host="officepc", max_concurrent=8)
    engine.create_task(
        conn, task_id="T-1", title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(conn, task_id="T-1", kind=kind, actor="admin",
                                authority=states.CONTROLLER)
    conn.close()
    return path


def connect(path):
    conn = db.connect(path)
    # Long enough that a contending writer waits for the lock rather than
    # failing instantly, which is what a real caller does.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def race(path, work, callers=2):
    """Run `work(conn)` in `callers` threads, released together."""
    ready = threading.Barrier(callers)
    results = []
    lock = threading.Lock()

    def run():
        conn = connect(path)
        try:
            ready.wait()
            outcome = ("ok", work(conn))
        except Exception as exc:
            outcome = ("error", f"{type(exc).__name__}: {exc}")
        finally:
            conn.close()

        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=run) for _ in range(callers)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=30)

    return results


def live_activations(path, task_id="T-1"):
    conn = connect(path)
    try:
        return conn.execute(
            "SELECT activation_id, stage, status FROM activations "
            "WHERE task_id = ? AND status IN (?, ?)",
            (task_id, activations.ISSUED, activations.CLAIMED),
        ).fetchall()
    finally:
        conn.close()


def transitions(path, kind, task_id="T-1"):
    conn = connect(path)
    try:
        return conn.execute(
            "SELECT event_id FROM events WHERE task_id = ? AND kind = ?",
            (task_id, kind),
        ).fetchall()
    finally:
        conn.close()


# --- Two callers issuing the same stage --------------------------------------


def test_two_concurrent_issues_produce_exactly_one_activation(db_path):
    """The blocker. Before the fix both callers inserted, and the loser's
    activation stayed live holding capacity."""
    def work(conn):
        return activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
        )

    results = race(db_path, work)

    assert len(live_activations(db_path)) == 1, live_activations(db_path)
    assert len([r for r in results if r[0] == "ok"]) == 1, results


def test_two_concurrent_issues_produce_exactly_one_transition(db_path):
    """An activation without its transition, or two transitions for one
    activation, is the state the schema's design note says cannot exist."""
    def work(conn):
        return activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
        )

    race(db_path, work)

    assert len(transitions(db_path, "author_activation_issued")) == 1


def test_the_loser_rolls_back_rather_than_orphaning_an_activation(db_path):
    """No row at all, not a row in some other status. A rolled-back insert
    leaves nothing; an orphan would still be counted by the next capacity
    check."""
    def work(conn):
        return activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
        )

    race(db_path, work)

    conn = connect(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM activations WHERE task_id = 'T-1'"
        ).fetchone()["n"]
    finally:
        conn.close()

    assert total == 1


def test_the_task_ends_in_one_consistent_state(db_path):
    def work(conn):
        return activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
        )

    race(db_path, work)

    conn = connect(db_path)
    try:
        task = engine.get_task(conn, "T-1")
    finally:
        conn.close()

    assert task["state"] == "AUTHOR_ASSIGNED"
    assert task["state_seq"] == 3


def test_four_concurrent_callers_still_produce_one(db_path):
    def work(conn):
        return activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
        )

    race(db_path, work, callers=4)

    assert len(live_activations(db_path)) == 1


# --- Two concurrent advance calls -------------------------------------------


def author_a_candidate(path):
    conn = connect(path)
    try:
        issued = activations.issue(
            conn, task_id="T-1", agent="chatgpt", host="officepc",
            stage="author", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE, expected_branch="task/T-1",
            repo_location="/repo",
        )
        activations.claim(conn, activation_id=issued["activation_id"],
                          agent="chatgpt")
        activations.submit_author_outcome(
            conn, activation_id=issued["activation_id"], agent="chatgpt",
            outcome="candidate", payload={"candidate_sha": CAND},
        )
    finally:
        conn.close()


def routing():
    return progression.Routing(
        verifier="gemini", integrator="claudecode", host="officepc",
        repo_location="/repo",
    )


def test_two_concurrent_advances_issue_one_review(db_path):
    """The path the live run actually uses, raced.

    Two pollers running on a timer is the normal deployment, not a corner
    case, and both reading `READY_REVIEW` before either issues is the ordinary
    interleaving rather than an unlucky one.
    """
    author_a_candidate(db_path)

    results = race(db_path, lambda conn: progression.advance(
        conn, routing=routing(), task_id="T-1"
    ))

    live = live_activations(db_path)

    assert len(live) == 1, live
    assert live[0]["stage"] == "review"
    assert len(transitions(db_path, "review_activation_issued")) == 1
    assert any(r[0] == "ok" for r in results)


def test_a_declining_advance_is_not_an_error(db_path):
    """The loser reports that it issued nothing rather than raising, so a
    poller does not treat an ordinary race as a fault."""
    author_a_candidate(db_path)

    results = race(db_path, lambda conn: progression.advance(
        conn, routing=routing(), task_id="T-1"
    ))

    issued = [
        record
        for status, value in results if status == "ok"
        for record in value
        if record.get("issued")
    ]

    assert len(issued) == 1, results
