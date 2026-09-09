"""Build the evidence a reviewer needs, from the repository rather than prose.

Why this exists
---------------

A reviewer handed only a candidate SHA and the author's own summary is not
reviewing; it is agreeing. The author's account of what it did is exactly the
thing under review, so using it as the evidence makes the review circular --
and a model asked to judge a change it cannot see will produce a confident
verdict anyway, which is worse than refusing.

So the packet is assembled from git: the objective and acceptance criteria the
task was created with, the base and candidate SHAs, the changed-file list, the
full diff, and whatever test output is available. The author's summary is
included, clearly labelled as a claim rather than as evidence.

Where it runs
-------------

On the execution host, in the worker that holds the review activation. The
controller has no working copy and never will -- it stores state, not source.

Size
----

Diffs are truncated at a byte budget rather than sent whole. A diff too large
for one review is a signal about the task, not something to paper over by
sending 400KB into a context window, so truncation is stated in the packet
where the reviewer will see it rather than hidden.
"""

from __future__ import annotations

import subprocess
from typing import Optional

# Generous enough for an ordinary change, small enough that a runaway diff is
# reported as one instead of silently filling a prompt.
DEFAULT_DIFF_BUDGET = 60_000


class PacketError(Exception):
    """The repository could not answer a question the packet needs."""


def _git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if check and result.returncode != 0:
        raise PacketError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or '').strip()[:300]}"
        )

    return result.stdout or ""


def resolve(repo: str, ref: str) -> str:
    """Full 40-character SHA for `ref`, or raise."""
    sha = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()

    if len(sha) != 40:
        raise PacketError(f"{ref!r} did not resolve to a commit sha")

    return sha


def build(
    repo: str,
    *,
    task: dict,
    branch: str,
    base: Optional[str] = None,
    author_summary: str = "",
    test_output: str = "",
    diff_budget: int = DEFAULT_DIFF_BUDGET,
) -> dict:
    """Assemble the review evidence for `branch` in `repo`.

    `base` may be omitted, in which case the merge-base of the branch and its
    first parent is used -- the point the work actually diverged from, which is
    what a reviewer needs to see rather than whatever happens to be on the
    default branch now.
    """
    candidate = resolve(repo, branch)

    if base:
        base_sha = resolve(repo, base)
    else:
        # The commit the branch grew from. Using HEAD of some other branch
        # would show the reviewer unrelated changes as if the author had made
        # them.
        base_sha = _git(repo, "rev-parse", f"{candidate}^").strip()

        if len(base_sha) != 40:
            raise PacketError(
                f"could not determine a base for {branch!r}; pass one explicitly"
            )

    if base_sha == candidate:
        raise PacketError(
            f"base and candidate are the same commit ({candidate[:12]}); "
            "there is nothing to review"
        )

    changed = [
        line for line in _git(
            repo, "diff", "--name-status", f"{base_sha}..{candidate}"
        ).splitlines() if line.strip()
    ]

    commits = [
        line for line in _git(
            repo, "log", "--oneline", "--no-decorate", f"{base_sha}..{candidate}"
        ).splitlines() if line.strip()
    ]

    diff = _git(repo, "diff", f"{base_sha}..{candidate}")
    truncated = len(diff.encode("utf-8")) > diff_budget

    if truncated:
        diff = diff.encode("utf-8")[:diff_budget].decode("utf-8", "ignore")

    return {
        "task_id": task.get("task_id"),
        "title": task.get("title", ""),
        "objective": task.get("objective", ""),
        "branch": branch,
        "base_sha": base_sha,
        "candidate_sha": candidate,
        "commits": commits,
        "changed_files": changed,
        "diff": diff,
        "diff_truncated": truncated,
        "author_summary": author_summary,
        "test_output": test_output,
    }


