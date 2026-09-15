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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

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

# A completed check with one of these conclusions has finished without failing.
# Anything else completed -- failure, cancelled, timed_out, action_required,
# startup_failure, stale -- is a red build, and waiting longer will not turn it
# green.
FINISHED_CLEAN = frozenset({"success", "skipped", "neutral"})

# Read at call time, so tests can drive the wait without real seconds passing.
_sleep = time.sleep
_clock = time.monotonic
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


def _read_check_runs(candidate_sha: str, *, repo_slug: str) -> list:
    """Every check run GitHub reports for this exact commit, or refuse."""
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

    try:
        return [
            json.loads(line) for line in (result.stdout or "").splitlines()
            if line.strip()
        ]
    except ValueError as exc:
        raise IntegrationRefused(
            f"unreadable CI listing for {candidate_sha[:12]}: {exc}"
        )


def await_ci(
    candidate_sha: str,
    *,
    repo_slug: str,
    required: Sequence[str] = (),
    wait_seconds: float,
    poll_seconds: float = 30.0,
    heartbeat: Optional[Callable[[], Any]] = None,
) -> None:
    """Wait, within a bound, for this commit's CI to finish. Or refuse.

    Why it waits (#32): the pull request is opened when the candidate is
    submitted, CI starts then and takes minutes, and review takes seconds. So
    integration is issued while the checks are still running, and refusing
    on "not completed" -- which `ci_evidence` rightly does -- sent a good
    candidate back to CHANGES_REQUESTED for being quick.

    Returns once every check reported for the commit has completed cleanly
    and every `required` suite is among them. Refuses at once on a check that
    completed red, naming it: waiting will not change it. Refuses when
    `wait_seconds` pass first, naming what was still pending or missing.

    Only reads, so nothing has been changed whichever way it ends, and
    `ci_evidence` re-reads afterwards: this decides when to look, never what
    the evidence says. `heartbeat` is called before every sleep so the
    activation's lease outlives the wait; the controller never lets a
    heartbeat extend the hard deadline, which stays the outer bound.

    A failed read during the wait is retried on the next poll -- one network
    blip is not a verdict on the build -- and named if the wait runs out.
    """
    deadline = _clock() + wait_seconds
    pending: list = []
    missing: list = sorted(required)
    last_error = ""

    while True:
        try:
            runs = _read_check_runs(candidate_sha, repo_slug=repo_slug)
            last_error = ""
        except IntegrationRefused as exc:
            runs, last_error = None, str(exc)

        if runs is not None:
            by_name = {f"ci:{run.get('name')}": run for run in runs}
            done = {
                name: str(run.get("conclusion") or "").lower()
                for name, run in by_name.items()
                if str(run.get("status") or "").lower() == "completed"
            }
            red = sorted(n for n, c in done.items() if c not in FINISHED_CLEAN)

            if red:
                raise IntegrationRefused(
                    f"CI for {candidate_sha[:12]} finished red: "
                    + ", ".join(f"{n} ({done[n] or 'no conclusion'})" for n in red)
                    + ". An approved candidate whose checks fail is not "
                    "integrable, whatever the review said."
                )

            pending = sorted(set(by_name) - set(done))
            missing = sorted(set(required) - set(by_name))

            if by_name and not pending and not missing:
                return

        now = _clock()

        if now >= deadline:
            raise IntegrationRefused(
                f"CI for {candidate_sha[:12]} did not finish within "
                f"{wait_seconds:.0f}s. Still running: "
                f"{', '.join(pending) or '(none)'}; not yet reported: "
                f"{', '.join(missing) or '(none)'}"
                + (f"; last read failed: {last_error}" if last_error else "")
                + ". Nothing was merged."
            )

        if heartbeat is not None:
            heartbeat()

        _sleep(max(0.0, min(poll_seconds, deadline - now)))


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
    runs = _read_check_runs(candidate_sha, repo_slug=repo_slug)

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


