"""The reviewer's evidence, and what it refuses to guess.

Two properties matter here and they pull in opposite directions. The packet has
to contain enough for a genuine judgment -- objective, base, candidate, changed
files, the actual diff -- and the verdict parser has to refuse to manufacture a
judgment when the model did not give one. A reviewer that approves because the
prose sounded positive is worse than no reviewer, because it produces the same
audit trail as a real approval.
"""

from __future__ import annotations

import subprocess

import pytest

import review_packet


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repository with one commit on a branch off main."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "test")
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "seed")

    git(path, "checkout", "-q", "-b", "task/T-1")
    (path / "demo.txt").write_text("added by the author\n", encoding="utf-8")
    git(path, "add", "demo.txt")
    git(path, "commit", "-q", "-m", "T-1: add demo.txt")
    git(path, "checkout", "-q", "main")

    return path


TASK = {
    "task_id": "T-1",
    "title": "add a demo file",
    "objective": "Create demo.txt containing one line. Change nothing else.",
}


# --- The packet contains evidence, not assertions ---------------------------


def test_the_packet_carries_the_diff_and_not_only_a_sha(repo):
    """The whole point: a SHA is not reviewable, a diff is."""
    packet = review_packet.build(repo, task=TASK, branch="task/T-1")

    assert len(packet["base_sha"]) == 40
    assert len(packet["candidate_sha"]) == 40
    assert packet["base_sha"] != packet["candidate_sha"]
    assert packet["changed_files"] == ["A\tdemo.txt"]
    assert "added by the author" in packet["diff"]
    assert "+++ b/demo.txt" in packet["diff"]


def test_the_objective_travels_with_it(repo):
    """A reviewer with no acceptance criteria is guessing at the bar."""
    rendered = review_packet.render(
        review_packet.build(repo, task=TASK, branch="task/T-1")
    )

    assert "Create demo.txt containing one line" in rendered
    assert "OBJECTIVE AND ACCEPTANCE CRITERIA" in rendered


def test_the_author_summary_is_labelled_a_claim(repo):
    """It is included, and it is not presented as evidence.

    The author's account of its own work is the thing under review. Putting it
    beside the diff unlabelled invites the reviewer to check the summary
    against itself.
    """
    rendered = review_packet.render(review_packet.build(
        repo, task=TASK, branch="task/T-1", author_summary="I did it perfectly.",
    ))

    assert "I did it perfectly." in rendered
    assert "not evidence" in rendered
    # And it comes after the diff, so the diff is read first.
    assert rendered.index("FULL DIFF") < rendered.index("I did it perfectly.")


def test_an_explicit_base_overrides_the_first_parent(repo):
    base = git(repo, "rev-parse", "main")
    packet = review_packet.build(repo, task=TASK, branch="task/T-1", base=base)

    assert packet["base_sha"] == base


def test_a_branch_that_does_not_exist_is_an_error_not_an_empty_review(repo):
    """Silently reviewing nothing would produce a confident approval."""
    with pytest.raises(review_packet.PacketError):
        review_packet.build(repo, task=TASK, branch="task/nope")


def test_an_empty_range_is_refused(repo):
    """Base equal to candidate means there is nothing to judge."""
    head = git(repo, "rev-parse", "task/T-1")

    with pytest.raises(review_packet.PacketError):
        review_packet.build(repo, task=TASK, branch="task/T-1", base=head)


def test_a_large_diff_is_truncated_and_says_so(repo):
    """Truncation the reviewer cannot see is truncation it cannot allow for."""
    packet = review_packet.build(repo, task=TASK, branch="task/T-1", diff_budget=20)

    assert packet["diff_truncated"] is True
    rendered = review_packet.render(packet)
    assert "DIFF TRUNCATED" in rendered
    assert "answer BLOCKED" in rendered


# --- The parser refuses to invent a verdict ---------------------------------


@pytest.mark.parametrize("text,expected", [
    ("VERDICT: APPROVE\nRATIONALE: meets the objective.", "satisfied"),
    ("VERDICT: CHANGES_REQUESTED\nRATIONALE: wrong file.", "changes_requested"),
    ("VERDICT: BLOCKED\nRATIONALE: cannot see the diff.", "blocked"),
    ("verdict: approve\nrationale: fine.", "satisfied"),
    ("VERDICT: APPROVED\nRATIONALE: fine.", "satisfied"),
])
def test_a_stated_verdict_is_read(text, expected):
    judgment, rationale = review_packet.parse_verdict(text)

    assert judgment == expected
    assert rationale


@pytest.mark.parametrize("text", [
    "This looks broadly fine, but I have a few concerns.",
    "I approve of the general direction here.",
    "LGTM",
    "The change is correct and I would merge it.",
    "",
    "   ",
])
def test_prose_without_a_verdict_line_is_blocked_not_guessed(text):
    """The dangerous case is prose that sounds like approval.

    "I approve of the general direction" contains the word approve and is not
    an approval. Any keyword search over reviewer prose eventually approves
    something nobody approved, and the resulting event is indistinguishable
    from a real one in the ledger.
    """
    judgment, rationale = review_packet.parse_verdict(text)

    assert judgment == "blocked"
    assert rationale


def test_changes_requested_is_not_read_as_approve():
    """CHANGES_REQUESTED contains no APPROVE, but ordering bugs are cheap."""
    judgment, _ = review_packet.parse_verdict("VERDICT: CHANGES_REQUESTED\nR: x")

    assert judgment == "changes_requested"


def test_the_rationale_survives_multiple_lines():
    judgment, rationale = review_packet.parse_verdict(
        "VERDICT: CHANGES_REQUESTED\n"
        "RATIONALE: the diff adds demo.txt\n"
        "but the objective also required a test."
    )

    assert judgment == "changes_requested"
    assert "demo.txt" in rationale
    assert "required a test" in rationale


def test_a_non_string_reply_is_blocked():
    assert review_packet.parse_verdict(None)[0] == "blocked"
