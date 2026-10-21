"""The bounded Codex CLOSED proof driver (#113): its guards and every exit."""
from __future__ import annotations

import json
import sqlite3

import pytest

import codex_closed_proof as proof
import lead_relay

CLI = r"C:\codex\bin\aaaa\codex.exe"


class Procs:
    def __init__(self):
        self.alive, self.killed = {}, []

    def is_same(self, pid, start):
        return bool(pid) and self.alive.get(pid) == start

    def kill_tree(self, pid):
        self.killed.append(pid)
        self.alive.pop(pid, None)


class Backend:
    def __init__(self):
        self.own, self.cli = "closed", CLI

    def command(self, session):
        return [self.cli, "exec", "resume", session.session_id, "-"]

    def ownership(self, session):
        return self.own


class World:
    """A fake Env over a real relay database, with a clock and scripted events."""

    def __init__(self, tmp_path):
        self.db_path = tmp_path / "lead_relay.db"
        db = sqlite3.connect(self.db_path, isolation_level=None)
        db.executescript(lead_relay.SCHEMA)
        self.cli_file = tmp_path / "codex.exe"
        self.cli_file.write_bytes(b"cli")
        self.cli = str(self.cli_file)
        db.execute("INSERT INTO meta VALUES ('cursor', '100')")
        db.execute("INSERT INTO sessions VALUES ('codex-lead', 'codex', ?, ?, ?, 0, 0)",
                   (proof.THREAD, proof.WORKSPACE, self.cli))
        db.close()
        self.config = tmp_path / "config.toml"
        self.config.write_text("sandbox_mode = 'x'\n")
        self.t, self.events, self.lines, self.posts = 1000.0, [], [], []
        self.processes, self.backend = Procs(), Backend()
        self.backend.cli = self.cli
        self.app = None
        self.images = {}
        self.disable_works = True
        self.stray = []
        self.state_path = tmp_path / "codex_closed_proof.json"

    # Env surface
    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        due = [e for e in self.events if e[0] <= self.t]
        self.events = [e for e in self.events if e[0] > self.t]
        for _, fn in sorted(due, key=lambda e: e[0]):
            fn()

    def say(self, line):
        self.lines.append(line)

    def app_server(self):
        return self.app

    def relay_cli(self, command, _flag, lead):
        if command == "disable" and not self.disable_works:
            return 0, "pretend"
        self.sql("UPDATE sessions SET enabled = ? WHERE recipient = ?", int(command == "enable"), lead)
        return 0, f"{lead}: {command}d"

    def post(self, text):
        self.posts.append((self.t, text))
        return "#9002"

    def statuses(self, since):
        return [{"id": 9003, "content": "STATUS thread 01a14068 workspace ok"}]

    def image(self, pid):
        return self.images.get(pid, self.cli)

    def new_session_files(self, since):
        return self.stray

    def rows(self, sql, *params):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    # helpers
    def sql(self, sql, *params):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute(sql, params)
        conn.close()

    def at(self, t, fn):
        self.events.append((t, fn))

    def prepare(self):
        self.cli_sha = proof.sha256(self.cli_file)
        state = dict(proof_id="abcd1234", prepared_at=self.t, enable_by=self.t + proof.ENABLE_WINDOW,
                     cli=self.cli, cli_sha256=self.cli_sha, config_sha256=proof.sha256(self.config),
                     baseline=100, probe1=proof.probes("abcd1234")[0],
                     probe2=proof.probes("abcd1234")[1], status="prepared")
        self.state_path.write_text(json.dumps(state))
        return state

    def deliver(self, mid, sender, content, state="pending"):
        self.sql("INSERT INTO deliveries VALUES (?, 'codex-lead', ?, ?, NULL, ?, 0, ?, NULL, NULL, NULL, ?)",
                 mid, sender, content, self.t, state, self.t)

    def set_delivery(self, mid, state, reason=None):
        self.sql("UPDATE deliveries SET state = ?, reason = ? WHERE message_id = ?", state, reason, mid)

    def launch(self, mid, pid, attempt=None):
        attempt = attempt or f"a{mid}-{pid}"
        self.sql("INSERT INTO attempts (attempt_id, message_id, recipient, token, path, state, "
                 "created_at, launched_at, pid, proc_start, backend) VALUES "
                 "(?, ?, 'codex-lead', ?, 'headless', 'running', ?, ?, ?, ?, 'codex')",
                 attempt, mid, attempt + "-tok", self.t, self.t, pid, f"s{pid}")
        self.sql("INSERT OR REPLACE INTO reservations VALUES ('codex:x', 'codex-lead', ?, ?)", attempt, self.t)
        self.processes.alive[pid] = f"s{pid}"

    def exit(self, mid, pid):
        self.processes.alive.pop(pid, None)
        self.sql("UPDATE attempts SET state = 'exited', ended_at = ?, usage_recorded = 1 "
                 "WHERE message_id = ? AND pid = ?",
                 self.t, mid, pid)
        self.sql("DELETE FROM reservations")

    def enabled(self):
        return self.rows("SELECT enabled FROM sessions")[0]["enabled"]

    def result(self):
        return json.loads(proof.result_path(self.state_path, "abcd1234").read_text())


