"""Activation lifecycle: issue, claim, heartbeat, result, expiry.

Several of §18's required deterministic tests live here: duplicate identical
result, conflicting result replay, stale task version, wrong authenticated
worker, heartbeat alive past the hard deadline, clock skew, late result after
lease expiry, and a result citing evidence with missing blobs.

The clock-skew tests are structural rather than simulated. There is no way to
skew a harness clock into the controller, because no absolute time is ever sent
to one — so the test asserts that property directly instead of pretending to
move a clock that has no influence.
"""

from __future__ import annotations

import time

import pytest

from controller import activations, engine, states
from controller.db import open_controller_db

T0 = 1_000_000.0
LEASE = 300.0
DEADLINE = 5400.0


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 1)
    yield connection
    connection.close()


@pytest.fixture
def ready_task(conn):
    engine.create_task(
        conn, task_id="T-1", title="pilot", objective="o",
        contract_yaml="schema_version: 7\n", base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-1", kind=kind, actor="c", authority=states.CONTROLLER
        )
    return "T-1"


def issue(conn, task="T-1", agent="claudecode", host="OFFICEPC", stage="author",
          now=T0, **kw):
    return activations.issue(
        conn, task_id=task, agent=agent, host=host, stage=stage,
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=now, **kw
    )


# --- Clocks never cross the host boundary -----------------------------------


def _looks_like_a_timestamp(value) -> bool:
    """Any number large enough to be a unix epoch is a leaked absolute time."""
    return isinstance(value, (int, float)) and value > 1_000_000_000


def test_no_response_carries_an_absolute_time(conn, ready_task):
    """§5: responses carry durations; the harness converts against monotonic.

    Asserted structurally, because there is no way to simulate skew against a
    controller that never sends a timestamp. Tower and OFFICEPC wall clocks
    drift; a lease compared across that boundary expires early or late by
    however far apart they have wandered.
    """
    activation = issue(conn, ready_task)

    claimed = activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )
    beat = activations.heartbeat(
        conn, activation_id=activation["activation_id"], agent="claudecode",
        lease_seconds=LEASE, now=T0 + 5,
    )

    for response in (claimed, beat):
        leaked = {k: v for k, v in response.items() if _looks_like_a_timestamp(v)}
        assert not leaked, f"absolute time leaked to the harness: {leaked}"


def test_the_controller_is_authoritative_regardless_of_harness_belief(conn, ready_task):
    """A result past the deadline is refused however much time the worker thought it had.

    This is the clock-skew case that matters: the harness's own arithmetic is
    irrelevant because the controller re-checks against its own clock.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    with pytest.raises(activations.DeadlineExceeded):
        activations.submit_result(
            conn, activation_id=activation["activation_id"], agent="claudecode",
            kind="candidate_submitted", now=T0 + DEADLINE + 1,
        )


def test_server_seq_increases_so_a_stale_response_can_be_discarded(conn, ready_task):
    """§5: the harness discards a delayed response with a lower sequence."""
    activation = issue(conn, ready_task)
    seqs = [
        activations.claim(
            conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
        )["server_seq"]
    ]

    for offset in (10, 20, 30):
        seqs.append(
            activations.heartbeat(
                conn, activation_id=activation["activation_id"], agent="claudecode",
                lease_seconds=LEASE, now=T0 + offset,
            )["server_seq"]
        )

    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


# --- The lease renews; the hard deadline does not ---------------------------


def test_a_heartbeat_renews_the_lease_but_never_the_deadline(conn, ready_task):
    """Invariant 10. Liveness is not progress.

    A worker stuck in a loop heartbeats perfectly well. Only the
    non-renewable deadline distinguishes it from one making progress.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    beat = activations.heartbeat(
        conn, activation_id=activation["activation_id"], agent="claudecode",
        lease_seconds=LEASE, now=T0 + 200,
    )

    assert beat["lease_seconds_remaining"] == pytest.approx(LEASE)
    assert beat["hard_deadline_seconds_remaining"] == pytest.approx(DEADLINE - 200)


