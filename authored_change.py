"""Turn an API model's answer into a commit, safely.

Why this exists
---------------

`claude_worker` authors by running `claude -p` with Bash: the model does the
work and the worker only reports it. The API workers have no shell, so for them
authoring has to be split -- the model supplies the content, and the worker
applies it. This module is the applying half, and it is deliberately the dull
half: it parses a fixed format, refuses anything it does not understand, and
writes only where it is allowed to.

The trust boundary
------------------

**Every path here comes from a model and is untrusted.** A path is data that
arrived over the network from a system whose output nobody reviewed yet, and
the worker applying it holds write access to a repository. Absolute paths,
parent traversal, drive letters, symlinked directories and `.git` itself are
all refused rather than sanitised, because sanitising invites an argument about
whether the sanitiser is complete and refusing does not.

What it does not do
-------------------

It does not merge, push, or touch any branch but the one it creates. It does
not amend or force. A task branch that already exists is an error, not
something to reuse: reusing one would let a retried activation silently build
on a previous attempt's work and report the result as if it were one change.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple


class AuthoringError(Exception):
    """The model's answer could not be turned into a change."""


class UnsafePath(AuthoringError):
    """A path from the model would write outside the repository."""


# The output contract. Chosen for being unambiguous to parse rather than
# pleasant to write: a fenced block with an explicit terminator means a model
# that rambles before or after it still produces a usable answer, and one that
# forgets the terminator produces an error instead of a truncated file.
FILE_HEADER = re.compile(r"^FILE:\s*(?P<path>\S.*?)\s*$")
BEGIN = "<<<BEGIN>>>"
END = "<<<END>>>"


def render_author_prompt(task: dict) -> str:
    """The prompt an API author is given."""
    return "\n".join([
        "You are producing one change to a repository. You cannot run "
        "commands; you write file contents and the harness commits them.",
        "",
        f"TASK: {task.get('task_id')} -- {task.get('title', '')}",
        "",
        "OBJECTIVE AND ACCEPTANCE CRITERIA",
        (task.get("objective") or "").strip() or "(none recorded)",
        "",
        "-" * 60,
        "Answer with one or more file blocks and nothing else. Exactly this "
        "form, repeated per file:",
        "",
        "FILE: relative/path/from/the/repository/root.txt",
        BEGIN,
        "the complete new contents of that file",
        END,
        "",
        "Rules:",
        "- Paths are relative to the repository root. Absolute paths, '..' and "
        "anything under .git are refused and your answer will be discarded.",
        "- Give the COMPLETE contents of each file. Fragments, diffs and "
        "'unchanged' placeholders cannot be applied.",
        "- Write no explanation outside the blocks. Anything outside them is "
        "ignored.",
        "- If the objective cannot be met by writing files, answer with the "
        "single line: CANNOT_AUTHOR: <one sentence saying why>",
    ] + ([
        "",
        "You may only write to these paths. Anything else is refused and your "
        "whole answer is discarded:",
        *(f"  {entry}" for entry in task.get("allowed_paths") or []),
    ] if task.get("allowed_paths") else []))


def matches_allowed(relative: str, allowed: List[str]) -> bool:
    """Whether `relative` falls under one of the contract's allowed paths.

    An entry is either an exact file or a directory prefix. Matching is done on
    path components rather than string prefixes, so `notes` does not authorise
    `notes-secret/x`, which a `startswith` check would happily allow.
    """
    target = PurePosixPath(relative)

    for entry in allowed:
        pattern = PurePosixPath((entry or "").strip().replace("\\", "/").strip("/"))

        if not pattern.parts:
            continue

        if target == pattern:
            return True

        if target.parts[: len(pattern.parts)] == pattern.parts:
            return True

    return False


def safe_relative_path(
    repo: Path, raw: str, allowed: Optional[List[str]] = None
) -> Path:
    """Resolve `raw` inside `repo` and within `allowed`, or refuse.

    Two separate checks, and both are needed. Staying inside the repository
    stops a path from reaching the filesystem at large; `allowed` is the
    contract's own statement of what this task was authorised to touch. A task
    asked to add a note has no business editing the build script, and "inside
    the repository" does not distinguish those.

    `allowed` empty or None means the contract named no restriction, and only
    the containment check applies.

    Containment is checked by resolving and comparing, not by scanning the
    string for '..'. String checks miss symlinks, miss Windows drive-relative
    forms like `C:x`, and miss anything the filesystem normalises differently
    from the checker.
    """
    candidate = (raw or "").strip().replace("\\", "/")

    if not candidate:
        raise UnsafePath("empty path")

    pure = PurePosixPath(candidate)

    if pure.is_absolute() or candidate.startswith("/"):
        raise UnsafePath(f"absolute path refused: {raw!r}")

    if re.match(r"^[A-Za-z]:", candidate):
        raise UnsafePath(f"drive-qualified path refused: {raw!r}")

    if ".git" in pure.parts:
        raise UnsafePath(f"path inside .git refused: {raw!r}")

    root = repo.resolve()
    target = (root / candidate).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise UnsafePath(f"path escapes the repository: {raw!r}")

    if target == root:
        raise UnsafePath("path is the repository root")

    if allowed:
        relative = target.relative_to(root).as_posix()

        if not matches_allowed(relative, allowed):
            raise UnsafePath(
                f"{relative!r} is outside the paths this task may touch "
                f"({', '.join(sorted(allowed))})"
            )

    return target


