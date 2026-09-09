"""The controller's storage layer: schema, pragmas, and transaction semantics.

These are the foundations everything else in Phase 1 rests on, and each one
fails in a way that is hard to diagnose later. A missing `PRAGMA foreign_keys`
turns every `REFERENCES` clause into a comment; a deferred transaction lets two
writers each compute a transition from state the other has already moved; a
schema mismatch applies half-matching SQL to real task state. None of those
announce themselves — they surface much later as a task in an impossible state.

So they are asserted directly rather than assumed from the fact that a write
succeeded.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from controller import db as controller_db
from controller.schema import EXPECTED_TABLES, SCHEMA_SQL, SCHEMA_VERSION


@pytest.fixture
def conn(tmp_path):
    connection = controller_db.open_controller_db(tmp_path / "controller.db")
    yield connection
    connection.close()


# --- Schema -----------------------------------------------------------------


def test_every_expected_table_is_created(conn):
    assert controller_db.missing_tables(conn) == set()


def test_table_list_is_not_silently_derived_from_the_sql():
    """EXPECTED_TABLES is maintained separately on purpose.

    Deriving it by parsing SCHEMA_SQL would make the check vacuous: a table
    accidentally deleted from the SQL would also vanish from the expectation,
    and the test would keep passing. This asserts the two agree, which only
    means something because they are written down independently.
    """
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table} " in SCHEMA_SQL


def test_initialize_is_idempotent(tmp_path):
    path = tmp_path / "controller.db"

    first = controller_db.open_controller_db(path)
    first.execute(
        "INSERT INTO tasks (task_id, title, objective, current_version, "
        "state, created_at, created_by) VALUES (?,?,?,?,?,?,?)",
        ("T-1", "t", "o", 1, "DRAFT", time.time(), "admin"),
    )
    first.close()

    # Re-opening must not recreate or clear anything.
    second = controller_db.open_controller_db(path)
    assert second.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    second.close()


def test_a_wrong_schema_version_refuses_to_open(tmp_path):
    """§17: startup fails closed against state it does not understand."""
    path = tmp_path / "controller.db"
    conn = controller_db.open_controller_db(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 99}")
    conn.close()

    with pytest.raises(controller_db.SchemaVersionMismatch):
        controller_db.open_controller_db(path)


# --- Pragmas ----------------------------------------------------------------


def test_foreign_keys_are_enforced(conn):
    """Off by default in SQLite, so this is a real setting and not a given."""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task_versions (task_id, version, contract_yaml, "
            "contract_hash, protocol_schema_version, base_sha, proof_mode, "
            "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            ("NO-SUCH-TASK", 1, "y", "h", 7, "0" * 40, "baseline", 1.0, "admin"),
        )


def test_wal_and_full_synchronous_are_set(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    # 2 == FULL. NORMAL can lose the last commits on power loss, and a task
    # recorded COMPLETE that is not complete is the failure mode this system
    # exists to prevent.
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2


# --- Transactions -----------------------------------------------------------


def _insert_task(conn, task_id="T-1"):
    conn.execute(
        "INSERT INTO tasks (task_id, title, objective, current_version, "
        "state, created_at, created_by) VALUES (?,?,?,?,?,?,?)",
        (task_id, "t", "o", 1, "DRAFT", time.time(), "admin"),
    )


def test_a_transaction_commits_on_success(conn):
    with controller_db.transaction(conn):
        _insert_task(conn)

    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_a_transaction_rolls_back_on_any_exception(conn):
    """The projection and its event must land together or not at all.

    A task whose state moved without an event, or the reverse, cannot be
    reconstructed afterwards — the event log is both the audit trail and the
    recovery mechanism.
    """
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with controller_db.transaction(conn):
            _insert_task(conn)
            raise Boom

    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_a_transaction_is_immediate_not_deferred(conn):
    """The write lock is taken when the block opens, not at first write.

    A deferred transaction lets two callers both read a task's state_seq,
    both decide a transition is legal, and only then collide — after each has
    computed its decision against state the other has already moved. Asserted
    by observing that a second connection cannot write while the block is open
    and has written nothing yet.
    """
    other = controller_db.connect(conn.execute("PRAGMA database_list").fetchone()[2], timeout=0.1)

    with controller_db.transaction(conn):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")

    other.close()


def test_nesting_a_transaction_is_refused(conn):
    """Silently joining the outer transaction would make rollback a lie.

    The inner block's caller believes its failure undoes its own writes. If it
    joined the outer transaction, its rollback would do nothing and the outer
    block would commit the half-written state.
    """
    with controller_db.transaction(conn):
        with pytest.raises(RuntimeError, match="nested"):
            with controller_db.transaction(conn):
                pass


# --- Constraints that encode protocol rules ---------------------------------


def test_priority_is_bounded(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks (task_id, title, objective, priority, "
            "current_version, state, created_at, created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("T-bad", "t", "o", 101, 1, "DRAFT", 1.0, "admin"),
        )


def test_proof_mode_is_restricted_to_the_declared_strategies(conn):
    """§10: the strategy is chosen before validation, never invented later."""
    _insert_task(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task_versions (task_id, version, contract_yaml, "
            "contract_hash, protocol_schema_version, base_sha, proof_mode, "
            "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            ("T-1", 1, "y", "h", 7, "0" * 40, "whatever-passes", 1.0, "admin"),
        )


def test_a_task_cannot_depend_on_itself(conn):
    _insert_task(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task_deps (task_id, depends_on, kind) VALUES (?,?,?)",
            ("T-1", "T-1", "blocks"),
        )


def test_event_ids_are_unique(conn):
    """A retried append must not be able to duplicate an event."""
    _insert_task(conn)
    conn.execute(
        "INSERT INTO task_versions (task_id, version, contract_yaml, "
        "contract_hash, protocol_schema_version, base_sha, proof_mode, "
        "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
        ("T-1", 1, "y", "h", 7, "0" * 40, "baseline", 1.0, "admin"),
    )

    row = ("E-1", "T-1", 1, "admin", "admin", "queued", "{}", 1.0)
    sql = (
        "INSERT INTO events (event_id, task_id, task_version, actor, authority, "
        "kind, payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)"
    )
    conn.execute(sql, row)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, row)


def test_retention_class_and_stream_kind_are_restricted(conn):
    """§9: retention belongs to the reference, from a closed set of classes."""
    for column, value in (("stream_kind", "sideband"), ("retention_class", "forever")):
        assert f"CHECK ({column} IN (" in SCHEMA_SQL, column
        assert value not in SCHEMA_SQL


# --- The statement splitter -------------------------------------------------


def test_the_splitter_survives_a_semicolon_inside_a_comment():
    """Regression: this exact case broke schema creation on the first run.

    schema.py contains the comment "the event log can rebuild; `state_seq`
    increments", and splitting the raw text on ";" cut it in half, leaving the
    remainder to be executed as SQL. It failed loudly as a syntax error, which
    was luck — a comment that split into something executable would not have.
    """
    sql = (
        "-- a comment; with a semicolon in it\n"
        "CREATE TABLE a (x INTEGER);\n"
        "CREATE TABLE b (y INTEGER);\n"
    )

    statements = controller_db.split_statements(sql)

    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert statements[1].startswith("CREATE TABLE b")


def test_the_splitter_returns_every_schema_statement():
    statements = controller_db.split_statements(SCHEMA_SQL)

    assert len(statements) == len(EXPECTED_TABLES) + 5      # tables + indexes
    assert all(s.strip() for s in statements)
