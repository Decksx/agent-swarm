"""A request's connection outlives the thread that opened it.

`get_conn` is a FastAPI dependency: it opens a connection, yields it, and
closes it in a `finally`. FastAPI runs a sync dependency in a threadpool, and a
generator dependency's two halves are separate scheduling events -- the setup
half on one worker thread, the cleanup half possibly on another. SQLite's
default guard then refuses the close, *after* the handler has already done its
work, so the effect lands and the caller still gets a 500.

Nineteen of those were in the running hub's log, across `claim` and the event
feed. Neither route caused it; it is a thread-scheduling race and any route
could hit it.

These do not race. Each half runs on a thread the test chooses, so "works
across threads" is a fact rather than a probability. What is *not* being
claimed is that the connection may be shared: one request, one connection,
used sequentially. `test_the_guard_is_kept_for_everyone_else` pins that the
default is unchanged.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import api, db  # noqa: E402

ADMINS = {"admin", "operator"}


def stub_authenticate(x_test_agent: str = Header(default="")) -> str:
    if not x_test_agent:
        raise HTTPException(status_code=401, detail="authentication required")

    return x_test_agent


def stub_require_admin(x_test_agent: str = Header(default="")) -> str:
    component = stub_authenticate(x_test_agent)

    if component not in ADMINS:
        raise HTTPException(status_code=403, detail="admin only")

    return component


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "controller.db"
    api.ensure_database(str(path))

    return str(path)


def on_thread(work):
    """Run `work` on a thread that is definitely not this one, and return it."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(work).result()


# --- The lifecycle, made deterministic ---------------------------------------


def test_a_request_connection_survives_being_closed_on_another_thread(database):
    """Opened on one thread, used on a second, closed on a third.

    That is the shape FastAPI produces; the only difference is that here the
    threads are chosen rather than scheduled.
    """
    opened = {}

    def open_it():
        opened["thread"] = threading.get_ident()

        return db.open_controller_db(database, same_thread_only=False)

    conn = on_thread(open_it)

    def use_it():
        assert threading.get_ident() != opened["thread"]

        return conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]

    assert on_thread(use_it) == 0

    def close_it():
        assert threading.get_ident() != opened["thread"]
        conn.close()

    on_thread(close_it)


def test_the_old_setting_fails_that_same_sequence(database):
    """The defect, reproduced deterministically rather than waited for.

    If this ever stops failing, the fix above has stopped being necessary and
    the test below it has stopped proving anything.
    """
    conn = db.open_controller_db(database)

    with pytest.raises(sqlite3.ProgrammingError) as caught:
        on_thread(conn.close)

    assert "same thread" in str(caught.value)

    # Closed from the thread that opened it, which the guard does allow.
    conn.close()


def test_a_write_and_a_commit_survive_the_thread_change(database):
    """Not just reads. A transition writes, and its transaction has to hold
    across the same hop."""
    conn = on_thread(
        lambda: db.open_controller_db(database, same_thread_only=False)
    )

    def write():
        with db.transaction(conn):
            conn.execute(
                "INSERT INTO host_capacity (host, max_concurrent) VALUES (?,?)",
                ("officepc", 3),
            )

    on_thread(write)

    def read():
        return conn.execute(
            "SELECT max_concurrent AS n FROM host_capacity WHERE host = 'officepc'"
        ).fetchone()["n"]

    assert on_thread(read) == 3

    on_thread(conn.close)


def test_a_rollback_still_rolls_back_across_threads(database):
    """The guarantee that matters most: a failed transaction leaves nothing."""
    conn = on_thread(
        lambda: db.open_controller_db(database, same_thread_only=False)
    )

    def failing_write():
        try:
            with db.transaction(conn):
                conn.execute(
                    "INSERT INTO host_capacity (host, max_concurrent) "
                    "VALUES (?,?)", ("officepc", 3),
                )
                raise RuntimeError("something went wrong mid-transaction")
        except RuntimeError:
            pass

    on_thread(failing_write)

    def count():
        return conn.execute(
            "SELECT COUNT(*) AS n FROM host_capacity"
        ).fetchone()["n"]

    assert on_thread(count) == 0

    on_thread(conn.close)


