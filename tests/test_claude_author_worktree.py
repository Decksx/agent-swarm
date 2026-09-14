"""The Claude CLI author works in its own worktree, on its own branch (#37).

The first chat-started task's claudecode attempt ran `claude -p` from a
directory inside the canonical checkout. It committed there, switched that
checkout onto a branch of its own naming, and the worker reported whatever
branch git showed afterwards.

These run the real author path against real repositories. The model is the
only thing stubbed, and the stubs do what a session with Bash authority can
do -- commit, switch branches, reach into another directory -- so each check
is exercised by the behaviour it exists to catch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import claude_worker
import repo_registry
import repo_snapshot


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout.strip()


class Queue:
    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({"outcome": outcome, "payload": payload or {}})

    @property
    def only(self):
        assert len(self.reports) == 1, self.reports
        return self.reports[0]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered project whose checkout is on main, mid-edit, and ahead.

    Ahead of the task's base on purpose: an author that started from the
    checkout's HEAD rather than the base would show up as a wrong parent.
    """
    root = tmp_path / "canonical"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
    (root / "notes").mkdir()
    (root / "notes" / "a.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")

    (root / "later.txt").write_text("after the base\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "later")

    # A person's unsaved work, which must survive every run untouched.
    (root / "notes" / "a.txt").write_text("somebody's edit\n", encoding="utf-8")

    registry = tmp_path / "repos.json"
    registry.write_text(json.dumps({"demo": {
        "path": str(root),
        "repo_id": repo_snapshot.repo_id(str(root)),
        "planning_ref": "refs/heads/main",
        "worktree_root": str(tmp_path / "worktrees"),
    }}), encoding="utf-8")

    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)
    monkeypatch.setattr(claude_worker, "AUTHOR_PROJECT", "demo")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", tmp_path / "inflight")
    monkeypatch.setattr(claude_worker, "post_reply", lambda *a, **k: None)

    return {"root": root, "base": base, "head": git(root, "rev-parse", "HEAD"),
            "worktrees": tmp_path / "worktrees"}


def activation(project, **overrides):
    record = {
        "task_id": "T-7",
        "title": "add a note",
        "objective": "add a note",
        "current_version": 1,
        "base_sha": project["base"],
        "proof_mode": "branch_only",
        "contract_hash": "a" * 64,
        "contract_yaml": "schema_version: 7\nallowed_paths:\n  - notes\n",
    }
    record.update(overrides.pop("record", {}))

    return {
        "activation_id": "act-7",
        "task_id": "T-7",
        "task": "add a note",
        "expected_branch": "task/T-7-a1",
        "task_record": record,
        "source": "controller",
        "issued_by": "controller",
        **overrides,
    }


def run(monkeypatch, project, session, **overrides):
    """Run the author path with `session(cwd, prompt)` standing in for claude."""
    seen = {"calls": 0}

    def fake_run_task(binary, prompt, cwd=None):
        seen["calls"] += 1
        seen["cwd"] = Path(cwd)
        seen["prompt"] = prompt
        return session(Path(cwd)) or ("done", 0)

    monkeypatch.setattr(claude_worker, "run_task", fake_run_task)
    queue = Queue()
    claude_worker._execute_author(
        None, "claude", activation(project, **overrides), queue)
    seen["report"] = queue.only
    return seen


def commit_a_note(cwd):
    (cwd / "notes" / "new.txt").write_text("a note\n", encoding="utf-8")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", "add a note")


def canonical_state(project):
    root = project["root"]
    return (git(root, "rev-parse", "HEAD"),
            git(root, "symbolic-ref", "--short", "HEAD"),
            (root / "notes" / "a.txt").read_text(encoding="utf-8"))


# --- The happy path, and where it happened ---------------------------------


def test_the_session_runs_in_a_worktree_not_the_canonical_checkout(
    monkeypatch, project
):
    seen = run(monkeypatch, project, commit_a_note)

    assert seen["cwd"].parent == project["worktrees"]
    assert project["root"] not in seen["cwd"].parents
    assert seen["cwd"] != project["root"]


def test_a_commit_on_the_expected_branch_is_the_candidate(monkeypatch, project):
    seen = run(monkeypatch, project, commit_a_note)
    report = seen["report"]
    tip = git(project["root"], "rev-parse", "refs/heads/task/T-7-a1")

    assert report["outcome"] == "candidate", report
    assert report["payload"]["branch"] == "task/T-7-a1"
    assert report["payload"]["candidate_sha"] == tip
    # From the task's base, not from wherever the checkout happens to be.
    assert git(project["root"], "rev-parse", f"{tip}^") == project["base"]


def test_the_canonical_checkout_is_left_exactly_as_it_was(monkeypatch, project):
    before = canonical_state(project)
    run(monkeypatch, project, commit_a_note)

    assert canonical_state(project) == before


def test_the_worktree_is_removed_and_the_branch_kept(monkeypatch, project):
    seen = run(monkeypatch, project, commit_a_note)

    assert not seen["cwd"].exists()
    git(project["root"], "rev-parse", "--verify", "refs/heads/task/T-7-a1")


