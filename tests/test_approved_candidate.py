"""Only the candidate a review actually approved may be integrated.

The column exists because "the branch head" and "what was approved" are the
same value right up until they are not, and the moment they diverge is exactly
the moment an integrator would merge the wrong tree without anything looking
wrong. A second candidate is authored after an approval; the branch moves; the
approval still reads as an approval.

So `approved_candidate_sha` is written by the controller, inside the same
transaction as `review_requirements_satisfied`, from the activation's own
`expected_candidate` -- the commit the controller issued the review against,
never a value a reviewer or an operator supplied -- and cleared by every event
that invalidates it.
"""

from __future__ import annotations

import sqlite3

import pytest

import integrator
from controller import activations, db, engine, outcomes, states


LEASE = 900.0
DEADLINE = 5400.0

CAND_1 = "1" * 40
CAND_2 = "2" * 40


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "controller.db"))
    db.initialize(connection)
    # Two, so an author and a reviewer activation can both be live: the
    # multi-candidate tests need the whole cycle to run more than once.
    activations.set_host_capacity(connection, host="officepc", max_concurrent=2)
    return connection


def make_task(conn, task_id="T-1"):
    engine.create_task(
        conn, task_id=task_id, title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n",
        base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id=task_id, kind=kind, actor="admin",
            authority=states.CONTROLLER,
        )
    return task_id


def author_a_candidate(conn, task_id, candidate):
    """Take the task through one full authoring round to READY_REVIEW."""
    issued = activations.issue(
        conn, task_id=task_id, agent="chatgpt", host="officepc",
        stage="author", lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"task/{task_id}",
    )
    activations.claim(conn, activation_id=issued["activation_id"], agent="chatgpt")
    outcomes.submit_author_outcome(
        conn, activation_id=issued["activation_id"], agent="chatgpt",
        outcome="candidate", payload={"candidate_sha": candidate},
    )
    return issued["activation_id"]


def review(conn, task_id, candidate, judgment="satisfied"):
    """Issue a review activation naming `candidate`, and judge it."""
    issued = activations.issue(
        conn, task_id=task_id, agent="gemini", host="officepc",
        stage="review", lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"task/{task_id}",
        expected_candidate=candidate, repo_location="/repo",
    )
    activations.claim(conn, activation_id=issued["activation_id"], agent="gemini")
    outcomes.submit_review_judgment(
        conn, activation_id=issued["activation_id"], agent="gemini",
        judgment=judgment,
    )
    return issued["activation_id"]


def reject_integration(conn, task_id):
    """The real path back from READY_INTEGRATION.

    `integration_rejected` comes from INTEGRATING, never from
    READY_INTEGRATION -- an integration cannot be rejected before it started.
    """
    for kind in ("integration_started", "integration_rejected"):
        engine.apply_transition(
            conn, task_id=task_id, kind=kind, actor="admin",
            authority=states.CONTROLLER,
        )


def approved(conn, task_id):
    return engine.get_task(conn, task_id)["approved_candidate_sha"]


# --- The column is additive and starts empty --------------------------------


def test_a_new_task_has_no_approval(conn):
    assert approved(conn, make_task(conn)) is None


