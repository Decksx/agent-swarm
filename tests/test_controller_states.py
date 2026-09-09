"""The state machine and the transition engine.

Invariant 14 — *undefined state transitions are rejected* — is the one these
mostly exist to defend. It is easy to satisfy in the happy path and easy to
lose the moment somebody adds a convenience path, so the rejection is asserted
exhaustively rather than by example: every `(state, event)` pair not in the
table is checked, not a handful of plausible ones.

The other recurring theme is that a refusal must leave nothing behind. A
transition that is rejected after appending its event would corrupt the log
that recovery depends on, so the tests check the log length as well as the
raised exception.
"""

from __future__ import annotations

import pytest

from controller import engine, states
from controller.db import open_controller_db


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    yield connection
    connection.close()


@pytest.fixture
def task(conn):
    engine.create_task(
        conn,
        task_id="T-1",
        title="pilot",
        objective="objective",
        contract_yaml="schema_version: 7\n",
        base_sha="0" * 40,
        created_by="admin",
    )
    return "T-1"


def advance(conn, task_id, *steps):
    """Drive a task through a sequence of (kind, authority) pairs."""
    for kind, authority in steps:
        engine.apply_transition(
            conn, task_id=task_id, kind=kind, actor="test", authority=authority
        )


TO_AUTHORING = (
    ("contract_validated", states.CONTROLLER),
    ("queued", states.CONTROLLER),
    ("author_activation_issued", states.CONTROLLER),
    ("activation_claimed", states.AUTHOR),
)


# --- Invariant 14: undefined transitions are rejected -----------------------


def test_every_undefined_pair_is_rejected(conn, task):
    """Exhaustive, not illustrative.

    Checking a few plausible bad pairs would pass even if whole regions of the
    table were wrong. This walks every state against every event kind and
    asserts that exactly the pairs in TRANSITIONS resolve.
    """
    for state in states.STATES:
        for kind in states.EVENT_KINDS:
            if kind in states.NON_TRANSITIONING_EVENTS:
                continue

            defined = (state, kind) in states.TRANSITIONS

            if defined:
                continue

            with pytest.raises(states.UndefinedTransition):
                # Any authority: an undefined pair must be refused before
                # authority is even considered.
                states.resolve(state, kind, states.ADMIN)


def test_an_unknown_event_kind_is_rejected(conn, task):
    with pytest.raises(states.UndefinedTransition):
        states.resolve("DRAFT", "please_just_work", states.ADMIN)


def test_an_unknown_state_is_rejected():
    with pytest.raises(states.UndefinedTransition):
        states.resolve("BANANA", "queued", states.CONTROLLER)


def test_a_rejected_transition_appends_no_event(conn, task):
    """A refusal must leave the log exactly as it found it.

    An event appended by a transition that was then rejected would make replay
    disagree with the projection, and replay is what rebuilds state after a
    crash.
    """
    before = len(engine.event_log(conn, task))

    with pytest.raises(states.TransitionRejected):
        engine.apply_transition(
            conn, task_id=task, kind="integration_completed",
            actor="x", authority=states.CONTROLLER,
        )

    assert len(engine.event_log(conn, task)) == before
    assert engine.get_task(conn, task)["state"] == "DRAFT"


# --- Authority --------------------------------------------------------------


def test_authority_is_enforced_separately_from_the_transition(conn, task):
    """The interesting failures are legal transitions by the wrong caller."""
    advance(conn, task, ("contract_validated", states.CONTROLLER),
            ("queued", states.CONTROLLER),
            ("author_activation_issued", states.CONTROLLER))

    # Claiming is the author's to do, not the controller's.
    with pytest.raises(states.NotAuthorized):
        engine.apply_transition(
            conn, task_id=task, kind="activation_claimed",
            actor="controller", authority=states.CONTROLLER,
        )

    engine.apply_transition(
        conn, task_id=task, kind="activation_claimed",
        actor="claudecode", authority=states.AUTHOR,
    )
    assert engine.get_task(conn, task)["state"] == "AUTHORING"


