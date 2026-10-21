"""Finite OPEN-watcher state tests: fake hub/heads/clock, no native schedule.

Every write is a temporary pilot database. No production state, credential,
Codex chat history or actual GitHub PR is changed by this file.
"""
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

import codex_hive_watch as watch
import lead_chat

THREAD = "01a14068-d723-76a0-a86d-c7d7b34c1b30"
HEAD = "a" * 40
CHAT_HASH = "c" * 64
OTHER = "b" * 40
TOKEN = "abcdefghijklmnopqrstuvwxy12345"
REPORT = "https://github.com/Decksx/agent-swarm/pull/126#issuecomment-12345"


def handoff(mid=11, *, number=126, head=HEAD, sender="claude-lead"):
    return dict(id=mid, sender=sender, target="@codex-lead",
                content=f"HANDOFF @codex-lead: swarm #{number} exact {head}",
                timestamp_utc="1970-01-01T00:16:39Z")


class Hub:
    def __init__(self):
        self.rows, self.posts, self.calls = [], [], []
        self.is_paused, self.unconfirmed, self.post_error = False, False, False
        self.found = []

    def paused(self):
        self.calls.append("paused")
        return self.is_paused

    def read(self, cursor):
        self.calls.append("read")
        return [r for r in self.rows if not isinstance(r, dict)
                or type(r.get("id")) is not int or r["id"] > cursor]

    def mentions(self, row):
        return row.get("target") == "@codex-lead"

    def find(self, text, baseline):
        self.calls.append("find")
        return self.found

    def post(self, text):
        self.calls.append("post")
        self.posts.append(text)
        if self.post_error:
            raise OSError("lost response")
        return SimpleNamespace(state="unconfirmed" if self.unconfirmed else "confirmed",
                               message_id=100)


class World:
    def __init__(self, tmp_path, *, limit=12):
        self.root, self.control = tmp_path / "pilot", tmp_path / "control"
        self.control.mkdir()
        self.hub = Hub()
        self.time = 1000.0
        self.head = HEAD
        self.head_calls = []
        watch.initialize(self.root, thread=THREAD, baseline=10, expires=1600,
                         control=self.control, chat_sha256=CHAT_HASH,
                         max_turns=limit, now=lambda: self.time)
        self.w = watch.Watcher(self.root, api=self.hub, resolve=self.resolve,
                               actual=(THREAD, str(uuid.uuid4())), now=lambda: self.time)

    def resolve(self, repo, number):
        self.head_calls.append((repo, number))
        return self.head

    def next_turn(self):
        self.w.actual = (THREAD, str(uuid.uuid4()))

    def notice(self, mid=12, source=11, token=TOKEN):
        self.hub.rows.append(dict(id=mid, sender="relay", target="@codex-lead",
                                 content=f"RELAY DELIVER #{source} → @codex-lead attempt={token} (live)"))


@pytest.fixture
def world(tmp_path):
    value = World(tmp_path)
    yield value
    value.w.close()


def test_claim_is_durable_and_bound_to_source_and_actual_head(world):
    world.hub.rows = [handoff()]
    result = world.w.poll()
    assert result["state"] == "work"
    assert (result["source_id"], result["head"], result["repo"], result["pr"]) == (
        11, HEAD, "Decksx/agent-swarm", 126)
    assert result["claimed_at"] == 1000 and result["source_timestamp_utc"].endswith("16:39Z")
    assert world.w.meta("cursor") == "11"
    stored = world.w.db.execute("SELECT state, owner_turn FROM work").fetchone()
    assert tuple(stored) == ("active", world.w.actual[1])
    assert world.hub.posts == []
    assert world.w.finish(result["claim"], REPORT)["state"] == "recorded"


def test_repeated_poll_in_one_turn_cannot_return_work_twice(world):
    world.hub.rows = [handoff()]
    assert world.w.poll()["state"] == "work"
    calls = list(world.hub.calls)
    assert world.w.poll() == {"state": "already-polled"}
    assert world.hub.calls == calls


