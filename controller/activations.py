"""Activation lifecycle: issue, claim, heartbeat, result.

An activation is one worker's permission to make one bounded attempt. It is the
only thing that starts work, which is what makes §1's invariant 2 -- *workers
pull one controller-issued activation at a time, they are never activated by
chat* -- true at the controller as well as at the worker.

Clocks never cross the host boundary
------------------------------------

The controller stores absolute times on its own clock and **never sends one to
a harness**. Every response carries remaining *durations*, which the harness
converts against its own `time.monotonic()`. That is not fastidiousness: Tower
and OFFICEPC are different machines, their wall clocks drift, and a lease
compared across that boundary expires early or late by however far apart they
have wandered. Durations have no such failure mode.

`build_timing()` is the only place a response's timing is constructed, so there
is one place to check that no absolute time escapes.

The lease renews. The hard deadline does not
--------------------------------------------

A heartbeat proves a worker is alive and extends its lease. It cannot extend
`hard_deadline_at` (§13, invariant 10), because otherwise a worker stuck in a
loop would heartbeat forever and never be reclaimed -- liveness is not
progress, and only the deadline distinguishes them.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Optional

from . import engine
from .db import transaction
from .states import AUTHOR, CONTROLLER, VERIFIER

# Activation statuses. ISSUED and CLAIMED are live; the rest are final.
ISSUED = "ISSUED"
CLAIMED = "CLAIMED"
DONE = "DONE"
EXPIRED = "EXPIRED"
ABANDONED = "ABANDONED"

LIVE_STATUSES = (ISSUED, CLAIMED)

# Which role each stage's activation carries, and which transition its claim
# causes. Keeping these together stops a review activation from being issued
# with an author's authority.
STAGE_ROLES = {
    "author": (AUTHOR, "author_activation_issued"),
    "review": (VERIFIER, "review_activation_issued"),
}


class ActivationError(Exception):
    pass


class ActivationNotFound(ActivationError):
    pass


class NotTheAssignedWorker(ActivationError):
    """The caller authenticated as somebody other than the assigned agent."""


class ActivationNotLive(ActivationError):
    """Already finished, expired, or abandoned."""


class LeaseExpired(ActivationError):
    pass


class DeadlineExceeded(ActivationError):
    """Past the hard deadline. Final regardless of what the harness believed."""


class HostAtCapacity(ActivationError):
    pass


class EvidenceNotDurable(ActivationError):
    """A result cited evidence whose blobs are not on the control plane (§9)."""


class ConflictingResult(ActivationError):
    """A different result was already submitted for this activation."""


def _canonical_hash(payload: dict) -> str:
    """Stable hash of a request, for idempotency.

    `sort_keys` matters: two deliveries of the same request must hash the same
    regardless of how the client happened to order the JSON, or a retry looks
    like a conflict.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_timing(row: sqlite3.Row, now: float) -> dict:
    """The timing block sent to a harness: durations only, never timestamps.

    Clamped at zero rather than allowed to go negative, so a harness cannot be
    handed a "negative time remaining" it has to interpret. Expiry is the
    controller's decision, not something the harness infers from a sign.
    """
    return {
        "lease_seconds_remaining": max(0.0, row["lease_expires_at"] - now),
        "hard_deadline_seconds_remaining": max(0.0, row["hard_deadline_at"] - now),
        "server_seq": row["heartbeat_seq"],
    }


def get_activation(conn: sqlite3.Connection, activation_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
    ).fetchone()

    if row is None:
        raise ActivationNotFound(activation_id)

    return dict(row)


def set_host_capacity(
    conn: sqlite3.Connection, host: str, max_concurrent: int
) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO host_capacity (host, max_concurrent) VALUES (?, ?) "
            "ON CONFLICT(host) DO UPDATE SET max_concurrent = excluded.max_concurrent",
            (host, max_concurrent),
        )


