"""A snapshot must be honest about its own gaps.

The interesting failures here are not crashes. They are a snapshot that shows
an archived copy of a document under the live document's name, one that lists a
file an author will not find at the base commit, and one whose silence about
the test suite reads as a passing suite. Each of those produces a plan that
looks fine and is built on something that is not there.
"""

from __future__ import annotations

import subprocess

import pytest

import repo_snapshot
from repo_snapshot import SnapshotError


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


def write(repo, relative, text):
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def init(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "snapshot@test")
    git(root, "config", "user.name", "Snapshot Test")
    return root


def commit(repo, message="commit"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    """A small project: a README, a doc, some source, an archived copy."""
    root = init(tmp_path / "project")
    write(root, "README.md", "# Project\n\nWhat it is.\n")
    write(root, "docs/architecture.md", "# Architecture\n\nHow it fits.\n")
    write(root, "docs/status.md", "# Status\n\nMilestone 3 in progress.\n")
    write(root, "src/thing.py", "def thing():\n    return 1\n")
    write(root, "tests/test_thing.py", "def test_thing():\n    assert True\n")
    write(root, "archive/2025/README.md", "# OLD -- do not use\n")
    commit(root, "initial")
    return root


# --- Identity ---------------------------------------------------------------


def test_repo_id_is_stable(repo):
    assert repo_snapshot.repo_id(str(repo)) == repo_snapshot.repo_id(str(repo))


def test_a_clone_has_the_same_repo_id(repo, tmp_path):
    """The id follows the history, not the path.

    The same project is snapshotted from a different directory on every host
    and again in every worktree; an id that changed with the path would reject
    every plan that crossed a machine.
    """
    clone = tmp_path / "elsewhere"
    git(tmp_path, "clone", "-q", str(repo), str(clone))

    assert repo_snapshot.repo_id(str(clone)) == repo_snapshot.repo_id(str(repo))


def test_a_different_project_has_a_different_repo_id(repo, tmp_path):
    other = init(tmp_path / "other")
    write(other, "README.md", "# Project\n\nWhat it is.\n")
    commit(other, "initial")

    assert repo_snapshot.repo_id(str(other)) != repo_snapshot.repo_id(str(repo))


def test_the_head_sha_is_the_full_commit(repo):
    snapshot = repo_snapshot.build(str(repo))

    assert snapshot["head_sha"] == git(repo, "rev-parse", "HEAD").strip()
    assert len(snapshot["head_sha"]) == 40
    assert snapshot["branch"] == "main"
    assert snapshot["detached"] is False


def test_a_detached_head_is_reported_as_detached(repo):
    git(repo, "checkout", "-q", "--detach", "HEAD")
    snapshot = repo_snapshot.build(str(repo))

    assert snapshot["detached"] is True
    assert snapshot["branch"] == ""
    assert "detached" in repo_snapshot.render(snapshot)


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(SnapshotError):
        repo_snapshot.build(str(tmp_path))


def test_a_repository_with_no_commits_is_refused(tmp_path):
    """There is no base to plan against, and inventing one is worse."""
    empty = init(tmp_path / "empty")

    with pytest.raises(SnapshotError):
        repo_snapshot.build(str(empty))


# --- The tree is the commit's tree ------------------------------------------


def test_the_tree_lists_the_committed_files(repo):
    listing = repo_snapshot.build(str(repo))["tree"]

    assert "src/thing.py" in listing["files"]
    assert listing["file_count"] == 6
    assert listing["directories"]["docs"] == 2
    assert listing["directories"]["(repository root)"] == 1


def test_an_untracked_file_is_not_in_the_tree(repo):
    """An author branching from HEAD will not find it there."""
    write(repo, "src/scratch.py", "x = 1\n")
    snapshot = repo_snapshot.build(str(repo))

    assert "src/scratch.py" not in snapshot["tree"]["files"]
    assert any("scratch" in entry for entry in snapshot["uncommitted"]["entries"])
    assert snapshot["uncommitted"]["clean"] is False


def test_a_clean_worktree_says_so(repo):
    snapshot = repo_snapshot.build(str(repo))

    assert snapshot["uncommitted"]["clean"] is True
    assert snapshot["uncommitted"]["count"] == 0
    assert "clean" in repo_snapshot.render(snapshot)


def test_uncommitted_changes_are_stated_in_the_omissions(repo):
    """The whole document describes a commit the disk no longer matches."""
    write(repo, "src/thing.py", "def thing():\n    return 2\n")
    snapshot = repo_snapshot.build(str(repo))

    assert any("uncommitted" in line for line in snapshot["omissions"])


def test_the_file_list_is_budgeted_and_the_cut_is_reported(repo):
    for index in range(30):
        write(repo, f"src/generated_{index}.py", "x = 1\n")

    commit(repo, "many files")
    snapshot = repo_snapshot.build(str(repo), file_budget=10)
    listing = snapshot["tree"]

    assert len(listing["files"]) == 10
    assert listing["files_truncated"] is True
    # The count and the directory summary still describe the whole tree.
    assert listing["file_count"] == 36
    assert listing["directories"]["src"] == 31
    assert any("file list" in line for line in snapshot["omissions"])
    assert "LIST TRUNCATED" in repo_snapshot.render(snapshot)


# --- Which documents ---------------------------------------------------------


def test_patterns_are_anchored_at_the_repository_root(repo):
    """`README.md` must not pull in `archive/2025/README.md`.

    `PurePosixPath.match` anchors a relative pattern at the right-hand end, so
    the obvious implementation includes the archived copy -- and a snapshot
    that shows an old document under the live name cannot be corrected by the
    omissions list, because nothing was omitted.
    """
    selected = repo_snapshot.select_documents(
        str(repo), git(repo, "rev-parse", "HEAD").strip()
    )

    assert "README.md" in selected
    assert "archive/2025/README.md" not in selected


def test_a_star_does_not_cross_a_directory_boundary():
    assert repo_snapshot.matches_pattern("docs/a.md", "docs/*.md")
    assert not repo_snapshot.matches_pattern("docs/deep/a.md", "docs/*.md")
    assert not repo_snapshot.matches_pattern("a/README.md", "README.md")


def test_named_documents_come_first_and_in_the_order_given(repo):
    selected = repo_snapshot.select_documents(
        str(repo),
        git(repo, "rev-parse", "HEAD").strip(),
        named=["docs/status.md", "src/thing.py"],
    )

    assert selected[:2] == ["docs/status.md", "src/thing.py"]
    assert selected.count("docs/status.md") == 1


def test_a_named_document_that_is_not_in_the_commit_is_reported(repo):
    snapshot = repo_snapshot.build(str(repo), documents=["docs/nope.md"])

    assert [d["path"] for d in snapshot["documents"]].count("docs/nope.md") == 0
    assert any("docs/nope.md" in line for line in snapshot["omissions"])


def test_documents_are_read_from_the_commit_not_the_disk(repo):
    """And the reader is told the disk has moved on.

    Reading the working copy would put uncommitted prose in a snapshot whose
    every other statement is about `head_sha`.
    """
    write(repo, "docs/status.md", "# Status\n\nSECRET UNCOMMITTED EDIT\n")
    snapshot = repo_snapshot.build(str(repo))
    status = next(d for d in snapshot["documents"] if d["path"] == "docs/status.md")

    assert "SECRET UNCOMMITTED EDIT" not in status["text"]
    assert "Milestone 3" in status["text"]
    assert status["modified_in_working_copy"] is True
    assert "EDITED SINCE THIS COMMIT" in repo_snapshot.render(snapshot)


# --- Budgets are reported, not hidden ----------------------------------------


def test_a_long_document_is_truncated_and_says_so(repo):
    """A per-document budget below the stub floor still truncates.

    The floor exists to stop an accidental remainder producing a fragment
    nobody can use, not to overrule a caller that asked for openings.
    """
    write(repo, "docs/architecture.md", "# Architecture\n" + ("detail\n" * 4000))
    commit(repo, "long doc")
    snapshot = repo_snapshot.build(str(repo), doc_budget=500)
    doc = next(d for d in snapshot["documents"] if d["path"] == "docs/architecture.md")

    assert doc["truncated"] is True
    assert len(doc["text"].encode("utf-8")) <= 500
    assert doc["bytes"] > 500
    assert any("architecture.md" in line for line in snapshot["omissions"])
    assert "TRUNCATED" in repo_snapshot.render(snapshot)


def test_documents_that_do_not_fit_are_named_with_their_size(repo):
    """So a planner can ask for one instead of inventing what it said."""
    write(repo, "docs/architecture.md", "# Architecture\n" + ("detail\n" * 2000))
    commit(repo, "long doc")
    snapshot = repo_snapshot.build(
        str(repo), doc_budget=2_000, total_doc_budget=1_500
    )

    # architecture.md came first alphabetically and spent the budget.
    included = [d["path"] for d in snapshot["documents"]]
    assert "docs/architecture.md" in included
    assert "docs/status.md" not in included

    omission = next(line for line in snapshot["omissions"] if "status.md" in line)
    assert "bytes" in omission


def test_a_document_is_left_out_rather_than_shown_as_a_stub(repo):
    """A title and half a sentence is not evidence, but it reads like some."""
    write(repo, "docs/architecture.md", "# Architecture\n" + ("detail\n" * 200))
    commit(repo, "long doc")
    snapshot = repo_snapshot.build(
        str(repo), doc_budget=2_000, total_doc_budget=1_450
    )

    included = [d["path"] for d in snapshot["documents"]]
    assert "docs/architecture.md" in included
    assert "docs/status.md" not in included

    omission = next(line for line in snapshot["omissions"] if "status.md" in line)
    assert "too little to show usefully" in omission


def test_the_uncommitted_list_is_budgeted(repo):
    for index in range(20):
        write(repo, f"scratch_{index}.txt", "x\n")

    snapshot = repo_snapshot.build(str(repo), dirty_budget=5)

    assert snapshot["uncommitted"]["count"] == 20
    assert len(snapshot["uncommitted"]["entries"]) == 5
    assert snapshot["uncommitted"]["entries_truncated"] is True
    assert any("uncommitted changes" in line for line in snapshot["omissions"])


def test_source_is_never_included_and_that_is_stated(repo):
    snapshot = repo_snapshot.build(str(repo))

    assert any("file contents" in line for line in snapshot["omissions"])


# --- Test status is reported, never assumed ----------------------------------


def test_no_suite_run_is_recorded_as_unknown(repo):
    snapshot = repo_snapshot.build(str(repo))

    assert snapshot["tests"]["status"] == "not_run"

    rendered = repo_snapshot.render(snapshot)
    assert "not run" in rendered
    # The distinction that matters: silence is not a pass.
    assert any(
        "not the same as passing" in line for line in snapshot["omissions"]
    )


def test_a_passing_command_is_recorded_as_passed(repo):
    result = repo_snapshot.run_tests(str(repo), "python -c \"print('9 passed')\"")

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert "9 passed" in result["output"]


def test_a_failing_command_is_recorded_as_failed(repo):
    result = repo_snapshot.run_tests(str(repo), "python -c \"raise SystemExit(3)\"")

    assert result["status"] == "failed"
    assert result["exit_code"] == 3

    snapshot = repo_snapshot.build(str(repo), tests=result)
    assert "failed" in repo_snapshot.render(snapshot)


def test_test_output_keeps_the_tail(repo):
    """The failure summary is at the end; the head of a pytest run is dots."""
    command = (
        "python -c \"print('dot ' * 4000); print('THE FAILURE SUMMARY')\""
    )
    result = repo_snapshot.run_tests(str(repo), command, budget=200)

    assert result["output_truncated"] is True
    assert "THE FAILURE SUMMARY" in result["output"]


def test_a_timed_out_suite_is_an_error_not_a_failure(repo):
    """`error` and `failed` are different facts.

    A suite that never finished says nothing about the code; recording it as
    a failure would put a verdict on a run that produced none.
    """
    result = repo_snapshot.run_tests(str(repo), "python -c \"import time; time.sleep(5)\"", timeout=0.5)

    assert result["status"] == "error"
    assert result["exit_code"] is None


# --- The rendered document ---------------------------------------------------


def test_the_rendered_document_carries_the_identity(repo):
    snapshot = repo_snapshot.build(str(repo))
    rendered = repo_snapshot.render(snapshot)

    assert snapshot["head_sha"] in rendered
    assert snapshot["repo_id"] in rendered
    assert "OMITTED OR TRUNCATED" in rendered
    assert "docs/status.md" in rendered
    assert "Milestone 3 in progress." in rendered


def test_the_snapshot_survives_a_round_trip_through_json(repo):
    """It is written to the ledger beside the plan it produced."""
    import json

    snapshot = repo_snapshot.build(str(repo))
    restored = json.loads(json.dumps(snapshot))

    assert repo_snapshot.render(restored) == repo_snapshot.render(snapshot)
