"""The HTTP routes for external-review ingest (#92).

Mounted by `api.build_router`, and kept apart from it so `api.py` stays
inside the author's per-file view budget. The logic lives in `external` and
`outcomes`; these only take identity from the authenticator, read
configuration per request, and map errors onto status codes.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import external, outcomes
from .ingress import parse_projects


class IngestOutcome(BaseModel):
    outcome: str
    payload: Dict[str, Any] = {}
    expected_state_seq: Optional[int] = None


class ExternalReview(BaseModel):
    """An operator asking for a pull request to be reviewed (contract section 6).

    `pr_number` is `Any` so a string or a float is refused by the controller's
    own check with a clear message, rather than coerced into a PR number.
    """
    task_id: str
    project: str
    pr_number: Any
    objective: str
    at_sha: Optional[str] = None
    paths: Optional[List[str]] = None
    authored_by: Optional[List[str]] = None


def add_routes(
    router: APIRouter,
    *,
    authenticate: Callable,
    require_admin: Callable,
    get_conn: Callable,
    to_http: Callable[[Exception], HTTPException],
) -> None:
    @router.post("/activations/{activation_id}/ingest")
    def ingest(
        activation_id: str,
        body: IngestOutcome,
        component: str = Depends(authenticate),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Report how an ingest activation ended (contract section 8.3).

        Not admin-gated, for the reason /integration is not: the controller
        refuses unless the caller holds this specific live ingest activation.
        A report the stored request contradicts is refused with 422 and
        records nothing.
        """
        try:
            return outcomes.submit_ingest_outcome(
                conn,
                activation_id=activation_id,
                agent=component,
                outcome=body.outcome,
                payload=body.payload,
                expected_state_seq=body.expected_state_seq,
            )
        except Exception as exc:
            raise to_http(exc)

    @router.post("/external-reviews")
    def external_review(
        body: ExternalReview,
        component: str = Depends(require_admin),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Ask for a pull request to be reviewed (#74, #92).

        Creates the task and applies `external_review_requested` in one
        transaction, or refuses with 400 and writes nothing. The repository
        comes from configuration, never from the caller: `INGRESS_PROJECTS`
        says where it is checked out and `EXTERNAL_REVIEW_REPOS` which GitHub
        repository it is. Both are read per request, and a bad
        `EXTERNAL_REVIEW_REPOS` disables only this route.
        """
        try:
            projects = parse_projects(os.environ.get("INGRESS_PROJECTS", ""))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"external review is disabled: {exc}"
            )

        try:
            repos = external.parse_repos(os.environ.get("EXTERNAL_REVIEW_REPOS", ""))
            return external.create(
                conn,
                task_id=body.task_id,
                project=body.project,
                pr_number=body.pr_number,
                objective=body.objective,
                at_sha=body.at_sha,
                paths=body.paths,
                authored_by=body.authored_by,
                projects=projects,
                repos=repos,
                actor=component,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"task exists: {exc}")
        except Exception as exc:
            raise to_http(exc)