@pytest.fixture
def w(tmp_path, monkeypatch):
    world = World(tmp_path)
    monkeypatch.setattr(world, "config", world.config)
    return world


def p1(w):
    return proof.probes("abcd1234")[0]


def p2(w):
    return proof.probes("abcd1234")[1]


def happy(w, *, second=True):
    """probe1 posted, launched, ACKed; probe2 waits, then launches and ACKs."""
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.set_delivery(101, "delivered"))
    if second:
        # Claude's probe2 arrives as a delivery once posted; held until probe1 exits.
        w.at(1050, lambda: w.deliver(102, "claude-lead", p2(w), "held"))
    w.at(1200, lambda: w.exit(101, 501))
    if second:
        w.at(1220, lambda: w.launch(102, 502))
        w.at(1250, lambda: w.set_delivery(102, "delivered"))
        w.at(1300, lambda: w.exit(102, 502))


def test_the_full_proof_passes_and_ends_disabled(w):
    w.prepare()
    happy(w)
    assert proof.run(w, w.state_path) == 0
    r = w.result()
    assert r["verdict"] == "passed"
    assert len(w.posts) == 1 and w.posts[0][1] == p2(w) and 1040 <= w.posts[0][0] < 1200
    assert w.enabled() == 0 and r["disable"]["stored_enabled"] == 0
    assert set(r["launches"]) == {"101", "102"}
    assert r["launches"]["101"]["a101-501"]["confirmed_exited"] is True
    assert w.processes.killed == []
    assert json.loads(w.state_path.read_text())["status"] == "finished"
    assert r["relay_settled"] is True and r["disable"]["confirmed"] is True


def test_a_used_or_expired_proof_refuses_without_touching_anything(w):
    state = w.prepare()
    state["status"] = "finished"
    w.state_path.write_text(json.dumps(state))
    assert proof.run(w, w.state_path) == 1
    state["status"], state["enable_by"] = "prepared", w.t
    w.state_path.write_text(json.dumps(state))
    assert proof.run(w, w.state_path) == 1
    assert w.enabled() == 0
    assert not proof.result_path(w.state_path, "abcd1234").exists()


def test_the_app_never_closing_expires_without_enabling(w):
    w.prepare()
    w.backend.own = "open"
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "expired" and "ownership is open" in r["why"][0]
    assert "enable" not in r and w.enabled() == 0


def test_a_running_desktop_app_server_blocks_enable(w):
    w.prepare()
    w.app = CLI
    assert proof.run(w, w.state_path) == 1
    assert w.result()["verdict"] == "expired" and "app-server" in w.result()["why"][0]


