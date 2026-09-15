"""Publishing a candidate, so a reviewer and CI have something to look at.

The author commits into a private worktree and the worktree is removed once
the commit exists. That was right while there was nowhere for a candidate to
go, and it is the gap now: the commit is real and reachable in the object
store, and nothing outside this machine can see it. So every run needed a
person to push the branch and open the pull request between authoring and
review.

Neither step is a judgment. Both are mechanical consequences of the candidate
existing, which is what makes them automatable and why leaving them manual
meant the cycle was not unattended.

What this refuses to do
-----------------------

**It never force-pushes.** A branch that already exists at a different commit
is somebody else's candidate, or this task's previous one -- which is evidence
for the review that rejected it and must not be moved. The push is by explicit
SHA to an explicit ref and is rejected by the remote if it would not
fast-forward.

**It never reuses a pull request whose head is not this candidate.** An open
PR on the same branch at an older commit is the artifact of an earlier review.
Reusing it would attach this candidate's approval to that one's discussion.

**It never picks between several.** Two open pull requests from one branch is
a question with no answer, and choosing would be this program deciding
something nobody asked it to.

Idempotent on purpose
---------------------

A worker that pushed and then crashed before reporting will run this again on
redelivery. Pushing the same SHA to the same ref a second time succeeds and
changes nothing; finding the pull request that already exists returns it
rather than creating a second one. The natural retry has to be safe, because
the alternative is a step that can only be taken once by a process that cannot
guarantee it runs once.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

import swarm_control


class PublicationError(Exception):
    """The candidate could not be published, and why."""


@dataclass(frozen=True)
class Target:
    """Where one project's candidates go: a forge repository and its branch."""

    repo_slug: str
    target_ref: str


def target_for(
    project, proof_mode: str, *, fallback_slug: str = "",
    fallback_target_ref: str = "",
) -> Optional[Target]:
    """Where this task's candidate is published, None to keep it local, or refuse.

    The project's `publish` block in repos.json decides first (#32): where a
    repository's candidates go is a property of the repository, so a project
    that publishes publishes every candidate, `branch_only` included. That is
    what lets a chat-started task reach review with its pull request already
    open and CI already running.

    A host's `PUBLISH_REPO_SLUG` is the fallback, for projects with no block.
    With neither, a `branch_only` task stays on this machine as it always
    has, and any other task is refused -- before the model is called, which
    is when callers ask -- because a candidate that must be published and
    cannot be is a model call spent on something nobody can review.
    """
    slug = getattr(project, "publish_repo_slug", "") or ""

    if slug:
        return Target(slug, project.publish_target_ref)

    if fallback_slug:
        return Target(fallback_slug, fallback_target_ref)

    if str(proof_mode or "").strip() == "branch_only":
        return None

    raise PublicationError(
        f"project {getattr(project, 'name', project)!r} has no publish block "
        "in repos.json and PUBLISH_REPO_SLUG is not configured on this host, "
        "so a candidate could be authored but not published -- no reviewer "
        "could reach it and no CI could run against it. Refusing before the "
        "model call. Configure one, or mark the task branch_only if the "
        "candidate is deliberately not meant to leave this machine."
    )


# Userinfo in a URL -- `https://user:token@host/` -- as git prints it when a
# remote was configured with credentials in it.
_URL_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


def scrub(text: str, limit: int = 400) -> str:
    """Forge output made safe to log or report: no credentials, bounded.

    git and gh print remote URLs in their errors, and a remote configured
    with a token in its URL prints the token with it. Applied to every
    message this module raises, so a caller never has to remember to.
    """
    cleaned = _URL_USERINFO.sub(r"\1[REDACTED]@", str(text or ""))
    return swarm_control.redact(cleaned).strip()[:limit]


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


def push_candidate(repo: str, *, branch: str, candidate_sha: str) -> dict:
    """Publish exactly this commit as exactly this branch, or refuse.

    By SHA rather than by branch name. `git push origin <branch>` publishes
    whatever the local branch points at now, which is the same thing right up
    until it is not; naming the commit means what is published is what was
    authored and reported.
    """
    remote_ref = f"refs/heads/{branch}"
    existing = _git(repo, "ls-remote", "origin", remote_ref)

    if existing.returncode != 0:
        raise PublicationError(
            f"could not read {remote_ref} from the remote: "
            f"{(existing.stderr or '').strip()}"
        )

    lines = (existing.stdout or "").strip().splitlines()
    already = lines[0].split()[0] if lines else ""

    if already == candidate_sha:
        # The retry case. Nothing to do, and saying so is not the same as
        # having pushed: the caller gets to know it was already there.
        return {"branch": branch, "candidate_sha": candidate_sha,
                "pushed": False, "already_published": True}

    if already:
        raise PublicationError(
            f"{remote_ref} already exists at {already[:12]} and this candidate "
            f"is {candidate_sha[:12]}. Refusing to move it: an earlier "
            "candidate on this branch is the evidence for the review that "
            "rejected it."
        )

    pushed = _git(repo, "push", "--no-force", "origin",
                  f"{candidate_sha}:{remote_ref}")

    if pushed.returncode != 0:
        raise PublicationError(
            f"could not publish {candidate_sha[:12]} as {remote_ref}: "
            f"{(pushed.stderr or pushed.stdout or '').strip()[:400]}"
        )

    return {"branch": branch, "candidate_sha": candidate_sha,
            "pushed": True, "already_published": False}


