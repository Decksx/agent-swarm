"""Landing an approved candidate, and refusing to land anything else.

`READY_INTEGRATION` is where every task in this system has stopped. The state
machine has modelled integration since v7 -- `integration_started`,
`integration_completed`, `rollback_started` -- and nothing has ever driven it.
This does, for one candidate at a time, and it refuses far more often than it
merges.

What it will not do, and why each one
-------------------------------------

**It will not resolve a conflict.** Not a whitespace one, not an obvious one.
A conflict means the approved tree and the target have both moved the same
lines, so the thing that would land is not the tree anybody reviewed -- it is a
new tree this program invented, carrying a judgment no reviewer made. The merge
is refused and a person is told which files.

**It will not alter business logic, reformat, or "fix up" anything.** The
approved tree lands byte for byte or it does not land. An integrator that
touches content is an author with commit access and no review.

**It will not merge a candidate whose SHA is not the approved one.** The
approval names a commit. A branch that has moved since -- one more push, an
amended commit, a force-push -- is a different tree wearing an approved name,
and it is the failure most likely to look like success.

**It will not merge into a target that moved.** The expected target SHA is
pinned before anything happens and checked again immediately before the merge.
A target that advanced in between may have introduced exactly the change the
candidate conflicts with, and the evidence was gathered against the old one.

**It will not accept "the tests passed" as a sentence.** Evidence is named
suites with counts and exit statuses, and a suite reporting zero passing tests
is refused the same way the deploy gate refuses one -- "nothing failed" is not
"something passed".

**It will not report COMPLETE until the remote says so.** A merge API returning
200 is a claim about a request, not about the repository. The target is fetched
afterwards and the merge commit has to be in it.

Why the PR path rather than a local merge
-----------------------------------------

The canonical checkout is permanently dirty -- it carries somebody's work in
progress, fourteen entries at the time of writing -- and merging in it would
mix that work into the merge commit or fail on a checkout it should never have
been touching. The remote already holds both refs; the merge belongs where
neither depends on this host's working tree.

It also means the merge is performed by the forge, under the same rules a
person's merge obeys, and leaves a record that does not depend on this program
having told the truth about what it did.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

SHA = re.compile(r"^[0-9a-f]{40}$")

# The states from which integration may begin. Exactly one, and it is the one
# a review moved the task into.
INTEGRABLE = "READY_INTEGRATION"


class IntegrationRefused(Exception):
    """The candidate will not be integrated, and why."""


@dataclass(frozen=True)
class Evidence:
    """One test suite's result, as a fact rather than an assurance."""

    name: str
    command: str
    exit_code: int
    passed: int
    failed: int = 0
    skipped: int = 0
    ran_at: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "command": self.command,
            "exit_code": self.exit_code, "passed": self.passed,
            "failed": self.failed, "skipped": self.skipped,
            "ran_at": self.ran_at,
        }


@dataclass(frozen=True)
class Plan:
    """Everything the integration was authorised to do, pinned.

    Built once, before anything is checked, so every later step compares
    against one statement of intent rather than re-reading the world and
    silently agreeing with whatever it finds.
    """

    task_id: str
    repo: str
    candidate_sha: str
    target_ref: str
    target_sha_expected: str
    pr_number: Optional[int] = None
    evidence: tuple[Evidence, ...] = ()

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id, "repo": self.repo,
            "candidate_sha": self.candidate_sha,
            "target_ref": self.target_ref,
            "target_sha_expected": self.target_sha_expected,
            "pr_number": self.pr_number,
            "evidence": [e.as_dict() for e in self.evidence],
        }


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )


