"""Which checkout, and which commit, must be configuration.

The incident these come from: a snapshot was generated against a real checkout
of the real project, on a feature branch, six weeks stale, with fourteen
uncommitted files. Nothing was malformed. `repo_id` could not have caught it --
both checkouts have the same lineage and therefore the same id, which is
correct. Only an explicit statement of which path is authoritative can.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import repo_registry
import repo_snapshot
import worktrees
from repo_registry import RegistryError, ResolutionError


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


def commit_file(repo, name, text, message="c"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def canonical(tmp_path):
    """A checkout shaped like the real one: on a feature branch, dirty."""
    root = tmp_path / "canonical"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "registry@test")
    git(root, "config", "user.name", "Registry Test")
    commit_file(root, "README.md", "# project\n", "initial")
    baseline = commit_file(root, "src/thing.py", "VALUE = 1\n", "on master")

    # Somebody is mid-task: another branch, checked out, with unsaved work.
    git(root, "checkout", "-q", "-b", "feature/in-progress")
    commit_file(root, "src/other.py", "x = 1\n", "work in progress")
    (root / "src" / "thing.py").write_text("VALUE = 999\n", encoding="utf-8")
    (root / "scratch.log").write_text("noise\n", encoding="utf-8")

    assert baseline  # the commit master points at; see the `baseline` fixture
    return root


@pytest.fixture
def baseline(canonical):
    """The commit the planning ref points at -- not the one checked out."""
    return git(canonical, "rev-parse", "refs/heads/master").strip()


@pytest.fixture
def registry_file(tmp_path, canonical):
    path = tmp_path / "repos.json"
    path.write_text(json.dumps({
        "demo": {
            "path": str(canonical),
            "repo_id": repo_snapshot.repo_id(str(canonical)),
            "planning_ref": "refs/heads/master",
            "worktree_root": str(tmp_path / "worktrees" / "demo"),
        }
    }), encoding="utf-8")
    return path


# --- The registry as configuration ------------------------------------------


def test_a_registered_project_resolves_to_one_sha(baseline, registry_file):
    resolved = repo_registry.resolve_name("demo", registry_file)

    assert resolved.sha == baseline
    assert len(resolved.sha) == 40
    assert resolved.ref == "refs/heads/master"


def test_the_planning_ref_wins_over_the_checked_out_branch(
    canonical, registry_file
):
    """The whole point. The checkout is on a feature branch; master is the base."""
    resolved = repo_registry.resolve_name("demo", registry_file)
    working_head = git(canonical, "rev-parse", "HEAD").strip()

    assert working_head != resolved.sha
    assert resolved.sha == git(canonical, "rev-parse", "refs/heads/master").strip()


def test_an_unregistered_name_is_refused_and_names_what_exists(registry_file):
    with pytest.raises(RegistryError, match="Registered: demo"):
        repo_registry.resolve_name("comicautomation", registry_file)


def test_a_bare_ref_name_is_refused(tmp_path, canonical):
    """`master` can name a branch and a tag at once.

    Git resolves that with a warning on stderr no automated caller reads, so
    the ambiguity is refused at the point it is written down instead.
    """
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({
        "demo": {
            "path": str(canonical),
            "repo_id": "whatever",
            "planning_ref": "master",
            "worktree_root": str(tmp_path / "w"),
        }
    }), encoding="utf-8")

    with pytest.raises(RegistryError, match="full refname"):
        repo_registry.load(path)


def test_a_worktree_root_inside_the_checkout_is_refused(tmp_path, canonical):
    """Task worktrees would show up in the checkout's own status."""
    path = tmp_path / "nested.json"
    path.write_text(json.dumps({
        "demo": {
            "path": str(canonical),
            "repo_id": "whatever",
            "planning_ref": "refs/heads/master",
            "worktree_root": str(canonical / "worktrees"),
        }
    }), encoding="utf-8")

    with pytest.raises(RegistryError, match="inside the canonical checkout"):
        repo_registry.load(path)


