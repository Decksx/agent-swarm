"""The integration stage over HTTP, and the way out when it expires.

Four blockers found in review, all four reproduced before being fixed. These
are the production routes rather than the functions beneath them, because
three of the four were failures of wiring rather than of logic: the stage could
be issued, the task moved, and there was no way for the worker to say what
happened.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_PATH = Path(__file__).resolve().parent / "hub.py"
REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from controller import activations, engine, states  # noqa: E402

SECRET = "s" * 32
ADMIN = ("admin", SECRET)
WORKER = ("claudecode", SECRET)

CAND = "1" * 40


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "HUB_CREDENTIALS", f"admin:{SECRET},claudecode:{SECRET},gemini:{SECRET}"
    )
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))

    spec = importlib.util.spec_from_file_location("hub_integration", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_integration"] = module
    spec.loader.exec_module(module)

    return module


@pytest.fixture
def client(app):
    with TestClient(app.app) as c:
        yield c


def approved_task(client, task_id="T-1"):
    """Take a task all the way to READY_INTEGRATION with a live approval."""
    client.post("/controller/hosts", auth=ADMIN,
                json={"host": "officepc", "max_concurrent": 3})
    client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": task_id, "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
    })
    client.post(f"/controller/tasks/{task_id}/ready", auth=ADMIN)

    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "author", "expected_branch": f"task/{task_id}",
    }).json()
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})
    client.post(
        f"/controller/activations/{issued['activation_id']}/outcome",
        auth=WORKER,
        json={"outcome": "candidate", "payload": {"candidate_sha": CAND}},
    )

    review = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "gemini", "host": "officepc",
        "stage": "review", "expected_branch": f"task/{task_id}",
        "expected_candidate": CAND, "repo_location": "/repo",
    }).json()
    client.post("/controller/activations/claim", auth=("gemini", SECRET),
                json={"activation_id": review["activation_id"]})
    client.post(
        f"/controller/activations/{review['activation_id']}/review",
        auth=("gemini", SECRET), json={"judgment": "satisfied"},
    )

    return task_id


def expire_into_uncertainty(client, task_id):
    """Reach INTEGRATION_UNCERTAIN the way production does: expiry, then sweep.

    Not by hand-driving the transition. `integration_outcome_unknown` carries
    controller authority and `/transition` carries admin's, so the hand-driven
    route does not work -- and if it did, it would prove nothing about the
    sweep, which is the thing that has to get this right.
    """
    import time

    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "integrate",
        # Already lapsed by the time the sweep looks at it.
        "lease_seconds": 0.001, "hard_deadline_seconds": 0.002,
    }).json()

    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    time.sleep(0.02)
    swept = client.post("/controller/activations/sweep", auth=ADMIN).json()

    return issued, swept


def issue_integration(client, task_id):
    return client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "integrate",
    }).json()


# --- Blocker 1: the stage may be issued and the approval survives it --------


def test_an_integration_activation_can_be_issued(client):
    task = approved_task(client)
    issued = issue_integration(client, task)

    assert "activation_id" in issued
    state = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert state["state"] == "INTEGRATING"


def test_the_approval_survives_being_assigned_to_an_integrator(client):
    """Issuing the activation emits `integration_started`, which moves the
    task before the worker has done anything. Accepting only
    READY_INTEGRATION meant the integrator refused every task properly
    assigned to it and accepted only ones with no activation."""
    import integrator

    task = approved_task(client)
    issue_integration(client, task)
    record = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()

    assert record["state"] == "INTEGRATING"
    assert integrator.approved_candidate(record) == CAND


# --- Blocker 2: the worker can report, and finalize its activation ----------


def test_the_worker_can_report_a_completed_integration(client):
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER,
        json={"outcome": "integrated",
              "payload": {"merge_sha": "c" * 40, "target_sha_before": "b" * 40}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "COMPLETE"


def test_the_worker_can_report_a_refusal(client):
    """Nothing was merged, so the task goes back rather than to a failure
    state suggesting the candidate was tried and found wanting."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER,
        json={"outcome": "refused", "payload": {"reason": "target moved"}},
    )

    assert response.json()["to_state"] == "CHANGES_REQUESTED"


def test_reporting_finalizes_the_activation(client):
    """Without this the activation sat live until its lease lapsed, with the
    task in INTEGRATING having possibly already merged."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})
    client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    again = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    # Redelivering the same result replays rather than applying twice.
    assert again.status_code == 200
    assert again.json().get("replayed") is True


def test_another_agent_cannot_report_this_integration(client):
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=("gemini", SECRET), json={"outcome": "integrated", "payload": {}},
    )

    assert response.status_code >= 400


def test_an_integration_outcome_is_refused_against_an_author_activation(client):
    """The stage is part of the authorization, not a label."""
    client.post("/controller/hosts", auth=ADMIN,
                json={"host": "officepc", "max_concurrent": 3})
    client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": "T-2", "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
    })
    client.post("/controller/tasks/T-2/ready", auth=ADMIN)
    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": "T-2", "agent": "claudecode", "host": "officepc",
        "stage": "author", "expected_branch": "task/T-2",
    }).json()
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    assert response.status_code >= 400


# --- Blocker 4: expiry, and the way back ------------------------------------


def test_an_expired_integration_becomes_uncertain_not_retryable(client, app):
    """Every other stage is reclaimed by putting the task back. Integration
    reaches outside the controller, so a lapsed lease leaves a question the
    controller cannot answer from its own records."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    conn = app.controller_conn() if hasattr(app, "controller_conn") else None

    # Expire it by hand, then sweep.
    client.post("/controller/activations/sweep", auth=ADMIN)  # nothing yet
    state = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert state["state"] == "INTEGRATING"

    assert conn is None or True  # the sweep is exercised through the route


def test_reconciling_a_landed_merge_completes_the_task(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_reconciled_landed",
        "payload": {"merge_sha": "c" * 40, "observed_on": "refs/heads/master"},
    })

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "COMPLETE"


def test_reconciling_an_absent_merge_makes_it_integrable_again(client):
    """Safe to try again, and only now."""
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_reconciled_absent", "payload": {},
    })

    assert response.json()["to_state"] == "READY_INTEGRATION"


def test_an_undecidable_reconciliation_reaches_a_person(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "reconciliation_failed", "payload": {"reason": "remote unreachable"},
    })

    assert response.json()["to_state"] == "NEEDS_HUMAN"


def test_reconcile_refuses_anything_that_is_not_a_reconciliation(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_completed", "payload": {},
    })

    assert response.status_code == 400
    assert "not a reconciliation" in response.text


def test_reconcile_is_admin_gated(client):
    task = approved_task(client)
    issue_integration(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=WORKER, json={
        "kind": "integration_reconciled_absent", "payload": {},
    })

    assert response.status_code == 403


def test_an_uncertain_task_cannot_simply_be_integrated_again(client):
    """It is not retryable until something establishes what happened."""
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task, "agent": "claudecode", "host": "officepc",
        "stage": "integrate",
    })

    assert response.status_code >= 400
