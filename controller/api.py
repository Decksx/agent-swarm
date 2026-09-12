"""HTTP routes over the controller library.

Why a router factory rather than a module-level app
---------------------------------------------------

`build_router()` takes the authentication dependency and the database path
from its caller. That keeps this module from importing `hub.py` -- which
imports this one -- and, more usefully, makes the routes testable against a
temp database and a stub authenticator without standing up the hub at all.

Identity
--------

**The authenticated component name is the agent.** Every route that acts on an
activation passes the caller's own component name into the controller, and no
route reads an agent, actor or sender from a request body. A worker therefore
cannot claim, heartbeat, result or judge on behalf of another agent, and the
controller's own `NotTheAssignedWorker` check is the second line rather than
the only one. This is the same property the hub gives chat by deriving
`sender` from the credential, applied to work.

Authority
---------

Two dependencies, matching the hub's own split: any authenticated component
may read and may act on activations issued to it; only an admin component may
create tasks, issue activations, or apply a bare transition. An agent cannot
issue itself work.

Connections
-----------

One SQLite connection per request, opened and closed inside the request.
FastAPI runs `def` endpoints in a threadpool, so a shared connection would be
used from several threads at once; per-request connections avoid that without
a lock. This is only safe because the hub runs as a single uvicorn process --
see the deployment notes on never adding `--workers N`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from . import activations, build, engine, states
from .db import transaction
from . import progression
from .db import connect, initialize, open_controller_db

# Controller errors mapped onto the status code that describes them, so a
# worker can tell "you are not allowed" from "you are too late" from "that does
# not exist" without parsing prose.
#
# 409 for the lifecycle failures is deliberate: they are all "the state moved
# under you", which is a conflict rather than a bad request. A worker that
# retries a 409 unchanged will keep getting it, which is the correct signal.
_STATUS_FOR = {
    activations.ActivationNotFound: 404,
    engine.TaskNotFound: 404,
    activations.NotTheAssignedWorker: 403,
    states.NotAuthorized: 403,
    activations.NotAReviewActivation: 403,
    activations.ActivationNotLive: 409,
    activations.LeaseExpired: 409,
    activations.DeadlineExceeded: 409,
    activations.ConflictingResult: 409,
    activations.HostAtCapacity: 409,
    activations.EvidenceNotDurable: 409,
    engine.StaleState: 409,
    engine.ConflictingReplay: 409,
    states.UndefinedTransition: 409,
    states.TransitionRejected: 409,
    activations.ActivationError: 400,
}


def _http(exc: Exception) -> HTTPException:
    """Translate a controller exception, most specific class first.

    Walked in `_STATUS_FOR` order rather than by `type(exc)` lookup, because
    the exception hierarchy is real -- `LeaseExpired` is an `ActivationError`
    -- and an exact-type lookup would miss a subclass added later and return
    500 for something the caller could have handled.
    """
    for klass, status in _STATUS_FOR.items():
        if isinstance(exc, klass):
            return HTTPException(status_code=status, detail=str(exc))

    raise exc


class CreateTask(BaseModel):
    task_id: str
    title: str
    objective: str
    contract_yaml: str = "schema_version: 7\n"
    base_sha: str
    proof_mode: str = "baseline"
    priority: int = 50


class IssueActivation(BaseModel):
    task_id: str
    agent: str
    host: str
    stage: str
    lease_seconds: float = 900.0
    hard_deadline_seconds: float = 5400.0
    expected_branch: Optional[str] = None
    expected_parent: Optional[str] = None
    expected_candidate: Optional[str] = None
    repo_location: Optional[str] = None


class Transition(BaseModel):
    kind: str
    payload: Dict[str, Any] = {}
    expected_state_seq: Optional[int] = None


class Result(BaseModel):
    kind: str
    payload: Dict[str, Any] = {}
    evidence_ids: List[str] = []
    expected_state_seq: Optional[int] = None


class ReviewJudgment(BaseModel):
    judgment: str
    payload: Dict[str, Any] = {}
    expected_state_seq: Optional[int] = None


class AuthorOutcome(BaseModel):
    outcome: str
    payload: Dict[str, Any] = {}
    expected_state_seq: Optional[int] = None


class IntegrationOutcome(BaseModel):
    outcome: str
    payload: Dict[str, Any] = {}
    expected_state_seq: Optional[int] = None


class HostCapacity(BaseModel):
    host: str
    max_concurrent: int = 1


# The NEEDS_HUMAN exits an operator may take through this route.
#
# A subset of what the state table allows, on purpose. `create_contract_version`
# is a real exit and is not here: it mints a new contract, and a contract is
# yaml, a base sha and a proof mode -- none of which a sentence of prose
# contains. Offering it as a free-text action would let an operator believe
# they had authorized new work when what they had actually supplied was a
# comment.
# Who may read the cross-task event feed.
#
# The narrator needs it to narrate, and an operator needs it to see what
# the narrator saw. Nobody else does, and every component that holds a
# credential is a component that could read it if allowed to.
FEED_READERS = frozenset({"narrator", "admin", "operator"})

# Kinds the generic transition route refuses, and where each belongs.
#
# Every one of them is reachable another way with checks attached, and
# reaching it here arrives with none of them. `operator-response` requires a
# NEEDS_HUMAN task, the version the operator was shown, the text they wrote,
# and one named resume -- then records the answer, applies the resume, and
# advances the version in one transaction. Submitting `return_to_author` here
# instead resumes the task with no answer recorded, no stale-write check, and
# the version left where it was, so every attempt authorized before the
# escalation stays valid against a decision that overruled them.
#
# `operator_response` itself is refused for the mirror reason: submitted here
# it records an answer that resumes nothing, leaving a task that reads as
# answered and is still stuck.
#
# `create_contract_version` is refused everywhere prose can reach it. It mints
# a contract, and a contract is yaml, a base sha and a proof mode.
#
# Cancellation and supersession stay generic: they are terminal or superseding
# moves that carry no evidence and invalidate nothing that needed carrying.
ROUTED_ELSEWHERE = {
    "operator_response":
        "POST /controller/tasks/{task_id}/operator-response",
    "return_to_author":
        "POST /controller/tasks/{task_id}/operator-response "
        "with action=return_to_author",
    "return_to_review":
        "POST /controller/tasks/{task_id}/operator-response "
        "with action=return_to_review",
    "admin_failed":
        "POST /controller/tasks/{task_id}/operator-response "
        "with action=admin_failed",
    "create_contract_version":
        "the task version route, with contract_yaml, base_sha and proof_mode; "
        "it cannot be created from free text",
}


RESUME_ACTIONS = frozenset({
    "return_to_author",
    "return_to_review",
    "admin_failed",
})


class OperatorResponse(BaseModel):
    """An operator answering a NEEDS_HUMAN escalation.

    Every field is required because every one of them is a way this goes wrong
    if it is guessed. `expected_version` is the stale-write check: an operator
    reading a question in the chatroom may be answering something the swarm
    has already moved past, and applying that answer to whatever the task
    looks like now is how a stale instruction becomes an authoritative one.
    `action` is named rather than inferred -- "return this to the author" and
    "return this to review" are different instructions, and a controller that
    picked one from the wording of a sentence would be interpreting prose as
    authority.
    """
    expected_version: int
    response: str
    action: str


class Heartbeat(BaseModel):
    # The worker asks for the lease it wants; the controller decides whether
    # it still has one to give. Never extends the hard deadline.
    lease_seconds: float = 900.0


def build_router(
    *,
    authenticate: Callable,
    require_admin: Callable,
    db_path: str,
) -> APIRouter:
    """Build the controller router bound to one authenticator and database."""
    router = APIRouter(prefix="/controller", tags=["controller"])

    def get_conn():
        """One connection, for one request, closed when that request is done.

        `same_thread_only=False`, and the reason is FastAPI's lifecycle rather
        than anything about concurrency. A sync dependency runs in a
        threadpool, and a generator dependency's two halves are separate
        scheduling events: the setup half runs on one worker thread, and the
        cleanup half can resume on another. SQLite's guard then refuses the
        `conn.close()` below -- after the handler has already done its work --
        so the request's effect lands and the caller still gets a 500. That
        produced intermittent failures on `claim` and on the event feed, which
        were indistinguishable from a real controller fault.

        This is NOT a claim that the connection is safe to share. It is used
        by exactly one request, sequentially: opened, handed to one handler,
        closed. Nothing here hands it to a second thread while a first is
        using it, and nothing caches it -- a module-global connection behind
        this dependency would turn a lifecycle quirk into genuine concurrent
        use of one SQLite object, which the guard exists to prevent and which
        turning the guard off would then hide.

        The schema's rule is unchanged and is what makes this safe at the
        database level: one process writes, and every projection update and
        its event append share one `BEGIN IMMEDIATE` transaction.
        """
        conn = open_controller_db(db_path, same_thread_only=False)
        try:
            yield conn
        finally:
            conn.close()

    # The narrator's only read, and the only route it needs.
    #
    # Bounded and ordered by `seq`, which is the whole reason pagination here
    # is safe. `seq` is AUTOINCREMENT and every append happens in one
    # serialized transaction, so an event committed while a narrator is
    # paginating necessarily lands *above* every sequence already returned --
    # it becomes the next page rather than shifting the current one. A feed
    # ordered by timestamp, or one paginated by offset, would let a late
    # arrival reorder or displace what had already been delivered.
    @router.get("/events")
    def event_feed(
        since: Optional[int] = None,
        limit: int = 200,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Events after `since`, oldest first, with the authoritative maximum.

        `max_seq` is computed from the table rather than from the page, so a
        first-run narrator can learn where the ledger currently ends without
        reading it. Taking the maximum from a limited page would start a fresh
        narrator at the end of its first *page* and replay everything after it
        into the room.

        Omitting `since` returns no events at all -- just the maximum. That is
        the "where are we" call, and it is shaped this way so that the cheapest
        thing a new narrator can do is also the thing that does not flood the
        room.
        """
        # Read-only, and still not for everyone. A worker has no
        # operational reason to read every other task's events: its own
        # activation carries everything it is entitled to act on, and a
        # cross-task stream would hand it operator responses and review
        # verdicts belonging to work it was never given.
        if component not in FEED_READERS:
            raise HTTPException(
                status_code=403,
                detail="this component may not read the event feed",
            )

        limit = max(1, min(int(limit), 500))

        row = conn.execute("SELECT MAX(seq) AS m FROM events").fetchone()
        max_seq = row["m"] if row and row["m"] is not None else 0

        if since is None:
            return {"events": [], "max_seq": max_seq, "next_since": max_seq}

        rows = conn.execute(
            "SELECT e.*, a.stage AS stage FROM events e "
            "LEFT JOIN activations a ON a.activation_id = e.activation_id "
            "WHERE e.seq > ? ORDER BY e.seq ASC LIMIT ?",
            (int(since), limit),
        ).fetchall()

        events = []

        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                payload = {}

            events.append({
                "seq": row["seq"],
                "event_id": row["event_id"],
                "task_id": row["task_id"],
                "task_version": row["task_version"],
                "activation_id": row["activation_id"],
                "stage": row["stage"],
                "actor": row["actor"],
                "authority": row["authority"],
                "kind": row["kind"],
                "from_state": row["from_state"],
                "to_state": row["to_state"],
                "payload_json": payload,
                "created_at": row["created_at"],
            })

        return {
            "events": events,
            "max_seq": max_seq,
            "next_since": events[-1]["seq"] if events else int(since),
        }

    @router.get("/status")
    def controller_status(
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Enough to tell whether the controller is alive and what it holds."""
        counts = {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM activations GROUP BY status"
            )
        }
        tasks = {
            row["state"]: row["n"]
            for row in conn.execute(
                "SELECT state, COUNT(*) AS n FROM tasks GROUP BY state"
            )
        }

        # Two builds, not one, and the difference between them is the point.
        #
        # `loaded` is what this process started with; `disk` is what is on the
        # host now. A constant would survive a forgotten deploy alongside the
        # stale code it describes, which is the failure this exists to catch --
        # but a single disk-read digest has its own version of that failure: a
        # deploy that copies files without restarting reports the new build
        # while the old code answers the request. Reporting both lets the
        # preflight tell "never deployed" from "deployed, not restarted",
        # which are different mistakes with different fixes.
        loaded = build.loaded()
        disk = build.describe(build.DEPLOYMENT_ROOT)

        return {
            "you": component,
            # The version lives in PRAGMA user_version, not a table.
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "loaded_build_id": loaded["build_id"],
            "disk_build_id": disk["build_id"],
            "loaded_files": loaded["files"],
            "disk_files": disk["files"],
            "tasks": tasks,
            "activations": counts,
        }

    # --- Tasks: admin only ---------------------------------------------------

    @router.post("/tasks")
    def create_task(
        body: CreateTask,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            return engine.create_task(
                conn,
                task_id=body.task_id,
                title=body.title,
                objective=body.objective,
                contract_yaml=body.contract_yaml,
                base_sha=body.base_sha,
                created_by=component,
                proof_mode=body.proof_mode,
                priority=body.priority,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"task exists: {exc}")
        except Exception as exc:
            raise _http(exc)

    @router.get("/tasks/{task_id}")
    def get_task(
        task_id: str,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            return engine.get_task(conn, task_id)
        except Exception as exc:
            raise _http(exc)

    @router.get("/tasks/{task_id}/events")
    def task_events(
        task_id: str,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            engine.get_task(conn, task_id)
            return {"task_id": task_id, "events": engine.event_log(conn, task_id)}
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/{task_id}/ready")
    def make_ready(
        task_id: str,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Move a DRAFT task to READY_AUTHOR, with controller authority.

        Admin triggers it; the controller performs it. Section 8 makes
        `contract_validated` and `queued` controller transitions, and that
        distinction is real rather than bookkeeping: an operator *asking* for a
        task to be queued is not an operator *declaring* it queued, in the same
        way a reviewer asks for a gate to close and the controller closes it.
        An admin-authority route for these would let the operator queue a task
        the controller would have rejected.

        **Nothing is validated.** The contract linter is deferred, so
        `contract_yaml` is stored and hashed but never parsed. The transition
        is emitted because the state machine requires it, not because anything
        was checked. Named `ready` rather than `validate` for that reason -- a
        route called `validate` would be claiming a check that does not exist.
        """
        try:
            for kind in ("contract_validated", "queued"):
                outcome = engine.apply_transition(
                    conn,
                    task_id=task_id,
                    kind=kind,
                    actor=component,
                    authority=states.CONTROLLER,
                )
            return outcome
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/{task_id}/retry")
    def retry(
        task_id: str,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Ask for another author attempt on a rejected task.

        Admin triggers it; the controller decides. `retry_authorized` is a
        controller-authority transition, so it cannot be applied through the
        admin transition route -- and that is not an oversight to work around
        here. An operator who could declare a retry could keep buying attempts
        past the point where the loop itself is the problem, which is what
        `budget_exhausted` and NEEDS_HUMAN exist to stop.

        Either outcome is a recorded decision: another attempt, or an
        escalation to a person.
        """
        try:
            return engine.authorize_retry(conn, task_id=task_id, actor=component)
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/{task_id}/repair")
    def repair(
        task_id: str,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Release a task from AUTHOR_BLOCKED or REVIEW_BLOCKED.

        Controller authority, admin-triggered, for the same reason /ready is:
        `environment_repaired` is a controller transition in section 8, so the
        admin-authority route cannot emit it -- which left a blocked task with
        no way back at all. A worker can put a task into a blocked state and
        nobody could take it out.

        The operator asserts the environment is fixed; the controller moves the
        task. Nothing here checks that anything was actually repaired, and the
        state machine will refuse this from anywhere but a blocked state.
        """
        try:
            return engine.apply_transition(
                conn,
                task_id=task_id,
                kind="environment_repaired",
                actor=component,
                authority=states.CONTROLLER,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/{task_id}/transition")
    def transition(
        task_id: str,
        body: Transition,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Apply an admin-authority transition.

        The operator's lever for the events section 8 gives to Admin alone:
        answering a NEEDS_HUMAN escalation, cancelling, superseding. A
        controller-authority event submitted here is refused as unauthorized,
        which is the point -- this route cannot be used to hand the operator
        the controller's own decisions.

        It is not how workers report work; that is the result route, which
        carries the activation's own authority.

        Five kinds are refused here and directed at the route that checks
        them. This route applies admin authority to any kind the state table
        permits, which made it a way around every guard on the escalation
        path: an operator could resume a task without recording what they
        answered, without the version they were shown being checked, and
        without the version advancing to invalidate the attempts the
        escalation overruled.
        """
        refused = ROUTED_ELSEWHERE.get((body.kind or "").strip())

        if refused is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "this transition has its own route",
                    "kind": body.kind,
                    "use": refused,
                    "why": "applying it here would skip the checks that route "
                           "exists to make",
                },
            )

        try:
            return engine.apply_transition(
                conn,
                task_id=task_id,
                kind=body.kind,
                actor=component,
                authority=states.ADMIN,
                expected_state_seq=body.expected_state_seq,
                payload=body.payload,
            )
        except Exception as exc:
            raise _http(exc)

    # --- Activations ---------------------------------------------------------

    # The operator's way back in, and the only one.
    #
    # Admin authority, deliberately. `narrator` can read the feed and speak in
    # the room and can do nothing here: the room is where questions are asked,
    # and it is not where answers acquire authority. Chat carried unauthenticated
    # remote execution before Phase 0, and a reply path that reached this route
    # would hand that back with better manners.
    @router.post("/tasks/{task_id}/operator-response")
    def operator_response(
        task_id: str,
        body: OperatorResponse,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Answer a NEEDS_HUMAN escalation and say what should happen next.

        One transaction over all four steps: check the task is still asking,
        check the operator is answering the version they were shown, record
        what was said, and apply the resume they named. Splitting any of those
        out would let an answer be recorded against a task that had already
        moved, or a resume be applied with no record of what prompted it.

        The version advances as part of the same transaction. That is not
        bookkeeping -- it is what invalidates everything in flight against the
        old one. A retry authorized before the escalation is pinned to the
        version it was authorized for, and an operator's answer is a decision
        that those attempts were made under conditions that no longer hold.
        """
        action = (body.action or "").strip()

        if action not in RESUME_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unsupported resume action",
                    "action": action,
                    "supported": sorted(RESUME_ACTIONS),
                    # Named rather than silently absent. `create_contract_version`
                    # is a real NEEDS_HUMAN exit and it needs a contract --
                    # yaml, base sha, proof mode -- none of which a sentence
                    # of prose contains. Accepting it here would mint a
                    # version whose contract was guessed.
                    "unsupported_here": {
                        "create_contract_version":
                            "needs structured contract data (contract_yaml, "
                            "base_sha, proof_mode); use the task version route",
                    },
                },
            )

        text = (body.response or "").strip()

        if not text:
            raise HTTPException(
                status_code=422, detail="response text may not be empty",
            )

        with transaction(conn):
            task = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()

            if task is None:
                raise HTTPException(status_code=404, detail="no such task")

            if task["state"] != "NEEDS_HUMAN":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "task is not asking for an operator decision",
                        "state": task["state"],
                    },
                )

            if task["current_version"] != body.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "stale response: the task has moved on",
                        "expected_version": body.expected_version,
                        "current_version": task["current_version"],
                    },
                )

            resulting_version = task["current_version"] + 1

            current = conn.execute(
                "SELECT * FROM task_versions WHERE task_id = ? AND version = ?",
                (task_id, task["current_version"]),
            ).fetchone()

            if current is None:
                raise HTTPException(
                    status_code=500,
                    detail="task has no contract for its current version",
                )

            now = time.time()

            # The same contract at a new version. Nothing about the work
            # changed; what changed is that every attempt pinned to the old
            # version was made before the operator answered.
            conn.execute(
                "INSERT INTO task_versions (task_id, version, contract_yaml, "
                "contract_hash, protocol_schema_version, base_sha, proof_mode, "
                "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    task_id, resulting_version, current["contract_yaml"],
                    current["contract_hash"],
                    current["protocol_schema_version"], current["base_sha"],
                    current["proof_mode"], now, component,
                ),
            )
            conn.execute(
                "UPDATE tasks SET current_version = ? WHERE task_id = ?",
                (resulting_version, task_id),
            )

            # Recorded before the resume, so the log reads in the order it
            # happened: the operator said this, and therefore the task moved.
            said = engine.apply_transition_within(
                conn, task_id=task_id, kind="operator_response",
                actor=component, authority=states.ADMIN,
                payload={
                    "response": text,
                    "action": action,
                    "resulting_version": resulting_version,
                },
                now=now,
            )

            moved = engine.apply_transition_within(
                conn, task_id=task_id, kind=action, actor=component,
                authority=states.ADMIN, source_event_id=said["event_id"],
                payload={"response_event_id": said["event_id"]}, now=now,
            )

        return {
            "task_id": task_id,
            "response_event_id": said["event_id"],
            "action": action,
            "from_state": "NEEDS_HUMAN",
            "to_state": moved["to_state"],
            "task_version": resulting_version,
            "answered_by": component,
        }

    @router.post("/hosts")
    def set_capacity(
        body: HostCapacity,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        # No drain flag here. Cooperative drain is deferred v7 hardening and is
        # kept inert for the MVP: the column exists in the schema, nothing
        # sets it, and exposing a route that did would be the first step to
        # something depending on a mechanism that is not built.
        activations.set_host_capacity(conn, body.host, body.max_concurrent)
        return {"host": body.host, "max_concurrent": body.max_concurrent}

    @router.post("/activations")
    def issue(
        body: IssueActivation,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Issue an activation. Admin only, so no agent can issue itself work."""
        try:
            return activations.issue(
                conn,
                task_id=body.task_id,
                agent=body.agent,
                host=body.host,
                stage=body.stage,
                lease_seconds=body.lease_seconds,
                hard_deadline_seconds=body.hard_deadline_seconds,
                expected_branch=body.expected_branch,
                expected_parent=body.expected_parent,
                expected_candidate=body.expected_candidate,
                repo_location=body.repo_location,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/claim")
    def claim(
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Claim the caller's next activation, or report that there is none.

        The agent is the authenticated component and is not in the body, so
        this route cannot be used to take work assigned to somebody else.

        An empty queue is a 200 with `activation: null` rather than a 404: for
        a polling worker, having no work is the normal case and not an error,
        and a 404 would be indistinguishable from a misrouted URL.
        """
        try:
            claimed = activations.claim_next(conn, agent=component)
        except Exception as exc:
            raise _http(exc)

        return {"agent": component, "activation": claimed}

    @router.post("/activations/{activation_id}/heartbeat")
    def heartbeat(
        activation_id: str,
        body: Heartbeat = Body(default=Heartbeat()),
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            return activations.heartbeat(
                conn,
                activation_id=activation_id,
                agent=component,
                lease_seconds=body.lease_seconds,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/{activation_id}/result")
    def result(
        activation_id: str,
        body: Result,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        try:
            return activations.submit_result(
                conn,
                activation_id=activation_id,
                agent=component,
                kind=body.kind,
                payload=body.payload,
                evidence_ids=body.evidence_ids,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/{activation_id}/review")
    def review(
        activation_id: str,
        body: ReviewJudgment,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Submit a review judgment for an activation the caller holds.

        Not admin-gated, and it does not need to be: the controller refuses
        unless the caller is the agent this specific review activation was
        issued to and the lease is still live. Requiring admin here would mean
        the operator judging every review, which is the thing the swarm exists
        to avoid.
        """
        try:
            return activations.submit_review_judgment(
                conn,
                activation_id=activation_id,
                agent=component,
                judgment=body.judgment,
                payload=body.payload,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/{activation_id}/outcome")
    def outcome(
        activation_id: str,
        body: AuthorOutcome,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Report how an author activation ended.

        The author counterpart of /review, and admin-gated for the same reason
        it is not: the controller refuses unless the caller is the agent this
        specific live author activation was issued to.

        This is how a worker says a run failed. `candidate_submitted` is the
        only author-authority event out of AUTHORING, so without this route a
        worker could report success and nothing else.
        """
        try:
            return activations.submit_author_outcome(
                conn,
                activation_id=activation_id,
                agent=component,
                outcome=body.outcome,
                payload=body.payload,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/{activation_id}/integration")
    def integration(
        activation_id: str,
        body: IntegrationOutcome,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Report how an integration activation ended.

        Its own route rather than a case of /outcome, because the outcomes are
        not the author's and collapsing them would let a worker submit
        `integrated` against an author activation. The stage is checked inside
        the submission, so a mismatch is refused rather than applied to the
        wrong task.

        Without this route the integration stage could be issued and claimed
        and then had no way to finish: the activation would sit live until its
        lease lapsed, and the task would sit in INTEGRATING having possibly
        already merged. Every check the integrator performs would have run and
        none of it could be recorded.
        """
        try:
            return activations.submit_integration_outcome(
                conn,
                activation_id=activation_id,
                agent=component,
                outcome=body.outcome,
                payload=body.payload,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/{task_id}/reconcile")
    def reconcile(
        task_id: str,
        body: Transition,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Resolve an integration whose outcome was never observed.

        The way out of INTEGRATION_UNCERTAIN, and the only one. `kind` is the
        reconciliation event -- landed, absent, or failed -- and it is applied
        with controller authority because deciding that a merge did or did not
        happen is a statement about the world that the ledger will be read as
        having established.

        Admin-gated because reconciling requires looking at the remote, which
        the controller cannot do. A person or an operator tool establishes the
        fact; this records it.
        """
        allowed = {
            "integration_reconciled_landed",
            "integration_reconciled_absent",
            "reconciliation_failed",
        }

        if body.kind not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"{body.kind!r} is not a reconciliation; "
                       f"expected one of {sorted(allowed)}",
            )

        try:
            return engine.apply_transition(
                conn,
                task_id=task_id,
                kind=body.kind,
                actor=component,
                authority=states.CONTROLLER,
                payload=body.payload,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise _http(exc)

    @router.post("/tasks/advance")
    def advance(
        task_id: Optional[str] = None,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Issue the next activation for anything whose stage is unambiguous.

        The third of the three operator steps that sat between stages, and the
        only one the controller can take: issuing an activation is granting
        permission to act, so a worker that could issue its own next stage
        could grant itself the work. A caller may only say "look for anything
        ready" -- never "start this task at this stage".

        Safe to poll. A task with a live activation is skipped, so a second
        call while a stage is under way does nothing rather than handing the
        same task to two workers.

        Reports what it declined as well as what it issued, because a poller
        needs to tell "nothing was ready" from "something was ready and could
        not be started".
        """
        routing = progression.Routing(
            verifier=os.environ.get("PROGRESSION_VERIFIER", ""),
            integrator=os.environ.get("PROGRESSION_INTEGRATOR", ""),
            host=os.environ.get("PROGRESSION_HOST", ""),
            repo_location=os.environ.get("PROGRESSION_REPO_LOCATION", ""),
        )

        try:
            return {"considered": progression.advance(
                conn, routing=routing, task_id=task_id
            )}
        except Exception as exc:
            raise _http(exc)

    @router.post("/activations/sweep")
    def sweep(
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Reclaim expired activations and recover their tasks."""
        return {"reclaimed": activations.sweep_expired(conn)}

    return router


def ensure_database(db_path: str) -> None:
    """Create the schema if this is a fresh database.

    Called once at import by whatever wires the router in, rather than lazily
    per request: a request that has to decide whether to create the schema is a
    request that can race another one doing the same.
    """
    # Through `connect`, not `sqlite3.connect`. Opening raw left a fresh
    # database in SQLite's default `delete` journal mode, because the pragmas
    # live in `connect` and nothing here ran them -- so the first requests
    # against a new database each found a non-WAL file and raced to set WAL,
    # which takes an exclusive lock, and the losers failed the *connect* with
    # "database is locked". Journal mode is a persistent property of the file,
    # so setting it once here is both sufficient and the only place it needs
    # doing.
    conn = connect(db_path)
    try:
        initialize(conn)
    finally:
        conn.close()
