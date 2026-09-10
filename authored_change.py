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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple


class AuthoringError(Exception):
    """The model's answer could not be turned into a change."""


class UnsafePath(AuthoringError):
    """A path from the model would write outside the repository."""


class ContractError(AuthoringError):
    """The contract does not say what this task may touch, or says it unreadably."""


# The output contract. Chosen for being unambiguous to parse rather than
# pleasant to write: a fenced block with an explicit terminator means a model
# that rambles before or after it still produces a usable answer, and one that
# forgets the terminator produces an error instead of a truncated file.
FILE_HEADER = re.compile(r"^FILE:\s*(?P<path>\S.*?)\s*$")
BEGIN = "<<<BEGIN>>>"
END = "<<<END>>>"


def _rejection_section(task: dict) -> List[str]:
    """What the last review sent this task back for, if anything.

    Included verbatim and attributed, because a retry that is not told what
    was wrong is not an attempt at the correction -- it is the same generation
    with the same inputs, and it will produce the same candidate. The
    reviewer's words are labelled as the reviewer's: they are a judgment to
    address, not part of the objective, and an author that treats them as new
    requirements will drift away from what was actually asked for.
    """
    rejection = task.get("last_rejection") or {}
    rationale = str(rejection.get("rationale") or "").strip()

    if not rationale:
        return []

    return [
        "",
        "-" * 60,
        "A PREVIOUS ATTEMPT AT THIS TASK WAS REJECTED IN REVIEW.",
        "",
        "The reviewer said:",
        rationale,
        "",
        "Address that. The objective above is unchanged and is still what you "
        "are being judged against; the rejection tells you where the last "
        "attempt fell short of it.",
    ]


DEFAULT_FILE_VIEW = 12_000
DEFAULT_VIEW_BUDGET = 48_000


def existing_in_scope(
    repo: str,
    sha: str,
    scope: Scope,
    *,
    per_file: int = DEFAULT_FILE_VIEW,
    total: int = DEFAULT_VIEW_BUDGET,
) -> List[dict]:
    """The current contents of the files this task may change, at `sha`.

    An author with no shell cannot read the repository. Asked to edit an
    existing file, it has to invent the parts it was not shown -- and the
    output format demands the *complete* contents of every file it writes, so
    inventing is not a corner it can cut, it is the only thing available to it.

    A live run made the consequence unmistakable: asked to reword one sentence
    in README.md while preserving everything else, the author produced a
    plausible README for a different project, complete with a hackathon in
    2020 and an MIT licence, and dropped every line it had been told to keep.
    The reviewer caught it, which is the system working; the author was set up
    to fail, which is this function.

    Only files inside the scope, because those are the only ones it may write.
    An unrestricted scope returns nothing rather than the whole repository: a
    task authorised everywhere is not a task whose relevant files can be
    guessed at, and filling a context window with an entire tree would crowd
    out the objective.
    """
    if scope.unrestricted:
        return []

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", sha],
        cwd=str(repo), capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )

    if listing.returncode != 0:
        return []

    files = []
    spent = 0

    for path in sorted(
        line.strip() for line in (listing.stdout or "").splitlines() if line.strip()
    ):
        if not matches_allowed(path, list(scope.paths)):
            continue

        shown = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=str(repo), capture_output=True, encoding="utf-8",
            errors="replace", check=False,
        )

        if shown.returncode != 0:
            continue

        text = shown.stdout or ""
        raw = text.encode("utf-8")
        room = min(per_file, max(0, total - spent))
        truncated = len(raw) > room

        if truncated:
            text = raw[:room].decode("utf-8", "ignore")

        spent += len(text.encode("utf-8"))
        files.append({"path": path, "text": text, "truncated": truncated})

    return files


def _existing_section(existing: List[dict]) -> List[str]:
    """The in-scope files as they stand, or a statement that there are none."""
    if not existing:
        return []

    parts = [
        "",
        "-" * 60,
        "THE FILES YOU MAY CHANGE, AS THEY ARE NOW",
        "",
        "This is their current content at the commit you are working from. To "
        "modify one, return its COMPLETE new content -- the parts you are not "
        "changing included, byte for byte as they appear here.",
    ]

    for entry in existing:
        parts += ["", f"--- {entry['path']}", entry["text"].rstrip("\n")]

        if entry["truncated"]:
            parts += [
                "",
                f"[{entry['path']} IS TRUNCATED. You have not been shown all "
                "of it, so you cannot reproduce it. Do not rewrite this file: "
                "answer CANNOT_AUTHOR and say the file is too large to be "
                "shown in full.]",
            ]

    return parts


def render_author_prompt(task: dict, existing: Optional[List[dict]] = None) -> str:
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
    ] if task.get("allowed_paths") else [])
        + _existing_section(existing or [])
        + _rejection_section(task))



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


# The one value that authorises writing anywhere in the repository. A word,
# not a glob: `**` or an empty list are things a contract arrives at by
# accident -- a truncated file, a key someone forgot to fill in, a model
# emitting plausible YAML -- and this must only ever be arrived at on purpose.
UNRESTRICTED = "UNRESTRICTED"


