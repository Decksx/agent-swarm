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
# Heartbeats and idle polls are absent because they are not decisions. A
# worker proving it is still alive every few seconds, and a progression pass
# finding nothing ready, are the two highest-volume things the runtime does
# and neither changes anything.
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
    "integration_reconciled_landed": "reconciled: landed",
    "integration_reconciled_absent": "reconciled: absent",
    "reconciliation_failed": "reconciliation failed",

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
    "checkpoint_captured",       # progress within an attempt, not a handoff
    "deadline_checkpointed",     # the same, at a boundary
    "contract_validated",        # the uninteresting half of validation
    "queued",                    # bookkeeping; the issue event says the same
    "reservation_granted",       # capacity accounting
    "note",                      # free text with no decision behind it
}


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
        detail.append(f"branch {payload['branch']}")

    if payload.get("reason"):
        detail.append(str(payload["reason"]))

    if payload.get("question"):
        detail.append(str(payload["question"]))

    if payload.get("response"):
        detail.append(str(payload["response"]))

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

    parts = [f"{task} v{version}" if version is not None else str(task)]
    parts.append(actor_name(event.get("actor")))

    if stage:
        parts.append(str(stage))

    return f"[{' · '.join(parts)}] {summarize(event)} (seq {seq})"
