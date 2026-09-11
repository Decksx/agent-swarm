"""The target race, against real git remotes rather than stubs.

The earlier implementation asked GitHub to merge and then checked the merge
commit's parents. That correctly identified a target that had moved -- after
the unreviewed combined tree was already on the branch. Reconciliation
evidence, not prevention.

The condition and the effect have to be one operation, and only the remote can
perform it. So the merge is built locally from the pinned target, which makes
its first parent the pinned target by construction, and published with a plain
non-force push: a fast-forward if the target is where it was pinned, and
rejected by the remote before anything changes if it is not.

These use real repositories with a real `origin`, because the property under
test is a property of git's ref update, and a stubbed `_git` would be testing
the stub.
"""

from __future__ import annotations

import subprocess

import pytest

import integrator
from integrator import IntegrationRefused, Plan


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
    """A bare repository standing in for the forge."""
    path = tmp_path / "remote.git"
    path.mkdir()
    git(path, "init", "-q", "--bare", "-b", "master")
    return path


@pytest.fixture
def local(tmp_path, remote):
    """A clone with a candidate branch, as the integrator would find it."""
    path = tmp_path / "local"
    path.mkdir()
    git(path, "init", "-q", "-b", "master")
    git(path, "config", "user.email", "integrator@test")
    git(path, "config", "user.name", "Integrator Test")
    git(path, "remote", "add", "origin", str(remote))

    commit(path, "README.md", "# project\n", "initial")
    git(path, "push", "-q", "origin", "master")

    return path


@pytest.fixture
def candidate(local):
    """One approved candidate, on its own branch, pushed."""
    git(local, "checkout", "-q", "-b", "task/T-1")
    sha = commit(local, "notes/added.md", "the approved change\n", "T-1: add a note")
    git(local, "push", "-q", "origin", "task/T-1")
    git(local, "checkout", "-q", "master")
    return sha


def plan_for(local, remote, candidate_sha, target_sha, tmp_path):
    return Plan(
        task_id="T-1",
        repo=str(local),
        candidate_sha=candidate_sha,
        target_ref="refs/heads/master",
        target_sha_expected=target_sha,
        pr_number=1,
    )


def remote_master(remote):
    return git(remote, "rev-parse", "refs/heads/master").stdout.strip()


# --- The ordinary case ------------------------------------------------------


def test_a_merge_onto_an_unmoved_target_lands(local, remote, candidate, tmp_path):
    target = remote_master(remote)
    plan = plan_for(local, remote, candidate, target, tmp_path)

    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))
    integrator.push_if_target_unmoved(plan, merge_sha)

    assert remote_master(remote) == merge_sha


def test_the_built_merge_has_the_pinned_target_as_its_first_parent(
    local, remote, candidate, tmp_path
):
    """By construction, not by a check that could have been overtaken."""
    target = remote_master(remote)
    plan = plan_for(local, remote, candidate, target, tmp_path)

    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))
    parents = git(local, "rev-list", "--parents", "-n", "1", merge_sha).stdout.split()

    assert parents[1] == target
    assert parents[2] == candidate


def test_the_landed_tree_is_the_approved_tree(local, remote, candidate, tmp_path):
    target = remote_master(remote)
    plan = plan_for(local, remote, candidate, target, tmp_path)
    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))
    integrator.push_if_target_unmoved(plan, merge_sha)

    integrator.check_tree_identical(plan, merge_sha)
    integrator.check_merge_parents(plan, merge_sha)


# --- The race, which must now be prevented rather than noticed --------------


