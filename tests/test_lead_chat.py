"""The interactive leads' chat tool (#109): its own credential, a read-back
receipt, and never a blind resend.

These run against a fake hub. `hub/test_lead_identities.py` runs the same tool
against the real hub app to pin what the server adds: the stored sender, and
that a lead's message is never parsed as a command.
"""

from __future__ import annotations

import base64
import io

import pytest

import lead_chat
from lead_chat import LeadChatError, Response

ENV = {"CLAUDE_LEAD_HUB_SECRET": "claude-lead-secret", "CODEX_LEAD_HUB_SECRET": "codex-lead-secret"}
NO_USER_ENV = lambda name: None  # noqa: E731


class FakeHub:
    """Stores what is sent and serves it back; a scripted fault per call."""

    def __init__(self, faults=None):
        self.messages = []
        self.calls = []
        self.faults = list(faults or [])

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        fault = self.faults.pop(0) if self.faults else None

        if isinstance(fault, Exception):
            raise fault
        if isinstance(fault, Response):
            return fault

        name = base64.b64decode(headers["Authorization"].split()[1]).decode().split(":")[0]

        if method == "POST":
            message = {"id": len(self.messages) + 1, "sender": fault or name,
                       "target": body["target"], "content": body["content"]}
            self.messages.append(message)
            return Response(200, {"status": "ok", "id": message["id"]})

        since = int(url.split("since_id=")[1])
        return Response(200, [m for m in self.messages if m["id"] > since])

    @property
    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def post(hub, content="HANDOFF @codex-lead: review #111 at 1a2b3c4", identity="claude-lead", **kw):
    return lead_chat.post(identity, content, url="http://hub", transport=hub,
                          environ=kw.pop("environ", ENV), user_environment=NO_USER_ENV, **kw)


# --- Identity: its own credential, never another's ---------------------------


def test_a_post_uses_the_named_leads_own_credential():
    hub = FakeHub()
    post(hub)

    auth = hub.posts[0][2]["Authorization"].split()[1]
    assert base64.b64decode(auth).decode() == "claude-lead:claude-lead-secret"
    assert "sender" not in hub.posts[0][3]


@pytest.mark.parametrize("identity", ["admin", "claudecode", "operator", "Claude-Lead ", ""])
def test_only_an_allowlisted_lead_identity_may_post(identity):
    hub = FakeHub()

    with pytest.raises(LeadChatError, match="not a lead identity"):
        post(hub, identity=identity)

    assert hub.calls == []


def test_a_missing_lead_secret_never_falls_back_to_another_credential():
    """A worker's or the operator's secret in the same shell is not a lead's."""
    hub = FakeHub()
    environ = {"HUB_SECRET": "worker", "CLAUDE_HUB_SECRET": "worker",
               "ADMIN_HUB_SECRET": "admin", "CODEX_LEAD_HUB_SECRET": "codex"}

    with pytest.raises(LeadChatError, match="CLAUDE_LEAD_HUB_SECRET is not set"):
        post(hub, environ=environ)

    assert hub.calls == []


def test_a_secret_installed_after_the_shell_started_is_found():
    hub = FakeHub()
    receipt = lead_chat.post("codex-lead", "REVIEW #111@1a2b3c4: approved", url="http://hub",
                             transport=hub, environ={},
                             user_environment={"CODEX_LEAD_HUB_SECRET": "late"}.get)

    assert receipt.state == "confirmed"
    assert base64.b64decode(hub.posts[0][2]["Authorization"].split()[1]).decode() == "codex-lead:late"


# --- Receipt: confirmed only by reading the stored row back ------------------


def test_a_post_is_confirmed_by_reading_its_id_back():
    hub = FakeHub()
    receipt = post(hub)

    assert (receipt.state, receipt.message_id, receipt.exit_code) == ("confirmed", 1, 0)
    assert hub.calls[1][0] == "GET" and hub.calls[1][1].endswith("since_id=0")


def test_the_first_mention_becomes_the_target():
    hub = FakeHub()
    post(hub, "QUESTION @admin: keep the 480i files?")
    post(hub, "@codex-lead, see #111")
    post(hub, "MERGED #111 as 9f8e7d6 (mail me at x@example.com)")
    post(hub, "HANDOFF to @codex-lead: review", target="@claude-lead")

    assert [m["target"] for m in hub.messages] == ["@admin", "@codex-lead", "@room", "@claude-lead"]


def test_a_stored_sender_other_than_the_lead_is_a_mismatch_not_a_success():
    """The hub derives the sender. If it ever stored someone else, say so."""
    hub = FakeHub(faults=["claudecode"])
    receipt = post(hub)

    assert receipt.state == "mismatch" and receipt.exit_code == lead_chat.EXIT_REFUSED


@pytest.mark.parametrize("fault", [
    TimeoutError("read timed out"),
    ConnectionResetError("reset"),
    Response(502, None),
    Response(200, {"status": "ok"}),
], ids=["timeout", "reset", "502", "no-id"])
def test_a_lost_or_unclear_response_is_unconfirmed_and_never_resent(fault):
    hub = FakeHub(faults=[fault])
    receipt = post(hub)

    assert receipt.state == "unconfirmed" and receipt.exit_code == lead_chat.EXIT_UNCONFIRMED
    assert len(hub.posts) == 1
    assert "find" in receipt.detail


