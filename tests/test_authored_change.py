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
