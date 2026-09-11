"""Issuing the next stage, and declining to.

The third of the three operator steps between stages. The other two belong to
the author's host; this one has to be the controller's, because issuing an
activation is granting permission to act and a worker that could issue its own
next stage could grant itself the work.

Meant to be polled, so the interesting property is what it does the second
time: nothing.
"""

from __future__ import annotations

import pytest

from controller import activations, db, engine, progression, states


LEASE = 900.0
DEADLINE = 5400.0
CAND = "1" * 40


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "controller.db"))
    db.initialize(connection)
    activations.set_host_capacity(connection, host="officepc", max_concurrent=3)
    return connection


def routing(**over):
    args = {"verifier": "gemini", "integrator": "claudecode",
            "host": "officepc", "repo_location": "/repo"}
    args.update(over)
    return progression.Routing(**args)


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


def author(conn, task_id, candidate=CAND):
    issued = activations.issue(
        conn, task_id=task_id, agent="chatgpt", host="officepc",
        stage="author", lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"task/{task_id}",
    )
    activations.claim(conn, activation_id=issued["activation_id"],
                      agent="chatgpt")
    activations.submit_author_outcome(
        conn, activation_id=issued["activation_id"], agent="chatgpt",
        outcome="candidate", payload={"candidate_sha": candidate},
    )
    return issued["activation_id"]


def review(conn, task_id, activation_id):
    activations.claim(conn, activation_id=activation_id, agent="gemini")
    activations.submit_review_judgment(
        conn, activation_id=activation_id, agent="gemini",
        judgment="satisfied",
    )


def only(records, task_id):
    matching = [r for r in records if r["task_id"] == task_id]
    assert len(matching) == 1, matching
    return matching[0]


# --- The two boundaries it closes -------------------------------------------


def test_a_submitted_candidate_gets_its_review_issued(conn):
    task = make_task(conn)
    author(conn, task)

    record = only(progression.advance(conn, routing=routing()), task)

    assert record["issued"] is True
    assert record["stage"] == "review"
    assert record["agent"] == "gemini"
    assert engine.get_task(conn, task)["state"] == "REVIEW_ASSIGNED"


def test_an_approval_gets_its_integration_issued(conn):
    task = make_task(conn)
    author(conn, task)
    issued = only(progression.advance(conn, routing=routing()), task)
    review(conn, task, issued["activation_id"])

    record = only(progression.advance(conn, routing=routing()), task)

    assert record["issued"] is True
    assert record["stage"] == "integrate"
    assert record["agent"] == "claudecode"
    assert engine.get_task(conn, task)["state"] == "INTEGRATING"


def test_the_whole_handoff_runs_without_an_operator(conn):
    """Author, advance, review, advance. Nobody issues anything by hand."""
    task = make_task(conn)
    author(conn, task)

    first = only(progression.advance(conn, routing=routing()), task)
    review(conn, task, first["activation_id"])
    second = only(progression.advance(conn, routing=routing()), task)

    assert first["stage"] == "review"
    assert second["stage"] == "integrate"
    assert engine.get_task(conn, task)["approved_candidate_sha"] == CAND


# --- Safe to poll -----------------------------------------------------------


def test_a_second_call_issues_nothing_more(conn):
    """The property that matters: polling cannot hand one task to two workers.

    Two guards produce it, and the outer one fires first. Issuing moves the
    task out of the advanceable state, so the second call does not consider it
    at all; the live-activation check is the inner guard, for a concurrent
    caller that read the state before the first issue committed.
    """
    task = make_task(conn)
    author(conn, task)
    progression.advance(conn, routing=routing())
    progression.advance(conn, routing=routing())

    issued = conn.execute(
        "SELECT COUNT(*) AS n FROM activations WHERE task_id = ? "
        "AND stage = 'review'",
        (task,),
    ).fetchone()

    assert issued["n"] == 1


def test_an_issued_but_unclaimed_activation_counts_as_live(conn):
    """The inner guard, exercised directly, because reaching it through
    `advance` needs a race this test cannot stage.

    An activation that has been issued but not claimed is still a permission
    somebody holds, so a second issue would put the same task in two workers'
    hands.
    """
    task = make_task(conn)
    author(conn, task)
    progression.advance(conn, routing=routing())

    live = conn.execute(
        "SELECT status FROM activations WHERE task_id = ? AND stage = 'review'",
        (task,),
    ).fetchone()

    assert live["status"] == activations.ISSUED
    assert progression._has_live_activation(conn, task) is True


def test_a_task_with_nothing_live_is_advanceable(conn):
    """The inner guard's other side, so it is not vacuously true."""
    task = make_task(conn)
    author(conn, task)

    assert progression._has_live_activation(conn, task) is False


def test_nothing_ready_is_reported_as_nothing_rather_than_silence(conn):
    make_task(conn)

    assert progression.advance(conn, routing=routing()) == []


def test_a_task_in_another_state_is_not_advanced(conn):
    task = make_task(conn)

    assert [r for r in progression.advance(conn, routing=routing())
            if r["task_id"] == task] == []


# --- It refuses to guess ----------------------------------------------------


def test_an_unconfigured_verifier_advances_nothing(conn):
    """A controller that guessed who should review would assign work to
    whoever it happened to name."""
    task = make_task(conn)
    author(conn, task)

    record = only(progression.advance(conn, routing=routing(verifier="")), task)

    assert record["issued"] is False
    assert "verifier" in record["reason"]
    assert engine.get_task(conn, task)["state"] == "READY_REVIEW"


def test_an_unconfigured_host_advances_nothing(conn):
    task = make_task(conn)
    author(conn, task)

    record = only(progression.advance(conn, routing=routing(host="")), task)

    assert record["issued"] is False
    assert "host" in record["reason"]


def test_a_declined_task_is_reported_not_omitted(conn):
    """A poller needs to tell "nothing was ready" from "something was ready
    and could not be started"."""
    task = make_task(conn)
    author(conn, task)

    records = progression.advance(conn, routing=routing(repo_location=""))

    assert only(records, task)["issued"] is False
    assert records != []


def test_the_branch_comes_from_the_ledger_not_from_the_task_id(conn):
    """They agree today, and a constructed one would keep agreeing right up
    until somebody issued an activation with a different branch."""
    task = make_task(conn, "T-9")
    issued = activations.issue(
        conn, task_id=task, agent="chatgpt", host="officepc", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch="feature/deliberately-different",
    )
    activations.claim(conn, activation_id=issued["activation_id"],
                      agent="chatgpt")
    activations.submit_author_outcome(
        conn, activation_id=issued["activation_id"], agent="chatgpt",
        outcome="candidate", payload={"candidate_sha": CAND},
    )

    record = only(progression.advance(conn, routing=routing()), task)

    assert record["expected_branch"] == "feature/deliberately-different"


def test_a_full_host_is_not_an_error(conn):
    """The host is busy and the task will be advanced by a later call, which
    is exactly what a queue does."""
    activations.set_host_capacity(conn, host="officepc", max_concurrent=1)
    first = make_task(conn, "T-A")
    second = make_task(conn, "T-B")
    author(conn, first)
    author(conn, second)

    # One author activation is still live, filling the single slot.
    records = progression.advance(conn, routing=routing())

    assert any(not r["issued"] for r in records)


def test_one_task_can_be_advanced_on_its_own(conn):
    make_task(conn, "T-A")
    make_task(conn, "T-B")
    author(conn, "T-A")
    author(conn, "T-B")

    records = progression.advance(conn, routing=routing(), task_id="T-A")

    assert [r["task_id"] for r in records] == ["T-A"]