def _capacity_blocked(conn: sqlite3.Connection, host: str) -> Optional[str]:
    """Why `host` cannot take another activation, or None.

    §6. An unknown host is refused rather than treated as unlimited: capacity
    that has never been measured is not the same as capacity that is infinite,
    and defaulting to infinite is how contention-induced timeouts start.
    """
    row = conn.execute(
        "SELECT * FROM host_capacity WHERE host = ?", (host,)
    ).fetchone()

    if row is None:
        return f"host {host!r} has no declared capacity"

    if row["exclusive_holder_id"] is not None:
        return (
            f"host {host!r} is held exclusively by "
            f"{row['exclusive_holder_kind']} {row['exclusive_holder_id']}"
        )

    if row["drain_requested"]:
        return f"host {host!r} is draining"

    active = conn.execute(
        "SELECT COUNT(*) AS n FROM activations WHERE host = ? AND status IN (?, ?)",
        (host, ISSUED, CLAIMED),
    ).fetchone()["n"]

    if active >= row["max_concurrent"]:
        return (
            f"host {host!r} at capacity ({active}/{row['max_concurrent']})"
        )

    return None


def issue(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent: str,
    host: str,
    stage: str,
    lease_seconds: float,
    hard_deadline_seconds: float,
    chargeable: bool = True,
    activation_id: Optional[str] = None,
    expected_branch: Optional[str] = None,
    expected_parent: Optional[str] = None,
    now: Optional[float] = None,
) -> dict:
    """Issue one activation and move the task to its assigned state.

    The capacity check happens inside the same transaction as the insert.
    Checking first and inserting after would let two issues both observe a free
    slot and both take it.
    """
    if stage not in STAGE_ROLES:
        raise ActivationError(f"unknown stage {stage!r}")

    role, transition_kind = STAGE_ROLES[stage]
    now = time.time() if now is None else now
    activation_id = activation_id or uuid.uuid4().hex

    with transaction(conn):
        blocked = _capacity_blocked(conn, host)
        if blocked is not None:
            raise HostAtCapacity(blocked)

        task = engine.get_task(conn, task_id)

        attempt = conn.execute(
            "SELECT COUNT(*) AS n FROM activations WHERE task_id = ? AND stage = ?",
            (task_id, stage),
        ).fetchone()["n"] + 1

        conn.execute(
            "INSERT INTO activations (activation_id, task_id, task_version, "
            "agent, host, role, stage, attempt_no, chargeable_attempt, "
            "expected_branch, expected_parent, issued_at, lease_expires_at, "
            "hard_deadline_at, heartbeat_seq, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                activation_id, task_id, task["current_version"], agent, host,
                role, stage, attempt, 1 if chargeable else 0,
                expected_branch, expected_parent, now,
                now + lease_seconds, now + hard_deadline_seconds, 0, ISSUED,
            ),
        )

    # Outside the transaction above because apply_transition opens its own, and
    # nesting is refused. The activation exists but the task has not moved yet;
    # if this fails the activation is orphaned in ISSUED and reclaimed by the
    # lease sweep, which is the safe direction -- the alternative is a task
    # marked ASSIGNED with no activation to claim.
    engine.apply_transition(
        conn, task_id=task_id, kind=transition_kind, actor="controller",
        authority=CONTROLLER, activation_id=activation_id, now=now,
        payload={"agent": agent, "host": host, "stage": stage},
    )

    return {"activation_id": activation_id, "role": role, "attempt_no": attempt}


