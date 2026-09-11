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

# The states in which a standing approval is live and may be acted on.
#
# Both, and this was a real defect: issuing an integration activation emits
# `integration_started`, which moves the task to INTEGRATING before the worker
# has done anything at all. Accepting only READY_INTEGRATION meant the
# integrator refused every task that had been properly assigned to it, and
# accepted only ones with no activation -- precisely backwards.
#
# INTEGRATING is safe to include because the approval survives it:
# `integration_started` is not in `engine.APPROVAL_CLEARING`, so
# `approved_candidate_sha` still holds the commit the review approved. Every
# event that would invalidate it clears it, and a cleared approval refuses
# here whatever the state says.
INTEGRABLE = "READY_INTEGRATION"
INTEGRABLE_STATES = frozenset({"READY_INTEGRATION", "INTEGRATING"})


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


def approved_candidate(task: Mapping[str, Any]) -> str:
    """The commit this task's review approved, from the controller. Or refuse.

    **Derived, never supplied.** There is deliberately no parameter here for a
    caller to pass a SHA in and have it agreed with. An operator assembling an
    integration request is not a source of truth about what a reviewer
    approved, and a function that accepted one would make the whole column
    decorative: whoever typed the request would decide what got merged.

    `approved_candidate_sha` is written by the controller inside the same
    transaction as `review_requirements_satisfied`, from the activation's own
    `expected_candidate` -- the commit the controller issued the review
    against. It is cleared by every event that invalidates the approval. So a
    non-NULL value here means exactly one thing, and reading it is enough.

    NULL is the normal state and the safe one. A task approved before this
    column existed has NULL, and refusing it is correct: nothing records which
    candidate that approval was for, and assuming the branch head would be
    inventing the answer.
    """
    task_id = str(task.get("task_id") or "(unknown)")
    state = str(task.get("state") or "").strip()

    if state not in INTEGRABLE_STATES:
        raise IntegrationRefused(
            f"{task_id} is {state or 'in no state at all'}, and an approval "
            f"is only live in {', '.join(sorted(INTEGRABLE_STATES))}. "
            "Approval is the controller's state and is not conferred by "
            "anything else."
        )

    approved = str(task.get("approved_candidate_sha") or "").strip()

    if not approved:
        raise IntegrationRefused(
            f"{task_id} is {INTEGRABLE} but carries no "
            "approved_candidate_sha. Either the approval predates the column, "
            "or something cleared it -- a rejection, a retry, or a newer "
            "candidate. Refusing to assume the branch head is what was "
            "reviewed."
        )

    if not SHA.match(approved):
        raise IntegrationRefused(
            f"{task_id}: approved_candidate_sha is {approved!r}, not a commit"
        )

    return approved


def check_approval(task: Mapping[str, Any], plan: Plan) -> None:
    """The plan lands exactly what the controller says was approved.

    The comparison is one-directional on purpose: `approved_candidate()`
    establishes the truth from the ledger, and this checks that the plan
    agrees with it. A plan that disagrees is refused rather than corrected --
    silently substituting the approved SHA would hide that the request was
    built against something else, and whatever produced it would go on being
    wrong.
    """
    approved = approved_candidate(task)

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


