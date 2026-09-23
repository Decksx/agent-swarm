"""The author budget counts attempts, and refuses where it is spent (#21).

Two halves of one contract disagreed.

**Charged.** Every author activation was issued `chargeable_attempt = 1`,
including ones that ended in `environment_defect` without the model ever
producing a usable reply. An infrastructure failure spent budget the author
never used.

**Enforced on one route only.** The ceiling was checked in
`engine.authorize_retry`, which a rejected task passes through on its way back
to READY_AUTHOR. A blocked task takes a different road -- `environment_repaired`
-- and `issue` never consulted the budget, so that road had no gate at all.

T-INFRA-12 went down both. Attempts 1 and 2 were reviewed and rejected.
Attempt 3 hit an OpenAI timeout, was charged, and left the task AUTHOR_BLOCKED
with 3 of 3 spent. Recovery was a repair plus a replacement activation: a
fourth chargeable attempt against a budget of three, allowed because nothing
on that route was counting.

These pin both halves, and the interaction between them -- with the defect
un-charged, the replacement activation T-INFRA-12 needed is legitimately the
third attempt rather than a fourth one nobody authorised.
"""

from __future__ import annotations

import pytest

from controller import activations, engine, outcomes, states
from controller.db import open_controller_db

T0 = 1_000_000.0
LEASE = 300.0
DEADLINE = 5400.0


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 4)
    yield connection
    connection.close()


@pytest.fixture
def ready_task(conn):
    engine.create_task(
        conn, task_id="T-1", title="pilot", objective="o",
        contract_yaml="schema_version: 7\n", base_sha="0" * 40, created_by="admin",
    )
    for kind in ("contract_validated", "queued"):
        engine.apply_transition(
            conn, task_id="T-1", kind=kind, actor="c", authority=states.CONTROLLER
        )
    return "T-1"


def issue(conn, **kw):
    return activations.issue(
        conn, task_id="T-1", agent="chatgpt", host="OFFICEPC", stage="author", repo_location="/repo", expected_branch="task/author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0, **kw
    )


def claim_and_report(conn, activation_id, outcome, payload=None):
    """Take an activation all the way to its terminal outcome."""
    activations.claim(
        conn, activation_id=activation_id, agent="chatgpt", now=T0)
    return outcomes.submit_author_outcome(
        conn, activation_id=activation_id, agent="chatgpt",
        outcome=outcome, payload=payload or {}, now=T0,
    )


def spent(conn):
    return engine.author_attempts_spent(conn, "T-1")


def repair(conn):
    """The road a blocked task takes back to READY_AUTHOR."""
    engine.apply_transition(
        conn, task_id="T-1", kind="environment_repaired", actor="admin",
        authority=states.CONTROLLER,
    )


# --- What spends an attempt, and what does not -------------------------------


def test_an_environment_defect_does_not_spend_an_attempt(conn, ready_task):
    """The T-INFRA-12 shape: a provider failure before any usable reply.

    The budget measures generative attempts. A run that never got one is not
    one, and charging it spends the author's allowance on the host's fault.
    """
    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "blocked", {
        "reason": "the provider call failed: timeout: Request timed out.",
        "provider_failure": "timeout",
    })

    assert spent(conn) == 0


def test_an_author_defect_does_spend_an_attempt(conn, ready_task):
    """The other side of the line. The model answered and the answer was
    unusable, which is exactly what an attempt is."""
    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "failed",
                     {"reason": "the answer did not apply"})

    assert spent(conn) == 1


def test_a_candidate_spends_an_attempt(conn, ready_task):
    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "candidate", {
        "branch": "task/T-1-a1", "candidate_sha": "a" * 40,
        "parent_sha": "0" * 40,
    })

    assert spent(conn) == 1


def test_an_activation_still_running_is_charged(conn, ready_task):
    """Chargeability is corrected when the outcome arrives, not predicted --
    so while a run is live it counts, and a second one cannot be minted
    beside it on the assumption that this one will fail."""
    issue(conn)

    assert spent(conn) == 1


def test_a_non_chargeable_activation_never_counts(conn, ready_task):
    issued = issue(conn, chargeable=False)
    claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})

    assert spent(conn) == 0


# --- Where the budget is enforced --------------------------------------------


def test_issue_refuses_once_the_budget_is_spent(conn, ready_task):
    """The half that was missing. `authorize_retry` refused a rejected task a
    fourth attempt; nothing refused anybody else."""
    for _ in range(3):
        issued = issue(conn)
        claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.CONTROLLER,
        )

    assert spent(conn) == 3

    with pytest.raises(engine.BudgetExhausted) as refused:
        issue(conn)

    assert "3 of 3" in str(refused.value)


