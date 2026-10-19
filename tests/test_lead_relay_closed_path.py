"""The relay's CLOSED path for both backends, against docs/design/113-codex-ownership.md.

Section numbers refer to that design (approved at b9f9f17). The relay fakes
come from `test_lead_relay`; the Codex data directory here is a temporary
one built to the observed schema, never `~/.codex`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

import lead_relay
import lead_relay_codex
from lead_relay import CLOSED, OPEN, UNKNOWN, Session
from lead_relay_codex import FREE, HELD, CodexBackend, codex_usage, probe_lock
from test_lead_relay import FakeBackend, FakePopen, World

THREAD = "01a14068-d723-76a0-a86d-c7d7b34c1b30"
WORKSPACE = r"C:\Users\david\Documents\Codex\2026-10-15\i-m-trying-to-merge-a"


def handoff(w, to="claude-lead", sender="codex-lead"):
    return w.hub.add(sender, f"HANDOFF @{to}: please look at #122")


def attempt(w, mid, recipient="claude-lead"):
    return w.relay.db.execute("SELECT * FROM attempts WHERE message_id = ? AND recipient = ? "
                              "ORDER BY created_at DESC", (mid, recipient)).fetchone()


# --- §4 the prompt travels on stdin, out of argv ------------------------------------


def test_the_prompt_and_token_go_to_stdin_and_never_into_argv(tmp_path):
    w = World(tmp_path)
    w.tick()
    mid = handoff(w)
    w.tick()

    row = attempt(w, mid)
    handle = w.relay.popen[row["attempt_id"]]
    sent = handle.stdin.data.decode("utf-8")
    assert w.delivery(mid) == ("running", None)
    assert row["token"] in sent and "> HANDOFF @claude-lead: please look at #122" in sent
    assert handle.stdin.closed
    argv = " ".join(w.spawned[0])
    assert row["token"] not in argv and "#122" not in argv


def test_pid_creation_time_and_launch_time_are_durable_before_the_write(tmp_path):
    w = World(tmp_path)
    w.tick()
    seen = {}

    class Inspecting(FakePopen):
        def __init__(self, processes, pid):
            super().__init__(processes, pid)
            outer = self

            class Stdin:
                closed = False

                def write(self, data):
                    # A separate connection: what it sees is committed, i.e. durable.
                    with closing(sqlite3.connect(w.db_path)) as db:
                        db.row_factory = sqlite3.Row
                        seen.update(dict(db.execute("SELECT * FROM attempts WHERE pid = ?",
                                                    (outer.pid,)).fetchone()))

                def close(self):
                    self.closed = True

            self.stdin = Stdin()

    def spawn(command, session, attempt_id):
        pid, start, _, log = w.spawn(command, session, attempt_id)
        return pid, start, Inspecting(w.processes, pid), log

    w.relay.spawn = spawn
    handoff(w)
    w.tick()

    assert seen["state"] == "launching"
    assert seen["pid"] and seen["proc_start"] and seen["launched_at"] == w.t[0]


@pytest.mark.parametrize("error", [BrokenPipeError(32, "pipe"), OSError(22, "invalid")])
def test_a_write_failure_kills_the_child_then_fails_once_and_is_never_retried(tmp_path, error):
    w = World(tmp_path)
    w.tick()

    def spawn(command, session, attempt_id):
        result = w.spawn(command, session, attempt_id)
        result[2].stdin.error = error
        return result

    w.relay.spawn = spawn
    mid = handoff(w)
    w.tick()

    row = attempt(w, mid)
    assert w.delivery(mid) == ("failed", f"spawn-io: {type(error).__name__}")
    assert row["state"] == "exited" and row["pid"] in w.processes.killed
    assert w.recorded and any("prompt not delivered" in p for p in w.hub.posts)
    for _ in range(3):
        w.tick(advance=lead_relay.EXIT_ACK_GRACE + 1)
    assert len(w.spawned) == 1
    assert w.relay.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0


def test_a_write_failure_whose_child_survives_the_kill_is_supervised_not_failed(tmp_path):
    w = World(tmp_path)
    w.tick()
    w.processes.kill_tree = lambda pid: w.processes.killed.append(pid)   # the kill doesn't take

    def spawn(command, session, attempt_id):
        result = w.spawn(command, session, attempt_id)
        result[2].stdin.error = BrokenPipeError(32, "pipe")
        return result

    w.relay.spawn = spawn
    mid = handoff(w)
    w.tick()

    assert w.delivery(mid) == ("running", None)
    assert attempt(w, mid)["state"] == "running"


def test_a_write_that_blocks_past_the_timeout_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(lead_relay, "STDIN_TIMEOUT", 0.2)
    w = World(tmp_path)
    w.tick()

    def spawn(command, session, attempt_id):
        result = w.spawn(command, session, attempt_id)
        result[2].stdin.write = lambda data: time.sleep(2)
        return result

    w.relay.spawn = spawn
    mid = handoff(w)
    w.tick()

    assert w.delivery(mid) == ("failed", "spawn-io: timeout")


def test_a_real_child_reads_the_prompt_from_stdin_and_not_from_argv(tmp_path):
    w = World(tmp_path)
    echo = tmp_path / "echo.py"
    out = tmp_path / "out.json"
    echo.write_text("import json, sys\n"
                    "json.dump({'argv': sys.argv, 'stdin': sys.stdin.read()},"
                    f" open({str(out)!r}, 'w'))\n", encoding="utf-8")
    session = Session("claude-lead", "claude", "11111111-2222-3333-4444-555555555555",
                      str(tmp_path), None, True)
    w.relay.processes = lead_relay.ProcessApi()
    pid, start, handle, log = w.relay._spawn([sys.executable, str(echo)], session, "a1")
    prompt = "Hive relay delivery ... `ACK #9 SECRETTOKEN0123456789abcd`"

    assert w.relay._feed(handle, prompt) is None
    handle.wait(timeout=30)
    seen = json.loads(out.read_text(encoding="utf-8"))
    assert seen["stdin"] == prompt
    assert not any("SECRETTOKEN" in arg for arg in seen["argv"])


def test_both_backends_put_the_prompt_on_stdin():
    session = Session("claude-lead", "claude", THREAD, "C:/git", "claude", True)
    assert lead_relay.ClaudeBackend(lead_relay.ProcessApi()).command(session) == [
        "claude", "-p", "--resume", THREAD, "--output-format", "json"]
    codex = CodexBackend(app_server=lambda: None, environ={})
    exe = Path(__file__)   # any existing file stands in for a registered CLI
    command = codex.command(Session("codex-lead", "codex", THREAD, WORKSPACE, str(exe), True))
    # Only the Git-checkout check is skipped; no sandbox or approval bypass.
    assert command == [str(exe), "exec", "resume", "--json", "--skip-git-repo-check", THREAD, "-"]
    assert not any("dangerously" in arg or arg in ("--full-auto", "--yolo") for arg in command)


# --- §4 recovery of a crash during the write -----------------------------------------


def crashed_mid_write(w):
    """A relay that died after persisting the pid but before marking running."""
    w.tick()
    mid = handoff(w)
    w.tick()
    row = attempt(w, mid)
    w.relay.db.execute("UPDATE attempts SET state = 'launching' WHERE attempt_id = ?",
                       (row["attempt_id"],))
    w.relay.db.execute("UPDATE deliveries SET state = 'launching' WHERE message_id = ?", (mid,))
    return mid, row


def test_a_live_launching_child_is_supervised_after_a_restart_and_not_marked_exited(tmp_path):
    w = World(tmp_path)
    mid, row = crashed_mid_write(w)
    w.restart()

    assert attempt(w, mid)["state"] == "running"
    assert w.delivery(mid) == ("running", None)
    assert len(w.spawned) == 1                      # never resent
    w.tick(advance=lead_relay.RUN_TIMEOUT + 1)
    assert row["pid"] in w.processes.killed         # the timeout still applies
    assert w.recorded and w.recorded[-1][1] >= lead_relay.RUN_TIMEOUT


def test_a_launching_child_that_is_gone_after_a_restart_is_uncertain_with_usage(tmp_path):
    w = World(tmp_path)
    mid, row = crashed_mid_write(w)
    w.processes.alive.pop(row["pid"])
    w.t[0] += 30
    w.restart()
    w.tick()

    assert w.delivery(mid) == ("uncertain", "process gone after restart")
    assert w.recorded and w.recorded[-1][1] >= 30
    assert len(w.spawned) == 1


def test_a_launching_row_without_a_pid_is_still_crash_before_pid(tmp_path):
    w = World(tmp_path)
    w.tick()
    mid = handoff(w)
    w.relay.spawn = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        w.tick()
    w.restart()

    assert w.delivery(mid) == ("uncertain", "crash before pid")


# --- §5 usage, by backend -------------------------------------------------------------


def two_backends(tmp_path):
    w = World(tmp_path)
    w.codex_backend = FakeBackend(CLOSED)
    w.relay.backends["codex"] = w.codex_backend
    w.relay.db.execute("UPDATE sessions SET backend = 'codex' WHERE recipient = 'codex-lead'")
    w.codex_recorded = []
    w.relay.usage["codex"] = (lambda: None, lambda s, e: w.codex_recorded.append((s, e)))
    return w


def test_each_run_is_charged_to_its_own_backend_only(tmp_path):
    w = two_backends(tmp_path)
    w.tick()
    to_codex = handoff(w, to="codex-lead", sender="claude-lead")
    w.tick()
    w.exit()
    w.tick(advance=5)

    assert attempt(w, to_codex, "codex-lead")["backend"] == "codex"
    assert len(w.codex_recorded) == 1 and w.recorded == []

    to_claude = handoff(w)
    w.tick(advance=lead_relay.EXIT_ACK_GRACE + 1)
    w.exit()
    w.tick(advance=5)
    assert attempt(w, to_claude)["backend"] == "claude"
    assert len(w.recorded) == 1 and len(w.codex_recorded) == 1


def test_a_backend_without_a_guard_never_launches(tmp_path):
    w = two_backends(tmp_path)
    del w.relay.usage["codex"]
    w.tick()
    mid = handoff(w, to="codex-lead", sender="claude-lead")
    w.tick()

    assert w.delivery(mid, "codex-lead") == ("held", "rate-unconfigured")
    assert w.spawned == []


def test_usage_follows_the_attempt_not_a_later_re_registration(tmp_path):
    w = two_backends(tmp_path)
    w.tick()
    handoff(w)
    w.tick()
    w.relay.db.execute("UPDATE sessions SET backend = 'codex' WHERE recipient = 'claude-lead'")
    w.exit()
    w.tick(advance=5)

    assert len(w.recorded) == 1 and w.codex_recorded == []


def test_an_older_database_is_migrated_and_its_attempts_are_claudes(tmp_path):
    db = sqlite3.connect(tmp_path / "relay.db")
    db.executescript(lead_relay.SCHEMA.replace(",\n    backend TEXT", ""))
    db.execute("INSERT INTO attempts (attempt_id, message_id, recipient, token, path, state, "
               "created_at) VALUES ('old', 1, 'claude-lead', 'tok', 'headless', 'done', 0)")
    db.commit()
    db.close()
    w = World(tmp_path, register=False)

    assert w.relay.db.execute("SELECT backend FROM attempts WHERE attempt_id = 'old'"
                              ).fetchone()[0] == "claude"


# --- §2 the probe is rate-limited, CLOSED never cached --------------------------------


class Counting(FakeBackend):
    probe_interval = 60.0

    def __init__(self, state):
        super().__init__(state)
        self.asked = 0

    def ownership(self, session):
        self.asked += 1
        return super().ownership(session)


def test_an_unknown_answer_is_reused_for_the_probe_interval_only(tmp_path):
    w = World(tmp_path)
    backend = Counting(UNKNOWN)
    w.relay.backends["claude"] = backend
    w.tick()
    mid = handoff(w)
    w.tick()
    w.tick(advance=20)
    w.tick(advance=20)
    assert backend.asked == 1 and w.delivery(mid) == ("held", "session-busy-or-unknown")
    w.tick(advance=21)
    assert backend.asked == 2


def test_a_closed_answer_is_never_reused_and_the_pre_spawn_check_always_asks(tmp_path):
    w = World(tmp_path)
    backend = Counting(CLOSED)
    w.relay.backends["claude"] = backend
    w.tick()
    handoff(w)
    w.tick()

    assert backend.asked == 2          # _hold_reason, then the pre-spawn re-check
    assert len(w.spawned) == 1


def test_a_held_closed_session_is_re_probed_every_tick(tmp_path):
    w = World(tmp_path, enabled=False)   # CLOSED but disabled: held, not launched
    backend = Counting(CLOSED)
    w.relay.backends["claude"] = backend
    w.tick()
    mid = handoff(w)
    for _ in range(3):
        w.tick(advance=20)

    assert w.delivery(mid) == ("held", "backend-disabled")
    assert backend.asked == 3          # never answered from a cached CLOSED


# --- §2 Codex ownership from its own storage ------------------------------------------


class Home:
    """A Codex data directory with the observed schema (2026-10-19)."""

    def __init__(self, root: Path, *, cwd=WORKSPACE, extended=True, turns=()):
        self.root = root
        rollout = root / "sessions" / "2026" / "10" / "15" / f"rollout-2026-10-15T10-32-55-{THREAD}.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": THREAD}}) + "\n",
                           encoding="utf-8")
        self.rollout = rollout
        prefix = "\\\\?\\" if extended else ""
        with closing(sqlite3.connect(root / "state_5.sqlite")) as db, db:
            db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, cwd TEXT, title TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?, ?, 't')",
                       (THREAD, prefix + str(rollout), prefix + cwd))
        with closing(sqlite3.connect(root / "thread_history_1.sqlite")) as db, db:
            db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT)")
            for i, status in enumerate(turns):
                db.execute("INSERT INTO thread_turns VALUES (?, ?, ?)", (THREAD, f"t{i}", status))
        (root / "thread-writer-locks").mkdir()
        (root / "thread-writer-locks" / f"{THREAD}.lock").write_bytes(b"")


def codex(home, lock=FREE):
    def probe(path):
        if isinstance(lock, Exception):
            raise lock
        return lock
    return CodexBackend(home.root, probe=probe, app_server=lambda: None, bin_dir=home.root / "bin",
                        environ={"CODEX_HOME": str(home.root)})


def lead(workspace=WORKSPACE, thread=THREAD):
    return Session("codex-lead", "codex", thread, workspace, None, True)


@pytest.mark.parametrize("lock, turns, expected", [
    (FREE, ("running",), UNKNOWN),                  # a status we have never seen
    (FREE, ("completed", None), UNKNOWN),
    (FREE, ("completed", 5), UNKNOWN),
    (FREE, ("completed", "INPROGRESS"), UNKNOWN),
    (HELD, ("completed",), OPEN),
    (HELD, ("inProgress",), OPEN),
    (FREE, ("completed", "failed", "interrupted"), CLOSED),
    (FREE, (), CLOSED),
    (FREE, ("completed", "inProgress"), UNKNOWN),   # a stale inProgress is not idle
    (OSError(5, "denied"), ("completed",), UNKNOWN),
])
def test_codex_ownership_comes_from_the_writer_lock_and_turn_state(tmp_path, lock, turns, expected):
    home = Home(tmp_path, turns=turns)
    assert codex(home, lock).ownership(lead()) == expected


def test_codex_paths_in_extended_length_form_still_match(tmp_path):
    assert codex(Home(tmp_path, extended=True)).ownership(lead()) == CLOSED
    other = tmp_path / "plain"
    other.mkdir()
    assert codex(Home(other, extended=False)).ownership(lead()) == CLOSED


@pytest.mark.parametrize("session", [
    lead(workspace=r"C:\git\agent-swarm"),                       # not the thread's workspace
    lead(thread="01a14068-0000-0000-0000-000000000000"),          # no such thread
    lead(thread="not-a-uuid"),
])
def test_codex_ownership_is_unknown_for_a_binding_it_cannot_confirm(tmp_path, session):
    assert codex(Home(tmp_path)).ownership(session) == UNKNOWN


@pytest.mark.parametrize("breakage", ["no-state-db", "no-turns-db", "threads-schema",
                                      "turns-schema", "no-rollout", "no-home"])
def test_codex_ownership_is_unknown_when_its_storage_is_not_as_expected(tmp_path, breakage):
    home = Home(tmp_path)
    if breakage == "no-state-db":
        (tmp_path / "state_5.sqlite").unlink()
    elif breakage == "no-turns-db":
        (tmp_path / "thread_history_1.sqlite").unlink()
    elif breakage == "threads-schema":
        with closing(sqlite3.connect(tmp_path / "state_5.sqlite")) as db, db:
            db.execute("ALTER TABLE threads RENAME COLUMN cwd TO workdir")
    elif breakage == "turns-schema":
        with closing(sqlite3.connect(tmp_path / "thread_history_1.sqlite")) as db, db:
            db.execute("ALTER TABLE thread_turns RENAME COLUMN status TO state")
    elif breakage == "no-rollout":
        home.rollout.unlink()
    else:
        home.root = tmp_path / "missing"
    assert codex(home).ownership(lead()) == UNKNOWN


def test_codex_ownership_never_writes_to_the_codex_data_directory(tmp_path):
    home = Home(tmp_path, turns=("inProgress",))
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    for lock in (HELD, FREE):
        codex(home, lock).ownership(lead())
    CodexBackend(tmp_path, app_server=lambda: None,
                 environ={"CODEX_HOME": str(tmp_path)}).ownership(lead())   # the real probe too
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_every_connection_to_codex_storage_is_closed(tmp_path, monkeypatch):
    """`with sqlite3.connect()` only commits; an open handle on Codex's own
    database is not ours to keep. Garbage collection would hide the leak."""
    real, opened = sqlite3.connect, []

    class Tracked:
        def __init__(self, *args, **kwargs):
            self.conn, self.closed = real(*args, **kwargs), False
            opened.append(self)

        def execute(self, *args):
            return self.conn.execute(*args)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.conn.__exit__(*exc)

        def close(self):
            self.closed = True
            self.conn.close()

    home = Home(tmp_path, turns=("completed",))
    monkeypatch.setattr(lead_relay_codex.sqlite3, "connect", Tracked)
    codex(home).ownership(lead())
    codex(home).transcript_mentions(lead(), "x")

    assert opened and all(c.closed for c in opened)


def test_the_codex_transcript_is_evidence_only(tmp_path):
    home = Home(tmp_path)
    with open(home.rollout, "a", encoding="utf-8") as f:
        f.write('{"text": "ACK #9 TOKENxyz0123456789abcdef"}\n')
    assert codex(home).transcript_mentions(lead(), "TOKENxyz0123456789abcdef") is True
    assert codex(home).transcript_mentions(lead(), "TOKENnothere0123456789") is False
    assert codex(home).transcript_mentions(lead(r"C:\elsewhere"), "x") is None


# --- §4 the CLI is resolved at spawn, and missing is a hold ---------------------------


def test_the_codex_cli_is_registered_then_running_then_newest_installed(tmp_path):
    home = Home(tmp_path)
    old, new = tmp_path / "bin" / "aaa" / "codex.exe", tmp_path / "bin" / "bbb" / "codex.exe"
    for exe in (old, new):
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
    os.utime(old, (1, 1))
    registered = tmp_path / "registered.exe"
    registered.write_bytes(b"")
    backend = codex(home)

    assert backend.cli(Session("codex-lead", "codex", THREAD, WORKSPACE, str(registered), True)) \
        == str(registered)
    backend.app_server = lambda: str(old)
    assert backend.cli(lead()) == str(old)
    backend.app_server = lambda: None
    assert backend.cli(lead()) == str(new)
    for exe in (old, new):
        exe.unlink()
    with pytest.raises(FileNotFoundError):
        backend.cli(lead())


def test_a_missing_cli_holds_the_delivery_instead_of_failing_a_launch(tmp_path):
    w = World(tmp_path)

    class NoCli(FakeBackend):
        def command(self, session):
            raise FileNotFoundError("no Codex CLI")

    w.relay.backends["claude"] = NoCli(CLOSED)
    w.tick()
    mid = handoff(w)
    w.tick()

    assert w.delivery(mid) == ("held", "pre-spawn-error") and w.spawned == []


# --- the real lock probe ---------------------------------------------------------------


HOLDER = """
import os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
if os.name == "nt":
    import msvcrt
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
time.sleep(30)
"""


def test_the_real_probe_sees_another_processs_lock_and_its_release(tmp_path):
    path = tmp_path / f"{THREAD}.lock"
    path.write_bytes(b"")
    assert probe_lock(path) == FREE and probe_lock(tmp_path / "absent.lock") == FREE

    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(path)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert probe_lock(path) == HELD
    finally:
        holder.kill()
        holder.wait()
    # The file outlives its writer; the OS lock does not.
    assert path.exists() and probe_lock(path) == FREE


# --- §5 the Codex duration guard -------------------------------------------------------


def test_the_codex_guard_holds_at_its_budget_and_forgets_old_runs(tmp_path):
    now = [10_000.0]
    check, record = codex_usage(tmp_path / "codex_usage.json", budget_seconds=100,
                                window_seconds=1000, now=lambda: now[0])
    assert check() is None
    record(now[0] - 200, 60)
    record(now[0] - 100, 50)
    assert check() == "codex-budget"
    now[0] += 1000
    assert check() is None


def test_an_unreadable_codex_guard_fails_closed(tmp_path):
    path = tmp_path / "codex_usage.json"
    path.write_text("{not json", encoding="utf-8")
    check, record = codex_usage(path, budget_seconds=100)
    with pytest.raises(ValueError):
        check()
    (tmp_path / "w").mkdir()
    w = two_backends(tmp_path / "w")
    w.relay.usage["codex"] = (check, record)
    w.tick()
    mid = handoff(w, to="codex-lead", sender="claude-lead")
    w.tick()
    assert w.delivery(mid, "codex-lead") == ("held", "guard-unavailable") and w.spawned == []


# --- review of 1797d4e: binding, home and data validation --------------------------


@pytest.mark.parametrize("cached", [OPEN, UNKNOWN])
def test_a_re_registered_delivery_is_probed_against_its_new_thread(tmp_path, cached):
    w = World(tmp_path)

    class ByThread(FakeBackend):
        probe_interval = 60.0

        def ownership(self, session):
            return cached if session.session_id.startswith("1111") else CLOSED

    w.relay.backends["claude"] = ByThread()
    w.tick()
    mid = handoff(w)
    if cached == OPEN:
        w.relay.db.execute("UPDATE sessions SET enabled = 0")   # notices stay notices
    w.tick()
    w.relay.db.execute("UPDATE sessions SET session_id = '22222222-2222-3333-4444-555555555555', "
                       "enabled = 1 WHERE recipient = 'claude-lead'")
    w.relay.db.execute("UPDATE deliveries SET state = 'held', reason = 'x', attempt_id = NULL "
                       "WHERE message_id = ?", (mid,))
    w.relay.db.execute("UPDATE attempts SET state = 'superseded'")
    w.tick(advance=10)       # well inside the probe interval

    assert w.delivery(mid) == ("running", None) and len(w.spawned) == 1


def test_probe_rollout_transcript_and_child_all_use_the_child_s_codex_home(tmp_path):
    (tmp_path / "custom").mkdir()
    home = Home(tmp_path / "custom", turns=("completed",))
    backend = CodexBackend(app_server=lambda: None, environ={"CODEX_HOME": str(home.root)},
                           probe=lambda path: HELD if path.parent.parent == home.root else FREE)
    assert backend.home == home.root
    assert backend.ownership(lead()) == OPEN           # probed under the chosen home
    assert backend.transcript_mentions(lead(), "nothing-here-0123456789") is False
    child = lead_relay.child_environment({"CODEX_HOME": str(home.root)}, "codex-lead")
    assert child["CODEX_HOME"] == str(home.root)       # what the woken run inherits


def test_a_pinned_home_that_is_not_the_child_s_holds(tmp_path):
    (tmp_path / "pinned").mkdir()
    (tmp_path / "chosen").mkdir()
    pinned = Home(tmp_path / "pinned", turns=("completed",))
    Home(tmp_path / "chosen", turns=("inProgress",))
    backend = CodexBackend(pinned.root, app_server=lambda: None, probe=lambda path: FREE,
                           environ={"CODEX_HOME": str(tmp_path / "chosen")})
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"")

    assert backend.ownership(lead()) == UNKNOWN        # not CLOSED from the wrong history
    with pytest.raises(LookupError):
        backend.command(Session("codex-lead", "codex", THREAD, WORKSPACE, str(exe), True))


@pytest.mark.parametrize("content", [
    "[[0, NaN]]", "[[0, Infinity]]", "[[0, -50]]", "[[-1, 5]]", "[[0, true]]",
    '[["0", 5]]', "[[0, 5, 1]]", "[[0]]", '[{"start": 0}]', "{}", "[0, 5]",
])
def test_a_malformed_codex_guard_fails_closed_and_is_kept(tmp_path, content):
    path = tmp_path / "codex_usage.json"
    path.write_text(content, encoding="utf-8")
    check, record = codex_usage(path, budget_seconds=100)
    with pytest.raises(ValueError):
        check()
    with pytest.raises(ValueError):
        record(0, 5)
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("budget, window", [(float("nan"), 10), (100, float("inf")),
                                            (0, 10), (-5, 10), (100, 0)])
def test_the_codex_guard_refuses_a_meaningless_budget(tmp_path, budget, window):
    with pytest.raises(ValueError):
        codex_usage(tmp_path / "u.json", budget_seconds=budget, window_seconds=window)


@pytest.mark.parametrize("start, elapsed", [(float("nan"), 1), (0, float("inf")), (0, -1), (-1, 1)])
def test_the_codex_guard_refuses_to_record_a_meaningless_run(tmp_path, start, elapsed):
    _, record = codex_usage(tmp_path / "u.json", budget_seconds=100)
    with pytest.raises(ValueError):
        record(start, elapsed)
    assert not (tmp_path / "u.json").exists()