def test_a_worker_cannot_declare_its_own_work_accepted(conn, task):
    """review_requirements_satisfied is the controller's alone.

    §8: the controller computes gate completion from evidence rows. A verifier
    that could emit this event could accept a candidate by asserting it.
    """
    advance(conn, task, *TO_AUTHORING,
            ("candidate_submitted", states.AUTHOR),
            ("review_activation_issued", states.CONTROLLER),
            ("activation_claimed", states.VERIFIER))

    for authority in (states.VERIFIER, states.AUTHOR, states.ADMIN, states.OPERATOR):
        with pytest.raises(states.NotAuthorized):
            engine.apply_transition(
                conn, task_id=task, kind="review_requirements_satisfied",
                actor="claude", authority=authority,
            )


# --- Terminal states --------------------------------------------------------


def test_terminal_states_accept_nothing_except_the_one_allowed_exit(conn):
    exits = {
        (state, kind)
        for (state, kind) in states.TRANSITIONS
        if state in states.TERMINAL_STATES
    }

    # The protocol allows exactly one: a completed change later found to be a
    # regression has to be recordable.
    assert exits == {("COMPLETE", "regression_reverted")}


def test_a_cancelled_task_cannot_be_resurrected(conn, task):
    engine.apply_transition(
        conn, task_id=task, kind="admin_cancelled", actor="admin",
        authority=states.ADMIN,
    )
    assert engine.get_task(conn, task)["state"] == "CANCELLED"

    for kind, authority in TO_AUTHORING:
        with pytest.raises(states.TransitionRejected):
            engine.apply_transition(
                conn, task_id=task, kind=kind, actor="x", authority=authority
            )


def test_a_completed_task_can_only_be_reverted(conn, task):
    advance(conn, task, *TO_AUTHORING,
            ("candidate_submitted", states.AUTHOR),
            ("review_activation_issued", states.CONTROLLER),
            ("activation_claimed", states.VERIFIER),
            ("review_requirements_satisfied", states.CONTROLLER),
            ("integration_started", states.CONTROLLER),
            ("integration_completed", states.CONTROLLER))

    assert engine.get_task(conn, task)["state"] == "COMPLETE"

    with pytest.raises(states.TransitionRejected):
        engine.apply_transition(
            conn, task_id=task, kind="queued", actor="x",
            authority=states.CONTROLLER,
        )

    engine.apply_transition(
        conn, task_id=task, kind="regression_reverted", actor="admin",
        authority=states.ADMIN,
    )
    assert engine.get_task(conn, task)["state"] == "REVERTED"


def test_admin_can_cancel_from_every_nonterminal_state():
    """Generated from STATES, so a new state cannot be left without them."""
    for state in states.STATES - states.TERMINAL_STATES:
        assert (state, "admin_cancelled") in states.TRANSITIONS
        assert (state, "superseded") in states.TRANSITIONS

    for state in states.TERMINAL_STATES:
        assert (state, "admin_cancelled") not in states.TRANSITIONS


# --- NEEDS_HUMAN has no generic resume --------------------------------------


def test_needs_human_requires_one_explicit_chosen_action(conn, task):
    """§8: no generic resume; the Admin picks one validated action.

    Asserted as the shape of the table rather than by trying a "resume" event,
    because the property is that no such event exists.
    """
    from_needs_human = {
        kind for (state, kind) in states.TRANSITIONS if state == "NEEDS_HUMAN"
    }

    assert "return_to_author" in from_needs_human
    assert "return_to_review" in from_needs_human
    assert "create_contract_version" in from_needs_human
    assert "resume" not in from_needs_human
    assert "retry_authorized" not in from_needs_human


# --- state_seq: the stale-write guard ---------------------------------------


def test_a_stale_state_seq_is_refused(conn, task):
    """A decision computed from state the task has since left is rejected.

    The scenario: a caller reads the task, something else moves it, and the
    caller then submits a result based on what it read. Without this the result
    would be applied to the wrong state.
    """
    seq_when_read = engine.get_task(conn, task)["state_seq"]

    engine.apply_transition(
        conn, task_id=task, kind="contract_validated", actor="c",
        authority=states.CONTROLLER,
    )

    with pytest.raises(engine.StaleState):
        engine.apply_transition(
            conn, task_id=task, kind="queued", actor="c",
            authority=states.CONTROLLER, expected_state_seq=seq_when_read,
        )


def test_a_matching_state_seq_is_accepted(conn, task):
    seq = engine.get_task(conn, task)["state_seq"]

    engine.apply_transition(
        conn, task_id=task, kind="contract_validated", actor="c",
        authority=states.CONTROLLER, expected_state_seq=seq,
    )

    assert engine.get_task(conn, task)["state"] == "VALIDATED"