def test_an_unfinished_claim_is_not_taken_over_by_another_turn(world):
    world.hub.rows = [handoff()]
    first = world.w.poll()
    world.next_turn()
    calls = list(world.hub.calls)
    assert world.w.poll()["reason"] == "unfinished-poll-or-claim"
    assert world.hub.calls == calls
    with pytest.raises(watch.WatchError, match="owned"):
        world.w.finish(first["claim"], REPORT)


def test_a_crashed_poll_marker_refuses_takeover_before_hub_access(world):
    world.w.set_meta("polling", str(uuid.uuid4()))
    assert world.w.poll()["reason"] == "unfinished-poll-or-claim"
    assert not world.hub.calls


def test_repeated_message_for_same_head_is_not_a_second_task(world):
    world.hub.rows = [handoff(), handoff(12)]
    first = world.w.poll()
    world.w.finish(first["claim"], REPORT)
    world.next_turn()
    assert world.w.poll()["state"] == "idle"
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 1
    assert world.w.meta("cursor") == "12"


def test_a_new_head_of_the_same_pr_is_new_work(world):
    world.hub.rows = [handoff()]
    first = world.w.poll()
    world.w.finish(first["claim"], REPORT)
    world.head = OTHER
    world.hub.rows.append(handoff(12, head=OTHER))
    world.next_turn()
    second = world.w.poll()
    assert second["state"] == "work" and second["claim"] != first["claim"]
    assert second["head"] == OTHER


def test_one_turn_claims_at_most_one_of_two_persisted_handoffs(world):
    world.hub.rows = [handoff(), handoff(12, number=127)]
    first = world.w.poll()
    assert first["pr"] == 126
    assert world.w.db.execute("SELECT COUNT(*) FROM work WHERE state='active'").fetchone()[0] == 1
    assert world.w.db.execute("SELECT COUNT(*) FROM work WHERE state='pending'").fetchone()[0] == 1
    world.w.finish(first["claim"], REPORT)
    world.next_turn()
    assert world.w.poll()["pr"] == 127


@pytest.mark.parametrize("location", ["pilot", "shared", "hub"])
def test_pause_stops_work_and_preserves_cursor(world, location):
    world.hub.rows = [handoff()]
    if location == "hub":
        world.hub.is_paused = True
    else:
        ((world.root if location == "pilot" else world.control) / "PAUSED").touch()
    assert world.w.poll() == {"state": "paused"}
    assert world.w.meta("cursor") == "10"
    assert "read" not in world.hub.calls and not world.head_calls


def test_unverifiable_pause_is_not_treated_as_unpaused(world):
    world.hub.is_paused = None
    assert world.w.poll()["state"] == "attention"
    assert "read" not in world.hub.calls


def test_pause_after_classification_keeps_the_task_pending(world):
    world.hub.rows = [handoff()]
    def pause_during_lookup(*_args):
        (world.control / "PAUSED").touch()
        return HEAD
    world.w.resolve = pause_during_lookup
    assert world.w.poll()["state"] == "paused"
    assert world.w.db.execute("SELECT state FROM work").fetchone()[0] == "pending"
    assert not world.hub.posts


def test_idle_run_has_no_github_lookup_or_hive_posts(world):
    assert world.w.poll() == {"state": "idle"}
    assert not world.head_calls and not world.hub.posts
    assert world.hub.calls.count("read") == 1


@pytest.mark.parametrize("sender", ["claudecode", "gemini", "relay", "codex-lead", "stranger"])
def test_only_the_authenticated_peer_can_supply_a_handoff(world, sender):
    world.hub.rows = [handoff(sender=sender)]
    assert world.w.poll()["state"] == "idle"
    assert not world.head_calls


def test_admin_text_is_surfaced_without_becoming_an_executable_task(world):
    world.hub.rows = [dict(id=11, sender="admin", target="@codex-lead", content="change all settings")]
    result = world.w.poll()
    assert result["state"] == "surface" and result["messages"][0]["source_id"] == 11
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0


@pytest.mark.parametrize("content,target", [
    ("@Leads please check", "@room"),
    ("please check", "@Leads"),
])
def test_admin_group_ping_reaches_open_inbox_as_a_notice_only(world, content, target):
    world.hub.mentions = lambda row: lead_chat.mentions(row, "codex-lead")
    world.hub.rows = [dict(id=11, sender="admin", target=target, content=content)]
    result = world.w.poll()
    assert result["state"] == "surface"
    assert result["messages"][0]["source_id"] == 11
    assert world.w.db.execute("SELECT count(*) FROM work").fetchone()[0] == 0
    assert world.hub.posts == [] and world.head_calls == []