def test_a_failed_read_back_is_unconfirmed_with_the_assigned_id():
    hub = FakeHub(faults=[None, ConnectionResetError("reset")])
    receipt = post(hub)

    assert (receipt.state, receipt.message_id) == ("unconfirmed", 1)
    assert len(hub.posts) == 1


def test_a_read_back_refusal_keeps_the_assigned_id_and_is_unconfirmed(monkeypatch):
    """Codex, #112 at 9f36273: the POST was accepted and returned #1, then the
    read-back got 401 (a credential rotated in between). That is not a refused
    post; the CLI must keep the id, say UNCONFIRMED and exit 2, having sent once."""
    monkeypatch.setattr(lead_chat, "_user_environment", NO_USER_ENV)
    monkeypatch.setenv("CLAUDE_LEAD_HUB_SECRET", "s")
    hub = FakeHub(faults=[None, Response(401, {})])
    out = io.StringIO()

    code = lead_chat.main(["--url", "http://hub", "post", "--as", "claude-lead", "MERGED #110"],
                          transport=hub, out=out)

    assert code == lead_chat.EXIT_UNCONFIRMED
    assert out.getvalue().startswith("UNCONFIRMED: the hub assigned #1")
    assert "find" in out.getvalue()
    assert len(hub.posts) == 1 and len(hub.messages) == 1


@pytest.mark.parametrize("status", [401, 403, 422])
def test_a_refused_post_is_reported_as_refused(status):
    with pytest.raises(LeadChatError, match=str(status)):
        post(FakeHub(faults=[Response(status, {"detail": "no"})]))


@pytest.mark.parametrize("content", ["", "   ", "x" * (lead_chat.MAX_CONTENT + 1)])
def test_empty_or_document_sized_posts_are_refused_before_sending(content):
    hub = FakeHub()

    with pytest.raises(LeadChatError):
        post(hub, content)

    assert hub.calls == []


# --- find and read ------------------------------------------------------------


def test_find_returns_only_this_leads_exact_earlier_posts():
    hub = FakeHub()
    text = "HANDOFF @codex-lead: review #111 at 1a2b3c4"
    post(hub, text)
    post(hub, text, identity="codex-lead")
    post(hub, text + " (again)")

    assert lead_chat.find("claude-lead", text, url="http://hub", transport=hub,
                          environ=ENV, user_environment=NO_USER_ENV) == [1]


@pytest.mark.parametrize("content, target, addressed", [
    ("HANDOFF @claude-lead: review #111", "@room", True),
    ("thanks (@claude-lead).", "@room", True),
    ("ping", "@claude-lead", True),
    ("ping", "@Claude-Lead", True),
    ("@claude-leader please", "@room", False),
    ("mail x@claude-lead.example", "@room", False),
    ("See @claude-lead.example", "@room", False),
    ("about claude-lead in general", "@room", False),
])
def test_a_mention_is_the_whole_handle(content, target, addressed):
    message = {"id": 1, "sender": "codex-lead", "target": target, "content": content}

    assert lead_chat.mentions(message, "claude-lead") is addressed


@pytest.mark.parametrize("content", [
    "HANDOFF @claude-lead: review #111", "thanks (@claude-lead).", "@claude-leader please",
    "See @claude-lead.example", "mail x@claude-lead.example", "about claude-lead",
    "QUESTION @admin: and @claude-lead too",
    # Codex, #112 at 1d9fa43: trimming hyphens turned another handle into this lead.
    "See @claude-lead-", "See @claude-lead---",
])
def test_the_posted_target_never_addresses_a_lead_the_text_does_not_mention(content):
    """Codex, #112 at 9f36273: `See @claude-lead.example` was posted to
    @claude-lead, and the synthesized target then made `mentions` true -- a
    wrong addressee now, and a spurious wake source under #113. Target
    inference and mention detection use the same boundaries, end to end."""
    hub = FakeHub()
    post(hub, content, identity="codex-lead")
    stored = hub.messages[0]

    by_text = lead_chat.mentions({**stored, "target": "@room"}, "claude-lead")
    assert lead_chat.mentions(stored, "claude-lead") is by_text


def test_read_leaves_out_the_leads_own_posts_and_filters_mentions():
    hub = FakeHub()
    post(hub, "HANDOFF @codex-lead: review #111", identity="claude-lead")
    post(hub, "REVIEW @claude-lead: approved", identity="codex-lead")
    post(hub, "MERGED #110", identity="codex-lead")

    everything = lead_chat.read("claude-lead", url="http://hub", transport=hub,
                                environ=ENV, user_environment=NO_USER_ENV)
    addressed = lead_chat.read("claude-lead", only_mentions=True, url="http://hub",
                               transport=hub, environ=ENV, user_environment=NO_USER_ENV)

    assert [m["id"] for m in everything] == [2, 3]
    assert [m["id"] for m in addressed] == [2]


