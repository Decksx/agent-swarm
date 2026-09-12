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


def connect(
    path: str | Path,
    *,
    timeout: float = 10.0,
    same_thread_only: bool = True,
) -> sqlite3.Connection:
    """Open the controller database with the pragmas it depends on.

    `timeout` is how long a writer waits for a competing write lock before
    raising. It is deliberately generous: the alternative to waiting is an
    operation failing under momentary contention, and every write here is
    short.

    `same_thread_only` keeps SQLite's own thread-affinity guard, and defaults
    to on. Every caller outside the HTTP layer opens a connection and uses it
    on the thread that opened it, and for those the guard is free insurance
    against a connection escaping into a thread nobody meant it to reach.

    The one caller that turns it off is the request-scoped connection FastAPI
    manages; `api.get_conn` says why. Turning it off is emphatically not a
    claim that the connection is safe to *share* -- see that note.
    """
    conn = sqlite3.connect(
        str(path),
        timeout=timeout,
        # Transactions are opened explicitly by transaction(); autocommit
        # mode here means sqlite3 does not start a deferred one behind our back.
        isolation_level=None,
        check_same_thread=same_thread_only,
    )
    conn.row_factory = sqlite3.Row

    # Foreign keys are OFF by default in SQLite. Without this every REFERENCES
    # clause in schema.py is a comment.
    conn.execute("PRAGMA foreign_keys = ON")

    # WAL lets readers run while a write is in progress, which is what keeps a
    # status query from blocking behind a transition.
    #
    # Set only when it is not already set. Changing `journal_mode` takes a
    # brief exclusive lock, and this runs on every connection open -- which
    # the HTTP layer does once per request. Concurrent opens then collide and
    # one of them fails the *connect* with "database is locked", producing a
    # 500 that has nothing to do with the work it was about to do. Reading the
    # mode first costs one shared-lock query and makes the common case -- an
    # existing WAL database -- take no write lock at all.
    if (conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower() != "wal":
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


# Ordered, additive migrations keyed by the version they produce.
#
# Additive only, deliberately. A column added with a NULL default cannot
# invalidate a row that already exists, so an interrupted migration leaves a
# database that is either wholly at the old version or wholly at the new one --
# and the version stamp is written in the same transaction as the ALTERs, so
# there is no state where the schema has moved and the stamp has not.
#
# Anything that is not additive -- dropping a column, changing a type,
# backfilling a NOT NULL -- does not belong here. It needs its own tested
# procedure and a backup taken first, which is what section 17 means by an
# explicit migration.
MIGRATIONS = {
    # Additive and nullable, like the migrations below it. NULL is correct for
    # every existing row: no activation in the deployed database was issued
    # while an operator response was outstanding, and inventing one would put
    # words in the operator's mouth.
    #
    # A callable rather than a bare ALTER so that it can be run twice. The
    # version bump is a separate transaction from the step, so a crash between
    # them leaves the column added and the version unchanged -- and the next
    # startup would re-run an ALTER that now fails on its own success,
    # wedging a controller that had actually migrated correctly.
    5: lambda conn: _add_operator_context(conn),
    2: [
        "ALTER TABLE activations ADD COLUMN expected_candidate TEXT",
        "ALTER TABLE activations ADD COLUMN repo_location TEXT",
    ],
    # Additive and non-destructive: one nullable column. Existing rows get
    # NULL, which is correct for every one of them -- no task in the deployed
    # database was approved under a rule that recorded which candidate the
    # approval was for, and writing a value in for them would manufacture an
    # approval nobody gave. A NULL here means the integrator refuses, which is
    # the right behaviour for a task whose approval predates the record of it.
    3: [
        "ALTER TABLE tasks ADD COLUMN approved_candidate_sha TEXT",
    ],
    # A rebuild rather than statements, because SQLite has no way to alter a
    # CHECK constraint and three tables reference this one.
    4: lambda conn: _widen_proof_mode(conn),
}


# The vocabulary after migration 4. `branch_only` is a real proof mode and not
# a flag bolted on beside one: it says how a task's result is to be
# demonstrated, and "the candidate stays on its branch" is an answer to that
# question in the same way "baseline" and "sabotage" are.
PROOF_MODES = ("baseline", "sabotage", "both", "branch_only")


def _add_operator_context(conn: sqlite3.Connection) -> None:
    """Add `activations.operator_context` unless it is already there.

    Asked of the table rather than assumed from the version, because the
    version is exactly what is not yet true when this runs.
    """
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(activations)")
    }

    if "operator_context" in columns:
        return

    with transaction(conn):
        conn.execute("ALTER TABLE activations ADD COLUMN operator_context TEXT")


