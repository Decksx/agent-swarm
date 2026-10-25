"""The wake-up relay's wiring and command line (#113).

Split out of `lead_relay.py` to keep that module within the per-file view
budget (`authored_change.DEFAULT_FILE_VIEW`). `lead_relay.main` delegates here,
so `python lead_relay.py run` (the `AgentSwarmLeadRelay` task) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from lead_relay import (
    HERE, LEADS, SCHEMA, AlreadyRunning, ClaudeBackend, Hub, ProcessApi, Relay, acquire_lock,
    log, migrate, status,
)
from lead_relay_codex import CodexBackend, codex_usage
import lead_relay_successor



def claude_usage():
    """(check, record) against the live Claude worker's shared guard files."""
    import claude_rate_guard
    from host_settings import setting

    root = setting("CLAUDE_RATE_GUARD_DIR")
    directory = Path(root).expanduser() if root else None
    if directory is None or not directory.is_dir():
        raise SystemExit("set CLAUDE_RATE_GUARD_DIR to the live Claude worker's directory")
    usage = directory / "claude_worker.usage"
    cooldown = float(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", str(5 * 3600)))
    warn = float(os.environ.get("RATE_LIMIT_WARN_SECONDS", str(4.5 * 3600)))

    def check():
        reason, _ = claude_rate_guard.rate_limit_reason(
            None, ratelimit_path=directory / "claude_worker.ratelimit",
            usage_window=claude_rate_guard.read_usage(usage),
            warn_seconds=warn, cooldown_seconds=cooldown)
        return reason

    def record(start, elapsed):
        claude_rate_guard.record_usage(usage, [], start, elapsed, cooldown, strict=True)

    return check, record


def build(db_path: Path, control_dir: Optional[Path]) -> Relay:
    processes = ProcessApi()
    # Codex design §5: one guard per backend. Codex's is a local duration
    # budget beside the relay's database, not the Codex account's quota.
    codex_budget = float(os.environ.get("LEAD_RELAY_CODEX_BUDGET_SECONDS", str(2 * 3600)))
    usage = {"claude": claude_usage(),
             "codex": codex_usage(db_path.with_name("codex_usage.json"),
                                  budget_seconds=codex_budget)}
    return Relay(db_path, Hub(), backends={"claude": ClaudeBackend(processes),
                                           "codex": CodexBackend()},
                 processes=processes, usage=usage, control_dir=control_dir)


def cancel_held(db, lead: str, ids: list[int], reason: str, *, confirm: bool,
                now=time.time) -> tuple[int, str]:
    """Retire exactly these held deliveries for one lead, or change nothing.

    For stale history that must not replay when a lead is (re)registered
    (#125 §1: the held Codex queue). Fenced so it cannot reach anything else:
    only the named ids, only rows still `held` for this lead, all or none,
    and never while this lead's binding is enabled. Rows for other recipients
    of the same message are untouched. Without `confirm` it only reports.

    With `confirm`, the caller must hold the relay's ownership lock (`main`
    does): a running daemon may already have read these rows for its current
    tick, and its later writes do not re-check them, so a cancellation it
    did not see could be put back to `held` or delivered live (Codex, #129
    at 7f3d63f). This transaction alone cannot fence that.
    """
    if not ids or len(set(ids)) != len(ids):
        return 1, "REFUSED: give each message id exactly once"
    if not reason.strip():
        return 1, "REFUSED: a reason is required; it is recorded on every row"
    db.execute("BEGIN IMMEDIATE")
    try:
        binding = db.execute("SELECT enabled FROM sessions WHERE recipient = ?", (lead,)).fetchone()
        if binding is not None and binding["enabled"]:
            db.execute("ROLLBACK")
            return 1, f"REFUSED: {lead} is enabled; disable it before cancelling its deliveries"
        marks = ",".join("?" * len(ids))
        rows = {r["message_id"]: r for r in db.execute(
            f"SELECT message_id, state, reason FROM deliveries WHERE recipient = ? "
            f"AND message_id IN ({marks})", (lead, *ids))}
        wrong = [f"#{i} {rows[i]['state'] if i in rows else 'missing'}" for i in ids
                 if i not in rows or rows[i]["state"] != "held"]
        if wrong:
            db.execute("ROLLBACK")
            return 1, f"REFUSED: not all held for {lead} ({', '.join(wrong)}); nothing changed"
        plan = ", ".join(f"#{i} held({rows[i]['reason']})" for i in sorted(ids))
        if not confirm:
            db.execute("ROLLBACK")
            return 0, f"DRY RUN: would cancel {len(ids)} for {lead}: {plan}. Add --confirm to apply."
        changed = db.execute(
            f"UPDATE deliveries SET state = 'cancelled', reason = ?, updated_at = ? "
            f"WHERE recipient = ? AND state = 'held' AND message_id IN ({marks})",
            (f"cancelled: {reason.strip()}", now(), lead, *ids)).rowcount
        if changed != len(ids):
            db.execute("ROLLBACK")
            return 1, f"REFUSED: {changed} of {len(ids)} rows changed underneath; nothing changed"
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    log.info("cancelled %d held deliveries for %s: %s (%s)", len(ids), lead, plan, reason)
    return 0, f"cancelled {len(ids)} for {lead}: {plan}"


def successor(db, db_path: Path, args) -> int:
    """`successor`: docs/design/relay-successor-transition.md. Applying takes
    the daemon's lock, as `cancel --confirm` does, for the same reason."""
    lock = None
    if args.confirm is not None:
        try:
            lock = acquire_lock(db_path.with_name(db_path.name + ".lock"))
        except AlreadyRunning:
            print("REFUSED: the relay daemon is running; stop it before --confirm "
                  "(a dry run needs no stop). Nothing changed.")
            return 3
    try:
        code, text = lead_relay_successor.transition(
            db, args.lead, args.retire_attempt, args.session, args.workspace, args.reason,
            processes=ProcessApi(), confirm=args.confirm,
            cli=lead_relay_successor.KEEP if args.cli is None else args.cli)
    finally:
        if lock is not None:
            os.close(lock)
    print(text)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(HERE / "control" / "lead_relay.db"))
    parser.add_argument("--control", default=os.environ.get("SWARM_CONTROL_DIR", str(HERE / "control")))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("register")
    p.add_argument("--lead", required=True, choices=LEADS)
    p.add_argument("--backend", required=True, choices=("claude", "codex"))
    p.add_argument("--session", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--cli")
    for name in ("enable", "disable"):
        sub.add_parser(name).add_argument("--lead", required=True, choices=LEADS)
    sub.add_parser("status")
    p = sub.add_parser("cancel", help="retire exactly these held deliveries (dry run without --confirm)")
    p.add_argument("--lead", required=True, choices=LEADS)
    p.add_argument("--ids", required=True, help="comma-separated message ids, each still held")
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm", action="store_true")
    p = sub.add_parser("successor", help="retire a terminal run's reservation and bind a new "
                       "session, disabled (dry run without --confirm)")
    p.add_argument("--lead", required=True, choices=LEADS)
    p.add_argument("--session", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--cli", help="default: the current binding's")
    p.add_argument("--retire-attempt", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm", metavar="ATTEMPT_ID", help="the attempt id again, to apply")
    p = sub.add_parser("run")
    p.add_argument("--interval", type=float, default=20.0)
    sub.add_parser("once")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.command in ("register", "enable", "disable", "status", "cancel", "successor"):
        db = sqlite3.connect(str(db_path), isolation_level=None)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        migrate(db)
        if args.command == "register":
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", args.session):
                print("REFUSED: --session must be the conversation's UUID (no --last, no fork)")
                return 1
            if not Path(args.workspace).is_absolute():
                print("REFUSED: --workspace must be absolute")
                return 1
            key = f"{args.backend}:{args.session.lower()}"
            other = db.execute("SELECT recipient FROM sessions WHERE backend = ? AND "
                               "lower(session_id) = lower(?) AND recipient != ?",
                               (args.backend, args.session, args.lead)).fetchone()
            if other:
                # One conversation, one identity: two leads resuming the same
                # session would each get their own reservation (Codex, #116).
                print(f"REFUSED: that session is already registered to {other[0]}")
                return 1
            if db.execute("SELECT 1 FROM reservations WHERE recipient = ? OR session_key = ?",
                          (args.lead, key)).fetchone():
                print(f"REFUSED: {args.lead} has a reserved run; re-register once it is released")
                return 1
            # Registering (again) always leaves the backend disabled until
            # its bridge proof, so a changed session id can't inherit "enabled".
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, 0, ?)",
                       (args.lead, args.backend, args.session, args.workspace, args.cli, time.time()))
            print(f"registered {args.lead} -> {args.backend} {args.session} (disabled)")
        elif args.command in ("enable", "disable"):
            changed = db.execute("UPDATE sessions SET enabled = ? WHERE recipient = ?",
                                 (int(args.command == "enable"), args.lead)).rowcount
            print(f"{args.lead}: {args.command}d" if changed else f"{args.lead} is not registered")
            return 0 if changed else 1
        elif args.command == "cancel":
            try:
                ids = [int(i) for i in args.ids.split(",") if i.strip()]
            except ValueError:
                print("REFUSED: --ids must be comma-separated message ids")
                return 1
            lock = None
            if args.confirm:
                # The daemon's own lock: applying requires the relay stopped.
                try:
                    lock = acquire_lock(db_path.with_name(db_path.name + ".lock"))
                except AlreadyRunning:
                    print("REFUSED: the relay daemon is running; stop it before --confirm "
                          "(a dry run needs no stop). Nothing changed.")
                    return 3
            try:
                code, text = cancel_held(db, args.lead, ids, args.reason, confirm=args.confirm)
            finally:
                if lock is not None:
                    os.close(lock)
            print(text)
            return code
        elif args.command == "successor":
            return successor(db, db_path, args)
        else:
            print(json.dumps({**status(db), "retired_reservations":
                              lead_relay_successor.retired(db)}, indent=2))
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Before recovery, and held for the whole run: a second `run` or `once`
    # on this database must never recover the first one's live launch.
    try:
        lock = acquire_lock(db_path.with_name(db_path.name + ".lock"))  # noqa: F841 -- kept open
        relay = build(db_path, Path(args.control) if args.control else None)
        relay.recover()
    except AlreadyRunning as exc:
        print(f"REFUSED: {exc}")
        return 3
    if args.command == "once":
        relay.tick()
        return 0
    while True:
        try:
            relay.tick()
        except AlreadyRunning as exc:
            log.error("stopping: %s", exc)
            return 3
        except Exception:  # noqa: BLE001 -- the daemon logs and keeps watching
            log.exception("relay tick failed")
        time.sleep(args.interval)