def claim(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    now: Optional[float] = None,
) -> dict:
    """Claim an issued activation. Returns durations, never timestamps."""
    now = time.time() if now is None else now

    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
        ).fetchone()

        if row is None:
            raise ActivationNotFound(activation_id)

        _require_caller_and_liveness(row, agent, now)

        if row["status"] != ISSUED:
            raise ActivationNotLive(
                f"activation is {row['status']}, not {ISSUED}"
            )

        conn.execute(
            "UPDATE activations SET status = ?, claimed_at = ?, "
            "heartbeat_at = ?, heartbeat_seq = heartbeat_seq + 1 "
            "WHERE activation_id = ?",
            (CLAIMED, now, now, activation_id),
        )

    engine.apply_transition(
        conn, task_id=row["task_id"], kind="activation_claimed", actor=agent,
        authority=row["role"], activation_id=activation_id, now=now,
    )

    fresh = conn.execute(
        "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
    ).fetchone()

    return {
        "activation_id": activation_id,
        "task_id": row["task_id"],
        "task_version": row["task_version"],
        "role": row["role"],
        "stage": row["stage"],
        **build_timing(fresh, now),
    }


def heartbeat(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    lease_seconds: float,
    now: Optional[float] = None,
) -> dict:
    """Renew the lease. Never extends the hard deadline.

    Invariant 10: a heartbeat proves liveness, not progress. A worker spinning
    in a loop would otherwise keep itself alive indefinitely.
    """
    now = time.time() if now is None else now

    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
        ).fetchone()

        if row is None:
            raise ActivationNotFound(activation_id)

        _require_caller_and_liveness(row, agent, now)

        if row["status"] != CLAIMED:
            raise ActivationNotLive(f"activation is {row['status']}, not {CLAIMED}")

        conn.execute(
            "UPDATE activations SET heartbeat_at = ?, lease_expires_at = ?, "
            "heartbeat_seq = heartbeat_seq + 1 WHERE activation_id = ?",
            (now, now + lease_seconds, activation_id),
        )

    fresh = conn.execute(
        "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
    ).fetchone()

    return {"activation_id": activation_id, **build_timing(fresh, now)}


def _require_caller_and_liveness(row: sqlite3.Row, agent: str, now: float) -> None:
    """The §5 authorization checks that apply to every activation operation.

    Identity first, then the deadline. Order matters for what a caller can
    learn: someone who is not the assigned worker gets the same answer whether
    or not the activation has expired.
    """
    if row["agent"] != agent:
        raise NotTheAssignedWorker(
            f"activation is assigned to another agent, not {agent!r}"
        )

    if row["status"] not in LIVE_STATUSES:
        raise ActivationNotLive(f"activation is {row['status']}")

    # The hard deadline is checked before the lease because it is the
    # non-renewable one: past it, nothing the worker did to stay alive matters.
    if now >= row["hard_deadline_at"]:
        raise DeadlineExceeded("hard deadline has passed")

    if now >= row["lease_expires_at"]:
        raise LeaseExpired("lease has expired")