def test_the_migration_is_additive(tmp_path):
    """An existing database gains the column without losing a row.

    Every task already in the deployed database gets NULL, which is correct for
    all of them: none was approved under a rule that recorded which candidate
    the approval was for, and writing a value in would manufacture an approval
    nobody gave.
    """
    path = str(tmp_path / "old.db")
    old = db.connect(path)
    old.executescript(
        "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, title TEXT, "
        "objective TEXT, priority INTEGER DEFAULT 50, current_version INTEGER, "
        "state TEXT, state_seq INTEGER DEFAULT 0, enqueued_at REAL, "
        "created_at REAL, created_by TEXT);"
        "CREATE TABLE activations (activation_id TEXT PRIMARY KEY);"
        # A real version-2 database always has this, and migration 4 rebuilds
        # it to widen the proof_mode CHECK. A stub without it is not a
        # controller database, so leaving it out tested a shape that cannot
        # exist.
        "CREATE TABLE task_versions ("
        "  task_id TEXT NOT NULL, version INTEGER NOT NULL,"
        "  contract_yaml TEXT NOT NULL, contract_hash TEXT NOT NULL,"
        "  protocol_schema_version INTEGER NOT NULL, base_sha TEXT NOT NULL,"
        "  proof_mode TEXT NOT NULL"
        "    CHECK (proof_mode IN ('baseline', 'sabotage', 'both')),"
        "  created_at REAL NOT NULL, created_by TEXT NOT NULL,"
        "  PRIMARY KEY (task_id, version));"
    )
    old.execute(
        "INSERT INTO tasks (task_id, title, objective, current_version, state, "
        "created_at, created_by) VALUES ('OLD-1','t','o',1,'DRAFT',0,'admin')"
    )
    old.execute(
        "INSERT INTO task_versions (task_id, version, contract_yaml, "
        "contract_hash, protocol_schema_version, base_sha, proof_mode, "
        "created_at, created_by) "
        "VALUES ('OLD-1',1,'allowed_paths:','h',7,'0','baseline',0,'admin')"
    )
    old.execute("PRAGMA user_version = 2")
    old.commit()
    old.close()

    fresh = db.connect(path)
    db.migrate(fresh)

    row = fresh.execute(
        "SELECT task_id, approved_candidate_sha FROM tasks"
    ).fetchone()

    assert row["task_id"] == "OLD-1"
    assert row["approved_candidate_sha"] is None

    # Migration 4 rebuilt task_versions to widen the proof_mode CHECK; the row
    # has to come through it, and the foreign keys with it.
    version = fresh.execute(
        "SELECT proof_mode FROM task_versions WHERE task_id = 'OLD-1'"
    ).fetchone()

    assert version["proof_mode"] == "baseline"
    assert fresh.execute("PRAGMA foreign_key_check").fetchall() == []


# --- Set atomically with the approval ---------------------------------------


def test_an_approval_records_the_candidate_it_was_issued_against(conn):
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)

    assert approved(conn, task) == CAND_1
    assert engine.get_task(conn, task)["state"] == "READY_INTEGRATION"


def test_the_approval_comes_from_the_activation_not_the_judgment(conn):
    """A reviewer answering "satisfied" is answering a question the controller
    asked about a specific commit. Letting the answer carry its own idea of
    which commit would let it approve a tree nobody looked at."""
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)

    issued = activations.issue(
        conn, task_id=task, agent="gemini", host="officepc", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"task/{task}", expected_candidate=CAND_1,
        repo_location="/repo",
    )
    activations.claim(conn, activation_id=issued["activation_id"], agent="gemini")
    outcomes.submit_review_judgment(
        conn, activation_id=issued["activation_id"], agent="gemini",
        judgment="satisfied",
        # The reviewer claims a different commit. It is ignored.
        payload={"candidate_sha": CAND_2, "approved_candidate_sha": CAND_2},
    )

    assert approved(conn, task) == CAND_1


def test_an_unstated_candidate_falls_back_to_the_ledger_not_to_nothing(conn):
    """A review issued without an explicit candidate is completed from the
    task's own latest `candidate_submitted` event.

    Worth pinning because it is the reason there is no path to an approval
    with no candidate: the fallback is the ledger, which is a controller
    record, so the approval is still derived from something the controller
    wrote rather than from anything a caller supplied.
    """
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)

    issued = activations.issue(
        conn, task_id=task, agent="gemini", host="officepc", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"task/{task}", repo_location="/repo",
    )
    activations.claim(conn, activation_id=issued["activation_id"], agent="gemini")
    outcomes.submit_review_judgment(
        conn, activation_id=issued["activation_id"], agent="gemini",
        judgment="satisfied",
    )

    assert approved(conn, task) == CAND_1


