"""Rebind a lead past a run the relay proved terminal (#113).

The contract is `docs/design/relay-successor-transition.md`. Section numbers
below refer to it. In one paragraph: a reservation whose conversation never
reads idle again (an orphaned `inProgress` Codex turn after a timeout kill)
blocks `register` forever. This retires that one reservation as evidence and
binds the lead to a new conversation, disabled, only when the relay's own
records prove the run ended and the host shows nothing of it alive. It never
declares the old conversation idle, never charges usage, and never reads or
writes the backend's own state.
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterable, Optional

import lead_relay
from lead_relay import ACTIVE, log, migrate

RETIRED = """
CREATE TABLE IF NOT EXISTS retired_reservations (
    attempt_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, recipient TEXT NOT NULL,
    acquired_at REAL NOT NULL, retired_at REAL NOT NULL, reason TEXT NOT NULL,
    successor_key TEXT NOT NULL, previous_binding TEXT NOT NULL);
"""

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
KEEP = object()   # `cli`: carry the current binding's over (§1)
# §2.8: a run with no container is checked against every live process created
# since it launched. Process creation and the relay's own timestamps are the
# same wall clock; the skew covers the launch bookkeeping before the spawn.
WINDOW_SKEW = 10.0


class Refused(Exception):
    """A precondition failed. The message is the operator's reason."""


def retired(db) -> list[dict]:
    """The retired reservations, for `status` (§3)."""
    db.executescript(RETIRED)
    return [dict(r) for r in db.execute("SELECT * FROM retired_reservations ORDER BY retired_at")]


