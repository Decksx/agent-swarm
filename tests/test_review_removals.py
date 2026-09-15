"""The reviewer is shown every block a candidate deletes outright (#35).

Gemini caught the dropped `hub/hub.py` comment block twice, but only by finding
six minus lines in a long diff, and a reviewer with less context might not.
A hunk that removes lines and adds none is exactly that defect's shape, and it
is deterministic to find, so the packet lists them where the verdict is formed.
"""

from __future__ import annotations

import subprocess

import pytest

import review_packet

TASK = {"task_id": "T-1", "title": "show the build id", "objective": "Show it. Change nothing else."}

HUB = "".join(f"line {n}\n" for n in range(1, 21))


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@test")
    git(root, "config", "user.name", "t")
    (root / "hub.py").write_text(HUB, encoding="utf-8", newline="\n")
    (root / "notes.sql").write_text("select 1;\n-- keep this comment\nselect 2;\n",
                                    encoding="utf-8", newline="\n")
    (root / "gone.txt").write_text("a\nb\n", encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def candidate(repo, **files):
    """Commit `files` ({name: text, or None to delete}) and return base, head."""
    base = git(repo, "rev-parse", "HEAD")

    for name, text in files.items():
        path = repo / name.replace("__", ".")
        if text is None:
            path.unlink()
        else:
            path.write_text(text, encoding="utf-8", newline="\n")

    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "candidate")
    return base, git(repo, "rev-parse", "HEAD")


def removals(repo, base, head):
    return review_packet.pure_deletions(str(repo), base, head)


def test_a_block_deleted_outright_is_listed_with_its_place(repo):
    base, head = candidate(repo, hub__py=HUB.replace("line 5\nline 6\nline 7\n", ""))

    hunks, truncated = removals(repo, base, head)

    assert hunks == [{"path": "hub.py", "start": 5, "lines": ["line 5", "line 6", "line 7"]}]
    assert truncated is False


def test_replaced_lines_are_not_listed(repo):
    base, head = candidate(repo, hub__py=HUB.replace("line 5\n", "line five\n"))

    assert removals(repo, base, head) == ([], False)


def test_a_deletion_beside_an_unrelated_edit_is_still_listed(repo):
    """The T-CMD-058924af3d shape: a real change, and a block dropped elsewhere."""
    text = HUB.replace("line 2\n", "line two\n").replace("line 15\nline 16\n", "")
    base, head = candidate(repo, hub__py=text)

    hunks, _ = removals(repo, base, head)

    assert [(h["start"], h["lines"]) for h in hunks] == [(15, ["line 15", "line 16"])]


def test_a_removed_line_that_starts_with_dashes_is_read_as_a_line(repo):
    base, head = candidate(repo, notes__sql="select 1;\nselect 2;\n")

    hunks, _ = removals(repo, base, head)

    assert hunks == [{"path": "notes.sql", "start": 2, "lines": ["-- keep this comment"]}]


def test_a_deleted_file_is_listed_under_its_own_name(repo):
    base, head = candidate(repo, gone__txt=None)

    hunks, _ = removals(repo, base, head)

    assert hunks == [{"path": "gone.txt", "start": 1, "lines": ["a", "b"]}]


def test_the_listing_is_bounded_and_says_so(repo, monkeypatch):
    monkeypatch.setattr(review_packet, "REMOVAL_LINE_BUDGET", 2)
    base, head = candidate(repo, hub__py="line 1\n")

    hunks, truncated = removals(repo, base, head)

    assert sum(len(h["lines"]) for h in hunks) == 2
    assert truncated is True


def test_the_packet_carries_them_and_the_prompt_shows_them(repo):
    base, head = candidate(repo, hub__py=HUB.replace("line 9\n", "").replace("line 1\n", "line one\n"))

    packet = review_packet.build(str(repo), task=TASK, base=base, candidate=head)
    prompt = review_packet.render(packet)

    assert packet["pure_deletions"] == [{"path": "hub.py", "start": 9, "lines": ["line 9"]}]
    assert "LINES REMOVED WITH NOTHING ADDED IN THEIR PLACE" in prompt
    assert "hub.py, base lines 9-9:" in prompt
    assert "    - line 9" in prompt
    assert "CHANGES_REQUESTED" in prompt.split("LINES REMOVED")[1].split("TEST RESULTS")[0]
    # After the diff, before the author's own claim.
    assert prompt.index("FULL DIFF") < prompt.index("LINES REMOVED") < prompt.index("AUTHOR'S SUMMARY")


def test_a_change_that_deletes_nothing_gets_no_section(repo):
    base, head = candidate(repo, hub__py=HUB + "line 21\n")

    prompt = review_packet.render(review_packet.build(str(repo), task=TASK, base=base, candidate=head))

    assert "LINES REMOVED" not in prompt


def test_a_truncated_listing_is_stated_in_the_prompt(repo, monkeypatch):
    monkeypatch.setattr(review_packet, "REMOVAL_LINE_BUDGET", 1)
    base, head = candidate(repo, hub__py="line 1\n")

    prompt = review_packet.render(review_packet.build(str(repo), task=TASK, base=base, candidate=head))

    assert "more removed lines are not listed here" in prompt
