"""A provider failure reaches the ledger as itself, not as silence (#20).

When the OpenAI call failed before producing any text -- a 429 over the
tokens-per-minute window, or a client timeout -- `generate_reply` answered
None, which is the same answer it gives when the model succeeds and returns
an empty string. The author path reported both as `blocked` with the reason
"the model returned nothing", so the ledger could not tell a provider
refusal from an empty generation and the operator had to read the worker log
on OFFICEPC to find the cause.

Two failures from 2026-09-13 are the shapes under test here:

  - T-INFRA-11, seq 318: `429 ... Request too large for gpt-4o ... tokens per
    min (TPM): Limit 30000, Requested 38...`
  - T-INFRA-12 author attempt 3, seq 338: `OpenAI request failed: Request
    timed out.` after 361.7s

Both are driven through the real `generate_reply`, by a client that raises,
rather than by stubbing the classification -- the defect was in the seam
between the call and the report, so a test that stubs the seam would not
have caught it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import authored_change
import authored_edits
import chatgpt_worker
import repo_registry
import repo_snapshot


# --- Exception shapes the SDK raises ---------------------------------------------
#
# The OpenAI SDK is imported lazily by `ensure_dependencies`, so these cannot
# be its real classes and must not be: the point of `classify_provider_error`
# is that it reads a status code and a class name off whatever it is handed.


class FakeAPIError(Exception):
    """An SDK error carrying a status code, as openai.APIStatusError does."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class APITimeoutError(FakeAPIError):
    """Name-matched, because the SDK's timeout carries no status code."""


class APIConnectionError(FakeAPIError):
    pass


TPM_429 = (
    "Error code: 429 - Request too large for gpt-4o in organization org-x on "
    "tokens per min (TPM): Limit 30000, Requested 38412."
)
RATE_429 = "Error code: 429 - Rate limit reached for gpt-4o. Please try again in 1s."


class Raises:
    """A model client whose completion call raises, at the real call site."""

    def __init__(self, exc):
        self.exc = exc

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        raise self.exc


class Answers:
    """A model client that returns one scripted completion."""

    def __init__(self, content):
        self.content = content

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        message = type("M", (), {"content": self.content})
        choice = type("C", (), {"message": message})
        return type("R", (), {"choices": [choice]})


# --- What each failure is called --------------------------------------------------


@pytest.mark.parametrize("exc,kind,status", [
    (APITimeoutError("Request timed out."), "timeout", None),
    (FakeAPIError(TPM_429, 429), "request_too_large", 429),
    (FakeAPIError(RATE_429, 429), "rate_limited", 429),
    (FakeAPIError("Incorrect API key provided", 401), "auth_rejected", 401),
    (FakeAPIError("Forbidden", 403), "auth_rejected", 403),
    (FakeAPIError("Bad gateway", 502), "provider_unavailable", 502),
    (FakeAPIError("Service unavailable", 503), "provider_unavailable", 503),
    (APIConnectionError("Connection error."), "connection_failed", None),
    (FakeAPIError("Invalid value for 'model'", 400), "provider_error", 400),
    (ValueError("something the SDK never documented"), "provider_error", None),
])
def test_each_failure_is_named(exc, kind, status):
    failure = chatgpt_worker.classify_provider_error(exc)

    assert (failure.kind, failure.status) == (kind, status)


def test_a_timeout_is_a_timeout_even_with_a_status():
    """Class name wins: a timeout is a timeout whatever the transport says."""
    failure = chatgpt_worker.classify_provider_error(APITimeoutError("timed out", 408))

    assert failure.kind == "timeout" and failure.status == 408


def test_the_two_429s_are_told_apart():
    """Waiting fixes one and never fixes the other, so they cannot share a name."""
    too_large = chatgpt_worker.classify_provider_error(FakeAPIError(TPM_429, 429))
    limited = chatgpt_worker.classify_provider_error(FakeAPIError(RATE_429, 429))

    assert too_large.kind == "request_too_large"
    assert limited.kind == "rate_limited"
    assert too_large.kind != limited.kind


