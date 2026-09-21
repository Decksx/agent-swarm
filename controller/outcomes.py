"""What a worker reports when a stage ends, and what the controller does with it.

Split out of `activations.py`, which had reached the per-file view budget --
50,000 characters, the window an author is shown. A module past it cannot be
handed to a worker as a task, so the swarm could not be asked to change its own
activation handling. Splitting was chosen over raising the cap because the cap
is paid by every prompt.

The seam is the one already in the file. `activations.py` issues work and
tracks the lifecycle of an activation: capacity, evidence at issue time, claim,
heartbeat, expiry sweep. This module is the other end -- the terminal
submission -- and the discipline it enforces is different in kind:

**Establish that the caller holds this specific live activation, then let the
controller emit the event.** A worker never causes its own gate to close.
`_result_preconditions` is §5's order in one place, and the order is the
specification: idempotency is checked *before* liveness, so a duplicate
delivery of a result accepted moments before the lease lapsed returns that
result rather than being told it failed.

The exception hierarchy stays in `activations.py` on purpose. It is the
activation vocabulary rather than this module's, `LeaseExpired` is an
`ActivationError`, and `api._STATUS_FOR` walks that hierarchy to choose a
status code -- splitting it across two modules would make one mapping read
from two places.

Nothing here is imported by `activations.py`. The dependency runs one way, so
the seam cannot quietly become a cycle.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Optional

from . import engine
from .activations import (
    ActivationError,
    ActivationNotFound,
    ActivationNotLive,
    CLAIMED,
    ConflictingResult,
    DeadlineExceeded,
    DONE,
    EvidenceNotDurable,
    ISSUED,
    LIVE_STATUSES,
    LeaseExpired,
    NotAReviewActivation,
    NotTheAssignedWorker,
)
from .db import transaction
from .states import CONTROLLER


def _canonical_hash(payload: dict) -> str:
    """Stable hash of a request, for idempotency.

    `sort_keys` matters: two deliveries of the same request must hash the same
    regardless of how the client happened to order the JSON, or a retry looks
    like a conflict.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

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
    uncharge: bool = False,
) -> None:
    """Mark the activation DONE and record what answered it.

    Recording the request hash is what makes the next identical delivery
    return the cached response. The host slot is released by the status change
    alone: `_capacity_blocked` counts only ISSUED and CLAIMED.

    `uncharge` clears `chargeable_attempt` in the same statement (#21).
    Chargeability is decided at issue, before anyone knows how the activation
    ends, and the outcome that should decide it arrives here -- so it is
    corrected rather than predicted. In this UPDATE rather than a second one,
    because a row marked DONE while still charged, even briefly, is a budget
    the controller would enforce against. The spent count is derived from the
    column, so clearing it corrects every reader at once.
    """
    with transaction(conn):
        conn.execute(
            f"UPDATE activations SET status = ?, result_event_id = ?, "
            f"result_request_hash = ?, result_response = ?"
            f"{', chargeable_attempt = 0' if uncharge else ''} "
            f"WHERE activation_id = ?",
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
    "satisfied": ("review_requirements_satisfied", CONTROLLER),
    "changes_requested": ("author_defect", CONTROLLER),
    "decision_required": ("decision_required", CONTROLLER),
    # "I could not review this" is not the same as "this is wrong", and
    # collapsing them would record a verdict about the work when the reviewer
    # never got far enough to form one. REVIEW_BLOCKED is the state an operator
    # repairs and reissues from; CHANGES_REQUESTED sends the author back to
    # rewrite something that may be perfectly fine.
    "blocked": ("environment_defect", CONTROLLER),
}

# What an author may report when its run is over, and the event each produces.
#
# Only `candidate` is an author-authority transition. A run that failed or hit
# a broken environment moves the task through a controller transition, for the
# same reason the review gate does: a worker must not be able to put its own
# task into CHANGES_REQUESTED or AUTHOR_BLOCKED by asserting it. Without this
# map a worker had exactly one reportable outcome -- success -- and no way to
# say a task had failed at all.
# Each outcome maps to (event, authority). `None` means "apply it under the
# activation's own role", which is the honest answer whenever the role is
# already permitted to cause that event: a worker reporting that it produced a
# candidate is reporting its own work, and section 8 gives the author that
# transition. The controller only stands in where the event is a *verdict* the
# worker must not be able to reach -- author_defect puts a task into
# CHANGES_REQUESTED, and environment_defect into AUTHOR_BLOCKED.
AUTHOR_OUTCOMES = {
    "candidate": ("candidate_submitted", None),
    "failed": ("author_defect", CONTROLLER),
    "blocked": ("environment_defect", CONTROLLER),
}

# What an integration activation may report.
#
# `integrated` is controller authority and not the holder's, for the same
# reason `review_requirements_satisfied` is: a worker must not be able to
# declare its own task COMPLETE. The controller applies it on the strength of
# the worker holding this specific live activation, and the worker only gets
# to say what it observed.
#
# `refused` is every pre-merge check failing -- the approval, the target, the
# PR, the evidence. Nothing was merged, so the task goes back to
# CHANGES_REQUESTED with the reason rather than to a failure state that
# suggests the candidate was tried and found wanting.
INTEGRATION_OUTCOMES = {
    "integrated": ("integration_completed", CONTROLLER),
    "refused": ("integration_rejected", CONTROLLER),
    "blocked": ("integration_rejected", CONTROLLER),
}

