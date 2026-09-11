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
    queue = Queue()
    activation = {
        "activation_id": "A-1",
        "task_id": "CND-7",
        "task": "tighten the guard\n\nmake the check load-bearing",
        "task_record": task_record,
        "operator_context": operator_context,
        # Controller-sourced: the path bound by a contract, and the one
        # that must refuse to run without one.
        "source": "controller",
        "issued_by": "controller",
    }
    claude_worker._execute_author(None, "claude", activation, queue)
    captured["queue"] = queue

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


# --- Without a usable contract, nothing runs ---------------------------------
#
# This worker holds Bash authority. The only thing between it and the rest of
# the filesystem is a contract it has been shown, and the operator section
# tells it the base commit and allowed paths cannot be changed -- so a run
# that reaches the CLI without a contract is an unbounded agent that has been
# told it is bounded.
#
# An earlier revision let that run proceed and rendered `(none recorded)`
# where the paths belonged, on the reasoning that degrading beats refusing.
# That is backwards here: the placeholder claims a boundary exists.


BROKEN = [
    ("no task record at all", None, "no task record"),
    ("no contract yaml", {**TASK_RECORD, "contract_yaml": ""}, "contract_yaml"),
    ("no base commit", {**TASK_RECORD, "base_sha": ""}, "base_sha"),
    ("no proof mode", {**TASK_RECORD, "proof_mode": None}, "proof_mode"),
    ("no contract hash", {**TASK_RECORD, "contract_hash": ""}, "contract_hash"),
    ("no task id", {**TASK_RECORD, "task_id": ""}, "task_id"),
    ("no version", {**TASK_RECORD, "current_version": None}, "current_version"),
    # `parse_scope` refuses a contract that declares no paths, with a better
    # message than this module could write. The empty-scope check in
    # `require_contract` stays as defence in depth behind it.
    ("a contract declaring no paths",
     {**TASK_RECORD, "contract_yaml": "schema_version: 7\n"},
     "allowed_paths"),
    ("a contract that will not parse",
     {**TASK_RECORD, "contract_yaml": "allowed_paths: [unclosed\n"},
     "could not be parsed"),
]


@pytest.mark.parametrize("label,record,_expected",
                         BROKEN, ids=[b[0] for b in BROKEN])
def test_a_contract_bound_run_without_a_usable_contract_calls_nothing(
    captured, label, record, _expected
):
    """No CLI call, no model call, nothing spawned."""
    run(captured, task_record=record)

    assert "prompt" not in captured, f"{label}: the CLI was invoked anyway"
    assert "binary" not in captured


@pytest.mark.parametrize("label,record,expected",
                         BROKEN, ids=[b[0] for b in BROKEN])
def test_the_refusal_names_the_specific_defect(captured, label, record, expected):
    """An operator has to be able to fix it without guessing which field."""
    run(captured, task_record=record)

    reports = captured["queue"].reports

    assert reports, f"{label}: nothing was reported"
    assert reports[-1]["outcome"] == "blocked"
    assert expected in reports[-1]["payload"]["reason"], reports[-1]


@pytest.mark.parametrize("label,record,_expected",
                         BROKEN, ids=[b[0] for b in BROKEN])
def test_the_activation_is_reported_rather_than_dropped(
    captured, label, record, _expected
):
    """Claimed and then refused. A silent drop leaves the task in AUTHORING
    until its lease lapses, which looks identical to a crashed worker."""
    run(captured, task_record=record)

    assert len(captured["queue"].reports) == 1


def test_no_placeholder_is_ever_rendered_for_the_paths():
    """The specific shape of the old defect: a prompt that says a boundary was
    recorded when none was."""
    import authored_change

    assert "(none recorded)" not in "\n".join(
        authored_change.contract_section(TASK_RECORD, ["notes"])
    )

    with pytest.raises(authored_change.ContractDefect):
        authored_change.require_contract(
            {**TASK_RECORD, "contract_yaml": "schema_version: 7\n"}
        )


def test_a_locally_issued_activation_still_runs(captured):
    """The operator's own control-directory path is not contract-bound and
    never claimed to be. Refusing it would remove something Phase 0 kept."""
    queue = Queue()
    claude_worker._execute_author(None, "claude", {
        "activation_id": "L-1",
        "task": "run the preflight and report",
        "issued_by": "admin",
        "source": "directory",
    }, queue)

    assert captured["prompt"]
    assert "THE CONTRACT FOR THIS TASK" not in captured["prompt"]


def test_an_empty_resolved_scope_is_refused_even_if_parsing_succeeds(monkeypatch):
    """Defence in depth, made demonstrable.

    `parse_scope` refuses every empty-scope shape today -- absent, `[]`, null,
    and blank entries -- so this branch is unreachable through a contract. It
    exists so that a future change there which returned an empty scope cannot
    quietly produce a prompt with no boundary in it, and it is tested by
    forcing that return rather than left as a guard nobody can show working.
    """
    import authored_change

    class Empty:
        paths = ()

    monkeypatch.setattr(authored_change, "parse_scope", lambda *a, **k: Empty())

    with pytest.raises(authored_change.ContractDefect) as caught:
        authored_change.require_contract(TASK_RECORD)

    assert "no writable paths" in str(caught.value)