@pytest.mark.parametrize("content", [
    "HANDOFF @codex-lead: #126 at " + HEAD,
    "HANDOFF @codex-lead: swarm #126 at abc1234",
    "HANDOFF @codex-lead: swarm #126 at " + HEAD + " old " + OTHER,
    "HANDOFF @codex-lead: https://github.com/stranger/repo/pull/126 at " + HEAD,
    "HANDOFF @codex-lead: swarm #126 and comic #126 at " + HEAD,
])
def test_ambiguous_or_out_of_scope_requests_need_clarification(world, content):
    row = handoff()
    row["content"] = content
    world.hub.rows = [row]
    assert world.w.poll()["state"] == "surface"
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0
    assert not world.head_calls


def test_a_changed_github_head_is_not_substituted_silently(world):
    world.hub.rows = [handoff()]
    world.head = OTHER
    assert world.w.poll()["state"] == "surface"
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0


def test_a_queued_head_is_rechecked_before_becoming_active(world):
    world.hub.rows = [handoff()]
    heads = iter([HEAD, OTHER])
    world.w.resolve = lambda *_: next(heads)
    result = world.w.poll()
    assert result["state"] == "surface" and result["messages"][0]["source_id"] == 11
    assert world.w.db.execute("SELECT state FROM work").fetchone()[0] == "stale"


def test_classification_failure_cannot_advance_cursor_without_its_claim(world, monkeypatch):
    world.hub.rows = [handoff()]
    original = world.w.classify
    def interrupted(row):
        original(row)
        raise OSError("failure before cursor commit")
    monkeypatch.setattr(world.w, "classify", interrupted)
    assert world.w.poll()["state"] == "attention"
    assert world.w.meta("cursor") == "10"
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0
    assert world.w.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_relay_notice_acks_once_but_cannot_become_a_second_task(world):
    world.hub.rows = [handoff()]
    world.notice()
    world.notice(mid=13)
    first = world.w.poll()
    assert world.hub.posts == [f"ACK #11 {TOKEN}"]
    assert world.w.db.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 1
    assert world.w.db.execute("SELECT COUNT(*) FROM acks").fetchone()[0] == 1
    world.w.finish(first["claim"], REPORT)
    world.next_turn()
    assert world.w.poll()["state"] == "idle"
    assert len(world.hub.posts) == 1


def test_an_existing_own_ack_is_reconciled_without_posting(world):
    world.hub.rows = [handoff()]
    world.notice()
    world.hub.found = [100]
    assert world.w.poll()["state"] == "work"
    assert not world.hub.posts
    assert world.w.db.execute("SELECT state, receipt FROM acks").fetchone()[1] == 100


@pytest.mark.parametrize("lost", ["receipt", "exception"])
def test_uncertain_ack_is_retained_and_not_retried(world, lost):
    world.hub.rows = [handoff()]
    world.notice()
    world.hub.unconfirmed = lost == "receipt"
    world.hub.post_error = lost == "exception"
    assert world.w.poll()["state"] == "attention"
    world.next_turn()
    assert world.w.poll()["reason"] == "uncertain-ack"
    assert len(world.hub.posts) == 1
    assert world.w.db.execute("SELECT COUNT(*) FROM work WHERE state='active'").fetchone()[0] == 0


def test_unknown_relay_source_is_not_acked_or_made_into_work(world):
    world.notice(source=5)
    assert world.w.poll()["state"] == "surface"
    assert not world.hub.posts and not world.head_calls


def test_expiry_before_check_prevents_hub_access(world):
    world.time = 1600
    assert world.w.poll() == {"state": "expired"}
    assert not world.hub.calls


def test_expiry_during_head_lookup_prevents_claim_and_post(world):
    world.hub.rows = [handoff()]
    world.notice()
    def expire(*_args):
        world.time = 1600
        return HEAD
    world.w.resolve = expire
    assert world.w.poll()["state"] == "expired"
    assert not world.hub.posts
    assert world.w.db.execute("SELECT COUNT(*) FROM work WHERE state='active'").fetchone()[0] == 0


