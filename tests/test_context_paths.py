"""What an author may read, and what reading it does not permit.

The rejection cycle exposed one half of this. An author with no shell was told
to reword a sentence in a file it had never been shown, and the output contract
demands the complete contents of every file it writes -- so inventing the rest
of the README was not a corner it cut, it was the only move available to it.
`existing_in_scope` fixed that case: show it the files it may write.

This is the other half, and it does not have a live incident behind it yet
because the demonstration never reached real code. A change to a real module
has to fit an interface it does not own, callers it must not break, and tests
that pin behaviour it is not writing. An author shown only its own files infers
all of that, and an inference that reads plausibly is the most expensive kind
of wrong: the reviewer has to read carefully to catch it, and the reviewer is
a model too.

The correction that was available before this existed was to widen
allowed_paths. That buys understanding with write authority -- and a file
listed as writable is a file that can come back rewritten, which is exactly
what the rejected candidate did to the README. So the two are separate lists,
and the separation is enforced at the point of writing rather than trusted.
"""

from __future__ import annotations

import subprocess

import pytest

import authored_change
from authored_change import ContractError, Scope, UnsafePath


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    """A repository with a writable file, reference material, and a test."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "context@test")
    git(root, "config", "user.name", "Context Test")

    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "reader.py").write_text(
        "def read(path):\n    return open(path).read()\n", encoding="utf-8"
    )
    (root / "src" / "api.py").write_text(
        "class Reader:\n    def read(self, path): ...\n", encoding="utf-8"
    )
    (root / "tests" / "test_reader.py").write_text(
        "def test_read():\n    assert True\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# project\n", encoding="utf-8")

    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture
def sha(repo):
    return git(repo, "rev-parse", "HEAD").strip()


# --- The contract states both, and means different things by silence --------


def test_a_contract_may_declare_context_paths():
    scope = authored_change.parse_scope(
        "allowed_paths:\n  - src/reader.py\n"
        "context_paths:\n  - src/api.py\n  - tests\n"
    )

    assert scope.paths == ("src/reader.py",)
    assert scope.context == ("src/api.py", "tests")


def test_a_contract_without_context_paths_has_none():
    """Silence means nothing to read, which is not what it means for
    allowed_paths.

    The asymmetry is deliberate. An unreadable allowed_paths must fail closed,
    because the quietest failure would otherwise produce the widest write
    authority. An unreadable context_paths fails to *less* context, and the
    author is already told to answer CANNOT_AUTHOR rather than invent what it
    was not shown. The safe direction is a refusal for one and an empty list
    for the other.
    """
    scope = authored_change.parse_scope("allowed_paths:\n  - notes\n")

    assert scope.context == ()


def test_an_empty_context_paths_key_is_not_an_error():
    """It authorises nothing and withholds nothing."""
    scope = authored_change.parse_scope(
        "allowed_paths:\n  - notes\ncontext_paths:\ntitle: x\n"
    )

    assert scope.context == ()


def test_a_flow_list_of_context_paths_is_read():
    scope = authored_change.parse_scope(
        "allowed_paths: [notes]\ncontext_paths: [src/api.py, 'tests']\n"
    )

    assert scope.context == ("src/api.py", "tests")


def test_context_paths_may_not_be_unrestricted():
    """A reading list of everything is the absence of a reading list.

    The budget would choose which files the author actually saw, in tree
    order, and present that arbitrary prefix as the files that mattered.
    """
    with pytest.raises(ContractError, match="reading list"):
        authored_change.parse_scope(
            "allowed_paths: [notes]\ncontext_paths: UNRESTRICTED\n"
        )


def test_an_unparseable_context_paths_scalar_is_refused():
    with pytest.raises(ContractError, match="context_paths"):
        authored_change.parse_scope(
            "allowed_paths: [notes]\ncontext_paths: everything\n"
        )


def test_a_declared_context_list_overrides_the_contract():
    scope = authored_change.parse_scope(
        "allowed_paths: [notes]\ncontext_paths: [src/api.py]\n",
        declared_context=["tests"],
    )

    assert scope.context == ("tests",)


def test_a_writable_path_is_dropped_from_the_reading_list():
    """It is already shown in full, and listing it again would contradict that.

    Dropped rather than refused: the file is shown and it is writable, which
    is what both entries wanted. Only the plan, where somebody can still say
    which list was meant, treats it as a mistake.
    """
    scope = authored_change.parse_scope(
        "allowed_paths:\n  - src\ncontext_paths:\n  - src/api.py\n  - tests\n"
    )

    assert scope.context == ("tests",)


def test_an_unrestricted_task_still_gets_its_reading_list():
    """It is not shown its in-scope files -- the whole tree is in scope.

    A reading list is the only way such a task is shown anything at all, which
    makes it the case where being shown the right files matters most.
    """
    scope = authored_change.parse_scope(
        "allowed_paths: UNRESTRICTED\ncontext_paths:\n  - src/api.py\n"
    )

    assert scope.unrestricted is True
    assert scope.context == ("src/api.py",)


# --- Reading it, from the commit and not the working tree -------------------


def test_context_is_read_from_the_baseline_commit(repo, sha):
    scope = Scope.restricted_to(["notes"], ["src/api.py"])
    (repo / "src" / "api.py").write_text("SABOTAGE\n", encoding="utf-8")

    context = authored_change.context_at(str(repo), sha, scope)

    assert context["files"][0]["path"] == "src/api.py"
    assert "class Reader" in context["files"][0]["text"]
    assert "SABOTAGE" not in context["files"][0]["text"]


def test_a_directory_expands_to_the_files_under_it(repo, sha):
    scope = Scope.restricted_to(["notes"], ["src"])

    paths = [
        entry["path"] for entry in authored_change.context_at(str(repo), sha, scope)["files"]
    ]

    assert paths == ["src/api.py", "src/reader.py"]


def test_a_file_is_read_once_when_two_entries_cover_it(repo, sha):
    """Showing it twice would spend the budget on a duplicate and read as two
    different files to the author."""
    scope = Scope.restricted_to(["notes"], ["src", "src/api.py"])

    paths = [
        entry["path"] for entry in authored_change.context_at(str(repo), sha, scope)["files"]
    ]

    assert paths == ["src/api.py", "src/reader.py"]


def test_a_path_that_is_not_there_is_reported_missing(repo, sha):
    """The author cannot discover this: from inside the prompt, a shorter
    reading list looks exactly like a shorter reading list."""
    scope = Scope.restricted_to(["notes"], ["src/absent.py"])

    context = authored_change.context_at(str(repo), sha, scope)

    assert context["files"] == []
    assert context["missing"][0]["path"] == "src/absent.py"


def test_an_unreadable_tree_reports_every_entry_missing(repo):
    """A listing that failed must not read as a task that needed no context."""
    scope = Scope.restricted_to(["notes"], ["src/api.py", "tests"])

    context = authored_change.context_at(str(repo), "0" * 40, scope)

    assert len(context["missing"]) == 2
    assert context["files"] == []


def test_a_file_too_large_for_its_share_is_flagged_truncated(repo, sha):
    scope = Scope.restricted_to(["notes"], ["src/api.py"])

    context = authored_change.context_at(str(repo), sha, scope, per_file=10)

    assert context["files"][0]["truncated"] is True


def test_a_file_that_got_no_room_is_omitted_not_truncated(repo, sha):
    """A file shown in part can still be reasoned about; one not shown at all
    cannot. Both render as absence unless they are named separately."""
    scope = Scope.restricted_to(["notes"], ["src"])

    context = authored_change.context_at(str(repo), sha, scope, total=20)

    assert [entry["path"] for entry in context["files"]] == ["src/api.py"]
    assert [entry["path"] for entry in context["omitted"]] == ["src/reader.py"]


def test_no_reading_list_reads_nothing(repo, sha):
    scope = Scope.restricted_to(["notes"])

    assert authored_change.context_at(str(repo), sha, scope) == {
        "files": [], "missing": [], "omitted": []
    }


# --- Being shown a file is not permission to write it -----------------------


def test_writing_a_context_path_is_refused(tmp_path):
    scope = Scope.restricted_to(["notes"], ["src/api.py"])

    with pytest.raises(UnsafePath, match="read-only context"):
        authored_change.safe_relative_path(tmp_path, "src/api.py", scope)


def test_the_refusal_says_it_was_context_not_that_it_was_out_of_scope(tmp_path):
    """"Outside the paths this task may touch" is misleading for a file the
    author was shown a moment earlier; it reads as the harness contradicting
    itself, and the author has nothing to act on."""
    scope = Scope.restricted_to(["notes"], ["src/api.py"])

    with pytest.raises(UnsafePath) as raised:
        authored_change.safe_relative_path(tmp_path, "src/api.py", scope)

    assert "allowed_paths" in str(raised.value)


def test_an_unrestricted_task_may_not_write_its_context_either(tmp_path):
    """The one authority UNRESTRICTED does not carry.

    "You may write anywhere" was never meant to include the reference material
    the task was handed in order to write correctly.
    """
    scope = Scope.everywhere(["src/api.py"])

    with pytest.raises(UnsafePath, match="read-only context"):
        authored_change.safe_relative_path(tmp_path, "src/api.py", scope)

    assert authored_change.safe_relative_path(tmp_path, "anything/else.py", scope)


def test_a_file_under_a_context_directory_is_refused(tmp_path):
    scope = Scope.restricted_to(["notes"], ["src"])

    with pytest.raises(UnsafePath, match="read-only context"):
        authored_change.safe_relative_path(tmp_path, "src/reader.py", scope)


def test_a_neighbouring_prefix_is_not_context(tmp_path):
    """`src` does not cover `src-generated`; matching is by path component."""
    scope = Scope.restricted_to(["src-generated"], ["src"])

    assert authored_change.safe_relative_path(
        tmp_path, "src-generated/out.py", scope
    )


# --- What the author is actually told ---------------------------------------


def prompt_for(scope, context):
    return authored_change.render_author_prompt(
        {"task_id": "T-1", "title": "t", "objective": "o" * 30,
         "allowed_paths": list(scope.paths)},
        [],
        context,
    )


def test_the_prompt_says_read_only_before_it_shows_anything(repo, sha):
    scope = Scope.restricted_to(["notes"], ["src/api.py"])
    context = authored_change.context_at(str(repo), sha, scope)

    text = prompt_for(scope, context)

    assert "YOU MAY NOT WRITE ANY OF THESE" in text
    assert text.index("YOU MAY NOT WRITE") < text.index("class Reader")


def test_a_truncated_context_file_tells_the_author_to_stop(repo, sha):
    """Not to infer. The part it cannot see is the part it would invent."""
    scope = Scope.restricted_to(["notes"], ["src/api.py"])
    context = authored_change.context_at(str(repo), sha, scope, per_file=10)

    text = prompt_for(scope, context)

    assert "IS TRUNCATED" in text
    assert "CANNOT_AUTHOR" in text


def test_context_that_did_not_fit_is_named_rather_than_dropped(repo, sha):
    scope = Scope.restricted_to(["notes"], ["src"])
    context = authored_change.context_at(str(repo), sha, scope, total=20)

    text = prompt_for(scope, context)

    assert "NOT SHOWN AT ALL" in text
    assert "src/reader.py" in text


def test_a_prompt_with_no_context_has_no_context_section(repo, sha):
    scope = Scope.restricted_to(["notes"])
    context = authored_change.context_at(str(repo), sha, scope)

    assert "FOR CONTEXT ONLY" not in prompt_for(scope, context)


def test_the_write_authority_is_stated_before_any_file_is_shown(repo, sha):
    """Every file below it is then read under a rule already given, rather
    than one that arrives afterwards to take something back."""
    scope = Scope.restricted_to(["notes"], ["src/api.py"])
    context = authored_change.context_at(str(repo), sha, scope)

    text = prompt_for(scope, context)

    assert text.index("You may only write to these paths") < text.index(
        "FOR CONTEXT ONLY"
    )