def ensure_pull_request(
    *,
    repo_slug: str,
    branch: str,
    base: str,
    candidate_sha: str,
    title: str,
    body: str,
) -> dict:
    """The open pull request for this candidate: found, or created. Or refuse.

    Found first, created second. A worker retrying after a lost response must
    not open a second pull request for the same candidate -- two review
    artifacts for one commit means two places a reviewer might comment and one
    of them is wrong.
    """
    listed = _gh(
        "pr", "list", "--repo", repo_slug, "--head", branch, "--base", base,
        "--state", "open", "--json", "number,headRefOid,url,isDraft",
    )

    if listed.returncode != 0:
        raise PublicationError(
            f"could not list pull requests for {branch}: "
            f"{(listed.stderr or '').strip()}"
        )

    try:
        found = json.loads(listed.stdout or "[]")
    except ValueError as exc:
        raise PublicationError(f"unreadable pull request listing: {exc}")

    if len(found) > 1:
        numbers = ", ".join(f"#{pr.get('number')}" for pr in found)
        raise PublicationError(
            f"{len(found)} open pull requests from {branch} into {base}: "
            f"{numbers}. Which one this candidate belongs to has no answer."
        )

    if found:
        pr = found[0]

        if pr.get("headRefOid") != candidate_sha:
            raise PublicationError(
                f"PR #{pr.get('number')} on {branch} is at "
                f"{str(pr.get('headRefOid'))[:12]}, and this candidate is "
                f"{candidate_sha[:12]}. It is an earlier review's artifact; "
                "attaching this candidate to it would attach this approval to "
                "that discussion."
            )

        return {"pr_number": int(pr["number"]), "pr_url": pr.get("url", ""),
                "created": False}

    created = _gh(
        "pr", "create", "--repo", repo_slug, "--base", base, "--head", branch,
        "--title", title, "--body", body,
    )

    if created.returncode != 0:
        raise PublicationError(
            f"could not open a pull request for {branch}: "
            f"{(created.stderr or '').strip()[:400]}"
        )

    url = (created.stdout or "").strip().splitlines()[-1] if created.stdout else ""
    number = url.rstrip("/").rsplit("/", 1)[-1] if url else ""

    try:
        number = int(number)
    except ValueError:
        raise PublicationError(
            f"opened a pull request for {branch} but could not read its "
            f"number from {url!r}"
        )

    return {"pr_number": number, "pr_url": url, "created": True}


def publish_for(
    project,
    target: Target,
    *,
    branch: str,
    candidate_sha: str,
    task_record: dict,
    activation_id: str = "",
) -> dict:
    """Publish one verified candidate of `project` to `target`. Or refuse.

    The one publishing call both authors make, after their own verification
    and before they report, so the `candidate_submitted` payload records the
    pull request. Pushed from the canonical checkout's object store by SHA,
    which reads no working tree and moves no HEAD. Every refusal's message is
    scrubbed of credentials.
    """
    record = task_record or {}

    try:
        return publish_candidate(
            str(project.path),
            branch=branch,
            candidate_sha=candidate_sha,
            repo_slug=target.repo_slug,
            target_ref=target.target_ref,
            task_id=str(record.get("task_id") or ""),
            title=str(record.get("title") or ""),
            objective=str(record.get("objective") or ""),
            activation_id=str(activation_id or ""),
        )
    except PublicationError as exc:
        raise PublicationError(scrub(str(exc))) from None


def publish_candidate(
    repo: str,
    *,
    branch: str,
    candidate_sha: str,
    repo_slug: str,
    target_ref: str,
    task_id: str,
    title: str = "",
    objective: str = "",
    activation_id: str = "",
) -> dict:
    """Push the candidate and make sure its pull request exists.

    Returns what a reviewer and an integrator both need: the branch, the
    commit, and the pull request. Recorded in the `candidate_submitted`
    payload, so the ledger says where the candidate went rather than only that
    one was produced.
    """
    base = target_ref.split("/")[-1] if target_ref.startswith("refs/") else target_ref

    pushed = push_candidate(repo, branch=branch, candidate_sha=candidate_sha)

    body = "\n".join([
        f"Authored by the controller for task `{task_id}`"
        + (f" under activation `{activation_id}`." if activation_id else "."),
        "",
        objective.strip() or "(no objective recorded)",
        "",
        "---",
        "",
        f"Candidate `{candidate_sha}`. This pull request is the review "
        f"artifact for `{task_id}` and will be integrated by the controller's "
        "integrator, not by hand.",
    ])

    pr = ensure_pull_request(
        repo_slug=repo_slug, branch=branch, base=base,
        candidate_sha=candidate_sha,
        title=f"{task_id}: {title}".strip().rstrip(":") or task_id,
        body=body,
    )

    return {**pushed, **pr, "repo_slug": repo_slug, "base": base}
