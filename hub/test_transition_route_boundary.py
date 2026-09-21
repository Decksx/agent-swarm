"""The generic transition route is not a way around the specialized ones.

`POST /controller/tasks/{id}/transition` applies admin authority to any kind
the state table permits, which made it a second door into the escalation path
with none of its checks. An operator could resume a NEEDS_HUMAN task by
submitting `return_to_author` here: no answer recorded, no check that they
were answering the version they were shown, and no version advance -- so every
attempt authorized before the escalation stayed valid against the decision
that overruled it.

`operator_response` is refused for the mirror reason. Submitted here it
records an answer that resumes nothing, leaving a task that reads as answered
and is still stuck.

The refusals have to change nothing. A route that rejects a request and writes
half of it is worse than one that accepts it, because the ledger then records
a decision nobody can account for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import api, engine, states  # noqa: E402
from controller.db import open_controller_db  # noqa: E402

ADMINS = {"admin", "operator"}


def stub_authenticate(x_test_agent: str = Header(default="")) -> str:
    if not x_test_agent:
        raise HTTPException(status_code=401, detail="authentication required")

    return x_test_agent


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

    made = TestClient(app)
    made.db_path = str(db)

    return made


def as_(client, agent, method, path, **kw):
    return getattr(client, method)(path, headers={"X-Test-Agent": agent}, **kw)


@pytest.fixture
def escalated(client):
    """A task sitting in NEEDS_HUMAN, reached the way the swarm reaches it."""
    as_(client, "admin", "post", "/controller/hosts",
        json={"host": "OFFICEPC", "max_concurrent": 1})
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "pilot", "objective": "o",
        "base_sha": "0" * 40,
    })
    as_(client, "admin", "post", "/controller/tasks/T-1/ready")

    conn = open_controller_db(client.db_path)

    try:
        for kind, actor, authority in (
            ("author_activation_issued", "controller", states.CONTROLLER),
            ("activation_claimed", "chatgpt", states.AUTHOR),
            ("candidate_submitted", "chatgpt", states.AUTHOR),
            ("review_activation_issued", "controller", states.CONTROLLER),
            ("activation_claimed", "gemini", states.VERIFIER),
            ("decision_required", "gemini", states.VERIFIER),
        ):
            engine.apply_transition(
                conn, task_id="T-1", kind=kind, actor=actor,
                authority=authority,
            )
    finally:
        conn.close()

    return "T-1"


def snapshot(client):
    """Every row a refused transition could have touched."""
    conn = open_controller_db(client.db_path)

    try:
        return {
            table: conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
            for table in ("tasks", "task_versions", "activations", "events")
        } | {
            "task": dict(conn.execute(
                "SELECT state, state_seq, current_version FROM tasks "
                "WHERE task_id = 'T-1'"
            ).fetchone()),
        }
    finally:
        conn.close()


ROUTED = sorted(api.ROUTED_ELSEWHERE)


# --- Each refusal ------------------------------------------------------------


@pytest.mark.parametrize("kind", ROUTED)
def test_the_generic_route_refuses_it(client, escalated, kind):
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": kind})

    assert response.status_code == 409, response.text


@pytest.mark.parametrize("kind", ROUTED)
def test_the_refusal_names_the_route_to_use(client, escalated, kind):
    """A refusal that does not say where to go is a dead end."""
    detail = as_(
        client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": kind},
    ).json()["detail"]

    assert detail["kind"] == kind
    assert detail["use"]


def test_the_contract_version_refusal_names_the_fields_it_needs(client,
                                                                escalated):
    detail = as_(
        client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": "create_contract_version"},
    ).json()["detail"]

    for field in ("contract_yaml", "base_sha", "proof_mode"):
        assert field in detail["use"], field


@pytest.mark.parametrize("kind", ROUTED)
def test_a_refusal_changes_no_row_at_all(client, escalated, kind):
    """Not the task, not its version, not an activation, not an event."""
    before = snapshot(client)

    as_(client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": kind})

    assert snapshot(client) == before


@pytest.mark.parametrize("kind", ROUTED)
def test_a_refusal_leaves_the_task_asking(client, escalated, kind):
    as_(client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": kind})

    state = as_(client, "admin", "get", "/controller/tasks/T-1").json()

    assert state["state"] == "NEEDS_HUMAN"
    assert state["current_version"] == 1


@pytest.mark.parametrize("kind", ROUTED)
def test_a_refusal_appends_no_event(client, escalated, kind):
    before = as_(
        client, "admin", "get", "/controller/tasks/T-1/events"
    ).json()["events"]

    as_(client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": kind})

    after = as_(
        client, "admin", "get", "/controller/tasks/T-1/events"
    ).json()["events"]

    assert [e["event_id"] for e in after] == [e["event_id"] for e in before]


@pytest.mark.parametrize("kind", ROUTED)
def test_whitespace_does_not_get_a_kind_past_the_refusal(client, escalated, kind):
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": f"  {kind}  "})

    assert response.status_code == 409


# --- What stays generic ------------------------------------------------------


def test_cancellation_still_works_through_the_generic_route(client, escalated):
    """Terminal, carries no evidence, and invalidates nothing that needed
    carrying."""
    response = as_(client, "admin", "post", "/controller/tasks/T-1/transition",
                   json={"kind": "admin_cancelled",
                         "payload": {"reason": "no longer wanted"}})

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "CANCELLED"


def test_the_refused_set_is_exactly_what_has_a_route_of_its_own(client):
    """Stated so that widening it is a decision rather than a drift.

    Widened twice, deliberately. The first five are the escalation exits.
    `out_of_band_merge_reported` (#26) is not an escalation exit and is refused
    here for the same underlying reason: it has a route that checks the task
    carries an approval before a report can move it into the state that trusts
    reports, and applied generically it arrives with none of that.
    `reconciliation_observation` (#57) is refused because its `source_event_id`
    is the whole of its meaning -- emitted here it would record what somebody
    says they saw, attached to no reconciliation at all.
    """
    assert set(api.ROUTED_ELSEWHERE) == {
        "operator_response",
        "return_to_author",
        "return_to_review",
        "admin_failed",
        "create_contract_version",
        "out_of_band_merge_reported",
        "reconciliation_observation",
    }
    assert "admin_cancelled" not in api.ROUTED_ELSEWHERE
    assert "superseded" not in api.ROUTED_ELSEWHERE


# --- The specialized route still works ---------------------------------------


def test_the_operator_response_route_is_unaffected(client, escalated):
    """The refusals must close a bypass, not the path itself."""
    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "require sabotage mode",
              "action": "return_to_author"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "READY_AUTHOR"
    assert response.json()["task_version"] == 2


def test_the_bypass_would_have_skipped_the_version_advance(client, escalated):
    """What the bypass actually cost, stated as a test.

    Going through the route advances the version, which is what invalidates
    attempts authorized before the escalation. The generic route left it
    where it was.
    """
    as_(client, "admin", "post", "/controller/tasks/T-1/transition",
        json={"kind": "return_to_author"})

    assert as_(client, "admin", "get",
               "/controller/tasks/T-1").json()["current_version"] == 1

    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go", "action": "return_to_author"})

    assert as_(client, "admin", "get",
               "/controller/tasks/T-1").json()["current_version"] == 2
