"""HTTP routes for external-review ingest (#92).

The admin entry route and the dedicated ingest result route, over the router
with a stub authenticator (the same harness as `test_controller_api.py`). The
lifecycle underneath is covered in `tests/test_external_ingest.py`; these pin
what the HTTP layer adds: who may call each route, the status codes, and that
configuration is read per request and fails closed without affecting anything
else.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller import api  # noqa: E402
from test_controller_api import as_, stub_authenticate, stub_require_admin  # noqa: E402

REPO = "C:/git/agent-swarm"
SLUG = "Decksx/agent-swarm"
HEAD = "a" * 40


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INGRESS_PROJECTS", f"agenthub={REPO}")
    monkeypatch.setenv("EXTERNAL_REVIEW_REPOS", f'{{"agenthub": "{SLUG}"}}')
    monkeypatch.setenv("PROGRESSION_HOST", "OFFICEPC")
    monkeypatch.setenv("PROGRESSION_INGESTER", "claudecode")

    db = tmp_path / "controller.db"
    api.ensure_database(str(db))
    app = FastAPI()
    app.include_router(api.build_router(
        authenticate=stub_authenticate, require_admin=stub_require_admin,
        db_path=str(db),
    ))
    test_client = TestClient(app)
    as_(test_client, "admin", "post", "/controller/hosts",
        json={"host": "OFFICEPC", "max_concurrent": 2})
    return test_client


def request_body(**overrides):
    body = {"task_id": "EXT-1", "project": "agenthub", "pr_number": 102,
            "objective": "Review against the criteria"}
    body.update(overrides)
    return body


def task_count(client):
    return sum(as_(client, "admin", "get", "/controller/status").json()["tasks"].values())


def registered():
    text = "body"
    return {
        "schema_version": 1, "project": "agenthub", "repo_location": REPO,
        "repo_slug": SLUG, "repo_id": "0dc8a2e4d227ab03", "pr_number": 102,
        "pr_url": f"https://github.com/{SLUG}/pull/102", "pr_state": "merged",
        "pr_draft": False, "pr_title": "t", "pr_body": text,
        "pr_body_truncated": False,
        "pr_body_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "head_sha": HEAD, "resolved_ref_sha": HEAD, "base_ref_sha": "b" * 40,
        "merge_base": "c" * 40, "pin_ref": "refs/swarm/external/EXT-1",
        "pin_created": True, "changed_files": ["README.md"], "author_signals": [],
    }


def claimed_ingest(client):
    assert as_(client, "admin", "post", "/controller/external-reviews",
               json=request_body()).status_code == 200
    advanced = as_(client, "admin", "post", "/controller/tasks/advance").json()
    assert advanced["considered"][0]["issued"] is True
    claim = as_(client, "claudecode", "post", "/controller/activations/claim",
                json={"stages": ["ingest"]}).json()
    return claim["activation"]


# --- The admin entry route ------------------------------------------------------


def test_an_admin_request_creates_a_pending_external_task(client):
    response = as_(client, "admin", "post", "/controller/external-reviews",
                   json=request_body(at_sha=HEAD))

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "EXTERNAL_PENDING"
    task = as_(client, "admin", "get", "/controller/tasks/EXT-1").json()
    assert task["base_sha"] == "" and task["proof_mode"] == "branch_only"


@pytest.mark.parametrize("agent", ["claudecode", "gemini", "chatgpt"])
def test_only_an_admin_may_request_an_external_review(client, agent):
    response = as_(client, agent, "post", "/controller/external-reviews",
                   json=request_body())

    assert response.status_code == 403
    assert task_count(client) == 0


@pytest.mark.parametrize("overrides", [
    {"project": "unknown"},
    {"pr_number": "102"},
    {"pr_number": -1},
    {"at_sha": "deadbeef"},
    {"objective": ""},
    {"task_id": "has space"},
])
def test_a_bad_request_is_400_and_writes_nothing(client, overrides):
    response = as_(client, "admin", "post", "/controller/external-reviews",
                   json=request_body(**overrides))

    assert response.status_code == 400, response.text
    assert task_count(client) == 0


def test_a_duplicate_task_id_is_409(client):
    as_(client, "admin", "post", "/controller/external-reviews", json=request_body())
    response = as_(client, "admin", "post", "/controller/external-reviews",
                   json=request_body())

    assert response.status_code == 409


@pytest.mark.parametrize("value", ["", "{broken", '{"agenthub": "--help"}', "{}"])
def test_bad_repo_configuration_disables_only_this_route(client, monkeypatch, value):
    monkeypatch.setenv("EXTERNAL_REVIEW_REPOS", value)

    response = as_(client, "admin", "post", "/controller/external-reviews",
                   json=request_body())

    assert response.status_code == 400
    assert "external review" in response.json()["detail"]
    assert task_count(client) == 0
    # Everything else still answers.
    assert as_(client, "admin", "get", "/controller/status").status_code == 200
    assert as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40,
    }).status_code == 200


@pytest.mark.parametrize("base", ["", "abc", "0" * 39, "z" * 40])
def test_the_generic_task_route_requires_a_full_base_sha(client, base):
    response = as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": base,
    })

    assert response.status_code == 400
    assert task_count(client) == 0


def test_external_review_is_still_refused_through_the_generic_transition(client):
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40,
    })
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": "external_review_requested"})

    assert response.status_code == 409
    assert "/controller/external-reviews" in response.json()["detail"]["use"]


# --- Claim and the ingest result route ------------------------------------------


def test_the_claim_carries_the_external_inputs(client):
    activation = claimed_ingest(client)

    assert activation["stage"] == "ingest"
    assert activation["external"]["pin_ref"] == "refs/swarm/external/EXT-1"
    assert activation["external"]["repo_slug"] == SLUG
    assert activation["external"]["pr_number"] == 102


def test_a_valid_report_registers_the_candidate(client):
    activation = claimed_ingest(client)
    response = as_(client, "claudecode", "post",
                   f"/controller/activations/{activation['activation_id']}/ingest",
                   json={"outcome": "registered", "payload": registered()})

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "READY_EXTERNAL_REVIEW"


def test_an_invalid_report_is_422_and_the_activation_stays_live(client):
    activation = claimed_ingest(client)
    path = f"/controller/activations/{activation['activation_id']}/ingest"

    bad = as_(client, "claudecode", "post", path,
              json={"outcome": "registered",
                    "payload": {**registered(), "merge_base": HEAD}})
    assert bad.status_code == 422
    assert "ingest_report_invalid" in bad.json()["detail"]

    good = as_(client, "claudecode", "post", path,
               json={"outcome": "registered", "payload": registered()})
    assert good.status_code == 200, good.text


@pytest.mark.parametrize("bad", [
    # Codex's reproductions on #107 at aaf3ec0: the first was a 200 that
    # registered a candidate no git lookup could find, the next two were 500s.
    {"head_sha": HEAD + "\n", "resolved_ref_sha": HEAD + "\n"},
    {"pr_state": []},
    {"author_signals": [{"kind": [], "value": "x", "source": "pr_body"}]},
    {"repo_id": "0dc8a2e4d227ab03\n"},
    {"pr_number": 102.0},
    {"schema_version": True},
], ids=["newline-sha", "list-state", "list-signal-kind", "newline-repo-id",
        "float-pr-number", "bool-schema"])
def test_a_malformed_report_is_422_records_nothing_and_can_be_corrected(client, bad):
    activation = claimed_ingest(client)
    path = f"/controller/activations/{activation['activation_id']}/ingest"

    refused = as_(client, "claudecode", "post", path,
                  json={"outcome": "registered", "payload": {**registered(), **bad}})
    assert refused.status_code == 422, refused.text

    task = as_(client, "admin", "get", "/controller/tasks/EXT-1").json()
    assert task["state"] == "EXTERNAL_INGESTING"

    corrected = as_(client, "claudecode", "post", path,
                    json={"outcome": "registered", "payload": registered()})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["to_state"] == "READY_EXTERNAL_REVIEW"


@pytest.mark.parametrize("outcome, bad", [
    ("registered", {"pr_title": "t\ud800"}),
    ("registered", {"pr_body": "body\udfff"}),
    ("registered", {"author_signals": [
        {"kind": "pr_body_footer", "value": "Generated with \ud800", "source": "pr_body"}]}),
    ("blocked", {"detail": "gh said \ud800"}),
], ids=["title", "body", "signal", "detail"])
def test_an_escaped_lone_surrogate_is_422_and_can_be_corrected(client, outcome, bad):
    """Codex's reproduction on #107 at f75f10c: ASCII JSON carrying `\\ud800`
    parses to a str that UTF-8 cannot encode, and sizing the report raised
    outside the validation catch -- a 500 the worker retries unchanged."""
    import json

    activation = claimed_ingest(client)
    path = f"/controller/activations/{activation['activation_id']}/ingest"
    base = (registered() if outcome == "registered"
            else {"schema_version": 1, "reason_code": "worker_error", "detail": "d"})
    raw = json.dumps({"outcome": outcome, "payload": {**base, **bad}})  # ASCII-escaped
    assert "\\ud" in raw and raw.isascii()

    refused = client.post(path, content=raw.encode("ascii"), headers={
        "X-Test-Agent": "claudecode", "Content-Type": "application/json"})
    assert refused.status_code == 422, refused.text
    assert "ingest_report_invalid" in refused.content.decode("utf-8")

    task = as_(client, "admin", "get", "/controller/tasks/EXT-1").json()
    assert task["state"] == "EXTERNAL_INGESTING"

    corrected = as_(client, "claudecode", "post", path,
                    json={"outcome": "registered", "payload": registered()})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["to_state"] == "READY_EXTERNAL_REVIEW"


@pytest.mark.parametrize("reason", [["pr_not_found"], {"x": 1}])
@pytest.mark.parametrize("outcome", ["refused", "blocked"])
def test_a_failure_report_with_a_non_string_reason_is_422(client, outcome, reason):
    activation = claimed_ingest(client)
    path = f"/controller/activations/{activation['activation_id']}/ingest"

    response = as_(client, "claudecode", "post", path, json={
        "outcome": outcome,
        "payload": {"schema_version": 1, "reason_code": reason, "detail": "d"},
    })

    assert response.status_code == 422, response.text


def test_the_generic_task_route_refuses_a_newline_terminated_base(client):
    response = as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40 + "\n",
    })

    assert response.status_code == 400
    assert task_count(client) == 0


def test_another_agent_cannot_report_this_ingest(client):
    activation = claimed_ingest(client)
    response = as_(client, "gemini", "post",
                   f"/controller/activations/{activation['activation_id']}/ingest",
                   json={"outcome": "registered", "payload": registered()})

    assert response.status_code == 403


def test_an_unknown_outcome_is_400(client):
    activation = claimed_ingest(client)
    response = as_(client, "claudecode", "post",
                   f"/controller/activations/{activation['activation_id']}/ingest",
                   json={"outcome": "integrated", "payload": registered()})

    assert response.status_code == 400