def render(packet: dict) -> str:
    """Render a packet as the reviewer's prompt.

    Ordered so the reviewer reads what was asked for before it reads what was
    done. The author's summary comes last and is labelled a claim, because a
    reviewer that reads the author's account first tends to look for
    confirmation of it rather than at the diff.
    """
    commits = [f"  {line}" for line in packet["commits"]] or ["  (none)"]
    changed = [f"  {line}" for line in packet["changed_files"]] or ["  (none)"]

    parts = [
        "You are reviewing one change. Judge only what the diff below shows.",
        "",
        f"TASK: {packet['task_id']} -- {packet['title']}",
        "",
        "OBJECTIVE AND ACCEPTANCE CRITERIA",
        packet["objective"] or "(none recorded)",
        "",
        f"BASE SHA      : {packet['base_sha']}",
        f"CANDIDATE SHA : {packet['candidate_sha']}",
        f"BRANCH        : {packet['branch']}",
        "",
        "COMMITS",
        *commits,
        "",
        "CHANGED FILES",
        *changed,
        "",
        "FULL DIFF",
        packet["diff"] or "(empty)",
    ]

    if packet["diff_truncated"]:
        parts += [
            "",
            "[DIFF TRUNCATED -- it exceeded the review budget. If you cannot "
            "judge the change from what is shown, answer BLOCKED and say so "
            "rather than approving what you have not seen.]",
        ]

    parts += [
        "",
        "TEST RESULTS",
        packet["test_output"] or "(none were run or reported)",
        "",
        "AUTHOR'S SUMMARY -- this is the author's own claim about its work, "
        "not evidence. The diff above is the evidence.",
        packet["author_summary"] or "(none)",
        "",
        "-" * 60,
        "Answer in exactly this form, and nothing else:",
        "",
        "VERDICT: <APPROVE|CHANGES_REQUESTED|BLOCKED>",
        "RATIONALE: <one to five sentences saying why, citing the diff>",
        "",
        "APPROVE means the diff meets the objective and acceptance criteria.",
        "CHANGES_REQUESTED means it does not, and the author should try again.",
        "BLOCKED means you could not judge it -- missing evidence, a truncated "
        "diff you cannot work around, or something wrong with the packet "
        "itself. BLOCKED is not a soft rejection: use it when the problem is "
        "with the review, not with the change.",
    ]

    return "\n".join(parts)


VERDICTS = {
    "APPROVE": "satisfied",
    "CHANGES_REQUESTED": "changes_requested",
    "BLOCKED": "blocked",
}


def parse_verdict(text: str) -> tuple:
    """Return (judgment, rationale) from a model's answer.

    A reply that does not contain a recognisable verdict is treated as
    `blocked` rather than guessed at. Inferring approval from prose is how a
    review becomes a rubber stamp: "this looks broadly fine, but" would read as
    approval to any keyword search, and the one case where guessing is most
    tempting is the one where it is least safe.
    """
    if not isinstance(text, str) or not text.strip():
        return "blocked", "the reviewer returned nothing"

    verdict = None
    rationale_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()

        if verdict is None and upper.startswith("VERDICT:"):
            token = upper.split(":", 1)[1].strip().strip(".").strip()
            # Longest first, so CHANGES_REQUESTED is not matched as a prefix of
            # nothing while APPROVE is matched inside "APPROVED".
            for name in sorted(VERDICTS, key=len, reverse=True):
                if token.startswith(name):
                    verdict = VERDICTS[name]
                    break
            continue

        if stripped.upper().startswith("RATIONALE:"):
            rationale_lines.append(stripped.split(":", 1)[1].strip())
        elif rationale_lines:
            rationale_lines.append(stripped)

    rationale = " ".join(part for part in rationale_lines if part).strip()

    if verdict is None:
        return "blocked", (
            "no VERDICT line in the reviewer's reply; refusing to infer one "
            f"from prose. First 200 characters: {text.strip()[:200]!r}"
        )

    return verdict, rationale or "(no rationale given)"
