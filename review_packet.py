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

The range, not the branch
-------------------------

Everything is derived from the immutable range ``base..candidate``. The branch
is a label: it is checked for agreement with the candidate and otherwise plays
no part. A branch names whatever its tip is at the moment it is read, so
reviewing "the branch" means a commit pushed between issue and review changes
what was judged -- and the ledger would record an approval of a commit nobody
looked at.

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

import os
import re
import subprocess
from typing import Optional

import authored_change

# Generous enough for an ordinary change, small enough that a runaway diff is
# reported as one instead of silently filling a prompt.
DEFAULT_DIFF_BUDGET = 60_000

# How much of the removed-lines report the reviewer is shown (#35). The full
# diff already carries every line; this is the part a reviewer must not miss.
REMOVAL_LINE_BUDGET = 200
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")

# Configuration a change starts reading, and how far the packet chases it (#34).
CONFIG_NAME_BUDGET = 20
CONFIG_SAMPLE_PATHS = 4
CONFIG_READS = (
    re.compile(r"""os\.environ\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*(?:,\s*([^)]*))?\)"""),
    re.compile(r"""os\.getenv\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*(?:,\s*([^)]*))?\)"""),
    re.compile(r"""os\.environ\[\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*\]"""),
    re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
)


class PacketError(Exception):
    """The repository could not answer a question the packet needs."""


