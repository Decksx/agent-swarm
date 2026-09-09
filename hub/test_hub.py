"""Tests for the hub's Phase 0 authentication and control plane.

These need `fastapi`, which the worker suite deliberately does not. Run them
against the scratch venv rather than the system interpreter:

    <venv>/Scripts/python -m pytest hub/test_hub.py -q

`pytest.ini` sets `testpaths = tests`, so a bare `pytest` runs the worker suite
and does not fail here on a missing import.

Every test loads `hub.py` fresh through `importlib`, because the module reads
`HUB_CREDENTIALS` and builds `CREDENTIALS` **at import time**. That is the
behaviour under test for the fail-closed cases, so it cannot be worked around
with a fixture that patches after the fact.
"""

from __future__ import annotations

import base64
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_PATH = Path(__file__).resolve().parent / "hub.py"

CREDS = "admin:admin-secret,claudecode:claude-secret,gemini:gemini-secret"


def basic(name: str, secret: str) -> dict:
    raw = f"{name}:{secret}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def load_hub(monkeypatch, tmp_path, credentials=CREDS):
    """Import hub.py fresh with a given environment and temp storage."""
    if credentials is None:
        monkeypatch.delenv("HUB_CREDENTIALS", raising=False)
    else:
        monkeypatch.setenv("HUB_CREDENTIALS", credentials)

    db = tmp_path / "chat.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "sender TEXT, target TEXT, content TEXT, timestamp REAL)"
    )
    conn.commit()
    conn.close()

    spec = importlib.util.spec_from_file_location("hub_under_test", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_under_test"] = module
    spec.loader.exec_module(module)          # credentials are parsed here

    module.DB_PATH = str(db)
    module.PAUSE_PATH = tmp_path / "control_pause.json"

    return module


@pytest.fixture
def hub(monkeypatch, tmp_path):
    return load_hub(monkeypatch, tmp_path)


@pytest.fixture
def client(hub):
    return TestClient(hub.app)


# --- Fail-closed startup ----------------------------------------------------


def test_missing_credentials_refuses_to_start(monkeypatch, tmp_path):
    """No credential configured means no hub, not an open hub.

    This is the single most important test here. A hub that restarted
    unauthenticated would look identical to a healthy one in the UI, and the
    operator would have no signal that the containment had evaporated.
    """
    with pytest.raises(RuntimeError) as excinfo:
        load_hub(monkeypatch, tmp_path, credentials=None)

    assert "HUB_CREDENTIALS" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad", ["", "   ", "noseparator", "name:", ":secret", ",,,", "name:secret,broken"]
)
def test_malformed_credentials_refuse_to_start(monkeypatch, tmp_path, bad):
    with pytest.raises(RuntimeError):
        load_hub(monkeypatch, tmp_path, credentials=bad)


def test_startup_errors_never_quote_a_secret(monkeypatch, tmp_path):
    """The refusal reaches the container log, so it must be safe to log."""
    secret = "SuperSecretValueThatMustNotLeak"

    with pytest.raises(RuntimeError) as excinfo:
        load_hub(monkeypatch, tmp_path, credentials=f"admin:{secret},broken")

    assert secret not in str(excinfo.value)


# --- Every route requires authentication ------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/"),
        ("get", "/messages"),
        ("post", "/send"),
        ("get", "/control/status"),
        ("post", "/control/pause"),
        ("post", "/control/resume"),
    ],
)
def test_every_route_rejects_an_anonymous_caller(client, method, path):
    # GET takes no body; only the POST routes are given one.
    if method == "post":
        response = client.post(path, json={"target": "@Admin", "content": "x"})
    else:
        response = client.get(path)

    assert response.status_code == 401
    assert "basic" in response.headers.get("www-authenticate", "").lower()


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_documentation_routes_are_gone(client, path):
    """They were three unauthenticated routes publishing the API surface.

    Removed rather than protected: nothing operational reads them, so deleting
    them is a smaller change than authenticating them and leaves less to get
    wrong. 404 here, not 401, because the route no longer exists.
    """
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    "name,secret",
    [
        ("admin", "wrong-secret"),
        ("admin", ""),
        ("nosuchcomponent", "admin-secret"),
        ("", "admin-secret"),
        ("ADMIN", "not-the-secret"),
    ],
)
def test_bad_credentials_are_rejected(client, name, secret):
    assert client.get("/messages", headers=basic(name, secret)).status_code == 401


