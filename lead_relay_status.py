"""The relay's counters for the chat page (#1737).

Kept out of `lead_relay.py` so that file stays within the authoring view
budget. Display only: nothing here can hold, start or count a delivery, and a
failure to publish is logged and retried on a later tick.

This module does not import `lead_relay`. The relay runs as `__main__`, so an
import here would load a second copy; the caller passes its leads and caps.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("lead_relay")

# How often the snapshot is pushed. The hub shows it as stale after 120 s.
PUBLISH_SECONDS = 30.0


def snapshot(db, now: float, paused: bool, leads, caps) -> dict:
    """The counters the page shows, from the relay database alone.

    `caps` is (launches per hour, launches per day, chain). Session ids are
    shortened: the page needs to tell bindings apart, not hold a resumable id.
    """
    count = lambda q, *a: db.execute(q, a).fetchone()[0]  # noqa: E731
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    try:
        owner_pid = json.loads(meta.get("owner") or "{}").get("pid")
    except ValueError:
        owner_pid = None
    per_lead = {}
    for row in db.execute("SELECT recipient, backend, session_id, enabled FROM sessions"):
        per_lead[row["recipient"]] = {"backend": row["backend"], "session": row["session_id"][:8],
                                      "enabled": bool(row["enabled"])}
    for lead in leads:
        entry = per_lead.setdefault(lead, {"backend": None, "session": None, "enabled": False})
        entry["launches_hour"] = count("SELECT COUNT(*) FROM wakes WHERE recipient = ? AND at > ?",
                                       lead, now - 3600)
        entry["launches_day"] = count("SELECT COUNT(*) FROM wakes WHERE recipient = ? AND at > ?",
                                      lead, now - 86400)
        entry["held"] = dict(db.execute(
            "SELECT reason, COUNT(*) FROM deliveries WHERE recipient = ? AND state = 'held' "
            "GROUP BY reason", (lead,)).fetchall())
        entry["active"] = [dict(r) for r in db.execute(
            "SELECT message_id, state FROM deliveries WHERE recipient = ? AND state IN "
            "('notified','launching','running','exited') ORDER BY message_id", (lead,))]
    hour, day, chain = caps
    return {
        "relay_time": now, "paused": paused, "owner_pid": owner_pid,
        "cursor": meta.get("cursor"), "chain": int(meta.get("chain") or 0),
        "caps": {"launches_per_hour": hour, "launches_per_day": day, "chain": chain},
        "leads": per_lead,
    }


def publish(relay, paused: bool, leads, caps) -> None:
    """Push the snapshot at most every PUBLISH_SECONDS, after dispatch."""
    now = relay.now()
    if now - relay.published_at < PUBLISH_SECONDS:
        return
    relay.published_at = now
    try:
        if not relay.hub.publish_status(snapshot(relay.db, now, paused, leads, caps)):
            log.warning("relay status not accepted by the hub")
    except Exception as exc:  # noqa: BLE001 -- display only, never fatal
        log.warning("relay status not published: %s: %s", type(exc).__name__, exc)