def test_turn_budget_is_durable_and_cannot_be_reset_by_reopening(world):
    for index in range(12):
        result = world.w.poll()
        assert result["state"] == "idle"
        assert result.get("stop_after_turn", False) == (index == 11)
        world.next_turn()
    world.w.close()
    world.w = watch.Watcher(world.root, api=world.hub, actual=(THREAD, str(uuid.uuid4())),
                            resolve=world.resolve, now=lambda: world.time)
    calls = list(world.hub.calls)
    assert world.w.poll() == {"state": "budget-exhausted"}
    assert world.hub.calls == calls


def test_initialize_cannot_overwrite_a_pilot_or_increase_its_limits(world):
    with pytest.raises(FileExistsError):
        watch.initialize(world.root, thread=THREAD, baseline=0, expires=1500,
                         control=world.control, chat_sha256=CHAT_HASH, now=lambda: 1000)
    for limit, expires in [(13, 1500), (12, 5000), (0, 1500)]:
        with pytest.raises(watch.WatchError):
            watch.initialize(world.root / "bad", thread=THREAD, baseline=10,
                             expires=expires, max_turns=limit, control=world.control,
                             chat_sha256=CHAT_HASH, now=lambda: 1000)
    assert world.w.meta("cursor") == "10"


def test_wrong_actual_thread_refuses_before_api_access(world):
    with pytest.raises(watch.WatchError):
        watch.Watcher(world.root, api=world.hub, actual=(str(uuid.uuid4()), str(uuid.uuid4())))
    assert not world.hub.calls


def test_finish_requires_the_exact_claim_owner_and_pr_report(world):
    world.hub.rows = [handoff()]
    first = world.w.poll()
    for report in [REPORT.replace("126", "127"), "https://example.com/report", REPORT + "evil"]:
        with pytest.raises(watch.WatchError):
            world.w.finish(first["claim"], report)
    world.w.finish(first["claim"], REPORT, blocked=True)
    assert world.w.db.execute("SELECT state FROM work").fetchone()[0] == "blocked"
    with pytest.raises(watch.WatchError):
        world.w.finish(first["claim"], REPORT)


def test_bounded_batch_does_not_skip_the_next_handoff(world):
    world.hub.rows = [dict(id=i, sender="narrator", content="ignored") for i in range(11, 61)]
    world.hub.rows.append(handoff(61))
    world.hub.rows.reverse()
    assert world.w.poll()["state"] == "idle"
    assert world.w.meta("cursor") == "60"
    world.next_turn()
    assert world.w.poll()["source_id"] == 61


@pytest.mark.parametrize("bad", [[None], [dict(id=True, content="bad")], [handoff(), handoff()]])
def test_malformed_batch_cannot_advance_cursor(world, bad):
    world.hub.rows = bad
    assert world.w.poll()["state"] == "attention"
    assert world.w.meta("cursor") == "10"


def _history(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE thread_turns(thread_id, turn_id, status, started_at, completed_at, duration_ms)")
        db.executemany("INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?)", rows)


def test_identity_and_metrics_read_only_target_turn_metadata(world, tmp_path):
    path = tmp_path / "history.sqlite"
    turn = world.w.actual[1]
    _history(path, [(THREAD, turn, "inProgress", 1000, None, None),
                    (str(uuid.uuid4()), str(uuid.uuid4()), "inProgress", 1000, None, None)])
    assert watch.identity(path, {"CODEX_THREAD_ID": THREAD}) == (THREAD, turn)
    assert world.w.poll()["state"] == "idle"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE thread_turns SET status='completed', completed_at=1002, duration_ms=2000 "
                   "WHERE thread_id=?", (THREAD,))
    metrics = world.w.metrics(path)
    assert metrics[0]["terminal_metadata"] == ["completed", 1000, 1002, 2000]
    assert metrics[0]["token_usage"] is None
    assert "not exposed" in metrics[0]["token_usage_reason"]


