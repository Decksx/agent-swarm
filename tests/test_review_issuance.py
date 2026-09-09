"""A review activation must be actionable before anybody claims it.

The alternative was demonstrated live on 2026-09-09: a review activation was
issued by hand with no branch, Gemini claimed it, found nothing to review, and
correctly reported `blocked`. That worked -- but it cost a claim, a lease, a
state transition into REVIEW_BLOCKED, an operator repair, and a reissue, all to
discover something the controller could have known at issue time.

On a paid model it would also have cost a call, because a reviewer that gets as
far as a malformed packet is one branch away from a reviewer that gets as far
as prompting.
"""

from __future__ import annotations

import pytest

from controller import activations, engine, states
from controller.db import open_controller_db

T0 = 1_000_000.0
LEASE = 300.0
DEADLINE = 5400.0

BASE = "1" * 40
CANDIDATE = "2" * 40


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 2)
    yield connection
    connection.close()


@pytest.fixture
def awaiting_review(conn):
    """A task in READY_REVIEW whose author reported a candidate SHA."""
    engine.create_task(
        conn, task_id="T-1", title="t", objective="o",
        contract_yaml="schema_version: 7", base_sha=BASE, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-1", kind=kind, actor="c", authority=states.CONTROLLER
        )

    author = activations.issue(
        conn, task_id="T-1", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="claudecode", now=T0
    )
    activations.submit_author_outcome(
        conn, activation_id=author["activation_id"], agent="claudecode",
        outcome="candidate",
        payload={"candidate_sha": CANDIDATE, "branch": "task/T-1"},
        now=T0 + 1,
    )

    assert engine.get_task(conn, "T-1")["state"] == "READY_REVIEW"
    return "T-1"


def issue_review(conn, **kw):
    params = dict(
        task_id="T-1", agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0 + 2,
        expected_branch="task/T-1", repo_location="/srv/checkouts/T-1",
    )
    params.update(kw)
    return activations.issue(conn, **params)


# --- What must be present ---------------------------------------------------


def test_a_review_without_a_branch_is_refused(conn, awaiting_review):
    with pytest.raises(activations.MissingReviewEvidence, match="expected_branch"):
        issue_review(conn, expected_branch=None)


def test_a_review_without_a_repository_is_refused(conn, awaiting_review):
    """Not verified, but required.

    The controller cannot see a path on another host and does not pretend to.
    Requiring one makes "which checkout was this reviewed in" answerable from
    the ledger rather than from somebody's memory.
    """
    with pytest.raises(activations.MissingReviewEvidence, match="repo_location"):
        issue_review(conn, repo_location="   ")


def test_the_task_does_not_move_when_issuance_is_refused(conn, awaiting_review):
    """A refused issue must leave the task claimable by a correct one."""
    with pytest.raises(activations.MissingReviewEvidence):
        issue_review(conn, expected_branch=None)

    assert engine.get_task(conn, "T-1")["state"] == "READY_REVIEW"

    # And a correct issue still works afterwards.
    assert issue_review(conn)["role"] == "verifier"


# --- What is derived rather than retyped ------------------------------------


def test_the_candidate_comes_from_the_authors_own_report(conn, awaiting_review):
    """Not retyped by the operator, which is the step that goes wrong.

    The author already recorded the SHA as a field when it submitted. Asking a
    human to copy it into the issue command adds a transcription error to a
    value that is already known correctly.
    """
    issue_review(conn)

    row = conn.execute(
        "SELECT expected_candidate, expected_parent FROM activations "
        "WHERE stage = 'review'"
    ).fetchone()

    assert row["expected_candidate"] == CANDIDATE
    assert row["expected_parent"] == BASE


def test_an_explicit_candidate_overrides_the_derived_one(conn, awaiting_review):
    issue_review(conn, expected_candidate="3" * 40)

    row = conn.execute(
        "SELECT expected_candidate FROM activations WHERE stage = 'review'"
    ).fetchone()

    assert row["expected_candidate"] == "3" * 40


def test_a_task_whose_author_reported_no_sha_cannot_be_reviewed(conn):
    """Refused rather than reviewed against a guess."""
    engine.create_task(
        conn, task_id="T-2", title="t", objective="o",
        contract_yaml="schema_version: 7", base_sha=BASE, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-2", kind=kind, actor="c", authority=states.CONTROLLER
        )
    author = activations.issue(
        conn, task_id="T-2", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )
    activations.claim(
        conn, activation_id=author["activation_id"], agent="claudecode", now=T0
    )
    # No candidate_sha in the payload -- an author that changed no code.
    activations.submit_author_outcome(
        conn, activation_id=author["activation_id"], agent="claudecode",
        outcome="candidate", now=T0 + 1,
    )

    with pytest.raises(
        activations.MissingReviewEvidence, match="expected_candidate"
    ):
        issue_review(conn, task_id="T-2")


# --- What must be well formed -----------------------------------------------


@pytest.mark.parametrize("bad", ["80cf8c8", "not-a-sha", "Z" * 40, "2" * 39])
def test_a_short_or_malformed_sha_is_refused(conn, awaiting_review, bad):
    """An abbreviated SHA is ambiguous by construction.

    It resolves today and may resolve to something else after the repository
    grows, which is a review that silently changes meaning.
    """
    with pytest.raises(activations.MissingReviewEvidence, match="40-character"):
        issue_review(conn, expected_candidate=bad)


def test_an_empty_range_is_refused(conn, awaiting_review):
    with pytest.raises(activations.MissingReviewEvidence, match="same commit"):
        issue_review(conn, expected_candidate=BASE)


# --- The author stage is unaffected -----------------------------------------


def test_an_author_activation_needs_none_of_this(conn):
    """The evidence requirement is the reviewer's, not everybody's.

    An author is being told what to do, not shown what somebody else did, so
    demanding a candidate SHA before any work exists would be incoherent.
    """
    engine.create_task(
        conn, task_id="T-3", title="t", objective="o",
        contract_yaml="schema_version: 7", base_sha=BASE, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-3", kind=kind, actor="c", authority=states.CONTROLLER
        )

    activation = activations.issue(
        conn, task_id="T-3", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
    )

    assert activation["role"] == "author"


def test_the_claim_hands_the_reviewer_everything_it_needs(conn, awaiting_review):
    """End to end: what issuance validated is what the claimant receives."""
    review = issue_review(conn)
    claimed = activations.claim(
        conn, activation_id=review["activation_id"], agent="gemini", now=T0 + 3
    )

    assert claimed["expected_branch"] == "task/T-1"
    assert claimed["expected_parent"] == BASE
    assert claimed["expected_candidate"] == CANDIDATE
    assert claimed["repo_location"] == "/srv/checkouts/T-1"