@pytest.mark.parametrize("missing", ["path", "repo_id", "planning_ref", "worktree_root"])
def test_every_field_is_required(tmp_path, canonical, missing):
    entry = {
        "path": str(canonical),
        "repo_id": "x",
        "planning_ref": "refs/heads/master",
        "worktree_root": str(tmp_path / "w"),
    }
    del entry[missing]

    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"demo": entry}), encoding="utf-8")

    with pytest.raises(RegistryError, match=missing):
        repo_registry.load(path)


# --- The three refusals -----------------------------------------------------


def test_a_checkout_that_is_not_there_is_unavailable_not_empty(tmp_path):
    """A drive that did not mount otherwise reads as a project with no files."""
    path = tmp_path / "gone.json"
    path.write_text(json.dumps({
        "demo": {
            "path": str(tmp_path / "not-here"),
            "repo_id": "x",
            "planning_ref": "refs/heads/master",
            "worktree_root": str(tmp_path / "w"),
        }
    }), encoding="utf-8")

    with pytest.raises(ResolutionError, match="does not exist"):
        repo_registry.resolve_name("demo", path)


def test_a_different_repository_at_the_registered_path_is_refused(
    tmp_path, canonical, registry_file
):
    """The path still works for every command except the one that matters."""
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "master")
    git(other, "config", "user.email", "o@test")
    git(other, "config", "user.name", "O")
    commit_file(other, "README.md", "# different project\n", "initial")

    entry = json.loads(registry_file.read_text(encoding="utf-8"))
    entry["demo"]["path"] = str(other)
    registry_file.write_text(json.dumps(entry), encoding="utf-8")

    with pytest.raises(ResolutionError, match="contains repository"):
        repo_registry.resolve_name("demo", registry_file)


def test_a_missing_planning_ref_does_not_fall_back_to_head(
    canonical, registry_file
):
    """A renamed default branch is the original mistake with an extra step."""
    entry = json.loads(registry_file.read_text(encoding="utf-8"))
    entry["demo"]["planning_ref"] = "refs/heads/main"
    registry_file.write_text(json.dumps(entry), encoding="utf-8")

    with pytest.raises(ResolutionError, match="does not exist"):
        repo_registry.resolve_name("demo", registry_file)


# --- The snapshot reads the baseline, not the checkout ----------------------


def test_the_snapshot_describes_the_planning_ref(baseline, registry_file):
    resolved = repo_registry.resolve_name("demo", registry_file)
    snapshot = repo_snapshot.build(resolved)

    assert snapshot["base_sha"] == baseline
    assert snapshot["project"] == "demo"
    assert snapshot["planning_ref"] == "refs/heads/master"


def test_a_file_committed_only_on_the_feature_branch_is_not_in_the_tree(
    canonical, registry_file
):
    """It is committed, and it is still not in the baseline."""
    snapshot = repo_snapshot.build(repo_registry.resolve_name("demo", registry_file))

    assert "src/thing.py" in snapshot["tree"]["files"]
    assert "src/other.py" not in snapshot["tree"]["files"]


def test_working_tree_edits_never_reach_the_baseline(canonical, registry_file):
    """thing.py says 999 on disk and 1 in the baseline."""
    snapshot = repo_snapshot.build(
        repo_registry.resolve_name("demo", registry_file),
        documents=["src/thing.py"],
    )
    doc = next(d for d in snapshot["documents"] if d["path"] == "src/thing.py")

    assert "VALUE = 1" in doc["text"]
    assert "999" not in doc["text"]


def test_an_empty_baseline_is_refused(tmp_path):
    """An empty manifest renders as a perfectly valid description of nothing."""
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "e@test")
    git(root, "config", "user.name", "E")
    git(root, "commit", "-q", "--allow-empty", "-m", "no files")

    path = tmp_path / "empty.json"
    path.write_text(json.dumps({
        "demo": {
            "path": str(root),
            "repo_id": repo_snapshot.repo_id(str(root)),
            "planning_ref": "refs/heads/master",
            "worktree_root": str(tmp_path / "w"),
        }
    }), encoding="utf-8")

    resolved = repo_registry.resolve_name("demo", path)

    with pytest.raises(repo_snapshot.SnapshotError, match="contains no files"):
        repo_snapshot.build(resolved)