def test_the_session_is_told_its_branch_and_base(monkeypatch, project):
    seen = run(monkeypatch, project, commit_a_note)

    assert "task/T-7-a1" in seen["prompt"]
    assert project["base"] in seen["prompt"]
    assert "dedicated git worktree" in seen["prompt"]


# --- A session that reaches outside its worktree ---------------------------


def test_switching_the_canonical_checkout_is_blocked(monkeypatch, project):
    """What attempt 3 of T-CMD-058924af3d did."""
    def session(cwd):
        commit_a_note(cwd)
        git(project["root"], "switch", "-q", "-c", "feat/my-own-name")

    report = run(monkeypatch, project, session)["report"]

    assert report["outcome"] == "blocked", report
    assert "canonical checkout" in report["payload"]["reason"]
    assert "candidate_sha" not in report["payload"]


def test_committing_in_the_canonical_checkout_is_blocked(monkeypatch, project):
    def session(cwd):
        git(project["root"], "commit", "-q", "--allow-empty", "-m", "stray")

    report = run(monkeypatch, project, session)["report"]

    assert report["outcome"] == "blocked", report
    assert "moved during the run" in report["payload"]["reason"]


def test_a_moved_checkout_is_blocked_even_when_the_run_failed(
    monkeypatch, project
):
    def session(cwd):
        git(project["root"], "switch", "-q", "-c", "feat/elsewhere")
        return ("gave up", 1)

    assert run(monkeypatch, project, session)["report"]["outcome"] == "blocked"


# --- A candidate that is not what was asked for ----------------------------


def test_work_on_another_branch_is_not_a_candidate(monkeypatch, project):
    def session(cwd):
        git(cwd, "switch", "-q", "-c", "feat/hub-header-build-id")
        commit_a_note(cwd)

    report = run(monkeypatch, project, session)["report"]

    assert report["outcome"] == "failed", report
    assert "task/T-7-a1" in report["payload"]["reason"]
    assert "candidate_sha" not in report["payload"]


def test_no_commit_is_not_a_candidate(monkeypatch, project):
    report = run(monkeypatch, project, lambda cwd: None)["report"]

    assert report["outcome"] == "failed", report
    assert "no commit" in report["payload"]["reason"]


def test_uncommitted_work_is_not_a_candidate_and_is_kept(monkeypatch, project):
    def session(cwd):
        commit_a_note(cwd)
        (cwd / "notes" / "forgotten.txt").write_text("x\n", encoding="utf-8")

    seen = run(monkeypatch, project, session)

    assert seen["report"]["outcome"] == "failed", seen["report"]
    assert "uncommitted" in seen["report"]["payload"]["reason"]
    assert (seen["cwd"] / "notes" / "forgotten.txt").exists()


def test_a_commit_that_rewrote_the_base_is_not_a_candidate(monkeypatch, project):
    def session(cwd):
        git(cwd, "checkout", "-q", "--orphan", "scratch")
        git(cwd, "commit", "-q", "-m", "unrelated history")
        git(cwd, "branch", "-q", "-D", "task/T-7-a1")
        git(cwd, "branch", "-q", "-m", "task/T-7-a1")

    report = run(monkeypatch, project, session)["report"]

    assert report["outcome"] == "failed", report
    assert "does not descend" in report["payload"]["reason"]


def test_a_failing_run_is_failed(monkeypatch, project):
    def session(cwd):
        commit_a_note(cwd)
        return ("boom", 1)

    assert run(monkeypatch, project, session)["report"]["outcome"] == "failed"


# --- Refused before any model call -----------------------------------------


@pytest.mark.parametrize("overrides,named", [
    ({"expected_branch": ""}, "expected_branch"),
    ({"expected_branch": "task/bad..name"}, "not a valid branch name"),
    ({"record": {"base_sha": "0" * 12}}, "base_sha"),
    ({"record": {"base_sha": "f" * 40}}, "worktree"),
    ({"activation_id": "../escape"}, "worktree name"),
])
def test_an_unusable_activation_is_blocked_before_the_model(
    monkeypatch, project, overrides, named
):
    seen = run(monkeypatch, project, commit_a_note, **overrides)

    assert seen["calls"] == 0
    assert seen["report"]["outcome"] == "blocked"
    assert named in seen["report"]["payload"]["reason"]


def test_an_existing_branch_is_not_built_on(monkeypatch, project):
    git(project["root"], "branch", "task/T-7-a1", project["base"])
    seen = run(monkeypatch, project, commit_a_note)

    assert seen["calls"] == 0
    assert seen["report"]["outcome"] == "blocked"
    assert "already exists" in seen["report"]["payload"]["reason"]


def test_no_author_project_is_blocked_before_the_model(monkeypatch, project):
    monkeypatch.setattr(claude_worker, "AUTHOR_PROJECT", "")
    seen = run(monkeypatch, project, commit_a_note)

    assert seen["calls"] == 0
    assert "AUTHOR_PROJECT" in seen["report"]["payload"]["reason"]