def retired_key(db, key: str) -> Optional[dict]:
    """The retired reservation on conversation `key`, if any (§2.9). A
    retired conversation is never bound again, by `successor` or `register`.
    Read-only: inside a caller's transaction, so it never runs DDL."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                      "AND name = 'retired_reservations'").fetchone():
        return None
    row = db.execute("SELECT * FROM retired_reservations WHERE session_key = ? "
                     "ORDER BY retired_at LIMIT 1", (key.lower(),)).fetchone()
    return dict(row) if row else None


def _ticks(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _when(epoch: Optional[float]) -> str:
    if epoch is None:
        return "unknown"
    return time.strftime("%Y-%m-%d %H:%M:%S%z", time.localtime(epoch))


def _describe(procs) -> str:
    return "; ".join(f"pid {p.pid} {p.name or '?'} created {_when(p.created)}"
                     for p in sorted(procs, key=lambda p: p.pid))


def tree_members(table, pid: int, proc_start) -> list:
    """Live processes the parent-pid chain ties to the run (§2.8), or Refused
    when a candidate's creation time could not be read.

    Windows keeps a dead parent's pid in each child's entry, so the chain is
    followed counting only processes created after their parent. A reused
    pid's own children are newer than the reuse, so they still count, which
    is a refusal, never a false "gone". The chain breaks where an
    intermediate process has exited and its child was reparented, which is
    why this is never the only check (§2.8).
    """
    children: dict[int, list] = {}
    for proc in table:
        children.setdefault(proc.ppid, []).append(proc)
    found, todo, seen = [], [(pid, _ticks(proc_start))], {pid}
    while todo:
        parent, born = todo.pop()
        for child in children.get(parent, ()):
            if child.pid in seen:
                continue
            start = _ticks(child.start)
            if start is None:
                raise Refused(f"the creation time of pid {child.pid} ({child.name or '?'}), a "
                              f"child of {parent}, could not be read; it may be part of the run")
            if born is None or start >= born:
                seen.add(child.pid)
                found.append(child)
                todo.append((child.pid, start))
    return found


def tree_proof(processes, attempt, inspected: Iterable[int] = ()) -> str:
    """How the host shows nothing of the run alive (§2.8), or Refused."""
    pid, start = attempt["pid"], attempt["proc_start"]
    try:
        table = processes.snapshot()
    except Exception as exc:  # noqa: BLE001 -- unreadable is not empty
        raise Refused(f"the process table could not be read ({type(exc).__name__}: {exc})")
    root = next((p for p in table if p.pid == pid), None)
    if root is not None:
        if root.start is None:
            raise Refused(f"pid {pid} is live and its creation time could not be read, so it "
                          "cannot be told apart from the run's own process")
        if str(root.start) == str(start):
            raise Refused(f"its process {pid} is still alive (same pid and creation time)")
    members = tree_members(table, pid, start)
    if members:
        raise Refused(f"part of its process tree is still alive: {_describe(members)}")

    container = attempt["container"]
    if container and container.startswith("job:"):
        name = container[4:]
        try:
            alive = processes.job_members(name)
        except Exception as exc:  # noqa: BLE001 -- a failed query is not absence
            raise Refused(f"its job {name} could not be queried ({type(exc).__name__}: {exc})")
        if alive is None:
            return (f"its job {name} no longer exists; it was created kill-on-close, so the "
                    "kernel ended every member before destroying it")
        if alive:
            named = {p.pid: p for p in table}
            listed = "; ".join(f"pid {p} {named[p].name}" if p in named else f"pid {p}"
                               for p in sorted(alive))
            raise Refused(f"its job {name} still has {len(alive)} live process(es): {listed}")
        return f"its job {name} has no live process"
    if container and container.startswith("session:"):
        sid = _ticks(container[8:])
        unreadable = [p for p in table if p.start is None]
        if sid is None or unreadable:
            raise Refused(f"its session {container[8:]} cannot be checked: "
                          + (_describe(unreadable) if unreadable else "bad container"))
        alive = [p for p in table if sid in (p.group, p.session)]
        if alive:
            raise Refused(f"its session {sid} still has live processes: {_describe(alive)}")
        return f"no live process is in its session {sid}"
    if container:
        raise Refused(f"its container {container!r} is not one this relay knows how to check")
    return _window_proof(table, attempt, set(inspected))


def _window_proof(table, attempt, inspected: set) -> str:
    """No container: refuse on every live process that may descend from the
    run, unless the operator inspected it (§2.8).

    A process may descend from the run when it was created since the run's
    launch and its parent chain, followed back while each parent is older
    than its child, breaks (the parent has exited) before reaching a live
    process created before the launch. The run's own processes all have
    ancestors created since its launch, back to its root, which is gone, so
    every one of them breaks this way. A survivor can create processes long
    after the root ended, so there is no upper bound. Only the processes where
    a chain breaks are listed: inspecting one covers its descendants."""
    lo = attempt["launched_at"] - WINDOW_SKEW
    unreadable = [p for p in table if p.created is None]
    if unreadable:
        raise Refused("no container was recorded for this run, and the creation time of "
                      f"{_describe(unreadable)} could not be read")
    by_pid = {p.pid: p for p in table}
    breaks: dict[int, object] = {}
    for proc in table:
        if proc.created < lo:
            continue
        here, seen = proc, {proc.pid}
        while True:
            parent = by_pid.get(here.ppid)
            if parent is None or parent.pid in seen or parent.created > here.created:
                breaks[here.pid] = here       # its parent exited: it may be the run's
                break
            if parent.created < lo:
                break                         # a live process older than the run
            seen.add(parent.pid)
            here = parent
    unexplained = [p for p in breaks.values() if p.pid not in inspected]
    if unexplained:
        raise Refused(
            f"no container was recorded for this run, so absence is checked by ancestry: "
            f"{len(unexplained)} live process(es) created since its launch at {_when(lo)} have "
            f"an exited parent, so any of them may be the run's survivor or one it created: "
            f"{_describe(unexplained)}. Inspect each (and what it started); if none is the "
            "run's, name them all with --inspected-pids "
            + ",".join(str(p.pid) for p in sorted(unexplained, key=lambda p: p.pid)))
    proof = (f"no container was recorded; root and parent chain gone, and every live process "
             f"created since its launch at {_when(lo)} descends from a live process older "
             "than the run")
    if breaks:
        proof += (", or from the operator-inspected "
                  + ", ".join(str(p) for p in sorted(breaks)))
    return proof


def terminal(attempt, delivery, run_timeout: float, provenance_since: Optional[float],
             historical: bool = False) -> str:
    """How the relay's own record proves the run ended (§2.5), or Refused."""
    aid = attempt["attempt_id"]
    if attempt["state"] not in ("exited", "done"):
        raise Refused(f"attempt {aid} is {attempt['state']}, not proven terminal")
    missing = [k for k in ("launched_at", "ended_at", "pid", "proc_start") if attempt[k] is None]
    if missing:
        raise Refused(f"attempt {aid} has no {', '.join(missing)} recorded; not proven terminal")
    if attempt["exit_code"] is not None:
        return f"exited with code {attempt['exit_code']}"
    ran = attempt["ended_at"] - attempt["launched_at"]
    uncertain = delivery is not None and delivery["state"] == "uncertain"
    how = attempt["ended_by"]
    if how == "timeout" and ran >= run_timeout and not uncertain:
        return f"killed by the run timeout after {ran / 60:.1f} min (recorded by its timeout path)"
    predates = how is None and provenance_since is not None \
        and attempt["ended_at"] < provenance_since
    if predates and ran >= run_timeout and not uncertain:
        if not historical:
            raise Refused(
                f"attempt {aid} ended with no exit code after {ran / 60:.1f} min (at least "
                f"RUN_TIMEOUT, {run_timeout / 60:.0f} min), before this database recorded how "
                "runs end; that is not proof of a timeout kill. The relay's own hive line "
                f"'RELAY TIMEOUT #{attempt['message_id']}', if posted, is the timeout path's, "
                "and is for the operator to check. To retire it on exactly that evidence, add "
                "--historical-evidence")
        return (f"historical evidence only: ended, no exit code, ran {ran / 60:.1f} min "
                f">= RUN_TIMEOUT ({run_timeout / 60:.0f} min), no termination provenance "
                "recorded (it predates it); not proven a timeout kill")
    raise Refused(f"attempt {aid} ended without an exit code after {ran / 60:.1f} min and the "
                  f"relay recorded no timeout kill (ended_by {how or 'not recorded'}); not "
                  "proven terminal (a quit or a restart's recovery is not proof)")


