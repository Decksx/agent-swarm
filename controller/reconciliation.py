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


# Where reporting an out-of-band merge makes sense: a task that stopped short
# of integrating.
#
# Not INTEGRATING or INTEGRATION_UNCERTAIN -- those have the integrator's own
# outcome route and the reconcile route, both of which carry evidence this one
# cannot. Not a terminal state either: a SUPERSEDED task is closed, and
# reopening one is a different decision than reconciling it, taken by a person
# who has to say so.
REPORTABLE_FROM = frozenset({"NEEDS_HUMAN", "CHANGES_REQUESTED"})


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
    candidate_sha: Optional[str] = None,
    pull_request: Optional[int] = None,
    merged_at: Optional[str] = None,
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

    with transaction(conn):
        task = engine.get_task(conn, task_id)

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

        moved = engine.apply_transition_within(
            conn,
            task_id=task_id,
            kind="out_of_band_merge_reported",
            actor=actor,
            authority=states.ADMIN,
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
        "next": (
            f"POST /controller/tasks/{task_id}/reconcile with "
            f"integration_reconciled_landed once {merge_sha[:12]} is "
            f"confirmed on {target_ref}"
        ),
    }