def test_foreign_keys_and_wal_survive_the_thread_change(database):
    """The pragmas are per-connection, and dropping the guard must not drop
    them."""
    conn = on_thread(
        lambda: db.open_controller_db(database, same_thread_only=False)
    )

    def pragmas():
        return (
            conn.execute("PRAGMA foreign_keys").fetchone()[0],
            conn.execute("PRAGMA journal_mode").fetchone()[0],
        )

    keys, journal = on_thread(pragmas)

    assert keys == 1
    assert journal.lower() == "wal"

    on_thread(conn.close)


# --- Everyone else keeps the guard -------------------------------------------


def test_the_guard_is_kept_for_everyone_else(database):
    """The default is the safe value, so dropping it has to be asked for."""
    conn = db.open_controller_db(database)

    with pytest.raises(sqlite3.ProgrammingError):
        on_thread(lambda: conn.execute("SELECT 1"))

    conn.close()


def test_connect_also_defaults_to_the_guard(database):
    conn = db.connect(database)

    with pytest.raises(sqlite3.ProgrammingError):
        on_thread(lambda: conn.execute("SELECT 1"))

    conn.close()


def test_only_the_request_dependency_drops_it():
    """Stated as a boundary. A second caller turning it off would be a
    decision, and should look like one."""
    callers = []

    for module in ("controller/api.py", "controller/db.py",
                   "controller/activations.py", "controller/engine.py",
                   "controller/progression.py"):
        source = Path(module).read_text(encoding="utf-8")

        for line in source.splitlines():
            if "same_thread_only=False" in line:
                callers.append(module)

    assert sorted(set(callers)) == ["controller/api.py"], sorted(set(callers))


# --- Through the actual HTTP surface -----------------------------------------


@pytest.fixture
def client(database):
    app = FastAPI()
    app.include_router(
        api.build_router(
            authenticate=stub_authenticate,
            require_admin=stub_require_admin,
            db_path=database,
        )
    )

    return TestClient(app)


def as_(client, agent, method, path, **kw):
    return getattr(client, method)(path, headers={"X-Test-Agent": agent}, **kw)


def test_the_event_feed_answers_under_concurrency(client):
    """The two endpoints the log actually shows failing, hit hard enough that
    the cleanup half lands on a different worker than the setup half."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            pool.submit(as_, client, "narrator", "get", "/controller/events")
            for _ in range(60)
        ]
        codes = [future.result().status_code for future in results]

    assert set(codes) == {200}, sorted(set(codes))


def test_an_empty_queue_claim_answers_under_concurrency(client):
    """`claim` against an empty queue, which is what a polling worker does all
    day and where most of the logged 500s came from."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            pool.submit(as_, client, "chatgpt", "post",
                        "/controller/activations/claim", json={"agent": "chatgpt"})
            for _ in range(60)
        ]
        codes = [future.result().status_code for future in results]

    assert 500 not in codes, sorted(set(codes))


def test_both_endpoints_together_produce_no_server_errors(client):
    """Mixed, because the scheduler interleaves them in production."""
    def feed():
        return as_(client, "narrator", "get", "/controller/events").status_code

    def claim():
        return as_(client, "chatgpt", "post", "/controller/activations/claim",
                   json={"agent": "chatgpt"}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(feed if index % 2 else claim) for index in range(80)
        ]
        codes = [future.result() for future in futures]

    assert 500 not in codes, sorted(set(codes))


def test_a_write_route_still_works_and_commits(client):
    """The dependency serves writes too, and this proves the effect persists
    rather than merely returning 200."""
    assert as_(client, "admin", "post", "/controller/hosts",
               json={"host": "OFFICEPC", "max_concurrent": 2}).status_code == 200

    created = as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40,
    })

    assert created.status_code == 200
    assert as_(client, "admin", "get",
               "/controller/tasks/T-1").json()["task_id"] == "T-1"


