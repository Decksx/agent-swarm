"""Database access for the controller.

Everything that writes authoritative state goes through `transaction()`. That
is not a style preference: §4 requires a projection update and its event append
to land in the same transaction, and the only way to make that hold in practice
is to have one obvious way to write.

Why `BEGIN IMMEDIATE` and not SQLite's default
----------------------------------------------

Python's sqlite3 opens a deferred transaction, which takes a write lock only at
the first write. Two readers can therefore both start, both decide to write,
and the second gets `SQLITE_BUSY` at commit time — after it has already read
the state it based its decision on. `BEGIN IMMEDIATE` takes the write lock up
front, so a conflicting writer is refused before it reads rather than after it
has computed a transition against state that has since moved.

That matters most for exactly the operations this controller performs:
read a task's `state_seq`, decide whether a transition is legal, write it.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schema import EXPECTED_TABLES, SCHEMA_SQL, SCHEMA_VERSION


class SchemaVersionMismatch(RuntimeError):
    """The database on disk is not the schema this build understands."""


def connect(path: str | Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Open the controller database with the pragmas it depends on.

    `timeout` is how long a writer waits for a competing write lock before
    raising. It is deliberately generous: the alternative to waiting is an
    operation failing under momentary contention, and every write here is
    short.
    """
    conn = sqlite3.connect(
        str(path),
        timeout=timeout,
        # Transactions are opened explicitly by transaction(); autocommit
        # mode here means sqlite3 does not start a deferred one behind our back.
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row

    # Foreign keys are OFF by default in SQLite. Without this every REFERENCES
    # clause in schema.py is a comment.
    conn.execute("PRAGMA foreign_keys = ON")

    # WAL lets readers run while a write is in progress, which is what keeps a
    # status query from blocking behind a transition.
    conn.execute("PRAGMA journal_mode = WAL")

    # FULL rather than NORMAL: NORMAL can lose the last commits on power loss,
    # and a task recorded as COMPLETE that is not actually complete is exactly
    # the failure this system is built to prevent.
    conn.execute("PRAGMA synchronous = FULL")

    return conn


def split_statements(sql: str) -> list:
    """Split `sql` into executable statements.

    Comments are stripped before splitting rather than after. That is not
    tidiness: the prose in schema.py contains semicolons -- "the event log can
    rebuild; `state_seq` increments" -- and splitting the raw text on ";" cuts
    such a comment in half, leaving its second line to be executed as SQL. That
    failed as a syntax error on the first run, which was the good outcome; the
    bad one is a comment that happens to split into something executable.

    Sound for this SQL because no string literal in it contains "--" or ";".
    The CHECK constraints hold literals like 'baseline' and 'stdout', none of
    which do. It is not a general-purpose SQL parser and should not be used as
    one.
    """
    without_comments = "\n".join(
        line.split("--", 1)[0] for line in sql.splitlines()
    )

    return [s.strip() for s in without_comments.split(";") if s.strip()]


def initialize(conn: sqlite3.Connection) -> None:
    """Create the schema if absent, and stamp its version.

    Safe to call on an already-initialized database: every statement is
    `IF NOT EXISTS`, and the version is only written when it is currently 0.
    """
    with transaction(conn):
        # Statement at a time, not executescript(). executescript() issues an
        # implicit COMMIT before it runs, which silently ends the transaction
        # opened above and leaves schema creation half-committed on failure.
        for statement in split_statements(SCHEMA_SQL):
            conn.execute(statement)

        current = conn.execute("PRAGMA user_version").fetchone()[0]

        if current == 0:
            # PRAGMA does not accept a bound parameter, and SCHEMA_VERSION is
            # an int constant from this package rather than anything a caller
            # supplies, so interpolating it is not an injection path.
            conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")


def check_schema_version(conn: sqlite3.Connection) -> int:
    """Return the on-disk schema version, or refuse to run against it.

    §17 requires startup to fail closed when it meets state it does not
    understand. An older build opening a newer database, or the reverse, would
    otherwise apply half-matching SQL to real task state and produce a
    corruption that only shows up later, as a task in an impossible state.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version != SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"database schema version {version} is not {SCHEMA_VERSION}; "
            f"refusing to run. An explicit, tested migration is required."
        )

    return version


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside one `BEGIN IMMEDIATE` transaction.

    Commits on success, rolls back on any exception. Nested use is a bug and
    raises rather than silently joining the outer transaction, because a caller
    that believes it has its own transaction would see its rollback quietly
    become a no-op and its half-written state committed by the outer block.
    """
    if conn.in_transaction:
        raise RuntimeError(
            "nested transaction: this block would commit as part of its "
            "caller's transaction, so its rollback would not roll anything back"
        )

    conn.execute("BEGIN IMMEDIATE")

    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    conn.execute("COMMIT")


def open_controller_db(path: str | Path) -> sqlite3.Connection:
    """Open, initialize if needed, and verify. The normal entry point."""
    conn = connect(path)
    initialize(conn)
    check_schema_version(conn)

    return conn


def table_names(conn: sqlite3.Connection) -> set:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()

    return {row["name"] for row in rows}


def missing_tables(conn: sqlite3.Connection) -> set:
    return set(EXPECTED_TABLES) - table_names(conn)