def ci_evidence(candidate_sha: str, *, repo_slug: str) -> tuple[Evidence, ...]:
    """The runner's own verdict on this exact commit. Derived, never supplied.

    Asked for **by commit SHA**, not by branch and not by PR. A branch's checks
    are the checks of whatever its head happens to be now; this integration is
    about one commit, and the evidence has to be about the same one or it is
    evidence about something else.

    Every returned check is reported, including failures -- `check_evidence`
    decides what that means. Returning only the passes would make a red build
    indistinguishable from a repository with no CI at all, and those need
    opposite responses.
    """
    result = _gh(
        "api", f"repos/{repo_slug}/commits/{candidate_sha}/check-runs",
        "--jq", ".check_runs[] | {name, conclusion, status, id}",
    )

    if result.returncode != 0:
        raise IntegrationRefused(
            f"could not read CI for {candidate_sha[:12]}: "
            f"{(result.stderr or '').strip()}. A build whose status cannot be "
            "read is not a build that passed."
        )

    runs = [
        json.loads(line) for line in (result.stdout or "").splitlines()
        if line.strip()
    ]

    evidence = []

    for run in runs:
        conclusion = str(run.get("conclusion") or "").lower()
        status = str(run.get("status") or "").lower()

        if status != "completed":
            raise IntegrationRefused(
                f"CI check {run.get('name')!r} on {candidate_sha[:12]} is "
                f"{status!r}, not completed. Merging while a check is still "
                "running is merging on a result nobody has."
            )

        # `passed` is 1 for a successful check and 0 otherwise, so a red or
        # skipped check reaches check_evidence()'s "nothing failed is not
        # something passed" rule rather than needing a second one here.
        evidence.append(Evidence(
            name=f"ci:{run.get('name')}",
            command=f"github check-run {run.get('id')}",
            exit_code=0 if conclusion == "success" else 1,
            passed=1 if conclusion == "success" else 0,
            failed=0 if conclusion in ("success", "skipped", "neutral") else 1,
            skipped=1 if conclusion == "skipped" else 0,
        ))

    return tuple(evidence)


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


def merge_pr(plan: Plan, *, repo_slug: str, expected_head: str) -> str:
    """Ask the forge to merge, naming the commit that must still be the head.

    `--match-head-commit` is the whole safety of this call. Without it the
    merge is "merge PR #N", and a push landing between the check and the call
    would be merged instead -- the exact race every check above exists to
    close, left open at the one moment it matters. With it, the forge refuses
    rather than merging something else.

    A merge commit, not a squash or a rebase. Both of those construct a commit
    whose tree is the merge result but whose history is not the reviewed
    candidate, so `git diff <candidate> <result>` stops being the check that
    proves the reviewed tree landed.
    """
    result = _gh(
        "pr", "merge", str(plan.pr_number), "--repo", repo_slug,
        "--merge", "--match-head-commit", expected_head,
    )

    if result.returncode != 0:
        raise IntegrationRefused(
            f"the merge of PR #{plan.pr_number} was refused by the forge: "
            f"{(result.stderr or '').strip()}"
        )

    merged = _gh(
        "pr", "view", str(plan.pr_number), "--repo", repo_slug,
        "--json", "mergeCommit,state",
    )

    if merged.returncode != 0:
        raise IntegrationRefused(
            f"merged PR #{plan.pr_number} but could not read the resulting "
            f"commit: {(merged.stderr or '').strip()}"
        )

    body = json.loads(merged.stdout or "{}")
    merge_sha = str((body.get("mergeCommit") or {}).get("oid") or "").strip()

    if not SHA.match(merge_sha):
        raise IntegrationRefused(
            f"PR #{plan.pr_number} reports merge commit {merge_sha!r}, which "
            "is not a commit. Refusing to report an integration whose result "
            "cannot be named."
        )

    return merge_sha


def check_merge_parents(plan: Plan, merge_sha: str) -> None:
    """The merge joined the pinned target to the approved candidate. Exactly.

    This is the answer to the gap `--match-head-commit` leaves open, and the
    gap is real: that flag pins the PR *head*, so a push to the candidate
    branch between the last check and the merge is refused -- but nothing pins
    the *base*. Another merge landing on the target in the same window is
    accepted, and what lands is a combined tree nobody reviewed.

    There is no base equivalent of `--match-head-commit` to ask for, so this
    does not try to check harder beforehand. A pre-merge check can always be
    overtaken; the window cannot be closed by making it smaller.

    Instead the result is proved. A merge commit's first parent is the branch
    it was merged INTO and its second is what was merged IN, and both are
    facts about the commit rather than about the moment it was created. If the
    first parent is not the target this integration pinned, the target moved
    and the merge combined the candidate with something else -- and that is
    visible afterwards no matter how the race ran.

    A refusal here means the merge already happened. It is reported so a
    person reconciles it, which is the same situation an expired integration
    leaves behind, and it is why saying so precisely matters.
    """
    result = _git(plan.repo, "rev-list", "--parents", "-n", "1", merge_sha)

    if result.returncode != 0:
        raise IntegrationRefused(
            f"could not read the parents of {merge_sha[:12]}: "
            f"{(result.stderr or '').strip()}"
        )

    parts = (result.stdout or "").split()

    if len(parts) != 3:
        raise IntegrationRefused(
            f"{merge_sha[:12]} has {max(len(parts) - 1, 0)} parent(s); a merge "
            "of one candidate into one target has exactly two. What landed is "
            "not the merge this integration asked for."
        )

    _, first_parent, second_parent = parts

    if first_parent != plan.target_sha_expected:
        raise IntegrationRefused(
            f"{merge_sha[:12]} was merged into {first_parent[:12]}, and this "
            f"integration pinned {plan.target_sha_expected[:12]}. The target "
            "moved between the final check and the merge, so what landed "
            "combines the approved candidate with a commit nobody reviewed "
            "alongside it. The merge has already happened; reconcile it."
        )

    if second_parent != plan.candidate_sha:
        raise IntegrationRefused(
            f"{merge_sha[:12]} merged in {second_parent[:12]}, not the "
            f"approved candidate {plan.candidate_sha[:12]}."
        )


