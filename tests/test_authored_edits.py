"""An API author changes existing files through EDIT blocks, never rewrites (#35).

Three chatgpt candidates for T-CMD-058924af3d deleted the same six-line comment
block from `hub/hub.py`, two of them after a review that named the deletion.
The harness showed the file whole and parsed the answer exactly; what lost the
lines was the protocol, which made the author retype 27,000 characters to
change three.

These check the replacement: blocks parse, edits resolve against the base with
every other line untouched, an answer that cannot be applied is refused with a
reason the author can act on, and the author is asked to fix it once -- and
only once -- inside the same activation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import authored_change
import authored_edits
import chatgpt_worker
from authored_change import BEGIN, END, AuthoringError, UnsafePath
from authored_edits import Block, EditRefused
from test_author_activation import CONTRACT, Queue, activation, author_repo, base_of  # noqa: F401

SCOPE = authored_change.Scope.restricted_to(["notes", "hub"])

HUB = (
    "def header():\n"
    "    return 'Agent Hub'\n"
    "\n"
    "// Converted in the browser from the server's instant.\n"
    "// A string the server formatted would carry its zone.\n"
    "function localTime(stamp) {\n"
    "    return new Date(stamp).toLocaleString();\n"
    "}\n"
)


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                            encoding="utf-8", errors="replace", check=False)
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "hub").mkdir(parents=True)
    (root / "notes").mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@test")
    git(root, "config", "user.name", "t")
    (root / "hub" / "hub.py").write_text(HUB, encoding="utf-8", newline="\n")
    (root / "notes" / "a.txt").write_text("one\ntwo\none\n", encoding="utf-8", newline="\n")
    (root / "notes" / "bare.txt").write_bytes(b"no newline at end")
    (root / "notes" / "blob.bin").write_bytes(b"\xff\xfe\x00binary")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def edit(path, search, replace):
    return (f"EDIT: {path}\n<<<SEARCH>>>\n{search}\n<<<REPLACE>>>\n{replace}\n{END}\n"
            if replace is not None else
            f"EDIT: {path}\n<<<SEARCH>>>\n{search}\n<<<REPLACE>>>\n{END}\n")


def new_file(path, text):
    return f"FILE: {path}\n{BEGIN}\n{text}\n{END}\n"


def resolve(repo, answer):
    return dict(authored_edits.resolve(str(repo), "HEAD", authored_edits.parse_answer(answer), SCOPE))


# --- Parsing -------------------------------------------------------------------


def test_file_and_edit_blocks_parse_in_order():
    blocks = authored_edits.parse_answer(
        "Here you go\n" + new_file("notes/new.txt", "hi") + edit("hub/hub.py", "a\nb", "c"))

    assert blocks == [
        Block("file", "notes/new.txt", content="hi\n"),
        Block("edit", "hub/hub.py", search=("a", "b"), replace=("c",)),
    ]


def test_an_empty_replace_is_a_deletion_not_a_parse_error():
    [block] = authored_edits.parse_answer(edit("hub/hub.py", "a", None))

    assert block.replace == ()


def test_crlf_answers_parse_like_lf_ones():
    answer = edit("hub/hub.py", "a", "b").replace("\n", "\r\n")

    assert authored_edits.parse_answer(answer)[0].search == ("a",)


@pytest.mark.parametrize("answer,named", [
    ("", "returned nothing"),
    ("CANNOT_AUTHOR: the file is too large\nmore", "CANNOT_AUTHOR"),
    ("just prose", "no FILE or EDIT blocks"),
    ("EDIT: hub/hub.py\nsearch without a marker\n", "expected <<<SEARCH>>>"),
    ("EDIT: hub/hub.py\n<<<SEARCH>>>\na\n", "no <<<REPLACE>>>"),
    ("EDIT: hub/hub.py\n<<<SEARCH>>>\na\n<<<REPLACE>>>\nb\n", "truncated"),
    (f"FILE: notes/x.txt\n{BEGIN}\nbody", "truncated"),
])
def test_an_unusable_answer_raises_and_is_not_an_edit_refusal(answer, named):
    with pytest.raises(AuthoringError, match=named) as refused:
        authored_edits.parse_answer(answer)

    assert not isinstance(refused.value, EditRefused)


# --- Resolving against the base ----------------------------------------------------


def test_an_edit_changes_only_its_lines_and_keeps_the_comment_block(repo):
    """The T-CMD-058924af3d case: change the header, keep the comment."""
    files = resolve(repo, edit("hub/hub.py", "    return 'Agent Hub'",
                               "    return 'Agent Hub ' + build_id()"))

    assert files["hub/hub.py"] == HUB.replace(
        "    return 'Agent Hub'", "    return 'Agent Hub ' + build_id()")
    assert "// Converted in the browser from the server's instant." in files["hub/hub.py"]


def test_edits_to_one_file_apply_in_order(repo):
    files = resolve(repo, edit("hub/hub.py", "def header():", "def title():")
                    + edit("hub/hub.py", "def title():\n    return 'Agent Hub'",
                           "def title():\n    return 'Hub'"))

    assert files["hub/hub.py"].startswith("def title():\n    return 'Hub'\n")


def test_an_empty_replace_deletes_exactly_the_search_lines(repo):
    files = resolve(repo, edit("notes/a.txt", "two", None))

    assert files["notes/a.txt"] == "one\none\n"


def test_a_file_without_a_final_newline_keeps_it_that_way(repo):
    files = resolve(repo, edit("notes/bare.txt", "no newline at end", "still none"))

    assert files["notes/bare.txt"] == "still none"


def test_a_new_file_is_written_whole(repo):
    assert resolve(repo, new_file("notes/new.txt", "hello")) == {"notes/new.txt": "hello\n"}


def test_resolving_writes_nothing(repo):
    resolve(repo, edit("hub/hub.py", "def header():", "def title():")
            + new_file("notes/new.txt", "hello"))

    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("answer,named", [
    (new_file("hub/hub.py", "rewritten"), "already exists. Use EDIT blocks"),
    (edit("hub/hub.py", "    return 'Agent Hubb'", "x"), "does not appear in the file"),
    (edit("hub/hub.py", "Agent Hub", "x"), "does not appear in the file"),
    (edit("notes/a.txt", "one", "uno"), "appears 2 times"),
    (edit("hub/hub.py", "", "x"), "SEARCH is empty"),
    (edit("hub/hub.py", "   ", "x"), "SEARCH is empty"),
    (edit("notes/missing.txt", "a", "b"), "does not exist; create it with a FILE block"),
    (new_file("notes/n.txt", "a") + new_file("notes/n.txt", "b"), "written twice"),
    (new_file("notes/n.txt", "a") + edit("notes/n.txt", "a", "b"), "created by a FILE block"),
    (edit("notes/blob.bin", "binary", "x"), "not UTF-8"),
])
def test_an_answer_that_cannot_be_applied_is_refused_by_name(repo, answer, named):
    with pytest.raises(EditRefused, match=named) as refused:
        resolve(repo, answer)

    assert refused.value.path
    assert "block " in str(refused.value)


def test_a_path_outside_the_scope_is_the_boundary_not_a_copying_mistake(repo):
    with pytest.raises(UnsafePath) as refused:
        resolve(repo, edit("README.md", "a", "b"))

    assert not isinstance(refused.value, EditRefused)


def test_the_repair_prompt_names_the_error_and_shows_the_file(repo):
    with pytest.raises(EditRefused) as refused:
        resolve(repo, edit("hub/hub.py", "    return 'Agent Hubb'", "x"))

    prompt = authored_edits.repair_prompt(refused.value, str(repo), "HEAD")

    assert "COULD NOT BE APPLIED, AND NOTHING WAS WRITTEN" in prompt
    assert str(refused.value) in prompt
    assert "--- hub/hub.py" in prompt and "function localTime(stamp) {" in prompt
    assert "only retry" in prompt


# --- The chatgpt author, end to end ---------------------------------------------------


@pytest.fixture
def answers(monkeypatch):
    """Scripted model answers, one per call; records what each call was sent."""
    state = {"script": [], "sent": []}

    def fake_generate_reply(client, messages):
        state["sent"].append([m["content"] for m in messages])
        return state["script"].pop(0) if state["script"] else None

    monkeypatch.setattr(chatgpt_worker, "generate_reply", fake_generate_reply)
    return state


def run(author_repo, answers, *script):
    answers["script"] = list(script)
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT, base=base_of(author_repo)), queue)
    return queue.last


def committed(author_repo, path):
    return git(author_repo, "show", f"refs/heads/task/T-1-a1:{path}")


def test_an_edit_answer_commits_the_change_and_nothing_else(author_repo, answers):
    report = run(author_repo, answers, edit("notes/existing.txt", "old", "new"))

    assert report["outcome"] == "candidate", report
    assert committed(author_repo, "notes/existing.txt") == "new"
    assert len(answers["sent"]) == 1


def test_a_whole_file_rewrite_of_an_existing_file_is_repaired_once(author_repo, answers):
    report = run(author_repo, answers,
                 new_file("notes/existing.txt", "rewritten"),
                 edit("notes/existing.txt", "old", "new"))

    assert report["outcome"] == "candidate", report
    assert committed(author_repo, "notes/existing.txt") == "new"
    assert len(answers["sent"]) == 2
    repair = answers["sent"][1]
    assert "COULD NOT BE APPLIED" in repair[-1]
    assert "already exists. Use EDIT blocks" in repair[-1]
    # The rejected answer is in the conversation, so the model can see what it sent.
    assert repair[-2] == new_file("notes/existing.txt", "rewritten")


def test_a_second_answer_that_cannot_be_applied_fails_the_attempt(author_repo, answers):
    report = run(author_repo, answers,
                 edit("notes/existing.txt", "olld", "new"),
                 edit("notes/existing.txt", "oold", "new"))

    assert report["outcome"] == "failed"
    assert "after one repair" in report["payload"]["reason"]
    assert report["payload"]["repaired"] is True
    assert len(answers["sent"]) == 2
    assert git(author_repo, "branch", "--list", "task/T-1-a1") == ""


def test_an_unrepaired_failure_is_not_retried_more_than_once(author_repo, answers):
    run(author_repo, answers, *[edit("notes/existing.txt", "nope", "x")] * 5)

    assert len(answers["sent"]) == 2


def test_a_path_outside_the_scope_is_not_offered_a_repair(author_repo, answers):
    report = run(author_repo, answers, new_file("build.sh", "echo SABOTAGE"),
                 new_file("notes/fine.txt", "ok"))

    assert report["outcome"] == "failed"
    assert len(answers["sent"]) == 1
    assert report["payload"]["repaired"] is False


def test_a_truncated_answer_is_not_offered_a_repair(author_repo, answers):
    report = run(author_repo, answers, "EDIT: notes/existing.txt\n<<<SEARCH>>>\nold\n")

    assert report["outcome"] == "failed"
    assert len(answers["sent"]) == 1


def test_no_reply_to_the_repair_is_blocked(author_repo, answers):
    report = run(author_repo, answers, edit("notes/existing.txt", "olld", "new"))

    assert report["outcome"] == "blocked"
    assert len(answers["sent"]) == 2


def test_an_unusable_answer_leaves_no_worktree(author_repo, answers, tmp_path):
    run(author_repo, answers, edit("notes/existing.txt", "olld", "x"),
        edit("notes/existing.txt", "olld", "x"))

    assert list((tmp_path / "worktrees").glob("*")) == []


def test_the_prompt_tells_the_author_to_edit_existing_files(author_repo, answers):
    run(author_repo, answers, edit("notes/existing.txt", "old", "new"))

    prompt = answers["sent"][0][0]
    assert "EDIT: relative/path/from/the/repository/root.txt" in prompt
    assert "A FILE block for a file that exists is refused" in prompt