def test_identity_fails_closed_on_missing_or_overlapping_metadata(tmp_path):
    absent = tmp_path / "absent.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        watch.identity(absent, {"CODEX_THREAD_ID": THREAD})
    assert not absent.exists()
    path = tmp_path / "history.sqlite"
    _history(path, [(THREAD, str(uuid.uuid4()), "inProgress", 1000, None, None)] * 2)
    with pytest.raises(watch.WatchError):
        watch.identity(path, {"CODEX_THREAD_ID": THREAD})


def test_runtime_api_refuses_changed_production_helper(tmp_path, monkeypatch):
    path = tmp_path / "lead_chat.py"
    path.write_text("raise AssertionError('changed code must not execute')", encoding="utf-8")
    monkeypatch.setattr(watch, "CHAT_PATH", path)
    with pytest.raises(watch.WatchError, match="bytes changed"):
        watch.production_api(CHAT_HASH)


@pytest.mark.parametrize("ending", ["evil", "0bad", ".example", "_suffix"])
def test_github_reference_cannot_be_a_prefix_of_a_different_path(ending):
    assert watch.reference("https://github.com/Decksx/agent-swarm/pull/126" + ending) is None


@pytest.mark.parametrize("stop", ["pause", "expiry"])
def test_stop_between_ack_lookup_and_post_keeps_ack_pending(world, stop):
    world.hub.rows = [handoff()]
    world.notice()
    def stop_in_find(*_args):
        if stop == "pause":
            (world.control / "PAUSED").touch()
        else:
            world.time = 1600
        return []
    world.hub.find = stop_in_find
    assert world.w.poll()["state"] in ("paused", "expired")
    assert not world.hub.posts
    assert world.w.db.execute("SELECT state FROM acks").fetchone()[0] == "pending"
    assert world.w.db.execute("SELECT state FROM work").fetchone()[0] == "pending"


def test_second_process_cannot_poll_while_first_owns_durable_marker(world, tmp_path):
    # The parent reaches the network with its polling marker already committed.
    script = tmp_path / "second.py"
    script.write_text('''import json, sys
from pathlib import Path
import codex_hive_watch as watch
class Forbidden:
    def paused(self): raise AssertionError("second process touched hub")
w = watch.Watcher(Path(sys.argv[1]), api=Forbidden(), actual=(sys.argv[2], sys.argv[3]), now=lambda: 1000)
try: print(json.dumps(w.poll()))
finally: w.close()
''', encoding="utf-8")
    original_read = world.hub.read
    def competing_read(cursor):
        child = subprocess.run([sys.executable, str(script), str(world.root), THREAD,
                                str(uuid.uuid4())], capture_output=True, text=True,
                               timeout=20, env={**__import__("os").environ,
                                                "PYTHONPATH": str(Path(watch.__file__).parent)})
        assert child.returncode == 0, child.stderr
        assert json.loads(child.stdout)["reason"] == "unfinished-poll-or-claim"
        return original_read(cursor)
    world.hub.read = competing_read
    world.hub.rows = [handoff()]
    assert world.w.poll()["state"] == "work"
    assert world.w.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


