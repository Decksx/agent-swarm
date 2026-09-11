"""Describe a repository to a planner, including what the planner cannot see.

Why this exists
---------------

A model asked to plan work against a repository it has not read will plan
anyway. It will name files that do not exist, assume a layout that was
refactored months ago, and produce a confident, well-formatted plan whose base
assumptions are invented. The failure is quiet: a plan is prose, so nothing
about it fails until an author tries to execute it.

So the planner is handed evidence taken from the repository rather than from
anybody's description of it, and -- just as importantly -- an explicit account
of what was left out. A planner that does not know what it was not shown treats
the absence of a file as evidence the file does not exist. The omissions
section exists to make "I was not shown this" available as a thought.

What is being described
-----------------------

A `repo_registry.Resolved`: a named project whose canonical checkout has been
verified, whose planning ref has been pinned to one full SHA. There is no path
parameter here, deliberately. Passing a path is how a snapshot came to describe
`D:\Documents\ComicAutomation` -- a real checkout of the real project, on a
feature branch, six weeks stale -- and nothing about that snapshot looked
wrong.

`repo_id` identifies the lineage: a digest of the root commits, so two clones
of a project agree and two projects cannot collide. It cannot say which
checkout is authoritative, because the stale one has the same id. That is the
registry's job, and this module takes its answer.

`base_sha` is the commit the snapshot describes and the base every task planned
from it branches from. It is resolved once, up front. A ref resolved again
later is a different question with the same name.

The baseline is the commit; everything else is context
------------------------------------------------------

File listings and document contents come from `base_sha`. A file that exists
only as an uncommitted edit, or only on the branch the checkout happens to be
on, is not something a plan can rely on -- the author starts from the commit
and will not see it.

What is happening in the checkout right now is reported in its own fenced
section: current branch, uncommitted paths, registered worktrees, and branches
carrying commits the baseline does not have. That is there so a plan can avoid
colliding with work already under way, and it is fenced because it is the part
a planner will most readily mistake for fact. A modified path looks exactly
like a file that exists.

Budgets
-------

Everything that could be unbounded has a budget: the file list, each document,
all documents together, the uncommitted list, and captured test output. Every
budget that is hit is recorded in `omissions` and marked inline at the point of
the cut. A snapshot that quietly drops half the repository is worse than one
that refuses, because the planner cannot tell the difference between "absent"
and "not shown".

This is evidence, not a prompt
------------------------------

`render` produces the snapshot document. It does not ask for a plan, define an
output format, or say what to do -- the planning activation wraps this and adds
that. Keeping the two apart means the same snapshot can be shown to a reviewer,
written to the ledger, or read by a human without carrying instructions
addressed to somebody else.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_registry  # noqa: E402

# Enough of a file list for the planner to locate work in an ordinary
# repository; past this the list stops being read and starts being scrolled.
DEFAULT_FILE_BUDGET = 400

# Per document, and across all of them. The second budget is the one that
# matters: a docs/ directory of twenty design notes will pass the per-file
# check twenty times over and still bury everything else in the snapshot.
DEFAULT_DOC_BUDGET = 12_000
DEFAULT_TOTAL_DOC_BUDGET = 60_000

# Below this, a document is left out rather than shown as a stub. The first
# few hundred bytes of a design note are its title and a sentence of preamble,
# which tells a planner nothing but does not read like nothing -- and a snapshot
# whose whole purpose is separating "absent" from "not shown" should not
# manufacture a third category of "shown, uselessly".
MIN_DOC_FRAGMENT = 1_000

DEFAULT_DIRTY_BUDGET = 60
DEFAULT_TEST_OUTPUT_BUDGET = 8_000

# Where a project states what it is and what it is currently doing. Globs
# rather than names because the status document is called something different
# in every repository; the total budget above is what keeps a wide match from
# swallowing the snapshot.
DEFAULT_DOC_PATTERNS = (
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "docs/*.md",
)


class SnapshotError(Exception):
    """The repository could not answer a question the snapshot needs."""


def _git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if check and result.returncode != 0:
        raise SnapshotError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or '').strip()[:300]}"
        )

    return result.stdout or ""


def _truncate(text: str, budget: int) -> tuple:
    """Cut `text` to `budget` bytes. Returns (text, was_truncated).

    Byte-based, because the budget is about what fits in a context window and
    a character count is not that. Decoding with `ignore` drops a multi-byte
    character split by the cut rather than raising.
    """
    raw = text.encode("utf-8")

    if len(raw) <= budget:
        return text, False

    return raw[:budget].decode("utf-8", "ignore"), True


def repo_id(repo: str) -> str:
    """A stable identifier for the history reachable from HEAD.

    Digest of the sorted root commits -- sorted and hashed rather than used
    raw so that a history with more than one root (a merged-in project, an
    imported archive) still produces exactly one value.
    """
    roots = sorted(
        line.strip()
        for line in _git(repo, "rev-list", "--max-parents=0", "HEAD").splitlines()
        if line.strip()
    )

    if not roots:
        raise SnapshotError("no root commit; the repository has no history to plan against")

    joined = "\n".join(roots)

    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def describe_commit(repo: str, sha: str) -> dict:
    """The baseline commit itself. Nothing here comes from the working tree."""
    verified = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").strip()

    if len(verified) != 40:
        raise SnapshotError(f"{sha!r} did not resolve to a commit sha")

    return {
        "base_sha": verified,
        "base_subject": _git(repo, "log", "-1", "--format=%s", verified).strip(),
        "base_committed": _git(repo, "log", "-1", "--format=%cI", verified).strip(),
    }


def uncommitted(repo: str, budget: int = DEFAULT_DIRTY_BUDGET) -> dict:
    """Working-copy paths that do not match the checkout's own HEAD.

    Operational context, never baseline. These paths say what somebody is in
    the middle of; they say nothing about the commit being planned against,
    and the commit being planned against is usually not even the one they are
    relative to.
    """
    entries = [
        line.rstrip()
        for line in _git(repo, "status", "--porcelain").splitlines()
        if line.strip()
    ]

    shown = entries[:budget]

    return {
        "clean": not entries,
        "count": len(entries),
        "entries": shown,
        "entries_truncated": len(entries) > len(shown),
    }


def worktrees(repo: str) -> list:
    """Every worktree git knows about, including ones that are not here.

    A checkout carries worktree registrations from wherever it has been used,
    and they outlive the machine that made them: this project holds seven
    pointing at `/sessions/.../worktrees/...`, locked, from a cloud session.
    They are reported rather than pruned. Prune is destructive, it is the
    operator's call, and a locked worktree is locked because somebody meant
    it. `present` says whether the path exists on this machine, which is the
    part that decides whether a name can be reused.
    """
    entries = []
    current = {}

    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        line = line.rstrip()

        if not line:
            if current:
                entries.append(current)
                current = {}
            continue

        key, _, value = line.partition(" ")

        if key == "worktree":
            current = {
                "path": value,
                "present": Path(value).exists(),
                "locked": False,
                "branch": "",
                "sha": "",
            }
        elif key == "HEAD":
            current["sha"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "locked":
            current["locked"] = True

    if current:
        entries.append(current)

    return entries


def branches_ahead(repo: str, sha: str, limit: int = 40) -> list:
    """Local branches carrying commits the baseline does not have.

    This is how a planner sees that work is already in flight. A plan that
    asks for something a branch is halfway through is not wrong exactly, but
    it is wasted, and the operator is the only one who can say which.

    Ahead and behind are both reported: a branch 40 behind and 2 ahead is
    somebody's stale experiment, while 0 behind and 12 ahead is the work that
    is about to land on the baseline.
    """
    names = [
        line.strip()
        for line in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        .splitlines()
        if line.strip()
    ]

    ahead = []

    for name in names:
        counts = _git(repo, "rev-list", "--left-right", "--count", f"{sha}...{name}")
        parts = counts.split()

        if len(parts) != 2:
            continue

        behind_n, ahead_n = int(parts[0]), int(parts[1])

        if ahead_n == 0:
            continue

        ahead.append({
            "branch": name,
            "ahead": ahead_n,
            "behind": behind_n,
            "tip": _git(repo, "rev-parse", name).strip()[:12],
            "subject": _git(repo, "log", "-1", "--format=%s", name).strip()[:80],
        })

    ahead.sort(key=lambda row: (-row["ahead"], row["branch"]))

    return ahead[:limit]


DEFAULT_ACTIVE_DIFF_BUDGET = 12_000


def active_work(repo: str, base: str, ref: str, *, budget: int = DEFAULT_ACTIVE_DIFF_BUDGET) -> dict:
    """What is being built right now on `ref`, relative to `base`.

    A planner shown only the baseline plans as though the baseline were the
    whole story. It is not: somebody is twelve commits into a slice on another
    branch, and the most useful plan is the one that does not collide with it
    or re-propose it. This is the difference between "what exists" and "what is
    happening", and only the first was ever in the snapshot.

    The diffstat rather than the diff. Four thousand added lines will not fit
    in a prompt and would crowd out everything else if they did; what a planner
    needs is which files are moving and how much, so it can ask for the ones
    that matter through a context request.
    """
    if not ref:
        return {"ref": "", "present": False}

    head = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False).strip()

    if not head or len(head) != 40:
        return {"ref": ref, "present": False, "reason": f"{ref} does not resolve"}

    ahead = _git(repo, "rev-list", "--count", f"{base}..{head}", check=False).strip()
    behind = _git(repo, "rev-list", "--count", f"{head}..{base}", check=False).strip()
    stat = _git(repo, "diff", "--stat", f"{base}...{head}", check=False)
    names = _git(repo, "diff", "--name-only", f"{base}...{head}", check=False)
    log = _git(repo, "log", "--oneline", "--no-decorate", f"{base}..{head}", check=False)

    stat_text, stat_truncated = _truncate(stat, budget)

    return {
        "ref": ref,
        "present": True,
        "head": head,
        "commits_ahead": int(ahead or 0),
        "commits_behind": int(behind or 0),
        "files": [line.strip() for line in names.splitlines() if line.strip()],
        "diffstat": stat_text,
        "diffstat_truncated": stat_truncated,
        "commits": [line.strip() for line in log.splitlines() if line.strip()][:40],
    }


def operational_context(repo: str, sha: str, *, dirty_budget: int = DEFAULT_DIRTY_BUDGET) -> dict:
    """What is going on in the checkout right now.

    Kept in its own section, and labelled in the rendered document, because it
    is the part that must never leak into the baseline. It is also the part a
    planner most wants to treat as fact: a file listed as modified looks
    exactly like a file that exists, and it is not one -- an author branching
    from the baseline will not find those edits.
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    detached = branch == "HEAD"
    working_head = _git(repo, "rev-parse", "--verify", "HEAD").strip()

    return {
        "checkout_branch": "" if detached else branch,
        "checkout_detached": detached,
        "checkout_head": working_head,
        "checkout_head_is_baseline": working_head == sha,
        "uncommitted": uncommitted(repo, budget=dirty_budget),
        "worktrees": worktrees(repo),
        "branches_ahead": branches_ahead(repo, sha),
    }


