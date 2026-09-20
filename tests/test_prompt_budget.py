"""A prompt too large for its model is refused before it costs anything (#24).

T-INFRA-11 asked for a change across three writable files with four read-only
context files beside them. `swarm_control.py` alone is about 11.7k tokens; the
whole prompt came to roughly 38k against gpt-4o's 30k-per-minute organisation
limit. OpenAI refused it before generating a word. The worker recorded "the
model returned nothing" (#20), the activation was charged against the author
budget (#21), and the task had to be cancelled and recreated without its
context files.

Every part of that was avoidable at the moment the prompt existed and nothing
had been spent, which is where this measures.

Two halves are tested here: what `prompt_budget` decides, and what the worker
does with the decision. The second matters as much -- a correct measurement
reported nowhere an operator reads is the defect #20 was about.
"""

from __future__ import annotations

import pytest

import prompt_budget


def contributor(path, tokens):
    """A `{path, text}` entry of roughly `tokens` estimated tokens."""
    return {"path": path, "text": "x" * (tokens * prompt_budget.CHARS_PER_TOKEN)}


def prompt_of(tokens):
    return "y" * (tokens * prompt_budget.CHARS_PER_TOKEN)


# --- What it measures ---------------------------------------------------------


def test_the_estimate_comes_from_the_prompt_not_its_parts():
    """The rendered string is the fact; contributors only attribute it.

    Summing the parts would re-derive what `render_author_prompt` does -- the
    fixed sections, the contract, the rejection, the operator context -- and
    that derivation goes silently wrong the day the prompt's shape changes.
    """
    measured = prompt_budget.measure(
        prompt_of(9_000), contributors=[contributor("a.py", 10)], limit=30_000)

    assert measured["estimate"] == 9_000


def test_a_prompt_with_no_contributors_is_still_measured():
    """A prompt large for a reason no file explains is still too large."""
    measured = prompt_budget.measure(prompt_of(40_000), limit=30_000)

    assert measured["estimate"] == 40_000
    assert measured["over"] is True
    assert measured["largest"] == []


@pytest.mark.parametrize("text,tokens", [
    ("", 0),
    ("x", 1),
    ("x" * 4, 1),
    ("x" * 5, 2),
])
def test_tokens_are_estimated_and_rounded_up(text, tokens):
    """Rounded up so anything at all is at least one: a section that exists
    should never measure as nothing."""
    assert prompt_budget.estimated_tokens(text) == tokens


def test_the_t_infra_11_shape_is_refused():
    """The case this exists for, at the size it actually was."""
    measured = prompt_budget.measure(
        prompt_of(38_000),
        contributors=[contributor("swarm_control.py", 11_700)],
        limit=30_000,
    )

    assert measured["over"] is True
    assert measured["estimate"] == 38_000


# --- Over, near, and neither --------------------------------------------------


def test_a_prompt_inside_the_margin_is_neither():
    measured = prompt_budget.measure(prompt_of(1_000), limit=30_000)

    assert measured["over"] is False
    assert measured["near"] is False


def test_a_prompt_past_the_warn_fraction_is_near():
    measured = prompt_budget.measure(
        prompt_of(25_000), limit=30_000, warn_fraction=0.8)

    assert measured["near"] is True
    assert measured["over"] is False


def test_over_and_near_are_never_both_true():
    """A caller treating them as independent would report a refusal and a
    warning for the same prompt."""
    measured = prompt_budget.measure(prompt_of(40_000), limit=30_000)

    assert measured["over"] is True
    assert measured["near"] is False


def test_exactly_at_the_limit_is_not_over():
    """The limit is what the model accepts, so accepting it is correct."""
    measured = prompt_budget.measure(prompt_of(30_000), limit=30_000)

    assert measured["over"] is False


def test_one_token_past_the_limit_is_over():
    measured = prompt_budget.measure(prompt_of(30_001), limit=30_000)

    assert measured["over"] is True


def test_the_warn_fraction_is_configurable():
    lenient = prompt_budget.measure(
        prompt_of(25_000), limit=30_000, warn_fraction=0.95)

    assert lenient["near"] is False


# --- What it names ------------------------------------------------------------


def test_the_largest_inputs_are_named_biggest_first():
    measured = prompt_budget.measure(
        prompt_of(40_000),
        contributors=[
            contributor("small.py", 10),
            contributor("huge.py", 11_700),
            contributor("middling.py", 900),
        ],
        limit=30_000,
    )
    named = [entry["path"] for entry in measured["largest"]]

    assert named == ["huge.py", "middling.py", "small.py"]


def test_empty_contributors_are_not_named():
    """Naming a file that contributes nothing is noise in a chat room."""
    measured = prompt_budget.measure(
        prompt_of(40_000),
        contributors=[contributor("real.py", 500), {"path": "empty.py", "text": ""}],
        limit=30_000,
    )

    assert [entry["path"] for entry in measured["largest"]] == ["real.py"]


