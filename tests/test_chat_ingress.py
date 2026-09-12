"""Task drafts: table creation, content hashing, and CAS confirmation.

Every test takes the drafts module as an argument rather than importing names
out of it, and creates the table by calling that module. Both are deliberate.
The table is what is under test, so a test that built it for itself would be
proving its own SQL rather than the module's; and taking the module as an
argument is what lets `test_chat_ingress_bypass.py` run these same tests
against a copy with one guard removed and show that a named test fails.

Connections are opened here with nothing but the stdlib -- no `db.connect`,
no row factory unless a test asks for one -- because the module has to work on
the connection a caller actually has.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from controller import db as controller_db
from controller import drafts as drafts_module

DRAFTS_SOURCE = Path(drafts_module.__file__)

CONTENT = {
    "title": "Add a drafts table",
    "objective": "Store proposed tasks until someone confirms them.",
    "allowed_paths": ["controller/drafts.py"],
}


def make_conn(path, row_factory=None) -> sqlite3.Connection:
    """A plain stdlib connection, optionally with a row factory.

    WAL so that a reader never blocks a writer's commit: the interleaving test
    needs a refused write to mean "the confirmation holds the write lock" and
    nothing else.
    """
    conn = sqlite3.connect(str(path))

    if row_factory is not None:
        conn.row_factory = row_factory

    conn.execute("PRAGMA journal_mode = WAL")

    return conn


@pytest.fixture
def drafts():
    return drafts_module


@pytest.fixture(params=["plain", "row"])
def conn(request, tmp_path):
    connection = make_conn(
        tmp_path / "drafts.db",
        sqlite3.Row if request.param == "row" else None,
    )
    yield connection
    connection.close()


def snapshot(conn) -> list:
    """Every row of task_drafts, as plain tuples, in a fixed order."""
    return [
        tuple(row)
        for row in conn.execute("SELECT * FROM task_drafts ORDER BY draft_id")
    ]


def table_sql(conn) -> list:
    return [
        row[0]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'task_drafts'"
        )
    ]


# --- The table ----------------------------------------------------------------


def test_the_table_comes_from_the_module(drafts, conn):
    assert table_sql(conn) == []

    drafts.create_drafts_table(conn)

    assert len(table_sql(conn)) == 1
    assert "CREATE TABLE IF NOT EXISTS task_drafts" in DRAFTS_SOURCE.read_text(
        encoding="utf-8"
    )


def test_create_drafts_table_twice_keeps_rows(drafts, conn):
    drafts.create_drafts_table(conn)
    drafts.create_draft(conn, CONTENT, created_by="operator", draft_id="d1")
    drafts.create_draft(
        conn, {"title": "second"}, created_by="operator", draft_id="d2"
    )
    rows_before = snapshot(conn)
    sql_before = table_sql(conn)

    drafts.create_drafts_table(conn)

    assert snapshot(conn) == rows_before
    assert table_sql(conn) == sql_before
    assert len(rows_before) == 2


# --- The hash -----------------------------------------------------------------


def test_hash_is_stable_and_ignores_key_order(drafts, conn):
    reordered = dict(reversed(list(CONTENT.items())))

    assert list(reordered) != list(CONTENT)
    assert drafts.draft_hash(CONTENT) == drafts.draft_hash(CONTENT)
    assert drafts.draft_hash(reordered) == drafts.draft_hash(CONTENT)
    assert drafts.draft_hash({**CONTENT, "title": "other"}) != drafts.draft_hash(
        CONTENT
    )

    drafts.create_drafts_table(conn)
    first = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="a")
    second = drafts.create_draft(conn, reordered, created_by="op", draft_id="b")

    assert first["draft_hash"] == drafts.draft_hash(CONTENT)
    assert second["draft_hash"] == first["draft_hash"]
    assert first["content"] == CONTENT
    # Recomputed from what was stored, not from what was passed in.
    assert drafts.draft_hash(first["content"]) == first["draft_hash"]


def test_content_must_be_a_mapping(drafts, conn):
    drafts.create_drafts_table(conn)

    with pytest.raises(TypeError):
        drafts.create_draft(conn, ["not", "a", "mapping"], created_by="op")

    assert snapshot(conn) == []


# --- Confirmation -------------------------------------------------------------


def test_matching_hash_confirms(drafts, conn):
    drafts.create_drafts_table(conn)
    draft = drafts.create_draft(
        conn, CONTENT, created_by="op", draft_id="d1", now=100.0
    )

    assert draft["status"] == drafts.PENDING
    assert draft["confirmed_at"] is None

    result = drafts.confirm_draft(conn, "d1", draft["draft_hash"], now=200.0)

    assert result["status"] == drafts.CONFIRMED
    assert result["confirmed_at"] == 200.0
    assert result["draft_hash"] == draft["draft_hash"]
    assert drafts.get_draft(conn, "d1") == result
    assert not conn.in_transaction


def test_hash_mismatch_raises_and_changes_nothing(drafts, conn):
    drafts.create_drafts_table(conn)
    draft = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="d1")
    drafts.create_draft(conn, {"title": "other"}, created_by="op", draft_id="d2")
    before = snapshot(conn)
    wrong = drafts.draft_hash({**CONTENT, "title": "edited"})

    with pytest.raises(drafts.DraftHashMismatch) as caught:
        drafts.confirm_draft(conn, "d1", wrong, now=200.0)

    message = str(caught.value)
    assert "mismatch" in message
    assert wrong in message
    assert draft["draft_hash"] in message
    assert snapshot(conn) == before
    assert drafts.get_draft(conn, "d1")["status"] == drafts.PENDING
    assert not conn.in_transaction


def test_confirmed_draft_cannot_be_confirmed_again(drafts, conn):
    drafts.create_drafts_table(conn)
    draft = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="d1")
    drafts.confirm_draft(conn, "d1", draft["draft_hash"], now=200.0)
    before = snapshot(conn)

    with pytest.raises(drafts.DraftAlreadyConfirmed):
        drafts.confirm_draft(conn, "d1", draft["draft_hash"], now=300.0)

    assert snapshot(conn) == before
    assert drafts.get_draft(conn, "d1")["confirmed_at"] == 200.0


def test_confirming_a_missing_draft_raises(drafts, conn):
    drafts.create_drafts_table(conn)
    draft = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="d1")
    before = snapshot(conn)

    with pytest.raises(drafts.DraftNotFound):
        drafts.confirm_draft(conn, "missing", draft["draft_hash"])

    with pytest.raises(drafts.DraftNotFound):
        drafts.get_draft(conn, "missing")

    assert snapshot(conn) == before
    assert not conn.in_transaction


class InterleavingConnection:
    """A connection that lets another writer try to cut in.

    Once the draft has been read, every further statement is preceded by an
    attempt from a second connection to rewrite the draft's content and hash.
    If the read and the write share a transaction, every attempt is refused
    because the write lock is already held. If they do not, one lands in the
    gap.
    """

    def __init__(self, conn, interloper):
        self._conn = conn
        self._interloper = interloper
        self._armed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        if self._armed:
            self._interloper()

        cursor = self._conn.execute(sql, params)

        if sql.lstrip().upper().startswith("SELECT") and "task_drafts" in sql:
            self._armed = True

        return cursor


def test_interleaved_writer_cannot_cut_between_compare_and_swap(drafts, conn):
    drafts.create_drafts_table(conn)
    draft = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="d1")
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    edited = {**CONTENT, "objective": "Something nobody confirmed."}
    outcome = {"refused": 0, "written": False}

    def interloper():
        if outcome["written"]:
            return

        other = sqlite3.connect(path, timeout=0, isolation_level=None)

        try:
            try:
                other.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                outcome["refused"] += 1
                return

            other.execute(
                "UPDATE task_drafts SET content_json = ?, draft_hash = ? "
                "WHERE draft_id = ?",
                (drafts.canonical_content(edited), drafts.draft_hash(edited), "d1"),
            )
            other.execute("COMMIT")
            outcome["written"] = True
        finally:
            other.close()

    drafts.confirm_draft(
        InterleavingConnection(conn, interloper), "d1", draft["draft_hash"]
    )

    stored = drafts.get_draft(conn, "d1")
    assert outcome["refused"] >= 1
    assert outcome["written"] is False
    assert stored["status"] == drafts.CONFIRMED
    assert stored["draft_hash"] == draft["draft_hash"]
    assert stored["content"] == CONTENT

    # The refusals were the lock, not a broken second connection: once the
    # confirmation has committed, the same writer gets in.
    other = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")
    finally:
        other.close()


# --- Connections --------------------------------------------------------------


def test_works_with_and_without_a_row_factory(drafts, tmp_path):
    for name, factory in (("plain", None), ("row", sqlite3.Row)):
        conn = make_conn(tmp_path / f"{name}.db", factory)

        try:
            drafts.create_drafts_table(conn)
            draft = drafts.create_draft(
                conn, CONTENT, created_by="op", draft_id="d1", now=1.0
            )
            confirmed = drafts.confirm_draft(
                conn, "d1", draft["draft_hash"], now=2.0
            )

            assert draft["draft_id"] == "d1"
            assert draft["content"] == CONTENT
            assert confirmed["status"] == drafts.CONFIRMED
            assert drafts.get_draft(conn, "d1") == confirmed
        finally:
            conn.close()


def test_works_on_a_controller_connection_inside_its_schema(drafts, tmp_path):
    """Drafts are storage only: confirming one creates no task and no event."""
    conn = controller_db.open_controller_db(tmp_path / "controller.db")

    try:
        drafts.create_drafts_table(conn)
        draft = drafts.create_draft(conn, CONTENT, created_by="op", draft_id="d1")
        drafts.confirm_draft(conn, "d1", draft["draft_hash"])

        for table in ("tasks", "task_versions", "events", "activations"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, table
    finally:
        conn.close()


# --- The module itself --------------------------------------------------------


def test_module_reads_no_chatroom_and_imports_no_task_creation():
    tree = ast.parse(DRAFTS_SOURCE.read_text(encoding="utf-8"))
    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))

    assert imported <= {
        "__future__", "hashlib", "json", "sqlite3", "time", "uuid", "typing",
        ".db",
    }, imported


def test_module_has_no_placeholders():
    source = DRAFTS_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for marker in ("TODO", "FIXME", "XXX", "NotImplementedError"):
        assert marker not in source, marker

    assert not any(isinstance(node, ast.Pass) for node in ast.walk(tree))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = [
                statement for statement in node.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                )
            ]
            assert body, f"{node.name} has no body beyond a docstring"
