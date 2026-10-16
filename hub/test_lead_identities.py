"""Lead identities on the real hub (#109).

`tests/test_lead_chat.py` covers the tool against a fake. These run the same
tool against the hub app itself, so what they pin is the server's half: a lead
post is stored under the credential's name whatever the body claims, it is
never parsed as a chat command, and a lead credential changes no control state.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lead_chat  # noqa: E402
from test_hub import INGRESS_COMMAND, basic, chat_rows, controller_count, load_hub  # noqa: E402

CREDS = ("admin:admin-secret,claudecode:claude-secret,gemini:gemini-secret,"
         "claude-lead:claude-lead-secret,codex-lead:codex-lead-secret")
ENV = {"CLAUDE_LEAD_HUB_SECRET": "claude-lead-secret", "CODEX_LEAD_HUB_SECRET": "codex-lead-secret"}


@pytest.fixture
def hub(monkeypatch, tmp_path):
    monkeypatch.setenv("INGRESS_PROJECTS", "agenthub=C:/git/agent-swarm")
    monkeypatch.setenv("PROGRESSION_VERIFIER", "gemini")
    monkeypatch.setenv("PROGRESSION_INTEGRATOR", "claudecode")
    monkeypatch.setenv("PROGRESSION_HOST", "officepc")
    return load_hub(monkeypatch, tmp_path, credentials=CREDS)


@pytest.fixture
def client(hub):
    return TestClient(hub.app)


def transport_for(client):
    """lead_chat's transport, answered by the app instead of the network."""
    def transport(method, url, headers, body):
        path = url.split("http://hub", 1)[1]
        reply = client.request(method, path, headers=headers, json=body)
        return lead_chat.Response(reply.status_code, reply.json() if reply.content else None)

    return transport


def post(client, identity, content):
    return lead_chat.post(identity, content, url="http://hub", transport=transport_for(client),
                          environ=ENV, user_environment=lambda name: None)


@pytest.mark.parametrize("identity", ["claude-lead", "codex-lead"])
def test_a_lead_post_is_confirmed_and_stored_under_the_leads_name(hub, client, identity):
    receipt = post(client, identity, "HANDOFF @admin: #111 is ready for your decision")

    assert receipt.state == "confirmed", receipt.detail
    assert chat_rows(hub) == [(identity, "@admin", "HANDOFF @admin: #111 is ready for your decision")]


@pytest.mark.parametrize("identity", ["claude-lead", "codex-lead"])
@pytest.mark.parametrize("command", [
    INGRESS_COMMAND,
    "@swarm confirm CMD-0123456789ab",
    "@swarm retry T-1",
    "@swarm cancel T-1 confirm",
])
def test_a_command_shaped_lead_post_is_only_chat(hub, client, identity, command):
    """Leads are not admin components: ingress never parses what they say."""
    receipt = post(client, identity, command)

    assert receipt.state == "confirmed"
    assert [r[0] for r in chat_rows(hub)] == [identity]
    assert controller_count(hub, "task_drafts") == 0
    assert controller_count(hub, "tasks") == 0


def test_a_lead_claiming_to_be_admin_in_the_body_is_still_the_lead(hub, client):
    response = client.post("/send", headers=basic("claude-lead", "claude-lead-secret"),
                           json={"sender": "admin", "target": "@swarm", "content": INGRESS_COMMAND})

    assert response.status_code == 200
    assert [r[0] for r in chat_rows(hub)] == ["claude-lead"]
    assert controller_count(hub, "task_drafts") == 0


@pytest.mark.parametrize("method, path, body", [
    ("post", "/control/pause", {"reason": "x"}),
    ("post", "/control/resume", None),
    ("post", "/controller/tasks", {"task_id": "T-9", "title": "t", "objective": "o",
                                   "base_sha": "0" * 40}),
    ("post", "/controller/external-reviews", {"task_id": "E-9", "project": "agenthub",
                                              "pr_number": 1, "objective": "o"}),
    ("post", "/controller/tasks/advance", None),
])
def test_a_lead_credential_changes_no_control_state(client, method, path, body):
    response = getattr(client, method)(path, headers=basic("codex-lead", "codex-lead-secret"),
                                       json=body)

    assert response.status_code == 403, (path, response.status_code, response.text)


def test_one_leads_secret_does_not_authenticate_the_other(client):
    for name, secret in [("codex-lead", "claude-lead-secret"), ("claude-lead", "codex-lead-secret"),
                         ("admin", "claude-lead-secret"), ("claudecode", "codex-lead-secret")]:
        assert client.get("/messages", headers=basic(name, secret)).status_code == 401


def test_a_lead_reads_handoffs_addressed_to_it(hub, client):
    post(client, "claude-lead", "HANDOFF @codex-lead: review #111 at 1a2b3c4")
    post(client, "codex-lead", "REVIEW @claude-lead: #111 approved")

    addressed = lead_chat.read("codex-lead", only_mentions=True, url="http://hub",
                               transport=transport_for(client), environ=ENV,
                               user_environment=lambda name: None)

    assert [(m["sender"], m["content"]) for m in addressed] == [
        ("claude-lead", "HANDOFF @codex-lead: review #111 at 1a2b3c4")]