def test_only_so_many_are_named():
    measured = prompt_budget.measure(
        prompt_of(40_000),
        contributors=[contributor(f"f{n}.py", n + 1) for n in range(20)],
        limit=30_000,
    )

    assert len(measured["largest"]) == prompt_budget.LARGEST_SHOWN


# --- What it says -------------------------------------------------------------


def test_the_refusal_says_nothing_was_spent():
    """An operator reading this in the room should not go looking for a
    charged attempt that does not exist."""
    measured = prompt_budget.measure(prompt_of(38_000), limit=30_000)
    said = prompt_budget.refusal(measured)

    assert "no attempt was spent" in said


def test_the_refusal_names_the_numbers_and_the_files():
    measured = prompt_budget.measure(
        prompt_of(38_000),
        contributors=[contributor("swarm_control.py", 11_700)],
        limit=30_000,
    )
    said = prompt_budget.refusal(measured)

    assert "38,000" in said
    assert "30,000" in said
    assert "swarm_control.py" in said
    assert "11,700" in said


def test_every_message_says_the_count_is_estimated():
    """The #48 lesson: a number that claims precision it does not have is
    worse than one that admits what it is."""
    over = prompt_budget.refusal(prompt_budget.measure(prompt_of(40_000), limit=30_000))
    near = prompt_budget.warning(prompt_budget.measure(prompt_of(25_000), limit=30_000))

    assert "estimated" in over.lower()
    assert "estimated" in near.lower()


@pytest.mark.parametrize("message", ["refusal", "warning"])
def test_no_message_claims_to_have_counted(message):
    """Saying "estimated" somewhere is not enough if the same sentence also
    claims exactness.

    A mutation replacing the ratio disclosure with "Counted exactly." survived
    the assertion above, because the word "estimated" still appeared earlier
    in the text. The message was then self-contradictory and claimed a
    precision it does not have, which is the whole #48 failure.
    """
    measured = prompt_budget.measure(prompt_of(40_000), limit=30_000)
    said = getattr(prompt_budget, message)(measured).lower()

    assert "counted exactly" not in said
    assert "exact" not in said


def test_the_refusal_discloses_the_ratio_it_used():
    """So a reader can judge the estimate rather than take it, and can tell
    at a glance how much slack a 38,000-against-30,000 call really had."""
    said = prompt_budget.refusal(
        prompt_budget.measure(prompt_of(40_000), limit=30_000))

    assert "not counted" in said.lower()
    assert str(prompt_budget.CHARS_PER_TOKEN) in said


def test_the_refusal_says_what_to_do():
    measured = prompt_budget.measure(prompt_of(38_000), limit=30_000)

    assert "Remove context files" in prompt_budget.refusal(measured)


def test_the_warning_does_not_read_as_a_failure():
    """The run worked. This is a note for whoever reads the task next.

    Asserted against the refusal's own claims rather than the word "refused",
    which the warning uses hypothetically -- "a little more context would have
    been refused" is the thing it is for. A substring check could not tell the
    two apart, and would have been a test about spelling.
    """
    said = prompt_budget.warning(prompt_budget.measure(prompt_of(25_000), limit=30_000))

    assert "was not sent" not in said
    assert "no attempt was spent" not in said
    assert "Remove context files" not in said


# --- What is carried onto an outcome ------------------------------------------


def test_nothing_is_carried_for_a_prompt_that_was_fine():
    measured = prompt_budget.measure(prompt_of(1_000), limit=30_000)

    assert prompt_budget.carried(measured) == {}


def test_nothing_is_carried_for_a_prompt_that_was_refused():
    """An over-limit prompt reports its own refusal; there is no outcome to
    carry a warning on, because no run happened."""
    measured = prompt_budget.measure(prompt_of(40_000), limit=30_000)

    assert prompt_budget.carried(measured) == {}


def test_nothing_is_carried_when_nothing_was_measured():
    assert prompt_budget.carried(None) == {}


def test_a_near_prompt_carries_the_numbers_and_the_reason():
    """`reason` is the field the narrator puts in the room, which is how this
    reaches an operator rather than a log file on OFFICEPC."""
    measured = prompt_budget.measure(prompt_of(25_000), limit=30_000)
    carried = prompt_budget.carried(measured)

    assert carried["prompt_tokens_estimated"] == 25_000
    assert carried["prompt_token_limit"] == 30_000
    assert "reason" in carried


def test_the_carried_numbers_and_text_travel_together():
    """Kept in one helper so a caller cannot report half of it."""
    carried = prompt_budget.carried(
        prompt_budget.measure(prompt_of(25_000), limit=30_000))

    assert set(carried) == {
        "prompt_tokens_estimated", "prompt_token_limit", "reason"}
