"""Reporting a merge the controller never performed (#26).

INTEGRATION_UNCERTAIN was reachable one way: an integration lease that lapsed
mid-merge, leaving the controller unable to say from its own records whether
the merge landed. T-INGRESS-05 reached the same question down a different
road. The integrator refused the candidate for want of test evidence, the
author budget ran out, the task escalated -- and minutes earlier an operator
had merged the pull request by hand. The merge was on the target and no event
in the ledger could say so, so the task was closed SUPERSEDED, which is the
least wrong close available and still loses that the work succeeded.

This module is the entrance to reconciliation for that case, and it is
deliberately not a second way to complete a task. It moves a task to
INTEGRATION_UNCERTAIN and stops; the reconcile route decides what actually
landed, so "this merge is on the target" is established in one place no matter
how the task arrived at the question.

What can and cannot be checked
------------------------------

Nothing here has a working copy, so the merge itself is **not verified** and
saying otherwise would be the whole problem with this feature. What the
controller can check is its own ledger, and it checks three things there: that
the task is somewhere a report makes sense, that the task carries an approval
at all, and that the candidate a reporter names is the one that approval was
issued against.

The second is the load-bearing one. Without it, reporting a merge is a way to
walk work nobody reviewed into the state that exists to trust reports, and
from there into COMPLETE.

`tasks.approved_candidate_sha` cannot answer the second or third question.
`integration_rejected` is in `engine.APPROVAL_CLEARING`, so the column is NULL
on precisely the tasks this module serves. The approval is read from the event
log, where it happened, and the candidate from the review activation the
controller issued -- never from the reporter. See `engine._approved_candidate`
for why that distinction is the security property and not a preference.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional

from . import activations, engine, states
from .db import transaction


class ReportRefused(Exception):
    """A report the ledger will not accept. Base class, never raised."""


class MalformedReport(ReportRefused):
    """The report does not say what landed, where, or who put it there."""


class NotReportable(ReportRefused):
    """The task is not somewhere an out-of-band merge can be reported."""


class NothingApproved(ReportRefused):
    """No approval in this task's log. A merge of unreviewed work is not a
    reconciliation, and recording it as one would launder it."""


class CandidateMismatch(ReportRefused):
    """The candidate reported is not the one the approval was issued for."""


class StaleReport(ReportRefused):
    """The reporter is describing a task that has moved since they read it."""


class WrongReconciliation(ReportRefused):
    """The reconciliation offered is the right answer for the other entrance.

    INTEGRATION_UNCERTAIN has two doors and they are not symmetrical, so the
    way out is not either. See `refuse_mismatched_reconciliation`.
    """


# Where reporting an out-of-band merge makes sense: a task that stopped short
# of integrating.
#
# Not INTEGRATING or INTEGRATION_UNCERTAIN -- those have the integrator's own
# outcome route and the reconcile route, both of which carry evidence this one
# cannot. Not a terminal state either: a SUPERSEDED task is closed, and
# reopening one is a different decision than reconciling it, taken by a person
# who has to say so.
REPORTABLE_FROM = frozenset({"NEEDS_HUMAN", "CHANGES_REQUESTED"})


def entered_by_report(conn: sqlite3.Connection, task_id: str) -> bool:
    """Did this task reach INTEGRATION_UNCERTAIN by a report, or by expiry?

    Answered from the event log, which is the only place the answer lives: the
    state table is keyed by (state, event) and cannot see how a state was
    entered, and `tasks.state` records where the task is rather than how it got
    there. Reading the most recent transition *into* the state rather than the
    last event overall, because a task can arrive, be reconciled, and arrive
    again, and the entrance that matters is the current one.
    """
    row = conn.execute(
        "SELECT kind FROM events WHERE task_id = ? AND to_state = ? "
        "AND from_state != to_state ORDER BY seq DESC LIMIT 1",
        (task_id, "INTEGRATION_UNCERTAIN"),
    ).fetchone()

    return row is not None and row["kind"] == "out_of_band_merge_reported"


# The way out of INTEGRATION_UNCERTAIN depends on which door the task came in
# by, and the two are not interchangeable.
#
# Expiry: the task was approved, was being integrated, and still carries
# `approved_candidate_sha`. `integration_reconciled_absent` means nothing
# landed and it is safe to try again, so READY_INTEGRATION is right.
#
# Report: the task was refused or escalated first, and `integration_rejected`
# cleared the approval on the way past. Absent means the report was false, and
# sending the task to READY_INTEGRATION would resurrect a candidate the
# integrator refused on the strength of a claim that just turned out not to be
# true -- and strand it there, because `progression.advance` will not issue an
# integrate stage for a task with no `approved_candidate_sha`.
#
# Named rather than inferred: the route refuses the wrong one and says which to
# use, instead of quietly substituting it. An operator answering "the merge is
# not there" should see which of the two answers they are giving.
_FOR_REPORTED = "out_of_band_report_unfounded"
_FOR_EXPIRED = "integration_reconciled_absent"


def refuse_mismatched_reconciliation(
    conn: sqlite3.Connection, *, task_id: str, kind: str
) -> None:
    """Refuse an absence answer aimed at the wrong entrance. Otherwise silent.

    Only the two absence events are checked. `integration_reconciled_landed`
    means the same thing down either door -- the merge is on the target and the
    task is COMPLETE -- and `reconciliation_failed` means nobody could tell,
    which is equally true either way.
    """
    if kind not in (_FOR_REPORTED, _FOR_EXPIRED):
        return

    by_report = entered_by_report(conn, task_id)

    if by_report and kind == _FOR_EXPIRED:
        raise WrongReconciliation(
            f"{task_id} reached INTEGRATION_UNCERTAIN by an out-of-band merge "
            f"report, so a merge that is not there means the report was "
            f"unfounded, not that the task is ready to integrate: use "
            f"{_FOR_REPORTED!r}"
        )

    if not by_report and kind == _FOR_REPORTED:
        raise WrongReconciliation(
            f"{task_id} reached INTEGRATION_UNCERTAIN by an expired "
            f"integration, not by a report; there is no report to call "
            f"unfounded: use {_FOR_EXPIRED!r}"
        )


def report_out_of_band_merge(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    actor: str,
    merge_sha: str,
    target_ref: str,
    merged_by: str,
    reason: str,
    expected_state_seq: int,
    expected_version: int,
    candidate_sha: Optional[str] = None,
    pull_request: Optional[int] = None,
    merged_at: Optional[str] = None,
    now: Optional[float] = None,
) -> dict:
    """Record that somebody merged this task's approved candidate by hand.

    Applied with admin authority, and deliberately not the operator's: this is
    a person saying what they did outside the system. A worker able to report
    its own out-of-band merge could walk unreviewed work into a state that
    exists to trust reports.

    The event kind says `reported`, the payload carries `verified: false` and
    the authenticated `reported_by`, and the task stops in
    INTEGRATION_UNCERTAIN rather than advancing. Three ways of recording the
    same thing: this is a claim, not an observation.

    The task version advances in the same transaction, for the reason
    `/operator-response` advances it: a report is a statement that this task
    resolved outside the system, and every attempt authorized before that was
    authorized under conditions that no longer hold. Leaving the version where
    it was would let a retry authorized minutes earlier stay valid against a
    task somebody has just merged by hand. A `reason` string records why a
    person acted; only the version advance invalidates what was in flight.

    Every check runs inside the transaction that appends the event, so a
    refusal writes nothing -- a route that rejects a request and records half
    of it is worse than one that accepts it.
    """
    merge_sha = (merge_sha or "").strip().lower()
    target_ref = (target_ref or "").strip()
    merged_by = (merged_by or "").strip()
    reason = (reason or "").strip()

    missing = [name for name, value in (
        ("target_ref", target_ref),
        ("merged_by", merged_by),
        ("reason", reason),
    ) if not value]

    if missing:
        raise MalformedReport(
            "a report must say what landed, where, and who put it there; "
            f"missing: {', '.join(missing)}"
        )

    if not activations.SHA_RE.match(merge_sha):
        raise MalformedReport(
            f"merge_sha {merge_sha!r} must be a full 40-character sha; a "
            "short sha names a different commit on a different day"
        )

    now = time.time() if now is None else now

    with transaction(conn):
        task = engine.get_task(conn, task_id)

        if task["current_version"] != expected_version:
            raise StaleReport(
                f"stale report: {task_id} was version {expected_version} when "
                f"it was read and is version {task['current_version']} now"
            )

        if task["state"] not in REPORTABLE_FROM:
            raise NotReportable(
                f"{task_id} is {task['state']}; an out-of-band merge can only "
                "be reported against a task that stopped short of "
                f"integrating ({', '.join(sorted(REPORTABLE_FROM))})"
            )

        approval = engine.approved_candidate_for_task(conn, task_id)

        if approval is None:
            raise NothingApproved(
                f"nothing on {task_id} was approved; a merge of unreviewed "
                "work is not a reconciliation"
            )

        approved = approval["candidate_sha"]
        claimed = (candidate_sha or "").strip().lower()

        # An approval whose activation named no candidate approved nothing
        # identifiable, and a report cannot be anchored to it. That is a gap in
        # issuance -- `_review_evidence` refuses such an activation now -- and
        # not a reason to accept whatever the reporter typed.
        if not approved:
            raise NothingApproved(
                f"the approval on {task_id} (seq {approval['seq']}) names no "
                "candidate; there is nothing to check a merge against"
            )

        if claimed and claimed != approved:
            raise CandidateMismatch(
                f"the candidate reported ({claimed[:12]}) is not the one this "
                f"task approved ({approved[:12]})"
            )

        # The same contract at a new version. Nothing about the work changed;
        # what changed is that every attempt pinned to the old version was
        # authorized before anyone said this task had resolved elsewhere.
        current = conn.execute(
            "SELECT * FROM task_versions WHERE task_id = ? AND version = ?",
            (task_id, task["current_version"]),
        ).fetchone()

        if current is None:
            raise ReportRefused(
                f"{task_id} has no contract for its current version "
                f"({task['current_version']})"
            )

        resulting_version = task["current_version"] + 1

        conn.execute(
            "INSERT INTO task_versions (task_id, version, contract_yaml, "
            "contract_hash, protocol_schema_version, base_sha, proof_mode, "
            "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id, resulting_version, current["contract_yaml"],
                current["contract_hash"], current["protocol_schema_version"],
                current["base_sha"], current["proof_mode"], now, actor,
            ),
        )
        conn.execute(
            "UPDATE tasks SET current_version = ? WHERE task_id = ?",
            (resulting_version, task_id),
        )

        moved = engine.apply_transition_within(
            conn,
            task_id=task_id,
            kind="out_of_band_merge_reported",
            actor=actor,
            authority=states.ADMIN,
            now=now,
            expected_state_seq=expected_state_seq,
            # The approval this report hangs on, so the log answers "what was
            # it allowed to land?" without a reader reconstructing it.
            source_event_id=approval["event_id"],
            payload={
                "merge_sha": merge_sha,
                "candidate_sha": approved,
                "target_ref": target_ref,
                "merged_by": merged_by,
                "pull_request": pull_request,
                "merged_at": merged_at,
                "reason": reason,
                "reported_by": actor,
                "approval_seq": approval["seq"],
                "resulting_version": resulting_version,
                # No working copy, no verification. Said here so a reader of
                # the log never has to infer it from the event's name.
                "verified": False,
            },
        )

    return {
        "task_id": task_id,
        "event_id": moved["event_id"],
        "from_state": moved["from_state"],
        "to_state": moved["to_state"],
        "candidate_sha": approved,
        "reported_by": actor,
        "task_version": resulting_version,
        "next": (
            f"POST /controller/tasks/{task_id}/reconcile with "
            f"integration_reconciled_landed once {merge_sha[:12]} is "
            f"confirmed on {target_ref}"
        ),
    }
