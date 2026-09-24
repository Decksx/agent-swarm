"""The external-review state chain (#74 slice 1, #91).

The table maps (state, event) and cannot tell an external task from one the
swarm authored, so "an external change is never integrated" has to be a
property of where the external states can lead. These tests hold it: the
first walks the whole transition graph, so a future edge that opens a path is
caught even if nobody thought to name it.
"""

from __future__ import annotations

import pytest

from controller import db, engine, states
from controller.states import (
    ADMIN, AUTHOR, CONTROLLER, EXTERNAL_STATES, INTEGRATION_STATES, OPERATOR,
    VERIFIER,
)

# Where an external task may end up besides its own states: closed by a
# person, and nowhere else.
EXITS = frozenset({"CANCELLED", "SUPERSEDED"})


def reachable_from(start: str) -> set:
    """Every state reachable from `start` by any event, under any authority."""
    seen, frontier = {start}, [start]

    while frontier:
        here = frontier.pop()
        for (frm, _), transition in states.TRANSITIONS.items():
            if frm == here and transition.to_state not in seen:
                seen.add(transition.to_state)
                frontier.append(transition.to_state)

    return seen


# --- The boundary -------------------------------------------------------------


def test_the_boundary_names_real_states():
    """A misspelt name would make the walk below pass vacuously."""
    assert INTEGRATION_STATES <= states.STATES
    assert len(EXTERNAL_STATES) == 7
    assert EXTERNAL_STATES <= states.STATES


@pytest.mark.parametrize("start", sorted(EXTERNAL_STATES))
def test_no_external_state_can_reach_integration(start):
    reached = reachable_from(start)

    assert not reached & INTEGRATION_STATES, (
        f"{start} can reach {sorted(reached & INTEGRATION_STATES)}"
    )


@pytest.mark.parametrize("start", sorted(EXTERNAL_STATES))
def test_an_external_task_never_leaves_its_own_chain(start):
    """Stronger than the test above: a leak into the swarm's own author or
    review states would reach integration one hop later."""
    leaked = reachable_from(start) - EXTERNAL_STATES - EXITS

    assert not leaked, f"{start} can reach {sorted(leaked)}"


def test_the_only_way_in_is_the_operators_request():
    entries = {
        (frm, kind): t for (frm, kind), t in states.TRANSITIONS.items()
        if t.to_state in EXTERNAL_STATES and frm not in EXTERNAL_STATES
    }

    assert set(entries) == {("DRAFT", "external_review_requested")}
    assert entries[("DRAFT", "external_review_requested")].authorities == {ADMIN}


def test_the_verdict_is_terminal():
    assert states.is_terminal("EXTERNAL_REVIEWED")
    assert not [k for k in states.TRANSITIONS if k[0] == "EXTERNAL_REVIEWED"]


# --- Authority ------------------------------------------------------------------


@pytest.mark.parametrize("authority", [AUTHOR, VERIFIER, OPERATOR])
def test_a_verifier_does_not_write_its_own_verdict(authority):
    with pytest.raises(states.NotAuthorized):
        states.resolve("EXTERNAL_REVIEWING", "external_review_judged", authority)


@pytest.mark.parametrize("authority", [AUTHOR, VERIFIER, OPERATOR, CONTROLLER])
def test_only_an_admin_requests_an_external_review(authority):
    with pytest.raises(states.NotAuthorized):
        states.resolve("DRAFT", "external_review_requested", authority)


@pytest.mark.parametrize("authority", [AUTHOR, VERIFIER, OPERATOR])
def test_only_the_controller_registers_the_pinned_candidate(authority):
    with pytest.raises(states.NotAuthorized):
        states.resolve("EXTERNAL_PENDING", "external_candidate_registered", authority)


@pytest.mark.parametrize("start", sorted(EXTERNAL_STATES))
def test_no_external_state_accepts_an_authors_candidate(start):
    """`candidate_submitted` means an activated author produced it. From an
    external state it would be exactly the false statement #74 exists to
    avoid."""
    with pytest.raises(states.UndefinedTransition):
        states.resolve(start, "candidate_submitted", AUTHOR)


# --- Blocked states return to the right place --------------------------------------


@pytest.mark.parametrize("blocked, returns_to", [
    ("EXTERNAL_INGEST_BLOCKED", "EXTERNAL_PENDING"),
    ("EXTERNAL_REVIEW_BLOCKED", "READY_EXTERNAL_REVIEW"),
])
def test_repair_returns_each_blocked_stage_to_its_own_start(blocked, returns_to):
    transition = states.resolve(blocked, "environment_repaired", CONTROLLER)

    assert transition.to_state == returns_to


