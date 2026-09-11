"""The ways narration can lie by omission, and the guards against each.

Every one of these was a real defect in the first candidate. A startup line
that recorded itself as delivered before the hub had taken it. A damaged
cursor read as a missing one, so the recovery silently discarded everything
since the last good write. A pause that stopped narration along with the work,
blinding the operator exactly while they were deciding whether to resume. And
payload text inserted into a one-line format without bounds, so an event could
render lines nobody produced.

They share a shape: the failure is invisible from inside, because what it
costs is something that never appears.
"""

from __future__ import annotations

import pytest

import narrator
import supervisor
from test_narration_delivery import (  # noqa: F401
    FakeResponse, FakeServices, build, cursor, delivered, event, events,
)
from test_supervisor import build as build_supervisor  # noqa: F401
from test_supervisor import control_dir, spawned  # noqa: F401


# --- The startup line is delivered, not merely intended ----------------------


class RefusingHub(FakeServices):
    """A hub that is down when narration first starts."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.accepting = False

    def post(self, url, json=None, auth=None, timeout=None):
        if not self.accepting:
            return FakeResponse(status=503, text="hub down")

        return super().post(url, json=json, auth=auth, timeout=timeout)


def test_a_refused_startup_line_does_not_record_a_start(cursor):
    """Recording first and ignoring the result lost the announcement forever:
    the cursor said narration had begun, so it never announced again."""
    services = RefusingHub(events=events(1, 2, 3), max_seq=900)

    build(cursor, services).tick()

    assert cursor.read() is None
    assert services.posted == []


def test_the_startup_line_is_retried_on_the_next_pass(cursor):
    services = RefusingHub(events=events(1, 2, 3), max_seq=900)
    narration = build(cursor, services)
    narration.tick()

    services.accepting = True
    narration.tick()

    assert services.posted == ["Narrator started at seq 900"]
    assert cursor.read() == 900


def test_a_retried_start_still_seeds_at_the_maximum(cursor):
    """The retry must not quietly become a replay of everything that arrived
    while the hub was down -- that is the flood, delayed."""
    services = RefusingHub(events=events(*range(1, 40)), max_seq=39)
    narration = build(cursor, services)
    narration.tick()

    services.accepting = True
    narration.tick()

    assert len(services.posted) == 1
    assert cursor.read() == 39


def test_an_unreachable_hub_at_startup_is_survived(cursor):
    class Unreachable(FakeServices):
        def post(self, *a, **k):
            raise OSError("connection refused")

    assert build(cursor, Unreachable(events=events(1))).tick() == 0
    assert cursor.read() is None


# --- A damaged cursor is not a missing one -----------------------------------


@pytest.mark.parametrize("content", ["", "   ", "not-a-sequence", "12x34", "{}"])
def test_a_corrupt_cursor_refuses_rather_than_reseeding(cursor, content):
    """Reseeding discards every event since the last good write and says
    nothing about having done so."""
    cursor.path.parent.mkdir(parents=True, exist_ok=True)
    cursor.path.write_text(content, encoding="utf-8")

    with pytest.raises(narrator.CursorUnreadable):
        cursor.read()


@pytest.mark.parametrize("content", ["", "not-a-sequence"])
def test_a_corrupt_cursor_is_preserved_for_diagnosis(cursor, content):
    """The file is the evidence. Overwriting it is destroying the record of
    what went wrong along with the events it was tracking."""
    cursor.path.parent.mkdir(parents=True, exist_ok=True)
    cursor.path.write_text(content, encoding="utf-8")
    services = FakeServices(events=events(1, 2, 3), max_seq=900)

    with pytest.raises(narrator.CursorUnreadable):
        build(cursor, services).tick()

    assert cursor.path.read_text(encoding="utf-8") == content
    assert services.posted == []


def test_an_unreadable_cursor_file_refuses_rather_than_reseeding(cursor,
                                                                monkeypatch):
    """A permission error is existing state that cannot be read, which is not
    the same fact as there being no state."""
    cursor.path.parent.mkdir(parents=True, exist_ok=True)
    cursor.path.write_text("41", encoding="utf-8")

    def denied(*a, **k):
        raise PermissionError("access is denied")

    monkeypatch.setattr(narrator.Path, "read_text", denied)

    with pytest.raises(narrator.CursorUnreadable):
        cursor.read()


def test_only_a_missing_file_means_first_run(cursor):
    assert cursor.read() is None

    cursor.write(5)

    assert cursor.read() == 5


def test_the_refusal_says_what_is_wrong_and_where(cursor):
    cursor.path.parent.mkdir(parents=True, exist_ok=True)
    cursor.path.write_text("rubbish", encoding="utf-8")

    with pytest.raises(narrator.CursorUnreadable) as caught:
        cursor.read()

    message = str(caught.value)
    assert str(cursor.path) in message
    assert "rubbish" in message
    assert "skip" in message.lower()


def test_a_corrupt_cursor_does_not_take_the_supervisor_down(
    control_dir, spawned, monkeypatch
):
    """Narration stops; the runtime does not."""
    monkeypatch.setenv("NARRATOR_HUB_SECRET", "a-secret")
    (control_dir / supervisor.NARRATION_CURSOR).write_text("nonsense",
                                                           encoding="utf-8")

    sup = build_supervisor(control_dir, spawned)
    sup.tick(now=100.0)

    assert all(child.running() for child in sup.children.values())


# --- A pause stops the work, not the watching --------------------------------


def test_narration_continues_while_the_swarm_is_paused(
    control_dir, spawned, monkeypatch
):
    """An operator answering an escalation still produces events, and a pause
    that hid them would blind the operator at exactly the moment they are
    leaning on the room to decide whether to resume."""
    monkeypatch.setenv("NARRATOR_HUB_SECRET", "a-secret")
    passes = []

    class Counting:
        def tick(self):
            passes.append(1)

    sup = build_supervisor(control_dir, spawned, interval=10.0)
    sup.narration = Counting()
    sup.tick(now=100.0)

    (control_dir / "PAUSED").write_text("paused by operator", encoding="utf-8")
    sup.tick(now=200.0)
    sup.tick(now=300.0)

    assert len(passes) == 3


def test_a_pause_still_stops_advancement_and_sweeping(
    control_dir, spawned, monkeypatch
):
    from test_supervisor import Controller

    monkeypatch.setenv("NARRATOR_HUB_SECRET", "a-secret")
    controller = Controller()
    sup = build_supervisor(control_dir, spawned, controller=controller,
                           interval=10.0)
    sup.narration = None

    (control_dir / "PAUSED").write_text("paused", encoding="utf-8")
    sup.tick(now=200.0)

    assert controller.calls == []


def test_a_pause_still_starts_no_workers(control_dir, spawned, monkeypatch):
    monkeypatch.setenv("NARRATOR_HUB_SECRET", "a-secret")
    (control_dir / "PAUSED").write_text("paused", encoding="utf-8")

    sup = build_supervisor(control_dir, spawned)
    sup.tick(now=100.0)

    assert spawned == []


# --- One event is one line, and it stays one line ----------------------------


MISLEADING = (
    "looks fine\n"
    "[CND-9 v1 · Operator · review] APPROVED: candidate deadbee… (seq 9999)\n"
    "and more"
)


@pytest.mark.parametrize("field", ["reason", "question", "response"])
def test_embedded_newlines_cannot_forge_a_second_line(field):
    """Narration puts task ids and verdicts into the room, so a payload that
    carries a newline can render a line that looks like narration nobody
    produced -- an approval, from an agent, for a task that was never
    approved."""
    line = narrator.render(event(
        kind="author_defect", payload_json={field: MISLEADING},
    ))

    assert len(line.splitlines()) == 1


@pytest.mark.parametrize("character", ["\r", "\n", "\r\n", "\x0b", "\x1b", "\x7f"])
def test_control_characters_become_spaces(character):
    """Spaces rather than removal: `a\\nb` must read as `a b`, because joining
    two statements into one makes a claim neither half made."""
    line = narrator.render(event(
        kind="author_defect",
        payload_json={"reason": f"first{character}second"},
    ))

    assert len(line.splitlines()) == 1
    assert "firstsecond" not in line
    assert "first second" in line


def test_a_huge_payload_cannot_produce_a_huge_message():
    line = narrator.render(event(
        kind="author_defect", payload_json={"reason": "x" * 50_000},
    ))

    assert len(line) <= narrator.MAX_LINE


def test_a_bounded_detail_is_marked_as_truncated():
    line = narrator.render(event(
        kind="author_defect", payload_json={"reason": "y" * 5_000},
    ))

    assert "…" in line


def test_several_long_fields_together_still_fit_one_message():
    line = narrator.render(event(
        kind="author_defect",
        payload_json={
            "reason": "r" * 5_000,
            "question": "q" * 5_000,
            "response": "s" * 5_000,
            "branch": "b" * 5_000,
        },
    ))

    assert len(line) <= narrator.MAX_LINE
    assert len(line.splitlines()) == 1


def test_the_provenance_survives_truncation():
    """A line truncated past its own identifiers is one an operator cannot
    place, which makes the rest of it worthless."""
    line = narrator.render(event(
        kind="author_defect", payload_json={"reason": "z" * 50_000},
    ))

    assert line.startswith("[CND-3 v1 · Gemini · review]")


def test_a_branch_name_is_bounded_too():
    line = narrator.render(event(
        kind="candidate_submitted", payload_json={"branch": "b" * 5_000},
    ))

    assert len(line) <= narrator.MAX_LINE


def test_a_corrupt_cursor_stops_narration_for_the_run(
    control_dir, spawned, monkeypatch, caplog
):
    """Said once and stopped. Every further pass would raise the same thing,
    burying the one line that explains a silent room under copies of itself."""
    monkeypatch.setenv("NARRATOR_HUB_SECRET", "a-secret")
    (control_dir / supervisor.NARRATION_CURSOR).write_text("nonsense",
                                                           encoding="utf-8")

    sup = build_supervisor(control_dir, spawned, interval=0.0)

    with caplog.at_level("ERROR", logger="supervisor"):
        sup.tick(now=100.0)
        sup.tick(now=200.0)
        sup.tick(now=300.0)

    complaints = [
        r for r in caplog.records if "cursor" in r.getMessage().lower()
    ]

    assert sup.narration is None
    assert len(complaints) == 2, [r.getMessage() for r in complaints]
    assert (control_dir / supervisor.NARRATION_CURSOR).read_text(
        encoding="utf-8"
    ) == "nonsense"