def test_a_refused_write_leaves_nothing_behind(client):
    """Rollback, through the HTTP surface rather than the connection alone."""
    as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40,
    })
    before = as_(client, "admin", "get", "/controller/status").json()["tasks"]

    duplicate = as_(client, "admin", "post", "/controller/tasks", json={
        "task_id": "T-1", "title": "t", "objective": "o", "base_sha": "0" * 40,
    })

    assert duplicate.status_code >= 400
    assert as_(client, "admin", "get",
               "/controller/status").json()["tasks"] == before


# --- A fresh database is created with the pragmas the code assumes -----------
#
# `ensure_database` opened with raw `sqlite3.connect`, so it never ran the
# pragmas that live in `connect`. A new database was therefore left in
# SQLite's default `delete` journal mode, and the first requests against it
# each found a non-WAL file and raced to set WAL -- which takes an exclusive
# lock, so the losers failed the *connect* itself with "database is locked".
#
# It never showed in production because journal mode is persistent: whichever
# request won set it once, and every later connection read `wal` and skipped.
# The exposure is a fresh database taking concurrent traffic, which is exactly
# what a test fixture is.


def test_a_fresh_database_is_created_in_wal_mode(tmp_path):
    path = tmp_path / "fresh.db"
    api.ensure_database(str(path))

    mode = sqlite3.connect(str(path)).execute(
        "PRAGMA journal_mode"
    ).fetchone()[0]

    assert mode.lower() == "wal", mode


def test_a_fresh_database_has_its_other_pragmas_too(tmp_path):
    """Journal mode is the one that bit, but the same omission covered all of
    them -- and a database created without foreign keys enforced would accept
    rows the schema says are impossible."""
    path = tmp_path / "fresh.db"
    api.ensure_database(str(path))

    conn = db.connect(str(path))

    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    conn.close()


def test_connecting_to_a_wal_database_does_not_reset_the_mode(tmp_path,
                                                              monkeypatch):
    """The conditional in `connect`.

    Setting journal mode takes an exclusive lock, and this runs on every open
    -- once per request in the HTTP layer. Reading it first costs a shared
    lock and, for the ordinary case of an already-WAL database, takes no write
    lock at all.
    """
    path = tmp_path / "fresh.db"
    api.ensure_database(str(path))

    statements = []
    real_connect = sqlite3.connect

    def traced(*args, **kwargs):
        made = real_connect(*args, **kwargs)
        made.set_trace_callback(statements.append)

        return made

    monkeypatch.setattr(db.sqlite3, "connect", traced)

    db.connect(str(path)).close()

    assert statements, "nothing was traced, so this asserts nothing"
    assert not any("journal_mode = WAL" in s for s in statements), statements
    assert any("journal_mode" in s for s in statements), (
        "the mode should still be read, just not set"
    )


def test_many_first_requests_against_a_new_database_do_not_500(tmp_path):
    """The exposure, reproduced: a brand-new database taking concurrent
    traffic immediately."""
    path = tmp_path / "brand-new.db"
    api.ensure_database(str(path))

    app = FastAPI()
    app.include_router(
        api.build_router(
            authenticate=stub_authenticate,
            require_admin=stub_require_admin,
            db_path=str(path),
        )
    )
    fresh = TestClient(app)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(as_, fresh, "narrator", "get", "/controller/events")
            for _ in range(60)
        ]
        codes = [future.result().status_code for future in futures]

    assert set(codes) == {200}, sorted(set(codes))


# --- The production dependency actually asks for it --------------------------
#
# The tests above prove the setting works and that the old one fails. Neither
# says the request dependency *uses* it -- they call `open_controller_db`
# themselves. Reverting `get_conn` to the guarded connection left all of them
# green, which made the headline fix untested. These close that.


def test_the_request_dependency_asks_for_a_cross_thread_connection(client,
                                                                   monkeypatch):
    """Asserted at the production call site, not at a call the test makes."""
    seen = []
    real = api.open_controller_db

    def watched(path, **kwargs):
        seen.append(kwargs)

        return real(path, **kwargs)

    monkeypatch.setattr(api, "open_controller_db", watched)

    assert as_(client, "narrator", "get",
               "/controller/events").status_code == 200
    assert seen, "the dependency never opened a connection"
    assert all(call.get("same_thread_only") is False for call in seen), seen