def find_pull_request(
    *, repo_slug: str, branch: str, candidate_sha: str, target_ref: str
) -> int:
    """The one open pull request this integration is about, or refuse.

    Derived, never supplied. The worker used to be handed a `pr_number`, and
    nothing in the controller ever produced one -- only the tests did, which
    is how a field that does not exist in production came to look load-bearing
    in review.

    Everything here comes from the controller or from configuration: the
    branch is `expected_branch` off the claimed activation, the commit is the
    ledger's `approved_candidate_sha`, and the repository and target are the
    host's own settings. No part of it is a caller's opinion about which pull
    request to merge.

    Exactly one match, and the count is the check. Zero means the review
    artifact does not exist and there is nothing a person looked at. More than
    one means the question "which PR is this" has no answer, and picking the
    newest -- or the lowest-numbered -- would be this program deciding
    something nobody asked it to decide.
    """
    base = target_ref.split("/")[-1] if target_ref.startswith("refs/") else target_ref

    result = _gh(
        "pr", "list", "--repo", repo_slug,
        "--head", branch, "--base", base, "--state", "open",
        "--json", "number,headRefOid,baseRefName,isDraft,state",
    )

    if result.returncode != 0:
        raise IntegrationRefused(
            f"could not list pull requests for {branch} in {repo_slug}: "
            f"{(result.stderr or '').strip()}"
        )

    try:
        candidates = json.loads(result.stdout or "[]")
    except ValueError as exc:
        raise IntegrationRefused(f"unreadable pull request listing: {exc}")

    if not candidates:
        raise IntegrationRefused(
            f"no open pull request from {branch} into {base} in {repo_slug}. "
            "The review artifact is what a person looked at; without it there "
            "is nothing to integrate."
        )

    if len(candidates) > 1:
        numbers = ", ".join(f"#{pr.get('number')}" for pr in candidates)
        raise IntegrationRefused(
            f"{len(candidates)} open pull requests from {branch} into {base}: "
            f"{numbers}. Which one this integration is about has no answer, "
            "and choosing would be this program deciding something nobody "
            "asked it to."
        )

    pr = candidates[0]

    # Checked here as well as in `check_pr`, because this is the step that
    # decides *which* pull request the rest of the run is about. A PR selected
    # by branch whose head is not the approved commit means the branch moved
    # after approval, and every later check would then be checking the wrong
    # object carefully.
    if pr.get("headRefOid") != candidate_sha:
        raise IntegrationRefused(
            f"PR #{pr.get('number')} from {branch} is at "
            f"{str(pr.get('headRefOid'))[:12]}, and the approved candidate is "
            f"{candidate_sha[:12]}. The branch moved after approval."
        )

    if pr.get("baseRefName") != base:
        raise IntegrationRefused(
            f"PR #{pr.get('number')} targets {pr.get('baseRefName')!r}, not "
            f"{base!r}"
        )

    return int(pr["number"])


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


def build_merge(plan: Plan, *, work_root: str) -> str:
    """Construct the exact two-parent merge locally. Nothing is pushed here.

    Built rather than requested, because a merge somebody else performs is a
    merge whose parents this program learns about afterwards. Constructing it
    means the first parent is the pinned target by construction -- not by a
    check that could have been overtaken.

    In an isolated worktree detached at the pinned target. Never the canonical
    checkout, which is permanently dirty with somebody else's work.

    A conflict is refused and never resolved. The tree that would land after a
    resolution is not the tree that was reviewed, and resolving one is a
    judgment no reviewer made.
    """
    import shutil
    import tempfile

    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="integrate-", dir=str(root)))

    # `git worktree add` refuses an existing directory.
    shutil.rmtree(workspace, ignore_errors=True)

    added = _git(
        plan.repo, "worktree", "add", "--detach",
        str(workspace), plan.target_sha_expected,
    )

    if added.returncode != 0:
        raise IntegrationRefused(
            f"could not prepare an isolated checkout at "
            f"{plan.target_sha_expected[:12]}: {(added.stderr or '').strip()}"
        )

    try:
        merged = _git(
            str(workspace), "merge", "--no-ff", "--no-edit",
            "-m", f"Merge {plan.task_id}: integrate "
                  f"{plan.candidate_sha[:12]} into {plan.target_ref}",
            plan.candidate_sha,
        )

        if merged.returncode != 0:
            _git(str(workspace), "merge", "--abort")
            raise IntegrationRefused(
                f"{plan.candidate_sha[:12]} does not merge cleanly into "
                f"{plan.target_sha_expected[:12]}: "
                f"{(merged.stdout or merged.stderr or '').strip()[:400]}. This "
                "will not resolve it -- the tree that would land afterwards is "
                "not the tree that was reviewed."
            )

        head = _git(str(workspace), "rev-parse", "HEAD").stdout.strip()

        if not SHA.match(head):
            raise IntegrationRefused(
                f"the merge produced {head!r}, which is not a commit"
            )

        return head
    finally:
        # The commit lives in the shared object store, so the worktree has
        # done its job either way.
        _git(plan.repo, "worktree", "remove", "--force", str(workspace))


