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

# hub.py imports the controller package, which lives one directory up. In the
# container the application directory is the working directory and this is
# implicit; here it has to be arranged.
sys.path.insert(0, str(HUB_PATH.parent.parent))

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

    # hub.py creates the controller schema at import, so it needs a writable
    # path before the module is loaded rather than after. Without this it would
    # reach for /data/controller.db, which does not exist off the container.
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))

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


# --- Cross-identity: a credential must authenticate exactly one name --------

# Four components, all with distinct secrets, matching the deployed set. The
# module-level CREDS has no chatgpt entry and other tests assert on the
# component list it produces, so this is kept separate rather than widened.
FOUR = (
    "admin:admin-secret-1,"
    "claudecode:claude-secret-2,"
    "chatgpt:chatgpt-secret-3,"
    "gemini:gemini-secret-4"
)

FOUR_SECRETS = {
    "admin": "admin-secret-1",
    "claudecode": "claude-secret-2",
    "chatgpt": "chatgpt-secret-3",
    "gemini": "gemini-secret-4",
}


@pytest.fixture
def four_client(monkeypatch, tmp_path):
    """A hub with the four deployed component names and distinct secrets."""
    return TestClient(load_hub(monkeypatch, tmp_path, credentials=FOUR).app)


def test_a_secret_cannot_borrow_another_components_name(four_client):
    """Every credential authenticates its own name and no other.

    authenticate() reads the component name from the Basic *username*, so the
    name is chosen by the caller and the secret is the only thing binding it.
    That makes "can a worker present a valid secret under a different valid
    name" the question identity separation actually rests on -- an unknown name
    with a valid secret (covered above) is a weaker case, because a
    non-existent component has no authority to borrow.

    All twelve ordered cross pairs are asserted rather than a sample, so a
    future change that special-cases one component cannot pass this by luck.
    """
    checked = 0

    for owner, secret in FOUR_SECRETS.items():
        for name in FOUR_SECRETS:
            response = four_client.get("/messages", headers=basic(name, secret))

            if name == owner:
                assert response.status_code == 200, f"{owner} rejected by its own name"
            else:
                assert response.status_code == 401, (
                    f"{owner}'s secret authenticated as {name}"
                )
                checked += 1

    assert checked == 12, "expected every ordered cross pair to be exercised"


@pytest.mark.parametrize("name", ["gemini", "claudecode", "admin"])
def test_the_chatgpt_secret_authenticates_as_nobody_else(four_client, name):
    """Named explicitly because it is the case the review asked to see."""
    assert four_client.get(
        "/messages", headers=basic(name, FOUR_SECRETS["chatgpt"])
    ).status_code == 401


def test_a_worker_secret_cannot_reach_admin_authority_by_renaming(four_client):
    """Control state is admin-only, and admin is a credential rather than a name.

    A worker that could pause or resume the swarm by presenting its own secret
    under the username "admin" would hold the operator's stop button. It is
    refused at authentication, before require_admin is ever consulted.
    """
    for secret in (FOUR_SECRETS["gemini"], FOUR_SECRETS["chatgpt"], FOUR_SECRETS["claudecode"]):
        assert four_client.post(
            "/control/pause", headers=basic("admin", secret), json={"reason": "x"}
        ).status_code == 401

        assert four_client.post(
            "/control/resume", headers=basic("admin", secret)
        ).status_code == 401

    # Still working for the component that really holds it, so the assertions
    # above are about identity and not about the route being broken.
    assert four_client.post(
        "/control/pause",
        headers=basic("admin", FOUR_SECRETS["admin"]),
        json={"reason": "still works"},
    ).status_code == 200


def test_components_sharing_a_secret_authenticate_as_each_other(monkeypatch, tmp_path):
    """The hazard, asserted, because it is a property of configuration.

    This is a characterization test: it documents that the hub *cannot* enforce
    identity separation on its own. Two components configured with the same
    secret each authenticate as the other, and every individual request is
    perfectly valid, so there is nothing for the server to detect or refuse.

    Isolation therefore has to be checked against the deployed credential set
    from outside, which is what `hub/auth_matrix.py` does. If this test ever
    fails, the hub has grown a defence it did not have and auth_matrix.py's
    reason for existing should be re-read rather than the test repaired.
    """
    shared = TestClient(
        load_hub(
            monkeypatch,
            tmp_path,
            credentials="admin:same-secret,gemini:same-secret",
        ).app
    )

    assert shared.get("/messages", headers=basic("admin", "same-secret")).status_code == 200
    assert shared.get("/messages", headers=basic("gemini", "same-secret")).status_code == 200

    # And the impersonation is complete, not partial: the stored sender is
    # whichever name was typed.
    shared.post(
        "/send",
        headers=basic("admin", "same-secret"),
        json={"target": "@x", "content": "posted by a gemini credential"},
    )

    messages = shared.get("/messages", headers=basic("admin", "same-secret")).json()
    assert messages[0]["sender"] == "admin"


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


# --- The UI template --------------------------------------------------------


