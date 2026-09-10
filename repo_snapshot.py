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

What identifies the snapshot
----------------------------

`repo_id` is a digest of the root commit(s) reachable from HEAD. Not the remote
URL, which can be renamed, re-pointed, or absent on a host that only ever
clones; not the filesystem path, which differs on every machine and again in
every worktree. The root commit is fixed for the life of the history, so two
checkouts of the same project agree and two different projects cannot collide.
A plan carries the `repo_id` it was made against, which is what stops a plan
for one repository being executed against another whose paths happen to match.

`head_sha` is the exact commit the snapshot describes. It becomes the plan's
base, and a later HEAD that has moved off it is what makes a plan stale.

The tree is the commit's tree
-----------------------------

File listings and document contents come from `HEAD`, not from the working
tree, because `head_sha` is what an author will branch from. A file that exists
only as an uncommitted edit is not something a plan can rely on: the author
starts from the commit and will not see it.

Uncommitted changes are therefore reported as a separate list of deviations
rather than folded into the tree. That is the honest shape -- "these paths in
the working copy do not match the commit I am describing" -- and it lets the
planner see that a document it is reading has been edited since, without the
snapshot having to guess which version is the real one.

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


def head(repo: str) -> dict:
    """The commit being described, and the label it is currently wearing."""
    sha = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()

    if len(sha) != 40:
        raise SnapshotError("HEAD did not resolve to a commit sha")

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    detached = branch == "HEAD"

    subject = _git(repo, "log", "-1", "--format=%s", sha).strip()
    committed = _git(repo, "log", "-1", "--format=%cI", sha).strip()

    return {
        "head_sha": sha,
        "branch": "" if detached else branch,
        "detached": detached,
        "head_subject": subject,
        "head_committed": committed,
    }


def uncommitted(repo: str, budget: int = DEFAULT_DIRTY_BUDGET) -> dict:
    """Working-copy paths that do not match HEAD.

    Reported rather than merged into the tree. The snapshot describes a
    commit; these are the places where the disk disagrees with it, which is a
    different fact and one the planner needs stated as such.
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
    repo: str,
    *,
    documents: Sequence[str] = (),
    doc_patterns: Sequence[str] = DEFAULT_DOC_PATTERNS,
    file_budget: int = DEFAULT_FILE_BUDGET,
    doc_budget: int = DEFAULT_DOC_BUDGET,
    total_doc_budget: int = DEFAULT_TOTAL_DOC_BUDGET,
    dirty_budget: int = DEFAULT_DIRTY_BUDGET,
    tests: Optional[dict] = None,
) -> dict:
    """Assemble the snapshot of `repo` at its current HEAD.

    `tests` is the result of `run_tests`, or None. None records `not_run`
    rather than an assumption: the one thing a snapshot must never do is let
    silence read as a passing suite, because "no failures were reported" and
    "nothing was run" look identical in a rendered document and only one of
    them is evidence.
    """
    root = Path(repo).resolve()

    if not (root / ".git").exists():
        raise SnapshotError(f"{root} is not a git repository")

    identity = head(str(root))
    sha = identity["head_sha"]

    dirty = uncommitted(str(root), budget=dirty_budget)
    listing = tree(str(root), sha, budget=file_budget)

    # `status --porcelain` lines are "XY path"; the paths are what a document
    # is matched against. Renames arrive as "old -> new" and the new name is
    # the one that exists.
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
            f"the working copy has {dirty['count']:,} uncommitted "
            f"{'entry' if dirty['count'] == 1 else 'entries'}; everything above "
            f"describes commit {sha[:12]}, not what is on disk"
        )

    # Said whether or not anything else was cut, because it is the largest
    # omission in every snapshot and the easiest one to forget.
    omissions.append(
        "file contents: only the documents listed above were read. No source "
        "file was included, and nothing here reports what any function does."
    )

    if tests is None or tests.get("status") == "not_run":
        omissions.append(
            "test status: no suite was run for this snapshot. Its state is "
            "unknown, which is not the same as passing."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_path": str(root),
        "repo_id": repo_id(str(root)),
        **identity,
        "uncommitted": dirty,
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
    identity = snapshot["head_sha"]
    branch = snapshot["branch"] or f"(detached at {identity[:12]})"
    dirty = snapshot["uncommitted"]
    listing = snapshot["tree"]

    parts = [
        "REPOSITORY SNAPSHOT",
        "",
        f"generated : {snapshot['generated_at']}",
        f"repo id   : {snapshot['repo_id']}",
        f"path      : {snapshot['repo_path']}",
        f"branch    : {branch}",
        f"HEAD      : {identity}",
        f"committed : {snapshot['head_committed']}  {snapshot['head_subject']}",
        "",
        "Everything below describes that commit. It is the base an author "
        "would branch from.",
        "",
        "WORKING COPY",
    ]

    if dirty["clean"]:
        parts.append("  clean -- the working copy matches the commit above")
    else:
        parts.append(
            f"  {dirty['count']} uncommitted "
            f"{'entry' if dirty['count'] == 1 else 'entries'}; these paths on "
            "disk differ from the commit and are not part of it:"
        )
        parts.extend(f"    {entry}" for entry in dirty["entries"])

        if dirty["entries_truncated"]:
            parts.append("    [LIST TRUNCATED]")

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
    parser.add_argument("--repo", required=True)
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
        tests = run_tests(args.repo, args.run_tests) if args.run_tests else None
        snapshot = build(
            args.repo,
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