def _evidence_is_durable(conn: sqlite3.Connection, evidence_ids: list) -> Optional[str]:
    """Why cited evidence is not acceptable yet, or None (§9).

    Evidence is not evidence until its content is on the control plane. A
    COMPLETE whose proof is a path on a workstation is not proof -- those temp
    directories are reaped.
    """
    for evidence_id in evidence_ids:
        row = conn.execute(
            "SELECT evidence_id FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()

        if row is None:
            return f"evidence {evidence_id!r} does not exist"

        blobs = conn.execute(
            "SELECT r.blob_hash FROM evidence_blob_refs r "
            "JOIN evidence_blobs b ON b.blob_hash = r.blob_hash "
            "WHERE r.evidence_id = ?",
            (evidence_id,),
        ).fetchall()

        if not blobs:
            return f"evidence {evidence_id!r} has no durable blobs"

    return None


def _result_preconditions(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    request_hash: str,
    evidence_ids: list,
    now: float,
) -> tuple:
    """The §5 checks every terminal submission shares, in §5's order.

    Returns ``(row, cached_response)``. A non-None cached response means this
    exact submission was already accepted and must be returned as-is rather
    than applied again.

    The order is the specification, which is why it lives in one place instead
    of being repeated by each caller: checking idempotency after validating
    liveness would reject a duplicate delivery of a result that was accepted
    just before the lease lapsed -- the worker did everything right and would
    be told it failed.
    """
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM activations WHERE activation_id = ?", (activation_id,)
        ).fetchone()

        if row is None:
            raise ActivationNotFound(activation_id)

        # 1. The caller must be the assigned worker. Checked before anything
        #    else so no other check can leak information to a stranger.
        if row["agent"] != agent:
            raise NotTheAssignedWorker(
                f"activation is assigned to another agent, not {agent!r}"
            )

        # 2-3. Idempotency, before liveness. A duplicate delivery of an
        #      already-accepted result must return that result, even if the
        #      lease has since lapsed: the work was accepted, and telling the
        #      worker otherwise would make it retry something already done.
        if row["result_request_hash"] is not None:
            if row["result_request_hash"] == request_hash:
                return row, {**json.loads(row["result_response"]), "replayed": True}

            raise ConflictingResult(
                "a different result was already submitted for this activation"
            )

        # 4. Liveness: live status, unexpired lease, unexpired hard deadline.
        #    The controller is authoritative here regardless of what the
        #    harness believed its remaining time to be.
        if row["status"] not in LIVE_STATUSES:
            raise ActivationNotLive(f"activation is {row['status']}")

        if now >= row["hard_deadline_at"]:
            raise DeadlineExceeded("hard deadline has passed")

        if now >= row["lease_expires_at"]:
            raise LeaseExpired("lease has expired")

        # 5. The activation must still be for the task version it was issued
        #    against. A refreshed contract version invalidates work done under
        #    the old one.
        task = engine.get_task(conn, row["task_id"])

        if task["current_version"] != row["task_version"]:
            raise ActivationNotLive(
                f"activation was issued for version {row['task_version']}, "
                f"task is now at {task['current_version']}"
            )

        # 6. Evidence must be durable before a result citing it is accepted.
        problem = _evidence_is_durable(conn, evidence_ids)
        if problem is not None:
            raise EvidenceNotDurable(problem)

    return row, None


def _finalize(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    outcome: dict,
    request_hash: str,
    response: dict,
) -> None:
    """Mark the activation DONE and record what answered it.

    Recording the request hash is what makes the next identical delivery
    return the cached response. The host slot is released by the status change
    alone: `_capacity_blocked` counts only ISSUED and CLAIMED.
    """
    with transaction(conn):
        conn.execute(
            "UPDATE activations SET status = ?, result_event_id = ?, "
            "result_request_hash = ?, result_response = ? WHERE activation_id = ?",
            (DONE, outcome["event_id"], request_hash, json.dumps(response), activation_id),
        )


def submit_result(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    kind: str,
    payload: Optional[dict] = None,
    expected_state_seq: Optional[int] = None,
    evidence_ids: Optional[list] = None,
    now: Optional[float] = None,
) -> dict:
    """Submit one terminal result for an activation, under the worker's role.

    The event is applied with the authority the activation was issued with, so
    a worker can only cause transitions its own role is permitted to cause. A
    judgment that needs controller authority goes through
    `submit_review_judgment` instead.
    """
    now = time.time() if now is None else now
    payload = payload or {}
    evidence_ids = evidence_ids or []

    request = {
        "activation_id": activation_id,
        "kind": kind,
        "payload": payload,
        "evidence_ids": sorted(evidence_ids),
    }
    request_hash = _canonical_hash(request)

    row, cached = _result_preconditions(
        conn,
        activation_id=activation_id,
        agent=agent,
        request_hash=request_hash,
        evidence_ids=evidence_ids,
        now=now,
    )

    if cached is not None:
        return cached

    # 7-8. The transition itself, in its own transaction. A rejection here --
    #      undefined transition, wrong authority, stale state_seq -- leaves the
    #      activation live and unresulted, so the worker can be told why and
    #      the attempt is not silently consumed.
    outcome = engine.apply_transition(
        conn,
        task_id=row["task_id"],
        kind=kind,
        actor=agent,
        authority=row["role"],
        expected_state_seq=expected_state_seq,
        activation_id=activation_id,
        payload={**payload, "evidence_ids": sorted(evidence_ids)},
        now=now,
    )

    response = {
        "activation_id": activation_id,
        "event_id": outcome["event_id"],
        "task_id": row["task_id"],
        "from_state": outcome["from_state"],
        "to_state": outcome["to_state"],
        "state_seq": outcome["state_seq"],
    }

    _finalize(
        conn,
        activation_id=activation_id,
        outcome=outcome,
        request_hash=request_hash,
        response=response,
    )

    return {**response, "replayed": False}


