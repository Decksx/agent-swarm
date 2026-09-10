"""Turning an API model's answer into a commit, and refusing to when it isn't one.

Every path in this module arrives from a model. It is data that came over the
network from a system whose output nobody has reviewed, and the process acting
on it holds write access to a repository. So the path tests are the important
half of this file, and they check the resolved location rather than scanning
the string -- a string check misses symlinks, misses Windows drive-relative
forms, and misses anything the filesystem normalises differently than the
checker does.
"""

from __future__ import annotations

import subprocess

import pytest

import authored_change


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "test")
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "seed")
    return path


ANSWER = f"""Here is the change.

FILE: notes/hello.txt
{authored_change.BEGIN}
first line
second line
{authored_change.END}
"""


# --- Parsing ----------------------------------------------------------------


def test_a_well_formed_answer_yields_path_and_contents():
    files = authored_change.parse_files(ANSWER)

    assert files == [("notes/hello.txt", "first line\nsecond line\n")]


def test_prose_around_the_blocks_is_ignored():
    """Models explain themselves. That must not break the parse."""
    files = authored_change.parse_files(
        "I'll create the file.\n" + ANSWER + "\nLet me know if you need more."
    )

    assert len(files) == 1


def test_several_files_are_returned_in_order():
    answer = "".join(
        f"FILE: f{n}.txt\n{authored_change.BEGIN}\nbody {n}\n{authored_change.END}\n"
        for n in range(3)
    )

    assert [p for p, _ in authored_change.parse_files(answer)] == [
        "f0.txt", "f1.txt", "f2.txt"
    ]


def test_a_missing_terminator_is_an_error_not_a_truncated_file():
    """Reading to end-of-answer would turn a cut-off reply into a whole file.

    That is the failure worth refusing: the commit would look complete and the
    file would be missing whatever came after the truncation.
    """
    with pytest.raises(authored_change.AuthoringError, match="truncated"):
        authored_change.parse_files(
            f"FILE: a.txt\n{authored_change.BEGIN}\nbody without an end"
        )


def test_an_answer_with_no_blocks_raises_rather_than_returning_nothing():
    """"Wrote nothing applicable" and "produced an empty change" are different.

    Only one of them is a task that succeeded, so they must not both be an
    empty list.
    """
    with pytest.raises(authored_change.AuthoringError, match="no FILE blocks"):
        authored_change.parse_files("I have thought about it and I would do X.")


def test_an_explicit_refusal_is_surfaced():
    with pytest.raises(authored_change.AuthoringError, match="cannot be done"):
        authored_change.parse_files("CANNOT_AUTHOR: this cannot be done by writing files")


@pytest.mark.parametrize("text", ["", "   ", None])
def test_an_empty_answer_raises(text):
    with pytest.raises(authored_change.AuthoringError):
        authored_change.parse_files(text)


# --- Path safety ------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    "../outside.txt",
    "notes/../../outside.txt",
    ".git/config",
    "notes/../.git/hooks/pre-commit",
    "C:/Windows/System32/x.txt",
    "C:relative.txt",
    "",
    "   ",
])
def test_a_path_that_would_escape_is_refused(repo, bad):
    """Refused, not sanitised.

    Sanitising invites an argument about whether the sanitiser is complete.
    Refusing does not, and a model that wanted to write outside the repository
    has no legitimate reason to.
    """
    with pytest.raises(authored_change.UnsafePath):
        authored_change.safe_relative_path(repo, bad)


@pytest.mark.parametrize("good", [
    "a.txt", "notes/a.txt", "a/b/c/d.txt", "notes\\windows_style.txt",
])
def test_an_ordinary_relative_path_is_allowed(repo, good):
    resolved = authored_change.safe_relative_path(repo, good)

    assert resolved.is_relative_to(repo.resolve())


def test_the_repository_root_itself_is_refused(repo):
    with pytest.raises(authored_change.UnsafePath):
        authored_change.safe_relative_path(repo, ".")


# --- Applying ---------------------------------------------------------------


def test_a_change_lands_on_a_new_branch_with_a_full_sha(repo):
    result = authored_change.apply_and_commit(
        repo, branch="task/T-1",
        files=[("notes/hello.txt", "hi\n")], message="T-1: add a note",
    )

    assert result["branch"] == "task/T-1"
    assert len(result["candidate_sha"]) == 40
    assert len(result["base_sha"]) == 40
    assert result["files"] == ["notes/hello.txt"]
    assert (repo / "notes" / "hello.txt").read_text(encoding="utf-8") == "hi\n"


def test_main_is_left_alone(repo):
    before = git(repo, "rev-parse", "main")

    authored_change.apply_and_commit(
        repo, branch="task/T-1", files=[("a.txt", "x\n")], message="m",
    )

    assert git(repo, "rev-parse", "main") == before


def test_an_existing_branch_is_refused(repo):
    """A retry must not build on the previous attempt and report the sum.

    That is precisely the ambiguity the immutable review range exists to
    remove, so allowing it here would reintroduce it one layer down.
    """
    authored_change.apply_and_commit(
        repo, branch="task/T-1", files=[("a.txt", "x\n")], message="m",
    )

    with pytest.raises(authored_change.AuthoringError, match="already exists"):
        authored_change.apply_and_commit(
            repo, branch="task/T-1", files=[("b.txt", "y\n")], message="m",
        )