def check_approval(task: Mapping[str, Any], plan: Plan) -> None:
    """The controller's state is the approval. Nothing else is.

    Not a flag in a payload, not the presence of a review comment: the task
    is in READY_INTEGRATION or it is not, because that state is reachable only
    through `review_requirements_satisfied` applied with controller authority
    on a live review activation.
    """
    state = str(task.get("state") or "").strip()

    if state != INTEGRABLE:
        raise IntegrationRefused(
            f"{plan.task_id} is {state or 'in no state at all'}, not "
            f"{INTEGRABLE}. Approval is the controller's state and is not "
            "conferred by anything else."
        )

    approved = str(task.get("candidate_sha") or "").strip()

    # When the task records which candidate was reviewed, it must be this one.
    # A task that does not record one cannot be checked here, and that is
    # reported rather than waved through.
    if not approved:
        raise IntegrationRefused(
            f"{plan.task_id} is {INTEGRABLE} but records no candidate_sha, so "
            "there is nothing to check the merge against. Refusing to assume "
            "the branch head is what was reviewed."
        )

    if approved != plan.candidate_sha:
        raise IntegrationRefused(
            f"{plan.task_id} approved {approved[:12]}, and this integration "
            f"was asked to land {plan.candidate_sha[:12]}. A branch that has "
            "moved since approval is a different tree wearing an approved "
            "name."
        )


def check_evidence(plan: Plan, *, required: Sequence[str]) -> None:
    """Named suites, each green, each having actually run something."""
    if not plan.evidence:
        raise IntegrationRefused(
            f"{plan.task_id}: no test evidence. 'The tests passed' is not a "
            "sentence this accepts; name the suites, their exit statuses and "
            "their counts."
        )

    by_name = {e.name: e for e in plan.evidence}

    for name in required:
        if name not in by_name:
            raise IntegrationRefused(
                f"{plan.task_id}: required suite {name!r} has no evidence. "
                f"Supplied: {', '.join(sorted(by_name)) or '(none)'}"
            )

    for entry in plan.evidence:
        if entry.exit_code != 0:
            raise IntegrationRefused(
                f"{plan.task_id}: suite {entry.name!r} exited "
                f"{entry.exit_code}. An approved candidate whose tests do not "
                "pass is not integrable, whatever the review said."
            )

        if entry.failed:
            raise IntegrationRefused(
                f"{plan.task_id}: suite {entry.name!r} reports "
                f"{entry.failed} failure(s) alongside exit 0, which is a "
                "result nobody should have to reconcile. Refusing."
            )

        # The deploy gate's rule, for the same reason: a suite that skipped
        # everything exits 0 having verified nothing, and "no failures"
        # renders almost identically to "no tests".
        if entry.passed <= 0:
            raise IntegrationRefused(
                f"{plan.task_id}: suite {entry.name!r} exited 0 with "
                f"{entry.passed} passing tests. 'Nothing failed' is not "
                "'something passed'."
            )


def pin_target(plan: Plan) -> str:
    """The target's SHA right now, from the remote, or refuse.

    Read from the remote rather than a local ref: the local one is whatever
    this host last fetched, and integrating against a stale idea of the target
    is the same class of error as integrating a stale candidate.
    """
    result = _git(plan.repo, "ls-remote", "origin", plan.target_ref)

    if result.returncode != 0:
        raise IntegrationRefused(
            f"could not read {plan.target_ref} from the remote: "
            f"{(result.stderr or '').strip()}"
        )

    line = (result.stdout or "").strip().splitlines()
    sha = line[0].split()[0] if line else ""

    if not SHA.match(sha):
        raise IntegrationRefused(
            f"{plan.target_ref} did not resolve to a commit on the remote "
            f"(got {sha!r})"
        )

    return sha


def check_target_unmoved(plan: Plan) -> str:
    """The target is where it was pinned, or the integration is abandoned.

    Called immediately before the merge, not only at the start. The window
    between the two is exactly where somebody else's merge lands, and a target
    that advanced in it may carry the change this candidate conflicts with --
    against which none of the evidence was gathered.
    """
    now = pin_target(plan)

    if now != plan.target_sha_expected:
        raise IntegrationRefused(
            f"{plan.target_ref} was {plan.target_sha_expected[:12]} when this "
            f"integration was authorised and is {now[:12]} now. It moved. The "
            "evidence was gathered against the old target; re-run it against "
            "the new one rather than merging on the strength of the old."
        )

    return now


