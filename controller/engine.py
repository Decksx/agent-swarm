"""Applying transitions: the only way authoritative task state changes.

Every function here that writes does so inside one `BEGIN IMMEDIATE`
transaction that appends the event *and* updates the projection. §4 requires
that pairing, and the reason is recovery rather than tidiness: the event log is
what rebuilds `tasks.state` after a crash, so a state that moved without an
event is unreconstructable and an event without the matching state is a lie
about what happened.

`replay_state()` exists to keep that honest. It rebuilds a task's state from
its events alone, and the tests assert it equals the stored projection. An
audit log that cannot reproduce the projection is a log, not a source of truth.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Optional

from .db import transaction
from .states import (
    CONTROLLER,
    NON_TRANSITIONING_EVENTS,
    TransitionRejected,
    resolve,
)


class TaskNotFound(Exception):
    pass


class StaleState(TransitionRejected):
    """The caller's view of the task is behind the stored one.

    Raised when a supplied `expected_state_seq` does not match. This is the
    guard against a decision computed from state the task has since left --
    a worker that spent ten minutes on an attempt and returns to find the task
    was cancelled must not be able to apply its result anyway.
    """


class ConflictingReplay(TransitionRejected):
    """The same event_id was submitted with different content.

    A duplicate delivery is idempotent; a *different* request reusing an
    event_id is a bug or an attack, and is refused rather than merged (§5).
    """


def contract_hash(contract_yaml: str) -> str:
    """Stable identity for a contract's text."""
    return hashlib.sha256(contract_yaml.encode("utf-8")).hexdigest()


