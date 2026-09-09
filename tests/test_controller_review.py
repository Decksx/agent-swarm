"""Stage outcomes: who may report them, and on whose authority.

Both stages share one mechanism and one reason for existing, so they share a
file. The review gate is the larger half and comes first; the author outcomes
are the same argument applied to a worker reporting failure.

Section 8 makes `review_requirements_satisfied` a controller transition so a
verifier cannot advance a task by declaring a gate met. A review activation
carries the *verifier* role, so the obvious route -- a reviewer calling
`submit_result` with that event -- is refused as unauthorized, and has to be.

`submit_review_judgment` is the route that works: it applies the event with
controller authority, but only after establishing that the caller is the agent
holding that specific live review activation. These tests pin both halves,
because getting only one of them right is what a plausible-looking bug looks
like here.

They also pin what the MVP deliberately does *not* do. The deterministic
completion predicates are unimplemented, so `satisfied` is accepted on the
reviewer's word with no evidence at all. That is asserted rather than left
unsaid: if predicates are added later, the test that changes tells whoever
adds them exactly which promise they are keeping.
"""

from __future__ import annotations

import pytest

from controller import activations, engine, states
from controller.db import open_controller_db

T0 = 1_000_000.0
LEASE = 300.0
DEADLINE = 5400.0


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    # Two slots: the author activation is finished before the review is issued
    # in most of these, but the fixture should not be the thing that enforces
    # that ordering.
    activations.set_host_capacity(connection, "OFFICEPC", 2)
    yield connection
    connection.close()


@pytest.fixture
def under_review(conn):
    """A task in REVIEWING with a live review activation held by gemini.

    Driven through the real transitions rather than by writing the state
    directly, so the fixture cannot set up a state the machine would refuse to
    produce.
    """
    engine.create_task(
        conn, task_id="T-1", title="pilot", objective="o",
        contract_yaml="schema_version: 7\n", base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-1", kind=kind, actor="c", authority=states.CONTROLLER
        )

    author = activations.issue(
        conn, task_id="T-1", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="claudecode", now=T0
    )
    activations.submit_result(
        conn, activation_id=author["activation_id"], agent="claudecode",
        kind="candidate_submitted", now=T0 + 1,
    )

    review = activations.issue(
        conn, task_id="T-1", agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0 + 2,
    )
    activations.claim(
        conn, activation_id=review["activation_id"], agent="gemini", now=T0 + 2
    )

    assert engine.get_task(conn, "T-1")["state"] == "REVIEWING"
    return review["activation_id"]


# --- The gate cannot be closed by the reviewer's own authority ---------------


def test_a_reviewer_cannot_emit_the_gate_event_through_submit_result(conn, under_review):
    """The verifier role is not authorized for `review_requirements_satisfied`.

    This is the check the whole split exists for. If it ever passes, a
    verifier can advance its own task by declaring the gate met, and
    submit_review_judgment's controller authority becomes decoration.
    """
    with pytest.raises(states.NotAuthorized):
        activations.submit_result(
            conn, activation_id=under_review, agent="gemini",
            kind="review_requirements_satisfied", now=T0 + 3,
        )

    # The task did not move, and the activation was not consumed by the
    # rejected attempt.
    assert engine.get_task(conn, "T-1")["state"] == "REVIEWING"
    assert activations.get_activation(conn, under_review)["status"] == "CLAIMED"


def test_the_judgment_route_applies_it_with_controller_authority(conn, under_review):
    outcome = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )

    assert outcome["to_state"] == "READY_INTEGRATION"
    assert outcome["judgment"] == "satisfied"
    assert outcome["replayed"] is False
    assert engine.get_task(conn, "T-1")["state"] == "READY_INTEGRATION"

    # The event records the controller as the authority and gemini as the
    # actor, so the log shows who judged and under whose authority it applied.
    event = engine.event_log(conn, "T-1")[-1]
    assert event["kind"] == "review_requirements_satisfied"
    assert event["authority"] == states.CONTROLLER
    assert event["actor"] == "gemini"


# --- Only the holder of that activation may judge ---------------------------


def test_another_agent_cannot_submit_the_judgment(conn, under_review):
    """Holding a credential is not holding the activation."""
    with pytest.raises(activations.NotTheAssignedWorker):
        activations.submit_review_judgment(
            conn, activation_id=under_review, agent="chatgpt",
            judgment="satisfied", now=T0 + 3,
        )

    assert engine.get_task(conn, "T-1")["state"] == "REVIEWING"