def submit_integration_outcome(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    outcome: str,
    payload: Optional[dict] = None,
    expected_state_seq: Optional[int] = None,
    now: Optional[float] = None,
) -> dict:
    """Report what an integration attempt observed.

    The payload carries the measured figures -- candidate, target before,
    merge commit, target after -- and the controller records them. It does not
    carry a verdict the controller then trusts: `integrated` is only accepted
    because this worker holds this activation, and everything it claims is
    checked by the worker against the remote before it claims it.
    """
    return _submit_stage_outcome(
        conn,
        activation_id=activation_id,
        agent=agent,
        stage="integrate",
        outcome=outcome,
        outcome_map=INTEGRATION_OUTCOMES,
        payload=payload,
        expected_state_seq=expected_state_seq,
        now=now,
    )

def submit_author_outcome(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    outcome: str,
    payload: Optional[dict] = None,
    expected_state_seq: Optional[int] = None,
    now: Optional[float] = None,
) -> dict:
    """Record how an author activation ended, with controller authority.

    The author counterpart of `submit_review_judgment`, and it exists for the
    same reason: the outcomes a worker most needs to report -- this failed,
    this environment is broken -- are controller transitions in section 8, so
    a worker cannot emit them itself and previously could not report them at
    all. The controller applies them on the strength of the caller holding
    that specific live author activation.

    `candidate` is applied the same way for one story rather than two, even
    though the author role would be permitted to emit it directly.
    """
    return _submit_stage_outcome(
        conn,
        activation_id=activation_id,
        agent=agent,
        stage="author",
        outcome=outcome,
        outcome_map=AUTHOR_OUTCOMES,
        payload=payload,
        expected_state_seq=expected_state_seq,
        now=now,
    )

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
    return _submit_stage_outcome(
        conn,
        activation_id=activation_id,
        agent=agent,
        stage="review",
        outcome=judgment,
        outcome_map=REVIEW_JUDGMENTS,
        payload=payload,
        expected_state_seq=expected_state_seq,
        now=now,
        outcome_key="judgment",
    )

def _submit_stage_outcome(
    conn: sqlite3.Connection,
    *,
    activation_id: str,
    agent: str,
    stage: str,
    outcome: str,
    outcome_map: dict,
    payload: Optional[dict] = None,
    expected_state_seq: Optional[int] = None,
    now: Optional[float] = None,
    outcome_key: str = "outcome",
) -> dict:
    """Apply a stage's terminal outcome with controller authority.

    Shared by the author and review stages because the discipline is the same
    and a second hand-written copy of it would drift: establish that the caller
    holds this specific live activation, then let the controller -- not the
    caller -- emit the event. The stage is part of the authorization rather
    than a label, so a review judgment cannot be submitted against an author
    activation or the reverse.
    """
    if outcome not in outcome_map:
        raise ActivationError(
            f"unknown {stage} {outcome_key} {outcome!r}; "
            f"expected one of {sorted(outcome_map)}"
        )

    now = time.time() if now is None else now
    payload = payload or {}
    kind, authority = outcome_map[outcome]

    # The outcome is part of the idempotency key, so redelivering the same one
    # replays, while a worker that reports something different after the fact
    # is refused as a conflicting result rather than silently overwriting a
    # decision the task has already moved on from.
    request = {
        "activation_id": activation_id,
        "kind": f"{stage}_outcome",
        outcome_key: outcome,
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
    if row["stage"] != stage:
        raise NotAReviewActivation(
            f"activation is a {row['stage']!r} activation, not a {stage}"
        )

    outcome_record = {outcome_key: outcome, f"{outcome_key}_by": agent}

    result = engine.apply_transition(
        conn,
        task_id=row["task_id"],
        kind=kind,
        actor=agent,
        # None means the activation's own role is already permitted to cause
        # this, so borrowing controller authority would overstate what
        # happened in the event log.
        authority=authority if authority is not None else row["role"],
        expected_state_seq=expected_state_seq,
        activation_id=activation_id,
        payload={**payload, **outcome_record},
        now=now,
    )

    response = {
        "activation_id": activation_id,
        "event_id": result["event_id"],
        "task_id": row["task_id"],
        outcome_key: outcome,
        "from_state": result["from_state"],
        "to_state": result["to_state"],
        "state_seq": result["state_seq"],
    }

    _finalize(
        conn,
        activation_id=activation_id,
        outcome=result,
        request_hash=request_hash,
        response=response,
        # An environment defect is not an attempt (#21). The taxonomy already
        # draws the line: `author_defect` is a model that answered unusably,
        # `environment_defect` a run that never got far enough to judge -- a
        # 429 before any text, a missing credential, a worktree that would not
        # open. Keyed on the transition, not the reported string, because the
        # transition is what the state machine acted on.
        uncharge=(kind == "environment_defect"),
    )

    return {**response, "replayed": False}
