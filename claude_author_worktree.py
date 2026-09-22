"""Where the Claude CLI author works, and what it may hand back (#37).

Why this exists
---------------

`claude -p` used to run with the worker's own `workspace/` directory as its
working directory -- a directory *inside* the canonical checkout. The session
holds Bash authority, and git walks up to the nearest repository, so every
commit it made landed in the checkout an operator works in. The first
chat-started task proved it: attempt 3 switched `C:\\git\\agent-swarm` onto a
branch of its own naming, and the worker reported whatever branch git showed
afterwards, with nothing comparing it to the activation's `expected_branch`.

So a controller activation now gets what the API author already had:

* a private worktree, detached at the task's `base_sha` and verified clean,
  under the project's `worktree_root` -- never the canonical checkout;
* the activation's `expected_branch`, created in that worktree before the
  model is called, and refused if it already exists;
* a snapshot of the canonical checkout's HEAD and branch, compared after the
  run -- a session that reached out of its worktree is caught, not trusted;
* a candidate that is reported only if it is a clean commit beyond the base,
  on exactly the expected branch;
* and, when the project publishes (#32), that candidate pushed and its pull
  request opened before it is reported, so CI runs while review happens.

Refusals before the run are `blocked`: the fix is an operator repairing the
environment, not the author trying again. A moved canonical checkout is also
`blocked`, whatever the run's exit code, because somebody has to look at it.
A run that left its work anywhere but a clean commit on the expected branch
is `failed` -- that is the author's mistake, and a retry is the right answer.
A good candidate that cannot be published is `blocked`: the remote or the
forge needs a person, not the author.

This module never calls a model and never writes to the canonical checkout's
working tree or HEAD. The branch ref it creates lives in the shared object
store, which is how a reviewer reading the canonical repository finds the
candidate, and publishing pushes from there by SHA.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import authored_change
import publication
import repo_registry
import retry_base
import worktrees

log = logging.getLogger("claude_author_worktree")

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class Refused(Exception):
    """The workspace could not be prepared; report `blocked`, call no model."""


@dataclass(frozen=True)
class Workspace:
    project: object
    name: str
    path: Path
    base_sha: str
    branch: str
    canonical: tuple
    publish: Optional[publication.Target] = None
    record: dict = field(default_factory=dict)
    # Where the work started versus what it is judged against (#68). They are
    # the same commit on a first attempt. On a retry `base_sha` is the
    # candidate the reviewer rejected -- the tree this session actually opens
    # in -- while `original_base` stays the task's own base, which is what the
    # review range is measured from and what the contract authorises against.
    original_base: str = ""
    retry_from: dict = field(default_factory=dict)


def _git(repo, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False, timeout=60,
    )


def snapshot(repo) -> tuple:
    """The canonical checkout's (HEAD commit, branch) -- what must not move.

    Not its working-tree status: a person may be mid-edit there, and their
    unsaved work changing during a run is not evidence against the author.
    """
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "symbolic-ref", "-q", "--short", "HEAD")

    if head.returncode != 0:
        raise Refused(
            f"cannot read the canonical checkout's HEAD at {repo}: "
            f"{(head.stderr or '').strip()[:200]}"
        )

    return (head.stdout.strip(), branch.stdout.strip() or "(detached)")


def open_for(activation: dict, project_name: str) -> Workspace:
    """A worktree on the activation's expected branch at its base, or Refused."""
    name = str(activation.get("activation_id") or "")
    record = activation.get("task_record") or {}
    base = str(record.get("base_sha") or "").strip().lower()
    branch = str(activation.get("expected_branch") or "").strip()

    if not project_name:
        raise Refused("AUTHOR_PROJECT is not configured on this host")

    try:
        project = repo_registry.get(project_name)
    except repo_registry.RegistryError as exc:
        raise Refused(f"repository registry: {exc}") from exc

    if not SHA_RE.match(base):
        raise Refused(f"the task's base_sha is {base!r}, not a full commit id")

    if not branch:
        raise Refused("the activation names no expected_branch to author on")

    try:
        worktrees.check_name(name)
    except worktrees.WorktreeError as exc:
        raise Refused(str(exc)) from exc

    # Decided before the model is called: a task that must be published and
    # has nowhere to go is refused now, not after the call has been spent.
    try:
        target = publication.target_for(project, record.get("proof_mode"))
    except publication.PublicationError as exc:
        raise Refused(str(exc)) from exc

    canonical = snapshot(project.path)

    # A retry opens in the rejected candidate rather than the task's base, so
    # the reviewer's rationale describes the tree the session is standing in
    # (#68). Resolved against the canonical checkout, which is where the
    # candidate's objects live; unusable candidates fall back to the base and
    # say why.
    retry_from = retry_base.resolve(
        str(project.path), {**record, "base_sha": base}, log
    )
    open_at = retry_from["sha"]

    try:
        path = worktrees.create(project, open_at, name)
    except worktrees.WorktreeError as exc:
        raise Refused(f"could not prepare an isolated worktree: {exc}") from exc

    # `-c`, never `-C`: git refuses a name that is not a valid branch and one
    # that already exists, which is the check. An existing branch is a
    # previous attempt's, and building on it would put that attempt's commits
    # into this one's candidate -- refused, as `apply_and_commit` refuses it.
    switched = _git(path, "switch", "-q", "-c", branch)

    if switched.returncode != 0:
        _remove(project, name)
        raise Refused(
            f"could not create branch {branch!r} in the worktree: "
            f"{(switched.stderr or '').strip()[:200]}"
        )

    log.info("authoring in %s on %s at %s", path, branch, open_at[:12])
    return Workspace(project, name, Path(path), open_at, branch, canonical,
                     publish=target, record=dict(record),
                     original_base=base, retry_from=retry_from)