def check_pr(plan: Plan, *, repo_slug: str) -> dict:
    """The pull request is the one approved, still open, and not conflicted.

    `mergeable` is the forge's own answer to "would this apply cleanly". A
    conflicted PR is refused here and never resolved: the tree that would land
    after a resolution is not the tree anybody reviewed.
    """
    result = _gh(
        "pr", "view", str(plan.pr_number), "--repo", repo_slug,
        "--json", "number,state,isDraft,headRefOid,baseRefOid,baseRefName,mergeable,mergeStateStatus",
    )

    if result.returncode != 0:
        raise IntegrationRefused(
            f"could not read PR #{plan.pr_number}: {(result.stderr or '').strip()}"
        )

    pr = json.loads(result.stdout or "{}")

    if pr.get("state") != "OPEN":
        raise IntegrationRefused(
            f"PR #{plan.pr_number} is {pr.get('state')}, not OPEN"
        )

    if pr.get("isDraft"):
        raise IntegrationRefused(
            f"PR #{plan.pr_number} is still a draft. A draft is a request for "
            "review, not a request to merge; marking it ready is a person's "
            "decision and deliberately not this program's."
        )

    if pr.get("headRefOid") != plan.candidate_sha:
        raise IntegrationRefused(
            f"PR #{plan.pr_number} head is {str(pr.get('headRefOid'))[:12]}, "
            f"and the approved candidate is {plan.candidate_sha[:12]}. The "
            "branch moved after approval."
        )

    if pr.get("baseRefOid") != plan.target_sha_expected:
        raise IntegrationRefused(
            f"PR #{plan.pr_number} is based on "
            f"{str(pr.get('baseRefOid'))[:12]}, and the pinned target is "
            f"{plan.target_sha_expected[:12]}."
        )

    if pr.get("mergeable") == "CONFLICTING":
        raise IntegrationRefused(
            f"PR #{plan.pr_number} conflicts with {plan.target_ref}. This "
            "will not resolve it: the tree that would land after a resolution "
            "is not the tree that was reviewed. A person resolves it, and the "
            "result is reviewed again."
        )

    if pr.get("mergeable") != "MERGEABLE":
        raise IntegrationRefused(
            f"PR #{plan.pr_number} reports mergeable="
            f"{pr.get('mergeable')!r}. Refusing to merge on an answer that is "
            "not yes."
        )

    return pr


def verify_landed(plan: Plan, merge_sha: str) -> None:
    """The remote target actually contains the merge. Checked, not assumed.

    A merge API returning success is a claim about a request. This is the only
    statement that means the change is in the branch, and it is why COMPLETE
    is not reported before it.
    """
    fetched = _git(plan.repo, "fetch", "origin", plan.target_ref)

    if fetched.returncode != 0:
        raise IntegrationRefused(
            f"merged as {merge_sha[:12]} but could not fetch "
            f"{plan.target_ref} to confirm it: {(fetched.stderr or '').strip()}"
        )

    now = pin_target(plan)

    if now == plan.target_sha_expected:
        raise IntegrationRefused(
            f"the merge reported {merge_sha[:12]} but {plan.target_ref} is "
            f"still at {now[:12]}. Nothing landed."
        )

    contains = _git(plan.repo, "merge-base", "--is-ancestor", merge_sha, now)

    if contains.returncode != 0:
        raise IntegrationRefused(
            f"{plan.target_ref} is now {now[:12]}, which does not contain "
            f"{merge_sha[:12]}. Something else landed; this integration "
            "cannot be reported as complete."
        )


def ledger_record(plan: Plan, *, target_before: str, merge_sha: str,
                  target_after: str, authority: str, actor: str) -> dict:
    """What the ledger is told. Every figure here was measured, not assumed."""
    return {
        "task_id": plan.task_id,
        "candidate_sha": plan.candidate_sha,
        "target_ref": plan.target_ref,
        "target_sha_before": target_before,
        "merge_sha": merge_sha,
        "target_sha_after": target_after,
        "pr_number": plan.pr_number,
        "evidence": [e.as_dict() for e in plan.evidence],
        "authority": authority,
        "actor": actor,
        "method": "github_pr_merge",
    }
