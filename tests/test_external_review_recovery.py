"""External-review activation expiry must recover the task, not just its slot.

These tests use controller primitives in a temporary database. They do not
enable the admin ingress, route external reviews, or contact the live hub.
"""

from __future__ import annotations

import json

import pytest

from controller import activations, engine, outcomes, states
from controller.db import open_controller_db

T0 = 1_000_000.0
LEASE = 10.0
DEADLINE = 30.0
TASK = "T-EXTERNAL-RECOVERY"
PARENT = "a" * 40
CANDIDATE = "b" * 40


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 1)
    yield connection
    connection.close()


def transition(conn, kind, authority=states.CONTROLLER, **kwargs):
    return engine.apply_transition(
        conn, task_id=TASK, kind=kind, actor="test", authority=authority,
        now=T0, **kwargs,
    )


def issue_review(conn, *, now=T0, lease_seconds=LEASE):
    return activations.issue(
        conn, task_id=TASK, agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=lease_seconds, hard_deadline_seconds=DEADLINE,
        expected_branch=f"refs/swarm/external/{TASK}",
        expected_parent=PARENT, expected_candidate=CANDIDATE,
        repo_location="C:/git/agent-swarm", now=now,
    )["activation_id"]


def start_review(conn, *, claimed, lease_seconds=LEASE):
    engine.create_task(
        conn, task_id=TASK, title="Review external PR", objective="operator objective",
        contract_yaml="allowed_paths:\n  - README.md\n", base_sha=PARENT,
        created_by="admin", now=T0,
    )
    transition(conn, "external_review_requested", states.ADMIN)
    # Through the ingest stage's own transitions (#92); these tests are about
    # the review stage that follows it.
    transition(conn, "ingest_activation_issued")
    transition(conn, "activation_claimed", states.OPERATOR)
    transition(conn, "external_candidate_registered", payload={
        "pr_number": 96, "head_sha": CANDIDATE, "merge_base": PARENT,
    })
    aid = issue_review(conn, lease_seconds=lease_seconds)
    if claimed:
        activations.claim(conn, activation_id=aid, agent="gemini", now=T0 + 1)
    return aid


def events(conn):
    return [dict(row) for row in conn.execute(
        "SELECT * FROM events WHERE task_id = ? ORDER BY seq", (TASK,),
    )]


@pytest.mark.parametrize("claimed", [False, True], ids=["assigned", "running"])
@pytest.mark.parametrize("timeout", ["lease", "deadline"])
def test_expiry_recovers_external_review_and_allows_a_fresh_attempt(conn, claimed, timeout):
    # For a deadline, keep the lease alive past it: heartbeat is not permission
    # to run beyond the hard deadline. Check exact boundaries, not only >.
    lease = DEADLINE * 2 if timeout == "deadline" else LEASE
    aid = start_review(conn, claimed=claimed, lease_seconds=lease)
    when = T0 + (DEADLINE if timeout == "deadline" else LEASE)
    if claimed and timeout == "deadline":
        activations.heartbeat(
            conn, activation_id=aid, agent="gemini", lease_seconds=lease, now=T0 + 2,
        )
    before = engine.get_task(conn, TASK)
    assert before["state"] == ("EXTERNAL_REVIEWING" if claimed else "EXTERNAL_REVIEW_ASSIGNED")
    assert activations.sweep_expired(conn, now=when - 0.01) == []

    swept = activations.sweep_expired(conn, now=when)

    reason = "hard_deadline_reached" if timeout == "deadline" else "lease_expired"
    recovery = "deadline_without_checkpoint" if claimed and timeout == "deadline" else reason
    assert swept == [{
        "activation_id": aid, "task_id": TASK, "stage": "review",
        "reason": reason, "recovery": recovery,
    }]
    task = engine.get_task(conn, TASK)
    assert task["state"] == "READY_EXTERNAL_REVIEW"
    assert task["approved_candidate_sha"] is None
    assert task["state_seq"] == before["state_seq"] + 1
    assert engine.replay_state(conn, TASK) == task["state"]
    assert activations.get_activation(conn, aid)["status"] == activations.EXPIRED
    event = events(conn)[-1]
    assert event["kind"] == recovery
    assert event["activation_id"] == aid
    assert event["from_state"] == before["state"]
    assert event["to_state"] == "READY_EXTERNAL_REVIEW"
    assert json.loads(event["payload_json"]) == {"reason": reason}
    count = len(events(conn))
    assert activations.sweep_expired(conn, now=when + 1) == []
    assert len(events(conn)) == count

    # Expiry must release capacity, retain the pinned range, and retire the
    # old permission even once a new activation has been issued and claimed.
    replacement = issue_review(conn, now=when + 1)
    fresh = activations.claim(
        conn, activation_id=replacement, agent="gemini", now=when + 2,
    )
    assert replacement != aid
    assert activations.get_activation(conn, replacement)["attempt_no"] == 2
    assert fresh["expected_parent"] == PARENT
    assert fresh["expected_candidate"] == CANDIDATE
    unchanged = events(conn)
    with pytest.raises(activations.ActivationNotLive):
        activations.claim(conn, activation_id=aid, agent="gemini", now=when + 2)
    with pytest.raises(activations.ActivationNotLive):
        activations.heartbeat(
            conn, activation_id=aid, agent="gemini", lease_seconds=LEASE, now=when + 2,
        )
    with pytest.raises(activations.ActivationNotLive):
        outcomes.submit_review_judgment(
            conn, activation_id=aid, agent="gemini", judgment="satisfied", now=when + 2,
        )
    assert events(conn) == unchanged
    assert engine.get_task(conn, TASK)["state"] == "EXTERNAL_REVIEWING"
    assert engine.get_task(conn, TASK)["approved_candidate_sha"] is None


@pytest.mark.parametrize("kind,authority,destination", [
    ("admin_cancelled", states.ADMIN, "CANCELLED"),
    ("superseded", states.ADMIN, "SUPERSEDED"),
    ("environment_defect", states.CONTROLLER, "EXTERNAL_REVIEW_BLOCKED"),
    ("external_review_judged", states.CONTROLLER, "EXTERNAL_REVIEWED"),
])
def test_expiry_does_not_reopen_an_external_task_that_moved_on(conn, kind, authority, destination):
    aid = start_review(conn, claimed=True)
    transition(conn, kind, authority)
    before = events(conn)

    swept = activations.sweep_expired(conn, now=T0 + LEASE)

    assert swept[0]["recovery"] is None
    assert activations.get_activation(conn, aid)["status"] == activations.EXPIRED
    assert engine.get_task(conn, TASK)["state"] == destination
    assert engine.replay_state(conn, TASK) == destination
    assert events(conn) == before
    assert engine.get_task(conn, TASK)["approved_candidate_sha"] is None
