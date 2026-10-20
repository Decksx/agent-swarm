"""The leads' work board and the relay's status snapshot (hive #1737).

David asked for the chat page to show the relay's counters, and which lead is
working on which task in each project, with the completed list, progress and
a completion projection.

Two kinds of data, deliberately kept apart from the controller:

- **The board** is the leads' own record of their work: projects, tasks and
  subtasks, an owner, a status and the evidence (a PR, issue or commit link).
  It is not the controller's task state and grants nothing. It has its own
  SQLite file, so it can never take part in a controller migration or lock.
- **The relay snapshot** is pushed by the relay, which runs on OfficePC while
  the hub runs on Tower. Only the `relay` component may write it. The page
  shows how old it is, because a stale snapshot means the relay is down, and
  silently showing old counters would claim a health nobody measured.

Writes come from the leads and the operator; every authenticated component
may read. A task only becomes `done` with evidence, so the completed list is
a list of things somebody can check.

The projection is labelled an estimate everywhere it appears. It is open tasks
divided by the recent completion rate, nothing more, and it is `None` when
there is no recent rate rather than a made-up date.
"""

import json
import sqlite3
import time
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

BOARD_WRITERS = {"claude-lead", "codex-lead", "admin", "operator"}
RELAY_COMPONENT = "relay"
STATUSES = ("todo", "in_progress", "review", "blocked", "done", "dropped")
OPEN_STATUSES = ("todo", "in_progress", "review", "blocked")
# The window the completion rate is measured over, for the projection.
RATE_WINDOW_DAYS = 7
# A snapshot older than this is shown as stale: the relay pushes every 30 s.
RELAY_STALE_SECONDS = 120
MAX_SNAPSHOT_BYTES = 64 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    key TEXT PRIMARY KEY, title TEXT NOT NULL, repo TEXT,
    status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(key),
    parent_id INTEGER REFERENCES tasks(id),
    title TEXT NOT NULL, owner TEXT, status TEXT NOT NULL,
    link TEXT, note TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    started_at REAL, completed_at REAL);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
    at REAL NOT NULL, by TEXT NOT NULL, change TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relay_status (
    id INTEGER PRIMARY KEY CHECK (id = 1), snapshot TEXT NOT NULL,
    received_at REAL NOT NULL);
