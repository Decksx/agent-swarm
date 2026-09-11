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


def test_the_author_prompt_says_the_answer_is_authoritative_guidance():
    """The escalation happened because the swarm could not settle something."""
    prompt = author_prompt(ANSWER).lower()

    assert "authoritative guidance" in prompt


def test_the_author_prompt_says_the_answer_cannot_change_the_contract():
    """An earlier version said "follow the operator" over the objective, which
    made a sentence of prose a contract-modification route -- while the
    controller refuses `create_contract_version` through that same route
    because a contract needs structured fields, and the new task version
    carries the same contract hash."""
    prompt = author_prompt(ANSWER)

    assert "CANNOT change the contract" in prompt

    for protected in ("objective", "acceptance criteria", "base commit",
                      "proof mode", "allowed paths"):
        assert protected in prompt.lower(), protected


def test_the_author_prompt_says_what_to_do_instead():
    """Refusing is only useful if the worker is told the structured route."""
    prompt = author_prompt(ANSWER).lower()

    assert "new contract version is needed" in prompt
    assert "stop" in prompt


def test_the_author_prompt_does_not_tell_the_model_to_override_the_objective():
    prompt = author_prompt(ANSWER).lower()

    assert "follow the operator" not in prompt


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


def test_the_review_prompt_attributes_and_bounds_the_answer():
    prompt = review_prompt(ANSWER)

    assert "OPERATOR" in prompt.upper()
    assert "authoritative guidance" in prompt.lower()
    assert "CANNOT change the contract" in prompt


def test_the_reviewer_is_told_the_contract_is_unchanged():
    """A reviewer judging a candidate against a contract the author was told
    to ignore would be judging against something nobody was working to."""
    prompt = review_prompt(ANSWER).lower()

    assert "follow the operator" not in prompt
    assert "new contract version is needed" in prompt


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
