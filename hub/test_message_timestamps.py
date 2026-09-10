"""Every message says when it was sent, and says it unambiguously.

A time of day on its own is a claim about a day nobody can recover. The hub
page is left open across days and read back during a handoff, so "11:42:07" in
a scrollback is worse than no timestamp: it looks like information. The same
goes for a bare float in an API response, which is unambiguous to a machine and
unreadable to a person, and was being rendered independently by the browser, by
each worker's transcript builder, and by whoever was reading a log -- three
chances to disagree about what a number meant.

The hub stays the authority. It assigns the instant, in Unix seconds, exactly
as it always has -- no migration, because the column already holds the right
thing -- and it publishes the ISO-8601 UTC rendering of that same instant
alongside it. Local time is computed only where somebody is actually looking:
in their browser, in their zone.

None of this is allowed to start work. A timestamp is display and transcript
metadata; the containment rule is that chat activates nothing, and adding a
field to a message does not change what a message is.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_PATH = Path(__file__).resolve().parent / "hub.py"
REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import swarm_control  # noqa: E402


SECRET = "s" * 32
AUTH = ("admin", SECRET)

# 2026-09-10T17:42:07Z, the example the requirement was written against.
NOON = 1789062127.0
DAY = 86400.0


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_CREDENTIALS", f"admin:{SECRET}")
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))

    db = tmp_path / "chat.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "sender TEXT, target TEXT, content TEXT, timestamp REAL)"
    )
    conn.commit()
    conn.close()

    spec = importlib.util.spec_from_file_location("hub_timestamps", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_timestamps"] = module
    spec.loader.exec_module(module)
    module.DB_PATH = str(db)

    module._db = db
    return module


def store(hub, rows):
    """Write message rows directly, so a stored timestamp can be chosen."""
    conn = sqlite3.connect(hub._db)

    for sender, content, timestamp in rows:
        conn.execute(
            "INSERT INTO messages (sender, target, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (sender, "@Admin", content, timestamp),
        )

    conn.commit()
    conn.close()


def fetch(hub):
    with TestClient(hub.app) as client:
        response = client.get("/messages", auth=AUTH)

    assert response.status_code == 200
    return response.json()


# --- The instant, in a form that cannot be misread --------------------------


def test_a_message_carries_an_iso_utc_timestamp(hub):
    store(hub, [("gemini", "hello", NOON)])

    assert fetch(hub)[0]["timestamp_utc"] == "2026-09-10T17:42:07Z"


def test_the_unix_timestamp_is_preserved_unchanged(hub):
    """Kept, and kept first. Every existing reader parses this field, and a
    rename would have been a migration of every client to gain nothing."""
    store(hub, [("gemini", "hello", NOON)])

    assert fetch(hub)[0]["timestamp"] == NOON


def test_the_hub_assigns_the_timestamp_not_the_client(hub):
    """The server is the authority. A client's idea of now is a client's."""
    with TestClient(hub.app) as client:
        client.post(
            "/send", auth=AUTH,
            json={"target": "@Admin", "content": "x", "timestamp": 0},
        )

    sent = fetch(hub)[0]

    assert sent["timestamp"] > 0
    assert sent["timestamp_utc"].endswith("Z")


def test_the_utc_form_uses_z_rather_than_an_offset(hub):
    """Both are valid ISO-8601. The offset form is the one that gets truncated
    to a local-looking string by something downstream."""
    store(hub, [("gemini", "hello", NOON)])

    stamp = fetch(hub)[0]["timestamp_utc"]

    assert stamp.endswith("Z")
    assert "+00:00" not in stamp


# --- Historical rows, which are the ones most likely to break ---------------


def test_a_row_with_no_timestamp_still_renders(hub):
    """A transcript that drops its earliest messages loses exactly the context
    a handoff is read for."""
    store(hub, [("gemini", "from before the column", None)])

    row = fetch(hub)[0]

    assert row["content"] == "from before the column"
    assert row["timestamp_utc"] == "unknown"


def test_a_missing_timestamp_is_not_rendered_as_the_epoch(hub):
    """1970 in a transcript reads as a real time somebody could reason about."""
    store(hub, [("gemini", "old", None)])

    assert "1970" not in fetch(hub)[0]["timestamp_utc"]


def test_an_unusable_timestamp_is_not_guessed_at(hub):
    store(hub, [("gemini", "corrupt", 1e30)])

    assert fetch(hub)[0]["timestamp_utc"] == "unknown"


def test_untimestamped_history_sorts_before_timestamped_messages(hub):
    """NULL sorts before everything in SQLite, which is very nearly right by
    accident for old rows. COALESCE makes it right on purpose."""
    store(hub, [
        ("gemini", "recent", NOON),
        ("admin", "ancient", None),
    ])

    assert [row["content"] for row in fetch(hub)] == ["ancient", "recent"]


# --- Deterministic order: by time, then by id -------------------------------


def test_messages_are_ordered_by_timestamp(hub):
    store(hub, [
        ("gemini", "second", NOON + 10),
        ("admin", "first", NOON),
    ])

    assert [row["content"] for row in fetch(hub)] == ["first", "second"]


def test_messages_sharing_a_timestamp_are_ordered_by_id(hub):
    """A burst of agent replies lands inside one tick of time.time().

    Ordering by timestamp alone would leave those rows in whatever order
    SQLite found convenient -- stable until an index changes, and then
    silently not, so a conversation reorders itself between two reads with
    nothing having changed.
    """
    store(hub, [
        ("gemini", "a", NOON),
        ("chatgpt", "b", NOON),
        ("admin", "c", NOON),
    ])

    rows = fetch(hub)

    assert [row["content"] for row in rows] == ["a", "b", "c"]
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)


def test_the_order_is_the_same_on_every_read(hub):
    store(hub, [("gemini", f"m{n}", NOON) for n in range(8)])

    assert [row["id"] for row in fetch(hub)] == [row["id"] for row in fetch(hub)]


def test_since_id_still_pages(hub):
    """The id remains what a caller pages through; only the order changed."""
    store(hub, [("gemini", "one", NOON), ("gemini", "two", NOON + 1)])
    first = fetch(hub)[0]

    with TestClient(hub.app) as client:
        rest = client.get(
            f"/messages?since_id={first['id']}", auth=AUTH
        ).json()

    assert [row["content"] for row in rest] == ["two"]


# --- Date rollover, which is the whole reason a date is shown ---------------


def test_messages_on_either_side_of_midnight_are_distinguishable(hub):
    """Two messages seconds apart on different days.

    A time-only rendering shows 23:59:59 and 00:00:01 and gives a reader no
    way to tell those are a day apart from the day before -- or, read a week
    later, which day either belonged to.
    """
    midnight = 1789084800.0  # 2026-09-11T00:00:00Z
    store(hub, [
        ("admin", "late", midnight - 1),
        ("admin", "early", midnight + 1),
    ])

    stamps = [row["timestamp_utc"] for row in fetch(hub)]

    assert stamps[0].startswith("2026-09-10")
    assert stamps[1].startswith("2026-09-11")


def test_a_days_worth_of_messages_all_carry_their_own_date(hub):
    store(hub, [
        ("admin", f"day {n}", NOON + n * DAY) for n in range(4)
    ])

    dates = {row["timestamp_utc"][:10] for row in fetch(hub)}

    assert dates == {"2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"}


# --- Timezone conversion happens where somebody is looking ------------------
#
# The server does not know where it is being read, so it says UTC and the
# viewer's own timezone database does the rest. That is also what makes
# daylight saving correct for historical messages: the conversion applies the
# rule in force at that instant, not the rule in force now. These check the
# instant the browser is handed; the rendering itself is `localTime` in the
# page, which converts from exactly this string.


def test_the_browser_is_handed_an_instant_it_can_convert(hub):
    """`new Date(...)` needs an unambiguous instant. A local-looking string
    without a zone is parsed as local time by some browsers and UTC by others,
    which is the ambiguity this set out to remove."""
    store(hub, [("gemini", "hello", NOON)])

    stamp = fetch(hub)[0]["timestamp_utc"]

    assert stamp == "2026-09-10T17:42:07Z"
    assert "T" in stamp and stamp.endswith("Z")


@pytest.mark.parametrize("offset_hours,expected_local_date", [
    (-6, "2026-09-10"),   # MDT: 11:42 the same morning
    (+9, "2026-09-11"),   # JST: 02:42 the next day
])
def test_the_same_instant_is_a_different_local_date_elsewhere(
    hub, offset_hours, expected_local_date
):
    """Which is why the date is rendered from the instant, per viewer, rather
    than formatted once on the server."""
    from datetime import datetime, timedelta, timezone as tz

    store(hub, [("gemini", "hello", NOON)])
    stamp = fetch(hub)[0]["timestamp_utc"]

    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.utc)
    local = moment.astimezone(tz(timedelta(hours=offset_hours)))

    assert local.strftime("%Y-%m-%d") == expected_local_date


def test_a_dst_boundary_converts_by_the_rule_in_force_then(hub):
    """A message from July and one from December are not the same offset from
    UTC in a zone that observes daylight saving. Converting from the instant
    gets that right; storing a preformatted local string would not."""
    from zoneinfo import ZoneInfo
    from datetime import datetime, timezone as tz

    july = 1784138400.0
    december = 1797357600.0
    store(hub, [("admin", "summer", july), ("admin", "winter", december)])

    denver = ZoneInfo("America/Denver")
    offsets = []

    for row in fetch(hub):
        moment = datetime.strptime(
            row["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=tz.utc)
        offsets.append(moment.astimezone(denver).utcoffset())

    assert offsets[0] != offsets[1]


# --- The transcript workers build for a model -------------------------------


def test_a_transcript_stamp_prefers_what_the_hub_said():
    assert swarm_control.message_stamp(
        {"timestamp_utc": "2026-09-10T17:42:07Z", "timestamp": 0}
    ) == "2026-09-10T17:42:07Z"


def test_a_transcript_stamp_falls_back_to_the_unix_field():
    """For a worker running against a hub not yet redeployed with the field.

    A transcript where some lines are stamped and some are not is harder to
    read than either.
    """
    assert swarm_control.message_stamp({"timestamp": NOON}) == "2026-09-10T17:42:07Z"


@pytest.mark.parametrize("message", [
    {}, {"timestamp": None}, {"timestamp": "not a time"}, None, "not a message",
])
def test_a_transcript_stamp_never_guesses(message):
    assert swarm_control.message_stamp(message) == "unknown"


def test_the_narration_log_records_both_forms(tmp_path, monkeypatch):
    """`timestamp` stays a float for anything already reading the file, and
    `recorded_at` is a different fact -- when this host wrote the line, which
    can be much later after a worker has been down."""
    monkeypatch.setattr(swarm_control, "CONTROL_DIR", tmp_path)
    monkeypatch.setattr(
        swarm_control, "NARRATION_PATH", tmp_path / "narration.jsonl"
    )

    swarm_control.record_narration([
        {"id": 1, "sender": "gemini", "target": "@Admin",
         "content": "hello", "timestamp": NOON},
    ])

    import json

    row = json.loads((tmp_path / "narration.jsonl").read_text(encoding="utf-8"))

    assert row["timestamp"] == NOON
    assert row["timestamp_utc"] == "2026-09-10T17:42:07Z"
    assert row["recorded_at"] >= NOON
    assert row["authoritative"] is False
