"""The authoring path, from an activation to a commit or a refusal.

`execute_author` had no test at all: it was only ever exercised live, one paid
model call at a time. The scope correction runs inside it, and "the parser
refuses" is not the same claim as "the worker refuses before it pays for a
generation" -- so the model client here raises if it is called, which turns the
count into an assertion rather than a hope.
"""

from __future__ import annotations

import subprocess

import pytest

import authored_change
import chatgpt_worker


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def author_repo(tmp_path, monkeypatch):
    """A clean repository the worker is pointed at."""
    root = tmp_path / "work"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
    (root / "README.md").write_text("# project\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "existing.txt").write_text("old\n", encoding="utf-8")
    (root / "build.sh").write_text("echo build\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")

    monkeypatch.setattr(chatgpt_worker, "AUTHOR_REPO", str(root))
    return root


class Queue:
    """Records what the worker reported, in order."""

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


class NeverCalled:
    """A model client that fails the test if anything asks it for a reply."""

    calls = 0

    def __getattr__(self, name):
        raise AssertionError(
            f"the model was called ({name}) -- the refusal must happen first"
        )


@pytest.fixture
def counted_reply(monkeypatch):
    """Replaces the model call with a scripted answer, counting the calls."""
    state = {"calls": 0, "answer": ""}

    def fake_generate_reply(client, messages):
        state["calls"] += 1
        state["prompt"] = messages[0]["content"]
        return state["answer"]

    monkeypatch.setattr(chatgpt_worker, "generate_reply", fake_generate_reply)
    return state


def activation(contract, *, allowed=None, title="add a note"):
    return {
        "activation_id": "A-1",
        "task_id": "T-1",
        "task_record": {
            "title": title,
            "objective": "add a note",
            "contract_yaml": contract,
            "allowed_paths": allowed,
        },
    }


CONTRACT = "task_id: T-1\nallowed_paths:\n  - notes\n"
ANSWER = (
    "FILE: notes/hello.txt\n"
    f"{authored_change.BEGIN}\n"
    "hello\n"
    f"{authored_change.END}\n"
)


# --- A contract that says nothing stops the work before it costs anything ----


@pytest.mark.parametrize("contract", [
    "task_id: T-1\ntitle: add a note\n",          # no allowed_paths at all
    "",                                            # empty contract
    "allowed_paths:\ntitle: x\n",                  # the key, no entries
    "allowed_paths: []",                           # an empty list
    "task_id: T-1\nallowed_pa",                    # truncated mid-key
    "allowed_paths: everything",                   # a scalar nobody can parse
])
def test_an_unusable_contract_blocks_before_the_model_is_called(
    author_repo, contract
):
    """The refusal is the point; that it is free is why it is placed here.

    Every one of these used to mean "unrestricted". Each is a shape a contract
    genuinely arrives in -- half-written, truncated by a token limit, or in a
    dialect this parser has never seen.
    """
    queue = Queue()
    chatgpt_worker.execute_author(NeverCalled(), activation(contract), queue)

    assert queue.last["outcome"] == "blocked"
    assert "authorise" in queue.last["payload"]["reason"]


def test_a_blocked_contract_leaves_the_repository_untouched(author_repo):
    queue = Queue()
    chatgpt_worker.execute_author(NeverCalled(), activation("title: x\n"), queue)

    assert git(author_repo, "status", "--porcelain") == ""
    assert git(author_repo, "branch", "--list", "task/T-1").strip() == ""


# --- A contract that says something is honoured ------------------------------


def test_a_scoped_contract_authors_one_commit_with_one_model_call(
    author_repo, counted_reply
):
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT), queue)

    assert counted_reply["calls"] == 1
    assert queue.last["outcome"] == "candidate"
    assert queue.last["payload"]["files"] == ["notes/hello.txt"]
    assert len(queue.last["payload"]["candidate_sha"]) == 40


def test_the_prompt_names_the_paths_the_task_may_touch(
    author_repo, counted_reply
):
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(object(), activation(CONTRACT), Queue())

    assert "notes" in counted_reply["prompt"]


def test_a_file_outside_the_scope_fails_the_attempt(author_repo, counted_reply):
    """The model answered; the answer was not one it was allowed to give."""
    counted_reply["answer"] = (
        "FILE: build.sh\n"
        f"{authored_change.BEGIN}\n"
        "rm -rf /\n"
        f"{authored_change.END}\n"
    )
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT), queue)

    assert queue.last["outcome"] == "failed"
    assert git(author_repo, "status", "--porcelain") == ""
    assert (author_repo / "build.sh").read_text(encoding="utf-8") == "echo build\n"


def test_the_controllers_own_allowed_paths_are_honoured(
    author_repo, counted_reply
):
    """A contract this parser cannot read is fine if the record states it."""
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation("nothing parseable here", allowed=["notes"]), queue
    )

    assert queue.last["outcome"] == "candidate"


def test_the_explicit_marker_authors_repository_wide(author_repo, counted_reply):
    """Reachable, deliberately -- and only from the marker."""
    counted_reply["answer"] = (
        "FILE: anywhere.txt\n"
        f"{authored_change.BEGIN}\n"
        "x\n"
        f"{authored_change.END}\n"
    )
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation("allowed_paths: UNRESTRICTED\n"), queue
    )

    assert queue.last["outcome"] == "candidate"
    assert queue.last["payload"]["files"] == ["anywhere.txt"]


# --- The other refusals on this path ----------------------------------------


def test_a_dirty_worktree_blocks_before_the_model_is_called(author_repo):
    """Paying for a generation and then discovering it cannot land is worse."""
    (author_repo / "someone_elses.txt").write_text("edit\n", encoding="utf-8")
    queue = Queue()
    chatgpt_worker.execute_author(NeverCalled(), activation(CONTRACT), queue)

    assert queue.last["outcome"] == "blocked"
    assert "uncommitted" in queue.last["payload"]["reason"]


def test_a_model_that_returns_nothing_is_blocked_not_failed(
    author_repo, counted_reply
):
    counted_reply["answer"] = None
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT), queue)

    assert queue.last["outcome"] == "blocked"