def test_a_heartbeat_past_the_hard_deadline_is_refused(conn, ready_task):
    """§18's "heartbeat alive past hard deadline"."""
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    with pytest.raises(activations.DeadlineExceeded):
        activations.heartbeat(
            conn, activation_id=activation["activation_id"], agent="claudecode",
            lease_seconds=LEASE, now=T0 + DEADLINE + 1,
        )


# --- Identity ---------------------------------------------------------------


@pytest.mark.parametrize("operation", ["claim", "heartbeat", "result"])
def test_only_the_assigned_worker_may_act(conn, ready_task, operation):
    """§5: authenticated agent == activation.agent, for every operation."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]

    if operation != "claim":
        activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    with pytest.raises(activations.NotTheAssignedWorker):
        if operation == "claim":
            activations.claim(conn, activation_id=aid, agent="chatgpt", now=T0 + 1)
        elif operation == "heartbeat":
            activations.heartbeat(
                conn, activation_id=aid, agent="chatgpt", lease_seconds=LEASE, now=T0 + 2
            )
        else:
            activations.submit_result(
                conn, activation_id=aid, agent="chatgpt",
                kind="candidate_submitted", now=T0 + 2,
            )


def test_identity_is_checked_before_expiry(conn, ready_task):
    """A stranger gets the same answer whether or not the activation expired.

    Reporting "expired" to an unauthorized caller would confirm the activation
    exists and reveal its timing.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    with pytest.raises(activations.NotTheAssignedWorker):
        activations.submit_result(
            conn, activation_id=activation["activation_id"], agent="chatgpt",
            kind="candidate_submitted", now=T0 + DEADLINE + 999,
        )


# --- Host capacity ----------------------------------------------------------


def test_capacity_prevents_a_second_activation(conn, ready_task):
    """§6: contention-induced timeouts are non-chargeable, so without a cap
    the system retries directly into the contention that caused them."""
    issue(conn, ready_task)

    with pytest.raises(activations.HostAtCapacity):
        issue(conn, ready_task, agent="chatgpt", now=T0 + 1)


def test_an_undeclared_host_is_refused_rather_than_treated_as_unlimited(
    conn, ready_task
):
    """Capacity never measured is not capacity known to be infinite."""
    with pytest.raises(activations.HostAtCapacity, match="no declared capacity"):
        issue(conn, ready_task, host="SOME-OTHER-BOX")


def test_a_draining_host_takes_no_new_activations(conn, ready_task):
    # Canonicalised, because the table is keyed on the canonical spelling and
    # this statement reaches around the API that would have done it.
    conn.execute(
        "UPDATE host_capacity SET drain_requested = 1 WHERE host = ?",
        (activations.canonical_host("OFFICEPC"),),
    )

    with pytest.raises(activations.HostAtCapacity, match="draining"):
        issue(conn, ready_task)


def test_an_exclusive_holder_excludes_everything_else(conn, ready_task):
    conn.execute(
        "UPDATE host_capacity SET exclusive_holder_kind = ?, exclusive_holder_id = ? "
        "WHERE host = ?",
        ("integration", "I-1", activations.canonical_host("OFFICEPC")),
    )

    with pytest.raises(activations.HostAtCapacity, match="exclusively"):
        issue(conn, ready_task)


def test_finishing_an_activation_releases_the_slot(conn, ready_task):
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )
    activations.submit_result(
        conn, activation_id=activation["activation_id"], agent="claudecode",
        kind="candidate_submitted", now=T0 + 2,
    )

    # READY_REVIEW now, so a review activation is the legal next one. It has
    # to carry its evidence; that refusal is covered in test_review_issuance.
    issue(conn, ready_task, agent="claude", stage="review", now=T0 + 3,
          expected_branch="task/T-1", expected_candidate="a" * 40,
          repo_location="/srv/checkouts/T-1")