def tree(repo: str, sha: str, budget: int = DEFAULT_FILE_BUDGET) -> dict:
    """Every path in the commit, with a directory summary alongside.

    The summary is computed whether or not the list fits. It costs nothing and
    it is the part a planner actually reasons with -- "there are 40 files under
    tests/" is more use than the fortieth filename.
    """
    paths = [
        line.strip()
        for line in _git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
        if line.strip()
    ]

    directories: Dict[str, int] = {}

    for path in paths:
        parts = PurePosixPath(path).parts
        key = parts[0] if len(parts) > 1 else "(repository root)"
        directories[key] = directories.get(key, 0) + 1

    shown = sorted(paths)[:budget]

    return {
        "file_count": len(paths),
        "files": shown,
        "files_truncated": len(paths) > len(shown),
        "directories": dict(sorted(directories.items())),
    }


def matches_pattern(path: str, pattern: str) -> bool:
    """Whether `path` matches `pattern`, anchored at the repository root.

    Componentwise rather than `PurePosixPath.match`, which anchors relative
    patterns at the *right*: under that rule `README.md` also matches
    `archive/backups/2026-05-14/README.md`, and the snapshot would present an
    archived copy of a document under the name of the live one. A wrong
    document is worse than a missing one, because the omissions list cannot
    warn about a document that was included.

    `*` does not cross a directory boundary, so `docs/*.md` means the markdown
    directly inside the repository's own `docs/`, and nothing deeper.
    """
    parts = PurePosixPath(path).parts
    wanted = PurePosixPath(pattern.replace("\\", "/").strip("/")).parts

    if len(parts) != len(wanted):
        return False

    return all(fnmatch.fnmatchcase(part, want) for part, want in zip(parts, wanted))