def test_the_ui_escapes_sender_and_target(client):
    """Regression guard for a stored XSS in the live terminal.

    `content` was escaped from the start; `sender` and `target` were
    interpolated raw into innerHTML. Since anyone on the LAN could choose the
    sender, a message from `<img src=x onerror=...>` executed script in the
    browser of whoever was watching.

    Asserted against the served template rather than a rendered page, because
    there is no browser here. The negative assertions are the load-bearing
    half: it is easy to add an escaped copy and leave the raw one in place.
    """
    page = client.get("/", headers=basic("admin", "admin-secret")).text

    assert "escapeHtml(String(msg.sender))" in page
    assert "escapeHtml(String(msg.target))" in page

    assert "${msg.sender}" not in page
    assert "${msg.target}" not in page


def test_the_ui_class_name_is_built_from_an_allowlist(client):
    """A class attribute is not text, so it is stripped rather than escaped."""
    page = client.get("/", headers=basic("admin", "admin-secret")).text

    assert "replace(/[^A-Za-z0-9_-]/g, '')" in page


def test_the_ui_no_longer_claims_to_be_admin(client):
    """The page used to hardcode sender: 'Admin' on every send."""
    page = client.get("/", headers=basic("admin", "admin-secret")).text

    assert "sender: 'Admin'" not in page


# --- Chat-command ingress ------------------------------------------------------

INGRESS_BASE = "6edf2a1a6e9d4ca2633944fd1e2f6eaeb9e818e7"
INGRESS_COMMAND = (
    "@swarm Show stage filters on the status page\n"
    "project: agenthub\n"
    f"base: {INGRESS_BASE}\n"
    "paths: hub/hub.py\n"
    "\n"
    "Add the applied claim stages to the status page."
)


@pytest.fixture
def ingress_env(monkeypatch):
    monkeypatch.setenv("INGRESS_PROJECTS", "agenthub=C:/git/agent-swarm")
    monkeypatch.setenv("PROGRESSION_VERIFIER", "gemini")
    monkeypatch.setenv("PROGRESSION_INTEGRATOR", "claudecode")
    monkeypatch.setenv("PROGRESSION_HOST", "officepc")


def chat_rows(hub):
    conn = sqlite3.connect(hub.DB_PATH)
    try:
        return conn.execute("SELECT sender, target, content FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()


def controller_count(hub, table):
    conn = sqlite3.connect(hub.CONTROLLER_DB)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_an_admin_command_is_stored_then_answered_by_the_controller(hub, client, ingress_env):
    response = client.post("/send", json={"target": "@swarm", "content": INGRESS_COMMAND},
                           headers=basic("admin", "admin-secret"))

    assert response.status_code == 200
    assert set(response.json()) == {"status", "id"}
    rows = chat_rows(hub)
    assert [r[0] for r in rows] == ["admin", "controller"]
    assert rows[1][1] == "@Admin" and rows[1][2].startswith("Draft CMD-")
    assert "@swarm confirm CMD-" in rows[1][2]
    assert controller_count(hub, "task_drafts") == 1
    assert controller_count(hub, "tasks") == 0


def test_a_worker_posting_the_same_text_is_only_chat(hub, client, ingress_env):
    client.post("/send", json={"target": "@swarm", "content": INGRESS_COMMAND},
                headers=basic("claudecode", "claude-secret"))

    assert [r[0] for r in chat_rows(hub)] == ["claudecode"]
    assert controller_count(hub, "task_drafts") == 0


def test_ordinary_admin_chat_gets_no_reply(hub, client, ingress_env):
    client.post("/send", json={"target": "@Gemini", "content": "thanks, looks good"},
                headers=basic("admin", "admin-secret"))

    assert [r[0] for r in chat_rows(hub)] == ["admin"]


def test_a_confirmation_through_the_route_creates_one_task_even_when_resent(hub, client, ingress_env):
    headers = basic("admin", "admin-secret")
    client.post("/send", json={"target": "@swarm", "content": INGRESS_COMMAND}, headers=headers)
    draft_id = next(t for t in chat_rows(hub)[1][2].split() if t.startswith("CMD-"))
    conn = sqlite3.connect(hub.CONTROLLER_DB)
    conn.execute("INSERT OR REPLACE INTO host_capacity (host, max_concurrent) VALUES ('officepc', 3)")
    conn.commit()
    conn.close()

    for _ in range(2):
        client.post("/send", json={"target": "@swarm", "content": f"@swarm confirm {draft_id}"}, headers=headers)

    replies = [r[2] for r in chat_rows(hub) if r[0] == "controller"]
    assert replies[1].startswith(f"Confirmed {draft_id} as T-{draft_id}")
    assert replies[2].startswith(f"{draft_id} was already confirmed")
    assert controller_count(hub, "tasks") == 1
    assert controller_count(hub, "activations") == 1


def test_an_ingress_failure_is_reported_in_chat_not_as_a_500(hub, client, ingress_env, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("controller unavailable")

    monkeypatch.setattr(hub.controller_ingress, "handle_message", broken)

    response = client.post("/send", json={"target": "@swarm", "content": INGRESS_COMMAND},
                           headers=basic("admin", "admin-secret"))

    assert response.status_code == 200
    reply = chat_rows(hub)[-1]
    assert reply[0] == "controller" and "RuntimeError: controller unavailable" in reply[2]
