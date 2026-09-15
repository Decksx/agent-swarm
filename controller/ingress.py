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
* `@swarm retry T-<id>` asks the controller for another author attempt on a
  task in CHANGES_REQUESTED and issues it to the previous attempt's author;
  `@ChatGPT retry T-<id>` / `@ClaudeCode retry T-<id>` choose the author (#33).
* `@swarm cancel T-<id> <reason>` previews a cancellation, and only
  `@swarm confirm-cancel T-<id> <code> <reason>` -- the line the preview
  gives -- applies it.

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

A retry issues nothing while an activation is live, so a repeated retry is a
no-op. A cancellation code is derived from the task, its state sequence and the
reason, so a confirmation replayed from chat history, typed with a different
reason, or sent after the task moved does not match and cancels nothing.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from typing import Iterable, Optional

from . import activations, drafts, engine, states
from .db import PROOF_MODES, transaction

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
LIFECYCLE_WORDS = frozenset({"retry", "cancel", "confirm-cancel"})
CANCEL_CODE_RE = re.compile(r"^[0-9a-f]{8}$")
MAX_REASON = 500
MAX_RATIONALE_SHOWN = 600


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


# --- Retry and cancel (#33) --------------------------------------------------------


def _task(conn: sqlite3.Connection, task_id: str) -> dict:
    try:
        return engine.get_task(conn, task_id)
    except engine.TaskNotFound:
        raise IngressRefused(f"there is no task {task_id}")


def _live_activation(conn: sqlite3.Connection, task_id: str):
    """An issued or claimed activation for the task: work somebody holds."""
    return conn.execute(
        "SELECT activation_id, stage, agent, status FROM activations "
        "WHERE task_id = ? AND status IN (?, ?) ORDER BY issued_at DESC LIMIT 1",
        (task_id, activations.ISSUED, activations.CLAIMED),
    ).fetchone()


def _author_attempts(conn: sqlite3.Connection, task_id: str) -> int:
    """Counted the way `engine.authorize_retry` counts them."""
    return conn.execute(
        "SELECT COUNT(*) FROM activations WHERE task_id = ? AND stage = 'author' "
        "AND chargeable_attempt = 1",
        (task_id,),
    ).fetchone()[0]


def _next_author_branch(conn: sqlite3.Connection, task_id: str) -> str:
    """`task/<id>-a<n>` for the next attempt, never one an activation has used."""
    used = {row[0] for row in conn.execute(
        "SELECT expected_branch FROM activations WHERE task_id = ? "
        "AND expected_branch IS NOT NULL", (task_id,))}
    n = conn.execute(
        "SELECT COUNT(*) FROM activations WHERE task_id = ? AND stage = 'author'",
        (task_id,),
    ).fetchone()[0] + 1

    while f"task/{task_id}-a{n}" in used:
        n += 1

    return f"task/{task_id}-a{n}"


def retry(conn: sqlite3.Connection, task_id: str, *, author: Optional[str], sender: str,
          routing, now: Optional[float] = None) -> str:
    """Ask for another author attempt and issue it. Safe to repeat.

    The controller decides: `engine.authorize_retry` either authorises the
    attempt or, with the budget spent, escalates to NEEDS_HUMAN. A task already
    in READY_AUTHOR -- authorised earlier, its activation refused for capacity
    -- only needs the activation. A live activation means the attempt is
    already under way, and nothing new is issued.
    """
    now = time.time() if now is None else now
    task = _task(conn, task_id)
    authorised = False

    if not routing.host:
        raise IngressRefused("PROGRESSION_HOST is not configured, so no author activation can be issued")

    previous = conn.execute(
        "SELECT agent, repo_location FROM activations WHERE task_id = ? AND stage = 'author' "
        "ORDER BY attempt_no DESC, issued_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    repo_location = ((previous["repo_location"] if previous else "") or routing.repo_location or "").strip()

    if previous is None or not repo_location:
        raise IngressRefused(
            f"{task_id} has no earlier author activation to take its author and repository "
            "location from; issue its first attempt with the admin CLI"
        )

    if task["state"] == "CHANGES_REQUESTED":
        outcome = engine.authorize_retry(conn, task_id=task_id, actor=sender, now=now)

        if outcome["to_state"] != "READY_AUTHOR":
            return (
                f"{task_id} has used {_author_attempts(conn, task_id)} of "
                f"{engine.DEFAULT_AUTHOR_ATTEMPTS} author attempts, so the controller did not "
                f"authorise another: it is now {outcome['to_state']}. Nothing was issued."
            )

        authorised = True
        task = _task(conn, task_id)
    elif task["state"] != "READY_AUTHOR":
        live = _live_activation(conn, task_id)

        # The retry already happened: its attempt is assigned or running.
        if live is not None and live["stage"] == "author":
            return (
                f"{task_id} already has a live author activation {live['activation_id']} "
                f"({live['agent']}, {live['status']}); nothing new was issued."
            )

        raise IngressRefused(
            f"{task_id} is {task['state']}; a retry is for a task in CHANGES_REQUESTED, "
            "or in READY_AUTHOR still waiting for its activation"
        )

    # No live-activation check here: issuing moves the task out of
    # READY_AUTHOR, so a task still in it has nothing live to duplicate.
    agent = author or previous["agent"]
    branch = _next_author_branch(conn, task_id)

    try:
        issued = activations.issue(
            conn, task_id=task_id, agent=agent, host=routing.host, stage="author",
            lease_seconds=routing.lease_seconds, hard_deadline_seconds=routing.hard_deadline_seconds,
            expected_branch=branch, repo_location=repo_location, now=now,
        )
    except activations.HostAtCapacity as exc:
        raise IngressRefused(
            f"{task_id} is READY_AUTHOR{' (retry authorised)' if authorised else ''}, but "
            f"{routing.host} is at capacity ({exc}); send the same retry again once a slot frees"
        )

    task = _task(conn, task_id)
    rationale = str((task.get("last_rejection") or {}).get("rationale") or "").strip()

    if len(rationale) > MAX_RATIONALE_SHOWN:
        rationale = rationale[:MAX_RATIONALE_SHOWN] + " [truncated]"

    return "\n".join([
        f"Retry of {task_id}" + (" authorised and" if authorised else "") + f" issued to {agent}",
        f"task:        {task_id} ({task['state']})",
        f"activation:  {issued['activation_id']}",
        f"branch:      {branch}",
        f"attempts:    {_author_attempts(conn, task_id)} of {engine.DEFAULT_AUTHOR_ATTEMPTS} used",
        "the author is given the last review's rationale:",
        *("  " + line for line in (rationale or "(none recorded)").split("\n")),
    ])


def cancel_code(task_id: str, state_seq: int, reason: str) -> str:
    """Binds a confirmation to the task, the state it was previewed in, and the reason."""
    return hashlib.sha256(f"{task_id}|{state_seq}|{reason}".encode("utf-8")).hexdigest()[:8]


def _reason(words: list) -> str:
    reason = " ".join(words).strip()

    if not reason:
        raise IngressRefused("a cancellation needs a reason: `@swarm cancel T-<id> <reason>`")

    if len(reason) > MAX_REASON:
        raise IngressRefused(f"the reason is longer than {MAX_REASON} characters")

    return reason


def _refuse_uncancellable(conn: sqlite3.Connection, task: dict) -> None:
    task_id = task["task_id"]

    if task["state"] in states.TERMINAL_STATES:
        raise IngressRefused(f"{task_id} is {task['state']}, which is terminal; nothing to cancel")

    live = _live_activation(conn, task_id)

    if live is not None:
        raise IngressRefused(
            f"{task_id} has a live {live['stage']} activation {live['activation_id']} "
            f"({live['agent']}, {live['status']}). Cancelling now could race work in flight -- "
            "an integration can still land. Send the cancel again once it has finished or its "
            "lease has expired."
        )


def _cancel_preview(task: dict, reason: str) -> str:
    code = cancel_code(task["task_id"], task["state_seq"], reason)
    return "\n".join([
        f"Cancel {task['task_id']}? Nothing has changed yet.",
        f"task:        {task['task_id']} ({task['state']}, state seq {task['state_seq']})",
        f"title:       {task.get('title') or ''}",
        f"reason:      {reason}",
        "",
        "Cancellation is terminal. To cancel, send exactly:",
        f"@swarm confirm-cancel {task['task_id']} {code} {reason}",
    ])


def preview_cancel(conn: sqlite3.Connection, task_id: str, reason: str) -> str:
    task = _task(conn, task_id)

    if task["state"] == "CANCELLED":
        return f"{task_id} is already CANCELLED; nothing changed."

    _refuse_uncancellable(conn, task)
    return _cancel_preview(task, reason)


def confirm_cancel(conn: sqlite3.Connection, task_id: str, code: str, reason: str, *,
                   sender: str, now: Optional[float] = None) -> str:
    """Apply a previewed cancellation, if nothing about it has changed.

    The check and the transition share one transaction, and the transition is
    pinned to the state sequence the code was made for, so work issued in
    between moves the sequence and the cancellation is refused.
    """
    now = time.time() if now is None else now

    with transaction(conn):
        task = _task(conn, task_id)

        if task["state"] == "CANCELLED":
            return f"{task_id} is already CANCELLED; nothing changed."

        _refuse_uncancellable(conn, task)

        if code != cancel_code(task_id, task["state_seq"], reason):
            raise IngressRefused(
                f"that confirmation does not match {task_id} as it is now, or its reason differs "
                "from the preview; nothing was cancelled.\n\n" + _cancel_preview(task, reason)
            )

        try:
            engine.apply_transition_within(
                conn, task_id=task_id, kind="admin_cancelled", actor=sender,
                authority=states.ADMIN, expected_state_seq=task["state_seq"],
                payload={"reason": reason}, now=now,
            )
        except states.TransitionRejected as exc:
            raise IngressRefused(f"the controller refused to cancel {task_id}: {exc}")

    return f"Cancelled {task_id} (was {task['state']}).\nreason:      {reason}"


def _lifecycle(conn: sqlite3.Connection, mention: str, word: str, tokens: list, *,
               sender: str, routing, now: Optional[float]) -> str:
    task_id = tokens[2] if len(tokens) >= 3 else ""

    if word == "retry":
        if len(tokens) != 3 or not TASK_ID_RE.match(task_id):
            raise IngressRefused(
                "a retry is exactly `@swarm retry T-<id>`, or `@ChatGPT retry T-<id>` / "
                "`@ClaudeCode retry T-<id>` to choose the author"
            )
        author = None if mention in PIPELINE_MENTIONS else AUTHOR_MENTIONS[mention]
        return retry(conn, task_id, author=author, sender=sender, routing=routing, now=now)

    if mention not in PIPELINE_MENTIONS:
        raise IngressRefused(f"{word} with `@swarm {word} T-<id> ...`")

    if not TASK_ID_RE.match(task_id):
        raise IngressRefused(f"`{word}` needs a task id: `@swarm {word} T-<id> ...`")

    if word == "cancel":
        return preview_cancel(conn, task_id, _reason(tokens[3:]))

    if len(tokens) < 4 or not CANCEL_CODE_RE.match(tokens[3]):
        raise IngressRefused("a confirmation is `@swarm confirm-cancel T-<id> <code> <reason>`, "
                             "exactly as the preview gave it")

    return confirm_cancel(conn, task_id, tokens[3], _reason(tokens[4:]), sender=sender, now=now)


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

        word = tokens[1].lower() if len(tokens) >= 2 else ""

        # One line, always. A task command is several lines, so a title that
        # happens to start with "retry" still drafts; a multi-line message
        # that names a task after the word is a lifecycle command malformed.
        if word in LIFECYCLE_WORDS:
            if "\n" not in text.strip():
                return _lifecycle(conn, mention, word, tokens, sender=sender, routing=routing, now=now)
            if len(tokens) >= 3 and TASK_ID_RE.match(tokens[2]):
                raise IngressRefused(f"`{word}` is a one-line command")

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