# --- Results ----------------------------------------------------------------


def test_an_identical_result_redelivery_returns_the_stored_outcome(conn, ready_task):
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    first = activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", payload={"sha": "a" * 40}, now=T0 + 2,
    )
    second = activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", payload={"sha": "a" * 40}, now=T0 + 3,
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["event_id"] == first["event_id"]
    assert len(engine.event_log(conn, ready_task)) == len(
        [e for e in engine.event_log(conn, ready_task)]
    )


def test_a_duplicate_is_honoured_even_after_the_lease_lapses(conn, ready_task):
    """Idempotency is checked before liveness, deliberately.

    The work was accepted while the lease was live. Telling the worker its
    redelivery failed would make it retry something already done.
    """
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)
    activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", payload={"sha": "a" * 40}, now=T0 + 2,
    )

    replay = activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", payload={"sha": "a" * 40}, now=T0 + DEADLINE + 500,
    )

    assert replay["replayed"] is True


def test_a_conflicting_result_is_refused(conn, ready_task):
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)
    activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", payload={"sha": "a" * 40}, now=T0 + 2,
    )

    with pytest.raises(activations.ConflictingResult):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", payload={"sha": "b" * 40}, now=T0 + 3,
        )


def test_payload_key_order_does_not_make_a_retry_look_like_a_conflict(conn, ready_task):
    """Canonicalized with sorted keys, so JSON ordering is not identity."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    activations.submit_result(
        conn, activation_id=aid, agent="claudecode", kind="candidate_submitted",
        payload={"a": 1, "b": 2}, now=T0 + 2,
    )
    replay = activations.submit_result(
        conn, activation_id=aid, agent="claudecode", kind="candidate_submitted",
        payload={"b": 2, "a": 1}, now=T0 + 3,
    )

    assert replay["replayed"] is True


def test_a_late_result_after_lease_expiry_is_refused(conn, ready_task):
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    with pytest.raises(activations.LeaseExpired):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", now=T0 + LEASE + 1,
        )


def test_a_result_for_a_superseded_task_version_is_refused(conn, ready_task):
    """A refreshed contract invalidates work done under the old one."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    conn.execute("UPDATE tasks SET current_version = 2 WHERE task_id = ?", (ready_task,))

    with pytest.raises(activations.ActivationNotLive, match="version"):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", now=T0 + 2,
        )


def test_a_result_citing_missing_evidence_is_refused(conn, ready_task):
    """§9: evidence is not acceptable until its content is on the control plane.

    A COMPLETE whose proof is a path on a workstation is not proof — those
    temp directories are reaped.
    """
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    with pytest.raises(activations.EvidenceNotDurable, match="does not exist"):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", evidence_ids=["EV-nonexistent"], now=T0 + 2,
        )


def test_a_result_citing_evidence_without_blobs_is_refused(conn, ready_task):
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    conn.execute(
        "INSERT INTO evidence (evidence_id, task_id, task_version, activation_id, "
        "authoritative, target_sha, gate_id, command_hash, contract_hash, shell, "
        "worktree_clean, environment_hash, outcome, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("EV-1", ready_task, 1, aid, 1, "a" * 40, "unit", "ch", "cc", "pwsh",
         1, "eh", "PASS", T0),
    )

    with pytest.raises(activations.EvidenceNotDurable, match="no durable blobs"):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", evidence_ids=["EV-1"], now=T0 + 2,
        )