# Git must not reach the network to answer a question about a commit it was
# told to read (#64).
#
# Choosing read-only subcommands is not enough, and that was the gap review
# found. In a partial or promisor clone, `cat-file`, `diff` and `rev-parse`
# will fetch missing objects *themselves*, from inside git, without anything
# here launching `git fetch`. A test that inspects the subcommands this code
# runs cannot see that happen.
#
# `GIT_NO_LAZY_FETCH=1` turns those internal fetches into failures, which is
# the behaviour this wants: a candidate that is not already present is absent,
# and absence is a refusal rather than something to go and fix over the
# network. `GIT_TERMINAL_PROMPT=0` means any fetch that somehow still occurs
# fails instead of blocking on a credential prompt in a background worker.
def offline_env(base: Optional[dict] = None) -> dict:
    """The environment every git call in a review runs under."""
    env = dict(os.environ if base is None else base)
    env["GIT_NO_LAZY_FETCH"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"

    return env


def _git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=offline_env(),
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


def is_reachable_from(repo: str, commit: str, ref: str) -> bool:
    """Whether `commit` is `ref` or an ancestor of it."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, ref],
        cwd=repo, capture_output=True, check=False, env=offline_env(),
    )

    return result.returncode == 0


def pure_deletions(repo: str, base_sha: str, candidate_sha: str) -> tuple:
    """([{path, start, lines}], truncated): hunks that remove lines and add none.

    The shape of the defect #35 is about. An author regenerating a file drops
    a block it was never asked to touch, and in the diff that block is a hunk
    with minus lines and no plus lines -- easy to scroll past in a long diff,
    and deterministic to find. A hunk that replaces lines is not listed: the
    replacement is the change, and the diff shows it.
    """
    text = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff",
                f"{base_sha}..{candidate_sha}")
    found, path, current, budget = [], "", None, REMOVAL_LINE_BUDGET
    truncated = False
    removing = adding = 0

    for line in text.splitlines():
        # Inside a hunk the header's counts say what each line is, so a
        # removed line that itself begins "-- " is never read as a file header.
        if removing or adding:
            if line.startswith("-") and removing:
                removing -= 1

                if current is not None:
                    if budget > 0:
                        current["lines"].append(line[1:])
                        budget -= 1
                    else:
                        truncated = True
            elif line.startswith("+") and adding:
                adding -= 1
            continue

        if line.startswith("--- "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("a/") else path
            continue

        header = HUNK_HEADER.match(line)

        if header:
            removing = int(header.group(2) if header.group(2) is not None else 1)
            adding = int(header.group(3) if header.group(3) is not None else 1)
            current = None

            if removing and not adding:
                current = {"path": path, "start": int(header.group(1)), "lines": []}
                found.append(current)

    return [hunk for hunk in found if hunk["lines"]], truncated


def _added_lines(diff_text: str) -> list:
    """The lines a diff adds, read by hunk count so content is never a header."""
    added, removing, adding = [], 0, 0

    for line in diff_text.splitlines():
        if removing or adding:
            if line.startswith("-") and removing:
                removing -= 1
            elif line.startswith("+") and adding:
                adding -= 1
                added.append(line[1:])
            continue

        header = HUNK_HEADER.match(line)

        if header:
            removing = int(header.group(2) if header.group(2) is not None else 1)
            adding = int(header.group(3) if header.group(3) is not None else 1)

    return added


def configuration_reads(repo: str, base_sha: str, candidate_sha: str) -> list:
    """[{name, default, elsewhere, only_tests}] for configuration the change starts reading.

    T-CMD-614eafb32c asked for the controller's build id in the hub header.
    The candidate read `os.environ.get("CONTROLLER_BUILD_ID", "unknown")` --
    a variable nothing in the repository sets, so the page would have shown
    "unknown" forever -- and its test passed because the test supplied the
    value. The review named the broken test and an unrelated deletion, not
    that.

    A name is looked for everywhere else at the candidate commit, and where it
    is found is reported rather than judged: the packet cannot see a
    deployment's own environment, so "nowhere else in the repository" is a
    question for the reviewer, not a verdict. Finding it only under tests is
    the case above, and is marked.
    """
    diff_text = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff",
                     f"{base_sha}..{candidate_sha}")
    changed = {
        line.split("\t")[-1].strip()
        for line in _git(repo, "diff", "--name-only", f"{base_sha}..{candidate_sha}").splitlines()
        if line.strip()
    }

    found: dict = {}

    for line in _added_lines(diff_text):
        for pattern in CONFIG_READS:
            for match in pattern.finditer(line):
                name = match.group(1)
                default = ""

                if pattern.groups > 1 and match.lastindex and match.lastindex > 1:
                    default = (match.group(2) or "").strip()

                if name not in found and len(found) < CONFIG_NAME_BUDGET:
                    found[name] = default

    reads = []

    for name, default in found.items():
        hits = _git(repo, "grep", "-l", "--fixed-strings", "-e", name, candidate_sha,
                    check=False).splitlines()
        elsewhere = sorted({
            hit.split(":", 1)[1] for hit in hits if ":" in hit
        } - changed)
        reads.append({
            "name": name,
            "default": default,
            "elsewhere": elsewhere[:CONFIG_SAMPLE_PATHS],
            "elsewhere_count": len(elsewhere),
            "only_tests": bool(elsewhere) and all(
                path.startswith("tests/") or "test_" in path for path in elsewhere
            ),
        })

    return reads


def build(
    repo: str,
    *,
    task: dict,
    base: str,
    candidate: str,
    branch: str = "",
    author_summary: str = "",
    test_output: str = "",
    diff_budget: int = DEFAULT_DIFF_BUDGET,
    operator_context: dict | None = None,
) -> dict:
    """Assemble the review evidence for the range `base..candidate`.

    **The range is the review, and both ends are commits.** `branch` is only a
    label, checked for consistency and otherwise not used to decide what is
    reviewed. That distinction is the whole point of this signature: a branch
    names whatever its tip happens to be at the moment it is read, so a branch
    that moves between issue and review silently changes what the reviewer
    judged -- and the ledger would record an approval of a commit nobody
    looked at.

    When `branch` is given, the candidate must be reachable from it. A
    candidate that is not on the branch it claims to be on means the two pieces
    of evidence disagree, and guessing which one is right is not this
    function's job.
    """
    base_sha = resolve(repo, base)
    candidate_sha = resolve(repo, candidate)

    if base_sha == candidate_sha:
        raise PacketError(
            f"base and candidate are the same commit ({candidate_sha[:12]}); "
            "there is nothing to review"
        )

    if branch:
        try:
            branch_tip = resolve(repo, branch)
        except PacketError as exc:
            raise PacketError(f"declared branch {branch!r} not found: {exc}")

        if not is_reachable_from(repo, candidate_sha, branch_tip):
            raise PacketError(
                f"candidate {candidate_sha[:12]} is not reachable from "
                f"{branch!r} (tip {branch_tip[:12]}); the branch and the "
                "candidate disagree about what was submitted"
            )

    if not is_reachable_from(repo, base_sha, candidate_sha):
        raise PacketError(
            f"base {base_sha[:12]} is not an ancestor of candidate "
            f"{candidate_sha[:12]}; the range is not a straight line and the "
            "diff would not be the author's work alone"
        )

    changed = [
        line for line in _git(
            repo, "diff", "--name-status", f"{base_sha}..{candidate_sha}"
        ).splitlines() if line.strip()
    ]

    commits = [
        line for line in _git(
            repo, "log", "--oneline", "--no-decorate", f"{base_sha}..{candidate_sha}"
        ).splitlines() if line.strip()
    ]

    diff = _git(repo, "diff", f"{base_sha}..{candidate_sha}")
    truncated = len(diff.encode("utf-8")) > diff_budget

    if truncated:
        diff = diff.encode("utf-8")[:diff_budget].decode("utf-8", "ignore")

    removals, removals_truncated = pure_deletions(repo, base_sha, candidate_sha)
    reads = configuration_reads(repo, base_sha, candidate_sha)

    return {
        "task_id": task.get("task_id"),
        "title": task.get("title", ""),
        "objective": task.get("objective", ""),
        # Carried into the packet so it reaches the prompt. A reviewer resuming
        # after an escalation has to know what the operator decided, or it
        # judges the candidate against the question rather than the answer.
        "operator_context": operator_context,
        "branch": branch,
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "commits": commits,
        "changed_files": changed,
        "diff": diff,
        "diff_truncated": truncated,
        "pure_deletions": removals,
        "pure_deletions_truncated": removals_truncated,
        "configuration_reads": reads,
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
        *authored_change.operator_section(packet.get("operator_context")),
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

    if packet.get("pure_deletions"):
        parts += [
            "",
            "LINES REMOVED WITH NOTHING ADDED IN THEIR PLACE",
            "Each block below is deleted outright by this change. Unless the "
            "objective or acceptance criteria require removing it, that is a reason "
            "for CHANGES_REQUESTED: an author can drop lines it was never asked to "
            "touch, and this is what that looks like.",
        ]

        for hunk in packet["pure_deletions"]:
            end = hunk["start"] + len(hunk["lines"]) - 1
            parts += ["", f"  {hunk['path']}, base lines {hunk['start']}-{end}:",
                      *(f"    - {line}" for line in hunk["lines"])]

        if packet.get("pure_deletions_truncated"):
            parts += ["", "  [more removed lines are not listed here; see the full diff]"]

    if packet.get("configuration_reads"):
        parts += [
            "",
            "CONFIGURATION THIS CHANGE STARTS READING",
            "Where each name appears elsewhere at the candidate commit. A name "
            "nothing else provides means the production path runs on its default, "
            "whatever the tests do; a name provided only by tests means the test "
            "supplies the value the code reads, which proves nothing about "
            "production. Either is CHANGES_REQUESTED unless the objective or the "
            "acceptance criteria say who sets it -- the repository cannot show a "
            "deployment's own environment, so say which you are relying on.",
        ]

        for read in packet["configuration_reads"]:
            default = f' (default {read["default"]})' if read["default"] else ""
            extra = read["elsewhere_count"] - len(read["elsewhere"])
            where = ", ".join(read["elsewhere"]) + (f" (+{extra} more)" if extra > 0 else "")
            parts.append(
                f"  {read['name']}{default} -- "
                + ("named nowhere else in the repository" if not read["elsewhere"]
                   else ("only in tests: " if read["only_tests"] else "also in: ") + where)
            )

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
        "APPROVE means the diff meets the objective and acceptance criteria "
        "through the code path that runs in production, not only under test. A "
        "test that supplies the value the code reads proves nothing about "
        "production, and a mock, placeholder or simulated value standing in for "
        "the real source is CHANGES_REQUESTED -- name the real source when the "
        "diff or the packet shows it.",
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