# The judgments a review activation may return, and the event each produces.
#
# `satisfied` is the one that needs controller authority: section 8 makes
# `review_requirements_satisfied` a controller transition precisely so a
# verifier cannot advance a task by declaring a gate met. The other two are
# already available to a verifier, and are routed through here as well so a
# reviewer has one endpoint and one idempotency story rather than two.
REVIEW_JUDGMENTS = {
    "satisfied": "review_requirements_satisfied",
    "changes_requested": "author_defect",
    "decision_required": "decision_required",
}


class NotAReviewActivation(ActivationError):
    """A review judgment was submitted against an activation of another stage."""


def submit_review_judgment(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    judgment: str,
    payload: Optional[dict] = None,
    expected_state_seq: Optional[int] = None,
    now: Optional[float] = None,
) -> dict:
    """Record the verifier's judgment, applied with controller authority.

    Why this exists rather than a plain `submit_result`: section 8 gives
    `review_requirements_satisfied` to the controller alone, and a review
    activation carries the *verifier* role, so a reviewer submitting that event
    through `submit_result` is refused as unauthorized. The gate is meant to be
    the controller's to close, not the reviewer's to declare closed.

    What closes it here is the reviewer's authenticated judgment, taken on the
    strength of three things checked before the event is applied: the caller is
    the agent the activation was issued to, the activation is live and
    unexpired, and its stage is `review`. The controller remains the authority
    that moves the task, and it moves it only because the agent holding that
    specific live review activation said so.

    **The deterministic completion predicates are not implemented and are not
    consulted here.** For the MVP the reviewer's judgment is the whole gate. A
    later version that computes the diff, verification and evidence predicates
    should refuse `satisfied` when they do not hold; until that exists, nothing
    in this controller checks them and no caller should assume otherwise.
    """
    if judgment not in REVIEW_JUDGMENTS:
        raise ActivationError(
            f"unknown review judgment {judgment!r}; "
            f"expected one of {sorted(REVIEW_JUDGMENTS)}"
        )

    now = time.time() if now is None else now
    payload = payload or {}
    kind = REVIEW_JUDGMENTS[judgment]

    # The judgment is part of the idempotency key, so re-delivering the same
    # judgment replays, while a reviewer that changes its mind afterwards is
    # refused as a conflicting result rather than silently overwriting.
    request = {
        "activation_id": activation_id,
        "kind": "review_judgment",
        "judgment": judgment,
        "payload": payload,
        "evidence_ids": [],
    }
    request_hash = _canonical_hash(request)

    row, cached = _result_preconditions(
        conn,
        activation_id=activation_id,
        agent=agent,
        request_hash=request_hash,
        evidence_ids=[],
        now=now,
    )

    if cached is not None:
        return cached

    # Checked after the caller and liveness checks, so an agent that does not
    # hold this activation learns nothing about what stage it is.
    if row["stage"] != "review":
        raise NotAReviewActivation(
            f"activation is a {row['stage']!r} activation, not a review"
        )

    outcome = engine.apply_transition(
        conn,
        task_id=row["task_id"],
        kind=kind,
        actor=agent,
        authority=CONTROLLER,
        expected_state_seq=expected_state_seq,
        activation_id=activation_id,
        payload={**payload, "judgment": judgment, "judged_by": agent},
        now=now,
    )

    response = {
        "activation_id": activation_id,
        "event_id": outcome["event_id"],
        "task_id": row["task_id"],
        "judgment": judgment,
        "from_state": outcome["from_state"],
        "to_state": outcome["to_state"],
        "state_seq": outcome["state_seq"],
    }

    _finalize(
        conn,
        activation_id=activation_id,
        outcome=outcome,
        request_hash=request_hash,
        response=response,
    )

    return {**response, "replayed": False}