def _read_from_commit(repo: str, sha: str, path: str) -> Optional[str]:
    """A file's contents as of `sha`, or None if it is not in that commit."""
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=str(repo),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode != 0:
        return None

    return result.stdout or ""


def select_documents(
    repo: str,
    sha: str,
    *,
    named: Sequence[str] = (),
    patterns: Sequence[str] = DEFAULT_DOC_PATTERNS,
) -> List[str]:
    """Which documents to include, in the order they should be spent.

    Explicitly named documents come first and in the order given, because
    naming one is the caller saying it matters more than whatever a glob
    happens to match. Pattern matches follow, sorted, so the same repository
    always produces the same snapshot.

    Matching is done against the commit's own file list rather than the disk,
    so an uncommitted document is not offered as though an author could read
    it from the base commit.
    """
    tracked = [
        line.strip()
        for line in _git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
        if line.strip()
    ]

    ordered: List[str] = []

    for path in named:
        candidate = str(PurePosixPath((path or "").replace("\\", "/")))

        if candidate not in ordered:
            ordered.append(candidate)

    matched = {
        path
        for path in tracked
        for pattern in patterns
        if matches_pattern(path, pattern)
    }

    ordered.extend(path for path in sorted(matched) if path not in ordered)

    return ordered


def collect_documents(
    repo: str,
    sha: str,
    paths: Sequence[str],
    *,
    doc_budget: int = DEFAULT_DOC_BUDGET,
    total_budget: int = DEFAULT_TOTAL_DOC_BUDGET,
    dirty_paths: Sequence[str] = (),
) -> tuple:
    """Read documents until the budget runs out. Returns (documents, omissions).

    Documents that do not fit are not silently dropped: each one is named in
    the omissions with its size, so a planner that needs it can ask for it by
    name instead of inventing what it probably said.
    """
    documents = []
    omissions: List[str] = []
    spent = 0
    dirty = set(dirty_paths)

    for path in paths:
        content = _read_from_commit(repo, sha, path)

        if content is None:
            omissions.append(
                f"{path}: named for inclusion but not present in {sha[:12]}"
            )
            continue

        size = len(content.encode("utf-8"))
        head_room = total_budget - spent
        remaining = min(doc_budget, head_room)

        # The floor applies to what is left over, never to `doc_budget`. A
        # small per-document budget is the caller deciding it wants openings;
        # a small remainder is an accident of which documents came first, and
        # only the accident should be allowed to drop a document.
        if size > head_room and head_room < MIN_DOC_FRAGMENT:
            omissions.append(
                f"{path}: not included ({size:,} bytes); {head_room:,} bytes "
                "of document budget remained, too little to show usefully"
            )
            continue

        text, truncated = _truncate(content, remaining)
        spent += len(text.encode("utf-8"))

        if truncated:
            omissions.append(
                f"{path}: included but truncated at {len(text.encode('utf-8')):,} "
                f"of {size:,} bytes"
            )

        documents.append({
            "path": path,
            "bytes": size,
            "text": text,
            "truncated": truncated,
            "modified_in_working_copy": path in dirty,
        })

    return documents, omissions


