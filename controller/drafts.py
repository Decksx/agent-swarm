"""Task drafts: proposed tasks held for confirmation before anything acts on them.

A draft is storage and validation only. Nothing here reads the chatroom and
nothing here creates a task. What a draft buys is a fixed thing to say yes to:
its hash is computed from its content, a confirmation names the hash it is
confirming, and the confirmation is refused unless that is still the hash
stored. Whatever later turns a confirmed draft into a task is acting on content
somebody actually saw, not on whatever the row happened to hold by then.

Why the comparison and the write share a transaction
----------------------------------------------------

`confirm_draft` is a compare-and-swap, and a compare-and-swap that is not
atomic is a compare. Read the hash, commit, then mark the row confirmed in a
second transaction, and a writer that lands between the two gets its content
confirmed under a hash that described something else. Both happen inside one
`BEGIN IMMEDIATE` transaction via `db.transaction`, which takes the write lock
before the read, so a competing writer is refused rather than interleaved.

Why there is no ledger event
----------------------------

Every write in `engine.py` appends an event with its projection update, and
this module does not. That is not an exception to the rule so much as a place
it cannot yet apply: `events` has a foreign key onto `(task_id, task_version)`,
and a draft is precisely the thing that exists before there is a task to point
at. The row carries its own `confirmed_at` instead.

The table is created by `create_drafts_table`, not by `schema.SCHEMA_SQL`.
Wiring it into the migration chain is a separate step; until then this is the
one statement that defines it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Mapping, Optional

from .db import transaction

PENDING = "pending"
CONFIRMED = "confirmed"

DRAFTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_drafts (
  draft_id      TEXT PRIMARY KEY,
  content_json  TEXT NOT NULL,
  draft_hash    TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('pending', 'confirmed')),
  created_at    REAL NOT NULL,
  created_by    TEXT NOT NULL,
  confirmed_at  REAL
)
"""

# Selected by name and read by position, so that a row is the same dict whether
# the connection hands back tuples or `sqlite3.Row`. `dict(row)` works only on
# the second, and a module that silently required it would fail on the first
# plain connection anybody opened.
DRAFT_COLUMNS = (
    "draft_id",
    "content_json",
    "draft_hash",
    "status",
    "created_at",
    "created_by",
    "confirmed_at",
)

_SELECT_DRAFT = (
    "SELECT " + ", ".join(DRAFT_COLUMNS) + " FROM task_drafts WHERE draft_id = ?"
)


class DraftRejected(Exception):
    """A confirmation the stored draft does not authorise."""


class DraftNotFound(DraftRejected):
    """No draft is stored under the given id."""


class DraftHashMismatch(DraftRejected):
    """The caller confirmed a hash that is not the one stored.

    Either the caller is looking at an older version of the draft or it never
    saw this draft at all. In both cases the confirmation is not about the
    stored content and must not be applied to it.
    """

    def __init__(self, draft_id: str, expected_hash: str, stored_hash: str):
        self.draft_id = draft_id
        self.expected_hash = expected_hash
        self.stored_hash = stored_hash
        super().__init__(
            f"draft {draft_id!r} hash mismatch: confirmation expected "
            f"{expected_hash!r}, stored hash is {stored_hash!r}"
        )


class DraftAlreadyConfirmed(DraftRejected):
    """A confirmation authorises one transition, pending to confirmed.

    Accepting it again would restamp `confirmed_at` and let a replayed
    confirmation look like a fresh decision.
    """


def create_drafts_table(conn: sqlite3.Connection) -> None:
    """Create `task_drafts` if it does not exist.

    Idempotent: a second call against the same database is a no-op and leaves
    every existing row where it was.
    """
    with transaction(conn):
        conn.execute(DRAFTS_TABLE_SQL)


def canonical_content(content: Mapping) -> str:
    """The one serialisation a draft's content is stored and hashed as.

    Keys sorted and separators fixed, so two mappings with the same content
    serialise identically regardless of the order they were built in.
    """
    if not isinstance(content, Mapping):
        raise TypeError(
            f"draft content must be a mapping, not {type(content).__name__}"
        )

    return json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def draft_hash(content: Mapping) -> str:
    """Stable identity for a draft's content."""
    return hashlib.sha256(canonical_content(content).encode("utf-8")).hexdigest()