def test_an_expired_lease_cannot_judge(conn, under_review):
    with pytest.raises(activations.LeaseExpired):
        activations.submit_review_judgment(
            conn, activation_id=under_review, agent="gemini",
            judgment="satisfied", now=T0 + 2 + LEASE + 1,
        )

    assert engine.get_task(conn, "T-1")["state"] == "REVIEWING"


def test_identity_is_checked_before_expiry(conn, under_review):
    """A stranger learns nothing about the activation's timing.

    Same ordering property the activation operations already have: the wrong
    agent gets NotTheAssignedWorker whether or not the lease has lapsed.
    """
    with pytest.raises(activations.NotTheAssignedWorker):
        activations.submit_review_judgment(
            conn, activation_id=under_review, agent="chatgpt",
            judgment="satisfied", now=T0 + 2 + LEASE + 1,
        )


def test_an_author_activation_cannot_carry_a_review_judgment(conn):
    """The stage is part of the authorization, not just a label."""
    engine.create_task(
        conn, task_id="T-2", title="p", objective="o",
        contract_yaml="schema_version: 7\n", base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-2", kind=kind, actor="c", authority=states.CONTROLLER
        )

    author = activations.issue(
        conn, task_id="T-2", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="claudecode", now=T0
    )

    with pytest.raises(activations.NotAReviewActivation):
        activations.submit_review_judgment(
            conn, activation_id=author["activation_id"], agent="claudecode",
            judgment="satisfied", now=T0 + 1,
        )


# --- Judgments other than "satisfied" ---------------------------------------


def test_changes_requested_sends_the_task_back(conn, under_review):
    outcome = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="changes_requested", payload={"why": "tests do not run"},
        now=T0 + 3,
    )

    assert outcome["to_state"] == "CHANGES_REQUESTED"
    assert engine.get_task(conn, "T-1")["state"] == "CHANGES_REQUESTED"


def test_decision_required_escalates(conn, under_review):
    outcome = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="decision_required", now=T0 + 3,
    )

    assert outcome["to_state"] == "NEEDS_HUMAN"


def test_an_unknown_judgment_is_refused_without_touching_the_task(conn, under_review):
    with pytest.raises(activations.ActivationError):
        activations.submit_review_judgment(
            conn, activation_id=under_review, agent="gemini",
            judgment="looks-fine-to-me", now=T0 + 3,
        )

    assert engine.get_task(conn, "T-1")["state"] == "REVIEWING"
    assert activations.get_activation(conn, under_review)["status"] == "CLAIMED"


# --- Idempotency, on the same terms as any other result ---------------------


def test_redelivering_the_same_judgment_replays_it(conn, under_review):
    first = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )
    second = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 4,
    )

    assert second["replayed"] is True
    assert second["event_id"] == first["event_id"]
    assert second["state_seq"] == first["state_seq"]

    # One event, not two: a redelivery must not append a second transition.
    kinds = [e["kind"] for e in engine.event_log(conn, "T-1")]
    assert kinds.count("review_requirements_satisfied") == 1


def test_changing_the_judgment_after_the_fact_is_refused(conn, under_review):
    """A reviewer does not get to withdraw a judgment by sending another."""
    activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )

    with pytest.raises(activations.ConflictingResult):
        activations.submit_review_judgment(
            conn, activation_id=under_review, agent="gemini",
            judgment="changes_requested", now=T0 + 4,
        )

    assert engine.get_task(conn, "T-1")["state"] == "READY_INTEGRATION"


def test_the_judgment_releases_the_host_slot(conn, under_review):
    activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )

    assert activations.get_activation(conn, under_review)["status"] == "DONE"


# --- What the MVP deliberately does not check -------------------------------


def test_satisfied_is_accepted_with_no_evidence_at_all(conn, under_review):
    """Characterization, not endorsement.

    The deterministic completion predicates are unimplemented, so the gate
    closes on the reviewer's word with zero evidence rows in the database.
    Asserted so the limitation is visible in the suite rather than only in a
    comment -- and so that whoever implements the predicates has a test that
    fails and tells them what promise they are now keeping.
    """
    assert conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"] == 0

    outcome = activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )

    assert outcome["to_state"] == "READY_INTEGRATION"


def test_the_task_stops_at_ready_integration(conn, under_review):
    """A satisfied review does not mean merged.

    Nothing integrates yet, so READY_INTEGRATION is where an ordinary task
    stops. A demonstration that wants to finish without a real integrator has
    to say so explicitly; it does not happen by default.
    """
    activations.submit_review_judgment(
        conn, activation_id=under_review, agent="gemini",
        judgment="satisfied", now=T0 + 3,
    )

    task = engine.get_task(conn, "T-1")
    assert task["state"] == "READY_INTEGRATION"
    assert task["state"] != "COMPLETE"


