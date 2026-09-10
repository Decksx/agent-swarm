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

import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from . import activations, build, engine, states
from .db import initialize, open_controller_db

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


class HostCapacity(BaseModel):
    host: str
    max_concurrent: int = 1


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
        conn = open_controller_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

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
        """
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
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        initialize(conn)
    finally:
        conn.close()
