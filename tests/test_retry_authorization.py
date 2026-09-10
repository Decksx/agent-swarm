"""A rejected task must have a way back, and a bottom to it.

`retry_authorized` and `budget_exhausted` sat in the state table with nothing
emitting either, so CHANGES_REQUESTED was reachable and terminal in practice --
a task the reviewer sent back could not be worked on again.

The budget is a loop detector rather than a cost control. Two rejections in a
row means the reviewer is asking for something the author cannot produce from
the contract it has, and the third attempt is the same generation with the same
inputs.
"""

from __future__ import annotations

import pytest

from controller import activations, engine, states
from controller.db import open_controller_db

LEASE = 900.0
DEADLINE = 5400.0
T0 = 1_000_000.0


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 4)
    yield connection
    connection.close()


@pytest.fixture
def rejected(conn):
    """A task that has been authored once and sent back."""
    engine.create_task(
        conn, task_id="T-1", title="pilot", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin",
    )

    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-1", kind=kind, actor="c", authority=states.CONTROLLER
        )

    issued = activations.issue(
        conn, task_id="T-1", agent="chatgpt", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=issued["activation_id"], agent="chatgpt", now=T0 + 1
    )
    engine.apply_transition(
        conn, task_id="T-1", kind="author_defect", actor="c",
        authority=states.CONTROLLER, activation_id=issued["activation_id"],
    )

    assert engine.get_task(conn, "T-1")["state"] == "CHANGES_REQUESTED"
    return "T-1"


def state(conn, task_id="T-1"):
    return engine.get_task(conn, task_id)["state"]


# --- The way back -----------------------------------------------------------


def test_a_rejected_task_can_be_authored_again(conn, rejected):
    engine.authorize_retry(conn, task_id="T-1", actor="admin")

    assert state(conn) == "READY_AUTHOR"


def test_the_authorization_is_recorded_with_its_reasoning(conn, rejected):
    outcome = engine.authorize_retry(conn, task_id="T-1", actor="admin")
    kinds = [event["kind"] for event in engine.event_log(conn, "T-1")]

    assert "retry_authorized" in kinds
    assert outcome["to_state"] == "READY_AUTHOR"


def test_it_carries_controller_authority_not_the_operators(conn, rejected):
    """An operator who could declare a retry could buy attempts forever.

    The admin transition route applies ADMIN authority, and the state table
    gives this transition to the controller alone -- so the route cannot be
    used for it, which is the property being pinned here.
    """
    with pytest.raises(states.NotAuthorized):
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.ADMIN,
        )


# --- And the bottom of it ---------------------------------------------------


def test_attempts_are_counted_from_activations_actually_issued(conn, rejected):
    """Not from a counter, which repair or re-versioning would rewrite."""
    engine.authorize_retry(conn, task_id="T-1", actor="admin", max_attempts=1)

    assert state(conn) == "NEEDS_HUMAN"


def test_exhaustion_escalates_rather_than_raising(conn, rejected):
    """Refusing another attempt is a decision the ledger should carry."""
    outcome = engine.authorize_retry(
        conn, task_id="T-1", actor="admin", max_attempts=1
    )

    assert outcome["to_state"] == "NEEDS_HUMAN"

    events = {event["kind"] for event in engine.event_log(conn, "T-1")}
    assert "budget_exhausted" in events
    assert "retry_authorized" not in events


def test_the_budget_counts_author_attempts_only(conn):
    """A review activation is not an attempt at the work.

    Walked the long way round -- author, candidate, review, rejection --
    because that is the only order in which a task acquires a review
    activation, and the shortcut would be testing a state the controller
    never produces.
    """
    engine.create_task(
        conn, task_id="T-3", title="pilot", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin",
    )

    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-3", kind=kind, actor="c", authority=states.CONTROLLER
        )

    author = activations.issue(
        conn, task_id="T-3", agent="chatgpt", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="chatgpt", now=T0 + 1
    )
    engine.apply_transition(
        conn, task_id="T-3", kind="candidate_submitted", actor="chatgpt",
        authority=states.AUTHOR, activation_id=author["activation_id"],
    )

    review = activations.issue(
        conn, task_id="T-3", agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0 + 2,
        expected_branch="task/T-3", expected_parent="0" * 40,
        expected_candidate="1" * 40, repo_location="OFFICEPC:/repo",
    )
    activations.claim(
        conn, activation_id=review["activation_id"], agent="gemini", now=T0 + 3
    )
    engine.apply_transition(
        conn, task_id="T-3", kind="author_defect", actor="c",
        authority=states.CONTROLLER, activation_id=review["activation_id"],
    )

    assert state(conn, "T-3") == "CHANGES_REQUESTED"

    # Two activations exist; only one of them was an attempt at the work.
    engine.authorize_retry(conn, task_id="T-3", actor="admin", max_attempts=2)

    assert state(conn, "T-3") == "READY_AUTHOR"


def test_a_task_that_was_not_rejected_cannot_be_retried(conn):
    engine.create_task(
        conn, task_id="T-2", title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin",
    )

    with pytest.raises(states.TransitionRejected):
        engine.authorize_retry(conn, task_id="T-2", actor="admin")