# --- The command line ---------------------------------------------------------


def test_the_cli_reports_a_receipt_and_never_prints_the_secret(monkeypatch):
    monkeypatch.setattr(lead_chat, "_user_environment", NO_USER_ENV)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    out = io.StringIO()

    code = lead_chat.main(["--url", "http://hub", "post", "--as", "claude-lead", "MERGED #110"],
                          transport=FakeHub(), out=out)

    assert code == 0 and out.getvalue().startswith("CONFIRMED: #1 stored as claude-lead")
    assert "claude-lead-secret" not in out.getvalue()


def test_the_cli_exits_2_when_delivery_is_unconfirmed(monkeypatch):
    monkeypatch.setattr(lead_chat, "_user_environment", NO_USER_ENV)
    monkeypatch.setenv("CLAUDE_LEAD_HUB_SECRET", "s")
    out = io.StringIO()

    code = lead_chat.main(["post", "--as", "claude-lead", "x"],
                          transport=FakeHub(faults=[TimeoutError()]), out=out)

    assert code == 2 and out.getvalue().startswith("UNCONFIRMED")


def test_the_cli_refuses_an_unknown_identity():
    with pytest.raises(SystemExit):
        lead_chat.main(["post", "--as", "admin", "x"], transport=FakeHub(), out=io.StringIO())


# --- The real HTTP transport ---------------------------------------------------


class TruncatingHub:
    """A localhost HTTP server that stores each POST, then answers with a body
    shorter than its declared Content-Length and closes -- the reply is lost
    after the message was stored (Codex's #112 probe)."""

    def __init__(self, status=200):
        import http.server
        import threading

        hub = self
        self.stored = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                hub.stored.append(self.rfile.read(length))
                body = b'{"status":"ok","id":1}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body) + 32))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize("status", [200, 500], ids=["ok-body", "error-body"])
def test_a_truncated_reply_is_a_transport_error_not_a_crash(status):
    with TruncatingHub(status) as hub:
        with pytest.raises(OSError, match="incomplete HTTP exchange"):
            lead_chat.urllib_transport("POST", f"{hub.url}/send", {}, {"target": "@room",
                                                                       "content": "x"})


def test_a_truncated_reply_after_storing_is_unconfirmed_and_sent_once(monkeypatch):
    monkeypatch.setattr(lead_chat, "_user_environment", NO_USER_ENV)
    monkeypatch.setenv("CLAUDE_LEAD_HUB_SECRET", "s")
    out = io.StringIO()

    with TruncatingHub() as hub:
        code = lead_chat.main(["--url", hub.url, "post", "--as", "claude-lead", "MERGED #110"],
                              out=out)

    assert code == lead_chat.EXIT_UNCONFIRMED, out.getvalue()
    assert out.getvalue().startswith("UNCONFIRMED: no response from the hub")
    assert len(hub.stored) == 1


# --- Board (#1737) ------------------------------------------------------------


class FakeBoard:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or Response(200, {"status": "ok", "id": 7})

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.reply


def run_board(monkeypatch, argv, board=None):
    monkeypatch.setenv("CLAUDE_LEAD_HUB_SECRET", "s")
    board = board or FakeBoard()
    out = io.StringIO()
    code = lead_chat.main(["--url", "http://hub", "board", "--as", "claude-lead", *argv],
                          transport=board, out=out)
    return code, out.getvalue(), board.calls


@pytest.mark.parametrize("argv, method, path, body", [
    (["show"], "GET", "/board", None),
    (["project", "swarm", "Agent swarm", "--repo", "Decksx/agent-swarm"], "POST", "/board/projects",
     {"key": "swarm", "title": "Agent swarm", "repo": "Decksx/agent-swarm"}),
    (["add", "swarm", "Cap fix", "--owner", "claude-lead", "--status", "done", "--link", "L"],
     "POST", "/board/tasks",
     {"project": "swarm", "title": "Cap fix", "owner": "claude-lead", "status": "done", "link": "L"}),
    (["add", "swarm", "Sub", "--parent", "3"], "POST", "/board/tasks",
     {"project": "swarm", "title": "Sub", "parent_id": 3}),
    (["set", "7", "--status", "review"], "POST", "/board/tasks/7", {"status": "review"}),
])
def test_board_actions_map_to_one_authenticated_call(monkeypatch, argv, method, path, body):
    code, out, calls = run_board(monkeypatch, argv)
    assert code == lead_chat.EXIT_OK
    assert [(c[0], c[1], c[3]) for c in calls] == [(method, "http://hub" + path, body)]
    assert base64.b64decode(calls[0][2]["Authorization"].split()[1]).decode() == "claude-lead:s"


def test_a_board_refusal_is_reported_with_the_servers_reason(monkeypatch):
    refusal = FakeBoard(Response(422, {"detail": "a task is done only with evidence"}))
    code, out, calls = run_board(monkeypatch, ["set", "7", "--status", "done"], refusal)
    assert code == lead_chat.EXIT_REFUSED
    assert out.startswith("REFUSED: the board refused this (422): a task is done only with evidence")
    assert len(calls) == 1