# --- Operational context, kept out of the baseline --------------------------


def test_the_checkouts_own_state_is_reported_separately(canonical, registry_file):
    snapshot = repo_snapshot.build(repo_registry.resolve_name("demo", registry_file))
    operational = snapshot["operational"]

    assert operational["checkout_branch"] == "feature/in-progress"
    assert operational["checkout_head_is_baseline"] is False
    assert operational["uncommitted"]["count"] == 2


def test_branches_ahead_of_the_baseline_are_reported(canonical, registry_file):
    snapshot = repo_snapshot.build(repo_registry.resolve_name("demo", registry_file))
    ahead = {row["branch"]: row for row in snapshot["operational"]["branches_ahead"]}

    assert "feature/in-progress" in ahead
    assert ahead["feature/in-progress"]["ahead"] == 1
    assert "master" not in ahead


def test_the_rendered_document_fences_the_operational_section(
    canonical, registry_file
):
    """A planner that reads a modified path as an existing file has read
    work in progress as fact."""
    rendered = repo_snapshot.render(
        repo_snapshot.build(repo_registry.resolve_name("demo", registry_file))
    )

    assert "OPERATIONAL CONTEXT -- NOT PART OF THE BASELINE" in rendered
    assert "NOT the baseline" in rendered

    baseline_section, _, operational_section = rendered.partition(
        "OPERATIONAL CONTEXT"
    )
    # The dirty paths appear only after the fence.
    assert "scratch.log" not in baseline_section
    assert "scratch.log" in operational_section


def test_a_worktree_whose_path_is_gone_is_reported_not_pruned(
    canonical, registry_file, tmp_path
):
    """The real checkout carries seven of these from a cloud session.

    Pruning is destructive and is the operator's call; a locked worktree is
    locked because somebody meant it.
    """
    elsewhere = tmp_path / "elsewhere"
    git(canonical, "worktree", "add", "-q", "--detach", str(elsewhere), "master")
    git(canonical, "worktree", "lock", str(elsewhere))
    __import__("shutil").rmtree(elsewhere)

    snapshot = repo_snapshot.build(repo_registry.resolve_name("demo", registry_file))
    rows = {row["path"].replace("\\", "/"): row for row in snapshot["operational"]["worktrees"]}
    row = rows[str(elsewhere).replace("\\", "/")]

    assert row["present"] is False
    assert row["locked"] is True
    assert "PATH NOT ON THIS MACHINE" in repo_snapshot.render(snapshot)


# --- Execution happens elsewhere --------------------------------------------


