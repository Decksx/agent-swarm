"""The two routes narration needs, and the authority each one carries.

One is read-only and the narrator may use it. The other resumes a task and the
narrator may not touch it. That split is the whole security story of this
slice: the room is where questions are asked, and it is not where answers
acquire authority. Chat carried unauthenticated remote execution before Phase
0, and a reply path that reached the resume route would hand that back with
better manners.
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

# Mirrors the hub's own ADMIN_COMPONENTS. `narrator` is deliberately not in it.
ADMINS = {"admin", "operator"}

COMPONENTS = ["admin", "operator", "narrator", "gemini", "chatgpt", "claudecode"]


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
def task(client):
    as_(client, "admin", "post", "/controller/hosts",
        json={"host": "OFFICEPC", "max_concurrent": 1})
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "pilot", "objective": "o",
        "base_sha": "0" * 40,
    })
    as_(client, "admin", "post", "/controller/tasks/T-1/ready")

    return "T-1"


# READY_AUTHOR -> ... -> REVIEWING -> NEEDS_HUMAN, with the authority each
# step actually carries. Driven through the engine rather than the transition
# route because that route applies admin authority only, and `decision_required`
# belongs to the verifier -- which is the point: an escalation is something the
# swarm raises, not something an operator can declare on its behalf.
ESCALATION = [
    ("author_activation_issued", "controller", states.CONTROLLER),
    ("activation_claimed", "chatgpt", states.AUTHOR),
    ("candidate_submitted", "chatgpt", states.AUTHOR),
    ("review_activation_issued", "controller", states.CONTROLLER),
    ("activation_claimed", "gemini", states.VERIFIER),
    ("decision_required", "gemini", states.VERIFIER),
]


def escalate(client, task_id):
    """Drive a task into NEEDS_HUMAN the way the swarm does."""
    conn = open_controller_db(client.db_path)

    try:
        for kind, actor, authority in ESCALATION:
            payload = (
                {"question": "approve the weaker proof?"}
                if kind == "decision_required" else {}
            )
            outcome = engine.apply_transition(
                conn, task_id=task_id, kind=kind, actor=actor,
                authority=authority, payload=payload,
            )
    finally:
        conn.close()

    assert outcome["to_state"] == "NEEDS_HUMAN", outcome


def escalate_from_review(client, task_id):
    """READY_REVIEW -> NEEDS_HUMAN again, for a task escalated twice."""
    conn = open_controller_db(client.db_path)

    try:
        for kind, actor, authority in (
            ("review_activation_issued", "controller", states.CONTROLLER),
            ("activation_claimed", "gemini", states.VERIFIER),
            ("decision_required", "gemini", states.VERIFIER),
        ):
            outcome = engine.apply_transition(
                conn, task_id=task_id, kind=kind, actor=actor,
                authority=authority,
                payload={"question": "again?"} if kind == "decision_required" else {},
            )
    finally:
        conn.close()

    assert outcome["to_state"] == "NEEDS_HUMAN", outcome


def state_of(client, task_id):
    return as_(client, "admin", "get", f"/controller/tasks/{task_id}").json()


# --- The feed ----------------------------------------------------------------


def test_the_feed_reports_the_maximum_without_returning_events(client, task):
    body = as_(client, "narrator", "get", "/controller/events").json()

    assert body["events"] == []
    assert body["max_seq"] > 0


def test_the_maximum_is_authoritative_rather_than_the_end_of_a_page(
    client, task
):
    """A narrator seeding from a page tail would start at the end of its first
    page and replay everything after it into the room."""
    full = as_(client, "narrator", "get", "/controller/events?since=0").json()
    paged = as_(
        client, "narrator", "get", "/controller/events?since=0&limit=1"
    ).json()

    assert len(paged["events"]) == 1
    assert paged["max_seq"] == full["max_seq"]
    assert paged["max_seq"] > paged["events"][-1]["seq"]


def test_events_come_back_oldest_first(client, task):
    body = as_(client, "narrator", "get", "/controller/events?since=0").json()
    sequences = [e["seq"] for e in body["events"]]

    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def test_since_excludes_what_has_already_been_delivered(client, task):
    everything = as_(
        client, "narrator", "get", "/controller/events?since=0"
    ).json()["events"]
    cut = everything[0]["seq"]

    rest = as_(
        client, "narrator", "get", f"/controller/events?since={cut}"
    ).json()["events"]

    assert all(e["seq"] > cut for e in rest)


def test_a_page_is_bounded_and_the_bound_is_capped(client, task):
    one = as_(
        client, "narrator", "get", "/controller/events?since=0&limit=1"
    ).json()
    huge = as_(
        client, "narrator", "get", "/controller/events?since=0&limit=100000"
    ).json()

    assert len(one["events"]) == 1
    assert len(huge["events"]) <= 500


def test_an_event_carries_what_a_narration_line_needs(client, task):
    body = as_(client, "narrator", "get", "/controller/events?since=0").json()
    event = body["events"][0]

    for field in ("seq", "task_id", "task_version", "actor", "kind",
                  "from_state", "to_state", "payload_json", "created_at"):
        assert field in event, field

    assert isinstance(event["payload_json"], dict)


def test_the_next_cursor_is_the_last_sequence_returned(client, task):
    body = as_(
        client, "narrator", "get", "/controller/events?since=0&limit=2"
    ).json()

    assert body["next_since"] == body["events"][-1]["seq"]


def test_an_empty_page_leaves_the_cursor_where_it_was(client, task):
    top = as_(client, "narrator", "get", "/controller/events").json()["max_seq"]
    body = as_(
        client, "narrator", "get", f"/controller/events?since={top}"
    ).json()

    assert body["events"] == []
    assert body["next_since"] == top


# --- Authorization matrix ----------------------------------------------------


@pytest.mark.parametrize("component", COMPONENTS)
def test_every_authenticated_component_may_read_the_feed(client, task, component):
    """Read-only and harmless. The narrator needs it; nobody is harmed by it."""
    assert as_(client, component, "get", "/controller/events").status_code == 200


def test_an_unauthenticated_caller_may_not_read_the_feed(client, task):
    assert client.get("/controller/events").status_code == 401


@pytest.mark.parametrize("component", ["narrator", "gemini", "chatgpt",
                                       "claudecode"])
def test_a_non_admin_may_not_answer_an_escalation(client, task, component):
    """The narrator can say that a question was asked. It cannot answer one."""
    escalate(client, task)

    response = as_(
        client, component, "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead",
              "action": "return_to_review"},
    )

    assert response.status_code == 403
    assert state_of(client, "T-1")["state"] == "NEEDS_HUMAN"


def test_an_unauthenticated_caller_may_not_answer_an_escalation(client, task):
    escalate(client, task)

    response = client.post(
        "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead",
              "action": "return_to_review"},
    )

    assert response.status_code == 401
    assert state_of(client, "T-1")["state"] == "NEEDS_HUMAN"


@pytest.mark.parametrize("component", sorted(ADMINS))
def test_an_admin_may_answer_an_escalation(client, task, component):
    escalate(client, task)

    response = as_(
        client, component, "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead",
              "action": "return_to_review"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answered_by"] == component


def test_the_narrator_gains_no_admin_authority_anywhere(client, task):
    """The one property the whole split rests on."""
    for path, payload in (
        ("/controller/tasks/T-1/ready", None),
        ("/controller/tasks/T-1/transition", {"kind": "author_activation_issued"}),
        ("/controller/hosts", {"host": "X", "max_concurrent": 1}),
        ("/controller/tasks/advance", None),
        ("/controller/activations/sweep", None),
    ):
        response = as_(
            client, "narrator", "post", path,
            **({"json": payload} if payload is not None else {}),
        )

        assert response.status_code == 403, f"{path} -> {response.status_code}"


# --- The response is one transaction, and it is strict -----------------------


def test_a_response_requires_the_task_to_be_asking(client, task):
    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead",
              "action": "return_to_review"},
    )

    assert response.status_code == 409
    assert "NEEDS_HUMAN" not in str(response.json()["detail"].get("state"))


def test_a_stale_version_is_refused_rather_than_applied(client, task):
    """An operator reading a question in the room may be answering something
    the swarm has already moved past."""
    escalate(client, task)

    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 99, "response": "go ahead",
              "action": "return_to_review"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["current_version"] == 1
    assert state_of(client, "T-1")["state"] == "NEEDS_HUMAN"


@pytest.mark.parametrize("action", [
    "", "resume", "continue", "do_the_thing", "admin_cancelled",
])
def test_an_unsupported_resume_action_is_refused(client, task, action):
    """Never guess author versus review. Two different instructions."""
    escalate(client, task)

    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead", "action": action},
    )

    assert response.status_code == 422
    assert state_of(client, "T-1")["state"] == "NEEDS_HUMAN"


def test_create_contract_version_is_refused_and_says_why(client, task):
    """A real exit that needs a contract. Free text is not a contract, and
    accepting it would mint a version whose contract was guessed."""
    escalate(client, task)

    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "rewrite the contract",
              "action": "create_contract_version"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "create_contract_version" in detail["unsupported_here"]
    assert "contract_yaml" in detail["unsupported_here"]["create_contract_version"]


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_response_is_refused(client, task, text):
    escalate(client, task)

    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": text,
              "action": "return_to_review"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("action,expected", [
    ("return_to_author", "READY_AUTHOR"),
    ("return_to_review", "READY_REVIEW"),
    ("admin_failed", "FAILED"),
])
def test_each_supported_action_applies_its_own_transition(
    client, task, action, expected
):
    escalate(client, task)

    response = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "do this", "action": action},
    )

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == expected
    assert state_of(client, "T-1")["state"] == expected


def test_answering_advances_the_task_version(client, task):
    """What invalidates everything in flight against the old one."""
    escalate(client, task)
    before = state_of(client, "T-1")["current_version"]

    body = as_(
        client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": before, "response": "go",
              "action": "return_to_review"},
    ).json()

    assert body["task_version"] == before + 1
    assert state_of(client, "T-1")["current_version"] == before + 1


def test_the_same_answer_cannot_be_applied_twice(client, task):
    """The version it was written against is gone, so the replay is stale."""
    escalate(client, task)
    payload = {"expected_version": 1, "response": "go",
               "action": "return_to_review"}

    first = as_(client, "admin", "post",
                "/controller/tasks/T-1/operator-response", json=payload)
    second = as_(client, "admin", "post",
                 "/controller/tasks/T-1/operator-response", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409


def test_the_response_and_the_resume_are_both_in_the_log(client, task):
    """Recorded before the resume, so the log reads in the order it happened."""
    escalate(client, task)
    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "go ahead",
              "action": "return_to_review"})

    kinds = [
        e["kind"] for e in
        as_(client, "admin", "get", "/controller/tasks/T-1/events").json()["events"]
    ]

    assert "operator_response" in kinds
    assert "return_to_review" in kinds
    assert kinds.index("operator_response") < kinds.index("return_to_review")


def test_a_refused_response_writes_nothing_at_all(client, task):
    """One transaction: a refusal leaves no half-applied answer behind."""
    escalate(client, task)
    before = as_(
        client, "admin", "get", "/controller/tasks/T-1/events"
    ).json()["events"]

    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 99, "response": "go",
              "action": "return_to_review"})

    after = as_(
        client, "admin", "get", "/controller/tasks/T-1/events"
    ).json()["events"]

    assert len(after) == len(before)
    assert state_of(client, "T-1")["current_version"] == 1


def test_answering_a_task_that_does_not_exist_is_a_404(client):
    response = as_(
        client, "admin", "post", "/controller/tasks/NOPE/operator-response",
        json={"expected_version": 1, "response": "go",
              "action": "return_to_review"},
    )

    assert response.status_code == 404


# --- The answer reaches the next activation, not just the log ----------------


def test_the_answer_is_carried_into_the_next_activation(client, task):
    """Copied into the activation, not left to be reconstructed.

    A worker that had to query the event log for its own instructions would be
    deciding for itself which event counted and what "latest" meant. Recording
    an answer and calling the worker informed is the same mistake as recording
    an approval and calling a candidate approved.
    """
    escalate(client, task)
    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "require sabotage mode",
              "action": "return_to_author"})

    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "chatgpt", "host": "OFFICEPC",
        "role": "author", "stage": "author",
    })
    claimed = as_(client, "chatgpt", "post", "/controller/activations/claim",
                  json={"agent": "chatgpt"}).json()

    carried = claimed["activation"]["operator_context"]

    assert carried is not None, "the worker was handed no operator context"
    assert carried["response"] == "require sabotage mode"
    assert carried["action"] == "return_to_author"
    assert carried["actor"] == "admin"
    assert carried["task_version"] == 2
    assert isinstance(carried["event_seq"], int)


def test_the_carried_answer_is_not_merely_recoverable_from_history(client, task):
    """The assertion is about the activation's own inputs.

    If this passed only because the event exists somewhere in the log, it
    would pass with the column empty. It is read from the claim response,
    which is everything the worker is given.
    """
    escalate(client, task)
    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "hold for the next slice",
              "action": "return_to_review"})

    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "gemini", "host": "OFFICEPC",
        "role": "verifier", "stage": "review",
        # A review activation must name what to review; the controller refuses
        # to issue one a reviewer could not act on.
        "expected_branch": "candidate/T-1", "expected_parent": "1" * 40,
        "expected_candidate": "2" * 40, "repo_location": "C:/git/demo",
    })
    claimed = as_(client, "gemini", "post", "/controller/activations/claim",
                  json={"agent": "gemini"}).json()

    carried = claimed["activation"]["operator_context"]

    assert set(carried) == {
        "response", "action", "actor", "event_seq", "task_version",
    }
    assert carried["response"] == "hold for the next slice"


def test_an_activation_with_no_outstanding_answer_carries_none(client, task):
    """The ordinary case. An empty field rather than a stale one."""
    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "chatgpt", "host": "OFFICEPC",
        "role": "author", "stage": "author",
    })
    claimed = as_(client, "chatgpt", "post", "/controller/activations/claim",
                  json={"agent": "chatgpt"}).json()

    assert claimed["activation"]["operator_context"] is None


def test_a_superseded_answer_is_not_carried_forward(client, task):
    """Tied to the version it produced, not to recency.

    A task escalated twice has two answers in its log, and an activation
    carrying the older one would be acting on an instruction the operator has
    already replaced.
    """
    escalate(client, task)
    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 1, "response": "first answer",
              "action": "return_to_review"})

    # The task moves on past the version that answer produced, and is
    # escalated a second time -- through the engine, because raising an
    # escalation is the verifier's to do and not an operator's.
    escalate_from_review(client, "T-1")
    as_(client, "admin", "post", "/controller/tasks/T-1/operator-response",
        json={"expected_version": 2, "response": "second answer",
              "action": "return_to_review"})

    as_(client, "admin", "post", "/controller/activations", json={
        "task_id": "T-1", "agent": "gemini", "host": "OFFICEPC",
        "role": "verifier", "stage": "review",
        # A review activation must name what to review; the controller refuses
        # to issue one a reviewer could not act on.
        "expected_branch": "candidate/T-1", "expected_parent": "1" * 40,
        "expected_candidate": "2" * 40, "repo_location": "C:/git/demo",
    })
    claimed = as_(client, "gemini", "post", "/controller/activations/claim",
                  json={"agent": "gemini"}).json()

    assert claimed["activation"]["operator_context"]["response"] == "second answer"