def preflight(db, lead: str, attempt_id: str, session: str, workspace: str, reason: str,
              processes, *, run_timeout: Optional[float] = None, historical: bool = False,
              inspected: Iterable[int] = ()) -> dict:
    """Every §2 check, read-only. Returns the plan, or raises Refused.

    `run_timeout` defaults to the relay's own, read when called."""
    run_timeout = lead_relay.RUN_TIMEOUT if run_timeout is None else run_timeout
    if not UUID.fullmatch(session or ""):
        raise Refused("--session must be the new conversation's UUID")
    if not re.match(r"^([A-Za-z]:[\\/]|/|\\\\)", workspace or ""):
        raise Refused("--workspace must be absolute")
    if not (reason or "").strip():
        raise Refused("a reason is required; it is recorded with the retired reservation")
    binding = db.execute("SELECT * FROM sessions WHERE recipient = ?", (lead,)).fetchone()
    if binding is None:
        raise Refused(f"{lead} is not registered; use register")
    current = f"{binding['backend']}:{binding['session_id'].lower()}"

    reservation = db.execute("SELECT * FROM reservations WHERE attempt_id = ?",
                             (attempt_id,)).fetchone()
    if reservation is None:
        old = db.execute("SELECT retired_at FROM retired_reservations WHERE attempt_id = ?",
                         (attempt_id,)).fetchone()
        if old is not None:
            raise Refused(f"attempt {attempt_id}'s reservation was already retired at "
                          f"{old[0]:.0f}; nothing to do")
        raise Refused(f"no reservation is held by attempt {attempt_id}")
    if reservation["recipient"] != lead:
        raise Refused(f"attempt {attempt_id}'s reservation belongs to {reservation['recipient']}")
    if reservation["session_key"] != current:
        raise Refused(f"the reservation is on {reservation['session_key']}, not {lead}'s "
                      f"current binding {current}")

    new_key = f"{binding['backend']}:{session.lower()}"
    others = [r[0] for r in db.execute(
        "SELECT attempt_id FROM reservations WHERE (recipient = ? OR session_key = ?) "
        "AND attempt_id != ?", (lead, new_key, attempt_id))]
    if others:
        raise Refused(f"other reservations would still block {lead}: {', '.join(others)}")

    attempt = db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
    if attempt is None:
        raise Refused(f"attempt {attempt_id} has no attempts row")
    if (attempt["recipient"], attempt["backend"], attempt["path"]) != (lead, binding["backend"],
                                                                       "headless") \
            or f"{attempt['backend']}:{(attempt['session_id'] or '').lower()}" != current:
        raise Refused(f"attempt {attempt_id} is not {lead}'s headless run on {current}")
    delivery = db.execute("SELECT * FROM deliveries WHERE message_id = ? AND recipient = ?",
                          (attempt["message_id"], lead)).fetchone()
    since = db.execute("SELECT value FROM meta WHERE key = 'provenance_since'").fetchone()
    how = terminal(attempt, delivery, run_timeout, float(since[0]) if since else None,
                   historical)
    if not attempt["usage_recorded"]:
        raise Refused(f"attempt {attempt_id}'s usage is not recorded yet; the running relay "
                      "charges it on its next tick")
    if delivery is not None and delivery["attempt_id"] == attempt_id \
            and delivery["state"] in ACTIVE:
        raise Refused(f"delivery #{attempt['message_id']} is still {delivery['state']}; "
                      "it owes its verdict first")
    try:
        gone = tree_proof(processes, attempt, inspected)
    except Refused as exc:
        raise Refused(f"attempt {attempt_id}: {exc}") from None

    if new_key in (reservation["session_key"], current):
        raise Refused("the successor must be a different conversation from the reserved one")
    taken = db.execute("SELECT recipient FROM sessions WHERE backend = ? AND "
                       "lower(session_id) = lower(?) AND recipient != ?",
                       (binding["backend"], session, lead)).fetchone()
    if taken:
        raise Refused(f"that session is already registered to {taken[0]}")
    if retired_key(db, new_key):
        raise Refused("that conversation holds a retired reservation; choose a new one")
    return {"binding": dict(binding), "reservation": dict(reservation), "how": how,
            "gone": gone, "new_key": new_key, "message_id": attempt["message_id"]}