def test_a_worktree_is_created_clean_at_the_baseline(canonical, registry_file):
    project = repo_registry.get("demo", registry_file)
    resolved = repo_registry.resolve(project)
    path = worktrees.create(project, resolved.sha, "T-1")

    assert path.exists()
    assert git(path, "rev-parse", "HEAD").strip() == resolved.sha
    assert git(path, "status", "--porcelain") == ""
    # The baseline's content, not the checkout's.
    assert (path / "src" / "thing.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (path / "src" / "other.py").exists()


def test_creating_a_worktree_does_not_touch_the_canonical_checkout(
    canonical, registry_file
):
    """The one thing that must never happen: somebody's work disturbed."""
    project = repo_registry.get("demo", registry_file)
    resolved = repo_registry.resolve(project)

    before_head = git(canonical, "rev-parse", "HEAD").strip()
    before_branch = git(canonical, "rev-parse", "--abbrev-ref", "HEAD").strip()
    before_status = git(canonical, "status", "--porcelain")
    before_thing = (canonical / "src" / "thing.py").read_text(encoding="utf-8")

    worktrees.create(project, resolved.sha, "T-2")

    assert git(canonical, "rev-parse", "HEAD").strip() == before_head
    assert git(canonical, "rev-parse", "--abbrev-ref", "HEAD").strip() == before_branch
    assert git(canonical, "status", "--porcelain") == before_status
    assert (canonical / "src" / "thing.py").read_text(encoding="utf-8") == before_thing


def test_an_existing_worktree_is_not_reused(canonical, registry_file):
    project = repo_registry.get("demo", registry_file)
    resolved = repo_registry.resolve(project)
    worktrees.create(project, resolved.sha, "T-3")

    with pytest.raises(worktrees.WorktreeError, match="refusing to reuse"):
        worktrees.create(project, resolved.sha, "T-3")


def test_a_removed_worktree_frees_the_name(canonical, registry_file):
    project = repo_registry.get("demo", registry_file)
    resolved = repo_registry.resolve(project)
    worktrees.create(project, resolved.sha, "T-4")

    assert worktrees.remove(project, "T-4") is True
    assert worktrees.create(project, resolved.sha, "T-4").exists()


@pytest.mark.parametrize("name", [
    "../escape", "a/b", "C:\\x", "", ".hidden", "x" * 80, "with space",
])
def test_a_name_that_is_not_an_identifier_is_refused(name):
    with pytest.raises(worktrees.WorktreeError):
        worktrees.check_name(name)


def test_only_this_modules_worktrees_are_listed(canonical, registry_file, tmp_path):
    """The checkout's other registrations belong to somebody else."""
    project = repo_registry.get("demo", registry_file)
    resolved = repo_registry.resolve(project)
    worktrees.create(project, resolved.sha, "T-5")
    git(canonical, "worktree", "add", "-q", "--detach",
        str(tmp_path / "unrelated"), "master")

    assert worktrees.existing(project) == ["T-5"]


# --- Closed to planning, not retired ----------------------------------------
#
# The demonstration repository holds a rejected candidate that is the evidence
# for the review that rejected it. A planner shown that entry would see a small
# tidy repository and plan against it, and the first new task would start
# moving the evidence. These are what stops that without deleting the entry --
# because deleting it also takes the record of which checkout was used.


@pytest.fixture
def closed_registry(tmp_path, canonical, registry_file):
    """The same registry, with the project closed to new planning."""
    raw = json.loads(registry_file.read_text(encoding="utf-8"))
    raw["demo"]["plannable"] = False
    registry_file.write_text(json.dumps(raw), encoding="utf-8")
    return registry_file


def test_an_entry_is_plannable_unless_it_says_otherwise(registry_file):
    assert repo_registry.get("demo", registry_file).plannable is True


def test_a_planner_is_refused_a_project_closed_to_planning(closed_registry):
    with pytest.raises(repo_registry.NotPlannable, match="plannable"):
        repo_registry.resolve_name("demo", closed_registry, for_planning=True)


def test_authoring_and_review_still_resolve_a_closed_project(
    baseline, closed_registry
):
    """The flag closes new work, not work already recorded against it.

    A task in flight against a closed project must still be authorable and
    reviewable, or closing a project would strand whatever is mid-cycle in it.
    """
    resolved = repo_registry.resolve_name("demo", closed_registry)

    assert resolved.sha == baseline


def test_the_refusal_is_distinguishable_from_something_being_broken(
    closed_registry
):
    """NotPlannable is a ResolutionError, but not every ResolutionError is it.

    A caller reporting "this project is unavailable" for a project that is
    merely closed would send somebody looking for a mount that never failed.
    """
    with pytest.raises(ResolutionError) as raised:
        repo_registry.resolve_name("demo", closed_registry, for_planning=True)

    assert isinstance(raised.value, repo_registry.NotPlannable)


@pytest.mark.parametrize("value", ["false", "no", 0, 1, None, []])
def test_a_non_boolean_plannable_is_refused_rather_than_coerced(
    tmp_path, canonical, registry_file, value
):
    """`"false"` is a true string. A permission does not guess.

    Every value here is one somebody could plausibly write meaning "closed",
    and several of them are truthy. Reading any of them as a boolean would
    make the widest reading the most likely accident.
    """
    raw = json.loads(registry_file.read_text(encoding="utf-8"))
    raw["demo"]["plannable"] = value
    registry_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RegistryError, match="plannable"):
        repo_registry.get("demo", registry_file)
