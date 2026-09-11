"""Narration says what the ledger says, to the operator, in one direction.

Three properties, and the third is the one that took a branch to establish the
first time. Lines have to carry enough identity to be readable in a room with
several tasks in it. Volume has to stay decisions-only, or an operator stops
reading and the narration is worth nothing. And none of it may become a way
back in: chat carried remote execution before Phase 0, and a mirror that grew
a reply path would hand that back.
"""

from __future__ import annotations

import pytest

import narrator


def event(**overrides):
    """A controller event, shaped as the feed delivers one."""
    base = {
        "seq": 42,
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


# --- A line identifies its own source ----------------------------------------


def test_a_line_names_the_task_version_agent_and_stage():
    line = narrator.render(event(
        payload_json={"approved_candidate_sha": "165ba5a88f06b76211e43f5b338"},
    ))

    assert line.startswith("[CND-3 v1 · Gemini · review]")
    assert "APPROVED" in line
    assert "165ba5a…" in line


def test_the_agent_is_named_rather_than_its_identifier():
    """An operator reading the room should see the agent, not a database key."""
    assert "Claude" in narrator.render(event(actor="claudecode"))
    assert "ChatGPT" in narrator.render(event(actor="chatgpt"))
    assert "Controller" in narrator.render(event(actor="controller"))


def test_an_unknown_actor_is_shown_rather_than_hidden():
    """Better a name nobody recognises than a line that claims the wrong one."""
    assert "newcomer" in narrator.render(event(actor="newcomer"))


def test_every_line_carries_its_event_sequence():
    """Delivery is at-least-once, so a repeat has to be recognisable as one."""
    assert "(seq 42)" in narrator.render(event())
    assert "(seq 99)" in narrator.render(event(seq=99))


def test_a_sha_is_abbreviated_and_marked_as_abbreviated():
    line = narrator.render(event(
        kind="integration_completed",
        payload_json={"merge_sha": "c7b6ea93bede846dbe47f51446775ca6559664b9"},
    ))

    assert "c7b6ea9…" in line
    assert "c7b6ea93bede" not in line


def test_a_state_change_is_shown():
    line = narrator.render(event())

    assert "-> READY_INTEGRATION" in line


def test_a_transition_that_changes_nothing_is_not_dressed_up_as_one():
    line = narrator.render(event(from_state="REVIEWING", to_state="REVIEWING"))

    assert "->" not in line


def test_a_missing_version_does_not_produce_a_broken_line():
    line = narrator.render(event(task_version=None))

    assert line.startswith("[CND-3 · Gemini · review]")


def test_a_stageless_event_omits_the_stage_rather_than_inventing_one():
    line = narrator.render(event(actor="controller", stage=None))

    assert line.startswith("[CND-3 v1 · Controller]")


# --- The summary comes from the ledger, not from prose -----------------------


def test_the_summary_is_built_from_the_payload():
    line = narrator.render(event(
        kind="author_defect",
        actor="gemini",
        payload_json={"reason": "three tests fail under branch_only"},
    ))

    assert "CHANGES REQUESTED" in line
    assert "three tests fail under branch_only" in line


def test_a_needs_human_question_reaches_the_room():
    """The escalation an operator is meant to answer is the one thing that is
    useless if it stays in the database."""
    line = narrator.render(event(
        kind="decision_required",
        to_state="NEEDS_HUMAN",
        payload_json={"question": "merge into main or hold for the next slice?"},
    ))

    assert "NEEDS_HUMAN" in line
    assert "merge into main or hold for the next slice?" in line


def test_a_payload_that_is_not_a_mapping_does_not_raise():
    """A malformed payload must not take narration down with it."""
    assert narrator.render(event(payload_json=None)) is not None
    assert narrator.render(event(payload_json="not a dict")) is not None


# --- Volume is decisions only ------------------------------------------------


@pytest.mark.parametrize("kind", sorted(narrator.NOT_NARRATED))
def test_bookkeeping_is_not_narrated(kind):
    """Heartbeats, reservations, validation bookkeeping and bare notes are the
    highest-volume things the runtime does, and none of them changes
    anything."""
    assert narrator.render(event(kind=kind)) is None


@pytest.mark.parametrize("kind,expected", [
    ("checkpoint_captured", "AUTHOR_PAUSED"),
    ("deadline_checkpointed", "REVIEW_PAUSED"),
])
def test_a_checkpoint_that_pauses_a_task_is_narrated(kind, expected):
    """Excluded as bookkeeping once, and that was wrong. A checkpoint moves
    authoring or review into a paused state, which is exactly the status
    change an operator is watching the room for."""
    line = narrator.render(event(kind=kind, to_state=expected))

    assert line is not None
    assert "paused" in line
    assert expected in line


def test_an_unrecognised_kind_is_silent_rather_than_guessed_at():
    """The allowlist is the point. A kind the controller grows later has to be
    considered before it reaches the room, not arrive in it by default."""
    assert narrator.render(event(kind="some_kind_added_next_year")) is None


def test_the_two_lists_do_not_overlap():
    """A kind that is both narrated and excluded is a contradiction one of the
    two lists is wrong about."""
    assert not (set(narrator.NARRATED) & narrator.NOT_NARRATED)


def test_heartbeats_are_not_in_the_narrated_set():
    for noisy in ("heartbeat", "poll", "idle", "activation_heartbeat"):
        assert noisy not in narrator.NARRATED


# --- It never speaks as Admin ------------------------------------------------


def test_narration_authenticates_as_the_narrator_component():
    assert narrator.IDENTITY == "narrator"


def test_a_missing_credential_stops_narration_rather_than_falling_back():
    """The fallback is the failure mode. Machine text under the operator's own
    identity makes the transcript unreadable in exactly the situation it exists
    for -- a person scrolling back through an incident cannot tell their own
    words from a rendering of a database.
    """
    with pytest.raises(narrator.NarrationNotConfigured):
        narrator.credential(env={})


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_a_blank_credential_is_a_missing_one(value):
    with pytest.raises(narrator.NarrationNotConfigured):
        narrator.credential(env={"NARRATOR_HUB_SECRET": value})


def test_the_refusal_names_the_variable_and_says_narration_is_off():
    with pytest.raises(narrator.NarrationNotConfigured) as caught:
        narrator.credential(env={})

    message = str(caught.value)
    assert "NARRATOR_HUB_SECRET" in message
    assert "admin" in message.lower()


def test_an_admin_secret_in_the_environment_is_not_used():
    """The specific substitution that must not happen."""
    with pytest.raises(narrator.NarrationNotConfigured):
        narrator.credential(env={"HUB_SECRET": "the-admin-secret"})


def test_a_present_credential_is_returned_stripped():
    assert narrator.credential(
        env={"NARRATOR_HUB_SECRET": "  a-secret  "}
    ) == "a-secret"


def test_narration_is_addressed_to_the_operator():
    """No worker reads it, and nothing downstream may act on it."""
    assert narrator.TARGET == "@Admin"


def test_the_module_imports_no_model_sdk():
    """An empty queue must cost nothing. Narration renders events that were
    already committed; it decides nothing and calls nothing."""
    import inspect

    source = inspect.getsource(narrator)

    for sdk in ("openai", "anthropic", "google.generativeai", "genai"):
        assert sdk not in source