def parse_files(text: str) -> List[Tuple[str, str]]:
    """Return [(path, contents)] from a model's answer, or raise.

    An answer containing no blocks at all raises rather than returning an empty
    list. "The model wrote nothing applicable" and "the model produced an empty
    change" would otherwise be indistinguishable, and only one of them is a
    task that succeeded.
    """
    if not isinstance(text, str) or not text.strip():
        raise AuthoringError("the model returned nothing")

    if text.strip().startswith("CANNOT_AUTHOR:"):
        raise AuthoringError(text.strip().splitlines()[0])

    files: List[Tuple[str, str]] = []
    lines = text.splitlines()
    index = 0

    while index < len(lines):
        header = FILE_HEADER.match(lines[index])

        if header is None:
            index += 1
            continue

        path = header.group("path")
        index += 1

        # The terminator is required. Reading to end-of-answer instead would
        # turn a truncated reply into a file that looks complete.
        if index >= len(lines) or lines[index].strip() != BEGIN:
            raise AuthoringError(f"{path!r}: expected {BEGIN} after the FILE line")

        index += 1
        body: List[str] = []

        while index < len(lines) and lines[index].strip() != END:
            body.append(lines[index])
            index += 1

        if index >= len(lines):
            raise AuthoringError(f"{path!r}: no {END}; the answer was truncated")

        index += 1
        files.append((path, "\n".join(body) + "\n"))

    if not files:
        raise AuthoringError("no FILE blocks in the model's answer")

    return files


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False, timeout=60,
    )

    if result.returncode != 0:
        raise AuthoringError(
            f"git {' '.join(args)} failed: {(result.stderr or '').strip()[:300]}"
        )

    return result.stdout or ""


def _abandon(root: Path, branch: str, starting_ref: str) -> None:
    """Undo a failed authoring attempt, leaving no branch and no dirt.

    Best effort by necessity -- it runs while an exception is propagating and
    must not replace it with one of its own -- but each step is attempted
    independently so a failure in one does not skip the rest. Whether it
    succeeded is checked by the caller with `worktree_is_clean`, because "the
    attempt failed" and "the attempt failed and left the repository unusable"
    need different responses.
    """
    for args in (
        ("reset", "--hard", "HEAD"),
        ("clean", "-fdq"),
        ("checkout", "-q", starting_ref),
        ("branch", "-D", branch),
    ):
        subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True,
            check=False, timeout=60,
        )


def worktree_is_clean(repo: str) -> bool:
    """Whether the repository has no uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False, timeout=60,
    )

    return result.returncode == 0 and not (result.stdout or "").strip()


def apply_and_commit(
    repo: str,
    *,
    branch: str,
    files: List[Tuple[str, str]],
    message: str,
    base: str = "HEAD",
    allowed_paths: Optional[List[str]] = None,
) -> dict:
    """Create `branch` off `base`, write `files`, commit, return branch and sha.

    The branch must not already exist. Reusing one would let a retried
    activation build on a previous attempt's work and report the combination as
    though it were this attempt's change -- which is exactly the ambiguity the
    immutable review range exists to remove.

    Nothing is pushed and no other branch is touched.
    """
    root = Path(repo).resolve()

    if not (root / ".git").exists():
        raise AuthoringError(f"{repo} is not a git repository")

    existing = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=str(root), capture_output=True, check=False,
    )

    if existing.returncode == 0:
        raise AuthoringError(
            f"branch {branch!r} already exists; refusing to build on a "
            "previous attempt"
        )

    # Resolved before the branch is created, so a bad base fails before
    # anything has changed.
    base_sha = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").strip()

    # Every path validated before any file is written. A partial application
    # would leave the working tree dirty with no commit and no branch.
    targets = [
        (safe_relative_path(root, path, allowed_paths), content)
        for path, content in files
    ]

    # The worktree must be clean before anything is written. Building on
    # somebody else's uncommitted edits would put them in this task's commit
    # and attribute them to the model.
    dirty = _git(root, "status", "--porcelain").strip()

    if dirty:
        raise AuthoringError(
            "the worktree is not clean before authoring; refusing to commit "
            f"changes that are not this task's ({len(dirty.splitlines())} entries)"
        )

    starting_ref = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() or base_sha
    _git(root, "checkout", "-q", "-b", branch, base_sha)

    # From here a failure has to leave the repository as it was found.
    # Anything else hands the next attempt a half-applied change to build
    # on, which is what the branch-already-exists check exists to prevent.

    try:
        for target, content in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")

        _git(root, "add", "--", *[str(t) for t, _ in targets])

        if not _git(root, "status", "--porcelain").strip():
            raise AuthoringError(
                "the model's files are identical to the base; there is "
                "nothing to commit"
            )

        _git(root, "commit", "-q", "-m", message)
        sha = _git(root, "rev-parse", "HEAD").strip()
    except BaseException:
        _abandon(root, branch, starting_ref)
        raise

    return {
        "branch": branch,
        "candidate_sha": sha,
        "base_sha": base_sha,
        "files": [str(Path(t).relative_to(root)).replace("\\", "/") for t, _ in targets],
    }
