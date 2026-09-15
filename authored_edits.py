"""EDIT blocks: how an API author changes a file without retyping it (#35).

Why this exists
---------------

The API author used to change a file by returning its complete new contents.
For `hub/hub.py` that meant regenerating 27,000 characters to change three
lines, and gpt-4o reproducibly dropped the same six-line comment block while
doing it -- in three candidates, two of them after a rejection that named the
deletion. The harness was not losing the lines: it showed the file whole and
parsed the answer exactly. Nothing checked what came back against what was
there, so a line the model forgot was a line the commit deleted.

So an existing file is changed only through edits:

    EDIT: hub/hub.py
    <<<SEARCH>>>
    lines copied exactly from the file
    <<<REPLACE>>>
    the lines that replace them
    <<<END>>>

A line the author did not put in a SEARCH is a line it cannot remove. `FILE`
blocks remain, for new files only; one naming a file that exists at the base
is refused rather than applied, because applying it is the failure above.

What is refused, and how
------------------------

Everything is resolved against the base before anything is written: every
path checked against the scope, every SEARCH matched. A SEARCH must match
exactly one run of whole lines in the file as the earlier edits to it have
left it. Zero matches means the author did not copy the text it was shown;
several means the edit does not say which one it means, and picking one would
be this module deciding. Either is an `EditRefused` that names the block, which
is what lets the author be told once and try again within the same activation.

A path outside the scope is not an `EditRefused`. That is not a copying
mistake an author should be invited to correct; it is the boundary, and it
stays a plain refusal.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import authored_change
from authored_change import BEGIN, END, FILE_HEADER, AuthoringError

EDIT_HEADER = re.compile(r"^EDIT:\s*(?P<path>\S.*?)\s*$")
SEARCH = "<<<SEARCH>>>"
REPLACE = "<<<REPLACE>>>"

# The file shown again in a repair prompt is bounded like the first view.
REPAIR_FILE_VIEW = authored_change.DEFAULT_FILE_VIEW


class EditRefused(AuthoringError):
    """The answer parsed but cannot be applied as written; the author can fix it."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class Block:
    kind: str  # "file" or "edit"
    path: str
    content: str = ""
    search: Tuple[str, ...] = ()
    replace: Tuple[str, ...] = ()


def _until(lines: List[str], index: int, marker: str) -> Tuple[List[str], int]:
    """The lines before `marker` from `index`, and the index after it (-1 if absent)."""
    body = []

    while index < len(lines) and lines[index].strip() != marker:
        body.append(lines[index])
        index += 1

    if index >= len(lines):
        return body, -1

    return body, index + 1


def parse_answer(text: str) -> List[Block]:
    """Return the FILE and EDIT blocks in a model's answer, in order, or raise.

    The same contract as `authored_change.parse_files`: nothing, CANNOT_AUTHOR,
    a block missing its terminator, or no blocks at all is an `AuthoringError`
    -- a truncated answer must never read as a complete one.
    """
    if not isinstance(text, str) or not text.strip():
        raise AuthoringError("the model returned nothing")

    if text.strip().startswith("CANNOT_AUTHOR:"):
        raise AuthoringError(text.strip().splitlines()[0])

    lines = text.replace("\r\n", "\n").split("\n")
    blocks: List[Block] = []
    index = 0

    while index < len(lines):
        file_header = FILE_HEADER.match(lines[index])
        edit_header = EDIT_HEADER.match(lines[index])

        if file_header is None and edit_header is None:
            index += 1
            continue

        path = (file_header or edit_header).group("path")
        index += 1
        opener = BEGIN if file_header else SEARCH

        if index >= len(lines) or lines[index].strip() != opener:
            kind = "FILE" if file_header else "EDIT"
            raise AuthoringError(f"{path!r}: expected {opener} after the {kind} line")

        if file_header:
            body, index = _until(lines, index + 1, END)

            if index < 0:
                raise AuthoringError(f"{path!r}: no {END}; the answer was truncated")

            blocks.append(Block("file", path, content="\n".join(body) + "\n"))
            continue

        search, index = _until(lines, index + 1, REPLACE)

        if index < 0:
            raise AuthoringError(f"{path!r}: no {REPLACE} in an EDIT block; the answer was truncated")

        replace, index = _until(lines, index, END)

        if index < 0:
            raise AuthoringError(f"{path!r}: no {END}; the answer was truncated")

        blocks.append(Block("edit", path, search=tuple(search), replace=tuple(replace)))

    if not blocks:
        raise AuthoringError("no FILE or EDIT blocks in the model's answer")

    return blocks