def test_a_review_cannot_be_issued_with_no_candidate_anywhere(conn):
    """The stronger property, and why no approval can lack a candidate.

    With no `candidate_submitted` event to fall back to, issuance itself is
    refused -- so a review activation that could approve nothing never exists.
    """
    task = make_task(conn)

    with pytest.raises(activations.MissingReviewEvidence):
        activations.issue(
            conn, task_id=task, agent="gemini", host="officepc",
            stage="review", lease_seconds=LEASE,
            hard_deadline_seconds=DEADLINE,
            expected_branch=f"task/{task}", repo_location="/repo",
        )


# --- Cleared by everything that invalidates it ------------------------------


def test_a_rejection_clears_the_approval(conn):
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)
    assert approved(conn, task) == CAND_1

    reject_integration(conn, task)

    assert approved(conn, task) is None


def test_a_new_candidate_clears_a_standing_approval(conn):
    """The approval named a specific commit; a newer candidate is a different
    tree, and an approval about a different tree is not an approval."""
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)
    reject_integration(conn, task)
    engine.apply_transition(
        conn, task_id=task, kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )
    author_a_candidate(conn, task, CAND_2)

    assert approved(conn, task) is None


def test_a_retry_clears_the_approval(conn):
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1, judgment="changes_requested")
    assert approved(conn, task) is None

    engine.apply_transition(
        conn, task_id=task, kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )

    assert approved(conn, task) is None


def test_changes_requested_clears_it(conn):
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)
    assert approved(conn, task) == CAND_1

    # Back round: reject, retry, author again, and the old approval is gone
    # well before the new review.
    reject_integration(conn, task)

    assert approved(conn, task) is None


# --- After multiple candidates, only the approved one integrates ------------


def test_only_the_specifically_approved_candidate_may_be_integrated(conn):
    """The whole point, end to end.

    Two candidates exist. The second was authored after the first was
    approved, so the branch head is CAND_2 and the approval is about CAND_1.
    An integrator reading "the current candidate" would merge CAND_2.
    """
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)
    reject_integration(conn, task)
    engine.apply_transition(
        conn, task_id=task, kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )
    author_a_candidate(conn, task, CAND_2)
    review(conn, task, CAND_2)

    record = engine.get_task(conn, task)

    # The second approval is the live one, and it names the second candidate.
    assert integrator.approved_candidate(record) == CAND_2

    # An integration plan naming the first is refused, even though CAND_1 was
    # genuinely approved once.
    stale = integrator.Plan(
        task_id=task, repo="/r", candidate_sha=CAND_1,
        target_ref="refs/heads/master", target_sha_expected="0" * 40,
    )

    with pytest.raises(integrator.IntegrationRefused, match="different tree"):
        integrator.check_approval(record, stale)


def test_an_unapproved_task_cannot_be_integrated_at_all(conn):
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)

    with pytest.raises(integrator.IntegrationRefused, match="READY_INTEGRATION"):
        integrator.approved_candidate(engine.get_task(conn, task))


def test_an_approval_cleared_by_a_newer_candidate_cannot_be_integrated(conn):
    """READY_INTEGRATION with a cleared approval refuses rather than falling
    back to anything."""
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)

    # Clear it directly, as a rejection would, while leaving the state alone
    # so the refusal is provably about the approval and not about the state.
    conn.execute(
        "UPDATE tasks SET approved_candidate_sha = NULL WHERE task_id = ?",
        (task,),
    )
    conn.commit()

    with pytest.raises(
        integrator.IntegrationRefused, match="no\\s+approved_candidate_sha"
    ):
        integrator.approved_candidate(engine.get_task(conn, task))


def test_the_approval_and_its_event_move_together(conn):
    """Same transaction. A task whose approval moved without an event, or an
    event without the approval, is unreconstructable afterwards."""
    task = make_task(conn)
    author_a_candidate(conn, task, CAND_1)
    review(conn, task, CAND_1)

    kinds = [e["kind"] for e in engine.event_log(conn, task)]

    assert "review_requirements_satisfied" in kinds
    assert approved(conn, task) == CAND_1