@dataclass(frozen=True)
class Scope:
    """What a task may write to. Either a list of paths, or the whole tree."""

    unrestricted: bool
    paths: tuple = ()

    @classmethod
    def restricted_to(cls, paths) -> "Scope":
        entries = tuple(
            str(p).strip() for p in paths if str(p).strip()
        )

        if not entries:
            raise ContractError("a restricted scope with no paths authorises nothing")

        return cls(False, entries)

    @classmethod
    def everywhere(cls) -> "Scope":
        """The whole repository. Only ever from the explicit marker."""
        return cls(True, ())


def parse_scope(contract: str, declared=None) -> Scope:
    """The scope a task is authorised to write in, or refuse to author it.

    **Silence is not permission.** This used to return an empty list for a
    contract it could not read, and an empty list meant unrestricted -- so a
    truncated contract, a misspelt key, or a format this parser had never seen
    all ended with a model holding write access to the entire repository. The
    quietest possible failure produced the widest possible authority, which is
    exactly backwards: the less a contract is understood, the less it should be
    allowed to do.

    So an unreadable, absent or empty `allowed_paths` raises, and the only way
    to write repository-wide is the literal `allowed_paths: UNRESTRICTED`.

    Still a hand-parse rather than a YAML dependency: hub.py installs fastapi,
    uvicorn and pydantic at every container start and nothing else. The change
    here is not the parser, it is what happens when the parser fails.

    When planning mode lands, a contract will be written by a model rather than
    by the operator, and the marker must not be reachable that way -- a planner
    granting its own author the whole repository is the same hole with a
    different author. That belongs in the controller's plan validation, which
    is where a planner's output stops being prose.
    """
    if declared is not None and not isinstance(declared, str):
        entries = [str(p).strip() for p in declared if str(p).strip()]

        if entries == [UNRESTRICTED]:
            return Scope.everywhere()

        if entries:
            return Scope.restricted_to(entries)

    if isinstance(declared, str) and declared.strip() == UNRESTRICTED:
        return Scope.everywhere()

    text = contract or ""
    paths: List[str] = []
    seen_key = False
    collecting = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("allowed_paths:"):
            seen_key = True
            collecting = True
            inline = stripped.partition(":")[2].strip()

            if inline == UNRESTRICTED:
                return Scope.everywhere()

            if inline.startswith("[") and inline.endswith("]"):
                entries = [
                    part.strip().strip("'\"")
                    for part in inline[1:-1].split(",") if part.strip()
                ]

                if entries == [UNRESTRICTED]:
                    return Scope.everywhere()

                if not entries:
                    raise ContractError(
                        "the contract's allowed_paths is an empty list, which "
                        "authorises nothing; say UNRESTRICTED if that is what "
                        "was meant"
                    )

                return Scope.restricted_to(entries)

            if inline:
                # A scalar that is neither the marker nor a list. Refusing
                # beats guessing: the guess would be a permission.
                raise ContractError(
                    f"the contract's allowed_paths is {inline!r}, which this "
                    "parser does not understand"
                )

            continue

        if collecting:
            if stripped.startswith("- "):
                paths.append(stripped[2:].strip().strip("'\""))
            elif stripped and not stripped.startswith("#"):
                break

    if not seen_key:
        raise ContractError(
            "the contract does not declare allowed_paths; refusing to author "
            "a change with no statement of what it may touch"
        )

    if not paths:
        raise ContractError(
            "the contract declares allowed_paths but lists none; refusing to "
            "read that as permission to write anywhere"
        )

    return Scope.restricted_to(paths)


def safe_relative_path(repo: Path, raw: str, scope: "Scope") -> Path:
    """Resolve `raw` inside `repo` and within `scope`, or refuse.

    Two separate checks, and both are needed. Staying inside the repository
    stops a path from reaching the filesystem at large; the scope is the
    contract's own statement of what this task was authorised to touch. A task
    asked to add a note has no business editing the build script, and "inside
    the repository" does not distinguish those.

    `scope` is required and has no default. The previous signature defaulted to
    None and read it as "unrestricted", so every call that forgot to pass a
    scope silently authorised the whole repository -- a default that grants
    everything is not a default, it is a hole with a docstring.

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

    if not isinstance(scope, Scope):
        raise ContractError(
            "no scope was supplied; authoring requires an explicit statement "
            "of what this task may touch"
        )

    if not scope.unrestricted:
        relative = target.relative_to(root).as_posix()

        if not matches_allowed(relative, scope.paths):
            raise UnsafePath(
                f"{relative!r} is outside the paths this task may touch "
                f"({', '.join(sorted(scope.paths))})"
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
    scope: Scope,
) -> dict:
    """Create `branch` off `base`, write `files`, commit, return branch and sha.

    `scope` is keyword-only and has no default, so a caller cannot reach this
    without having decided what the task may touch. The decision is not one
    anything downstream can make: by the time a path is being resolved, the
    only honest answer to "was this authorised?" is the one the contract gave.

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
        (safe_relative_path(root, path, scope), content)
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