def run_tests(
    repo: str,
    command: str,
    *,
    timeout: float = 1800.0,
    budget: int = DEFAULT_TEST_OUTPUT_BUDGET,
) -> dict:
    """Run the project's test command and record what happened.

    **The command is the operator's, never a model's.** This executes on the
    host with the repository writable; a test command supplied by a planner
    would be an arbitrary shell call dressed as configuration. It is a
    parameter so that different projects can be snapshotted, not so that
    something being snapshotted can choose it.

    Output is captured from the tail rather than the head: the failure summary
    is at the end, and a truncated head of a pytest run is a list of dots.
    """
    try:
        result = subprocess.run(
            command,
            cwd=str(repo),
            shell=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "command": command,
            "exit_code": None,
            "output": f"timed out after {timeout:g}s",
            "output_truncated": False,
        }
    except Exception as exc:  # a missing interpreter, a bad shell command
        return {
            "status": "error",
            "command": command,
            "exit_code": None,
            "output": f"could not run: {exc}",
            "output_truncated": False,
        }

    combined = (result.stdout or "") + (result.stderr or "")
    raw = combined.encode("utf-8")
    truncated = len(raw) > budget

    if truncated:
        combined = raw[-budget:].decode("utf-8", "ignore")

    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": command,
        "exit_code": result.returncode,
        "output": combined,
        "output_truncated": truncated,
    }


