"""HTTP behaviour of the controller routes.

Lives in `hub/` rather than `tests/` for the same reason `test_hub.py` does:
it needs FastAPI, and the system interpreter does not have it. `pytest.ini`
points a bare `pytest` at `tests/`, so a suite placed there would fail to
import for everyone without the venv. The module under test is
`controller/api.py`; the directory only records what it needs to run.

The router is built with a stub authenticator, so these exercise the routes
without standing up the hub. What they are pinning is the HTTP layer's own
contribution -- identity taken from the credential rather than the body,
admin-only routes, and controller exceptions mapped onto status codes a worker
can act on. The lifecycle guarantees underneath are already covered by the 166
tests in `tests/`, and are not re-asserted here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import api, schema  # noqa: E402

ADMINS = {"admin", "operator"}


def stub_authenticate(x_test_agent: str = Header(default="")) -> str:
    """Stand in for the hub's HTTP Basic dependency.

    A header rather than real Basic auth: what these tests care about is that
    the routes take identity from the *authenticator* and never from a body,
    and that property is independent of how the authenticator establishes it.
    """
    if not x_test_agent:
        raise HTTPException(status_code=401, detail="authentication required")

    return x_test_agent.strip().lower()


def stub_require_admin(x_test_agent: str = Header(default="")) -> str:
    component = stub_authenticate(x_test_agent)

    if component not in ADMINS:
        raise HTTPException(status_code=403, detail="admin only")

    return component


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "controller.db"
    api.ensure_database(str(db))

    app = FastAPI()
    app.include_router(
        api.build_router(
            authenticate=stub_authenticate,
            require_admin=stub_require_admin,
            db_path=str(db),
        )
    )
    return TestClient(app)


def as_(client, agent, method, path, **kw):
    return getattr(client, method)(path, headers={"X-Test-Agent": agent}, **kw)


@pytest.fixture
def queued_task(client):
    """A task in READY_AUTHOR, on a host with one slot."""
    as_(client, "admin", "post", "/controller/hosts",
        json={"host": "OFFICEPC", "max_concurrent": 1})
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "pilot", "objective": "o", "base_sha": "0" * 40,
    })
    as_(client, "admin", "post", "/controller/tasks/T-1/ready")
    return "T-1"


# --- Authentication and authority -------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("get", "/controller/status"),
    ("post", "/controller/activations/claim"),
    ("get", "/controller/tasks/T-1"),
])
def test_every_route_needs_a_credential(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("path,body", [
    ("/controller/tasks", {"task_id": "X", "title": "t", "objective": "o",
                           "base_sha": "0" * 40}),
    ("/controller/activations", {"task_id": "T-1", "agent": "claudecode",
                                 "host": "OFFICEPC", "stage": "author"}),
    ("/controller/hosts", {"host": "OFFICEPC", "max_concurrent": 1}),
])
def test_a_worker_cannot_reach_the_admin_routes(client, path, body):
    """An agent that could issue activations could assign itself work."""
    assert as_(client, "gemini", "post", path, json=body).status_code == 403
    assert as_(client, "claudecode", "post", path, json=body).status_code == 403


def test_the_agent_is_the_credential_not_the_body(client, queued_task):
    """Claiming takes no agent field, so it cannot be aimed at someone else.

    The activation is issued to claudecode. chatgpt claiming finds nothing --
    not an error, and specifically not claudecode's work.
    """
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })

    stolen = as_(client, "chatgpt", "post", "/controller/activations/claim")
    assert stolen.status_code == 200
    assert stolen.json()["activation"] is None

    mine = as_(client, "claudecode", "post", "/controller/activations/claim")
    assert mine.json()["activation"]["task_id"] == "T-1"


def test_another_agent_cannot_result_someone_elses_activation(client, queued_task):
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })
    claimed = as_(client, "claudecode", "post", "/controller/activations/claim")
    activation_id = claimed.json()["activation"]["activation_id"]

    response = as_(client, "chatgpt", "post",
                   f"/controller/activations/{activation_id}/result",
                   json={"kind": "candidate_submitted"})

    assert response.status_code == 403


# --- Claiming ----------------------------------------------------------------


def test_an_empty_queue_is_a_200_with_no_activation(client):
    """Not a 404: for a polling worker, no work is the normal case.

    A 404 would also be indistinguishable from a misrouted URL, which is
    exactly the confusion a worker cannot resolve on its own.
    """
    response = as_(client, "claudecode", "post", "/controller/activations/claim")

    assert response.status_code == 200
    assert response.json() == {"agent": "claudecode", "activation": None}


def test_a_second_claim_does_not_hand_out_the_same_activation(client, queued_task):
    """Repeated polling must not repeat work already claimed."""
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })

    first = as_(client, "claudecode", "post", "/controller/activations/claim")
    second = as_(client, "claudecode", "post", "/controller/activations/claim")

    assert first.json()["activation"]["activation_id"]
    assert second.json()["activation"] is None


def test_a_claim_carries_durations_and_no_timestamps(client, queued_task):
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })
    body = as_(client, "claudecode", "post",
               "/controller/activations/claim").json()["activation"]

    assert "lease_seconds_remaining" in body
    assert not any(key.endswith("_at") for key in body), body


# --- Error mapping -----------------------------------------------------------


def test_a_missing_task_is_404(client):
    assert as_(client, "admin", "get", "/controller/tasks/nope").status_code == 404


def test_a_missing_activation_is_404(client):
    assert as_(client, "claudecode", "post",
               "/controller/activations/nope/heartbeat").status_code == 404


def test_a_duplicate_task_is_409(client):
    body = {"task_id": "T-9", "title": "t", "objective": "o", "base_sha": "0" * 40}
    assert as_(client, "admin", "post", "/controller/tasks", json=body).status_code == 200
    assert as_(client, "admin", "post", "/controller/tasks", json=body).status_code == 409


def test_an_undefined_transition_is_409(client, queued_task):
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": "integration_completed"})

    assert response.status_code == 409


def test_admin_cannot_borrow_controller_authority_through_transition(client, queued_task):
    """The generic route is admin-authority, and only admin-authority.

    `review_requirements_satisfied` belongs to the controller. If an operator
    could emit it here, the review gate would have a second door with no
    activation check behind it.
    """
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": "review_requirements_satisfied"})

    assert response.status_code in (403, 409)


def test_capacity_refusal_is_409(client, queued_task):
    """A full host is a conflict, not a bad request: retrying later works."""
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-2", "title": "t", "objective": "o", "base_sha": "0" * 40,
    })
    as_(client, "admin", "post", "/controller/tasks/T-2/ready")

    first = as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })
    second = as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-2", "agent": "chatgpt", "host": "OFFICEPC",
        "stage": "author",
    })

    assert first.status_code == 200
    assert second.status_code == 409


# --- The review gate over HTTP ----------------------------------------------


@pytest.fixture
def under_review(client, queued_task):
    as_(client, "admin", "post", "/controller/hosts",
        json={"host": "OFFICEPC", "max_concurrent": 2})
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })
    author = as_(client, "claudecode", "post",
                 "/controller/activations/claim").json()["activation"]
    as_(client, "claudecode", "post",
        f"/controller/activations/{author['activation_id']}/result",
        json={"kind": "candidate_submitted",
              "payload": {"branch": "task/T-1", "sha": "a" * 40}})

    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "gemini", "host": "OFFICEPC", "stage": "review",
        "expected_branch": "task/T-1", "expected_candidate": "a" * 40,
        "repo_location": "/srv/checkouts/T-1",
    })
    review = as_(client, "gemini", "post",
                 "/controller/activations/claim").json()["activation"]
    return review["activation_id"]


def test_the_reviewer_can_close_the_gate(client, under_review):
    response = as_(client, "gemini", "post",
                   f"/controller/activations/{under_review}/review",
                   json={"judgment": "satisfied"})

    assert response.status_code == 200
    assert response.json()["to_state"] == "READY_INTEGRATION"


def test_a_non_holder_cannot_close_the_gate(client, under_review):
    """403 even for admin: this is about holding the activation, not rank."""
    assert as_(client, "chatgpt", "post",
               f"/controller/activations/{under_review}/review",
               json={"judgment": "satisfied"}).status_code == 403
    assert as_(client, "admin", "post",
               f"/controller/activations/{under_review}/review",
               json={"judgment": "satisfied"}).status_code == 403


def test_the_reviewer_cannot_take_the_gate_through_the_result_route(client, under_review):
    """The verifier role is unauthorized for that event, over HTTP too."""
    response = as_(client, "gemini", "post",
                   f"/controller/activations/{under_review}/result",
                   json={"kind": "review_requirements_satisfied"})

    assert response.status_code == 403


def test_a_redelivered_judgment_replays_rather_than_repeating(client, under_review):
    first = as_(client, "gemini", "post",
                f"/controller/activations/{under_review}/review",
                json={"judgment": "satisfied"}).json()
    second = as_(client, "gemini", "post",
                 f"/controller/activations/{under_review}/review",
                 json={"judgment": "satisfied"}).json()

    assert second["replayed"] is True
    assert second["event_id"] == first["event_id"]

    events = as_(client, "admin", "get",
                 "/controller/tasks/T-1/events").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("review_requirements_satisfied") == 1


def test_the_event_log_shows_actor_and_authority(client, under_review):
    as_(client, "gemini", "post", f"/controller/activations/{under_review}/review",
        json={"judgment": "satisfied"})

    events = as_(client, "admin", "get",
                 "/controller/tasks/T-1/events").json()["events"]
    gate = [e for e in events if e["kind"] == "review_requirements_satisfied"][0]

    assert gate["actor"] == "gemini"
    assert gate["authority"] == "controller"


# --- Status ------------------------------------------------------------------


def test_status_reports_the_schema_version_and_counts(client, queued_task):
    body = as_(client, "gemini", "get", "/controller/status").json()

    assert body["you"] == "gemini"
    assert body["schema_version"] == schema.SCHEMA_VERSION
    assert body["tasks"] == {"READY_AUTHOR": 1}


# --- The author outcome route -----------------------------------------------


@pytest.fixture
def authoring(client, queued_task):
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "claudecode", "host": "OFFICEPC",
        "stage": "author",
    })
    claimed = as_(client, "claudecode", "post", "/controller/activations/claim")
    return claimed.json()["activation"]["activation_id"]


@pytest.mark.parametrize("outcome,expected", [
    ("candidate", "READY_REVIEW"),
    ("failed", "CHANGES_REQUESTED"),
    ("blocked", "AUTHOR_BLOCKED"),
])
def test_a_worker_can_report_how_its_run_ended(client, authoring, outcome, expected):
    """Including that it failed, which it previously had no way to say."""
    response = as_(client, "claudecode", "post",
                   f"/controller/activations/{authoring}/outcome",
                   json={"outcome": outcome})

    assert response.status_code == 200
    assert response.json()["to_state"] == expected


def test_only_the_holder_can_report_the_outcome(client, authoring):
    assert as_(client, "chatgpt", "post",
               f"/controller/activations/{authoring}/outcome",
               json={"outcome": "candidate"}).status_code == 403
    assert as_(client, "admin", "post",
               f"/controller/activations/{authoring}/outcome",
               json={"outcome": "candidate"}).status_code == 403


def test_the_event_log_distinguishes_a_report_from_a_verdict(client, authoring):
    """Success is the author's own; a verdict is the controller's.

    Both are reported through the same route by the same worker, and the log
    has to keep them apart -- otherwise "the controller decided this task
    failed" and "the worker said it produced a candidate" look identical.
    """
    as_(client, "claudecode", "post",
        f"/controller/activations/{authoring}/outcome",
        json={"outcome": "failed"})

    events = as_(client, "admin", "get",
                 "/controller/tasks/T-1/events").json()["events"]
    verdict = [e for e in events if e["kind"] == "author_defect"][0]

    assert verdict["actor"] == "claudecode"
    assert verdict["authority"] == "controller"


def test_a_candidate_is_recorded_under_the_authors_own_authority(client, authoring):
    as_(client, "claudecode", "post",
        f"/controller/activations/{authoring}/outcome",
        json={"outcome": "candidate"})

    events = as_(client, "admin", "get",
                 "/controller/tasks/T-1/events").json()["events"]
    submitted = [e for e in events if e["kind"] == "candidate_submitted"][0]

    assert submitted["actor"] == "claudecode"
    assert submitted["authority"] == "author"
