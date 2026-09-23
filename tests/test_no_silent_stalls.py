"""No more silent stalls (#77).

T-ACC2-README was issued an author activation with no branch and no
repository, authored a candidate anyway, and was then declined for review
every 20 seconds for sixteen hours. The decline was correct and logged at
debug, so nothing anywhere said so.

Two changes, tested here:

1. An author activation without `expected_branch` and `repo_location` is
   refused when it is issued, where the operator is looking.
2. A decline that will not clear by itself is said once -- at WARNING and in
   the hub room -- and not every tick; one that clears by itself is not said.
"""

from __future__ import annotations

import logging

import pytest

import stall_watch
import supervisor
from controller import activations, db, engine, outcomes, progression, states

LEASE = 900.0
DEADLINE = 5400.0
CAND = "1" * 40


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "controller.db"))
    db.initialize(connection)
    activations.set_host_capacity(connection, host="officepc", max_concurrent=3)
    return connection


def make_task(conn, task_id="T-1"):
    engine.create_task(
        conn, task_id=task_id, title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(conn, task_id=task_id, kind=kind,
                                actor="admin", authority=states.CONTROLLER)
    return task_id


def issue_author(conn, task_id, **over):
    args = dict(task_id=task_id, agent="chatgpt", host="officepc",
                stage="author", lease_seconds=LEASE,
                hard_deadline_seconds=DEADLINE,
                expected_branch=f"task/{task_id}-a1", repo_location="/repo")
    args.update(over)
    return activations.issue(conn, **args)


def authored(conn, task_id):
    issued = issue_author(conn, task_id)
    activations.claim(conn, activation_id=issued["activation_id"], agent="chatgpt")
    outcomes.submit_author_outcome(
        conn, activation_id=issued["activation_id"], agent="chatgpt",
        outcome="candidate", payload={"candidate_sha": CAND},
    )
    return issued["activation_id"]


def routing(**over):
    args = {"verifier": "gemini", "integrator": "claudecode",
            "host": "officepc", "repo_location": ""}
    args.update(over)
    return progression.Routing(**args)


def only(records, task_id):
    [record] = [r for r in records if r["task_id"] == task_id]
    return record


# --- 1. Refused at issue ------------------------------------------------------


@pytest.mark.parametrize("missing", ["expected_branch", "repo_location"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_author_activation_without_where_is_refused(conn, missing, value):
    task = make_task(conn)

    with pytest.raises(activations.ActivationError, match=missing):
        issue_author(conn, task, **{missing: value})

    assert engine.get_task(conn, task)["state"] == "READY_AUTHOR", (
        "a refused issue must not move the task"
    )
    assert conn.execute("SELECT COUNT(*) FROM activations").fetchone()[0] == 0


def test_both_missing_names_both(conn):
    task = make_task(conn)

    with pytest.raises(activations.ActivationError) as refused:
        issue_author(conn, task, expected_branch=None, repo_location=None)

    assert "expected_branch and repo_location" in str(refused.value)


def test_an_author_activation_that_names_both_is_issued(conn):
    task = make_task(conn)
    issue_author(conn, task)

    assert engine.get_task(conn, task)["state"] == "AUTHOR_ASSIGNED"


# --- 2a. The controller says which declines persist ------------------------------


def test_the_t_acc2_decline_is_persistent(conn):
    """A legacy author activation with no branch -- as T-ACC2-README's is in
    the live ledger -- is declined as `no_producing_branch`, persistently."""
    task = make_task(conn)
    activation_id = authored(conn, task)
    conn.execute(
        "UPDATE activations SET expected_branch = NULL, repo_location = NULL "
        "WHERE activation_id = ?", (activation_id,),
    )
    conn.commit()

    record = only(progression.advance(conn, routing=routing()), task)

    assert record["issued"] is False
    assert record["reason_code"] == "no_producing_branch"
    assert record["persistent"] is True


def test_missing_routing_is_persistent(conn):
    task = make_task(conn)
    authored(conn, task)

    record = only(progression.advance(conn, routing=routing(verifier="")), task)

    assert record["reason_code"] == "routing_missing"
    assert record["persistent"] is True


def test_a_live_activation_is_not_persistent(conn):
    """A task in READY_REVIEW that still holds a live activation -- the
    in-flight case that must stay quiet."""
    task2 = make_task(conn, "T-2")
    authored(conn, task2)
    conn.execute(
        "INSERT INTO activations (activation_id, task_id, task_version, agent, "
        "host, role, stage, attempt_no, chargeable_attempt, issued_at, "
        "lease_expires_at, hard_deadline_at, heartbeat_seq, status) "
        "VALUES ('live', ?, 1, 'gemini', 'officepc', 'verifier', 'review', 9, "
        "0, 0, 9e12, 9e12, 0, ?)", (task2, activations.ISSUED),
    )
    conn.commit()

    record = only(progression.advance(conn, routing=routing()), task2)

    assert record["reason_code"] == "live_activation"
    assert record["persistent"] is False


def test_a_busy_host_is_not_persistent(conn):
    task = make_task(conn)
    authored(conn, task)
    activations.set_host_capacity(conn, host="officepc", max_concurrent=0)

    record = only(progression.advance(conn, routing=routing(repo_location="/repo")), task)

    assert record["reason_code"] == "host_at_capacity"
    assert record["persistent"] is False


def test_every_decline_carries_a_code_and_a_verdict(conn):
    task = make_task(conn)
    authored(conn, task)

    for record in progression.advance(conn, routing=routing(verifier="")):
        if not record["issued"]:
            assert record["reason_code"]
            assert isinstance(record["persistent"], bool)


# --- 2b. Said once -------------------------------------------------------------


def stall(task_id="T-1", code="no_producing_branch", persistent=True, stage="review"):
    return {"task_id": task_id, "state": "READY_REVIEW", "stage": stage,
            "issued": False, "reason": f"because {code}",
            "reason_code": code, "persistent": persistent}


def test_a_persistent_stall_is_announced_once():
    watch = stall_watch.StallWatch()

    first = watch.observe([stall()])
    again = [watch.observe([stall()]) for _ in range(5)]

    assert [t for t, _ in first] == ["T-1"]
    assert "T-1" in first[0][1] and "because no_producing_branch" in first[0][1]
    assert again == [[]] * 5


def test_a_self_clearing_decline_is_never_announced():
    watch = stall_watch.StallWatch()

    assert watch.observe([stall(code="live_activation", persistent=False)]) == []


def test_a_changed_reason_is_announced_again():
    watch = stall_watch.StallWatch()
    watch.observe([stall()])

    assert [t for t, _ in watch.observe([stall(code="routing_missing")])] == ["T-1"]


def test_a_stall_that_clears_and_returns_is_news_again():
    watch = stall_watch.StallWatch()
    watch.observe([stall()])
    watch.observe([])

    assert [t for t, _ in watch.observe([stall()])] == ["T-1"]


def test_a_line_that_did_not_get_out_is_retried():
    watch = stall_watch.StallWatch()
    watch.observe([stall()])
    watch.forget("T-1")

    assert [t for t, _ in watch.observe([stall()])] == ["T-1"]


# --- 2c. The supervisor says it, in the log and the room ------------------------


class Room:
    def __init__(self, accepts=True):
        self.lines = []
        self.accepts = accepts

    def say(self, text):
        self.lines.append(text)
        return self.accepts


def bare_supervisor(answers, room):
    sup = object.__new__(supervisor.Supervisor)
    sup.stalls = stall_watch.StallWatch()
    sup.narration = room
    replies = iter(answers)
    sup._post = lambda path: next(replies)
    return sup


def test_a_stall_is_one_warning_and_one_room_line_across_ticks(caplog):
    room = Room()
    sup = bare_supervisor([{"considered": [stall()]}] * 4, room)

    with caplog.at_level(logging.DEBUG, logger="supervisor"):
        for _ in range(4):
            sup.advance()

    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "stalled" in r.getMessage()]
    assert len(warnings) == 1
    assert len(room.lines) == 1
    assert "T-1" in room.lines[0]


def test_a_self_clearing_decline_stays_at_debug(caplog):
    room = Room()
    quiet = stall(code="live_activation", persistent=False)
    sup = bare_supervisor([{"considered": [quiet]}] * 3, room)

    with caplog.at_level(logging.DEBUG, logger="supervisor"):
        for _ in range(3):
            sup.advance()

    assert room.lines == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_refused_room_line_is_tried_again_next_tick():
    room = Room(accepts=False)
    sup = bare_supervisor([{"considered": [stall()]}] * 3, room)

    for _ in range(3):
        sup.advance()

    assert len(room.lines) == 3


def test_an_unreachable_controller_forgets_nothing():
    """`advance` answering nothing is not "the stall cleared"."""
    room = Room()
    sup = bare_supervisor([{"considered": [stall()]}, None,
                           {"considered": [stall()]}], room)

    for _ in range(3):
        sup.advance()

    assert len(room.lines) == 1