# --- Author outcomes: the same argument, on the other stage -----------------


@pytest.fixture
def authoring(conn):
    """A task in AUTHORING with a live author activation held by claudecode."""
    engine.create_task(
        conn, task_id="T-A", title="pilot", objective="o",
        contract_yaml="schema_version: 7\n", base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-A", kind=kind, actor="c", authority=states.CONTROLLER
        )

    author = activations.issue(
        conn, task_id="T-A", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="claudecode", now=T0
    )

    assert engine.get_task(conn, "T-A")["state"] == "AUTHORING"
    return author["activation_id"]


def test_a_worker_cannot_emit_a_failure_event_itself(conn, authoring):
    """`author_defect` is a controller transition, and must stay one.

    A worker able to emit it could put its own task into CHANGES_REQUESTED,
    which is a verdict about the work rather than a report about the run.
    """
    with pytest.raises(states.NotAuthorized):
        activations.submit_result(
            conn, activation_id=authoring, agent="claudecode",
            kind="author_defect", now=T0 + 1,
        )

    assert engine.get_task(conn, "T-A")["state"] == "AUTHORING"


@pytest.mark.parametrize("outcome,expected", [
    ("candidate", "READY_REVIEW"),
    ("failed", "CHANGES_REQUESTED"),
    ("blocked", "AUTHOR_BLOCKED"),
])
def test_each_author_outcome_lands_where_it_should(conn, authoring, outcome, expected):
    """Before this existed a worker could report success and nothing else."""
    result = activations.submit_author_outcome(
        conn, activation_id=authoring, agent="claudecode",
        outcome=outcome, now=T0 + 1,
    )

    assert result["to_state"] == expected
    assert engine.get_task(conn, "T-A")["state"] == expected


def test_blocked_is_recoverable_and_failed_is_a_verdict(conn, authoring):
    """The distinction is why there are two failure outcomes and not one.

    AUTHOR_BLOCKED says the host could not run this; an operator repairs the
    environment and it returns to READY_AUTHOR with nothing said about the
    task. CHANGES_REQUESTED says the attempt was wrong.
    """
    activations.submit_author_outcome(
        conn, activation_id=authoring, agent="claudecode",
        outcome="blocked", payload={"reason": "rate limit guard"}, now=T0 + 1,
    )

    engine.apply_transition(
        conn, task_id="T-A", kind="environment_repaired", actor="c",
        authority=states.CONTROLLER,
    )

    assert engine.get_task(conn, "T-A")["state"] == "READY_AUTHOR"


def test_another_agent_cannot_report_this_activation(conn, authoring):
    with pytest.raises(activations.NotTheAssignedWorker):
        activations.submit_author_outcome(
            conn, activation_id=authoring, agent="chatgpt",
            outcome="candidate", now=T0 + 1,
        )


def test_a_review_judgment_cannot_be_submitted_against_an_author_activation(
    conn, authoring
):
    """The stage is part of the authorization, both ways round."""
    with pytest.raises(activations.NotAReviewActivation):
        activations.submit_review_judgment(
            conn, activation_id=authoring, agent="claudecode",
            judgment="satisfied", now=T0 + 1,
        )


def test_redelivering_an_author_outcome_replays_it(conn, authoring):
    """A worker retrying after a dropped response must not run twice."""
    first = activations.submit_author_outcome(
        conn, activation_id=authoring, agent="claudecode",
        outcome="candidate", now=T0 + 1,
    )
    second = activations.submit_author_outcome(
        conn, activation_id=authoring, agent="claudecode",
        outcome="candidate", now=T0 + 2,
    )

    assert second["replayed"] is True
    assert second["event_id"] == first["event_id"]

    kinds = [e["kind"] for e in engine.event_log(conn, "T-A")]
    assert kinds.count("candidate_submitted") == 1


def test_reporting_a_different_outcome_afterwards_is_refused(conn, authoring):
    activations.submit_author_outcome(
        conn, activation_id=authoring, agent="claudecode",
        outcome="candidate", now=T0 + 1,
    )

    with pytest.raises(activations.ConflictingResult):
        activations.submit_author_outcome(
            conn, activation_id=authoring, agent="claudecode",
            outcome="failed", now=T0 + 2,
        )