def _widen_proof_mode(conn: sqlite3.Connection) -> None:
    """Rebuild `task_versions` so `proof_mode` may be `branch_only`.

    The documented SQLite procedure for changing a constraint, and every part
    of it is load-bearing:

    * foreign keys OFF around the whole thing, because three tables reference
      `task_versions` and `DROP TABLE` with enforcement on is an implicit
      delete of every row they point at;
    * the pragma outside the transaction, where it is not a no-op;
    * `foreign_key_check` afterwards, because turning enforcement off means
      nothing was checking during the rebuild and the only honest way to know
      the result is consistent is to ask.

    Idempotent. The version bump is a separate transaction, so a crash between
    the two leaves this applied and unversioned, and running it again on an
    already-widened table copies the same rows into a fresh one.
    """
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        with transaction(conn):
            conn.execute("DROP TABLE IF EXISTS task_versions_rebuild")
            conn.execute(
                "CREATE TABLE task_versions_rebuild ("
                "  task_id                 TEXT NOT NULL REFERENCES tasks(task_id),"
                "  version                 INTEGER NOT NULL,"
                "  contract_yaml           TEXT NOT NULL,"
                "  contract_hash           TEXT NOT NULL,"
                "  protocol_schema_version INTEGER NOT NULL,"
                "  base_sha                TEXT NOT NULL,"
                "  proof_mode              TEXT NOT NULL"
                "    CHECK (proof_mode IN "
                "      ('baseline', 'sabotage', 'both', 'branch_only')),"
                "  created_at              REAL NOT NULL,"
                "  created_by              TEXT NOT NULL,"
                "  PRIMARY KEY (task_id, version)"
                ")"
            )
            conn.execute(
                "INSERT INTO task_versions_rebuild "
                "(task_id, version, contract_yaml, contract_hash, "
                " protocol_schema_version, base_sha, proof_mode, created_at, "
                " created_by) "
                "SELECT task_id, version, contract_yaml, contract_hash, "
                "       protocol_schema_version, base_sha, proof_mode, "
                "       created_at, created_by FROM task_versions"
            )
            conn.execute("DROP TABLE task_versions")
            conn.execute(
                "ALTER TABLE task_versions_rebuild RENAME TO task_versions"
            )

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()

        if violations:
            raise SchemaVersionMismatch(
                f"rebuilding task_versions left {len(violations)} foreign key "
                "violation(s); refusing to report the migration as applied"
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def migrate(conn: sqlite3.Connection) -> int:
    """Bring an existing database up to SCHEMA_VERSION. Returns the version.

    A fresh database is created at the current version by `initialize` and
    never passes through here. An older one is stepped forward one version at
    a time, each step in its own transaction, so a failure at step N leaves
    the database consistently at N-1 rather than somewhere between.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version == 0 or version == SCHEMA_VERSION:
        return version

    if version > SCHEMA_VERSION:
        # Fail closed rather than guess. A newer database opened by an older
        # build is exactly the case that produces a corruption which only
        # shows up later.
        raise SchemaVersionMismatch(
            f"database is at schema version {version}, newer than this "
            f"build's {SCHEMA_VERSION}; refusing to downgrade"
        )

    while version < SCHEMA_VERSION:
        target = version + 1
        step = MIGRATIONS.get(target)

        if step is None:
            raise SchemaVersionMismatch(
                f"no migration to schema version {target}; refusing to run"
            )

        if callable(step):
            # A step that cannot be expressed as statements inside one
            # transaction. SQLite cannot alter a CHECK constraint, so widening
            # one means rebuilding the table -- and dropping a table three
            # others reference needs `PRAGMA foreign_keys=OFF`, which is a
            # no-op inside a transaction.
            #
            # The callable manages that itself and must be idempotent: the
            # version bump below is a separate transaction, so a crash between
            # the two leaves the rebuild applied and the version unchanged,
            # and the next startup runs it again.
            step(conn)

            with transaction(conn):
                conn.execute(f"PRAGMA user_version = {int(target)}")
        else:
            with transaction(conn):
                for statement in step:
                    conn.execute(statement)

                conn.execute(f"PRAGMA user_version = {int(target)}")

        version = target

    return version


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


def open_controller_db(
    path: str | Path, *, same_thread_only: bool = True
) -> sqlite3.Connection:
    """Open, initialize if needed, and verify. The normal entry point.

    `same_thread_only` is passed through to `connect` and defaults to the safe
    value, so a caller has to ask for the guard to be dropped rather than
    inherit that from here.
    """
    conn = connect(path, same_thread_only=same_thread_only)
    initialize(conn)
    # Between the two: initialize() creates a fresh database already stamped
    # at the current version and leaves an existing one alone, so migrate()
    # is what moves an older one forward, and check_schema_version() is the
    # assertion that one of those two things actually happened.
    migrate(conn)
    check_schema_version(conn)

    return conn


def table_names(conn: sqlite3.Connection) -> set:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()

    return {row["name"] for row in rows}


def missing_tables(conn: sqlite3.Connection) -> set:
    return set(EXPECTED_TABLES) - table_names(conn)
