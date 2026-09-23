"""Saying so, once, when a task has stopped moving and will not start again (#77).

`progression.advance` reports every task it declined and why, and the
supervisor asks it every twenty seconds. Most declines are a task mid-stage
and clear by themselves; those are logged at debug and should stay there. The
rest do not clear: a task with no branch to review from is declined identically
on every tick until a person does something. T-ACC2-README was declined that
way for sixteen hours, at debug, and nothing anywhere said so.

The controller decides which is which (`persistent` on each decline record).
This module decides only when to say it: the first time a persistent decline
is seen, and again if its stage or reason changes. Not every tick -- a line
repeated every twenty seconds is noise that buries the next real one -- and
not never again: once a task stops being declined it is forgotten, so the
next stall is news.

State is in memory and per supervisor. A restart announces a standing stall
once more, which is the right amount: the room learns the swarm came back and
something is still stuck.
"""

from __future__ import annotations

from typing import Iterable


def render(record: dict) -> str:
    """One line for the room and the log."""
    return (
        f"[{record.get('task_id')}] stalled: {record.get('state')} cannot "
        f"move to {record.get('stage')}: {record.get('reason')}. This will "
        "not clear by itself; it needs a person."
    )


class StallWatch:
    """Which persistent declines have already been announced."""

    def __init__(self) -> None:
        self._announced: dict = {}

    def observe(self, considered: Iterable[dict]) -> list:
        """(task_id, line) for each persistent decline not yet announced.

        `considered` must be one complete `advance` answer. A task absent from
        it is no longer being declined, and is forgotten.
        """
        fresh = []
        declined_now = set()

        for record in considered:
            if record.get("issued") or not record.get("persistent"):
                continue

            task_id = record.get("task_id")
            declined_now.add(task_id)
            key = (record.get("stage"), record.get("reason_code"))

            if self._announced.get(task_id) == key:
                continue

            self._announced[task_id] = key
            fresh.append((task_id, render(record)))

        for task_id in list(self._announced):
            if task_id not in declined_now:
                del self._announced[task_id]

        return fresh

    def forget(self, task_id) -> None:
        """Announce this one again next time -- the line did not get out."""
        self._announced.pop(task_id, None)