def briefing(ws: Workspace) -> str:
    """What the session is told about where it is. Checked afterwards anyway."""
    where = (
        "Workspace: the current directory is a dedicated git worktree of "
        f"project {ws.project.name}, already on branch `{ws.branch}` at base "
        f"commit {ws.base_sha}. Make and commit your change here, on this "
        "branch. Do not switch branches, create other branches, push, or "
        "read or write any other checkout -- the candidate is taken from this "
        "branch and nowhere else, and anything left uncommitted is lost."
    )

    # A session that does not know it is standing in a rejected attempt will
    # read the tree as the original and re-make the edit that was sent back
    # (#68). It can see the change with git, but only if it is told there is
    # one to look for.
    if (ws.retry_from or {}).get("source") == "rejected_candidate":
        where += (
            f"\n\nThis is a retry. {ws.base_sha[:12]} is the candidate a "
            f"reviewer rejected, not this task's original base, which is "
            f"{ws.original_base[:12]}. The rejected attempt's change is "
            f"already applied in this tree -- `git diff {ws.original_base[:12]} "
            "HEAD` shows it, and the review feedback you were given describes "
            "exactly that diff. You are judged on the whole change from "
            f"{ws.original_base[:12]}, so you may revert or rewrite any part "
            "of that attempt rather than building on it."
        )

    return where


def _outside_contract(ws: Workspace, base: str, head: str) -> list:
    """Paths in `base..head` the task's contract does not authorise.

    An unreadable contract returns nothing rather than failing the run. The
    contract is checked, and refused if it cannot be read, well before a model
    is called; re-deriving that verdict here -- after the work is done, from a
    record this function was handed -- would turn one refusal into two with
    different wording, and the later one would arrive as a lost attempt.
    """
    try:
        scope = authored_change.require_contract(ws.record)
    except authored_change.ContractDefect:
        return []

    if scope.unrestricted:
        return []

    listing = _git(ws.path, "diff", "--name-only", f"{base}..{head}")

    if listing.returncode != 0:
        return []

    return sorted({
        line.strip().replace("\\", "/")
        for line in (listing.stdout or "").splitlines()
        if line.strip()
        and not authored_change.matches_allowed(
            line.strip().replace("\\", "/"), list(scope.paths)
        )
    })


