"""Publishing a candidate, against real git remotes.

The author commits into a private worktree and the worktree is removed once the
commit exists, so the candidate was real and reachable only on the machine that
made it. Every run needed a person to push the branch and open the pull request
between authoring and review.

Neither is a judgment, which is why they are automatable -- and both are
destructive if done carelessly, which is why every refusal here is tested. A
force push would move a rejected candidate that is the evidence for the review
that rejected it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import publication
from publication import PublicationError


def git(repo, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    if check:
        assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"

    return result


def commit(repo, name, text, message):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.git"
    path.mkdir()
    git(path, "init", "-q", "--bare", "-b", "master")
    return path


@pytest.fixture
def local(tmp_path, remote):
    path = tmp_path / "local"
    path.mkdir()
    git(path, "init", "-q", "-b", "master")
    git(path, "config", "user.email", "author@test")
    git(path, "config", "user.name", "Author Test")
    git(path, "remote", "add", "origin", str(remote))
    commit(path, "README.md", "# project\n", "initial")
    git(path, "push", "-q", "origin", "master")
    return path


@pytest.fixture
def candidate(local):
    git(local, "checkout", "-q", "-b", "task/T-1")
    sha = commit(local, "notes/x.md", "authored\n", "T-1: add a note")
    git(local, "checkout", "-q", "master")
    return sha


def remote_branch(remote, name):
    result = git(remote, "rev-parse", f"refs/heads/{name}", check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


# --- Pushing the exact commit -----------------------------------------------


def test_the_candidate_is_published_by_sha(local, remote, candidate):
    result = publication.push_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate
    )

    assert result["pushed"] is True
    assert remote_branch(remote, "task/T-1") == candidate


def test_publishing_the_same_candidate_twice_is_a_no_op(
    local, remote, candidate
):
    """A worker that pushed and then crashed before reporting runs this again
    on redelivery. The natural retry has to be safe."""
    publication.push_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate
    )
    second = publication.push_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate
    )

    assert second["pushed"] is False
    assert second["already_published"] is True
    assert remote_branch(remote, "task/T-1") == candidate


def test_a_branch_at_a_different_commit_is_never_moved(
    local, remote, candidate
):
    """An earlier candidate on this branch is the evidence for the review that
    rejected it. A force push would destroy it."""
    publication.push_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate
    )

    git(local, "checkout", "-q", "task/T-1")
    second = commit(local, "notes/x.md", "different\n", "T-1: attempt two")

    with pytest.raises(PublicationError, match="Refusing to move it"):
        publication.push_candidate(
            str(local), branch="task/T-1", candidate_sha=second
        )

    assert remote_branch(remote, "task/T-1") == candidate


def test_the_published_commit_is_the_one_named_not_the_branch_tip(
    local, remote, candidate
):
    """`git push origin <branch>` publishes whatever the local branch points at
    now, which is the same thing right up until it is not."""
    git(local, "checkout", "-q", "task/T-1")
    commit(local, "notes/x.md", "moved on\n", "local work after the candidate")
    git(local, "checkout", "-q", "master")

    publication.push_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate
    )

    assert remote_branch(remote, "task/T-1") == candidate


def test_an_unreadable_remote_is_not_treated_as_an_absent_branch(
    local, candidate, monkeypatch
):
    monkeypatch.setattr(
        publication, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 1, "", "no such remote"),
    )

    with pytest.raises(PublicationError, match="could not read"):
        publication.push_candidate(
            str(local), branch="task/T-1", candidate_sha=candidate
        )


# --- Finding or opening the pull request ------------------------------------


def gh_returning(monkeypatch, *responses):
    """Answer successive `gh` calls with scripted results."""
    calls = {"n": 0, "args": []}

    def fake(*args):
        calls["args"].append(args)
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        code, out = responses[index]
        return subprocess.CompletedProcess(args, code, out, "" if code == 0 else out)

    monkeypatch.setattr(publication, "_gh", fake)
    return calls


def ensure(**kw):
    args = {"repo_slug": "o/r", "branch": "task/T-1", "base": "master",
            "candidate_sha": "a" * 40, "title": "T-1", "body": "b"}
    args.update(kw)
    return publication.ensure_pull_request(**args)


def test_an_existing_pull_request_for_this_candidate_is_reused(monkeypatch):
    """Opening a second means two places a reviewer might comment, and one of
    them is wrong."""
    gh_returning(monkeypatch, (0, json.dumps(
        [{"number": 3, "headRefOid": "a" * 40, "url": "u", "isDraft": False}]
    )))

    result = ensure()

    assert result == {"pr_number": 3, "pr_url": "u", "created": False}


def test_a_pull_request_is_opened_when_none_exists(monkeypatch):
    calls = gh_returning(
        monkeypatch, (0, "[]"),
        (0, "https://github.com/o/r/pull/12\n"),
    )

    result = ensure()

    assert result["pr_number"] == 12
    assert result["created"] is True
    assert calls["args"][1][1] == "create"


def test_an_existing_pull_request_at_another_commit_is_refused(monkeypatch):
    """It is an earlier review's artifact; attaching this candidate would
    attach this approval to that discussion."""
    gh_returning(monkeypatch, (0, json.dumps(
        [{"number": 3, "headRefOid": "b" * 40, "url": "u", "isDraft": False}]
    )))

    with pytest.raises(PublicationError, match="earlier review"):
        ensure()


def test_several_open_pull_requests_are_refused(monkeypatch):
    gh_returning(monkeypatch, (0, json.dumps([
        {"number": 3, "headRefOid": "a" * 40, "url": "u", "isDraft": False},
        {"number": 4, "headRefOid": "a" * 40, "url": "v", "isDraft": False},
    ])))

    with pytest.raises(PublicationError, match="has no answer"):
        ensure()


def test_a_failed_creation_is_reported(monkeypatch):
    gh_returning(monkeypatch, (0, "[]"), (1, "permission denied"))

    with pytest.raises(PublicationError, match="could not open"):
        ensure()


def test_an_unparseable_pull_request_url_is_refused(monkeypatch):
    gh_returning(monkeypatch, (0, "[]"), (0, "created something\n"))

    with pytest.raises(PublicationError, match="could not read its"):
        ensure()


# --- The two together -------------------------------------------------------


def test_publish_candidate_returns_what_the_next_stages_need(
    local, remote, candidate, monkeypatch
):
    gh_returning(monkeypatch, (0, "[]"), (0, "https://github.com/o/r/pull/5\n"))

    result = publication.publish_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate,
        repo_slug="o/r", target_ref="refs/heads/master", task_id="T-1",
        title="add a note", objective="write the note",
    )

    assert result["candidate_sha"] == candidate
    assert result["branch"] == "task/T-1"
    assert result["pr_number"] == 5
    assert result["base"] == "master"
    assert remote_branch(remote, "task/T-1") == candidate


def test_a_refs_style_target_is_reduced_to_a_branch_name(
    local, remote, candidate, monkeypatch
):
    calls = gh_returning(
        monkeypatch, (0, "[]"), (0, "https://github.com/o/r/pull/5\n")
    )

    publication.publish_candidate(
        str(local), branch="task/T-1", candidate_sha=candidate,
        repo_slug="o/r", target_ref="refs/heads/master", task_id="T-1",
    )

    assert "master" in calls["args"][0]
    assert "refs/heads/master" not in calls["args"][0]
