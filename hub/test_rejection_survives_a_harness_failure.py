"""A reviewer's verdict outlives the author's next stumble.

`author_defect` is written by two unrelated things. A reviewer returning
`changes_requested` writes one carrying `rationale` -- the words the next
attempt exists to address. The authoring harness writes one too, when it
refuses before the model is called: a branch that already exists, a worktree
that is not clean. That payload carries `reason`, and it knows nothing about
the change.

`get_task` used to answer with the newest of the two. So a retry that died on
a branch collision replaced the reviewer's verdict with a sentence about git,
`_rejection_section` found no `rationale` and rendered nothing, and the next
attempt was told only the original objective -- the same inputs that produced
the candidate the reviewer had just rejected.

It cost an attempt out of three, and it cost it silently: nothing in the task
record says the feedback used to be there.

These are written against the real ledger rather than a stubbed one, because
the defect was in what a query returned, and a test that stubbed the query
would have asserted the bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from controller import engine, states  # noqa: E402
from controller.db import open_controller_db  # noqa: E402

REVIEWER_WORDS = (
    "`draft[\"draft_hash\"]` assumes a sqlite3.Row factory and will fail with "
    "a TypeError on a standard connection."
)


@pytest.fixture
def conn(tmp_path):
    return open_controller_db(str(tmp_path / "controller.db"))


def a_task_in_review(conn, task_id="T-1"):
    """A task carried to REVIEWING the way the state machine actually gets there."""
    engine.create_task(
        conn, task_id=task_id, title="t", objective="o",
        contract_yaml="schema_version: 7\nallowed_paths:\n  - a.py\n",
        base_sha="a" * 40, created_by="admin",
    )

    for kind, authority in (
        ("contract_validated", states.CONTROLLER),
        ("queued", states.CONTROLLER),
        ("author_activation_issued", states.CONTROLLER),
        ("activation_claimed", states.AUTHOR),
        ("candidate_submitted", states.AUTHOR),
        ("review_activation_issued", states.CONTROLLER),
        ("activation_claimed", states.VERIFIER),
    ):
        engine.apply_transition(
            conn, task_id=task_id, kind=kind, actor="test", authority=authority,
        )

    return task_id


def reviewer_rejects(conn, task_id, rationale=REVIEWER_WORDS):
    engine.apply_transition(
        conn, task_id=task_id, kind="author_defect", actor="gemini",
        authority=states.CONTROLLER,
        payload={"judgment": "changes_requested", "judgment_by": "gemini",
                 "rationale": rationale},
    )


def harness_refuses(conn, task_id, reason="branch 'task/T-1' already exists"):
    """The author's own failure: it never reached the model, so it has no verdict."""
    engine.apply_transition(
        conn, task_id=task_id, kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )
    engine.apply_transition(
        conn, task_id=task_id, kind="author_activation_issued", actor="controller",
        authority=states.CONTROLLER,
    )
    engine.apply_transition(
        conn, task_id=task_id, kind="activation_claimed", actor="chatgpt",
        authority=states.AUTHOR,
    )
    engine.apply_transition(
        conn, task_id=task_id, kind="author_defect", actor="chatgpt",
        authority=states.CONTROLLER,
        payload={"outcome": "failed", "outcome_by": "chatgpt", "reason": reason},
    )


def test_the_reviewer_is_heard_while_it_is_the_only_thing_said(conn):
    task_id = a_task_in_review(conn)
    reviewer_rejects(conn, task_id)

    assert engine.get_task(conn, task_id)["last_rejection"]["rationale"] == REVIEWER_WORDS


def test_a_harness_failure_does_not_erase_the_verdict(conn):
    """The defect, stated as the thing that actually happened."""
    task_id = a_task_in_review(conn)
    reviewer_rejects(conn, task_id)
    harness_refuses(conn, task_id)

    standing = engine.get_task(conn, task_id)["last_rejection"]

    assert standing["rationale"] == REVIEWER_WORDS
    assert standing["judgment_by"] == "gemini"


def test_the_words_reach_the_prompt_the_author_is_given(conn):
    """Transport is not the point; the author reading them is.

    Asserted against the rendered prompt rather than the task record, because
    the record being right and the section still rendering empty is exactly
    the failure this is about.
    """
    import authored_change

    task_id = a_task_in_review(conn)
    reviewer_rejects(conn, task_id)
    harness_refuses(conn, task_id)

    prompt = authored_change.render_author_prompt(engine.get_task(conn, task_id))

    assert REVIEWER_WORDS in prompt
    assert "A PREVIOUS ATTEMPT AT THIS TASK WAS REJECTED IN REVIEW." in prompt
    assert "branch 'task/T-1' already exists" not in prompt


def test_a_newer_verdict_replaces_an_older_one(conn):
    """Preserving the reviewer must not mean freezing the first reviewer.

    Otherwise the fix trades one stale prompt for another: an author would be
    corrected against a review two attempts out of date.
    """
    task_id = a_task_in_review(conn)
    reviewer_rejects(conn, task_id, "the first thing that was wrong")

    engine.apply_transition(
        conn, task_id=task_id, kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )
    for kind, authority in (
        ("author_activation_issued", states.CONTROLLER),
        ("activation_claimed", states.AUTHOR),
        ("candidate_submitted", states.AUTHOR),
        ("review_activation_issued", states.CONTROLLER),
        ("activation_claimed", states.VERIFIER),
    ):
        engine.apply_transition(
            conn, task_id=task_id, kind=kind, actor="test", authority=authority,
        )

    reviewer_rejects(conn, task_id, "the second thing that was wrong")

    assert engine.get_task(conn, task_id)["last_rejection"]["rationale"] == (
        "the second thing that was wrong"
    )


def test_a_task_only_ever_refused_by_the_harness_claims_no_verdict(conn):
    """No rationale anywhere is an empty rejection, not the harness's sentence.

    An author handed `reason` where it expects `rationale` would be told a
    review had rejected it and shown a message about git.

    Driven from AUTHORING rather than through a review, because a first
    attempt that dies in the harness is exactly a task no reviewer has seen.
    """
    engine.create_task(
        conn, task_id="T-2", title="t", objective="o",
        contract_yaml="schema_version: 7\nallowed_paths:\n  - a.py\n",
        base_sha="a" * 40, created_by="admin",
    )

    for kind, authority in (
        ("contract_validated", states.CONTROLLER),
        ("queued", states.CONTROLLER),
        ("author_activation_issued", states.CONTROLLER),
        ("activation_claimed", states.AUTHOR),
    ):
        engine.apply_transition(
            conn, task_id="T-2", kind=kind, actor="test", authority=authority,
        )

    engine.apply_transition(
        conn, task_id="T-2", kind="author_defect", actor="chatgpt",
        authority=states.CONTROLLER,
        payload={"outcome": "failed", "outcome_by": "chatgpt",
                 "reason": "the worktree was not clean"},
    )

    assert engine.get_task(conn, "T-2")["last_rejection"] == {}


def test_an_unreadable_payload_is_skipped_rather_than_believed(conn):
    """A row that will not parse must not shadow a readable verdict behind it."""
    task_id = a_task_in_review(conn)
    reviewer_rejects(conn, task_id)
    harness_refuses(conn, task_id)

    conn.execute(
        "UPDATE events SET payload_json = ? WHERE seq = "
        "(SELECT MAX(seq) FROM events WHERE task_id = ?)",
        ("{not json at all", task_id),
    )
    conn.commit()

    assert engine.get_task(conn, task_id)["last_rejection"]["rationale"] == REVIEWER_WORDS
