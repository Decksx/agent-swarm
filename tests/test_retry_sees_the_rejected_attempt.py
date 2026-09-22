"""A retry is shown the change the reviewer was talking about (#68).

The defect was not a missing rationale. All three attempts at
T-CMD-99a5880f3e received the reviewer's words verbatim. What the author never
received was the document those words described: every retry authored from
`base_sha` and was shown the files as they stood *there*, so it read "the
change removes the leading `- ` bullet marker" while looking at a file where
the bullet was still present, and "placing this under the section header
creates a contradiction" about a placement that existed only in a commit it
had never seen.

The regression these tests hold down is the one the issue asks for: the task
requires an implemented capability to be **moved out** of a "not implemented"
section, not reworded in place. The rejected candidate here is the real shape
of attempt 2 -- bullet marker dropped, text still under the wrong heading --
and the assertions are about what the next attempt is given to work from. A
test that only checked "the sentence changed" would pass on every one of the
three candidates that were actually rejected.
"""

from __future__ import annotations

import subprocess

import pytest

import authored_change
import retry_base


README_AT_BASE = """# agent-swarm

## What works

- **Authoring.** A worker writes a candidate and pushes a branch.

## Deliberately not done yet

- **No integrator.** `READY_INTEGRATION` is where tasks stop. Nothing merges.
- **No scheduler.** Tasks are activated by the controller, not on a timer.
"""

# Attempt 2, as it actually was: the claim reworded in place, the list marker
# lost with it, and the text still sitting under "Deliberately not done yet".
README_AT_REJECTED = README_AT_BASE.replace(
    "- **No integrator.** `READY_INTEGRATION` is where tasks stop. Nothing merges.",
    "**Integrator exists.** Tasks progress beyond `READY_INTEGRATION` with an "
    "integrator component (`integrator.py`) that conducts the merging process.",
)

RATIONALE = (
    "The change removes the leading `- ` bullet marker, breaking the Markdown "
    "list formatting. Additionally, placing a description stating "
    '"**Integrator exists.**" directly under the "**Deliberately not done '
    'yet**" section header creates a logical contradiction in the document '
    "structure."
)


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          encoding="utf-8", errors="replace", check=check)


def out(repo, *args):
    return git(repo, *args).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repository with a base commit and one rejected candidate on top."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")

    (path / "README.md").write_text(README_AT_BASE, encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "base")
    base = out(path, "rev-parse", "HEAD")

    (path / "README.md").write_text(README_AT_REJECTED, encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "attempt 2")
    rejected = out(path, "rev-parse", "HEAD")

    # The branch is gone, as an abandoned attempt's branch is; the commit is
    # still reachable here because nothing has collected it yet.
    return {"path": path, "base": base, "rejected": rejected}


def task_for(repo, *, candidate=None, allowed=("README.md",)):
    return {
        "task_id": "T-CMD-99a5880f3e",
        "title": "Describe the integration pipeline that exists",
        "base_sha": repo["base"],
        "proof_mode": "branch_only",
        "current_version": 1,
        "contract_hash": "c" * 64,
        "contract_yaml": (
            "schema_version: 7\ntask_id: T-CMD-99a5880f3e\nallowed_paths:\n"
            + "".join(f"  - {entry}\n" for entry in allowed)
        ),
        "objective": (
            "README.md says `- **No integrator.** READY_INTEGRATION is where "
            "tasks stop. Nothing merges.` That is no longer true. Describe the "
            "pipeline that exists, and do not leave an implemented capability "
            "listed under a heading for things that are not implemented."
        ),
        "last_rejection": (
            {} if candidate is None else
            {"candidate_sha": candidate, "rationale": RATIONALE,
             "judgment": "changes_requested", "judgment_by": "gemini"}
        ),
    }


# --- Which commit the attempt authors from -----------------------------------


def test_a_first_attempt_authors_from_the_task_base(repo):
    resolved = retry_base.resolve(
        str(repo["path"]), task_for(repo)
    )

    assert resolved["sha"] == repo["base"]
    assert resolved["source"] == "base"


def test_a_retry_authors_from_the_rejected_candidate(repo):
    resolved = retry_base.resolve(
        str(repo["path"]), task_for(repo, candidate=repo["rejected"])
    )

    assert resolved["sha"] == repo["rejected"]
    assert resolved["source"] == "rejected_candidate"
    # The original base is carried, not discarded: it is what the review range
    # is measured from and what the contract is enforced against.
    assert resolved["original_base"] == repo["base"]


def test_a_collected_candidate_falls_back_to_the_base_with_a_reason(repo):
    """An abandoned branch's commit may simply be gone. That is recoverable."""
    resolved = retry_base.resolve(
        str(repo["path"]), task_for(repo, candidate="0" * 40)
    )

    assert resolved["sha"] == repo["base"]
    assert resolved["source"] == "base_after_unusable_candidate"
    assert "not present" in resolved["reason"]


