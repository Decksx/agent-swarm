"""Mirror what the controller decided into the chatroom, and nothing else.

Why this exists
---------------

The runtime became unattended before it became legible. The supervisor keeps
three workers alive and drives progression on a timer, and the only way to
learn what any of it did was to read a log file on OFFICEPC. That gap is not
theoretical: chatgpt was locked out of the swarm permanently by a stale pid
file, and the only symptom an operator could see was `status` reporting it as
"not running" -- indistinguishable from a worker that had simply finished.

So every decision the controller records is mirrored into the room the
operator is already watching, tagged with the task, version, stage and the
agent that actually did it.

What it is not
--------------

**It is not a second activation path.** Nothing here reads chat. Narration is
one-way, and the containment rule from Phase 0 is unchanged: a message in the
room carries no authority, cannot start work, and is never replied to
automatically. The operator's way back in is the controller
(`operator-response`), authenticated and task-scoped, and it is the controller
that decides whether that response is allowed to resume anything.

**It is not an agent.** It calls no model and makes no judgement. Every line it
posts is a rendering of an event the controller had already committed, which
is what keeps an empty queue costing nothing: no events, no messages, no
tokens.

**It never speaks as Admin.** Narration authenticates as the `narrator`
component and as nothing else. Posting machine text under the operator's own
identity would make the transcript unreadable in exactly the situation it
exists for -- a person scrolling back through an incident cannot tell their own
words from a rendering of a database. Without `NARRATOR_HUB_SECRET` narration
stops and says so; it does not fall back.

Delivery
--------

At-least-once, never at-most-once. The cursor advances only after the hub has
accepted a message, so a crash between posting and recording repeats a line
rather than losing it -- and every line carries its event sequence number, so
a repeat is recognisable as one rather than read as a second occurrence.

On first activation the cursor starts at the controller's current maximum
sequence and announces where it started. Replaying the ledger into the room
would bury the present under weeks of history, and the ledger is already
durable and queryable; this is a live view, not an archive.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("narrator")

# The component this authenticates as. Not `admin`: see the module docstring.
IDENTITY = "narrator"

# Where the room is told to look. Narration is addressed to the operator
# because it is for the operator; no worker reads it.
TARGET = "@Admin"

# How each actor is written. The controller's internal names are lowercase
# identifiers; a person reading the room should see the agent.
ACTORS = {
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "claudecode": "Claude",
    "controller": "Controller",
    "admin": "Admin",
    "operator": "Operator",
    "author": "Author",
    "verifier": "Verifier",
}

# What is worth saying, as an allowlist rather than a denylist.
#
# A denylist is the wrong shape here: the controller gains event kinds as it
# gains behaviour, and a new kind should have to be considered before it
# reaches the room rather than arrive in it by default. The cost of forgetting
# to add one is a quiet room; the cost of forgetting to exclude one is the
# noise that makes an operator stop reading, which is the same as having no
# narration at all.
#
# Heartbeats and idle polls are absent because they are not decisions, and
# they are the two highest-volume things the runtime does: a worker proving it
# is still alive every few seconds, and a progression pass finding nothing
# ready. Neither changes anything.
#
# "High volume" is the test, not "internal". Checkpoints were excluded here
# once on the reasoning that they are progress within an attempt, and that was
# wrong: a checkpoint moves authoring or review into a paused state, which is
# a status change an operator watching the room needs to see.
NARRATED = {
    # Work being handed to somebody.
    "author_activation_issued": "authoring",
    "review_activation_issued": "review issued",
    "activation_claimed": "claimed",
    "candidate_submitted": "candidate submitted",

    # Verdicts.
    "review_requirements_satisfied": "APPROVED",
    "author_defect": "CHANGES REQUESTED",
    "proof_inconclusive": "proof inconclusive",
    "decision_required": "decision required",

    # Integration.
    "integration_started": "integrating",
    "integration_completed": "INTEGRATED",
    "integration_rejected": "integration refused",
    "integration_outcome_unknown": "integration outcome unknown",
    "out_of_band_merge_reported": "out-of-band merge reported",
    "out_of_band_report_unfounded": "out-of-band report unfounded",
    "integration_reconciled_landed": "reconciled: landed",
    "integration_reconciled_absent": "reconciled: absent",
    "reconciliation_failed": "reconciliation failed",

    # Paused, which is a state change and not progress within an attempt.
    # These were excluded as bookkeeping and they are not: each moves
    # authoring or review into a paused state, which is precisely the status
    # change an operator is watching the room for.
    "checkpoint_captured": "paused at a checkpoint",
    "deadline_checkpointed": "paused at the deadline",

    # Failure and exhaustion.
    "validation_failed": "validation failed",
    "environment_defect": "environment defect",
    "environment_repaired": "environment repaired",
    "lease_expired": "lease expired",
    "hard_deadline_reached": "hard deadline reached",
    "deadline_without_checkpoint": "deadline passed with no checkpoint",
    "budget_exhausted": "BUDGET EXHAUSTED",
    "escalation_expired": "escalation expired",
    "repository_uncertain": "repository state uncertain",

    # Rollback.
    "rollback_started": "rolling back",
    "rollback_completed": "rolled back",
    "regression_reverted": "regression reverted",

    # Operator and admin authority.
    "operator_response": "OPERATOR",
    "return_to_author": "operator: returned to author",
    "return_to_review": "operator: returned to review",
    "create_contract_version": "operator: new contract version",
    "admin_failed": "operator: marked failed",
    "admin_cancelled": "operator: cancelled",
    "retry_authorized": "retry authorized",
    "superseded": "superseded",
}

# Recorded, deliberately unspoken. Named rather than merely omitted so that a
# reader can tell a decision not to narrate from an oversight.
NOT_NARRATED = {
    "contract_validated",        # the uninteresting half of validation
    "queued",                    # bookkeeping; the issue event says the same
    "reservation_granted",       # capacity accounting
    "note",                      # free text with no decision behind it
}


class CursorUnreadable(Exception):
    """Existing cursor state is damaged. Narration stops rather than guessing."""


class NarrationNotConfigured(Exception):
    """No narrator credential. Narration stops rather than speaking as Admin."""


def credential(env: Optional[dict] = None) -> str:
    """The narrator's own hub secret, or a refusal that names what is missing.

    There is deliberately no fallback. Every other component in this system
    fails closed when its credential is absent, and narration posting as Admin
    would be worse than failing closed rather than better: it would put machine
    text under the operator's identity in the one place the operator goes to
    find out what happened.
    """
    source = os.environ if env is None else env
    secret = (source.get("NARRATOR_HUB_SECRET") or "").strip()

    if not secret:
        raise NarrationNotConfigured(
            "NARRATOR_HUB_SECRET is not set, so narration cannot authenticate "
            "as the narrator component. Narration is disabled for this run. "
            "It will not post as admin instead: machine-generated text under "
            "the operator's own identity is worse than a silent room."
        )

    return secret


# One narrated line is one chat message, and a chat transcript is read as a
# sequence of them. Text arriving from an event payload -- a reviewer's
# rationale, an operator's question -- is written by a model or a person and
# can contain anything, so a newline in it would render as a second line that
# looks like narration nobody produced.
#
# Bounded for the same reason in the other direction: a payload carrying a
# whole diff would become a chat message nobody can scroll past, which costs
# the operator the room this exists to give them.
MAX_DETAIL = 240
MAX_LINE = 900

# The two ends of a line, bounded separately so the middle can never crowd
# them out. Together they leave the summary at least half the line.
MAX_PREFIX = 200
MAX_SUFFIX = 40

# One identifier inside the prefix -- a task id, an actor, a stage. Bounded
# individually so that the prefix's own brackets always survive.
MAX_IDENTIFIER = 48


def flatten(text: object, limit: int = MAX_DETAIL) -> str:
    """One line of at most `limit` characters, with nothing smuggled in it.

    Control characters become spaces rather than being stripped, so that
    `a
b` reads as `a b` and not as `ab` -- removing the boundary would join
    two statements into one that neither half made.
    """
    flat = "".join(
        " " if (character < " " or character == "") else character
        for character in str(text)
    )
    flat = " ".join(flat.split())

    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def short(sha: Optional[str], keep: int = 7) -> str:
    """A sha at reading length, marked as abbreviated."""
    text = (sha or "").strip()

    return f"{text[:keep]}…" if len(text) > keep else text


def actor_name(actor: Optional[str]) -> str:
    key = (actor or "").strip().lower()

    return ACTORS.get(key, key or "unknown")


def summarize(event: dict) -> str:
    """The part of the line that says what happened.

    Built from the event's own payload rather than from prose written at the
    call site, so a line cannot claim something the ledger does not record.
    """
    kind = event.get("kind")
    payload = event.get("payload_json") or {}

    if not isinstance(payload, dict):
        payload = {}

    headline = NARRATED.get(kind, kind)

    detail = []

    for field, label in (
        ("candidate_sha", "candidate"),
        ("approved_candidate_sha", "candidate"),
        ("merge_sha", "merge"),
        ("base_sha", "base"),
    ):
        if payload.get(field):
            detail.append(f"{label} {short(payload[field])}")

    if payload.get("branch"):
        detail.append(f"branch {flatten(payload['branch'], 120)}")

    for field in ("reason", "question", "response"):
        if payload.get(field):
            detail.append(flatten(payload[field]))

    to_state = event.get("to_state")
    from_state = event.get("from_state")

    if to_state and to_state != from_state:
        detail.append(f"-> {to_state}")

    return f"{headline}: {'; '.join(detail)}" if detail else headline


def render(event: dict) -> Optional[str]:
    """One chat line for one event, or None if this event is not narrated.

    The identifiers are not decoration. A room carrying several tasks at once
    is unreadable without them, and the sequence number is what makes a
    redelivered line recognisable as the same event rather than a second
    occurrence of it -- which matters because delivery is at-least-once by
    design.
    """
    kind = event.get("kind")

    if kind not in NARRATED:
        return None

    task = event.get("task_id") or "?"
    version = event.get("task_version")
    stage = event.get("stage")
    seq = event.get("seq")

    # Each part bounded on its own rather than the assembled prefix, so the
    # brackets survive. Bounding the prefix alone let a long enough task id
    # eat its own closing `]`, which leaves a line whose provenance is not
    # merely shortened but unparseable.
    task = flatten(task, MAX_IDENTIFIER)
    parts = [f"{task} v{flatten(version, 12)}" if version is not None else task]
    parts.append(flatten(actor_name(event.get("actor")), MAX_IDENTIFIER))

    if stage:
        parts.append(flatten(stage, MAX_IDENTIFIER))

    # Built in three pieces and bounded in the middle one, because the two
    # outer pieces are the line's provenance and truncation must never reach
    # them.
    #
    # Truncating the assembled string did reach them. Enough maximum-length
    # details pushed `(seq N)` past the bound and it was cut off -- and a line
    # without its sequence is one a repeat cannot be recognised by, which is
    # the entire mechanism that makes at-least-once delivery safe. The
    # prefix is bounded too, so a task id long enough to fill the line cannot
    # squeeze the suffix out from the other side.
    # The brackets and the separating spaces are added *after* flattening,
    # never inside it. `flatten` strips its result, so a prefix built as
    # "[...] " lost the space that separates it from the summary and a suffix
    # built as " (seq N)" lost the space before it -- which ran the three
    # pieces together into `[...]authoring: -> AUTHOR_ASSIGNED(seq 108)`.
    # Cosmetic, and the kind of cosmetic that makes a transcript harder to
    # scan in the moment it is being relied on.
    prefix = "[" + flatten(" · ".join(parts), MAX_PREFIX) + "] "
    suffix = " (seq " + flatten(seq, MAX_SUFFIX) + ")"
    room = MAX_LINE - len(prefix) - len(suffix)

    return prefix + flatten(summarize(event), max(room, 1)) + suffix


class Cursor:
    """Where narration has got to, on disk, so a restart does not replay.

    Written by atomic replacement. A cursor torn by a crash mid-write is worse
    than either outcome it could have held: a truncated file reads as no
    cursor at all, and a fresh narrator would then seed itself at the current
    maximum and silently skip everything that happened while it was down.
    Replacement makes the file either the old sequence or the new one.

    Duplicate delivery after a crash is acceptable and loss is not, which is
    why the cursor is written *after* the hub accepts a message rather than
    before. Every line carries its sequence number, so a repeat is
    recognisable as a repeat; a gap is not recognisable as anything.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> Optional[int]:
        """The last delivered sequence, or None if narration has never run.

        None means one thing only: there is no cursor file. Everything else
        that can go wrong here raises.

        Conflating them silently discards history. A file that cannot be read,
        or that holds something other than a number, is *existing state that
        has been damaged* -- and treating it as never-run makes the next pass
        seed at the current maximum, which skips every event since the last
        good cursor and reports nothing about having done so. That is the
        silent gap this whole cursor exists to prevent, arrived at through its
        own error handling.

        The file is left exactly as it is, because it is the evidence.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CursorUnreadable(
                f"the narration cursor at {self.path} exists and could not be "
                f"read ({exc}). Narration is stopped rather than restarted: "
                f"seeding at the current sequence would silently skip every "
                f"event since this cursor was last written. The file has been "
                f"left alone for diagnosis."
            ) from exc

        try:
            return int(raw.strip())
        except ValueError:
            raise CursorUnreadable(
                f"the narration cursor at {self.path} holds {raw.strip()[:80]!r}, "
                f"which is not a sequence number. Narration is stopped rather "
                f"than restarted: seeding at the current sequence would "
                f"silently skip every event since this cursor was last "
                f"written. The file has been left alone for diagnosis."
            )

    def write(self, seq: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".new")
        temporary.write_text(str(int(seq)), encoding="utf-8")
        os.replace(temporary, self.path)


class Narrator:
    """Reads the controller's event feed and says what it finds, once.

    Holds no state of its own beyond the cursor. It is driven by whatever is
    already running -- the supervisor's tick -- rather than being a fourth
    process, because a second narrator would say everything twice and there is
    nothing here that needs its own scheduler.
    """

    def __init__(self, *, controller_url: str, cursor: Cursor, secret: str,
                 requests_module, page: int = 200):
        self.controller_url = controller_url.rstrip("/")
        self.cursor = cursor
        self.secret = secret
        self.requests = requests_module
        self.page = page

    # --- talking to the two services ----------------------------------------

    def _auth(self):
        return (IDENTITY, self.secret)

    def feed(self, since: Optional[int]) -> Optional[dict]:
        """One page of events, or None if the controller could not be asked."""
        params = {"limit": self.page}

        if since is not None:
            params["since"] = since

        try:
            response = self.requests.get(
                f"{self.controller_url}/controller/events",
                params=params, auth=self._auth(), timeout=20,
            )
        except Exception as exc:
            log.warning("controller unreachable for narration: %s", exc)
            return None

        if response.status_code >= 400:
            log.warning(
                "controller refused the event feed: %s %s",
                response.status_code, response.text[:200],
            )
            return None

        try:
            return response.json()
        except ValueError:
            log.warning("controller returned unreadable JSON from the feed")
            return None

    def say(self, text: str) -> bool:
        """Post one line. Returns whether the hub accepted it."""
        try:
            response = self.requests.post(
                f"{self.controller_url}/send",
                json={"target": TARGET, "content": text},
                auth=self._auth(), timeout=20,
            )
        except Exception as exc:
            log.warning("hub unreachable for narration: %s", exc)
            return False

        if response.status_code >= 400:
            log.warning(
                "hub refused a narration line: %s %s",
                response.status_code, response.text[:200],
            )
            return False

        return True

    # --- the pass ------------------------------------------------------------

    def start(self) -> Optional[int]:
        """Seed the cursor at the ledger's current end and announce it.

        The maximum comes from the controller's own count, not from the tail
        of a page. A narrator that took its starting point from a limited page
        would begin at the end of its first *page* and then replay everything
        after it into the room -- which is the flood this exists to avoid,
        arrived at by looking like it was avoiding it.

        Announced before it is persisted, like every other line. Recording
        first and ignoring the result lost the announcement permanently when
        the hub was down: the cursor said narration had begun, so it never
        announced again. A crash between the two repeats the startup line
        instead, which is the at-least-once trade every other line makes.
        """
        body = self.feed(None)

        if body is None:
            return None

        maximum = int(body.get("max_seq") or 0)

        # Posted before it is recorded, like every other line. Writing the
        # cursor first and ignoring the result meant a hub that was down at
        # startup lost the announcement permanently: the cursor said the
        # narrator had begun, so it never announced again. A crash between the
        # two repeats the startup line instead, which is the same
        # at-least-once trade every other line already makes.
        if not self.say(f"Narrator started at seq {maximum}"):
            log.warning(
                "narration could not announce its start; it will try again "
                "on the next pass rather than begin silently"
            )
            return None

        self.cursor.write(maximum)
        log.info("narration started at seq %s", maximum)

        return maximum

    def tick(self) -> int:
        """Deliver whatever is new. Returns how many lines were posted."""
        since = self.cursor.read()

        if since is None:
            return 0 if self.start() is None else 0

        body = self.feed(since)

        if body is None:
            return 0

        said = 0

        # Ascending, and one at a time. The feed is ordered by sequence and
        # the cursor moves with it, so a failure stops the batch where it
        # happened rather than skipping past it: everything before the failed
        # event is delivered and recorded, and the next pass resumes at
        # exactly the event that failed.
        for event in body.get("events") or []:
            seq = event.get("seq")

            if seq is None or seq <= since:
                continue

            line = render(event)

            if line is None:
                # Excluded on purpose, and the cursor still advances past it.
                # Leaving it behind would make every pass re-read the same
                # heartbeats forever and never reach anything after them.
                since = seq
                self.cursor.write(seq)
                continue

            if not self.say(line):
                log.warning(
                    "narration stopped at seq %s; it will resume there", seq,
                )
                break

            since = seq
            self.cursor.write(seq)
            said += 1

        return said