def settle(ws: Workspace, exit_code: int) -> tuple:
    """(outcome, payload fields) for the run that just ended in `ws`."""
    try:
        now = snapshot(ws.project.path)
    except Refused as exc:
        return "blocked", {"reason": str(exc)}

    if now != ws.canonical:
        log.error("canonical checkout moved during the run: %s -> %s",
                  ws.canonical, now)
        return "blocked", {"reason": (
            f"the canonical checkout {ws.project.path} moved during the run: "
            f"HEAD {ws.canonical[0][:12]} on {ws.canonical[1]} is now "
            f"{now[0][:12]} on {now[1]}. The author reached outside its "
            "worktree; an operator must restore the checkout."
        )}

    if exit_code != 0:
        return "failed", {"reason": f"the author exited {exit_code}"}

    branch = _git(ws.path, "symbolic-ref", "-q", "--short", "HEAD")
    on = branch.stdout.strip() if branch.returncode == 0 else "(detached)"

    if on != ws.branch:
        return "failed", {"reason": (
            f"the worktree is on {on!r}, not the expected branch {ws.branch!r}"
        )}

    head = _git(ws.path, "rev-parse", "HEAD").stdout.strip()

    if head == ws.base_sha:
        return "failed", {"reason": (
            f"no commit on {ws.branch!r} beyond the base {ws.base_sha[:12]}"
        )}

    if _git(ws.path, "merge-base", "--is-ancestor", ws.base_sha, head).returncode:
        return "failed", {"reason": (
            f"{head[:12]} on {ws.branch!r} does not descend from the base "
            f"{ws.base_sha[:12]}"
        )}

    # And from the task's own base, which on a retry is a different commit
    # (#68). The check above proves the session built on the tree it was
    # opened in; this proves that tree is still a continuation of the task the
    # reviewer will measure it against. They are the same question only on a
    # first attempt.
    original = ws.original_base or ws.base_sha

    if _git(ws.path, "merge-base", "--is-ancestor", original, head).returncode:
        return "failed", {"reason": (
            f"{head[:12]} on {ws.branch!r} does not descend from the task's "
            f"base {original[:12]}; the review range would not be this "
            "task's change"
        )}

    # Every path the reviewer will be shown, against the contract. On a first
    # attempt this is the session's own commits. On a retry it also covers the
    # rejected attempt's edits, which arrive through the base rather than
    # through anything this run wrote, and so had never been checked here.
    outside = _outside_contract(ws, original, head)

    if outside:
        return "failed", {"reason": (
            f"the change from {original[:12]} touches {len(outside)} path(s) "
            "the contract does not authorise: " + ", ".join(outside[:10])
        )}

    dirt = _git(ws.path, "status", "--porcelain").stdout.strip()

    if dirt:
        return "failed", {"reason": (
            f"the worktree has {len(dirt.splitlines())} uncommitted "
            "entries; the commit is not the whole of the change"
        )}

    found = {"candidate_sha": head, "branch": ws.branch}

    if ws.publish is None:
        return "candidate", found

    # Before the report, so `candidate_submitted` names the pull request, and
    # a failure is reported as what it is. The authored commit is named under
    # another key: only a submitted candidate carries `candidate_sha`.
    try:
        published = publication.publish_for(
            ws.project, ws.publish, branch=ws.branch, candidate_sha=head,
            task_record=ws.record, activation_id=ws.name,
        )
    except publication.PublicationError as exc:
        log.error("could not publish %s: %s", ws.branch, exc)
        return "blocked", {
            "reason": f"the candidate was authored but could not be "
                      f"published: {exc}",
            "authored_sha": head, "branch": ws.branch,
        }

    log.info("published %s as PR #%s", ws.branch, published.get("pr_number"))
    return "candidate", {**published, **found}


def _remove(project, name: str, *, force: bool = True) -> None:
    try:
        worktrees.remove(project, name, force=force)
    except worktrees.WorktreeError as exc:
        log.warning("worktree for %s kept for inspection: %s", name, exc)


def close(ws: Workspace) -> None:
    """Take the worktree away. The branch, and so the candidate, stays.

    Not forced, as the API author does it: a worktree with uncommitted work
    in it is what a failed run left behind, and that is evidence until
    somebody has looked at it.
    """
    _remove(ws.project, ws.name, force=False)
