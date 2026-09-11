"""The operator's answer has to be in the prompt, not near it.

Transport to the worker process is not delivery. The claim response carried
`operator_context` and all three workers ignored it: ChatGPT built its prompt
from the task record and the repository, Gemini from the review packet, and
Claude from a preamble plus the task text. Every one of them would have
resumed an escalated task without ever seeing what the escalation was
answered with -- which is resuming into the position that raised the question.

So these capture what is actually handed to the model or the CLI and read the
answer out of it. A test that asserted the field arrived in the process would
have passed throughout the failure it was meant to catch.
"""

from __future__ import annotations

import pytest

import authored_change
import review_packet


ANSWER = {
    "response": "require sabotage mode; branch_only is not enough here",
    "action": "return_to_author",
    "actor": "admin",
    "event_seq": 412,
    "task_version": 3,
}

SUPERSEDED = {
    "response": "branch_only is fine, ship it",
    "action": "return_to_review",
    "actor": "admin",
    "event_seq": 87,
    "task_version": 2,
}


# --- The author prompt -------------------------------------------------------


def author_prompt(operator_context):
    """The prompt `chatgpt_worker` hands to the model, built the same way."""
    return authored_change.render_author_prompt({
        "task_id": "CND-7",
        "title": "tighten the guard",
        "objective": "make the check load-bearing",
        "allowed_paths": ["src/"],
        "operator_context": operator_context,
    })


def test_the_author_prompt_contains_the_operator_response():
    prompt = author_prompt(ANSWER)

    assert ANSWER["response"] in prompt


def test_the_author_prompt_attributes_the_answer_to_the_operator():
    """An instruction from a person is not the same as a line of the
    objective, and a model that cannot tell them apart will average them."""
    prompt = author_prompt(ANSWER)

    assert "OPERATOR" in prompt.upper()
    assert "admin" in prompt


def test_the_author_prompt_says_the_answer_outranks_the_objective():
    """The escalation happened because the two disagreed."""
    prompt = author_prompt(ANSWER).lower()

    assert "follow the operator" in prompt


def test_the_author_prompt_carries_the_action_and_the_provenance():
    prompt = author_prompt(ANSWER)

    assert "return_to_author" in prompt
    assert "412" in prompt
    assert "3" in prompt


def test_a_superseded_answer_is_not_in_the_author_prompt():
    """Only what the controller attached to *this* activation. A worker handed
    a replaced instruction would act on a decision the operator overruled."""
    prompt = author_prompt(ANSWER)

    assert SUPERSEDED["response"] not in prompt


def test_an_author_prompt_without_an_escalation_says_nothing_about_one():
    prompt = author_prompt(None)

    assert "OPERATOR" not in prompt.upper()
    assert "ESCALATED" not in prompt.upper()


@pytest.mark.parametrize("context", [
    None, {}, {"response": ""}, {"response": "   "},
])
def test_an_empty_answer_adds_no_section(context):
    """An empty section is worse than none: it tells a model an escalation
    happened and then does not say what was decided."""
    assert "ESCALATED" not in author_prompt(context).upper()


# --- The review prompt -------------------------------------------------------


def review_prompt(operator_context):
    """The prompt `gemini_worker` renders, from a packet built the same way."""
    packet = {
        "task_id": "CND-7",
        "title": "tighten the guard",
        "objective": "make the check load-bearing",
        "branch": "candidate/CND-7",
        "base_sha": "1" * 40,
        "candidate_sha": "2" * 40,
        "commits": ["abc1234 tighten"],
        "changed_files": ["src/guard.py"],
        "diff": "--- a/src/guard.py\n+++ b/src/guard.py\n",
        "diff_truncated": False,
        "author_summary": "",
        "test_output": "",
        "operator_context": operator_context,
    }

    return review_packet.render(packet)


def test_the_review_prompt_contains_the_operator_response():
    prompt = review_prompt(ANSWER)

    assert ANSWER["response"] in prompt


def test_the_review_prompt_attributes_and_ranks_the_answer():
    prompt = review_prompt(ANSWER)

    assert "OPERATOR" in prompt.upper()
    assert "follow the operator" in prompt.lower()


def test_a_superseded_answer_is_not_in_the_review_prompt():
    prompt = review_prompt(ANSWER)

    assert SUPERSEDED["response"] not in prompt


def test_a_review_prompt_without_an_escalation_says_nothing_about_one():
    assert "ESCALATED" not in review_prompt(None).upper()


def test_the_answer_appears_before_the_diff():
    """A reviewer reads top to bottom, and the answer changes what the diff is
    being judged against."""
    prompt = review_prompt(ANSWER)

    assert prompt.index(ANSWER["response"]) < prompt.index("FULL DIFF")


def test_the_packet_carries_the_answer_from_the_activation():
    """`build` is where the worker hands it over, so the field has to survive
    the packet and not only the renderer."""
    import inspect

    signature = inspect.signature(review_packet.build)

    assert "operator_context" in signature.parameters


# --- The call sites actually pass it ----------------------------------------
#
# The renderers above are only reached if each worker hands them the field.
# These read the worker source rather than running a model, because the thing
# being asserted is the wiring and the model call is the part that costs money.


@pytest.mark.parametrize("worker,call", [
    ("chatgpt_worker.py", "render_author_prompt"),
    ("gemini_worker.py", "review_packet.build"),
    ("claude_worker.py", "operator_section"),
])
def test_each_worker_passes_the_activation_context_into_its_prompt(worker, call):
    source = open(worker, encoding="utf-8").read()
    index = source.index(call)
    window = source[index:index + 700]

    assert "operator_context" in window, (
        f"{worker} builds its prompt without the operator's answer"
    )


def test_the_claude_worker_puts_the_answer_before_the_task():
    """A CLI worker reads its prompt top to bottom, so an instruction placed
    after the task it overrules is a footnote to it."""
    source = open("claude_worker.py", encoding="utf-8").read()

    assert "HANDOFF_PREAMBLE + (operator" in source