def create_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    title: str,
    objective: str,
    contract_yaml: str,
    base_sha: str,
    created_by: str,
    proof_mode: str = "baseline",
    protocol_schema_version: int = 7,
    priority: int = 50,
    now: Optional[float] = None,
) -> dict:
    """Create a task and its version 1 contract, in DRAFT.

    Both rows are written together because a task without a version cannot
    have events: `events` has a foreign key onto `(task_id, task_version)`, so
    a task created alone could not record its own creation and would be
    invisible to replay.
    """
    now = time.time() if now is None else now
    digest = contract_hash(contract_yaml)

    with transaction(conn):
        conn.execute(
            "INSERT INTO tasks (task_id, title, objective, priority, "
            "current_version, state, state_seq, created_at, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, title, objective, priority, 1, "DRAFT", 0, now, created_by),
        )
        conn.execute(
            "INSERT INTO task_versions (task_id, version, contract_yaml, "
            "contract_hash, protocol_schema_version, base_sha, proof_mode, "
            "created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id, 1, contract_yaml, digest, protocol_schema_version,
                base_sha, proof_mode, now, created_by,
            ),
        )

    return {"task_id": task_id, "version": 1, "contract_hash": digest, "state": "DRAFT"}


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    """The task, including the contract and base of its current version.

    The two tables are joined here rather than left to callers because every
    caller wants the same thing and the omission was invisible: `tasks` has no
    `contract_yaml` and no `base_sha`, so a worker reading the task record got
    an empty contract and no baseline, and nothing said so. With the scope
    correction in place that now blocks authoring outright, which is the safe
    direction and also the reason it surfaced at all.

    The contract is served from here, never read from the tree being changed.
    A contract an author could edit is not a constraint on that author.
    """
    row = conn.execute(
        "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()

    if row is None:
        raise TaskNotFound(task_id)

    task = dict(row)

    version = conn.execute(
        "SELECT contract_yaml, contract_hash, base_sha, protocol_schema_version "
        "FROM task_versions WHERE task_id = ? AND version = ?",
        (task_id, task["current_version"]),
    ).fetchone()

    if version is not None:
        task.update(dict(version))

    # What the last review sent it back for, if it was sent back.
    #
    # A retry without this is the same generation with the same inputs, which
    # is not an attempt at the correction -- it is a re-roll. The author is
    # told what the reviewer said, verbatim and labelled as the reviewer's
    # words, so the second attempt can be about the thing that was wrong.
    rejection = conn.execute(
        "SELECT payload_json FROM events WHERE task_id = ? AND kind = 'author_defect' "
        "ORDER BY seq DESC LIMIT 1",
        (task_id,),
    ).fetchone()

    if rejection is not None:
        try:
            task["last_rejection"] = json.loads(rejection["payload_json"] or "{}")
        except (TypeError, ValueError):
            task["last_rejection"] = {}

    return task


def _existing_event(conn: sqlite3.Connection, event_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()

    return dict(row) if row else None


def apply_transition(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    kind: str,
    actor: str,
    authority: str,
    expected_state_seq: Optional[int] = None,
    activation_id: Optional[str] = None,
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict:
    """Append one event and move the task, atomically.

    `expected_state_seq` is optional but should be supplied by anything acting
    on a view of the task it fetched earlier. Omitting it means "apply to
    whatever state the task is in now", which is only safe for a decision the
    controller makes from state it read inside this same call.

    Supplying `event_id` makes the call idempotent: re-delivering the identical
    request returns the stored result rather than appending a second event.
    """
    now = time.time() if now is None else now
    payload = payload or {}
    event_id = event_id or uuid.uuid4().hex
    payload_json = json.dumps(payload, sort_keys=True)

    with transaction(conn):
        # Idempotency is checked inside the transaction, not before it. Outside,
        # two concurrent identical deliveries could both find no existing event
        # and both proceed.
        existing = _existing_event(conn, event_id)

        if existing is not None:
            same = (
                existing["task_id"] == task_id
                and existing["kind"] == kind
                and existing["actor"] == actor
                and existing["payload_json"] == payload_json
            )

            if not same:
                raise ConflictingReplay(
                    f"event_id {event_id!r} already exists with different content"
                )

            task = get_task(conn, task_id)

            return {
                "event_id": event_id,
                "task_id": task_id,
                "from_state": existing["from_state"],
                "to_state": existing["to_state"],
                "state_seq": task["state_seq"],
                "replayed": True,
            }

        task = get_task(conn, task_id)
        from_state = task["state"]

        if expected_state_seq is not None and expected_state_seq != task["state_seq"]:
            raise StaleState(
                f"expected state_seq {expected_state_seq}, task is at "
                f"{task['state_seq']}"
            )

        if kind in NON_TRANSITIONING_EVENTS:
            # Advisory. Appends an event, leaves state and state_seq alone --
            # so a note can never be the reason a task moved.
            to_state = from_state
            new_seq = task["state_seq"]
        else:
            # No explicit terminal-state check here. There was one, and the
            # bypass matrix proved it unreachable: TRANSITIONS contains no
            # entry from a terminal state except COMPLETE -> REVERTED, and
            # admin_cancelled/superseded are generated only for nonterminal
            # states, so resolve() already refuses every one of them. A guard
            # that fails nothing when removed was never load-bearing, and
            # leaving it would suggest the safety lives here rather than in the
            # table. It lives in the table, and
            # test_terminal_states_accept_nothing_except_the_one_allowed_exit
            # is what holds it there.
            transition = resolve(from_state, kind, authority)
            to_state = transition.to_state
            new_seq = task["state_seq"] + 1

        conn.execute(
            "INSERT INTO events (event_id, task_id, task_version, activation_id, "
            "source_event_id, actor, authority, kind, from_state, to_state, "
            "payload_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, task_id, task["current_version"], activation_id,
                source_event_id, actor, authority, kind, from_state, to_state,
                payload_json, now,
            ),
        )

        if new_seq != task["state_seq"] or to_state != from_state:
            conn.execute(
                "UPDATE tasks SET state = ?, state_seq = ? WHERE task_id = ?",
                (to_state, new_seq, task_id),
            )

    return {
        "event_id": event_id,
        "task_id": task_id,
        "from_state": from_state,
        "to_state": to_state,
        "state_seq": new_seq,
        "replayed": False,
    }


# How many author attempts a task gets before a person has to look at it.
# Not a cost control -- a loop detector. Two rejections in a row means the
# reviewer is asking for something the author is not able to produce from the
# contract it has, and a third attempt is the same generation with the same
# inputs. The state machine has always had `budget_exhausted` beside
# `retry_authorized` for this; nothing emitted either until now.
DEFAULT_AUTHOR_ATTEMPTS = 3


def authorize_retry(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    actor: str,
    max_attempts: int = DEFAULT_AUTHOR_ATTEMPTS,
    now: Optional[float] = None,
) -> dict:
    """Decide whether a rejected task gets another attempt.

    A controller decision, not an operator one, and the distinction is the
    same as everywhere else in section 8: the operator *asks* for a retry, and
    the controller either authorises one or refuses and escalates. An
    admin-authority route for this would let an operator keep buying attempts
    past the point where the loop is the problem.

    Attempts are counted from the activations actually issued rather than from
    a counter on the task, because that is the number that reflects what was
    really spent -- a task repaired, superseded, or re-versioned does not get
    its history rewritten by this.

    Returns the transition outcome. On exhaustion the task goes to NEEDS_HUMAN
    rather than raising: refusing another attempt is a decision the ledger
    should carry, not an error the caller can ignore.
    """
    spent = conn.execute(
        "SELECT COUNT(*) AS n FROM activations "
        "WHERE task_id = ? AND stage = 'author' AND chargeable_attempt = 1",
        (task_id,),
    ).fetchone()["n"]

    if spent >= max_attempts:
        return apply_transition(
            conn,
            task_id=task_id,
            kind="budget_exhausted",
            actor=actor,
            authority=CONTROLLER,
            now=now,
            payload={"author_attempts": spent, "max_attempts": max_attempts},
        )

    return apply_transition(
        conn,
        task_id=task_id,
        kind="retry_authorized",
        actor=actor,
        authority=CONTROLLER,
        now=now,
        payload={"author_attempts": spent, "max_attempts": max_attempts},
    )


def replay_state(conn: sqlite3.Connection, task_id: str) -> Optional[str]:
    """Rebuild a task's state from its events alone.

    Reads only the event log — never `tasks.state` — so comparing the two is a
    real check. Returns None for a task with no events.
    """
    rows = conn.execute(
        "SELECT to_state FROM events WHERE task_id = ? ORDER BY seq ASC",
        (task_id,),
    ).fetchall()

    if not rows:
        return None

    return rows[-1]["to_state"]


def event_log(conn: sqlite3.Connection, task_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM events WHERE task_id = ? ORDER BY seq ASC", (task_id,)
    ).fetchall()

    return [dict(row) for row in rows]