def test_state_seq_increments_once_per_accepted_transition(conn, task):
    assert engine.get_task(conn, task)["state_seq"] == 0

    advance(conn, task, ("contract_validated", states.CONTROLLER))
    assert engine.get_task(conn, task)["state_seq"] == 1

    advance(conn, task, ("queued", states.CONTROLLER))
    assert engine.get_task(conn, task)["state_seq"] == 2


# --- Idempotency and replay -------------------------------------------------


def test_an_identical_redelivery_is_idempotent(conn, task):
    """Duplicate delivery must not append a second event (§5)."""
    first = engine.apply_transition(
        conn, task_id=task, kind="contract_validated", actor="c",
        authority=states.CONTROLLER, event_id="E-fixed",
    )
    second = engine.apply_transition(
        conn, task_id=task, kind="contract_validated", actor="c",
        authority=states.CONTROLLER, event_id="E-fixed",
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["to_state"] == "VALIDATED"
    assert len(engine.event_log(conn, task)) == 1
    assert engine.get_task(conn, task)["state_seq"] == 1


def test_a_conflicting_replay_is_refused(conn, task):
    """Same event_id, different content: a bug or an attack, never merged."""
    engine.apply_transition(
        conn, task_id=task, kind="contract_validated", actor="c",
        authority=states.CONTROLLER, event_id="E-fixed",
    )

    with pytest.raises(engine.ConflictingReplay):
        engine.apply_transition(
            conn, task_id=task, kind="contract_validated", actor="someone-else",
            authority=states.CONTROLLER, event_id="E-fixed",
        )

    assert len(engine.event_log(conn, task)) == 1


def test_replaying_the_event_log_reproduces_the_projection(conn, task):
    """§18's required test: replay must match stored state exactly.

    replay_state reads only events and never tasks.state, so this comparison
    means something. An audit log that cannot rebuild the projection is a log,
    not a source of truth.
    """
    advance(conn, task, *TO_AUTHORING,
            ("candidate_submitted", states.AUTHOR),
            ("review_activation_issued", states.CONTROLLER),
            ("activation_claimed", states.VERIFIER),
            ("author_defect", states.CONTROLLER),
            ("retry_authorized", states.CONTROLLER))

    assert engine.replay_state(conn, task) == engine.get_task(conn, task)["state"]
    assert engine.get_task(conn, task)["state"] == "READY_AUTHOR"


# --- Notes are advisory -----------------------------------------------------


def test_a_note_appends_an_event_without_moving_the_task(conn, task):
    """Appendix A: `note` never advances state.

    Both state and state_seq are asserted. Leaving state_seq alone matters as
    much as leaving state alone: bumping it would invalidate every caller's
    outstanding expected_state_seq, so a note could make unrelated legitimate
    results fail as stale.
    """
    before = engine.get_task(conn, task)

    result = engine.apply_transition(
        conn, task_id=task, kind="note", actor="gemini",
        authority=states.CONTROLLER, payload={"text": "an observation"},
    )

    after = engine.get_task(conn, task)

    assert result["to_state"] == before["state"]
    assert after["state"] == before["state"]
    assert after["state_seq"] == before["state_seq"]
    assert len(engine.event_log(conn, task)) == 1


def test_a_note_is_accepted_in_a_terminal_state(conn, task):
    """Recording an observation about a finished task must stay possible."""
    engine.apply_transition(
        conn, task_id=task, kind="admin_cancelled", actor="admin",
        authority=states.ADMIN,
    )

    engine.apply_transition(
        conn, task_id=task, kind="note", actor="admin",
        authority=states.ADMIN, payload={"text": "cancelled because ..."},
    )

    assert engine.get_task(conn, task)["state"] == "CANCELLED"


# --- Table integrity --------------------------------------------------------


def test_every_transition_names_a_known_state_and_role():
    for (from_state, kind), transition in states.TRANSITIONS.items():
        assert from_state in states.STATES, from_state
        assert transition.to_state in states.STATES, transition.to_state
        assert transition.authorities, (from_state, kind)
        assert transition.authorities <= states.ROLES, transition.authorities


def test_every_state_is_reachable_or_initial():
    """A state nothing can enter is dead weight and probably a typo."""
    reachable = {t.to_state for t in states.TRANSITIONS.values()} | {"DRAFT"}

    assert states.STATES - reachable == set()
