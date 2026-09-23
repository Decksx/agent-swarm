"""The worker fed by the real controller, with nothing hand-built.

Every earlier worker test constructed its own activation dict, and one of them
put a `pr_number` in it that the controller has never produced. The field
looked load-bearing in review precisely because the tests supplied it.

So this claims through the real HTTP route and hands the worker **exactly what
came back**, unmodified. If the controller does not supply something, the
worker does not get it here either, and any dependence on a field that does
not exist shows up as a refusal rather than as a pass.

The merge itself is the only stub: `gh` talks to GitHub, and pointing it at a
real repository would make this a network test. Everything between the claim
and that call is production code.
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

import claude_worker  # noqa: E402
import integrator  # noqa: E402

SECRET = "s" * 32
ADMIN = ("admin", SECRET)
WORKER = ("claudecode", SECRET)

CAND = "1" * 40
MERGE = "3" * 40


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "HUB_CREDENTIALS", f"admin:{SECRET},claudecode:{SECRET},gemini:{SECRET}"
    )
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))

    spec = importlib.util.spec_from_file_location("hub_e2e", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_e2e"] = module
    spec.loader.exec_module(module)

    return module


@pytest.fixture
def client(app):
    with TestClient(app.app) as c:
        yield c


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for name, value in (
        ("INTEGRATION_TARGET_REF", "refs/heads/master"),
        ("INTEGRATION_REPO_SLUG", "owner/repo"),
        ("INTEGRATION_WORK_ROOT", str(tmp_path / "work")),
    ):
        monkeypatch.setenv(name, value)

    # Repository selection has its own tests (test_integration_repo.py). Here
    # only the filesystem and git checks are stubbed; the rule that an
    # activation must name its repository stays real (#78).
    import claude_integration
    monkeypatch.setattr(claude_integration.Path, "is_dir", lambda self: True)
    monkeypatch.setattr(claude_integration, "_git_succeeds", lambda *a: True)


class RealQueue:
    """Reports through the real HTTP routes, counting what it sent."""

    def __init__(self, client):
        self.client = client
        self.author = []
        self.integration = []

    def report(self, activation_id, *, outcome, payload=None):
        self.author.append(outcome)
        return self.client.post(
            f"/controller/activations/{activation_id}/outcome", auth=WORKER,
            json={"outcome": outcome, "payload": payload or {}},
        ).json()

    def report_integration(self, activation_id, *, outcome, payload=None):
        self.integration.append(outcome)
        return self.client.post(
            f"/controller/activations/{activation_id}/integration", auth=WORKER,
            json={"outcome": outcome, "payload": payload or {}},
        ).json()


class NoModel:
    def __getattr__(self, name):
        raise AssertionError(f"a model was reached ({name})")


def approved_task(client, task_id="T-1"):
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
    client.post("/controller/activations/claim", auth=WORKER)
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
    client.post("/controller/activations/claim", auth=("gemini", SECRET))
    client.post(
        f"/controller/activations/{review['activation_id']}/review",
        auth=("gemini", SECRET), json={"judgment": "satisfied"},
    )

    return task_id


def claim_integration(client, task_id):
    """Issue, then claim through the real route, and return exactly what the
    controller handed back plus the task record the client would attach."""
    client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "integrate", "expected_branch": f"task/{task_id}",
        "expected_candidate": CAND, "repo_location": "/repo",
    })

    claimed = client.post(
        "/controller/activations/claim", auth=WORKER
    ).json()["activation"]

    assert claimed is not None, "nothing was claimable"

    # The one thing controller_client adds, fetched from the real route.
    record = client.get(
        f"/controller/tasks/{claimed['task_id']}", auth=ADMIN
    ).json()

    return {**claimed, "task_record": record}


# --- One claim, zero model calls, one merge, one outcome --------------------


def test_the_claim_alone_is_enough_to_integrate(
    client, configured, monkeypatch
):
    """Nothing hand-built. If the controller does not supply it, the worker
    does not get it."""
    merges = {"count": 0, "kwargs": None}

    def one_merge(task, **kw):
        merges["count"] += 1
        merges["kwargs"] = kw
        return {"candidate_sha": CAND, "merge_sha": MERGE,
                "target_ref": "refs/heads/master",
                "target_sha_before": "b" * 40}

    monkeypatch.setattr(integrator, "run_integration", one_merge)

    task = approved_task(client)
    activation = claim_integration(client, task)
    queue = RealQueue(client)

    claude_worker.execute_activation(NoModel(), "claude", activation, queue)

    assert merges["count"] == 1
    assert queue.integration == ["integrated"]
    assert queue.author == []

    final = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert final["state"] == "COMPLETE"


def test_no_pr_number_reaches_the_integrator_from_a_real_claim(
    client, configured, monkeypatch
):
    """The blocker itself. The controller has no such field, so the worker
    must derive the pull request from the branch it was issued against."""
    seen = {}

    def capture(task, **kw):
        seen.update(kw)
        return {"candidate_sha": CAND, "merge_sha": MERGE,
                "target_ref": "refs/heads/master"}

    monkeypatch.setattr(integrator, "run_integration", capture)

    task = approved_task(client)
    activation = claim_integration(client, task)

    assert "pr_number" not in activation
    assert "pr_number" not in activation["task_record"]

    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )

    assert seen["branch"] == f"task/{task}"
    assert "pr_number" not in seen


def test_the_approved_candidate_comes_from_the_ledger(
    client, configured, monkeypatch
):
    seen = {}
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: seen.update(task=task) or {
            "candidate_sha": CAND, "merge_sha": MERGE,
            "target_ref": "refs/heads/master"},
    )

    task = approved_task(client)
    activation = claim_integration(client, task)

    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )

    assert seen["task"]["approved_candidate_sha"] == CAND


def test_a_refusal_reaches_the_controller_and_sends_the_task_back(
    client, configured, monkeypatch
):
    def refuse(task, **kw):
        raise integrator.IntegrationRefused("the target moved; nothing landed")

    monkeypatch.setattr(integrator, "run_integration", refuse)

    task = approved_task(client)
    activation = claim_integration(client, task)
    queue = RealQueue(client)

    claude_worker.execute_activation(NoModel(), "claude", activation, queue)

    assert queue.integration == ["refused"]
    final = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert final["state"] == "CHANGES_REQUESTED"


def test_the_whole_path_runs_with_no_model_available(
    client, configured, monkeypatch
):
    """`NoModel` raises on any attribute access, so reaching a model at all
    fails the test rather than merely being counted."""
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: {"candidate_sha": CAND, "merge_sha": MERGE,
                            "target_ref": "refs/heads/master"},
    )

    task = approved_task(client)
    activation = claim_integration(client, task)

    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )


def test_an_integration_is_recorded_in_the_ledger_with_its_figures(
    client, configured, monkeypatch
):
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: {"candidate_sha": CAND, "merge_sha": MERGE,
                            "target_sha_before": "b" * 40,
                            "target_ref": "refs/heads/master"},
    )

    task = approved_task(client)
    activation = claim_integration(client, task)
    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )

    events = client.get(f"/controller/tasks/{task}/events", auth=ADMIN).json()
    kinds = [e["kind"] for e in events["events"]]

    assert "integration_started" in kinds
    assert "integration_completed" in kinds


# --- A check that could not answer is not a verdict (#78) --------------------


def test_the_repository_comes_from_the_claimed_activation(
    client, configured, monkeypatch
):
    """`repo_location` is recorded at issue and handed over by the claim;
    the worker integrates there and reads no host setting for it."""
    seen = {}

    def capture(task, **kw):
        seen.update(kw)
        return {"candidate_sha": CAND, "merge_sha": MERGE,
                "target_ref": "refs/heads/master"}

    monkeypatch.setattr(integrator, "run_integration", capture)
    monkeypatch.setenv("INTEGRATION_REPO", "/the-production-checkout")

    task = approved_task(client)
    activation = claim_integration(client, task)
    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )

    assert seen["repo"] == "/repo"


def test_an_unverifiable_integration_keeps_the_approval_and_can_be_repaired(
    client, configured, monkeypatch
):
    def cannot_answer(task, **kw):
        raise integrator.IntegrationUnverifiable(
            "git merge-base --is-ancestor exited 128: fatal: not a valid "
            "commit name", detail={"exit_code": 128},
        )

    monkeypatch.setattr(integrator, "run_integration", cannot_answer)

    task = approved_task(client)
    activation = claim_integration(client, task)
    queue = RealQueue(client)
    claude_worker.execute_activation(NoModel(), "claude", activation, queue)

    assert queue.integration == ["unverifiable"]
    blocked = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert blocked["state"] == "INTEGRATION_BLOCKED"
    assert blocked["approved_candidate_sha"] == CAND, (
        "nobody found anything wrong with the candidate; its approval stands"
    )

    events = client.get(f"/controller/tasks/{task}/events", auth=ADMIN).json()
    kinds = [e["kind"] for e in (events.get("events") if isinstance(events, dict) else events)]
    assert "integration_rejected" not in kinds
    assert "integration_blocked" in kinds

    repaired = client.post(f"/controller/tasks/{task}/repair", auth=ADMIN)
    assert repaired.status_code == 200, repaired.text

    ready = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert ready["state"] == "READY_INTEGRATION"
    assert ready["approved_candidate_sha"] == CAND


def test_an_unverifiable_check_after_the_push_is_uncertain(
    client, configured, monkeypatch
):
    def landed_maybe(task, **kw):
        raise integrator.IntegrationUnverifiable("x", after_push=True)

    monkeypatch.setattr(integrator, "run_integration", landed_maybe)

    task = approved_task(client)
    activation = claim_integration(client, task)
    claude_worker.execute_activation(
        NoModel(), "claude", activation, RealQueue(client)
    )

    final = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert final["state"] == "INTEGRATION_UNCERTAIN"