def test_a_target_that_moved_rejects_the_push_and_nothing_lands(
    local, remote, candidate, tmp_path
):
    """The whole point.

    The target is pinned, then somebody else's commit lands on it, then the
    integration tries to publish. The remote refuses because the update is no
    longer a fast-forward, and the competing commit is still exactly where it
    was.
    """
    pinned = remote_master(remote)
    plan = plan_for(local, remote, candidate, pinned, tmp_path)

    # The merge is built while the target is still where it was pinned.
    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))

    # Now somebody else lands on master, exactly in the window the earlier
    # implementation could not close.
    other = tmp_path / "other"
    other.mkdir()
    git(other, "clone", "-q", str(remote), ".")
    git(other, "config", "user.email", "other@test")
    git(other, "config", "user.name", "Other Person")
    competing = commit(other, "unrelated.md", "somebody else's work\n", "unrelated")
    git(other, "push", "-q", "origin", "master")

    assert remote_master(remote) == competing

    with pytest.raises(IntegrationRefused, match="nothing landed"):
        integrator.push_if_target_unmoved(plan, merge_sha)

    # The competing commit is untouched and the integration never landed.
    assert remote_master(remote) == competing
    assert remote_master(remote) != merge_sha


def test_the_refusal_says_the_merge_was_not_applied(
    local, remote, candidate, tmp_path
):
    """A refusal here means nothing happened, which is the opposite of what
    the post-merge check could say. The wording has to carry that."""
    pinned = remote_master(remote)
    plan = plan_for(local, remote, candidate, pinned, tmp_path)
    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))

    other = tmp_path / "other"
    other.mkdir()
    git(other, "clone", "-q", str(remote), ".")
    git(other, "config", "user.email", "other@test")
    git(other, "config", "user.name", "Other")
    commit(other, "unrelated.md", "x\n", "unrelated")
    git(other, "push", "-q", "origin", "master")

    with pytest.raises(IntegrationRefused) as raised:
        integrator.push_if_target_unmoved(plan, merge_sha)

    assert "was NOT applied" in str(raised.value)


def test_the_competing_work_survives_a_refused_integration(
    local, remote, candidate, tmp_path
):
    """A force push would have destroyed it. A refused fast-forward cannot."""
    pinned = remote_master(remote)
    plan = plan_for(local, remote, candidate, pinned, tmp_path)
    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))

    other = tmp_path / "other"
    other.mkdir()
    git(other, "clone", "-q", str(remote), ".")
    git(other, "config", "user.email", "other@test")
    git(other, "config", "user.name", "Other")
    commit(other, "precious.md", "work that must not be lost\n", "precious")
    git(other, "push", "-q", "origin", "master")
    competing = remote_master(remote)

    with pytest.raises(IntegrationRefused):
        integrator.push_if_target_unmoved(plan, merge_sha)

    contents = git(
        remote, "show", f"{competing}:precious.md"
    ).stdout

    assert "must not be lost" in contents


# --- A conflict is refused, never resolved ----------------------------------


def test_a_conflicting_candidate_is_refused_and_leaves_no_worktree(
    local, remote, tmp_path
):
    """The tree that would land after a resolution is not the tree that was
    reviewed."""
    git(local, "checkout", "-q", "-b", "task/T-2")
    conflicting = commit(local, "README.md", "# theirs\n", "T-2: rewrite")
    git(local, "checkout", "-q", "master")
    commit(local, "README.md", "# ours\n", "master moves")
    git(local, "push", "-q", "origin", "master")

    plan = plan_for(local, remote, conflicting, remote_master(remote), tmp_path)
    work = tmp_path / "work"

    with pytest.raises(IntegrationRefused, match="will not resolve it"):
        integrator.build_merge(plan, work_root=str(work))

    leftover = list(work.glob("integrate-*")) if work.exists() else []

    assert leftover == []


def test_the_canonical_checkout_is_never_written_to(
    local, remote, candidate, tmp_path
):
    """It is permanently dirty with somebody else's work in progress."""
    (local / "scratch.txt").write_text("unsaved work\n", encoding="utf-8")
    before = git(local, "status", "--porcelain").stdout
    head_before = git(local, "rev-parse", "HEAD").stdout.strip()

    plan = plan_for(local, remote, candidate, remote_master(remote), tmp_path)
    merge_sha = integrator.build_merge(plan, work_root=str(tmp_path / "work"))
    integrator.push_if_target_unmoved(plan, merge_sha)

    assert git(local, "status", "--porcelain").stdout == before
    assert git(local, "rev-parse", "HEAD").stdout.strip() == head_before
