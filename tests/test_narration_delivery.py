"""Delivery: at-least-once, in order, and never past a failure.

Losing a line and repeating one are not symmetric. A repeat is recognisable as
a repeat because every line carries its event sequence; a gap is not
recognisable as anything, and the operator's only sign of it is a decision
that never appears. So the cursor moves after the hub accepts a message and
not before, and it is written by atomic replacement, because a cursor torn by
a crash reads as never-run -- and a never-run narrator seeds itself at the
current maximum and silently skips everything it was down for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import narrator


def event(**overrides):
    base = {
        "seq": 1,
        "task_id": "CND-3",
        "task_version": 1,
        "actor": "gemini",
        "stage": "review",
        "kind": "review_requirements_satisfied",
        "from_state": "REVIEWING",
        "to_state": "READY_INTEGRATION",
        "payload_json": {},
    }
    base.update(overrides)
    return base


def events(*seqs, kind="review_requirements_satisfied"):
    return [event(seq=s, kind=kind) for s in seqs]


class FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = {} if body is None else body
        self.text = text

    def json(self):
        return self._body


class FakeServices:
    """A controller feed and a hub whose behaviour the test decides."""

    def __init__(self, events=None, max_seq=None, fail_posts_from=None):
        self.events = list(events or [])
        self._max = max_seq
        self.posted = []
        self.fail_posts_from = fail_posts_from
        self.feed_calls = []
        self.auth_seen = []

    @property
    def max_seq(self):
        if self._max is not None:
            return self._max

        return max((e["seq"] for e in self.events), default=0)

    def get(self, url, params=None, auth=None, timeout=None):
        self.auth_seen.append(auth)
        self.feed_calls.append(dict(params or {}))
        since = (params or {}).get("since")
        limit = (params or {}).get("limit", 200)

        if since is None:
            return FakeResponse(body={"events": [], "max_seq": self.max_seq})

        page = [e for e in self.events if e["seq"] > since][:limit]

        return FakeResponse(body={"events": page, "max_seq": self.max_seq})

    def post(self, url, json=None, auth=None, timeout=None):
        self.auth_seen.append(auth)
        content = (json or {}).get("content", "")

        if self.fail_posts_from is not None:
            if "(seq %d)" % self.fail_posts_from in content:
                return FakeResponse(status=503, text="hub down")

        self.posted.append(content)

        return FakeResponse()


@pytest.fixture
def cursor(tmp_path):
    return narrator.Cursor(tmp_path / "narration.cursor")


def build(cursor, services, **kw):
    args = {
        "controller_url": "http://controller",
        "cursor": cursor,
        "secret": "narrator-secret",
        "requests_module": services,
    }
    args.update(kw)

    return narrator.Narrator(**args)


def delivered(services):
    """The sequence numbers actually posted, in the order they were posted."""
    return [
        line.split("(seq ")[1].rstrip(")")
        for line in services.posted if "(seq " in line
    ]


# --- First run ---------------------------------------------------------------


def test_a_first_run_seeds_at_the_authoritative_maximum(cursor):
    """Not at the end of a page.

    A narrator taking its starting point from a limited page would begin at
    the end of its first page and then replay everything after it into the
    room -- the flood this exists to avoid, arrived at by looking like it was
    avoiding it.
    """
    services = FakeServices(events=events(1, 2, 3), max_seq=900)

    build(cursor, services).tick()

    assert cursor.read() == 900


def test_a_first_run_asks_for_the_maximum_without_asking_for_events(cursor):
    services = FakeServices(events=events(1, 2, 3))

    build(cursor, services).start()

    assert services.feed_calls[0].get("since") is None


def test_a_first_run_posts_exactly_one_startup_line(cursor):
    services = FakeServices(events=events(1, 2, 3), max_seq=900)

    build(cursor, services).tick()

    assert services.posted == ["Narrator started at seq 900"]


def test_a_first_run_does_not_replay_history(cursor):
    services = FakeServices(events=events(*range(1, 50)))

    build(cursor, services).tick()

    assert len(services.posted) == 1


# --- Order, and stopping where a failure happened ----------------------------


def test_events_are_delivered_in_ascending_sequence(cursor):
    cursor.write(0)
    services = FakeServices(events=events(1, 2, 3))

    build(cursor, services).tick()

    assert delivered(services) == ["1", "2", "3"]


def test_the_cursor_advances_only_after_the_hub_accepts(cursor):
    cursor.write(0)
    services = FakeServices(events=events(1, 2, 3), fail_posts_from=2)

    said = build(cursor, services).tick()

    assert said == 1
    assert cursor.read() == 1


def test_delivery_stops_at_the_failure_rather_than_skipping_it(cursor):
    cursor.write(0)
    services = FakeServices(events=events(1, 2, 3), fail_posts_from=2)

    build(cursor, services).tick()

    assert delivered(services) == ["1"]


def test_the_next_pass_resumes_at_the_event_that_failed(cursor):
    cursor.write(0)
    services = FakeServices(events=events(1, 2, 3), fail_posts_from=2)
    narration = build(cursor, services)
    narration.tick()

    services.fail_posts_from = None
    narration.tick()

    assert delivered(services) == ["1", "2", "3"]


def test_excluded_events_advance_the_cursor(cursor):
    """Otherwise every pass re-reads the same bookkeeping forever and never
    reaches anything after it."""
    cursor.write(0)
    services = FakeServices(events=[
        event(seq=1, kind="reservation_granted"),
        event(seq=2, kind="note"),
        event(seq=3),
    ])

    build(cursor, services).tick()

    assert cursor.read() == 3
    assert delivered(services) == ["3"]


def test_a_pass_over_only_excluded_events_still_moves_forward(cursor):
    cursor.write(0)
    services = FakeServices(
        events=[event(seq=n, kind="note") for n in (1, 2, 3)]
    )

    build(cursor, services).tick()

    assert cursor.read() == 3
    assert services.posted == []


# --- Outages are survived, not skipped ---------------------------------------


def test_an_unreachable_controller_delivers_nothing_and_does_not_move(cursor):
    cursor.write(7)

    class Down(FakeServices):
        def get(self, *a, **k):
            raise OSError("connection refused")

    build(cursor, Down()).tick()

    assert cursor.read() == 7


def test_a_refused_feed_is_survived(cursor):
    cursor.write(7)

    class Refused(FakeServices):
        def get(self, *a, **k):
            return FakeResponse(status=403, text="nope")

    assert build(cursor, Refused()).tick() == 0
    assert cursor.read() == 7


def test_narration_authenticates_as_narrator_on_both_services(cursor):
    cursor.write(0)
    services = FakeServices(events=events(1))

    build(cursor, services).tick()

    assert services.auth_seen
    assert all(a == ("narrator", "narrator-secret") for a in services.auth_seen)


# --- The cursor survives a crash ---------------------------------------------


def test_the_cursor_is_written_by_atomic_replacement(cursor, monkeypatch):
    replaced = []
    real = narrator.os.replace

    def watched(source, destination):
        replaced.append((source, destination))
        return real(source, destination)

    monkeypatch.setattr(narrator.os, "replace", watched)

    cursor.write(12)

    assert replaced, "the cursor was written in place rather than replaced"
    assert cursor.read() == 12


def test_a_restart_resumes_from_the_recorded_sequence(cursor):
    cursor.write(0)
    build(cursor, FakeServices(events=events(1, 2, 3))).tick()

    # A completely fresh narrator over the same cursor file.
    again = FakeServices(events=events(1, 2, 3, 4))
    build(narrator.Cursor(cursor.path), again).tick()

    assert delivered(again) == ["4"]


def test_a_crash_before_the_cursor_write_repeats_rather_than_loses(cursor):
    """At-least-once on purpose."""
    cursor.write(0)

    class CrashOnFirstWrite(narrator.Cursor):
        crashed = False

        def write(self, seq):
            if seq == 1 and not CrashOnFirstWrite.crashed:
                CrashOnFirstWrite.crashed = True
                raise RuntimeError("power cut")

            super().write(seq)

    services = FakeServices(events=events(1, 2))

    with pytest.raises(RuntimeError):
        build(CrashOnFirstWrite(cursor.path), services).tick()

    assert delivered(services) == ["1"], "the line was posted before the crash"

    recovered = FakeServices(events=events(1, 2))
    build(narrator.Cursor(cursor.path), recovered).tick()

    assert "1" in delivered(recovered), "seq 1 was lost rather than repeated"


def test_a_missing_cursor_seeds_rather_than_replaying_the_ledger(cursor):
    """Zero would replay everything. A missing file seeds at the maximum.

    A *damaged* file is a different fact and is refused instead -- see
    `test_narration_hardening`, where conflating the two was its own defect.
    """
    services = FakeServices(events=events(*range(1, 40)), max_seq=39)

    build(cursor, services).tick()

    assert cursor.read() == 39
    assert services.posted == ["Narrator started at seq 39"]


# --- Pagination cannot reorder delivery --------------------------------------


def test_a_page_is_bounded(cursor):
    cursor.write(0)
    services = FakeServices(events=events(*range(1, 500)))

    build(cursor, services, page=10).tick()

    assert len(delivered(services)) == 10


def test_events_arriving_during_pagination_land_after_what_was_delivered(cursor):
    """`seq` is monotonic and the feed is ordered by it, so a late arrival
    becomes the next page rather than displacing the current one."""
    cursor.write(0)
    services = FakeServices(events=events(1, 2))
    narration = build(cursor, services, page=2)
    narration.tick()

    services.events.extend(events(3, 4))
    narration.tick()

    assert delivered(services) == ["1", "2", "3", "4"]


def test_an_event_at_or_below_the_cursor_is_not_redelivered(cursor):
    cursor.write(2)
    services = FakeServices(events=events(1, 2, 3))

    build(cursor, services).tick()

    assert delivered(services) == ["3"]
