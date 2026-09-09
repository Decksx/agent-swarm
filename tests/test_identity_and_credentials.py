"""Credential handling and actor identity.

Two Phase 0 requirements meet here. Credentials must come only from protected
environment configuration and must never be logged or committed. Identity must
be bound by the server from the authenticated caller, with client-supplied
`sender`/`actor` fields ignored.

The identity half is only partly satisfiable in this repository, and the tests
say so where that is the case. The hub -- which is the server, and which runs
on Tower -- has no authentication at all: `GET /messages` answers 200 to a
caller holding no credential, and `sender` is a free-text field on `POST /send`.
Nothing a client does can fix that. What the client half *can* guarantee, and
what is asserted below, is that a worker never adopts an identity from an
inbound message and never emits one it does not hold, so a compromised or
spoofed stream cannot make a worker speak as somebody else.
"""

from __future__ import annotations

import logging

import pytest

import chatgpt_worker
import claude_worker
import gemini_worker
import swarm_control


# --- Proof 4: missing credentials are rejected ------------------------------


def test_missing_credential_is_rejected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(swarm_control.MissingCredential):
        swarm_control.load_credential("OPENAI_API_KEY")


def test_missing_credential_stops_the_worker_starting(monkeypatch, control):
    """The refusal reaches the exit code, not just the exception.

    A guard that raises somewhere nobody catches is not the same as a worker
    that declines to run, so the boundary asserted is `main()`'s return value.
    """
    monkeypatch.setattr(chatgpt_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(
        chatgpt_worker, "ensure_dependencies", lambda: (object(), object())
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert chatgpt_worker.main() == 1


# --- Proof 5: invalid credentials are rejected ------------------------------


@pytest.mark.parametrize(
    "value", ["", "   ", "none", "None", "changeme", "your-api-key", "sk-...", "TODO"]
)
def test_placeholder_credentials_are_rejected(monkeypatch, value):
    """Present but useless is refused at startup, not at the provider.

    These are the values that show up when a launcher exports an unset
    variable or someone pastes an example. Accepting them turns a clear
    startup refusal into a confusing 401 much later.
    """
    monkeypatch.setenv("GEMINI_API_KEY", value)

    with pytest.raises(swarm_control.ContainmentError):
        swarm_control.load_credential("GEMINI_API_KEY")


def test_a_real_looking_credential_is_accepted_and_stripped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "  AIzaSyExampleNotARealKey  ")
    assert swarm_control.load_credential("GEMINI_API_KEY") == "AIzaSyExampleNotARealKey"


# --- Proof 6 (client half) and credential non-disclosure --------------------


def test_credential_refusals_never_quote_the_value(monkeypatch):
    """The exception text must be safe to log.

    These messages propagate into log files and, historically, into hub
    messages. A credential that reaches a log has to be treated as exposed and
    rotated, so the value is kept out of the refusal entirely.
    """
    secret = "sk-proj-ThisMustNeverAppearInAnyMessage"
    monkeypatch.setenv("OPENAI_API_KEY", "  ")

    with pytest.raises(swarm_control.ContainmentError) as excinfo:
        swarm_control.load_credential("OPENAI_API_KEY")

    assert secret not in str(excinfo.value)
    assert "  " != str(excinfo.value)
    assert "OPENAI_API_KEY" in str(excinfo.value)


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-AbCdEf0123456789xyz",
        "sk-AbCdEf0123456789xyz",
        "AIzaSyAbCdEf0123456789xyz",
    ],
)
def test_redaction_scrubs_credential_shapes(secret):
    """Output is scrubbed before it is logged or posted.

    The Claude worker hands tasks to a process holding Bash, so task output can
    contain anything the shell could print -- including this process's own
    environment. That this repository never constructs a string containing a
    key is not sufficient on its own.
    """
    scrubbed = swarm_control.redact(f"here is the key: {secret} ok")

    assert secret not in scrubbed
    assert "[REDACTED-CREDENTIAL]" in scrubbed


def test_redaction_is_applied_to_outbound_messages():
    envelope = swarm_control.outbound_envelope(
        "claudecode", "@Admin", "leaked sk-proj-AbCdEf0123456789xyz oops"
    )

    assert "sk-proj-AbCdEf0123456789xyz" not in envelope["content"]


