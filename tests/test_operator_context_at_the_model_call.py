"""What the worker actually hands the model, captured at the call itself.

The renderers are tested directly elsewhere. These run the worker's own
authoring and review paths with the model call replaced by a recorder, and
read the prompt out of the arguments it was given -- so what is asserted is
the string that would have been sent, not the shape of the code that builds
it.

A source-window assertion stood here first. It matched the right text and
could have matched a comment or a call that nothing reaches, which is the
difference between reading code and running it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import authored_change  # noqa: E402
import chatgpt_worker  # noqa: E402
import gemini_worker  # noqa: E402
import repo_registry  # noqa: E402
import repo_snapshot  # noqa: E402
import review_packet  # noqa: E402


ANSWER = {
    "response": "require sabotage mode; branch_only is not enough here",
    "action": "return_to_author",
    "actor": "admin",
    "event_seq": 412,
    "task_version": 3,
}

SUPERSEDED = {
    "response": "branch_only is fine, ship it",
    "action": "return_to_review",
    "actor": "admin",
    "event_seq": 87,
    "task_version": 2,
}


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"

    return result.stdout


class Queue:
    """Records what the worker reported, so a refusal is visible."""

    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({"outcome": outcome, "payload": payload or {}})

    def judge(self, activation_id, *, judgment, payload=None):
        self.reports.append({"outcome": judgment, "payload": payload or {}})


# --- Authoring ---------------------------------------------------------------


@pytest.fixture
def author_repo(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
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


@pytest.fixture
def author_call(monkeypatch):
    """Replaces the one model call and keeps the prompt it was handed."""
    seen = {}

    def recorder(client, messages):
        seen["prompt"] = messages[0]["content"]

        return (
            "FILE: notes/hello.txt\n"
            f"{authored_change.BEGIN}\nhello\n{authored_change.END}\n"
        )

    monkeypatch.setattr(chatgpt_worker, "generate_reply", recorder)

    return seen


def author_activation(repo, operator_context=None):
    return {
        "activation_id": "A-1",
        "task_id": "T-1",
        "expected_branch": "task/T-1-a1",
        "operator_context": operator_context,
        "task_record": {
            "task_id": "T-1",
            "title": "add a note",
            "base_sha": git(repo, "rev-parse", "HEAD").strip(),
            "objective": "add a note",
            "contract_yaml": "task_id: T-1\nallowed_paths:\n  - notes\n",
            "proof_mode": "branch_only",
            # The author now states the contract it is bound by, so the
            # record has to carry what a controller record carries.
            "current_version": 1,
            "contract_hash": "c" * 64,
        },
    }


def author(repo, operator_context=None):
    chatgpt_worker.execute_author(
        object(), author_activation(repo, operator_context), Queue()
    )


def test_the_prompt_sent_to_the_author_model_carries_the_answer(
    author_repo, author_call
):
    author(author_repo, ANSWER)

    assert "prompt" in author_call, "the model was never called"
    assert ANSWER["response"] in author_call["prompt"]


def test_the_prompt_sent_to_the_author_model_bounds_it_by_the_contract(
    author_repo, author_call
):
    author(author_repo, ANSWER)

    assert "CANNOT change the contract" in author_call["prompt"]
    assert "follow the operator" not in author_call["prompt"].lower()


def test_a_superseded_answer_never_reaches_the_author_model(
    author_repo, author_call
):
    author(author_repo, ANSWER)

    assert SUPERSEDED["response"] not in author_call["prompt"]


def test_an_unescalated_task_sends_no_operator_section(author_repo, author_call):
    author(author_repo, None)

    assert "ESCALATED" not in author_call["prompt"].upper()


# --- Review ------------------------------------------------------------------


PACKET = {
    "task_id": "T-1",
    "title": "add a note",
    "objective": "add a note",
    "branch": "task/T-1-a1",
    "base_sha": "1" * 40,
    "candidate_sha": "2" * 40,
    "commits": ["abc1234 add a note"],
    "changed_files": ["notes/hello.txt"],
    "diff": "--- a/notes/hello.txt\n+++ b/notes/hello.txt\n",
    "diff_truncated": False,
    "author_summary": "",
    "test_output": "",
}


@pytest.fixture
def review_call(monkeypatch, tmp_path):
    """The review path with the evidence gathering and the model both stubbed.

    `review_packet.build` runs git over a real range; what is under test here
    is whether the activation's operator context reaches the prompt, so the
    packet is supplied and the worker's own wiring is left to run.
    """
    seen = {}

    def fake_build(repo, **kwargs):
        seen["build_kwargs"] = kwargs

        return {**PACKET, "operator_context": kwargs.get("operator_context")}

    def recorder(client, types, messages):
        seen["prompt"] = messages[0]["content"]

        return "VERDICT: approve\nRATIONALE: fine"

    monkeypatch.setattr(review_packet, "build", fake_build)
    monkeypatch.setattr(gemini_worker, "generate_reply", recorder)
    monkeypatch.setattr(gemini_worker, "REVIEW_REPO", str(tmp_path))

    return seen


def review_activation(operator_context=None):
    return {
        "activation_id": "R-1",
        "task_id": "T-1",
        "expected_branch": "task/T-1-a1",
        "expected_parent": "1" * 40,
        "expected_candidate": "2" * 40,
        "repo_location": "",
        "operator_context": operator_context,
        "task_record": {"title": "add a note", "objective": "add a note"},
    }


def review(operator_context=None):
    gemini_worker.execute_review(
        object(), object(), review_activation(operator_context), Queue()
    )


def test_the_activation_context_is_handed_to_the_packet_builder(review_call):
    review(ANSWER)

    assert review_call["build_kwargs"].get("operator_context") == ANSWER


def test_the_prompt_sent_to_the_review_model_carries_the_answer(review_call):
    review(ANSWER)

    assert "prompt" in review_call, "the model was never called"
    assert ANSWER["response"] in review_call["prompt"]


def test_the_prompt_sent_to_the_review_model_bounds_it_by_the_contract(
    review_call
):
    review(ANSWER)

    assert "CANNOT change the contract" in review_call["prompt"]
    assert "follow the operator" not in review_call["prompt"].lower()


def test_a_superseded_answer_never_reaches_the_review_model(review_call):
    review(ANSWER)

    assert SUPERSEDED["response"] not in review_call["prompt"]


def test_an_unescalated_review_sends_no_operator_section(review_call):
    review(None)

    assert "ESCALATED" not in review_call["prompt"].upper()