def test_a_status_that_is_not_an_integer_is_ignored():
    """`status_code` is whatever the exception carries; None beats a wrong number."""
    failure = chatgpt_worker.classify_provider_error(FakeAPIError("odd", "429"))

    assert failure.status is None and failure.kind == "provider_error"


def test_an_error_with_no_text_is_named_by_its_class():
    failure = chatgpt_worker.classify_provider_error(APITimeoutError(""))

    assert failure.message == "APITimeoutError"


def test_the_provider_message_is_bounded():
    failure = chatgpt_worker.classify_provider_error(FakeAPIError("x" * 5000, 500))

    assert len(failure.message) == chatgpt_worker.PROVIDER_MESSAGE_CHARS


def test_a_credential_in_the_provider_message_is_redacted():
    """Provider errors quote the request, and the ledger is not a secret store."""
    failure = chatgpt_worker.classify_provider_error(
        FakeAPIError("Incorrect API key provided: sk-proj-abcdefghijklmnop1234567890", 401))

    assert "sk-proj-abcdefghijklmnop1234567890" not in failure.message


def test_the_reason_names_the_class_the_status_and_the_text():
    reason = chatgpt_worker.classify_provider_error(FakeAPIError(TPM_429, 429)).reason()

    assert "request_too_large" in reason
    assert "HTTP 429" in reason
    assert "Limit 30000" in reason


def test_a_reason_without_a_status_says_no_status():
    reason = chatgpt_worker.classify_provider_error(APITimeoutError("Request timed out.")).reason()

    assert "HTTP" not in reason and "timeout" in reason


# --- What generate_reply answers --------------------------------------------------


CONTEXT = [{"sender": "controller", "target": "@chatgpt", "content": "do the thing"}]


def test_a_failed_call_answers_a_provider_failure():
    reply = chatgpt_worker.generate_reply(Raises(FakeAPIError(TPM_429, 429)), CONTEXT)

    assert isinstance(reply, chatgpt_worker.ProviderFailure)
    assert reply.kind == "request_too_large"


def test_an_empty_generation_still_answers_none():
    """The other half of the old conflation has to keep its own answer."""
    assert chatgpt_worker.generate_reply(Answers("   "), CONTEXT) is None


def test_a_good_generation_answers_text():
    assert chatgpt_worker.generate_reply(Answers(" hello "), CONTEXT) == "hello"


def test_an_unusable_response_shape_is_a_provider_failure():
    """An empty `choices` list raises inside the try; it must not crash the loop."""
    class NoChoices(Answers):
        def create(self, **kwargs):
            return type("R", (), {"choices": []})

    assert isinstance(chatgpt_worker.generate_reply(NoChoices(""), CONTEXT),
                      chatgpt_worker.ProviderFailure)