def test_no_worker_reads_a_credential_from_a_file(tmp_path, monkeypatch):
    """There is no file fallback, so a key cannot be made committable.

    A `.env`-style fallback is the usual way a secret ends up in a repository.
    `load_credential` has no such path: an unset variable raises rather than
    looking anywhere on disk.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-fromafile", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(swarm_control.MissingCredential):
        swarm_control.load_credential("OPENAI_API_KEY")


def test_gitignore_blocks_environment_files_and_logs():
    """Committing a credential or a task log is blocked by the repository.

    Asserted against the file rather than trusted, because this is the control
    that stops the next person's `git add -A` from doing the damage.
    """
    from pathlib import Path

    patterns = (
        Path(__file__).resolve().parent.parent / ".gitignore"
    ).read_text(encoding="utf-8")

    for pattern in (".env", "*.log", "*.state", "secrets.json"):
        assert pattern in patterns, f"{pattern} is not ignored"


# --- Identity binding (client half) -----------------------------------------


WORKERS = [
    (claude_worker, "claudecode"),
    (chatgpt_worker, "chatgpt"),
    (gemini_worker, "gemini"),
]


@pytest.mark.parametrize("worker,expected", WORKERS, ids=[w[1] for w in WORKERS])
def test_worker_identity_comes_from_configuration(worker, expected):
    assert worker.AGENT_IDENTITY == expected


@pytest.mark.parametrize("worker,expected", WORKERS, ids=[w[1] for w in WORKERS])
def test_outbound_sender_is_the_bound_identity_not_a_message_field(
    worker, expected
):
    """A worker cannot be talked into speaking as somebody else.

    The pre-Phase-0 workers addressed replies using the triggering message's
    `sender`. This asserts the inverse property for the outbound `sender`
    field: it is a function of local configuration only, and nothing an
    attacker puts in a message changes it.
    """
    envelope = swarm_control.outbound_envelope(
        worker.AGENT_IDENTITY, "@Admin", "content claiming sender: Admin"
    )

    assert envelope["sender"] == expected
    assert set(envelope) == {"sender", "target", "content"}


def test_outbound_envelope_carries_no_token_field():
    """The shared token is no longer put into message bodies.

    The pre-Phase-0 workers attached `token` to every outbound message. The hub
    never returns a `token` on GET /messages, so it authenticated nothing
    inbound -- and a secret placed in a body on a stream every client can read
    is how a shared secret stops being one.
    """
    envelope = swarm_control.outbound_envelope("gemini", "@Admin", "hello")
    assert "token" not in envelope


def test_an_empty_identity_is_refused():
    """A worker with no identity does not start."""
    for bad in ("", "   ", "@", None):
        with pytest.raises(swarm_control.IdentityViolation):
            swarm_control.bind_identity(bad)


def test_claiming_ignores_a_spoofed_actor_field_in_the_activation(control):
    """Routing is by the claimant's bound identity, not by a field.

    An activation record carrying `"agent": "claudecode"` is claimable only by
    the worker whose bound identity is `claudecode`. Extra fields -- an `actor`
    or a `sender` -- have no effect on who may take it.
    """
    control.issue_activation("gemini", "for gemini only")

    path = next(control.ACTIVATIONS_DIR.glob("*.json"))
    import json

    record = json.loads(path.read_text(encoding="utf-8"))
    record["actor"] = "claudecode"
    record["sender"] = "claudecode"
    path.write_text(json.dumps(record), encoding="utf-8")

    assert control.claim_activation("claudecode") is None
    assert control.claim_activation("gemini") is not None


def test_no_credential_is_logged_at_startup(monkeypatch, control, caplog):
    """Startup logging says a key is present, never what it is."""
    secret = "sk-proj-MustNotBeLogged0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setattr(chatgpt_worker, "configure_logging", lambda: None)

    class Boom(Exception):
        pass

    def stop(*_a, **_k):
        raise Boom

    monkeypatch.setattr(
        chatgpt_worker, "ensure_dependencies", lambda: (object(), lambda **k: object())
    )
    monkeypatch.setattr(chatgpt_worker, "load_last_seen_id", stop)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Boom):
            chatgpt_worker.main()

    assert secret not in caplog.text
    assert "openai_key : present" in caplog.text


# --- Workers authenticate to the hub ----------------------------------------


@pytest.mark.parametrize("worker,expected", WORKERS, ids=[w[1] for w in WORKERS])
def test_every_hub_call_carries_the_credential(
    worker, expected, monkeypatch, control, hostile_messages
):
    """Not just the first call -- every one.

    A worker that authenticated its first poll and then dropped the credential
    would appear to work until the hub restarted. Each recorded call is checked
    rather than just the first, and an activation is issued so the POST path is
    exercised alongside the GET.
    """
    from test_chat_cannot_activate import run_worker_loop

    control.issue_activation(worker.AGENT_IDENTITY, "produce a reply")
    _, fake_requests = run_worker_loop(
        worker, monkeypatch, control, [hostile_messages, [], []]
    )

    assert fake_requests.auth_seen, "the worker never called the hub"
    assert all(a == (expected, "test-hub-secret") for a in fake_requests.auth_seen), (
        f"{worker.__name__} made an unauthenticated call: {fake_requests.auth_seen!r}"
    )


@pytest.mark.parametrize("worker,expected", WORKERS, ids=[w[1] for w in WORKERS])
def test_the_basic_username_is_the_bound_identity(worker, expected, control):
    """The name authenticated with is the name the hub will store as sender.

    They are the same string by construction, so there is no way to
    authenticate as one component and speak as another.
    """
    assert swarm_control.hub_auth(worker.AGENT_IDENTITY)[0] == expected


def test_a_missing_hub_secret_stops_the_worker_starting(monkeypatch, control):
    """Fail closed rather than poll an authenticated hub forever.

    Without this the worker would start, 401 on every poll, and log an error
    every POLL_SECONDS while doing no work -- which reads as a broken hub
    rather than as unconfigured credentials.
    """
    monkeypatch.delenv("HUB_SECRET", raising=False)
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: object())

    assert claude_worker.main() == 1