def test_the_repair_route_cannot_exceed_the_budget(conn, ready_task):
    """T-INFRA-12's fourth activation, refused -- through the actual road.

    This has to reach AUTHOR_BLOCKED with the budget already spent, and the
    only way there now is a non-chargeable activation doing the blocking:
    three charged author defects spend the budget, and a fourth *chargeable*
    one is refused at issue. So the blocked run is issued `chargeable=False`,
    which is allowed because it spends nothing.

    Then the repair. A task reaching READY_AUTHOR through
    `environment_repaired` never passes `authorize_retry`, so before #21 this
    issued and the budget was a suggestion. It is `issue` that refuses it now.
    """
    for _ in range(3):
        issued = issue(conn)
        claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.CONTROLLER,
        )

    blocked = issue(conn, chargeable=False)
    claim_and_report(conn, blocked["activation_id"], "blocked", {"reason": "host"})

    assert engine.get_task(conn, "T-1")["state"] == "AUTHOR_BLOCKED"
    assert spent(conn) == 3

    repair(conn)

    assert engine.get_task(conn, "T-1")["state"] == "READY_AUTHOR"

    with pytest.raises(engine.BudgetExhausted):
        issue(conn)


def test_a_non_chargeable_activation_is_issued_past_the_budget(conn, ready_task):
    """It cannot exhaust what it does not spend, so it is not refused."""
    for _ in range(3):
        issued = issue(conn)
        claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.CONTROLLER,
        )

    assert issue(conn, chargeable=False)["activation_id"]


def spend_the_budget_and_produce_a_candidate(conn):
    """Two author defects, then a third attempt that succeeds. 3 of 3 spent,
    and a candidate waiting to be reviewed."""
    for _ in range(2):
        issued = issue(conn)
        claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.CONTROLLER,
        )

    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "candidate", {
        "branch": "task/T-1-a3", "candidate_sha": "a" * 40,
        "parent_sha": "0" * 40,
    })
    return issued


def test_a_review_activation_is_issued_past_a_spent_author_budget(
    conn, ready_task
):
    """The author ceiling is the author's, and nothing else's.

    A task that spends all three attempts and succeeds on the third still has
    to be reviewed. If the budget refused every stage rather than the author
    stage, that candidate could never be looked at -- the task would spend its
    last attempt producing work the controller then refused to review.
    """
    spend_the_budget_and_produce_a_candidate(conn)

    assert spent(conn) == 3

    reviewed = activations.issue(
        conn, task_id="T-1", agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
        expected_branch="task/T-1-a3", expected_candidate="a" * 40,
        repo_location="/srv/checkouts/T-1",
    )

    assert reviewed["activation_id"]


def test_a_review_activation_does_not_spend_the_author_budget(conn, ready_task):
    """The count is the author stage's. A review that also carries
    `chargeable_attempt = 1` would make reviewing a task cost it an attempt.
    """
    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "candidate", {
        "branch": "task/T-1-a1", "candidate_sha": "a" * 40,
        "parent_sha": "0" * 40,
    })

    assert spent(conn) == 1

    activations.issue(
        conn, task_id="T-1", agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE, now=T0,
        expected_branch="task/T-1-a1", expected_candidate="a" * 40,
        repo_location="/srv/checkouts/T-1",
    )

    assert spent(conn) == 1


# --- The two halves together --------------------------------------------------


def test_a_blocked_attempt_leaves_room_for_its_replacement(conn, ready_task):
    """The interaction, and the outcome T-INFRA-12 should have had.

    Two rejected attempts, then a provider timeout. The timeout does not
    count, so the replacement the operator asks for after repairing is the
    third attempt -- issued, and within the budget, rather than a fourth one
    nothing authorised.
    """
    for _ in range(2):
        issued = issue(conn)
        claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
        engine.apply_transition(
            conn, task_id="T-1", kind="retry_authorized", actor="admin",
            authority=states.CONTROLLER,
        )

    blocked = issue(conn)
    claim_and_report(conn, blocked["activation_id"], "blocked", {
        "reason": "the provider call failed: timeout: Request timed out.",
    })

    assert spent(conn) == 2

    repair(conn)
    replacement = issue(conn)

    assert replacement["activation_id"]
    assert spent(conn) == 3


def test_repeated_environment_defects_never_buy_an_attempt(conn, ready_task):
    """Un-charging must not become a way to mint attempts.

    A host that is broken all afternoon can block the same task many times
    over, and none of it moves the budget in either direction: the two real
    attempts around it are still the two that were spent.
    """
    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
    engine.apply_transition(
        conn, task_id="T-1", kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )

    for _ in range(5):
        blocked = issue(conn)
        claim_and_report(conn, blocked["activation_id"], "blocked", {"reason": "host"})
        repair(conn)

    assert spent(conn) == 1

    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})

    assert spent(conn) == 2


# --- One count, asked everywhere ----------------------------------------------


def test_every_caller_counts_the_same_attempts(conn, ready_task):
    """`authorize_retry`, `issue` and the chat ingress each used to hold their
    own copy of this SELECT. Two that decide something disagreeing is the
    defect; a third that only reports it is how an operator is misled."""
    from controller import ingress

    issued = issue(conn)
    claim_and_report(conn, issued["activation_id"], "failed", {"reason": "x"})
    blocked = None

    engine.apply_transition(
        conn, task_id="T-1", kind="retry_authorized", actor="admin",
        authority=states.CONTROLLER,
    )
    blocked = issue(conn)
    claim_and_report(conn, blocked["activation_id"], "blocked", {"reason": "y"})

    assert engine.author_attempts_spent(conn, "T-1") == 1
    assert ingress._author_attempts(conn, "T-1") == 1
    assert engine.refuse_if_budget_spent(conn, task_id="T-1", max_attempts=9) == 1
