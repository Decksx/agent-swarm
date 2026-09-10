"""Work happens in a clean tree at the baseline, never in the canonical checkout.

Why not just author in the checkout
-----------------------------------

The canonical checkout is where a person works. `C:\\git\\ComicAutomation` is
sitting on a feature branch with fourteen uncommitted files as this is written,
and that is its normal condition, not a problem to be tidied up before a run.

Authoring there would mean one of two things, both bad. Either the worker
refuses whenever somebody has unsaved work -- which is most of the time, and
turns the safety check into an obstacle to be switched off -- or it commits on
top of whatever is there, putting a person's half-finished edits into a
model's commit and handing them to a reviewer as the model's work.

It would also have to move HEAD. A worker checking out a task branch in the
checkout somebody is using is not a race condition so much as an ambush.

So each activation gets its own worktree, created detached at the baseline
commit, and the canonical checkout is never written to. Its `.git` directory
gains a registration -- that is how worktrees work -- but its working tree, its
index and its HEAD are untouched, which is the thing that matters and which the
tests assert directly.

Clean by construction, checked anyway
-------------------------------------

A fresh worktree at a commit is clean and at that commit by definition, so
verifying it looks redundant. It is checked because the alternative to
checking is assuming, and an author that starts in a tree which is not what it
should be produces a candidate whose diff contains something nobody can
account for. The check costs one `git status`.

Names
-----

The directory is named for the activation, and the name is validated rather
than sanitised: it reaches here from the controller, and a task id is a short
token or it is not a task id. An existing directory is an error -- reusing one
would let a retried activation build on the previous attempt's leftovers,
which is the same ambiguity `apply_and_commit` refuses a branch for.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# A task or activation id, and nothing that could be a path. Validated, not
# sanitised: sanitising invites an argument about whether the sanitiser is
# complete, and there is no legitimate task id this rejects.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class WorktreeError(Exception):
    """A worktree could not be created, or is not what it should be."""


def _git(repo, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def check_name(name: str) -> str:
    if not isinstance(name, str) or not SAFE_NAME.match(name):
        raise WorktreeError(
            f"{name!r} is not usable as a worktree name; expected a short "
            "identifier of letters, digits, dot, dash or underscore"
        )

    return name


def path_for(project, name: str) -> Path:
    """Where this activation's worktree goes."""
    return Path(project.worktree_root) / check_name(name)


def verify(path: Path, sha: str) -> None:
    """The tree is at `sha` and has nothing else in it, or raise."""
    path = Path(path)

    if not (path / ".git").exists():
        raise WorktreeError(f"{path} is not a git worktree")

    head = _git(path, "rev-parse", "HEAD")

    if head.returncode != 0:
        raise WorktreeError(f"{path}: cannot read HEAD: {head.stderr.strip()[:200]}")

    at = (head.stdout or "").strip()

    if at != sha:
        raise WorktreeError(
            f"{path} is at {at[:12]}, not the baseline {sha[:12]}"
        )

    status = _git(path, "status", "--porcelain")
    dirt = (status.stdout or "").strip()

    if dirt:
        raise WorktreeError(
            f"{path} is not clean ({len(dirt.splitlines())} entries) before "
            "any work has been done in it"
        )


def create(project, sha: str, name: str) -> Path:
    """A clean worktree for `name`, detached at `sha`.

    Detached deliberately. The author creates its own task branch as its first
    act; a worktree that arrived already on a branch would mean the branch
    existed before the work did, and a second activation for the same task
    would find it and could not tell whose it was.
    """
    target = path_for(project, name)

    if target.exists():
        raise WorktreeError(
            f"{target} already exists; refusing to reuse it. A previous "
            "attempt's files would end up in this attempt's commit."
        )

    target.parent.mkdir(parents=True, exist_ok=True)

    result = _git(
        project.path, "worktree", "add", "--detach", str(target), sha
    )

    if result.returncode != 0:
        raise WorktreeError(
            f"could not create a worktree at {target}: "
            f"{(result.stderr or '').strip()[:300]}"
        )

    try:
        verify(target, sha)
    except WorktreeError:
        # A worktree that is not what it should be is worse than none: the
        # next attempt would find the directory and refuse.
        remove(project, name, force=True)
        raise

    return target


def remove(project, name: str, *, force: bool = False) -> bool:
    """Take the worktree away and deregister it. True if there was one.

    `git worktree remove` refuses a dirty tree without --force, which is the
    right default: a worktree with uncommitted work in it may be an author
    that failed halfway, and that is evidence until somebody has looked at it.
    """
    target = path_for(project, name)

    if not target.exists():
        return False

    args = ["worktree", "remove", str(target)]

    if force:
        args.insert(2, "--force")

    result = _git(project.path, *args)

    if result.returncode != 0:
        if not force:
            raise WorktreeError(
                f"could not remove {target}: "
                f"{(result.stderr or '').strip()[:300]}"
            )

        # Forced cleanup after a failed create: the registration may not
        # exist, and leaving the directory behind would block every retry.
        shutil.rmtree(target, ignore_errors=True)
        _git(project.path, "worktree", "prune")

    return True


def existing(project) -> list:
    """Worktrees this module has created, by name.

    Only the ones under `worktree_root`. The checkout carries registrations
    from elsewhere -- other machines, cloud sessions, locked and long gone --
    and those are somebody else's to prune.
    """
    root = Path(project.worktree_root)

    if not root.is_dir():
        return []

    return sorted(child.name for child in root.iterdir() if child.is_dir())