def transition(db, lead: str, attempt_id: str, session: str, workspace: str, reason: str, *,
               processes, confirm: Optional[str] = None, cli=KEEP, now=time.time,
               run_timeout: Optional[float] = None, historical: bool = False,
               inspected: Iterable[int] = ()) -> tuple[int, str]:
    """Retire one reservation as evidence and bind the successor, disabled (§3).

    Without `confirm` it only reports. With it, `confirm` must name the
    attempt, and the caller must hold the relay's lock (`main` does), for
    the reason `cancel_held` gives.
    """
    migrate(db)
    db.executescript(RETIRED)
    db.execute("BEGIN IMMEDIATE")
    try:
        try:
            plan = preflight(db, lead, attempt_id, session, workspace, reason, processes,
                             run_timeout=run_timeout, historical=historical,
                             inspected=inspected)
            if confirm is not None and confirm != attempt_id:
                raise Refused(f"--confirm must name the attempt being retired ({attempt_id})")
        except Refused as exc:
            db.execute("ROLLBACK")
            return 1, f"REFUSED: {exc}. Nothing changed."
        binding = plan["binding"]
        chosen = binding["cli"] if cli is KEEP else cli
        text = (f"retire reservation {plan['reservation']['session_key']} of attempt {attempt_id} "
                f"(#{plan['message_id']}, {plan['how']}; {plan['gone']}), then bind {lead} -> "
                f"{binding['backend']} {session} workspace {workspace} cli {chosen} (disabled)")
        if confirm is None:
            db.execute("ROLLBACK")
            return 0, f"DRY RUN: would {text}. Add --confirm {attempt_id} to apply."
        at = now()
        db.execute("INSERT INTO retired_reservations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (attempt_id, plan["reservation"]["session_key"], lead,
                    plan["reservation"]["acquired_at"], at, reason.strip(), plan["new_key"],
                    json.dumps(binding, sort_keys=True)))
        if db.execute("DELETE FROM reservations WHERE attempt_id = ?", (attempt_id,)).rowcount != 1:
            db.execute("ROLLBACK")
            return 1, "REFUSED: the reservation changed underneath; nothing changed"
        # As `register` writes it: always disabled until the bridge proof.
        db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, 0, ?)",
                   (lead, binding["backend"], session, workspace, chosen, at))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    log.info("successor: %s (%s)", text, reason)
    return 0, f"done: {text}"