"""


def ensure_database(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


class ProjectIn(BaseModel):
    key: str
    title: str
    repo: Optional[str] = None
    status: str = "active"


class TaskIn(BaseModel):
    project: str
    title: str
    owner: Optional[str] = None
    status: str = "todo"
    parent_id: Optional[int] = None
    link: Optional[str] = None
    note: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    link: Optional[str] = None
    note: Optional[str] = None


def _check_status(status: Optional[str]) -> None:
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(STATUSES)}")


def _require_evidence(status: Optional[str], link: Optional[str]) -> None:
    if status == "done" and not (link or "").strip():
        raise HTTPException(status_code=422,
                            detail="a task is done only with evidence: give a PR, issue or commit link")


def _task(conn, task_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no task {task_id}")
    return row


def stats(conn, now: float) -> dict:
    """Counts per project, recent throughput and a labelled estimate."""
    projects = {}
    for row in conn.execute("SELECT project, status, COUNT(*) AS n FROM tasks GROUP BY project, status"):
        projects.setdefault(row["project"], {s: 0 for s in STATUSES})[row["status"]] = row["n"]
    since = now - RATE_WINDOW_DAYS * 86400
    per_day = {}
    for row in conn.execute("SELECT completed_at FROM tasks WHERE status = 'done' AND completed_at > ?",
                            (since,)):
        day = time.strftime("%Y-%m-%d", time.gmtime(row["completed_at"]))
        per_day[day] = per_day.get(day, 0) + 1
    done_recent = sum(per_day.values())
    rate = done_recent / RATE_WINDOW_DAYS
    summary = {}
    for key, counts in projects.items():
        open_n = sum(counts[s] for s in OPEN_STATUSES)
        total = open_n + counts["done"]
        project_rate = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE project = ? AND status = 'done' AND completed_at > ?",
            (key, since)).fetchone()[0] / RATE_WINDOW_DAYS
        summary[key] = {
            "counts": counts, "open": open_n,
            "percent_done": round(100 * counts["done"] / total) if total else None,
            "estimate_days_remaining": round(open_n / project_rate, 1) if project_rate and open_n else None,
        }
    open_all = sum(p["open"] for p in summary.values())
    return {
        "projects": summary,
        "completed_per_day_utc": dict(sorted(per_day.items())),
        "rate_window_days": RATE_WINDOW_DAYS,
        "completion_rate_per_day": round(rate, 2),
        "open_tasks": open_all,
        "estimate_days_remaining": round(open_all / rate, 1) if rate and open_all else None,
        "estimate_note": (f"Estimate only: open tasks / tasks completed per day over the last "
                          f"{RATE_WINDOW_DAYS} days. Task sizes differ; no estimate without a recent rate."),
    }


def build_router(*, authenticate: Callable, db_path: str,
                 clock: Callable[[], float] = time.time) -> APIRouter:
    router = APIRouter(tags=["board"])

    def get_conn():
        # One connection per request, as the controller router does, and for
        # the same FastAPI threadpool reason.
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def writer(component: str = Depends(authenticate)) -> str:
        if component not in BOARD_WRITERS:
            raise HTTPException(status_code=403, detail="this component may not change the board")
        return component

    def event(conn, task_id: int, by: str, change: dict) -> None:
        conn.execute("INSERT INTO task_events (task_id, at, by, change) VALUES (?, ?, ?, ?)",
                     (task_id, clock(), by, json.dumps(change, sort_keys=True)))

    @router.get("/board")
    def board(component: str = Depends(authenticate), conn=Depends(get_conn)):
        rows = lambda q, *a: [dict(r) for r in conn.execute(q, a).fetchall()]  # noqa: E731
        return {
            "projects": rows("SELECT * FROM projects ORDER BY status, key"),
            "tasks": rows("SELECT * FROM tasks ORDER BY project, COALESCE(parent_id, id), id"),
            "recent_events": rows("SELECT * FROM task_events ORDER BY id DESC LIMIT 50"),
            "stats": stats(conn, clock()),
            "server_time": clock(),
        }

    @router.post("/board/projects")
    def put_project(req: ProjectIn, by: str = Depends(writer), conn=Depends(get_conn)):
        if not req.key.strip() or not req.title.strip():
            raise HTTPException(status_code=422, detail="key and title are required")
        now = clock()
        conn.execute(
            "INSERT INTO projects (key, title, repo, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET title = excluded.title, "
            "repo = excluded.repo, status = excluded.status, updated_at = excluded.updated_at",
            (req.key.strip(), req.title.strip(), req.repo, req.status, now, now))
        conn.commit()
        return {"status": "ok", "key": req.key.strip()}

    @router.post("/board/tasks")
    def add_task(req: TaskIn, by: str = Depends(writer), conn=Depends(get_conn)):
        _check_status(req.status)
        conn.execute("BEGIN IMMEDIATE")   # project/parent checks hold until the insert
        _require_evidence(req.status, req.link)
        if not req.title.strip():
            raise HTTPException(status_code=422, detail="title is required")
        if conn.execute("SELECT 1 FROM projects WHERE key = ?", (req.project,)).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"no project {req.project}")
        if req.parent_id is not None and _task(conn, req.parent_id)["project"] != req.project:
            raise HTTPException(status_code=422, detail="a subtask belongs to its parent's project")
        now = clock()
        cur = conn.execute(
            "INSERT INTO tasks (project, parent_id, title, owner, status, link, note, created_at, "
            "updated_at, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (req.project, req.parent_id, req.title.strip(), req.owner, req.status, req.link, req.note,
             now, now, now if req.status != "todo" else None, now if req.status == "done" else None))
        event(conn, cur.lastrowid, by, {"created": req.model_dump()})
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}

    @router.post("/board/tasks/{task_id}")
    def update_task(task_id: int, req: TaskUpdate, by: str = Depends(writer), conn=Depends(get_conn)):
        _check_status(req.status)
        # The write lock before the read (Codex, #128 at a236d22): otherwise
        # two writers validate against the same old row, and one can blank
        # the evidence of a task the other has just completed. A refusal
        # below leaves the transaction to be rolled back when it is closed.
        conn.execute("BEGIN IMMEDIATE")
        row = _task(conn, task_id)
        changes = {k: v for k, v in req.model_dump().items()
                   if v is not None and v != row[k]}
        if not changes:
            return {"status": "ok", "id": task_id, "changed": []}
        # The resulting task, not the request: blanking the link of a done
        # task is refused just like marking a task done without one.
        _require_evidence(changes.get("status", row["status"]), changes.get("link", row["link"]))
        now = clock()
        sets = dict(changes, updated_at=now)
        if "status" in changes:
            if changes["status"] != "todo" and row["started_at"] is None:
                sets["started_at"] = now
            # Re-opening clears the completion time, so it can't count twice.
            sets["completed_at"] = now if changes["status"] == "done" else None
        conn.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                     (*sets.values(), task_id))
        event(conn, task_id, by, {k: [row[k], v] for k, v in changes.items()})
        conn.commit()
        return {"status": "ok", "id": task_id, "changed": sorted(changes)}

    @router.post("/relay/status")
    def put_relay_status(snapshot: dict, component: str = Depends(authenticate),
                         conn=Depends(get_conn)):
        if component != RELAY_COMPONENT:
            raise HTTPException(status_code=403, detail="only the relay reports relay status")
        body = json.dumps(snapshot, sort_keys=True)
        if len(body) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(status_code=413, detail="relay snapshot too large")
        conn.execute("INSERT OR REPLACE INTO relay_status (id, snapshot, received_at) VALUES (1, ?, ?)",
                     (body, clock()))
        conn.commit()
        return {"status": "ok"}

    @router.get("/relay/status")
    def get_relay_status(component: str = Depends(authenticate), conn=Depends(get_conn)):
        row = conn.execute("SELECT snapshot, received_at FROM relay_status WHERE id = 1").fetchone()
        if row is None:
            return {"available": False, "reason": "the relay has not reported yet"}
        age = clock() - row["received_at"]
        return {"available": True, "received_at": row["received_at"], "age_seconds": round(age, 1),
                "stale": age > RELAY_STALE_SECONDS, "stale_after_seconds": RELAY_STALE_SECONDS,
                "snapshot": json.loads(row["snapshot"])}

    return router