def test_an_unsafe_path_stops_the_whole_change(repo):
    """Validated before anything is written, so nothing is half-applied."""
    with pytest.raises(authored_change.UnsafePath):
        authored_change.apply_and_commit(
            repo, branch="task/T-2",
            files=[("ok.txt", "x\n"), ("../escape.txt", "y\n")], message="m",
        )

    assert not (repo / "ok.txt").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_writing_identical_content_is_an_error_not_an_empty_commit(repo):
    with pytest.raises(authored_change.AuthoringError, match="nothing to commit"):
        authored_change.apply_and_commit(
            repo, branch="task/T-3",
            files=[("README.md", "seed\n")], message="m",
        )


def test_a_non_repository_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(authored_change.AuthoringError, match="not a git repository"):
        authored_change.apply_and_commit(
            plain, branch="task/T-4", files=[("a.txt", "x\n")], message="m",
        )


# --- The prompt -------------------------------------------------------------


def test_the_prompt_carries_the_objective_and_the_contract():
    prompt = authored_change.render_author_prompt({
        "task_id": "T-1", "title": "add a note",
        "objective": "Create notes/hello.txt with one line.",
    })

    assert "Create notes/hello.txt with one line." in prompt
    assert authored_change.BEGIN in prompt
    assert authored_change.END in prompt
    assert "COMPLETE contents" in prompt


# --- allowed_paths ----------------------------------------------------------


ALLOWED = ["notes", "docs/changelog.md"]


@pytest.mark.parametrize("path", [
    "notes/a.txt", "notes/deep/b.txt", "notes", "docs/changelog.md",
])
def test_a_path_inside_the_contract_is_allowed(repo, path):
    assert authored_change.safe_relative_path(repo, path, ALLOWED)


@pytest.mark.parametrize("path", [
    "build.sh", "docs/other.md", "src/main.py", "README.md",
])
def test_a_path_outside_the_contract_is_refused(repo, path):
    """Inside the repository is not the same as authorised to touch.

    A task asked to add a note has no business editing the build script, and
    the containment check cannot tell those apart -- both are inside the
    repository.
    """
    with pytest.raises(authored_change.UnsafePath, match="outside the paths"):
        authored_change.safe_relative_path(repo, path, ALLOWED)


def test_a_sibling_with_a_shared_prefix_is_not_allowed(repo):
    """`notes` must not authorise `notes-secret`.

    A startswith check would allow it. Matching is on path components for
    exactly this case.
    """
    with pytest.raises(authored_change.UnsafePath):
        authored_change.safe_relative_path(repo, "notes-secret/x.txt", ALLOWED)


def test_no_contract_restriction_means_containment_only(repo):
    """An empty list is "unrestricted", not "nothing permitted"."""
    assert authored_change.safe_relative_path(repo, "anything.txt", [])
    assert authored_change.safe_relative_path(repo, "anything.txt", None)


def test_apply_refuses_a_file_outside_the_contract(repo):
    with pytest.raises(authored_change.UnsafePath):
        authored_change.apply_and_commit(
            repo, branch="task/T-9",
            files=[("notes/ok.txt", "x\n"), ("build.sh", "rm -rf /\n")],
            message="m", allowed_paths=ALLOWED,
        )

    assert git(repo, "status", "--porcelain") == ""
    assert "task/T-9" not in git(repo, "branch", "--list", "task/T-9")


# --- The worktree is left clean, or the failure says so ---------------------


def test_a_dirty_worktree_is_refused_before_anything_is_written(repo):
    """Somebody else's uncommitted edits must not land in this task's commit.

    They would be attributed to the model, and the review would judge them as
    though the author had written them.
    """
    (repo / "stray.txt").write_text("not mine\n", encoding="utf-8")

    with pytest.raises(authored_change.AuthoringError, match="not clean"):
        authored_change.apply_and_commit(
            repo, branch="task/T-8", files=[("a.txt", "x\n")], message="m",
        )


def test_a_failure_partway_through_leaves_no_branch_and_no_dirt(repo):
    """The empty-change failure happens after files are written and staged.

    That is the interesting case: the attempt got far enough to modify the
    worktree before failing, so recovery has to actually undo something.
    """
    before = git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    with pytest.raises(authored_change.AuthoringError, match="nothing to commit"):
        authored_change.apply_and_commit(
            repo, branch="task/T-7",
            files=[("README.md", "seed\n")], message="m",
        )

    assert authored_change.worktree_is_clean(repo)
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == before
    assert git(repo, "branch", "--list", "task/T-7") == ""


def test_a_failed_attempt_can_be_retried_on_the_same_branch(repo):
    """The point of cleaning up: the branch name is free again.

    Without the rollback the retry would hit "branch already exists" and the
    task would be stuck behind its own failed attempt.
    """
    with pytest.raises(authored_change.AuthoringError):
        authored_change.apply_and_commit(
            repo, branch="task/T-6",
            files=[("README.md", "seed\n")], message="m",
        )

    result = authored_change.apply_and_commit(
        repo, branch="task/T-6", files=[("fixed.txt", "better\n")], message="m",
    )

    assert len(result["candidate_sha"]) == 40
