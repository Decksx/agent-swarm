"""The author is shown the contract it is judged against.

`render_author_prompt` printed a heading reading OBJECTIVE AND ACCEPTANCE
CRITERIA and then only the objective. `contract_yaml` was never read, so every
term written in the contract -- what may not be stubbed, what the tests may
not build for themselves, what has to happen inside one transaction -- was
invisible to the author, while the reviewer judged against all of it.

That is not a cosmetic gap. It produces a run that looks like a model
ignoring its instructions: three candidates were rejected for omitting things
the author was never told to do, and each rejection read as the author's
fault. The heading made it worse than silence, because a section that names
acceptance criteria and contains none reads as a contract with nothing
further to say.

So these assert on the rendered string a worker actually sends. A test that
checked `contract_section` in isolation would have passed throughout the
period the bug existed -- the section was correct; nothing called it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import authored_change  # noqa: E402

CONTRACT = """schema_version: 7
task_id: T-1
title: Draft storage

allowed_paths:
  - controller/drafts.py

scope_notes:
  - controller/db.py is NOT writable; expose table creation as a callable.

acceptance:
  - No placeholder. Nothing may be a comment standing in for logic.
  - The read and the write that follows it happen in one transaction.
"""


def a_task(**overrides):
    task = {
        "task_id": "T-1",
        "title": "Draft storage",
        "objective": "Implement controller/drafts.py.",
        "current_version": 1,
        "base_sha": "a" * 40,
        "proof_mode": "branch_only",
        "contract_hash": "b" * 64,
        "contract_yaml": CONTRACT,
        "allowed_paths": ["controller/drafts.py"],
    }
    task.update(overrides)
    return task


@pytest.fixture
def scope():
    return authored_change.require_contract(a_task())


def test_the_acceptance_criteria_are_in_the_prompt(scope):
    """The defect, stated as the thing that was missing."""
    prompt = authored_change.render_author_prompt(a_task(), scope=scope)

    assert "No placeholder. Nothing may be a comment standing in for logic." in prompt
    assert "The read and the write that follows it happen in one transaction." in prompt


def test_the_scope_notes_are_in_the_prompt(scope):
    prompt = authored_change.render_author_prompt(a_task(), scope=scope)

    assert "controller/db.py is NOT writable" in prompt


def test_the_heading_is_not_a_promise_the_prompt_breaks(scope):
    """Whatever the heading claims to introduce has to be under it.

    Asserted by position rather than presence: the criteria appearing further
    down under some other heading would satisfy a containment check while
    leaving the heading exactly as misleading as it was.
    """
    prompt = authored_change.render_author_prompt(a_task(), scope=scope)

    heading = prompt.index("OBJECTIVE AND ACCEPTANCE CRITERIA")
    criteria = prompt.index("No placeholder.")
    answer_rules = prompt.index("Answer with one or more blocks")

    assert heading < criteria < answer_rules


def test_the_binding_terms_travel_with_the_contract(scope):
    """Base, proof mode and hash, so the author can tell what it is bound to."""
    prompt = authored_change.render_author_prompt(a_task(), scope=scope)

    assert "a" * 40 in prompt
    assert "branch_only" in prompt
    assert "b" * 64 in prompt


BARE_LIST = "Anything else is refused and your whole answer is discarded"


def test_write_authority_is_granted_by_one_heading_only(scope):
    """The old bare list must not sit alongside the contract's own statement.

    Not a count of the path itself -- the objective names files in prose and
    the verbatim contract restates its own list, and both of those are the
    contract being quoted rather than authority being granted twice. What
    must not happen is two *grants*, under two headings, free to drift apart
    with no way for a reader to tell which one binds.
    """
    prompt = authored_change.render_author_prompt(a_task(), scope=scope)

    assert "THE CONTRACT FOR THIS TASK" in prompt
    assert BARE_LIST not in prompt


def test_an_unrestricted_author_is_told_so(scope):
    """`Scope(unrestricted=True, paths=())` has no path list to print.

    The old bare list rendered nothing at all for this case, so the author
    with the widest authority in the system was told it had none.
    """
    task = a_task(contract_yaml="schema_version: 7\nallowed_paths: UNRESTRICTED\n",
                  allowed_paths=[])
    unrestricted = authored_change.require_contract(task)

    assert unrestricted.unrestricted

    prompt = authored_change.render_author_prompt(task, scope=unrestricted)

    assert "ENTIRE repository" in prompt


def test_without_a_scope_the_prompt_is_what_it_always_was(scope):
    """Callers that have not resolved a contract keep the bare path list.

    They must not silently gain a contract section built from a task dict
    nobody validated.
    """
    prompt = authored_change.render_author_prompt(a_task())

    assert "THE CONTRACT FOR THIS TASK" not in prompt
    assert "No placeholder." not in prompt
    assert BARE_LIST in prompt
    assert "controller/drafts.py" in prompt


def test_the_worker_passes_its_resolved_scope(monkeypatch):
    """Transport, at the call site that had the defect.

    `chatgpt_worker` resolves a scope and then rendered without it. Asserted
    by capturing what the worker hands the renderer, because the renderer
    being able to show a contract and the worker not passing one is exactly
    the state this was in.
    """
    import inspect

    import chatgpt_worker

    source = inspect.getsource(chatgpt_worker)
    call = source[source.index("render_author_prompt"):]
    call = call[:call.index(")\n")]

    assert "scope=scope" in call