@pytest.mark.parametrize("parent", ["git", "codex"])
def test_initialize_refuses_git_or_codex_state(tmp_path, monkeypatch, parent):
    base = tmp_path / "base"
    base.mkdir()
    if parent == "git":
        (base / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    else:
        monkeypatch.setattr(watch.Path, "home", lambda: tmp_path)
        base = tmp_path / ".codex"
        base.mkdir()
    root = base / "pilot"
    with pytest.raises(watch.WatchError, match="outside Git"):
        watch.initialize(root, thread=THREAD, baseline=10, expires=1600,
                         control=tmp_path, chat_sha256=CHAT_HASH, now=lambda: 1000)
    assert not root.exists()


def test_github_head_lookup_is_allowlisted_read_only_and_bounded(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps({"headRefOid": HEAD}))
    monkeypatch.setattr(watch.subprocess, "run", run)
    for repo, number in [("evil/repo", 126), ("Decksx/agent-swarm", True)]:
        with pytest.raises(watch.WatchError):
            watch.github_head(repo, number)
    assert not calls
    assert watch.github_head("Decksx/agent-swarm", 126) == HEAD
    argv, options = calls[0]
    assert argv == ["gh", "pr", "view", "126", "--repo", "Decksx/agent-swarm",
                    "--json", "headRefOid"]
    assert options["timeout"] == 30 and "shell" not in options


def test_recording_completion_does_not_load_chat_or_touch_hub(world, monkeypatch, capsys):
    world.hub.rows = [handoff()]
    packet = world.w.poll()
    monkeypatch.setattr(watch, "identity", lambda: world.w.actual)
    def forbidden():
        raise AssertionError("local completion must not load hub adapter")
    monkeypatch.setattr(watch, "production_api", forbidden)
    assert watch.main(["--root", str(world.root), "finish", "--claim", packet["claim"],
                       "--report", REPORT]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "recorded"


@pytest.mark.parametrize("change", ["nothing", "expiry", "pause", "head", "owner"])
def test_guard_rechecks_current_owner_bounds_and_head_before_side_effect(world, change):
    world.hub.rows = [handoff()]
    packet = world.w.poll()
    calls = len(world.hub.calls)
    if change == "expiry":
        world.time = 1600
    elif change == "pause":
        world.hub.is_paused = True
    elif change == "head":
        world.head = OTHER
    elif change == "owner":
        world.next_turn()
    if change == "owner":
        with pytest.raises(watch.WatchError, match="owned"):
            world.w.guard(packet["claim"])
    else:
        expected = {"nothing": "ready", "expiry": "expired", "pause": "paused", "head": "attention"}
        assert world.w.guard(packet["claim"])["state"] == expected[change]
    if change in ("owner", "expiry"):
        assert len(world.hub.calls) == calls
    assert world.w.db.execute("SELECT state FROM work").fetchone()[0] == "active"
    assert not world.hub.posts


def test_guard_rechecks_pause_after_its_head_lookup(world):
    world.hub.rows = [handoff()]
    packet = world.w.poll()
    def pause(*_args):
        (world.control / "PAUSED").touch()
        return HEAD
    world.w.resolve = pause
    assert world.w.guard(packet["claim"])["state"] == "paused-or-expired"


@pytest.mark.parametrize("notice", [
    dict(id=12, sender="admin", target="@codex-lead", content="@claude-lead @codex-lead good work you two"),
    dict(id=12, sender="claude-lead", content="HANDOFF @codex-lead: swarm #126 at shortsha"),
    dict(id=12, sender="relay", content=f"RELAY DELIVER #5 → @codex-lead attempt={TOKEN} (live)"),
])
def test_surface_message_cannot_hide_pending_work_or_repeat_next_turn(world, notice):
    world.hub.rows = [handoff(), notice]
    packet = world.w.poll()
    assert packet["state"] == "work" and packet["source_id"] == 11
    assert packet["notices"][0]["source_id"] == 12
    assert packet["notices"][0]["reason"].startswith("surface:")
    world.w.finish(packet["claim"], REPORT)
    world.next_turn()
    assert world.w.poll() == {"state": "idle"}


def test_surface_only_message_is_durable_and_does_not_stop_next_poll(world):
    world.hub.rows = [dict(id=11, sender="admin", target="@codex-lead", content="thanks")]
    assert world.w.poll()["state"] == "surface"
    assert world.w.meta("cursor") == "11"
    world.next_turn()
    world.hub.rows.append(handoff(12))
    assert world.w.poll()["source_id"] == 12


def test_failed_pre_send_pause_check_does_not_create_uncertain_ack(world):
    world.hub.rows = [handoff()]
    world.notice()
    original = world.hub.paused
    def fail_after_find():
        if "find" in world.hub.calls:
            raise watch.WatchError("hub pause unavailable")
        return original()
    world.hub.paused = fail_after_find
    result = world.w.poll()
    assert result == {"state": "attention", "reason": "hub pause unavailable"}
    assert world.w.db.execute("SELECT state FROM acks").fetchone()[0] == "pending"
    assert not world.hub.posts
    world.hub.paused = original
    world.next_turn()
    assert world.w.poll()["state"] == "work"
    assert world.hub.posts == [f"ACK #11 {TOKEN}"]


def test_posting_marker_is_durable_immediately_before_the_actual_send(world):
    world.hub.rows = [handoff()]
    world.notice()
    original = world.hub.post
    def inspect_marker(content):
        with sqlite3.connect(world.root / "watch.sqlite") as db:
            assert db.execute("SELECT state FROM acks").fetchone()[0] == "posting"
        return original(content)
    world.hub.post = inspect_marker
    assert world.w.poll()["state"] == "work"


@pytest.mark.parametrize("label,repo", [("swarm", "Decksx/agent-swarm"), ("comic", "Decksx/cbz-automation-suite")])
def test_natural_project_pr_reference(label, repo):
    assert watch.reference(f"HANDOFF @codex-lead: {label} PR #128 at {HEAD}") == (repo, 128)


def test_init_pin_is_recorded_and_required_without_automatic_repinning(world, monkeypatch, capsys):
    assert world.w.config["chat_sha256"] == CHAT_HASH
    monkeypatch.setattr(watch, "identity", lambda: world.w.actual)
    pins = []
    def api(pin):
        pins.append(pin)
        return world.hub
    monkeypatch.setattr(watch, "production_api", api)
    assert watch.main(["--root", str(world.root), "poll"]) == 0
    # main uses real UTC; this fixture's 1970 pilot has expired. The adapter
    # still must receive its stored pin, never compute a new trusted hash.
    assert json.loads(capsys.readouterr().out)["state"] == "expired"
    assert pins == [CHAT_HASH]
    assert world.w.config["chat_sha256"] == CHAT_HASH


def test_api_executes_only_the_explicitly_pinned_helper_bytes(tmp_path, monkeypatch):
    import hashlib
    path = tmp_path / "chat.py"
    raw = b"marker = 42\n"
    path.write_bytes(raw)
    monkeypatch.setattr(watch, "CHAT_PATH", path)
    assert watch.production_api(hashlib.sha256(raw).hexdigest()) is not None
    path.write_bytes(b"raise AssertionError('changed bytes must not execute')\n")
    with pytest.raises(watch.WatchError, match="bytes changed"):
        watch.production_api(hashlib.sha256(raw).hexdigest())


def test_main_preserves_safe_watcherror_but_not_arbitrary_exception_text(world, monkeypatch, capsys):
    def refusal():
        raise watch.WatchError("unique actual in-progress turn unavailable")
    monkeypatch.setattr(watch, "identity", refusal)
    assert watch.main(["--root", str(world.root), "poll"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "unique actual in-progress turn unavailable"
    def error():
        raise OSError("arbitrary sensitive diagnostic")
    monkeypatch.setattr(watch, "identity", error)
    assert watch.main(["--root", str(world.root), "poll"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "OSError"


def test_cli_init_records_explicit_reviewed_pin_without_loading_the_hub(world, monkeypatch, capsys):
    from datetime import datetime, timezone
    import time
    root = world.root.parent / "new-init"
    expires = datetime.fromtimestamp(time.time() + 600, timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(watch, "identity", lambda: world.w.actual)
    def forbidden(*_args):
        raise AssertionError("init must not load hub adapter")
    monkeypatch.setattr(watch, "production_api", forbidden)
    assert watch.main(["--root", str(root), "init", "--thread", THREAD, "--baseline", "11",
                       "--expires", expires, "--control", str(world.control),
                       "--chat-sha256", CHAT_HASH]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "initialized"
    with sqlite3.connect(root / "watch.sqlite") as db:
        config = json.loads(db.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
    assert config["chat_sha256"] == CHAT_HASH and config["schema_version"] == 2


@pytest.mark.parametrize("bad", [None, True, "", "A" * 64, "c" * 64 + "\n"])
def test_corrupt_or_missing_init_pin_refuses_before_adapter_load(world, monkeypatch, capsys, bad):
    config = dict(world.w.config, chat_sha256=bad)
    world.w.set_meta("config", json.dumps(config))
    monkeypatch.setattr(watch, "identity", lambda: world.w.actual)
    def forbidden(*_args):
        raise AssertionError("invalid config must not load code")
    monkeypatch.setattr(watch, "production_api", forbidden)
    assert watch.main(["--root", str(world.root), "poll"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid pilot bounds or control path"
