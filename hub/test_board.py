"""The leads' work board and the relay snapshot behind the chat page (#1737)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import board  # noqa: E402
from test_hub import basic, load_hub  # noqa: E402

DAY = 86400.0


class World:
    """The board router alone, with a controllable clock and identity."""

    def __init__(self, tmp_path):
        self.t = [1_800_000_000.0]
        path = str(tmp_path / "board.db")
        board.ensure_database(path)

        def authenticate(x_who: str = Header(default="")) -> str:
            if not x_who:
                raise HTTPException(status_code=401)
            return x_who

        app = FastAPI()
        app.include_router(board.build_router(authenticate=authenticate, db_path=path,
                                              clock=lambda: self.t[0]))
        self.client = TestClient(app)

    def as_(self, who, method, url, json=None):
        return self.client.request(method, url, json=json, headers={"X-Who": who})

    def project(self, key="comic", who="claude-lead"):
        r = self.as_(who, "POST", "/board/projects", {"key": key, "title": key.title()})
        assert r.status_code == 200, r.text
        return key

    def task(self, project="comic", who="claude-lead", **fields):
        r = self.as_(who, "POST", "/board/tasks", {"project": project, "title": "t", **fields})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def update(self, task_id, who="claude-lead", **fields):
        return self.as_(who, "POST", f"/board/tasks/{task_id}", fields)

    def board(self, who="gemini"):
        r = self.as_(who, "GET", "/board")
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_any_component_reads_but_only_leads_and_the_operator_write(w):
    w.project()
    assert w.as_("gemini", "GET", "/board").status_code == 200
    assert w.as_("gemini", "POST", "/board/projects", {"key": "x", "title": "X"}).status_code == 403
    assert w.as_("relay", "POST", "/board/tasks", {"project": "comic", "title": "t"}).status_code == 403
    for who in ("claude-lead", "codex-lead", "admin"):
        w.task(who=who)
    assert w.as_("", "GET", "/board").status_code == 401


def test_a_task_is_done_only_with_evidence(w):
    w.project()
    refused = w.as_("claude-lead", "POST", "/board/tasks",
                    {"project": "comic", "title": "t", "status": "done"})
    assert refused.status_code == 422
    tid = w.task()
    assert w.update(tid, status="done").status_code == 422
    assert w.update(tid, status="done", link="https://github.com/o/r/pull/1").status_code == 200
    # Blanking the evidence of a done task is refused too.
    assert w.update(tid, link="   ").status_code == 422
    assert w.board()["tasks"][0]["link"] == "https://github.com/o/r/pull/1"


def test_status_times_and_reopening(w):
    w.project()
    tid = w.task()
    task = w.board()["tasks"][0]
    assert (task["started_at"], task["completed_at"]) == (None, None)

    w.t[0] += 60
    w.update(tid, status="in_progress")
    w.t[0] += 60
    w.update(tid, status="done", link="L")
    task = w.board()["tasks"][0]
    assert task["started_at"] == w.t[0] - 60 and task["completed_at"] == w.t[0]

    w.update(tid, status="review")
    task = w.board()["tasks"][0]
    assert task["completed_at"] is None, "a reopened task must not count as completed"
    assert task["started_at"] == w.t[0] - 60, "the first start is kept"


def test_unknown_status_and_cross_project_subtasks_are_refused(w):
    w.project("comic")
    w.project("swarm")
    parent = w.task("comic")
    assert w.update(parent, status="finished").status_code == 422
    r = w.as_("claude-lead", "POST", "/board/tasks",
              {"project": "swarm", "title": "sub", "parent_id": parent})
    assert r.status_code == 422
    assert w.task("comic", parent_id=parent)
    assert w.as_("claude-lead", "POST", "/board/tasks",
                 {"project": "nope", "title": "t"}).status_code == 404


def test_every_change_is_attributed_to_the_authenticated_writer(w):
    w.project()
    tid = w.task(who="codex-lead", owner="codex-lead")
    w.update(tid, who="claude-lead", owner="claude-lead")
    events = w.board()["recent_events"]
    assert [e["by"] for e in events] == ["claude-lead", "codex-lead"]
    assert '"owner": ["codex-lead", "claude-lead"]' in events[0]["change"]
    assert w.update(tid, owner="claude-lead").json()["changed"] == []
    assert len(w.board()["recent_events"]) == 2, "a no-op writes no event"


def test_stats_and_the_labelled_estimate(w):
    w.project()
    assert w.board()["stats"]["estimate_days_remaining"] is None
    ids = [w.task() for _ in range(6)]
    stats = w.board()["stats"]
    assert stats["open_tasks"] == 6 and stats["estimate_days_remaining"] is None, \
        "no recent completions, so no projection rather than a made-up one"

    for tid in ids[:2]:
        w.update(tid, status="done", link="L")
    stats = w.board()["stats"]
    # 2 done in the 7-day window: 2/7 per day, 4 open -> 14 days.
    assert stats["completion_rate_per_day"] == round(2 / 7, 2)
    assert stats["estimate_days_remaining"] == 14.0
    assert stats["projects"]["comic"]["percent_done"] == 33
    assert stats["projects"]["comic"]["estimate_days_remaining"] == 14.0
    assert "Estimate only" in stats["estimate_note"]

    w.t[0] += 8 * DAY
    stats = w.board()["stats"]
    assert stats["completion_rate_per_day"] == 0 and stats["estimate_days_remaining"] is None
    assert stats["projects"]["comic"]["counts"]["done"] == 2, "history is kept, only the rate ages"


def test_dropped_tasks_are_neither_open_nor_done(w):
    w.project()
    tid = w.task()
    w.update(tid, status="dropped")
    p = w.board()["stats"]["projects"]["comic"]
    assert (p["open"], p["counts"]["done"], p["percent_done"]) == (0, 0, None)


def test_only_the_relay_reports_relay_status_and_staleness_is_shown(w):
    r = w.as_("gemini", "GET", "/relay/status").json()
    assert r == {"available": False, "reason": "the relay has not reported yet"}
    assert w.as_("claude-lead", "POST", "/relay/status", {"x": 1}).status_code == 403
    assert w.as_("admin", "POST", "/relay/status", {"x": 1}).status_code == 403
    assert w.as_("relay", "POST", "/relay/status", {"chain": 1}).status_code == 200

    r = w.as_("gemini", "GET", "/relay/status").json()
    assert (r["available"], r["stale"], r["snapshot"]) == (True, False, {"chain": 1})
    w.t[0] += board.RELAY_STALE_SECONDS + 1
    assert w.as_("gemini", "GET", "/relay/status").json()["stale"] is True


def test_an_oversized_relay_snapshot_is_refused(w):
    big = {"x": "y" * board.MAX_SNAPSHOT_BYTES}
    assert w.as_("relay", "POST", "/relay/status", big).status_code == 413


def test_the_hub_mounts_the_board_behind_basic_auth(monkeypatch, tmp_path):
    hub = load_hub(monkeypatch, tmp_path,
                   credentials="admin:a,claude-lead:c,relay:r,gemini:g")
    client = TestClient(hub.app)
    assert client.get("/board").status_code == 401
    assert client.get("/board", headers=basic("gemini", "g")).status_code == 200
    r = client.post("/board/projects", json={"key": "swarm", "title": "Swarm"},
                    headers=basic("claude-lead", "c"))
    assert r.status_code == 200
    assert client.post("/relay/status", json={"a": 1}, headers=basic("relay", "r")).status_code == 200
    assert (tmp_path / "board.db").exists(), "BOARD_DB is honoured, not /data"