@pytest.mark.parametrize("change", ["cli", "config", "registration", "pending", "launcher"])
def test_preflight_refuses_any_changed_fact(w, change):
    state = w.prepare()
    if change == "cli":
        w.cli_file.write_bytes(b"updated")  # same path, new bytes: the hash must catch it
    elif change == "config":
        w.config.write_text("sandbox_mode = 'other'\n")
    elif change == "registration":
        w.sql("UPDATE sessions SET workspace = 'C:\\elsewhere'")
    elif change == "pending":
        w.deliver(99, "admin", "@codex-lead old", "held")
    else:
        w.backend.cli = r"C:\codex\bin\bbbb\codex.exe"
    assert proof.preflight(w, state, enabled=0, closed=True) != []


def test_preflight_passes_on_the_prepared_facts(w):
    assert proof.preflight(w, w.prepare(), enabled=0, closed=True) == []


def test_an_unexpected_delivery_stops_and_disables(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", "@Leads anything else"))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and "unexpected" in r["why"][0]
    assert w.enabled() == 0 and w.posts == []


def test_a_second_launch_for_one_source_fails(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1060, lambda: (w.exit(101, 501), w.launch(101, 503, "again")))
    w.at(1100, lambda: w.exit(101, 503))
    assert proof.run(w, w.state_path) == 1
    assert "more than one launch" in " ".join(w.result()["why"])


def test_probe2_launching_beside_a_live_probe1_run_fails(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1050, lambda: w.deliver(102, "claude-lead", p2(w), "held"))
    w.at(1060, lambda: w.launch(102, 502))
    w.at(1100, lambda: (w.exit(101, 501), w.exit(102, 502)))
    assert proof.run(w, w.state_path) == 1
    assert "while the probe1 run was alive" in " ".join(w.result()["why"])


def test_a_different_launched_executable_is_inconclusive(w):
    w.prepare()
    w.images[501] = r"C:\codex\bin\bbbb\codex.exe"
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.exit(101, 501))
    assert proof.run(w, w.state_path) == 1
    assert w.result()["verdict"] == "inconclusive" and w.enabled() == 0


def test_a_probe1_run_never_seen_alive_is_inconclusive_not_passed(w):
    """probe2 is posted as soon as the probe1 run is seen; if it never is, there
    is no executable identity and item 6 was not exercised."""
    w.prepare()
    w.at(1030, lambda: (w.deliver(101, "admin", p1(w)), w.launch(101, 501),
                        w.set_delivery(101, "delivered"), w.exit(101, 501)))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "inconclusive" and r["probe2"] == "not exercised" and w.posts == []
    assert w.enabled() == 0


def test_a_run_past_its_limit_is_stopped_by_identity(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.set_delivery(101, "delivered"))
    w.processes.alive[777] = "unrelated"
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert any("past 15 min" in why for why in r["why"])
    assert w.processes.killed == [501] and 777 in w.processes.alive
    assert r["launches"]["101"]["a101-501"]["killed"] is True
    assert r["launches"]["101"]["a101-501"]["confirmed_exited"] is True
    assert w.enabled() == 0


def test_a_reused_pid_is_not_killed(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    # The run exits and a stranger reuses pid 501 with another creation time.
    w.at(1100, lambda: (w.exit(101, 501), w.processes.alive.__setitem__(501, "stranger")))
    w.at(1110, lambda: w.deliver(102, "admin", "@codex-lead unrelated"))
    proof.run(w, w.state_path)
    assert w.processes.killed == [] and w.processes.alive[501] == "stranger"


def test_no_ack_within_ten_minutes_fails(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.exit(101, 501))
    assert proof.run(w, w.state_path) == 1
    assert "no ACK for #101" in " ".join(w.result()["why"])


def test_probe2s_ack_clock_starts_when_the_probe1_run_ends(w):
    """probe2 waits behind a long probe1 run; that wait is not a missing ACK."""
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.set_delivery(101, "delivered"))
    w.at(1050, lambda: w.deliver(102, "claude-lead", p2(w), "held"))
    w.at(1040 + 14 * 60, lambda: w.exit(101, 501))          # 13+ min after probe2 arrived
    w.at(1040 + 14 * 60 + 30, lambda: w.launch(102, 502))
    w.at(1040 + 14 * 60 + 60, lambda: (w.set_delivery(102, "delivered"), w.exit(102, 502)))
    assert proof.run(w, w.state_path) == 0
    assert w.result()["verdict"] == "passed"