def check_tree_identical(plan: Plan, merge_sha: str) -> None:
    """The merged tree is the approved tree, compared rather than assumed.

    The last check, and the one that catches everything the others cannot: a
    squash that rewrote content, a merge driver that silently resolved
    something, a forge setting nobody knew was on. If this differs, the thing
    on the target is not what was reviewed however clean every earlier step
    looked.
    """
    diff = _git(plan.repo, "diff", "--name-only", plan.candidate_sha, merge_sha)

    if diff.returncode != 0:
        raise IntegrationRefused(
            f"could not compare {plan.candidate_sha[:12]} with "
            f"{merge_sha[:12]}: {(diff.stderr or '').strip()}"
        )

    changed = [line for line in (diff.stdout or "").splitlines() if line.strip()]

    if changed:
        raise IntegrationRefused(
            f"the merged tree differs from the approved candidate in "
            f"{len(changed)} file(s): {', '.join(changed[:5])}. What landed "
            "is not what was reviewed."
        )


def run_integration(
    task: Mapping[str, Any],
    *,
    repo: str,
    target_ref: str,
    pr_number: int,
    repo_slug: str,
    required_suites: Sequence[str] = (),
    actor: str = "claudecode",
) -> dict:
    """One integration attempt, in the only order that is safe.

    The order is the design. Everything derivable is derived before anything
    is done, the target is re-pinned immediately before the merge rather than
    trusted from the start, and every claim about the result is checked
    against the remote afterwards rather than taken from the API's response.

        1. approval      from the controller ledger, never from a caller
        2. target        pinned from the remote
        3. evidence      from the runner, by commit SHA
        4. PR            open, not draft, head is the approval, no conflict
        5. target again  unmoved since step 2
        6. merge         naming the head that must still be current
        7. landed        refetch; the target must contain the merge
        8. parents       the merge joined the PINNED target to the approval
        9. tree          the merged tree equals the approved tree

    Returns the ledger record. Raises `IntegrationRefused` at the first step
    that does not hold, having changed nothing -- every step before the merge
    is a read.
    """
    candidate = approved_candidate(task)

    plan = Plan(
        task_id=str(task.get("task_id") or ""),
        repo=repo,
        candidate_sha=candidate,
        target_ref=target_ref,
        target_sha_expected="",
        pr_number=pr_number,
    )

    target_before = pin_target(plan)
    plan = Plan(**{**plan.__dict__, "target_sha_expected": target_before,
                   "evidence": ci_evidence(candidate, repo_slug=repo_slug)})

    check_evidence(plan, required=required_suites)
    check_pr(plan, repo_slug=repo_slug)
    check_target_unmoved(plan)

    merge_sha = merge_pr(plan, repo_slug=repo_slug, expected_head=candidate)

    verify_landed(plan, merge_sha)
    check_merge_parents(plan, merge_sha)
    check_tree_identical(plan, merge_sha)

    return ledger_record(
        plan,
        target_before=target_before,
        merge_sha=merge_sha,
        target_after=pin_target(plan),
        authority="controller",
        actor=actor,
    )