def test_a_rejected_result_leaves_the_activation_claimable_again(conn, ready_task):
    """A refused result must not silently consume the attempt."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)

    with pytest.raises(activations.EvidenceNotDurable):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", evidence_ids=["nope"], now=T0 + 2,
        )

    row = activations.get_activation(conn, aid)
    assert row["status"] == activations.CLAIMED
    assert row["result_request_hash"] is None

    accepted = activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", now=T0 + 3,
    )
    assert accepted["to_state"] == "READY_REVIEW"


# --- Expiry sweep -----------------------------------------------------------


def test_the_sweep_distinguishes_a_lapsed_lease_from_a_passed_deadline(
    conn, ready_task
):
    """They mean different things and get different recovery.

    A lapsed lease is a worker that stopped talking. A passed deadline is a
    worker that talked the whole time and never finished.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    assert activations.sweep_expired(conn, now=T0 + 10) == []

    lapsed = activations.sweep_expired(conn, now=T0 + LEASE + 1)
    assert len(lapsed) == 1 and lapsed[0]["reason"] == "lease_expired"


def test_a_passed_deadline_is_reported_as_such(conn, ready_task):
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    swept = activations.sweep_expired(conn, now=T0 + DEADLINE + 1)

    assert len(swept) == 1 and swept[0]["reason"] == "hard_deadline_reached"


def test_a_swept_activation_cannot_submit_a_result(conn, ready_task):
    """§13: a late process's state changes are rejected."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)
    activations.sweep_expired(conn, now=T0 + LEASE + 1)

    with pytest.raises(activations.ActivationNotLive):
        activations.submit_result(
            conn, activation_id=aid, agent="claudecode",
            kind="candidate_submitted", now=T0 + LEASE + 2,
        )


def test_sweeping_frees_the_host_slot(conn, ready_task):
    issue(conn, ready_task)
    activations.sweep_expired(conn, now=T0 + DEADLINE + 1)

    issue(conn, ready_task, now=T0 + DEADLINE + 2)


def test_the_sweep_recovers_the_task_not_just_the_activation(conn, ready_task):
    """Reclaiming without recovering leaves a permanently stuck task.

    An earlier version only marked the activation EXPIRED. The task stayed in
    AUTHOR_ASSIGNED with nothing live to claim, and no later sweep would touch
    it, because sweeps look at activations and that one had been dealt with.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    swept = activations.sweep_expired(conn, now=T0 + LEASE + 1)

    assert swept[0]["recovery"] == "lease_expired"
    assert engine.get_task(conn, ready_task)["state"] == "READY_AUTHOR"


def test_a_deadline_during_work_uses_the_without_checkpoint_branch(conn, ready_task):
    """§8 offers checkpointed and without-checkpoint from AUTHORING.

    Phase 1 captures no checkpoints, so the honest branch is the latter.
    Claiming a checkpoint exists would let a later activation resume from state
    that was never captured.
    """
    activation = issue(conn, ready_task)
    activations.claim(
        conn, activation_id=activation["activation_id"], agent="claudecode", now=T0 + 1
    )

    swept = activations.sweep_expired(conn, now=T0 + DEADLINE + 1)

    assert swept[0]["recovery"] == "deadline_without_checkpoint"
    assert engine.get_task(conn, ready_task)["state"] == "READY_AUTHOR"


def test_an_unclaimed_activation_recovers_from_the_assigned_state(conn, ready_task):
    """Nothing had started, so the plain recovery event applies."""
    issue(conn, ready_task)

    swept = activations.sweep_expired(conn, now=T0 + DEADLINE + 1)

    assert swept[0]["recovery"] == "hard_deadline_reached"
    assert engine.get_task(conn, ready_task)["state"] == "READY_AUTHOR"


def test_the_sweep_does_nothing_to_a_task_that_already_moved_on(conn, ready_task):
    """A result landing in the same instant the sweep runs is not a conflict."""
    activation = issue(conn, ready_task)
    aid = activation["activation_id"]
    activations.claim(conn, activation_id=aid, agent="claudecode", now=T0 + 1)
    activations.submit_result(
        conn, activation_id=aid, agent="claudecode",
        kind="candidate_submitted", now=T0 + 2,
    )

    # DONE, so the sweep should not see it at all.
    assert activations.sweep_expired(conn, now=T0 + DEADLINE + 1) == []
    assert engine.get_task(conn, ready_task)["state"] == "READY_REVIEW"