def test_a_malformed_authorization_header_is_rejected(client):
    for header in (
        {"Authorization": "Basic not-base64!!"},
        {"Authorization": "Bearer admin-secret"},
        {"Authorization": "Basic"},
        {"Authorization": base64.b64encode(b"admin:admin-secret").decode()},
    ):
        assert client.get("/messages", headers=header).status_code == 401


def test_a_valid_credential_is_accepted(client):
    assert client.get("/messages", headers=basic("admin", "admin-secret")).status_code == 200


def test_component_names_are_case_insensitive(client):
    assert client.get("/messages", headers=basic("ADMIN", "admin-secret")).status_code == 200


# --- Identity binding -------------------------------------------------------


def test_the_stored_sender_is_the_authenticated_component(client):
    """A client cannot post as somebody else, however it fills in the body.

    The UI used to hardcode `sender: "Admin"` on every send, so "Admin" in the
    log was never evidence of anything. Now the stored sender is the name whose
    secret verified.
    """
    client.post(
        "/send",
        headers=basic("gemini", "gemini-secret"),
        json={"sender": "Admin", "target": "@ClaudeCode", "content": "spoof attempt"},
    )

    messages = client.get("/messages", headers=basic("admin", "admin-secret")).json()

    assert len(messages) == 1
    assert messages[0]["sender"] == "gemini"
    assert messages[0]["sender"] != "Admin"


def test_an_omitted_sender_is_accepted(client):
    """`sender` is optional now, so a client that stops sending it still works."""
    response = client.post(
        "/send",
        headers=basic("claudecode", "claude-secret"),
        json={"target": "@Admin", "content": "no sender field"},
    )

    assert response.status_code == 200

    messages = client.get("/messages", headers=basic("admin", "admin-secret")).json()
    assert messages[0]["sender"] == "claudecode"


def test_a_supplied_token_field_confers_nothing(client):
    """The old `token` is still accepted by the schema and still means nothing."""
    assert client.post(
        "/send",
        json={"sender": "Admin", "target": "@x", "content": "y", "token": "anything"},
    ).status_code == 401


# --- Control plane ----------------------------------------------------------


def test_status_is_readable_by_any_authenticated_component(client):
    response = client.get("/control/status", headers=basic("gemini", "gemini-secret"))

    assert response.status_code == 200
    body = response.json()
    assert body["paused"] is False
    assert body["you"] == "gemini"


def test_admin_can_pause_and_resume(client):
    paused = client.post(
        "/control/pause",
        headers=basic("admin", "admin-secret"),
        json={"reason": "incident"},
    )
    assert paused.status_code == 200

    status = client.get("/control/status", headers=basic("admin", "admin-secret")).json()
    assert status["paused"] is True
    assert status["pause"]["reason"] == "incident"
    assert status["pause"]["engaged_by"] == "admin"

    client.post("/control/resume", headers=basic("admin", "admin-secret"))
    assert client.get(
        "/control/status", headers=basic("admin", "admin-secret")
    ).json()["paused"] is False


def test_a_non_admin_component_cannot_change_control_state(client):
    """Authenticated is not the same as authorized.

    A worker credential is on every worker on the execution host. If holding
    one were enough to lift a pause, the pause would not be an operator
    control.
    """
    for path in ("/control/pause", "/control/resume"):
        response = client.post(
            path, headers=basic("claudecode", "claude-secret"), json={}
        )
        assert response.status_code == 403


def test_a_pause_survives_a_restart(monkeypatch, tmp_path):
    """The pause is persisted to /data, which is the bind-mounted volume.

    A pause that forgot itself on restart would be worse than none: the
    operator would believe the swarm was held when it was not.
    """
    hub = load_hub(monkeypatch, tmp_path)
    client = TestClient(hub.app)
    client.post(
        "/control/pause", headers=basic("admin", "admin-secret"), json={"reason": "held"}
    )

    # A second import is a restart: fresh module, same /data.
    restarted = load_hub(monkeypatch, tmp_path)
    restarted.PAUSE_PATH = tmp_path / "control_pause.json"
    status = TestClient(restarted.app).get(
        "/control/status", headers=basic("admin", "admin-secret")
    ).json()

    assert status["paused"] is True
    assert status["pause"]["reason"] == "held"


def test_an_unreadable_pause_file_fails_closed(client, hub):
    """Corrupt state reads as paused, not as running."""
    hub.PAUSE_PATH.write_text("{not json", encoding="utf-8")

    status = client.get("/control/status", headers=basic("admin", "admin-secret")).json()

    assert status["paused"] is True
    assert "failing closed" in status["pause"]["reason"]