def _row_to_draft(row) -> dict:
    draft = dict(zip(DRAFT_COLUMNS, row))
    draft["content"] = json.loads(draft["content_json"])

    return draft


def create_draft(
    conn: sqlite3.Connection,
    content: Mapping,
    *,
    created_by: str,
    draft_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict:
    """Store a draft as pending and return it as stored."""
    now = time.time() if now is None else now
    draft_id = draft_id or uuid.uuid4().hex
    content_json = canonical_content(content)
    digest = draft_hash(content)

    with transaction(conn):
        conn.execute(
            "INSERT INTO task_drafts (draft_id, content_json, draft_hash, "
            "status, created_at, created_by) VALUES (?,?,?,?,?,?)",
            (draft_id, content_json, digest, PENDING, now, created_by),
        )
        stored = conn.execute(_SELECT_DRAFT, (draft_id,)).fetchone()

    return _row_to_draft(stored)


def ensure_draft(
    conn: sqlite3.Connection,
    content: Mapping,
    *,
    draft_id: str,
    created_by: str,
    now: Optional[float] = None,
) -> tuple:
    """Store a draft under `draft_id` unless it exists; return (draft, created).

    For callers whose id is derived from the content, so a repeated submission
    of the same content must land on the same row instead of adding a second
    one. An existing row with a different hash is refused, never overwritten:
    two different contents under one id means the id did not identify them.
    """
    now = time.time() if now is None else now
    content_json = canonical_content(content)
    digest = draft_hash(content)

    with transaction(conn):
        inserted = conn.execute(
            "INSERT OR IGNORE INTO task_drafts (draft_id, content_json, "
            "draft_hash, status, created_at, created_by) VALUES (?,?,?,?,?,?)",
            (draft_id, content_json, digest, PENDING, now, created_by),
        ).rowcount
        stored = conn.execute(_SELECT_DRAFT, (draft_id,)).fetchone()

    draft = _row_to_draft(stored)

    if draft["draft_hash"] != digest:
        raise DraftHashMismatch(draft_id, digest, draft["draft_hash"])

    return draft, bool(inserted)


def get_draft(conn: sqlite3.Connection, draft_id: str) -> dict:
    stored = conn.execute(_SELECT_DRAFT, (draft_id,)).fetchone()

    if stored is None:
        raise DraftNotFound(draft_id)

    return _row_to_draft(stored)


def _check_draft(
    conn: sqlite3.Connection, draft_id: str, expected_hash: str
) -> None:
    """Refuse unless the stored draft is pending under `expected_hash`."""
    found = conn.execute(
        "SELECT draft_hash, status FROM task_drafts WHERE draft_id = ?",
        (draft_id,),
    ).fetchone()

    if found is None:
        raise DraftNotFound(draft_id)

    stored_hash, status = found[0], found[1]

    if stored_hash != expected_hash:
        raise DraftHashMismatch(draft_id, expected_hash, stored_hash)

    if status != PENDING:
        raise DraftAlreadyConfirmed(
            f"draft {draft_id!r} is {status!r}, not {PENDING!r}"
        )


def _mark_confirmed(conn: sqlite3.Connection, draft_id: str, now: float) -> None:
    conn.execute(
        "UPDATE task_drafts SET status = ?, confirmed_at = ? WHERE draft_id = ?",
        (CONFIRMED, now, draft_id),
    )


def confirm_draft(
    conn: sqlite3.Connection,
    draft_id: str,
    expected_hash: str,
    *,
    now: Optional[float] = None,
) -> dict:
    """Confirm a pending draft, provided its stored hash is `expected_hash`.

    Raises `DraftHashMismatch` on inequality, `DraftAlreadyConfirmed` if the
    draft is no longer pending and `DraftNotFound` if there is no such draft;
    every refusal happens before the write, and the transaction is rolled back,
    so a refused confirmation leaves the row exactly as it was.

    The returned draft is read back inside the same transaction as the write,
    so what it reports is what was committed rather than what was intended.
    """
    now = time.time() if now is None else now

    with transaction(conn):
        _check_draft(conn, draft_id, expected_hash)
        _mark_confirmed(conn, draft_id, now)
        confirmed = conn.execute(_SELECT_DRAFT, (draft_id,)).fetchone()

    return _row_to_draft(confirmed)