def test_an_exception_still_disables_and_reports(w, monkeypatch):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))

    def boom(self):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(proof.Proof, "step", boom)
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and "database is locked" in r["why"][0] and w.enabled() == 0


def test_an_unconfirmed_disable_overrides_a_pass(w):
    w.prepare()
    happy(w)
    w.disable_works = False
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and "NOT confirmed disabled" in " ".join(r["why"])


def test_a_new_session_file_stops_the_proof(w):
    w.prepare()
    w.stray = [r"C:\Users\x\.codex\sessions\new.jsonl"]
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    assert proof.run(w, w.state_path) == 1
    why = w.result()["why"]
    assert "new session files" in why[0], why      # stopped mid-run, not only at the end


def test_the_window_expires_if_nobody_posts(w):
    w.prepare()
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "expired" and r["enable"]["rc"] == 0 and w.enabled() == 0


def test_prepare_refuses_while_an_unused_proof_is_open(w):
    w.prepare()
    assert proof.prepare(w, w.state_path, w.cli, w.cli_sha, proof.sha256(w.config)) == 1


def test_prepare_records_fresh_probes_and_the_relay_cursor(w):
    rc = proof.prepare(w, w.state_path, w.cli, proof.sha256(w.cli_file), proof.sha256(w.config))
    assert rc == 0
    s = json.loads(w.state_path.read_text())
    assert s["baseline"] == 100 and s["status"] == "prepared"
    assert s["probe1"].startswith("@codex-lead BRIDGE-PROOF " + s["proof_id"])
    assert s["probe2"].startswith("HANDOFF @codex-lead: BRIDGE-PROOF-2 " + s["proof_id"])
    assert lead_relay.recipients({"sender": "admin", "target": "@codex-lead",
                                  "content": s["probe1"]}) == ["codex-lead"]
    assert lead_relay.recipients({"sender": "claude-lead", "target": "@codex-lead",
                                  "content": s["probe2"]}) == ["codex-lead"]


def test_probe1_text_from_anyone_but_admin_is_unexpected(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "claude-lead", p1(w)))
    assert proof.run(w, w.state_path) == 1
    assert "unexpected codex-lead delivery #101 from claude-lead" in w.result()["why"][0]


def test_a_probe_that_arrived_before_enable_fails(w):
    w.prepare()
    w.deliver(101, "admin", p1(w), "delivered")   # e.g. ACKed by the open app
    w.sql("UPDATE deliveries SET received_at = 900")
    assert proof.run(w, w.state_path) == 1
    assert "arrived before enable" in w.result()["why"][0]


def test_a_delivery_without_a_launch_is_never_a_pass(w):
    """An ACK with no headless launch is not CLOSED-path evidence."""
    w.prepare()
    w.at(1030, lambda: (w.deliver(101, "admin", p1(w)), w.set_delivery(101, "delivered")))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "inconclusive" and r["launches"] == {}


# --- Codex, #133 at c7573c8: every recovery stage runs; evidence gates a pass;
# --- one live driver per proof.

import subprocess
import sys
import textwrap


def test_a_thrown_disable_still_cleans_up_and_saves_a_failure(w):
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))     # still alive when the run ends
    real = w.relay_cli

    def cli(command, flag, lead):
        if command == "disable":
            raise subprocess.TimeoutExpired("lead_relay.py disable", 60)
        return real(command, flag, lead)
    w.relay_cli = cli
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and r["disable"]["confirmed"] is False
    assert "TimeoutExpired" in r["disable"]["error"]
    assert "NOT confirmed disabled" in " ".join(r["why"])
    assert w.processes.killed == [501]                       # cleanup still ran
    assert r["launches"]["101"]["a101-501"]["confirmed_exited"] is True
    assert json.loads(w.state_path.read_text())["status"] == "finished"


