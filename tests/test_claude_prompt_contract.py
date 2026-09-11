"""What Claude is actually handed, captured at `run_task`.

The operator section tells a worker its instruction cannot move the base
commit, the proof mode or the allowed paths. Claude was never shown any of
them: `activation["task"]` is title and objective, assembled by the controller
client, and the contract fields sit in `task_record` which nothing rendered.

A boundary named but not drawn is worse than no boundary. It reads as a check
somebody has made, so a worker asked to cross one has no way to notice and
every reason to assume the question was already settled.

These capture the argument `run_task` is given -- the exact string handed to
the CLI -- and read both the contract and the answer out of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claude_worker  # noqa: E402


CONTRACT_YAML = (
    "schema_version: 7\n"
    "allowed_paths:\n"
    "  - notes\n"
    "acceptance:\n"
    "  - the guard is load-bearing\n"
)

TASK_RECORD = {
    "task_id": "CND-7",
    "title": "tighten the guard",
    "objective": "make the check load-bearing",
    "current_version": 3,
    "base_sha": "b4f8d21036520856b39f3c919905213da9754622",
    "proof_mode": "branch_only",
    "contract_hash": "12fa46f9230262b7674ecf9ca8b48d0ecd9ffc04",
    "contract_yaml": CONTRACT_YAML,
}

ANSWER = {
    "response": "require sabotage mode; branch_only is not enough here",
    "action": "return_to_author",
    "actor": "admin",
    "event_seq": 412,
    "task_version": 3,
}


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Runs the real author path and keeps what `run_task` was handed."""
    seen = {}

    def recorder(binary, instructions):
        seen["binary"] = binary
        seen["prompt"] = instructions

        return ("done", 0)

    monkeypatch.setattr(claude_worker, "run_task", recorder)
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", tmp_path / "inflight")

    return seen


class Queue:
    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({"outcome": outcome, "payload": payload or {}})


def run(captured, *, operator_context=None, task_record=TASK_RECORD):
    activation = {
        "activation_id": "A-1",
        "task_id": "CND-7",
        "task": "tighten the guard\n\nmake the check load-bearing",
        "task_record": task_record,
        "operator_context": operator_context,
    }
    claude_worker._execute_author(None, "claude", activation, Queue())

    return captured.get("prompt", "")


# --- The contract is in the prompt -------------------------------------------


def test_the_prompt_reaches_run_task_at_all(captured):
    assert run(captured)


@pytest.mark.parametrize("field,value", [
    ("task version", "3"),
    ("base commit", "b4f8d21036520856b39f3c919905213da9754622"),
    ("proof mode", "branch_only"),
    ("contract hash", "12fa46f9230262b7674ecf9ca8b48d0ecd9ffc04"),
])
def test_the_prompt_states_each_contract_field(captured, field, value):
    prompt = run(captured)

    assert field in prompt.lower(), field
    assert value in prompt, value


def test_the_prompt_states_the_allowed_paths(captured):
    """Resolved from the contract, so a worker can check a path against them
    rather than parsing yaml itself."""
    prompt = run(captured)

    assert "You may only write to these paths" in prompt
    assert "notes" in prompt


def test_the_prompt_carries_the_contract_verbatim(captured):
    """The resolved fields are what an instruction is checked against; the
    yaml is what the contract says, including acceptance criteria this cannot
    know the shape of."""
    prompt = run(captured)

    assert "the guard is load-bearing" in prompt
    assert "schema_version: 7" in prompt


def test_the_prompt_says_the_contract_may_not_be_changed(captured):
    prompt = run(captured)

    assert "None of the above may be changed" in prompt
    assert "stop and say so" in prompt.lower()


# --- The operator's answer is there too, and subordinate ---------------------


def test_the_prompt_carries_the_operator_response(captured):
    prompt = run(captured, operator_context=ANSWER)

    assert ANSWER["response"] in prompt


def test_the_prompt_carries_both_the_boundary_and_the_answer(captured):
    """The pairing is the point. Either alone is what the defect was."""
    prompt = run(captured, operator_context=ANSWER)

    assert ANSWER["response"] in prompt
    assert "branch_only" in prompt
    assert "b4f8d21036520856b39f3c919905213da9754622" in prompt
    assert "CANNOT change the contract" in prompt


def test_the_contract_comes_before_the_answer(captured):
    """Everything after the contract is bound by it, including the answer."""
    prompt = run(captured, operator_context=ANSWER)

    assert prompt.index("THE CONTRACT FOR THIS TASK") < prompt.index(
        "THIS TASK WAS ESCALATED"
    )


def test_the_answer_comes_before_the_task_text(captured):
    prompt = run(captured, operator_context=ANSWER)

    assert prompt.index("THIS TASK WAS ESCALATED") < prompt.index(
        "make the check load-bearing"
    )


def test_the_answer_is_not_said_to_outrank_the_task(captured):
    """It is guidance within the contract, and the prompt must not imply
    otherwise anywhere."""
    prompt = run(captured, operator_context=ANSWER).lower()

    assert "follow the operator" not in prompt


def test_a_task_with_no_escalation_still_gets_its_contract(captured):
    """The contract is not conditional on an operator having spoken."""
    prompt = run(captured)

    assert "THE CONTRACT FOR THIS TASK" in prompt
    assert "THIS TASK WAS ESCALATED" not in prompt


def test_a_missing_task_record_does_not_break_the_run(captured):
    """An activation without a record still has to reach the CLI, rather than
    failing on the section that describes it."""
    prompt = run(captured, task_record=None)

    assert prompt
    assert "THE CONTRACT FOR THIS TASK" not in prompt