def push_if_target_unmoved(plan: Plan, merge_sha: str) -> None:
    """Publish the merge, and let the remote refuse it if the target moved.

    **This is the check, and it is the write.** Everything before it is a read
    that could be overtaken between looking and acting; this cannot, because
    the condition and the effect are one operation performed by the remote.

    A plain non-force push is exactly the compare-and-swap wanted. `merge_sha`
    has the pinned target as its first parent, so it is a descendant of that
    commit and of nothing later. If the target is still where it was pinned,
    the update is a fast-forward and is accepted. If anything landed in the
    meantime, the target is no longer an ancestor, the push is not a
    fast-forward, and the remote rejects it **before anything changes**.

    No `--force`, and no `--force-with-lease` either. Force-with-lease would
    also express the condition, and it would express it as permission to
    overwrite -- so a mistake in computing the lease loses somebody's commits.
    A refused fast-forward cannot lose anything, and the worst outcome of
    getting it wrong is an integration that did not happen.
    """
    pushed = _git(
        plan.repo, "push", "--no-force", "origin",
        f"{merge_sha}:{plan.target_ref}",
    )

    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout or "").strip()
        raise IntegrationRefused(
            f"the remote refused the update of {plan.target_ref}: "
            f"{detail[:400]}. The target moved after it was pinned at "
            f"{plan.target_sha_expected[:12]}, so the merge was NOT applied "
            "and nothing landed. Re-run against the new target, with fresh "
            "evidence."
        )


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
    branch: str,
    repo_slug: str,
    work_root: str,
    required_suites: Sequence[str] = (),
    actor: str = "claudecode",
    ci_wait_seconds: float = 0.0,
    ci_poll_seconds: float = 30.0,
    heartbeat: Optional[Callable[[], Any]] = None,
) -> dict:
    """One integration attempt, in the only order that is safe.

    The order is the design. Everything derivable is derived before anything
    is done, the target is re-pinned immediately before the merge rather than
    trusted from the start, and every claim about the result is checked
    against the remote afterwards rather than taken from the API's response.

        1. approval      from the controller ledger, never from a caller
        2. pull request  derived from the controller-issued branch, never
                         supplied; exactly one open match or refuse
        2b. CI wait      when `ci_wait_seconds` is set, wait for this commit's
                         checks to finish (`await_ci`); a read, bounded, and
                         before the target is pinned so the pin is fresh
        3. target        pinned from the remote
        4. evidence      from the runner, by commit SHA
        5. PR            open, not draft, head is the approval, no conflict
        6. target again  unmoved since step 3 -- cheap, and not the guard
        6b. ancestry     the pinned target is already contained in the
                         candidate. Unnumbered because it came later and
                         renumbering would silently change what the
                         paragraph below refers to
        7. build         construct the merge locally from the pinned target
        8. push          non-force; the REMOTE refuses if the target moved
        9. landed        refetch; the target must contain the merge
       10. parents       the merge joined the pinned target to the approval
       11. tree          the merged tree equals the approved tree

    Step 8 is where the safety actually lives. Step 6 is a read and can be
    overtaken between looking and acting, so it exists to fail cheaply rather
    than to protect anything; steps 10 and 11 confirm afterwards what step 8
    made true. Only step 8 is a condition and an effect in one operation, and
    only the remote can perform it.

    Step 6b is the same kind of cheap read, and it is here because step 11
    is not cheap: a candidate whose target has advanced cannot produce the
    approved tree, and finding that out at step 11 means finding it out
    after the merge has landed. The condition is the same one either way;
    asking it early costs one ancestry query and asking it late costs a
    merge nobody can take back.

    Returns the ledger record. Raises `IntegrationRefused` at the first step
    that does not hold, having changed nothing -- every step before the merge
    is a read.
    """
    candidate = approved_candidate(task)

    # Derived from the controller-issued branch and the ledger-derived
    # approval, before any plan exists to carry it.
    pr_number = find_pull_request(
        repo_slug=repo_slug, branch=branch,
        candidate_sha=candidate, target_ref=target_ref,
    )

    if ci_wait_seconds > 0:
        await_ci(
            candidate, repo_slug=repo_slug, required=required_suites,
            wait_seconds=ci_wait_seconds, poll_seconds=ci_poll_seconds,
            heartbeat=heartbeat,
        )

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

    # The target has to be IN the candidate, not merely related to it.
    # Step 6 asks whether the target moved since step 3; this asks the
    # different question that step 11 will answer far too late -- whether
    # merging can produce the approved tree at all. It can only do so when
    # the candidate already contains the target, so anything else is a
    # candidate approved against a target that has since advanced.
    #
    # Placed here because every step above is a read and this one is too.
    # Left to step 11 the same divergence is caught, but after the merge
    # has landed on the remote -- which is how T-INFRA-03 ended up merged
    # and recorded as rejected in the same breath.
    is_ancestor = _git(plan.repo, "merge-base", "--is-ancestor",
                       plan.target_sha_expected, plan.candidate_sha)

    if is_ancestor.returncode != 0:
        raise IntegrationRefused(
            f"The pinned target {plan.target_sha_expected[:12]} is not an "
            f"ancestor of the candidate {plan.candidate_sha[:12]}."
        )

    merge_sha = build_merge(plan, work_root=work_root)
    push_if_target_unmoved(plan, merge_sha)

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
