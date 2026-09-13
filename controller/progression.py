"""Issuing the next stage, so a person does not have to.

Three operator steps used to sit between the stages of a run, and none of them
was a judgment: push the candidate, open its pull request, and issue the next
activation. The first two belong to the author's host and live in
`publication`. This is the third.

Why the controller does this and not a worker
---------------------------------------------

Issuing an activation is granting permission to act, so a worker that could
issue its own next stage could grant itself the work. The asymmetry is the
whole point of the design: a worker asks, and the controller decides.

So this runs with controller authority, on the controller's own state, and a
caller only gets to say "look for anything ready" -- never "start this task at
this stage".

What makes it safe to run repeatedly
------------------------------------

A task is advanced only if it is in a state whose next stage is unambiguous
*and* has no live activation. The second half is the idempotency: an
activation already issued means the stage is already under way, so a second
call does nothing rather than issuing a duplicate. That matters because this
is meant to be polled, and a poller that raced itself would hand the same task
to two workers.

Nothing is inferred about *what* to do. The stage follows from the state by a
table, the evidence comes from the ledger, and the agents and host come from
configuration. An unconfigured controller advances nothing, which is the right
failure: a controller that guessed who should review would assign work to
whoever it happened to name.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from . import activations, engine

# The state each stage follows from. Deliberately only two entries: these are
# the boundaries that were being crossed by hand, and every other transition in
# the machine either needs a judgment or is already automatic.
NEXT_STAGE = {
    "READY_REVIEW": "review",
    "READY_INTEGRATION": "integrate",
}


class Routing:
    """Who does what, and where. Configuration, never inference.

    Every field is required for the stage that uses it. A missing one means
    that stage is not advanced -- reported, rather than filled in with a
    plausible default, because the plausible default for "who reviews this" is
    whichever agent happens to be first in a list.
    """

    def __init__(
        self,
        *,
        verifier: str = "",
        integrator: str = "",
        host: str = "",
        repo_location: str = "",
        lease_seconds: float = 900.0,
        hard_deadline_seconds: float = 5400.0,
    ):
        self.verifier = (verifier or "").strip()
        self.integrator = (integrator or "").strip()
        self.host = (host or "").strip()
        self.repo_location = (repo_location or "").strip()
        self.lease_seconds = lease_seconds
        self.hard_deadline_seconds = hard_deadline_seconds

    def agent_for(self, stage: str) -> str:
        return {"review": self.verifier, "integrate": self.integrator}.get(stage, "")

    def missing_for(self, stage: str) -> list:
        lacking = []

        if not self.agent_for(stage):
            lacking.append("verifier" if stage == "review" else "integrator")

        if not self.host:
            lacking.append("host")

        # `repo_location` is deliberately not here. It is per-task first and
        # global only as a fallback, so a missing default is not a reason to
        # decline a task whose own producing activation records one. Checked
        # after that activation is resolved, against both.
        return lacking


def _has_live_activation(conn: sqlite3.Connection, task_id: str) -> bool:
    """Whether anything is already under way for this task.

    The idempotency, and the reason this can be polled. An activation that has
    been issued but not yet claimed still counts: it is a permission somebody
    holds, and issuing a second would put the same task in two workers' hands.
    """
    row = conn.execute(
        "SELECT 1 FROM activations WHERE task_id = ? AND status IN (?, ?) "
        "LIMIT 1",
        (task_id, activations.ISSUED, activations.CLAIMED),
    ).fetchone()

    return row is not None


def _producing_activation(conn: sqlite3.Connection, task_id: str) -> Optional[dict]:
    """The author activation that produced the candidate now approved.

    Not "the most recent activation naming a branch", which is what this used
    to read, and not a global setting. Both were wrong in the same direction:
    they described where work happens in general rather than where *this*
    task's work happened.

    The consequence was live. One `PROGRESSION_REPO_LOCATION` was applied to
    every ready task, so tasks belonging to other repositories were handed
    activations pointing at the demonstration checkout.

    So the branch, the repository and the candidate all come from one row: the
    author activation whose `candidate_submitted` event produced the commit the
    review approved. Every downstream stage is then talking about the same
    piece of work, and a task from another repository carries its own location
    or is not advanced at all.
    """
    row = conn.execute(
        "SELECT a.activation_id, a.expected_branch, a.repo_location, "
        "       e.payload_json "
        "FROM events e JOIN activations a "
        "  ON a.activation_id = e.activation_id "
        "WHERE e.task_id = ? AND e.kind = 'candidate_submitted' "
        "ORDER BY e.seq DESC LIMIT 1",
        (task_id,),
    ).fetchone()

    if row is None:
        return None

    try:
        payload = json.loads(row["payload_json"] or "{}")
    except ValueError:
        payload = {}

    return {
        "activation_id": row["activation_id"],
        "expected_branch": (row["expected_branch"] or "").strip(),
        "repo_location": (row["repo_location"] or "").strip(),
        "candidate_sha": str(payload.get("candidate_sha") or "").strip(),
    }


def _resolve_review_activation(
    conn: sqlite3.Connection, task_id: str, approved_candidate_sha: str
) -> Optional[dict]:
    """Resolve the review activation matching the approved candidate."""
    row = conn.execute(
        "SELECT activation_id, expected_branch, repo_location "
        "FROM activations WHERE task_id = ? AND expected_candidate = ? "
        "AND stage = 'review' "
        "ORDER BY issued_at DESC, activation_id DESC LIMIT 1",
        (task_id, approved_candidate_sha),
    ).fetchone()

    return dict(row) if row else None


def advance(
    conn: sqlite3.Connection,
    *,
    routing: Routing,
    task_id: Optional[str] = None,
    now: Optional[float] = None,
) -> list:
    """Issue the next activation for every task whose stage is unambiguous.

    Returns one record per task considered, saying what happened and why --
    including the ones it declined to advance. A caller polling this needs to
    be able to tell "nothing was ready" from "something was ready and could not
    be started", and a function that returned only its successes would make
    those identical.
    """
    states = list(NEXT_STAGE)
    placeholders = ",".join("?" for _ in states)
    params = list(states)

    query = (
        f"SELECT task_id, state, approved_candidate_sha FROM tasks "
        f"WHERE state IN ({placeholders})"
    )

    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)

    considered = []

    for row in conn.execute(query, params).fetchall():
        stage = NEXT_STAGE[row["state"]]
        record = {"task_id": row["task_id"], "state": row["state"],
                  "stage": stage, "issued": False}

        if _has_live_activation(conn, row["task_id"]):
            record["reason"] = "an activation is already live for this task"
            considered.append(record)
            continue

        # An integration the integrator would refuse is an integration not
        # worth issuing. Found in the first live run: four tasks left in
        # READY_INTEGRATION by earlier phases were swept up and given
        # activations, which consumed every slot on the host and blocked the
        # task the run was actually about.
        #
        # None of them could ever have been integrated -- their approvals
        # predate the column that records which candidate was approved, so
        # `approved_candidate_sha` is NULL and the integrator refuses. Issuing
        # anyway spent a real activation, moved a task out of the state it had
        # been parked in, and started a lease that would expire into
        # INTEGRATION_UNCERTAIN.
        #
        # Checked here rather than left to the integrator because the cost is
        # not the refusal, it is everything issuing does on the way to it.
        if stage == "integrate" and not (row["approved_candidate_sha"] or ""):
            record["reason"] = (
                "no approved_candidate_sha, so the integrator would refuse "
                "this; not spending an activation to find that out"
            )
            considered.append(record)
            continue

        lacking = routing.missing_for(stage)

        if lacking:
            record["reason"] = (
                f"routing is not configured for {stage}: missing "
                f"{', '.join(lacking)}"
            )
            considered.append(record)
            continue

        if stage == "integrate":
            approved_candidate = (row["approved_candidate_sha"] or "").strip()

            review_activation = _resolve_review_activation(
                conn, row["task_id"], approved_candidate
            )

            if not review_activation:
                record["reason"] = (
                    f"no review activation matches the approval candidate "
                    f"{approved_candidate}"
                )
                considered.append(record)
                continue

            branch = review_activation["expected_branch"]
            repo_location = review_activation["repo_location"] or routing.repo_location
        else:
            produced = _producing_activation(conn, row["task_id"])

            if produced is None or not produced["expected_branch"]:
                # Without it a review activation cannot be issued at all, and an
                # integration would have nothing to find a pull request from.
                record["reason"] = (
                    "no author activation with a branch produced a candidate for "
                    "this task"
                )
                considered.append(record)
                continue

            branch = produced["expected_branch"]

            # The repository this task's work actually happened in, carried from
            # the activation that did it. Falls back to the routing default only
            # when the producing activation recorded none, and a task with neither
            # is not advanced rather than pointed at somebody else's checkout.
            repo_location = produced["repo_location"] or routing.repo_location

            if not repo_location:
                record["reason"] = (
                    "neither the producing activation nor the routing names a "
                    "repository location for this task"
                )
                considered.append(record)
                continue

        try:
            issued = activations.issue(
                conn,
                task_id=row["task_id"],
                agent=routing.agent_for(stage),
                host=routing.host,
                stage=stage,
                lease_seconds=routing.lease_seconds,
                hard_deadline_seconds=routing.hard_deadline_seconds,
                expected_branch=branch,
                expected_candidate=(
                    (row["approved_candidate_sha"] or "").strip() or None
                ),
                repo_location=repo_location,
                now=now,
            )
        except activations.HostAtCapacity as exc:
            # Not an error. The host is busy and this task will be advanced by
            # a later call, which is exactly what a queue does.
            record["reason"] = str(exc)
            considered.append(record)
            continue
        except Exception as exc:
            record["reason"] = f"{type(exc).__name__}: {exc}"
            considered.append(record)
            continue

        record.update({
            "issued": True,
            "activation_id": issued["activation_id"],
            "agent": routing.agent_for(stage),
            "expected_branch": branch,
            "repo_location": repo_location,
            "from_activation": review_activation["activation_id"] if stage == "integrate" else produced["activation_id"],
        })
        considered.append(record)

    return considered
