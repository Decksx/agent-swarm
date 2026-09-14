"""Chat-command ingress: a message from the operator becomes a draft, then a task.

The first production slice, and deliberately narrow. The hub calls
`handle_message` for every message it stores; everything here decides whether
that message is a command and, if so, what the one allowed response is.

What it will act on
-------------------

Only a message whose authenticated sender is an admin component, whose content
begins with an exact mention. Nothing a worker posts, and nothing this module
posts, is ever parsed: replies go out as `controller`, which is not an admin.

* `@ChatGPT <title>` / `@ClaudeCode <title>` draft a task authored by that agent.
* `@swarm <title>` / `@all <title>` draft a task authored by the default author.
  Every route is the same pipeline -- author, then review by the configured
  verifier, then integration by the configured integrator -- issued stage by
  stage by progression. No mention activates several models at once.
* `@swarm confirm CMD-<id>` (or `@all confirm ...`) turns a draft into a task.
* `@Gemini status T-<id>` reports a task. `@Gemini` cannot start new work: a
  review needs something to review, and progression issues it.

What it will not do
-------------------

Call a model, read a repository, or guess. A command names its project, its
full base commit, and its allowed paths explicitly; the controller has no
working copy and cannot resolve `main` or discover paths itself. Anything
missing or malformed is refused with the specific reason, and nothing is stored.

Idempotency
-----------

A draft's id is derived from its content (sender included), so the same command
delivered twice lands on one draft. A confirmation runs steps that each check
whether they have already happened -- create the task, queue it, issue its
author activation, mark the draft confirmed -- so a repeated or interrupted
confirmation converges on one task and one activation.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from typing import Iterable, Optional

from . import activations, drafts, engine, states
from .db import PROOF_MODES

ADMIN_SENDERS = frozenset({"admin", "operator"})
REPLY_SENDER = "controller"
DEFAULT_AUTHOR = "chatgpt"

# Leading mention -> author. Matched case-insensitively against the first token.
AUTHOR_MENTIONS = {
    "@chatgpt": "chatgpt",
    "@claudecode": "claudecode",
    "@swarm": DEFAULT_AUTHOR,
    "@all": DEFAULT_AUTHOR,
}
PIPELINE_MENTIONS = frozenset({"@swarm", "@all"})
REVIEW_MENTION = "@gemini"

DRAFT_ID_RE = re.compile(r"^CMD-[0-9a-f]{10}$")
TASK_ID_RE = re.compile(r"^T-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Relative repository paths only: no leading slash, no drive, no backslash, no
# `..` segment, and a character set that needs no quoting in the contract YAML.
PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.][A-Za-z0-9_./-]*$")
FIELDS = ("project", "base", "paths", "context", "proof")
MAX_TITLE = 200
DEFAULT_PROOF = "branch_only"


class IngressRefused(Exception):
    """A command that cannot be acted on, with the reason to show the operator."""


# --- Configuration -----------------------------------------------------------


def parse_projects(value: Optional[str]) -> dict:
    """`INGRESS_PROJECTS` as {name: repo_location}.

    Comma-separated `name=location` entries; split on the first `=`, so a
    Windows location such as `C:/git/agent-swarm` is kept whole. Malformed
    entries raise rather than being skipped: a project that silently vanished
    from the map would be refused with a misleading reason.
    """
    projects = {}

    for entry in (value or "").split(","):
        entry = entry.strip()

        if not entry:
            continue

        name, sep, location = entry.partition("=")
        name, location = name.strip().lower(), location.strip()

        if not sep or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) or not location:
            raise ValueError(f"INGRESS_PROJECTS entry {entry!r} is not name=location")

        projects[name] = location

    return projects


# --- Parsing ---------------------------------------------------------------------


def _split_paths(raw: str, field: str) -> tuple:
    paths = [p.strip() for p in raw.split(",") if p.strip()]

    if not paths:
        raise IngressRefused(f"`{field}:` names no paths")

    for path in paths:
        if not PATH_RE.match(path):
            raise IngressRefused(
                f"`{field}:` path {path!r} is not a relative repository path "
                "(no leading /, drive, backslash or `..`)"
            )

    return tuple(sorted(set(paths)))


def parse_task_command(content: str, *, author: str, projects: dict) -> dict:
    """The draft content for a task command, or IngressRefused with the reason."""
    lines = content.replace("\r\n", "\n").split("\n")
    first = lines[0].split(None, 1)
    title = first[1].strip() if len(first) > 1 else ""

    if not title:
        raise IngressRefused("the first line needs a title after the mention")

    # The commonest mistake, named: every field typed on the title line, as a
    # one-line chat box forces. Checked before the title's length, which such a
    # line usually exceeds, so the refusal points at the actual fix.
    second = lines[1] if len(lines) > 1 else ""
    field_re = r"(?i)(?:^|\s)(?:project|base|paths|context|proof):"
    if re.search(field_re, title) and not re.match(r"(?i)\s*(?:project|base|paths|context|proof)\s*:", second):
        raise IngressRefused(
            "put `project:`, `base:` and `paths:` each on its own line below the title "
            "(Shift+Enter in the chat box), then a blank line and the objective"
        )

    if len(title) > MAX_TITLE:
        raise IngressRefused(f"the title is longer than {MAX_TITLE} characters")

    fields = {}
    index = 1

    while index < len(lines) and lines[index].strip():
        key, sep, value = lines[index].partition(":")
        key = key.strip().lower()

        if not sep or key not in FIELDS:
            raise IngressRefused(
                f"line {index + 1} is not one of {', '.join(f + ':' for f in FIELDS)} "
                "(put a blank line before the objective)"
            )

        if key in fields:
            raise IngressRefused(f"`{key}:` is given twice")

        fields[key] = value.strip()
        index += 1

    objective = "\n".join(lines[index:]).strip()

    for required in ("project", "base", "paths"):
        if not fields.get(required):
            raise IngressRefused(f"`{required}:` is required")

    if not objective:
        raise IngressRefused("the objective is missing: add it after a blank line")

    project = fields["project"].lower()

    if project not in projects:
        known = ", ".join(sorted(projects)) or "none configured"
        raise IngressRefused(f"unknown project {project!r}; known: {known}")

    base = fields["base"].lower()

    if not SHA_RE.match(base):
        raise IngressRefused(
            "`base:` must be a full 40-character commit SHA; the controller "
            "has no checkout and cannot resolve a branch name"
        )

    allowed = _split_paths(fields["paths"], "paths")
    context = _split_paths(fields["context"], "context") if fields.get("context") else ()
    overlap = sorted(set(allowed) & set(context))

    if overlap:
        raise IngressRefused(f"{overlap} are both writable (`paths:`) and read-only (`context:`)")

    proof = (fields.get("proof") or DEFAULT_PROOF).lower()

    if proof not in PROOF_MODES:
        raise IngressRefused(f"`proof:` must be one of {', '.join(PROOF_MODES)}")

    return {
        "kind": "task",
        "title": title,
        "objective": objective,
        "project": project,
        "repo_location": projects[project],
        "base_sha": base,
        "proof_mode": proof,
        "allowed_paths": list(allowed),
        "context_paths": list(context),
        "author": author,
    }


def draft_id_for(content: dict, sender: str) -> str:
    identity = drafts.canonical_content({"sender": sender, "content": content})
    return "CMD-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]


def task_id_for(draft_id: str) -> str:
    return "T-" + draft_id


def contract_yaml_for(task_id: str, content: dict) -> str:
    lines = ["schema_version: 7", f"task_id: {task_id}", "allowed_paths:"]
    lines += [f"  - {p}" for p in content["allowed_paths"]]

    if content["context_paths"]:
        lines.append("context_paths:")
        lines += [f"  - {p}" for p in content["context_paths"]]

    return "\n".join(lines) + "\n"


# --- Replies ---------------------------------------------------------------------


def _describe(content: dict, routing) -> list:
    return [
        f"project:     {content['project']} ({content['repo_location']})",
        f"base:        {content['base_sha']}",
        f"proof mode:  {content['proof_mode']}",
        f"paths:       {', '.join(content['allowed_paths'])}",
        f"context:     {', '.join(content['context_paths']) or '(none)'}",
        f"routing:     author {content['author']} -> review {routing.verifier or '(unset)'} "
        f"-> integrate {routing.integrator or '(unset)'}",
        f"title:       {content['title']}",
        "objective:",
        *("  " + line for line in content["objective"].split("\n")),
    ]


def _preview(draft: dict, created: bool, routing, conn: sqlite3.Connection) -> str:
    draft_id = draft["draft_id"]
    task_id = task_id_for(draft_id)
    head = f"Draft {draft_id}" + ("" if created else " (already drafted; nothing new stored)")

    if draft["status"] == drafts.CONFIRMED or _task_exists(conn, task_id):
        tail = f"Already confirmed as {task_id}."
    else:
        tail = f"Nothing runs until you confirm. To create {task_id}, send:\n@swarm confirm {draft_id}"

    return "\n".join([head, *_describe(draft["content"], routing), "", tail])


# --- Confirmation ----------------------------------------------------------------


def _task_exists(conn: sqlite3.Connection, task_id: str) -> bool:
    return conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is not None


def _author_activation(conn: sqlite3.Connection, task_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT activation_id FROM activations WHERE task_id = ? AND stage = 'author' "
        "ORDER BY issued_at ASC, activation_id ASC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row[0] if row is not None else None


def confirm(conn: sqlite3.Connection, draft_id: str, *, sender: str, routing,
            now: Optional[float] = None) -> str:
    """Create, queue and start the task a draft describes. Safe to repeat."""
    now = time.time() if now is None else now

    try:
        draft = drafts.get_draft(conn, draft_id)
    except drafts.DraftNotFound:
        raise IngressRefused(f"there is no draft {draft_id}")

    content = draft["content"]
    task_id = task_id_for(draft_id)
    contract = contract_yaml_for(task_id, content)
    notes = []

    if not routing.host:
        raise IngressRefused("PROGRESSION_HOST is not configured, so no author activation can be issued")

    if not _task_exists(conn, task_id):
        try:
            engine.create_task(
                conn, task_id=task_id, title=content["title"], objective=content["objective"],
                contract_yaml=contract, base_sha=content["base_sha"], created_by=sender,
                proof_mode=content["proof_mode"], now=now,
            )
            notes.append("created")
        except sqlite3.IntegrityError:
            pass  # created by a concurrent confirmation; carry on with its row

    task = engine.get_task(conn, task_id)

    if task["contract_hash"] != engine.contract_hash(contract):
        raise IngressRefused(f"{task_id} exists with a different contract; refusing to reuse it")

    if task["state"] == "DRAFT":
        for kind in ("contract_validated", "queued"):
            engine.apply_transition(conn, task_id=task_id, kind=kind, actor=sender,
                                    authority=states.CONTROLLER, now=now)
        notes.append("queued")
        task = engine.get_task(conn, task_id)

    activation_id = _author_activation(conn, task_id)

    if activation_id is None and task["state"] == "READY_AUTHOR":
        try:
            issued = activations.issue(
                conn, task_id=task_id, agent=content["author"], host=routing.host, stage="author",
                lease_seconds=routing.lease_seconds, hard_deadline_seconds=routing.hard_deadline_seconds,
                expected_branch=f"task/{task_id}-a1", repo_location=content["repo_location"], now=now,
            )
            activation_id = issued["activation_id"]
            notes.append("author activation issued")
        except activations.HostAtCapacity as exc:
            raise IngressRefused(
                f"{task_id} is queued, but {routing.host} is at capacity ({exc}); "
                f"send the same confirmation again once a slot frees"
            )
        task = engine.get_task(conn, task_id)

    if draft["status"] == drafts.PENDING:
        try:
            drafts.confirm_draft(conn, draft_id, draft["draft_hash"], now=now)
        except drafts.DraftAlreadyConfirmed:
            pass

    head = (f"Confirmed {draft_id} as {task_id}" if notes
            else f"{draft_id} was already confirmed as {task_id}; nothing new was created")

    return "\n".join([
        head,
        f"task:        {task_id} ({task['state']})",
        f"author activation: {activation_id or '(none)'}",
        *_describe(content, routing),
    ])


# --- Entry point -----------------------------------------------------------------


def handle_message(conn: sqlite3.Connection, *, sender: str, content: str, projects: dict,
                   routing, now: Optional[float] = None) -> Optional[str]:
    """The reply to post for a stored chat message, or None if it is not a command."""
    if (sender or "").strip().lower() not in ADMIN_SENDERS:
        return None

    text = content or ""
    first_line = text.split("\n", 1)[0]
    tokens = first_line.split()

    # Exact leading mention: the message's first characters are the mention.
    if not tokens or not first_line.startswith(tokens[0]):
        return None

    mention = tokens[0].lower()

    if mention not in AUTHOR_MENTIONS and mention != REVIEW_MENTION:
        return None

    try:
        if mention == REVIEW_MENTION:
            if len(tokens) == 3 and tokens[1].lower() == "status" and TASK_ID_RE.match(tokens[2]):
                try:
                    task = engine.get_task(conn, tokens[2])
                except engine.TaskNotFound:
                    raise IngressRefused(f"there is no task {tokens[2]}")
                return (f"{task['task_id']} is {task['state']}. Reviews are issued by progression "
                        "when a candidate is ready; nothing was started.")
            raise IngressRefused(
                "@Gemini reviews through the pipeline and cannot start new work. "
                "Start work with @swarm, @ChatGPT or @ClaudeCode, or ask `@Gemini status T-<id>`."
            )

        if len(tokens) >= 2 and tokens[1].lower() == "confirm":
            if mention not in PIPELINE_MENTIONS:
                raise IngressRefused("confirm with `@swarm confirm CMD-<id>`")
            if len(tokens) != 3 or "\n" in text.strip() or not DRAFT_ID_RE.match(tokens[2]):
                raise IngressRefused("a confirmation is exactly `@swarm confirm CMD-<10 hex>`")
            return confirm(conn, tokens[2], sender=sender, routing=routing, now=now)

        parsed = parse_task_command(text, author=AUTHOR_MENTIONS[mention], projects=projects)
        draft_id = draft_id_for(parsed, sender)
        draft, created = drafts.ensure_draft(conn, parsed, draft_id=draft_id, created_by=sender, now=now)
        return _preview(draft, created, routing, conn)
    except IngressRefused as exc:
        return f"Not accepted: {exc}"