def sweep_expired(
    conn: sqlite3.Connection, *, now: Optional[float] = None
) -> list:
    """Reclaim activations past their lease or hard deadline, and recover the task.

    The recovery transition is emitted here rather than left to a caller. An
    earlier version only marked the activation EXPIRED and returned it, which
    left the task in AUTHOR_ASSIGNED with nothing live to claim -- a stuck task
    that no later sweep would touch, because sweeps look at activations and this
    one had already been dealt with. Reclaiming without recovering is not
    reclaiming.

    A lapsed lease and a passed deadline are reported separately because they
    mean different things: the first is a worker that stopped talking, the
    second a worker that talked the whole time and never finished.

    Which transition applies depends on the stage the task is actually in, per
    §8. From an *_ASSIGNED state nothing had started, so the plain recovery
    event applies. From AUTHORING or REVIEWING work was underway, and §8 offers
    `deadline_checkpointed` or `deadline_without_checkpoint` -- Phase 1 has no
    checkpoint capture, so it is always the latter, and that becomes a real
    choice in Phase 2.
    """
    now = time.time() if now is None else now
    reclaimed = []

    with transaction(conn):
        rows = conn.execute(
            "SELECT * FROM activations WHERE status IN (?, ?)", (ISSUED, CLAIMED)
        ).fetchall()

        for row in rows:
            if now >= row["hard_deadline_at"]:
                reason = "hard_deadline_reached"
            elif now >= row["lease_expires_at"]:
                reason = "lease_expired"
            else:
                continue

            conn.execute(
                "UPDATE activations SET status = ? WHERE activation_id = ?",
                (EXPIRED, row["activation_id"]),
            )
            reclaimed.append(
                {
                    "activation_id": row["activation_id"],
                    "task_id": row["task_id"],
                    "stage": row["stage"],
                    "reason": reason,
                }
            )

    # Transitions are applied after the sweep's transaction closes, because
    # apply_transition opens its own and nesting is refused.
    for item in reclaimed:
        task = engine.get_task(conn, item["task_id"])
        kind = _recovery_kind(item["reason"], task["state"])
        item["recovery"] = kind

        if kind is None:
            # The task already moved on -- a result landed in the same instant
            # the sweep ran, say. Nothing to recover; the activation is still
            # correctly marked EXPIRED.
            continue

        engine.apply_transition(
            conn, task_id=item["task_id"], kind=kind, actor="controller",
            authority=CONTROLLER, activation_id=item["activation_id"], now=now,
            payload={"reason": item["reason"]},
        )

    return reclaimed


# States where work had not started yet, so the plain recovery event applies.
_ASSIGNED_STATES = {"AUTHOR_ASSIGNED", "REVIEW_ASSIGNED"}
# States where an attempt was underway.
_RUNNING_STATES = {"AUTHORING", "REVIEWING"}


def _recovery_kind(reason: str, task_state: str) -> Optional[str]:
    """The §8 transition for this reclamation, or None if nothing applies."""
    if reason == "lease_expired" and task_state in _ASSIGNED_STATES | _RUNNING_STATES:
        return "lease_expired"

    if reason == "hard_deadline_reached":
        if task_state in _ASSIGNED_STATES:
            return "hard_deadline_reached"
        if task_state in _RUNNING_STATES:
            # Phase 1 captures no checkpoints, so the without-checkpoint branch
            # is the only honest one. Claiming a checkpoint exists would let a
            # task resume from state that was never captured.
            return "deadline_without_checkpoint"

    return None