def _at_base(root: Path, base: str, relative: str) -> Optional[str]:
    """The file's text at `base`, or None if it does not exist there."""
    shown = subprocess.run(
        ["git", "show", f"{base}:{relative}"], cwd=str(root),
        capture_output=True, check=False, timeout=60,
    )

    if shown.returncode != 0:
        return None

    try:
        return shown.stdout.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise EditRefused(f"{relative} is not UTF-8 text and cannot be edited", relative)


def _matches(lines: List[str], search: Tuple[str, ...]) -> List[int]:
    width = len(search)
    return [
        start for start in range(len(lines) - width + 1)
        if tuple(lines[start:start + width]) == search
    ]


def resolve(repo: str, base: str, blocks: List[Block], scope) -> List[Tuple[str, str]]:
    """[(path, new contents)] for every file the answer changes, or raise.

    Nothing is written. Paths are checked against `scope` first, so a path the
    task may not touch is refused as that, whatever else is wrong with it.
    """
    root = Path(repo).resolve()
    texts: Dict[str, str] = {}
    created = set()
    order: List[str] = []

    def at_base(relative: str, label: str) -> Optional[str]:
        try:
            return _at_base(root, base, relative)
        except EditRefused as exc:
            raise EditRefused(f"{label}: {exc}", relative) from None

    for number, block in enumerate(blocks, start=1):
        target = authored_change.safe_relative_path(root, block.path, scope)
        relative = target.relative_to(root).as_posix()
        label = f"block {number} ({block.kind.upper()} {relative})"

        if block.kind == "file":
            if relative in texts or relative in created:
                raise EditRefused(f"{label}: {relative} is written twice in one answer", relative)

            if at_base(relative, label) is not None:
                raise EditRefused(
                    f"{label}: {relative} already exists. Use EDIT blocks for existing "
                    "files; a FILE block only creates a new one",
                    relative,
                )

            created.add(relative)
            texts[relative] = block.content
            order.append(relative)
            continue

        if relative in created:
            raise EditRefused(
                f"{label}: {relative} is created by a FILE block in this answer; "
                "put its whole content there instead of editing it", relative)

        if not block.search or not any(line.strip() for line in block.search):
            raise EditRefused(f"{label}: its SEARCH is empty; copy the lines to replace", relative)

        if relative not in texts:
            original = at_base(relative, label)

            if original is None:
                raise EditRefused(
                    f"{label}: {relative} does not exist; create it with a FILE block",
                    relative)

            texts[relative] = original
            order.append(relative)

        lines = texts[relative].split("\n")
        found = _matches(lines, block.search)

        if len(found) != 1:
            first = block.search[0].strip()[:80]
            problem = (
                "does not appear in the file" if not found
                else f"appears {len(found)} times; include enough surrounding lines to "
                     "make it unique"
            )
            raise EditRefused(
                f"{label}: its SEARCH ({len(block.search)} line(s), first {first!r}) "
                f"{problem}. SEARCH must be copied exactly, whole lines, from the file "
                "as it stands after this answer's earlier edits to it",
                relative,
            )

        start = found[0]
        lines[start:start + len(block.search)] = list(block.replace)
        texts[relative] = "\n".join(lines)

    return [(relative, texts[relative]) for relative in order]


def repair_prompt(error: EditRefused, repo: str, base: str) -> str:
    """What the author is told when its answer could not be applied. Asked once."""
    parts = [
        "YOUR ANSWER COULD NOT BE APPLIED, AND NOTHING WAS WRITTEN.",
        "",
        str(error),
        "",
        "Answer again with your complete change -- every FILE and EDIT block, not "
        "only the one that failed -- in the same form as before. This is the only "
        "retry: an answer that cannot be applied again ends this attempt.",
    ]

    if error.path:
        try:
            text = _at_base(Path(repo).resolve(), base, error.path)
        except EditRefused:
            text = None

        if text is not None:
            shown = text[:REPAIR_FILE_VIEW]
            parts += [
                "",
                f"{error.path} as it is now, to copy SEARCH text from"
                + (" (truncated)" if len(shown) < len(text) else "") + ":",
                f"--- {error.path}",
                shown.rstrip("\n"),
            ]

    return "\n".join(parts)