@pytest.mark.parametrize("state, kind", [
    ("EXTERNAL_REVIEW_ASSIGNED", "lease_expired"),
    ("EXTERNAL_REVIEW_ASSIGNED", "hard_deadline_reached"),
    ("EXTERNAL_REVIEWING", "lease_expired"),
    ("EXTERNAL_REVIEWING", "deadline_without_checkpoint"),
])
def test_a_lapsed_review_goes_back_to_ready(state, kind):
    assert states.resolve(state, kind, CONTROLLER).to_state == "READY_EXTERNAL_REVIEW"


# --- Through the engine, and the ledger --------------------------------------------


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "controller.db"))
    db.initialize(connection)
    return connection


def external_task(conn, task_id="T-EXT-1"):
    engine.create_task(
        conn, task_id=task_id, title="review PR #79", objective="o",
        contract_yaml="allowed_paths:\n  - README.md\n", base_sha="0" * 40,
        created_by="admin",
    )
    return task_id


def apply(conn, task_id, kind, authority, payload=None):
    return engine.apply_transition(
        conn, task_id=task_id, kind=kind, actor="test", authority=authority,
        payload=payload or {},
    )


@pytest.mark.parametrize("judgment", ["satisfied", "changes_requested", "decision_required"])
def test_every_judgment_lands_in_the_verdict_state_and_writes_no_approval(conn, judgment):
    task = external_task(conn)

    apply(conn, task, "external_review_requested", ADMIN, {"pr_number": 79})
    apply(conn, task, "external_candidate_registered", CONTROLLER,
          {"head_sha": "a" * 40, "merge_base": "b" * 40})
    apply(conn, task, "review_activation_issued", CONTROLLER)
    apply(conn, task, "activation_claimed", VERIFIER)
    apply(conn, task, "external_review_judged", CONTROLLER,
          {"judgment": judgment, "rationale": "r", "head_sha": "a" * 40})

    record = engine.get_task(conn, task)
    assert record["state"] == "EXTERNAL_REVIEWED"
    assert record["approved_candidate_sha"] is None, (
        "an external verdict must never read as an integration approval"
    )
    assert engine.replay_state(conn, task) == "EXTERNAL_REVIEWED"


def test_a_note_can_be_added_to_a_verdict(conn):
    """The ledger's advisory event still works on the terminal state -- the
    way to correct the record without rewriting it."""
    task = external_task(conn)
    apply(conn, task, "external_review_requested", ADMIN)
    apply(conn, task, "external_candidate_registered", CONTROLLER)
    apply(conn, task, "review_activation_issued", CONTROLLER)
    apply(conn, task, "activation_claimed", VERIFIER)
    apply(conn, task, "external_review_judged", CONTROLLER, {"judgment": "satisfied"})

    apply(conn, task, "note", ADMIN, {"text": "merged by hand at the reviewed SHA"})

    assert engine.get_task(conn, task)["state"] == "EXTERNAL_REVIEWED"


# --- Said in the room -----------------------------------------------------------


def test_every_event_kind_is_either_narrated_or_deliberately_not():
    """An unlabelled event is silently dropped by the narrator. That is how
    `integration_blocked` (#78) was recorded and never said, and it is the
    silence #77 exists to end. A new event must now choose."""
    import narrator

    undecided = states.EVENT_KINDS - set(narrator.NARRATED) - set(narrator.NOT_NARRATED)

    assert not undecided, f"neither narrated nor excluded: {sorted(undecided)}"


def test_an_external_verdict_line_names_the_pr_the_sha_and_the_judgment():
    import narrator

    line = narrator.render({
        "kind": "external_review_judged", "task_id": "T-EXT-1", "task_version": 1,
        "actor": "controller", "seq": 900, "from_state": "EXTERNAL_REVIEWING",
        "to_state": "EXTERNAL_REVIEWED",
        "payload_json": {"judgment": "changes_requested", "pr_number": 79,
                         "head_sha": "806b3d20c580b8700e2dda5b11f5a51950e2f38c"},
    })

    assert "EXTERNAL VERDICT" in line
    assert "PR #79" in line and "head 806b3d2" in line
    assert "changes_requested" in line and "(seq 900)" in line
