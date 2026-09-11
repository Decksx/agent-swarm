"""The task state machine.

`SWARM_PROTOCOL_v7.md` §8 as data. Invariant 14 is the whole point of this
file: **undefined state transitions are rejected.** Encoding the table rather
than scattering `if state == ...` checks through the request handlers is what
makes that enforceable — an unlisted `(state, event)` pair has nowhere to be
handled, so it fails by construction instead of by somebody remembering to
check.

Authority is part of the table, not a separate concern. "Who may cause this"
belongs with "what does this do", because the interesting failures are the ones
where a transition is legal but the caller was not entitled to it — a worker
declaring its own work accepted, for instance.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, NamedTuple, Tuple

# --- Roles ------------------------------------------------------------------
#
# The authority a caller acts with. Deliberately coarse: this is about which
# plane a request came from, not which specific agent, because the per-agent
# check (does this activation belong to this worker?) is a different question
# answered against the activations table.

CONTROLLER = "controller"
AUTHOR = "author"
VERIFIER = "verifier"
OPERATOR = "operator"
ADMIN = "admin"

ROLES = frozenset({CONTROLLER, AUTHOR, VERIFIER, OPERATOR, ADMIN})


# --- States -----------------------------------------------------------------

STATES: FrozenSet[str] = frozenset({
    "DRAFT",
    "VALIDATED",
    "READY_AUTHOR",
    "AUTHOR_ASSIGNED",
    "AUTHORING",
    "AUTHOR_PAUSED",
    "AUTHOR_BLOCKED",
    "READY_REVIEW",
    "REVIEW_ASSIGNED",
    "REVIEWING",
    "REVIEW_PAUSED",
    "REVIEW_BLOCKED",
    "CHANGES_REQUESTED",
    "READY_INTEGRATION",
    "INTEGRATING",
    # An integration whose activation expired while it may already have had
    # external effects. Deliberately not a failure and deliberately not a
    # retryable state.
    #
    # Every other stage can be reclaimed by putting the task back: nothing an
    # author or a reviewer does outside the controller survives losing its
    # lease. Integration is the one stage that reaches out and changes
    # something a later run cannot undo by starting over. A lease that lapses
    # mid-merge leaves two possibilities -- the merge landed, or it did not --
    # and the controller cannot tell them apart from its own records.
    #
    # Sending such a task back to READY_INTEGRATION would invite a second
    # merge of a candidate that may already be on the target. Calling it
    # COMPLETE would claim a landing nobody observed. Both are worse than
    # saying plainly that the outcome is unknown and must be reconciled
    # against the remote.
    "INTEGRATION_UNCERTAIN",
    "REVERTING",
    "NEEDS_HUMAN",
    "COMPLETE",
    "FAILED",
    "CANCELLED",
    "SUPERSEDED",
    "EXPIRED",
    "REVERTED",
})

# A terminal state accepts nothing further. `COMPLETE` is the one exception and
# it is deliberate: §8 allows `COMPLETE -> REVERTED` via `regression_reverted`,
# because discovering later that an integrated change was wrong has to be
# recordable. It is handled as an explicit transition below rather than by
# making COMPLETE non-terminal, so nothing else can move a completed task.
TERMINAL_STATES: FrozenSet[str] = frozenset({
    "COMPLETE",
    "FAILED",
    "CANCELLED",
    "SUPERSEDED",
    "EXPIRED",
    "REVERTED",
})

assert TERMINAL_STATES <= STATES


class Transition(NamedTuple):
    to_state: str
    authorities: FrozenSet[str]


def _t(to_state: str, *authorities: str) -> Transition:
    assert to_state in STATES, to_state
    assert all(a in ROLES for a in authorities), authorities

    return Transition(to_state, frozenset(authorities))


# --- The table --------------------------------------------------------------
#
# Keyed by (from_state, event_kind). Mirrors §8's "Principal transitions",
# including its authority column.

TRANSITIONS: Dict[Tuple[str, str], Transition] = {
    ("DRAFT", "contract_validated"): _t("VALIDATED", CONTROLLER),
    ("DRAFT", "validation_failed"): _t("DRAFT", CONTROLLER),

    ("VALIDATED", "queued"): _t("READY_AUTHOR", CONTROLLER),

    ("READY_AUTHOR", "author_activation_issued"): _t("AUTHOR_ASSIGNED", CONTROLLER),

    ("AUTHOR_ASSIGNED", "activation_claimed"): _t("AUTHORING", AUTHOR),
    ("AUTHOR_ASSIGNED", "lease_expired"): _t("READY_AUTHOR", CONTROLLER),
    ("AUTHOR_ASSIGNED", "hard_deadline_reached"): _t("READY_AUTHOR", CONTROLLER),

    ("AUTHORING", "candidate_submitted"): _t("READY_REVIEW", AUTHOR),
    ("AUTHORING", "checkpoint_captured"): _t("AUTHOR_PAUSED", CONTROLLER, OPERATOR),
    ("AUTHORING", "environment_defect"): _t("AUTHOR_BLOCKED", CONTROLLER),
    ("AUTHORING", "author_defect"): _t("CHANGES_REQUESTED", CONTROLLER),
    ("AUTHORING", "lease_expired"): _t("READY_AUTHOR", CONTROLLER),
    ("AUTHORING", "deadline_checkpointed"): _t("AUTHOR_PAUSED", CONTROLLER, OPERATOR),
    ("AUTHORING", "deadline_without_checkpoint"): _t("READY_AUTHOR", CONTROLLER),

    ("AUTHOR_PAUSED", "author_activation_issued"): _t("AUTHOR_ASSIGNED", CONTROLLER),
    ("AUTHOR_BLOCKED", "environment_repaired"): _t("READY_AUTHOR", CONTROLLER),

    ("READY_REVIEW", "review_activation_issued"): _t("REVIEW_ASSIGNED", CONTROLLER),

    ("REVIEW_ASSIGNED", "activation_claimed"): _t("REVIEWING", VERIFIER),
    ("REVIEW_ASSIGNED", "lease_expired"): _t("READY_REVIEW", CONTROLLER),
    ("REVIEW_ASSIGNED", "hard_deadline_reached"): _t("READY_REVIEW", CONTROLLER),

    # Controller authority, deliberately: a verifier must not be able to
    # advance a task by declaring a gate met.
    #
    # The protocol also requires the controller to emit this only when the
    # deterministic completion predicates hold, computed from evidence rows.
    # **Those predicates are not implemented.** Nothing in this controller
    # computes them, and this table cannot enforce them -- it maps
    # (state, event, authority) and knows nothing about evidence.
    #
    # For the MVP the gate is the reviewer's authenticated judgment, applied
    # with controller authority by activations.submit_review_judgment() once it
    # has verified the caller holds that specific live review activation. That
    # is weaker than the protocol asks for and is recorded as such here rather
    # than described as if the predicates existed.
    ("REVIEWING", "review_requirements_satisfied"): _t("READY_INTEGRATION", CONTROLLER),
    ("REVIEWING", "author_defect"): _t("CHANGES_REQUESTED", CONTROLLER),
    ("REVIEWING", "checkpoint_captured"): _t("REVIEW_PAUSED", CONTROLLER, OPERATOR),
    ("REVIEWING", "environment_defect"): _t("REVIEW_BLOCKED", CONTROLLER),
    ("REVIEWING", "proof_inconclusive"): _t("NEEDS_HUMAN", CONTROLLER),
    ("REVIEWING", "decision_required"): _t("NEEDS_HUMAN", VERIFIER, CONTROLLER),
    ("REVIEWING", "lease_expired"): _t("READY_REVIEW", CONTROLLER),
    ("REVIEWING", "deadline_checkpointed"): _t("REVIEW_PAUSED", CONTROLLER, OPERATOR),
    ("REVIEWING", "deadline_without_checkpoint"): _t("READY_REVIEW", CONTROLLER),

    ("REVIEW_PAUSED", "review_activation_issued"): _t("REVIEW_ASSIGNED", CONTROLLER),
    ("REVIEW_BLOCKED", "environment_repaired"): _t("READY_REVIEW", CONTROLLER),

    ("CHANGES_REQUESTED", "retry_authorized"): _t("READY_AUTHOR", CONTROLLER),
    ("CHANGES_REQUESTED", "budget_exhausted"): _t("NEEDS_HUMAN", CONTROLLER),

    ("READY_INTEGRATION", "integration_started"): _t("INTEGRATING", CONTROLLER, OPERATOR),
    # A self-transition, and the only one in this table.
    #
    # The other two stages have an assigned state and a running state, so the
    # claim is what moves between them. Integration has one state: issuing the
    # activation moves READY_INTEGRATION -> INTEGRATING, and there is nowhere
    # further to go until the attempt ends.
    #
    # Recorded anyway, because without it an integrate activation cannot be
    # claimed at all -- `claim` applies this event and an undefined transition
    # refuses. That is how it was found. The event also answers a question the
    # state cannot: which worker picked this up, and when. A task sitting in
    # INTEGRATING with no claim recorded is one nobody has started.
    ("INTEGRATING", "activation_claimed"): _t("INTEGRATING", OPERATOR),
    # Self-transition: a reservation changes scheduling, not stage.
    ("READY_INTEGRATION", "reservation_granted"): _t("READY_INTEGRATION", CONTROLLER),

    ("INTEGRATING", "integration_rejected"): _t("CHANGES_REQUESTED", CONTROLLER, OPERATOR),
    # The expiry path. Not `lease_expired`, which means "nothing happened,
    # start again" -- here something may have happened and the point is that
    # nobody knows.
    ("INTEGRATING", "integration_outcome_unknown"): _t(
        "INTEGRATION_UNCERTAIN", CONTROLLER
    ),
    # Reconciliation, once somebody or something has looked at the remote.
    # Two outcomes, because there are exactly two facts it can establish, and
    # each leads somewhere different.
    #
    # `landed`: the merge is on the target. The task is COMPLETE, and it is
    # reached through this event rather than `integration_completed` so the
    # ledger distinguishes an integration observed by the integrator from one
    # reconstructed afterwards. They are not the same evidence.
    ("INTEGRATION_UNCERTAIN", "integration_reconciled_landed"): _t(
        "COMPLETE", CONTROLLER, OPERATOR
    ),
    # `absent`: nothing landed. Safe to try again, and only now.
    ("INTEGRATION_UNCERTAIN", "integration_reconciled_absent"): _t(
        "READY_INTEGRATION", CONTROLLER, OPERATOR
    ),
    # And the honest third answer: reconciliation itself could not decide.
    # A person looks.
    ("INTEGRATION_UNCERTAIN", "reconciliation_failed"): _t(
        "NEEDS_HUMAN", CONTROLLER, OPERATOR
    ),
    ("INTEGRATING", "integration_completed"): _t("COMPLETE", CONTROLLER),
    ("INTEGRATING", "rollback_started"): _t("REVERTING", CONTROLLER, OPERATOR),

    ("REVERTING", "rollback_completed"): _t("CHANGES_REQUESTED", CONTROLLER, OPERATOR),
    ("REVERTING", "repository_uncertain"): _t("NEEDS_HUMAN", CONTROLLER, OPERATOR),

    # §8: NEEDS_HUMAN has no generic resume. The Admin response selects one
    # explicit validated action, so each is its own event rather than a
    # "resume" carrying a destination in its payload -- a payload field would
    # put the choice back inside data the controller would have to validate
    # anyway.
    ("NEEDS_HUMAN", "return_to_author"): _t("READY_AUTHOR", ADMIN),
    ("NEEDS_HUMAN", "return_to_review"): _t("READY_REVIEW", ADMIN),
    ("NEEDS_HUMAN", "create_contract_version"): _t("DRAFT", ADMIN),
    ("NEEDS_HUMAN", "admin_failed"): _t("FAILED", ADMIN),

    # EXPIRED is a state in §8 and escalation has a timeout in §7
    # (`human_response_timeout_hours`), but Appendix A's event catalogue names
    # no event that produces it. `escalation_expired` is this implementation's
    # name for that transition. Recorded here as an addition rather than
    # presented as if the protocol specified it -- see docs/PHASE1_NOTES.md.
    ("NEEDS_HUMAN", "escalation_expired"): _t("EXPIRED", CONTROLLER),

    ("COMPLETE", "regression_reverted"): _t("REVERTED", ADMIN, CONTROLLER),
}

# §8: "Every nonterminal state also accepts Admin cancellation or
# supersession." Generated rather than written out, so a state added to STATES
# cannot accidentally be left without them.
for _state in STATES - TERMINAL_STATES:
    TRANSITIONS[(_state, "admin_cancelled")] = _t("CANCELLED", ADMIN)
    TRANSITIONS[(_state, "superseded")] = _t("SUPERSEDED", ADMIN, CONTROLLER)

del _state

# `note` is advisory: it appends an event and never changes state (Appendix A).
# It is not in TRANSITIONS because it is not a transition; the engine handles it
# separately, which keeps "events that move a task" and "events that do not"
# from being distinguishable only by reading a to_state.
NON_TRANSITIONING_EVENTS: FrozenSet[str] = frozenset({"note"})

EVENT_KINDS: FrozenSet[str] = frozenset(
    kind for _, kind in TRANSITIONS
) | NON_TRANSITIONING_EVENTS


class TransitionRejected(Exception):
    """A transition was refused. Carries why, for the event payload."""


class UndefinedTransition(TransitionRejected):
    """No rule exists for this (state, event) pair — invariant 14."""


class NotAuthorized(TransitionRejected):
    """The rule exists but the caller may not invoke it."""


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def resolve(from_state: str, kind: str, authority: str) -> Transition:
    """The transition for this pair, or raise.

    Order matters: an undefined pair is reported as undefined even when the
    caller also lacked authority, because "that cannot happen from here" is the
    more useful diagnosis and does not leak which roles could have done it.
    """
    if from_state not in STATES:
        raise UndefinedTransition(f"unknown state {from_state!r}")

    if kind not in EVENT_KINDS:
        raise UndefinedTransition(f"unknown event kind {kind!r}")

    try:
        transition = TRANSITIONS[(from_state, kind)]
    except KeyError:
        raise UndefinedTransition(
            f"{kind!r} is not a defined transition from {from_state!r}"
        ) from None

    if authority not in transition.authorities:
        raise NotAuthorized(
            f"{authority!r} may not cause {kind!r} from {from_state!r}"
        )

    return transition
