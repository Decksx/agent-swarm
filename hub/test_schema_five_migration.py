"""Schema 4 to 5, against a database with real work in it.

Tower's controller holds eleven tasks, twenty-two activations and ninety
events at schema 4. Migrating an empty database proves the SQL parses; it does
not prove that the rows survive, that the foreign keys still resolve, or that
a controller built for 5 can read what a controller built for 4 wrote.

So this builds a populated, live-shaped database at version 4 -- tasks in
several states, activations with results, an event log that replays -- and
migrates it.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import activations, db, engine, schema  # noqa: E402


# The activations table exactly as schema 4 defined it: no operator_context.
SCHEMA_FOUR_ACTIVATIONS = """
CREATE TABLE activations (
  activation_id       TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL,
  task_version        INTEGER NOT NULL,
  agent               TEXT NOT NULL,
  host                TEXT NOT NULL,
  role                TEXT NOT NULL,
  stage               TEXT NOT NULL,
  attempt_no          INTEGER NOT NULL,
  chargeable_attempt  INTEGER NOT NULL DEFAULT 1,
  expected_branch     TEXT,
  expected_parent     TEXT,
  expected_candidate  TEXT,
  repo_location       TEXT,
  issued_at           REAL NOT NULL,
  claimed_at          REAL,
  lease_expires_at    REAL NOT NULL,
  hard_deadline_at    REAL NOT NULL,
  heartbeat_at        REAL,
  heartbeat_seq       INTEGER NOT NULL DEFAULT 0,
  status              TEXT NOT NULL,
  result_event_id     TEXT,
  result_request_hash TEXT,
  result_response     TEXT,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);
"""


def schema_four_sql() -> str:
    """The current schema with the activations table rolled back to four."""
    sql = schema.SCHEMA_SQL
    start = sql.index("CREATE TABLE IF NOT EXISTS activations")
    end = sql.index(");", start) + 2

    return sql[:start] + SCHEMA_FOUR_ACTIVATIONS.strip() + sql[end:]


@pytest.fixture
def populated(tmp_path):
    """A version-4 database with tasks, activations and a replayable log."""
    path = tmp_path / "controller.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_four_sql())
    now = time.time()

    for index in range(1, 6):
        task = f"OLD-{index}"
        conn.execute(
            "INSERT INTO tasks (task_id, title, objective, priority, "
            "current_version, state, state_seq, created_at, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (task, f"task {index}", "an objective", 50, 1, "READY_AUTHOR",
             0, now, "admin"),
        )
        conn.execute(
            "INSERT INTO task_versions (task_id, version, contract_yaml, "
            "contract_hash, protocol_schema_version, base_sha, proof_mode, "
            "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (task, 1, "objective: x", "h" * 64, 4, "0" * 40, "baseline",
             now, "admin"),
        )
        conn.execute(
            "INSERT INTO activations (activation_id, task_id, task_version, "
            "agent, host, role, stage, attempt_no, chargeable_attempt, "
            "issued_at, lease_expires_at, hard_deadline_at, heartbeat_seq, "
            "status, result_response) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"act{index}", task, 1, "chatgpt", "officepc", "author", "author",
             1, 1, now, now + 900, now + 3600, 3, "DONE", '{"ok": true}'),
        )
        conn.execute(
            "INSERT INTO events (event_id, task_id, task_version, "
            "activation_id, actor, authority, kind, from_state, to_state, "
            "payload_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"ev{index}", task, 1, f"act{index}", "controller", "controller",
             "author_activation_issued", "READY_AUTHOR", "AUTHOR_ASSIGNED",
             "{}", now),
        )

    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    return path


def counts(conn):
    return {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("tasks", "task_versions", "activations", "events")
    }


def test_the_starting_point_really_is_version_four(populated):
    conn = sqlite3.connect(str(populated))
    conn.row_factory = sqlite3.Row

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(activations)")}

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert "operator_context" not in columns

    conn.close()


def test_migrating_reaches_the_build_version(populated):
    conn = db.connect(str(populated))
    db.migrate(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION

    conn.close()


def test_every_row_survives(populated):
    before = db.connect(str(populated))
    expected = counts(before)
    before.close()

    conn = db.connect(str(populated))
    db.migrate(conn)

    assert counts(conn) == expected
    assert expected["events"] == 5

    conn.close()


def test_the_new_column_is_null_for_every_existing_activation(populated):
    """NULL is correct for all of them: none was issued while an operator
    response was outstanding, and inventing one would put words in the
    operator's mouth."""
    conn = db.connect(str(populated))
    db.migrate(conn)

    rows = conn.execute("SELECT operator_context FROM activations").fetchall()

    assert rows
    assert all(row["operator_context"] is None for row in rows)

    conn.close()


def test_existing_results_are_not_disturbed(populated):
    conn = db.connect(str(populated))
    db.migrate(conn)

    row = conn.execute(
        "SELECT * FROM activations WHERE activation_id = 'act1'"
    ).fetchone()

    assert row["result_response"] == '{"ok": true}'
    assert row["status"] == "DONE"
    assert row["heartbeat_seq"] == 3

    conn.close()


def test_the_foreign_keys_still_resolve(populated):
    conn = db.connect(str(populated))
    db.migrate(conn)

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    conn.close()


def test_the_event_log_still_replays(populated):
    """The log is the audit trail and the recovery mechanism. A migration that
    left it unreplayable would have taken both."""
    conn = db.connect(str(populated))
    db.migrate(conn)

    assert engine.replay_state(conn, "OLD-1") == "AUTHOR_ASSIGNED"

    conn.close()


def test_a_migrated_database_accepts_a_new_activation_with_context(populated):
    """The column is not merely present; it is usable by the code that needs
    it, on a database that was not created with it."""
    conn = db.connect(str(populated))
    db.migrate(conn)

    conn.execute(
        "UPDATE tasks SET state = 'READY_AUTHOR' WHERE task_id = 'OLD-2'"
    )
    conn.execute(
        "INSERT OR REPLACE INTO host_capacity (host, max_concurrent) "
        "VALUES ('officepc', 2)"
    )
    conn.commit()

    issued = activations.issue(
        conn, task_id="OLD-2", agent="chatgpt", host="officepc",
        stage="author", repo_location="/repo", expected_branch="task/author", lease_seconds=900.0, hard_deadline_seconds=3600.0,
    )
    claimed = activations.claim(
        conn, activation_id=issued["activation_id"], agent="chatgpt",
    )

    assert "operator_context" in claimed
    assert claimed["operator_context"] is None

    conn.close()


def test_migrating_twice_is_not_an_error(populated):
    """The version bump is a separate transaction from the step, so a crash
    between them leaves the column added and the version unchanged -- and the
    next startup runs the step again."""
    conn = db.connect(str(populated))
    db.migrate(conn)
    db.migrate(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION

    conn.close()


def test_the_step_alone_is_idempotent(populated):
    """Exactly the crash case, without waiting for a crash."""
    conn = db.connect(str(populated))
    db.migrate(conn)

    db._add_operator_context(conn)
    db._add_operator_context(conn)

    columns = [
        row["name"] for row in conn.execute("PRAGMA table_info(activations)")
    ]

    assert columns.count("operator_context") == 1

    conn.close()