NOT_RUN = {
    "status": "not_run",
    "command": "",
    "exit_code": None,
    "output": "",
    "output_truncated": False,
}


def build(
    resolved,
    *,
    documents: Sequence[str] = (),
    doc_patterns: Sequence[str] = DEFAULT_DOC_PATTERNS,
    file_budget: int = DEFAULT_FILE_BUDGET,
    doc_budget: int = DEFAULT_DOC_BUDGET,
    total_doc_budget: int = DEFAULT_TOTAL_DOC_BUDGET,
    dirty_budget: int = DEFAULT_DIRTY_BUDGET,
    tests: Optional[dict] = None,
    active_ref: str = "",
) -> dict:
    """Assemble the snapshot of one resolved project at one commit.

    `resolved` is a `repo_registry.Resolved` -- a named project whose
    identity has been verified and whose planning ref has already been pinned
    to a single SHA. There is deliberately no path parameter and no ref
    parameter. A path is how the wrong checkout got snapshotted, and a ref
    resolved here rather than once, up front, would let the baseline move
    between the plan and the work.

    `tests` is the result of `run_tests`, or None. None records `not_run`
    rather than an assumption: the one thing a snapshot must never do is let
    silence read as a passing suite, because "no failures were reported" and
    "nothing was run" look identical in a rendered document and only one of
    them is evidence.
    """
    root = Path(resolved.path).resolve()

    if not (root / ".git").exists():
        raise SnapshotError(f"{root} is not a git repository")

    commit = describe_commit(str(root), resolved.sha)
    sha = commit["base_sha"]

    listing = tree(str(root), sha, budget=file_budget)

    # An empty manifest hashes and renders perfectly well. It would describe a
    # project with no files, which is not a project -- far likelier a ref that
    # resolved to something unexpected, or a discovery that silently found
    # nothing. The same failure was shipped once already in a deploy script.
    if listing["file_count"] == 0:
        raise SnapshotError(
            f"{resolved.name}: commit {sha[:12]} contains no files. Refusing "
            "to produce a snapshot of nothing -- it would render as a valid "
            "description of an empty repository."
        )

    operational = operational_context(str(root), sha, dirty_budget=dirty_budget)
    dirty = operational["uncommitted"]
    active = active_work(str(root), sha, active_ref) if active_ref else {"present": False, "ref": ""}

    # `status --porcelain` lines are "XY path"; the paths are what a document
    # is matched against. Renames arrive as "old -> new" and the new name is
    # the one that exists. These mark a document as "edited in the checkout",
    # never as content -- the content always comes from the baseline commit.
    dirty_paths = {
        entry[3:].split(" -> ")[-1].strip().strip('"') for entry in dirty["entries"]
    }

    selected = select_documents(
        str(root), sha, named=documents, patterns=doc_patterns
    )
    docs, doc_omissions = collect_documents(
        str(root),
        sha,
        selected,
        doc_budget=doc_budget,
        total_budget=total_doc_budget,
        dirty_paths=dirty_paths,
    )

    omissions: List[str] = []

    if listing["files_truncated"]:
        omissions.append(
            f"file list: {len(listing['files']):,} of {listing['file_count']:,} "
            "paths listed; the rest are in the directory summary only"
        )

    if dirty["entries_truncated"]:
        omissions.append(
            f"uncommitted changes: {len(dirty['entries']):,} of {dirty['count']:,} "
            "entries listed"
        )

    omissions.extend(doc_omissions)

    if not dirty["clean"]:
        omissions.append(
            f"the canonical checkout has {dirty['count']:,} uncommitted "
            f"{'entry' if dirty['count'] == 1 else 'entries'}. None of it is in "
            f"the baseline: everything above describes commit {sha[:12]}, which "
            "is what an author will branch from."
        )

    if not operational["checkout_head_is_baseline"]:
        omissions.append(
            f"the canonical checkout is on "
            f"{operational['checkout_branch'] or 'a detached HEAD'} at "
            f"{operational['checkout_head'][:12]}, which is not the baseline. "
            "Its working files are somebody else's work in progress."
        )

    # Said whether or not anything else was cut, because it is the largest
    # omission in every snapshot and the easiest one to forget.
    omissions.append(
        "file contents: only the documents listed above were read. No source "
        "file was included, and nothing here reports what any function does. "
        "This is the single largest gap and the one most likely to make a "
        "plan wrong: a path being absent from the tree says nothing about "
        "whether the behaviour already exists somewhere else under another "
        "name. Ask for the files you need."
    )

    if active.get("present") and active.get("commits_ahead"):
        omissions.append(
            f"active work: {active['ref']} is {active['commits_ahead']} "
            f"commit(s) ahead of the baseline across {len(active['files'])} "
            "file(s). The diffstat is shown; the contents of those commits "
            "are not. Work in progress is the likeliest thing to duplicate."
        )

    if tests is None or tests.get("status") == "not_run":
        omissions.append(
            "test status: no suite was run for this snapshot. Its state is "
            "unknown, which is not the same as passing."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": resolved.name,
        "repo_path": str(root),
        "repo_id": resolved.project.repo_id,
        "planning_ref": resolved.ref,
        **commit,
        "operational": operational,
        "active_work": active,
        "tree": listing,
        "documents": docs,
        "tests": dict(tests) if tests else dict(NOT_RUN),
        "omissions": omissions,
    }


