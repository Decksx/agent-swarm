"""Rebind a lead past a run the relay proved terminal (#113).

The contract is `docs/design/relay-successor-transition.md`. Section numbers
below refer to it. In one paragraph: a reservation whose conversation never
reads idle again (an orphaned `inProgress` Codex turn after a timeout kill)
blocks `register` forever. This retires that one reservation as evidence and
binds the lead to a new conversation, disabled, only when the relay's own
records prove the run ended and its process tree is gone. It never declares
the old conversation idle, never charges usage, and never reads or writes
the backend's own state.
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional

from lead_relay import ACTIVE, RUN_TIMEOUT, log
from lead_relay_backends import session_key

RETIRED = """
CREATE TABLE IF NOT EXISTS retired_reservations (
    attempt_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, recipient TEXT NOT NULL,
    acquired_at REAL NOT NULL, retired_at REAL NOT NULL, reason TEXT NOT NULL,
    successor_key TEXT NOT NULL, previous_binding TEXT NOT NULL);
"""

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
KEEP = object()   # `cli`: carry the current binding's over (§1)


class Refused(Exception):
    """A precondition failed. The message is the operator's reason."""


def retired(db) -> list[dict]:
    """The retired reservations, for `status` (§3)."""
    db.executescript(RETIRED)
    return [dict(r) for r in db.execute("SELECT * FROM retired_reservations ORDER BY retired_at")]


def tree_gone(processes, pid, proc_start) -> Optional[str]:
    """None when the run's whole process tree is gone, else why not (§2.8)."""
    if processes.is_same(pid, proc_start):
        return f"its process {pid} is still alive (same pid and creation time)"
    try:
        alive = processes.descendants(pid, proc_start)
    except Exception as exc:  # noqa: BLE001 -- unreadable is not empty
        return f"its process tree could not be read ({type(exc).__name__}: {exc})"
    if alive:
        return f"part of its process tree is still alive (pids {sorted(alive)})"
    return None


def terminal(attempt, delivery, run_timeout: float) -> str:
    """How the relay's own record proves the run ended (§2.5), or Refused."""
    if attempt["state"] not in ("exited", "done"):
        raise Refused(f"attempt {attempt['attempt_id']} is {attempt['state']}, not proven terminal")
    missing = [k for k in ("launched_at", "ended_at", "pid", "proc_start") if attempt[k] is None]
    if missing:
        raise Refused(f"attempt {attempt['attempt_id']} has no {', '.join(missing)} recorded; "
                      "not proven terminal")
    if attempt["exit_code"] is not None:
        return f"exited with code {attempt['exit_code']}"
    ran = attempt["ended_at"] - attempt["launched_at"]
    if ran >= run_timeout and not (delivery is not None and delivery["state"] == "uncertain"):
        return f"killed by the run timeout after {ran / 60:.1f} min"
    raise Refused(f"attempt {attempt['attempt_id']} ended without an exit code after "
                  f"{ran / 60:.1f} min and was not a timeout kill; not proven terminal "
                  "(a quit or a restart's recovery is not proof)")


def preflight(db, lead: str, attempt_id: str, session: str, workspace: str, reason: str,
              processes, *, run_timeout: float = RUN_TIMEOUT) -> dict:
    """Every §2 check, read-only. Returns the plan, or raises Refused."""
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
    how = terminal(attempt, delivery, run_timeout)
    if not attempt["usage_recorded"]:
        raise Refused(f"attempt {attempt_id}'s usage is not recorded yet; the running relay "
                      "charges it on its next tick")
    if delivery is not None and delivery["attempt_id"] == attempt_id \
            and delivery["state"] in ACTIVE:
        raise Refused(f"delivery #{attempt['message_id']} is still {delivery['state']}; "
                      "it owes its verdict first")
    alive = tree_gone(processes, attempt["pid"], attempt["proc_start"])
    if alive:
        raise Refused(f"attempt {attempt_id}: {alive}")

    if new_key in (reservation["session_key"], current):
        raise Refused("the successor must be a different conversation from the reserved one")
    taken = db.execute("SELECT recipient FROM sessions WHERE backend = ? AND "
                       "lower(session_id) = lower(?) AND recipient != ?",
                       (binding["backend"], session, lead)).fetchone()
    if taken:
        raise Refused(f"that session is already registered to {taken[0]}")
    if db.execute("SELECT 1 FROM retired_reservations WHERE session_key = ?",
                  (new_key,)).fetchone():
        raise Refused("that conversation holds a retired reservation; choose a new one")
    return {"binding": dict(binding), "reservation": dict(reservation), "how": how,
            "new_key": new_key, "message_id": attempt["message_id"]}


def transition(db, lead: str, attempt_id: str, session: str, workspace: str, reason: str, *,
               processes, confirm: Optional[str] = None, cli=KEEP, now=time.time,
               run_timeout: float = RUN_TIMEOUT) -> tuple[int, str]:
    """Retire one reservation as evidence and bind the successor, disabled (§3).

    Without `confirm` it only reports. With it, `confirm` must name the
    attempt, and the caller must hold the relay's lock (`main` does), for
    the reason `cancel_held` gives.
    """
    db.executescript(RETIRED)
    db.execute("BEGIN IMMEDIATE")
    try:
        try:
            plan = preflight(db, lead, attempt_id, session, workspace, reason, processes,
                             run_timeout=run_timeout)
            if confirm is not None and confirm != attempt_id:
                raise Refused(f"--confirm must name the attempt being retired ({attempt_id})")
        except Refused as exc:
            db.execute("ROLLBACK")
            return 1, f"REFUSED: {exc}. Nothing changed."
        binding = plan["binding"]
        chosen = binding["cli"] if cli is KEEP else cli
        text = (f"retire reservation {plan['reservation']['session_key']} of attempt {attempt_id} "
                f"(#{plan['message_id']}, {plan['how']}; process tree gone), then bind {lead} -> "
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