def test_a_candidate_from_another_history_is_refused_as_a_base(repo, tmp_path):
    """The check that stops a retry inheriting somebody else's changes."""
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    (other / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    git(other, "add", "unrelated.py")
    git(other, "commit", "-qm", "unrelated")
    stranger = out(other, "rev-parse", "HEAD")

    # Fetched into the repository, so the object is present and only the
    # ancestry check can reject it.
    git(repo["path"], "fetch", "-q", str(other), stranger)

    resolved = retry_base.resolve(
        str(repo["path"]), task_for(repo, candidate=stranger)
    )

    assert resolved["sha"] == repo["base"]
    assert resolved["source"] == "base_after_unusable_candidate"
    assert "not an ancestor" in resolved["reason"]


# --- What the author is actually shown ---------------------------------------


def prompt_for(repo, candidate):
    """The retry prompt, built the way the worker builds it."""
    task = task_for(repo, candidate=candidate)
    scope = authored_change.require_contract(task)
    resolved = retry_base.resolve(str(repo["path"]), task)
    existing = authored_change.existing_in_scope(
        str(repo["path"]), resolved["sha"], scope
    )

    return authored_change.render_author_prompt(
        task, existing, {}, scope=scope, retry_from=resolved
    ), resolved


def test_the_retry_prompt_shows_the_rejected_text_not_the_original(repo):
    """The assertion the defect fails.

    Before #68 the prompt carried the rationale above a README in which the
    bullet the rationale complains about is still present -- feedback about a
    document the author was not looking at.
    """
    prompt, _ = prompt_for(repo, repo["rejected"])

    # What the reviewer objected to is in front of the author.
    assert "**Integrator exists.**" in prompt

    # And the line it replaced is not, because in the tree being shown it no
    # longer exists. This is the half that fails on the old behaviour.
    assert (
        "- **No integrator.** `READY_INTEGRATION` is where tasks stop."
        not in prompt.split("A PREVIOUS ATTEMPT")[0]
    )


def test_the_retry_prompt_says_the_files_are_the_rejected_attempt(repo):
    prompt, resolved = prompt_for(repo, repo["rejected"])

    assert "REJECTED ATTEMPT'S VERSION" in prompt
    assert resolved["sha"][:12] in prompt
    # Judged on the whole change, and told the attempt is not a floor.
    assert repo["base"][:12] in prompt
    assert "not a floor you have to build on" in prompt


def test_the_retry_prompt_says_restructuring_is_in_scope(repo):
    """Issue point 4: nothing told the author it could move content.

    The objective says "describe the pipeline that exists", and the rejection
    is about placement. An author that believes only rewording is available to
    it cannot satisfy both, which is what all three attempts did.
    """
    prompt, _ = prompt_for(repo, repo["rejected"])

    assert "moving content" in prompt
    assert "not answered by changing what it says" in prompt


def test_a_fallback_prompt_admits_the_attempt_cannot_be_shown(repo):
    """Honest about the state #68 could not fix, rather than silent about it."""
    prompt, resolved = prompt_for(repo, "0" * 40)

    assert resolved["source"] == "base_after_unusable_candidate"
    assert "THE FILES SHOWN ABOVE ARE THE ORIGINAL" in prompt
    assert "not present" in prompt
    # The rationale is still delivered -- it is the only feedback there is.
    assert "breaking the Markdown list formatting" in prompt


def test_a_first_attempt_prompt_says_none_of_this(repo):
    """No rejection, no retry wording, and no change to the first attempt."""
    task = task_for(repo)
    scope = authored_change.require_contract(task)
    existing = authored_change.existing_in_scope(
        str(repo["path"]), repo["base"], scope
    )
    prompt = authored_change.render_author_prompt(
        task, existing, {}, scope=scope,
        retry_from=retry_base.resolve(str(repo["path"]), task),
    )

    assert "A PREVIOUS ATTEMPT" not in prompt
    assert "REJECTED ATTEMPT'S VERSION" not in prompt
    assert "- **No integrator.**" in prompt


# --- The cumulative change is what the contract is enforced against ----------


def test_the_cumulative_diff_is_validated_against_the_original_base(repo):
    """A retry's candidate carries the prior attempt's edits. They are checked.

    The prior attempt's paths were authorised when it was written, so this
    passes in the ordinary case. It exists for the case where the commit being
    built on is not what this task produced -- where the range handed to a
    reviewer would contain changes nobody authorised.
    """
    task = task_for(repo, candidate=repo["rejected"], allowed=("docs/",))
    scope = authored_change.require_contract(task)

    work = repo["path"].parent / "work"
    git(repo["path"], "worktree", "add", "-q", "--detach", str(work),
        repo["rejected"])

    with pytest.raises(authored_change.AuthoringError) as caught:
        authored_change.apply_and_commit(
            str(work),
            branch="task/retry",
            base=repo["rejected"],
            original_base=repo["base"],
            files=[("docs/notes.md", "fine\n")],
            message="retry",
            scope=scope,
        )

    # README.md is outside `docs/`, and it is in the range only because the
    # rejected candidate changed it.
    assert "README.md" in str(caught.value)
    assert "does not authorise" in str(caught.value)

    # And the refusal left nothing behind.
    assert authored_change.worktree_is_clean(str(work))
    assert git(work, "rev-parse", "--verify", "task/retry",
               check=False).returncode != 0


def test_an_in_scope_retry_commits_and_reports_the_cumulative_files(repo):
    task = task_for(repo, candidate=repo["rejected"])
    scope = authored_change.require_contract(task)

    work = repo["path"].parent / "work-ok"
    git(repo["path"], "worktree", "add", "-q", "--detach", str(work),
        repo["rejected"])

    moved = README_AT_BASE.replace(
        "- **No integrator.** `READY_INTEGRATION` is where tasks stop. Nothing merges.\n",
        "",
    ).replace(
        "## Deliberately not done yet",
        "- **Integration.** `integrator.py` merges a candidate and the task "
        "reaches `COMPLETE`.\n\n## Deliberately not done yet",
    )

    result = authored_change.apply_and_commit(
        str(work),
        branch="task/retry-ok",
        base=repo["rejected"],
        original_base=repo["base"],
        files=[("README.md", moved)],
        message="retry",
        scope=scope,
    )

    assert result["original_base"] == repo["base"]
    assert result["cumulative_files"] == ["README.md"]
    # The commit descends from the rejected candidate, so the range the
    # reviewer reads from the task's base contains both attempts.
    assert git(work, "merge-base", "--is-ancestor", repo["rejected"],
               result["candidate_sha"], check=False).returncode == 0