def render(snapshot: dict) -> str:
    """The snapshot as a document.

    Ordered so identity comes first and caveats last: what this is, then how
    far the disk has drifted from it, then the repository itself, then -- read
    immediately before whatever question is asked of it -- what none of the
    above covers.
    """
    base = snapshot["base_sha"]
    operational = snapshot["operational"]
    dirty = operational["uncommitted"]
    listing = snapshot["tree"]

    parts = [
        "REPOSITORY SNAPSHOT",
        "",
        f"generated    : {snapshot['generated_at']}",
        f"project      : {snapshot['project']}",
        f"repo id      : {snapshot['repo_id']}",
        f"path         : {snapshot['repo_path']}",
        f"planning ref : {snapshot['planning_ref']}",
        f"BASE SHA     : {base}",
        f"committed    : {snapshot['base_committed']}  {snapshot['base_subject']}",
        "",
        "THE BASELINE IS THAT COMMIT. The tree and the documents below are "
        "read from it,",
        "and every task planned from this snapshot branches from it. Nothing "
        "in the checkout's",
        "working files is part of it.",
    ]

    parts += [
        "",
        f"TREE -- {listing['file_count']:,} tracked "
        f"{'file' if listing['file_count'] == 1 else 'files'}",
        "",
        "  by directory:",
    ]
    parts.extend(
        f"    {name:<40} {count:>6,}"
        for name, count in listing["directories"].items()
    )

    parts += ["", f"  paths ({len(listing['files']):,} listed):"]
    parts.extend(f"    {path}" for path in listing["files"])

    if listing["files_truncated"]:
        parts.append(
            f"    [LIST TRUNCATED after {len(listing['files']):,} of "
            f"{listing['file_count']:,} paths -- the directory summary above "
            "covers the rest]"
        )

    parts += ["", "DOCUMENTS"]

    if not snapshot["documents"]:
        parts.append("  (none were included)")

    for document in snapshot["documents"]:
        note = ""

        if document["modified_in_working_copy"]:
            note = "  [EDITED SINCE THIS COMMIT -- shown as committed]"

        parts += [
            "",
            f"--- {document['path']} ({document['bytes']:,} bytes){note}",
            "",
            document["text"].rstrip(),
        ]

        if document["truncated"]:
            parts.append(
                f"[TRUNCATED -- {document['bytes']:,} bytes in full. The rest "
                "of this document was not shown.]"
            )

    # Fenced, and placed after the baseline rather than among it. Everything
    # in this section is true of the checkout right now and false of the
    # commit above -- a planner that reads a modified path as a file that
    # exists has read work in progress as fact.
    parts += [
        "",
        "=" * 70,
        "OPERATIONAL CONTEXT -- NOT PART OF THE BASELINE",
        "",
        "What is going on in the canonical checkout at this moment. None of it "
        "is in the",
        "baseline commit, and an author branching from that commit will not "
        "see any of it.",
        "It is here so a plan can avoid colliding with work already under way.",
        "",
    ]

    if operational["checkout_head_is_baseline"]:
        parts.append(
            f"  checkout is on the baseline commit "
            f"({operational['checkout_branch'] or 'detached'})"
        )
    else:
        where = operational["checkout_branch"] or "a detached HEAD"
        parts.append(
            f"  checkout is on {where} at {operational['checkout_head'][:12]} "
            "-- NOT the baseline"
        )

    if dirty["clean"]:
        parts.append("  no uncommitted changes")
    else:
        parts.append(
            f"  {dirty['count']} uncommitted "
            f"{'entry' if dirty['count'] == 1 else 'entries'} in the checkout:"
        )
        parts.extend(f"    {entry}" for entry in dirty["entries"])

        if dirty["entries_truncated"]:
            parts.append("    [LIST TRUNCATED]")

    ahead = operational["branches_ahead"]
    parts += ["", "  branches carrying commits the baseline does not have:"]

    if not ahead:
        parts.append("    (none)")
    else:
        parts.extend(
            f"    {row['branch']:<52} +{row['ahead']:<4} -{row['behind']:<4} "
            f"{row['tip']}  {row['subject']}"
            for row in ahead
        )

    trees = operational["worktrees"]
    parts += ["", "  worktrees registered on this checkout:"]

    if not trees:
        parts.append("    (none)")
    else:
        for row in trees:
            marks = []

            if not row["present"]:
                marks.append("PATH NOT ON THIS MACHINE")
            if row["locked"]:
                marks.append("locked")

            suffix = f"  [{', '.join(marks)}]" if marks else ""
            parts.append(
                f"    {row['path']}  {row['sha'][:12]} "
                f"{row['branch'] or '(detached)'}{suffix}"
            )

    parts += ["", "=" * 70]

    tests = snapshot["tests"]
    parts += ["", "TEST STATUS"]

    if tests["status"] == "not_run":
        parts.append(
            "  not run for this snapshot. The state of the suite is unknown."
        )
    else:
        parts += [
            f"  {tests['status']} (exit {tests['exit_code']})",
            f"  command: {tests['command']}",
            "",
            tests["output"].rstrip() or "  (no output)",
        ]

        if tests["output_truncated"]:
            parts.append("[OUTPUT TRUNCATED -- the tail is shown]")

    # Placed immediately before the omissions, and after everything the
    # baseline says, because it is the section that qualifies all of it: the
    # tree above is what exists, and this is what somebody is in the middle of
    # changing about it. A plan that duplicates work in flight is the most
    # expensive kind, because both versions get written before anybody notices.
    active = snapshot.get("active_work") or {}

    if active.get("present"):
        parts += [
            "",
            "WORK IN PROGRESS ON ANOTHER BRANCH",
            f"  {active['ref']} at {active['head'][:12]}",
            f"  {active['commits_ahead']} commit(s) ahead of the baseline, "
            f"{active['commits_behind']} behind",
            "",
            "  This is not in the baseline and will not be in what you plan "
            "against. It is here so you do not propose it again, and do not "
            "propose anything that collides with it.",
            "",
        ]

        if active.get("commits"):
            parts.append("  Commits:")
            parts.extend(f"    {line}" for line in active["commits"])
            parts.append("")

        if active.get("diffstat"):
            parts.append("  Changed:")
            parts.extend(
                f"    {line}" for line in active["diffstat"].rstrip().splitlines()
            )

            if active.get("diffstat_truncated"):
                parts.append("    [DIFFSTAT TRUNCATED]")

    parts += ["", "OMITTED OR TRUNCATED"]
    parts.extend(f"  - {line}" for line in snapshot["omissions"])
    parts += [
        "",
        "  Nothing outside this document was examined. An absence here is "
        "evidence about the snapshot, not about the repository.",
    ]

    return "\n".join(parts)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project", required=True,
        help="a name registered in repos.json. There is no --repo: a path is "
             "how the wrong checkout got snapshotted.",
    )
    parser.add_argument(
        "--registry", default=None,
        help="an alternative registry file (default: repos.json beside this)",
    )
    parser.add_argument(
        "--doc", action="append", default=[],
        help="include this path first, ahead of the pattern matches. Repeatable.",
    )
    parser.add_argument(
        "--pattern", action="append", default=None,
        help="override the default document patterns. Repeatable.",
    )
    parser.add_argument("--file-budget", type=int, default=DEFAULT_FILE_BUDGET)
    parser.add_argument("--doc-budget", type=int, default=DEFAULT_DOC_BUDGET)
    parser.add_argument(
        "--total-doc-budget", type=int, default=DEFAULT_TOTAL_DOC_BUDGET
    )
    parser.add_argument(
        "--run-tests", metavar="COMMAND", default=None,
        help="run this command in the repository and record the result. The "
             "command is yours: it executes on this host with the repository "
             "writable.",
    )
    parser.add_argument(
        "--json", metavar="PATH", default=None,
        help="also write the snapshot as JSON, for the ledger",
    )
    args = parser.parse_args(argv[1:])

    # The snapshot quotes documents, and documents contain arrows, dashes and
    # accented names. A Windows console is cp1252, so printing one unprepared
    # raises UnicodeEncodeError -- the snapshot would be built correctly and
    # then die on its way to the screen. Replacement characters in a terminal
    # are a cosmetic loss; the JSON is written as UTF-8 and keeps everything.
    stream = getattr(sys.stdout, "reconfigure", None)

    if stream is not None:
        stream(encoding="utf-8", errors="replace")

    try:
        resolved = repo_registry.resolve_name(args.project, args.registry)
    except repo_registry.RegistryError as exc:
        print(f"snapshot: {exc}")
        return 2

    print(
        f"snapshot: {resolved.name} -> {resolved.ref} -> {resolved.sha}",
        file=sys.stderr,
    )

    try:
        tests = (
            run_tests(str(resolved.path), args.run_tests) if args.run_tests else None
        )
        snapshot = build(
            resolved,
            documents=args.doc,
            doc_patterns=tuple(args.pattern) if args.pattern else DEFAULT_DOC_PATTERNS,
            file_budget=args.file_budget,
            doc_budget=args.doc_budget,
            total_doc_budget=args.total_doc_budget,
            tests=tests,
        )
    except SnapshotError as exc:
        print(f"snapshot: {exc}")
        return 1

    if args.json:
        Path(args.json).write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )

    print(render(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