# --- What the ledger is told ------------------------------------------------------


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def author_repo(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
    (root / "README.md").write_text("# project\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "existing.txt").write_text("old\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")

    registry = tmp_path / "repos.json"
    registry.write_text(json.dumps({
        "demo": {
            "path": str(root),
            "repo_id": repo_snapshot.repo_id(str(root)),
            "planning_ref": "refs/heads/main",
            "worktree_root": str(tmp_path / "worktrees"),
        }
    }), encoding="utf-8")

    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)
    monkeypatch.setattr(chatgpt_worker, "AUTHOR_PROJECT", "demo")
    return root


class Queue:
    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({
            "activation_id": activation_id,
            "outcome": outcome,
            "payload": payload or {},
        })

    @property
    def last(self):
        assert self.reports, "the worker reported nothing at all"
        return self.reports[-1]


CONTRACT = "task_id: T-1\nallowed_paths:\n  - notes\n"


def activation(base):
    return {
        "activation_id": "A-1",
        "task_id": "T-1",
        "expected_branch": "task/T-1-a1",
        "task_record": {
            "task_id": "T-1",
            "title": "add a note",
            "base_sha": base,
            "current_version": 1,
            "contract_hash": "c" * 64,
            "objective": "add a note",
            "contract_yaml": CONTRACT,
            "allowed_paths": ["notes"],
            "proof_mode": "branch_only",
        },
    }


def author_with(repo, exc):
    queue = Queue()
    base = git(repo, "rev-parse", "HEAD").strip()
    chatgpt_worker.execute_author(Raises(exc), activation(base), queue)
    return queue.last


def test_the_tpm_429_is_recorded_as_itself(author_repo):
    """T-INFRA-11 seq 318: recorded as "the model returned nothing" before #20."""
    report = author_with(author_repo, FakeAPIError(TPM_429, 429))

    assert report["outcome"] == "blocked"
    assert report["payload"]["provider_failure"] == "request_too_large"
    assert report["payload"]["provider_status"] == 429
    assert "Limit 30000" in report["payload"]["provider_message"]
    assert "the model returned nothing" not in report["payload"]["reason"]


def test_the_timeout_is_recorded_as_itself(author_repo):
    """T-INFRA-12 attempt 3, seq 338: a 361.7s client timeout."""
    report = author_with(author_repo, APITimeoutError("Request timed out."))

    assert report["outcome"] == "blocked"
    assert report["payload"]["provider_failure"] == "timeout"
    assert report["payload"]["provider_status"] is None
    assert "timeout" in report["payload"]["reason"]
    assert "the model returned nothing" not in report["payload"]["reason"]


def test_a_blocked_provider_failure_carries_how_long_it_took(author_repo):
    report = author_with(author_repo, FakeAPIError(RATE_429, 429))

    assert report["payload"]["elapsed_seconds"] >= 0
    assert report["payload"]["repaired"] is False


def test_an_empty_generation_is_still_the_model_returning_nothing(author_repo):
    """The regression guard: the honest case keeps the honest reason."""
    queue = Queue()
    base = git(author_repo, "rev-parse", "HEAD").strip()
    chatgpt_worker.execute_author(Answers(""), activation(base), queue)

    assert queue.last["outcome"] == "blocked"
    assert queue.last["payload"]["reason"] == "the model returned nothing"
    assert "provider_failure" not in queue.last["payload"]


def test_a_failure_during_the_repair_call_is_reported_as_the_failure(author_repo):
    """The second call can fail too, and it lands in the same branch (#35 repair)."""
    # A SEARCH that is not in the file: refused, and worth one repair (#35).
    answers = [
        f"EDIT: notes/existing.txt\n{authored_edits.SEARCH}\nnot in the file\n"
        f"{authored_edits.REPLACE}\nx\n{authored_change.END}\n",
    ]

    class ThenFails(Answers):
        def create(self, **kwargs):
            if answers:
                self.content = answers.pop(0)
                return super().create(**kwargs)
            raise APITimeoutError("Request timed out.")

    queue = Queue()
    base = git(author_repo, "rev-parse", "HEAD").strip()
    chatgpt_worker.execute_author(ThenFails(""), activation(base), queue)

    assert queue.last["outcome"] == "blocked"
    assert queue.last["payload"]["provider_failure"] == "timeout"
    assert queue.last["payload"]["repaired"] is True


# --- What the hub is told ---------------------------------------------------------


def test_the_chat_path_still_says_nothing_on_a_failure(monkeypatch):
    """Silence on the hub is deliberate: a 429 posted as a reply becomes a thread."""
    class Posted(Exception):
        pass

    def never_post(*args, **kwargs):
        raise Posted("a provider failure was posted to the hub")

    monkeypatch.setattr(chatgpt_worker, "post_reply", never_post)

    chatgpt_worker.execute_activation(
        None, Raises(FakeAPIError(TPM_429, 429)),
        {"activation_id": "A-1", "task": "say hello", "issued_by": "admin"},
    )