def test_a_thrown_disable_verification_is_unconfirmed_not_disabled(w, monkeypatch):
    w.prepare()
    happy(w)
    real = w.rows

    def rows(sql, *params):
        if sql == "SELECT enabled FROM sessions WHERE recipient = ?":
            raise sqlite3.OperationalError("database is locked")
        return real(sql, *params)
    w.rows = rows
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["disable"]["stored_enabled"] is None and r["disable"]["confirmed"] is False
    assert "database is locked" in r["disable"]["verify_error"] and r["verdict"] == "failed"


def test_a_thrown_cleanup_still_checks_evidence_and_saves(w, monkeypatch):
    w.prepare()
    happy(w)

    def boom(self):
        raise OSError("taskkill missing")
    monkeypatch.setattr(proof.Proof, "cleanup", boom)
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and "cleanup: OSError" in " ".join(r["why"])
    assert "config_sha256_after" in r and r["disable"]["confirmed"] is True


def test_an_unsaveable_result_is_printed_in_full(w, monkeypatch):
    w.prepare()
    happy(w)
    real = proof.save

    def save(path, data):
        if path.name.endswith(".result.json"):
            raise OSError("disk full")
        real(path, data)
    monkeypatch.setattr(proof, "save", save)
    proof.run(w, w.state_path)
    printed = [l for l in w.lines if l.startswith("RESULT NOT SAVED")]
    assert printed and '"verdict": "passed"' in printed[0]


@pytest.mark.parametrize("spoil, verdict, why", [
    ("config", "failed", "config.toml changed"),
    ("stray", "failed", "new session files"),
    ("image", "inconclusive", "no executable identity"),
    ("reservation", "failed", "not released the reservation"),
    ("usage", "failed", "recorded usage"),
    ("binding", "failed", "binding changed"),
    ("cli", "inconclusive", "registered cli changed"),
])
def test_a_pass_needs_its_final_evidence(w, spoil, verdict, why):
    """Each of these used to leave a `passed` verdict standing."""
    w.prepare()
    happy(w)
    if spoil == "config":
        w.at(1150, lambda: w.config.write_text("changed\n"))
    elif spoil == "stray":
        w.at(1290, lambda: setattr(w, "stray", ["unexpected-session.jsonl"]))  # final sample only
    elif spoil == "image":
        w.images.update({501: None, 502: None})
    elif spoil == "reservation":
        w.at(1300, lambda: w.sql("INSERT INTO reservations VALUES ('codex:x', 'codex-lead', 'a102-502', 0)"))
    elif spoil == "usage":
        w.at(1300, lambda: w.sql("UPDATE attempts SET usage_recorded = 0 WHERE pid = 502"))
    elif spoil == "binding":
        w.at(1300, lambda: w.sql("UPDATE sessions SET workspace = 'C:\\elsewhere'"))
    else:
        w.at(1300, lambda: w.cli_file.write_bytes(b"updated"))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == verdict and why in " ".join(r["why"])


def test_a_second_driver_in_this_process_cannot_claim_the_same_proof(w, monkeypatch):
    """Codex's interleaving: pause the first caller before it saves its claim."""
    w.prepare()
    happy(w)
    enables = []
    real_cli, real_save = w.relay_cli, proof.save
    inner = []

    def cli(command, flag, lead):
        if command == "enable":
            enables.append(w.t)
        return real_cli(command, flag, lead)

    def save(path, data):
        if not inner and data.get("status") == "claimed":
            inner.append(proof.run(w, w.state_path))         # the second caller, mid-claim
        real_save(path, data)
    w.relay_cli = cli
    monkeypatch.setattr(proof, "save", save)
    assert proof.run(w, w.state_path) == 0
    assert inner == [1] and len(enables) == 1
    assert "another proof driver is running" in " ".join(w.lines)
    assert w.result()["verdict"] == "passed"


HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {repo!r})
    from lead_relay_backends import acquire_lock
    fd = acquire_lock(__import__("pathlib").Path({lock!r}))
    print("held", flush=True)
    sys.stdin.read()
""")


@pytest.fixture
def other_driver(w):
    """A real second process holding the proof driver's lock."""
    lock = str(w.state_path.with_name(w.state_path.name + ".lock"))
    child = subprocess.Popen([sys.executable, "-c", HOLDER.format(repo=str(proof.HERE), lock=lock)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    yield child
    child.stdin.close()
    child.wait(10)


def test_a_live_driver_in_another_process_blocks_run(w, other_driver):
    w.prepare()
    assert proof.run(w, w.state_path) == 1
    assert w.enabled() == 0 and "another proof driver is running" in w.lines[-1]
    assert json.loads(w.state_path.read_text())["status"] == "prepared"


def test_a_live_driver_in_another_process_blocks_prepare(w, other_driver):
    assert proof.prepare(w, w.state_path, w.cli, proof.sha256(w.cli_file), proof.sha256(w.config)) == 1
    assert not w.state_path.exists()


def test_an_interrupted_claim_is_kept_for_reconciliation(w):
    state = w.prepare()
    state["status"] = "claimed"
    w.state_path.write_text(json.dumps(state))
    assert proof.prepare(w, w.state_path, w.cli, proof.sha256(w.cli_file), proof.sha256(w.config)) == 1
    assert proof.run(w, w.state_path) == 1
    assert json.loads(w.state_path.read_text())["proof_id"] == "abcd1234"
    assert "reconcile" in " ".join(w.lines)


def test_an_existing_result_is_never_overwritten(w):
    w.prepare()
    proof.result_path(w.state_path, "abcd1234").write_text('{"verdict": "earlier"}')
    assert proof.run(w, w.state_path) == 1
    assert json.loads(proof.result_path(w.state_path, "abcd1234").read_text()) == {"verdict": "earlier"}


def test_a_probe2_delivered_without_its_own_launch_is_not_a_pass(w):
    """e.g. an ACK from a reopened app: no headless launch carried probe2."""
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.set_delivery(101, "delivered"))
    w.at(1050, lambda: w.deliver(102, "claude-lead", p2(w), "held"))
    w.at(1200, lambda: (w.exit(101, 501), w.set_delivery(102, "delivered")))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "expired" and "102" not in r["launches"]


def test_an_overlap_between_samples_is_caught_from_the_relay_rows(w):
    """Codex, #133 at 317a547: probe2 launches at 1199, probe1 ends at 1200,
    and no 2 s sample sees both alive. The recorded times still decide."""
    w.prepare()
    w.at(1030, lambda: w.deliver(101, "admin", p1(w)))
    w.at(1040, lambda: w.launch(101, 501))
    w.at(1100, lambda: w.set_delivery(101, "delivered"))
    w.at(1050, lambda: w.deliver(102, "claude-lead", p2(w), "held"))

    def overlap():
        w.t = 1199
        w.launch(102, 502)
        w.t = 1200
        w.exit(101, 501)
    w.at(1199, overlap)
    w.at(1250, lambda: w.set_delivery(102, "delivered"))
    w.at(1300, lambda: w.exit(102, 502))
    assert proof.run(w, w.state_path) == 1
    r = w.result()
    assert r["verdict"] == "failed" and "before the probe1 run ended" in " ".join(r["why"])


def test_unrecorded_end_timing_is_never_a_pass(w):
    w.prepare()
    happy(w)
    w.at(1300, lambda: w.sql("UPDATE attempts SET ended_at = NULL WHERE pid = 501"))
    assert proof.run(w, w.state_path) == 1
    assert w.result()["verdict"] == "expired"
