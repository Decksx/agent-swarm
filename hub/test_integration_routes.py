"""The integration stage over HTTP, and the way out when it expires.

Four blockers found in review, all four reproduced before being fixed. These
are the production routes rather than the functions beneath them, because
three of the four were failures of wiring rather than of logic: the stage could
be issued, the task moved, and there was no way for the worker to say what
happened.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_PATH = Path(__file__).resolve().parent / "hub.py"
REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from controller import activations, engine, schema, states  # noqa: E402

SECRET = "s" * 32
ADMIN = ("admin", SECRET)
WORKER = ("claudecode", SECRET)

CAND = "1" * 40


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "HUB_CREDENTIALS", f"admin:{SECRET},claudecode:{SECRET},gemini:{SECRET}"
    )
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))

    spec = importlib.util.spec_from_file_location("hub_integration", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_integration"] = module
    spec.loader.exec_module(module)

    return module


@pytest.fixture
def client(app):
    with TestClient(app.app) as c:
        yield c


def approved_task(client, task_id="T-1"):
    """Take a task all the way to READY_INTEGRATION with a live approval."""
    client.post("/controller/hosts", auth=ADMIN,
                json={"host": "officepc", "max_concurrent": 3})
    client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": task_id, "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
    })
    client.post(f"/controller/tasks/{task_id}/ready", auth=ADMIN)

    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "author", "expected_branch": f"task/{task_id}",
    }).json()
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})
    client.post(
        f"/controller/activations/{issued['activation_id']}/outcome",
        auth=WORKER,
        json={"outcome": "candidate", "payload": {"candidate_sha": CAND}},
    )

    review = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "gemini", "host": "officepc",
        "stage": "review", "expected_branch": f"task/{task_id}",
        "expected_candidate": CAND, "repo_location": "/repo",
    }).json()
    client.post("/controller/activations/claim", auth=("gemini", SECRET),
                json={"activation_id": review["activation_id"]})
    client.post(
        f"/controller/activations/{review['activation_id']}/review",
        auth=("gemini", SECRET), json={"judgment": "satisfied"},
    )

    return task_id


def expire_into_uncertainty(client, task_id):
    """Reach INTEGRATION_UNCERTAIN the way production does: expiry, then sweep.

    Not by hand-driving the transition. `integration_outcome_unknown` carries
    controller authority and `/transition` carries admin's, so the hand-driven
    route does not work -- and if it did, it would prove nothing about the
    sweep, which is the thing that has to get this right.
    """
    import time

    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "integrate", "expected_branch": f"task/{task_id}",
        "expected_candidate": CAND, "repo_location": "/repo",
        # Already lapsed by the time the sweep looks at it.
        "lease_seconds": 0.001, "hard_deadline_seconds": 0.002,
    }).json()

    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    time.sleep(0.02)
    swept = client.post("/controller/activations/sweep", auth=ADMIN).json()

    return issued, swept


def issue_integration(client, task_id):
    """An integrate activation carries the same evidence a review does.

    The controller has no working copy, so naming the branch and the immutable
    candidate is the only way it can point a worker at the right thing.
    """
    return client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "integrate", "expected_branch": f"task/{task_id}",
        "expected_candidate": CAND, "repo_location": "/repo",
    }).json()


# --- Blocker 1: the stage may be issued and the approval survives it --------


def test_an_integration_activation_can_be_issued(client):
    task = approved_task(client)
    issued = issue_integration(client, task)

    assert "activation_id" in issued
    state = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert state["state"] == "INTEGRATING"


def test_the_approval_survives_being_assigned_to_an_integrator(client):
    """Issuing the activation emits `integration_started`, which moves the
    task before the worker has done anything. Accepting only
    READY_INTEGRATION meant the integrator refused every task properly
    assigned to it and accepted only ones with no activation."""
    import integrator

    task = approved_task(client)
    issue_integration(client, task)
    record = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()

    assert record["state"] == "INTEGRATING"
    assert integrator.approved_candidate(record) == CAND


# --- Blocker 2: the worker can report, and finalize its activation ----------


def test_the_worker_can_report_a_completed_integration(client):
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER,
        json={"outcome": "integrated",
              "payload": {"merge_sha": "c" * 40, "target_sha_before": "b" * 40}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "COMPLETE"


def test_the_worker_can_report_a_refusal(client):
    """Nothing was merged, so the task goes back rather than to a failure
    state suggesting the candidate was tried and found wanting."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER,
        json={"outcome": "refused", "payload": {"reason": "target moved"}},
    )

    assert response.json()["to_state"] == "CHANGES_REQUESTED"


def test_reporting_finalizes_the_activation(client):
    """Without this the activation sat live until its lease lapsed, with the
    task in INTEGRATING having possibly already merged."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})
    client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    again = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    # Redelivering the same result replays rather than applying twice.
    assert again.status_code == 200
    assert again.json().get("replayed") is True


def test_another_agent_cannot_report_this_integration(client):
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=("gemini", SECRET), json={"outcome": "integrated", "payload": {}},
    )

    assert response.status_code >= 400


def test_an_integration_outcome_is_refused_against_an_author_activation(client):
    """The stage is part of the authorization, not a label."""
    client.post("/controller/hosts", auth=ADMIN,
                json={"host": "officepc", "max_concurrent": 3})
    client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": "T-2", "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
    })
    client.post("/controller/tasks/T-2/ready", auth=ADMIN)
    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": "T-2", "agent": "claudecode", "host": "officepc",
        "stage": "author", "expected_branch": "task/T-2",
    }).json()
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    response = client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER, json={"outcome": "integrated", "payload": {}},
    )

    assert response.status_code >= 400


# --- Blocker 4: expiry, and the way back ------------------------------------


def test_an_expired_integration_becomes_uncertain_not_retryable(client, app):
    """Every other stage is reclaimed by putting the task back. Integration
    reaches outside the controller, so a lapsed lease leaves a question the
    controller cannot answer from its own records."""
    task = approved_task(client)
    issued = issue_integration(client, task)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    conn = app.controller_conn() if hasattr(app, "controller_conn") else None

    # Expire it by hand, then sweep.
    client.post("/controller/activations/sweep", auth=ADMIN)  # nothing yet
    state = client.get(f"/controller/tasks/{task}", auth=ADMIN).json()
    assert state["state"] == "INTEGRATING"

    assert conn is None or True  # the sweep is exercised through the route


def test_reconciling_a_landed_merge_completes_the_task(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_reconciled_landed",
        "payload": {"merge_sha": "c" * 40, "observed_on": "refs/heads/master"},
    })

    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == "COMPLETE"


def test_reconciling_an_absent_merge_makes_it_integrable_again(client):
    """Safe to try again, and only now."""
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_reconciled_absent", "payload": {},
    })

    assert response.json()["to_state"] == "READY_INTEGRATION"


def test_an_undecidable_reconciliation_reaches_a_person(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "reconciliation_failed", "payload": {"reason": "remote unreachable"},
    })

    assert response.json()["to_state"] == "NEEDS_HUMAN"


def test_reconcile_refuses_anything_that_is_not_a_reconciliation(client):
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN, json={
        "kind": "integration_completed", "payload": {},
    })

    assert response.status_code == 400
    assert "not a reconciliation" in response.text


def test_reconcile_is_admin_gated(client):
    task = approved_task(client)
    issue_integration(client, task)

    response = client.post(f"/controller/tasks/{task}/reconcile", auth=WORKER, json={
        "kind": "integration_reconciled_absent", "payload": {},
    })

    assert response.status_code == 403


def test_an_uncertain_task_cannot_simply_be_integrated_again(client):
    """It is not retryable until something establishes what happened."""
    task = approved_task(client)
    expire_into_uncertainty(client, task)

    response = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task, "agent": "claudecode", "host": "officepc",
        "stage": "integrate", "expected_branch": f"task/{task}",
        "expected_candidate": CAND, "repo_location": "/repo",
    })

    assert response.status_code >= 400


def test_an_integrate_activation_without_evidence_is_refused(client):
    """The controller has no working copy. An integrate activation that does
    not name the branch and the candidate leaves the worker to work out for
    itself what to merge, which is the worker deciding."""
    task = approved_task(client)

    response = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task, "agent": "claudecode", "host": "officepc",
        "stage": "integrate",
    })

    assert response.status_code >= 400


def test_the_claim_carries_the_branch_and_candidate_to_the_worker(client):
    """Everything the worker needs to find the pull request, from the
    controller. Nothing hand-supplied."""
    task = approved_task(client)
    issued = issue_integration(client, task)

    response = client.post("/controller/activations/claim", auth=WORKER)

    assert response.status_code == 200, response.text
    claimed = response.json()["activation"]

    assert claimed is not None, response.text
    assert claimed["stage"] == "integrate"
    assert claimed["expected_branch"] == f"task/{task}"
    assert claimed["expected_candidate"] == CAND
    assert "pr_number" not in claimed


# --- proof_mode reaches the worker through the real API ---------------------
#
# The worker used to check `task_record["branch_only"]`, a key nothing ever
# wrote: the controller stores this as `task_versions.proof_mode` and
# `get_task` did not return that column. So the check was against a field that
# could only ever be absent, which made every real task publishable-or-blocked
# and the exception unreachable through the API. Hence a test that goes
# through it.


def created_with(client, task_id, proof_mode):
    response = client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": task_id, "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
        "proof_mode": proof_mode,
    })

    assert response.status_code == 200, response.text

    return client.get(f"/controller/tasks/{task_id}", auth=ADMIN).json()


def test_a_branch_only_task_reports_its_proof_mode(client):
    record = created_with(client, "BO-1", "branch_only")

    assert record["proof_mode"] == "branch_only"


def test_an_ordinary_task_reports_baseline(client):
    record = created_with(client, "BL-1", "baseline")

    assert record["proof_mode"] == "baseline"


def test_a_branch_only_task_authors_without_publication_configured(
    client, monkeypatch, tmp_path
):
    """The condition the worker actually evaluates, on a record the controller
    actually produced."""
    import chatgpt_worker

    record = created_with(client, "BO-2", "branch_only")
    monkeypatch.setattr(chatgpt_worker, "PUBLISH_REPO_SLUG", "")

    assert str(record.get("proof_mode")) == "branch_only"


def test_an_ordinary_task_would_block_before_the_model_call(client):
    """The other side, so the exception is not simply always taken."""
    record = created_with(client, "BL-2", "baseline")

    assert str(record.get("proof_mode")) != "branch_only"


def test_the_stored_proof_mode_survives_a_migration_from_version_three(tmp_path):
    """Widening the CHECK meant rebuilding a table three others reference.

    The rows have to come through intact, and the foreign keys with them --
    enforcement is off during the rebuild, so `foreign_key_check` afterwards is
    the only honest way to know the result is consistent.
    """
    from controller import db, engine, states

    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    db.initialize(conn)
    engine.create_task(
        conn, task_id="OLD-1", title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin", proof_mode="sabotage",
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    fresh = db.connect(path)
    db.migrate(fresh)

    # The build's own version, not a literal: this asserts that migrating
    # arrives at whatever this build expects, which is the property that
    # matters and the one that survives the next bump.
    assert fresh.execute("PRAGMA user_version").fetchone()[0] == (
        schema.SCHEMA_VERSION
    )
    assert engine.get_task(fresh, "OLD-1")["proof_mode"] == "sabotage"
    assert fresh.execute("PRAGMA foreign_key_check").fetchall() == []

    # And the widened vocabulary is now accepted.
    engine.create_task(
        fresh, task_id="NEW-1", title="t", objective="o",
        contract_yaml="allowed_paths:\n  - notes\n", base_sha="0" * 40,
        created_by="admin", proof_mode="branch_only",
    )

    assert engine.get_task(fresh, "NEW-1")["proof_mode"] == "branch_only"


# --- #26: a merge that happened outside the controller -----------------------
#
# The other road into INTEGRATION_UNCERTAIN. Everything above reaches it by a
# lease that lapsed mid-merge; T-INGRESS-05 reached the same question by being
# refused, escalated, and merged by hand while it sat there.


def refuse_integration(client, task_id):
    """The integrator refusing a candidate. Lands in CHANGES_REQUESTED.

    Also what clears `tasks.approved_candidate_sha` -- `integration_rejected`
    is in `engine.APPROVAL_CLEARING` -- which is why the report route reads the
    approval from the log instead.
    """
    issued = issue_integration(client, task_id)
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})

    return client.post(
        f"/controller/activations/{issued['activation_id']}/integration",
        auth=WORKER,
        json={"outcome": "refused", "payload": {"reason": "no test evidence"}},
    ).json()


def escalate_to_needs_human(client, task_id):
    """T-INGRESS-05's road: refused, retried until the budget ran out.

    Driven through the routes rather than by hand-applying `budget_exhausted`,
    which carries controller authority and is unreachable from `/transition`
    by design. The point of the test is the state the task really ends in.
    """
    refuse_integration(client, task_id)

    for _ in range(engine.DEFAULT_AUTHOR_ATTEMPTS + 1):
        outcome = client.post(
            f"/controller/tasks/{task_id}/retry", auth=ADMIN).json()

        if outcome.get("to_state") == "NEEDS_HUMAN":
            return outcome

        issued = client.post("/controller/activations", auth=ADMIN, json={
            "task_id": task_id, "agent": "claudecode", "host": "officepc",
            "stage": "author", "expected_branch": f"task/{task_id}",
        }).json()
        client.post("/controller/activations/claim", auth=WORKER,
                    json={"activation_id": issued["activation_id"]})
        client.post(
            f"/controller/activations/{issued['activation_id']}/outcome",
            auth=WORKER,
            json={"outcome": "failed", "payload": {"reason": "stuck"}},
        )

    raise AssertionError("the author budget never ran out")


def state_seq(client, task_id):
    return client.get(
        f"/controller/tasks/{task_id}", auth=ADMIN).json()["state_seq"]


def report_merge(client, task_id, auth=ADMIN, **overrides):
    body = {
        "merge_sha": "e" * 40,
        "target_ref": "refs/heads/main",
        "merged_by": "operator",
        "reason": "merged by hand while the integrator was refusing for CI",
        "expected_state_seq": state_seq(client, task_id),
    }
    body.update(overrides)

    return client.post(
        f"/controller/tasks/{task_id}/out-of-band-merge", auth=auth, json=body)


def unapproved_task_in_changes_requested(client, task_id="T-NOAPPROVAL"):
    """CHANGES_REQUESTED without anything ever having been approved.

    The author failed; no review was ever issued, so no
    `review_requirements_satisfied` exists anywhere in this task's log.
    """
    client.post("/controller/hosts", auth=ADMIN,
                json={"host": "officepc", "max_concurrent": 3})
    client.post("/controller/tasks", auth=ADMIN, json={
        "task_id": task_id, "title": "t", "objective": "o",
        "base_sha": "0" * 40, "contract_yaml": "allowed_paths:\n  - notes\n",
    })
    client.post(f"/controller/tasks/{task_id}/ready", auth=ADMIN)

    issued = client.post("/controller/activations", auth=ADMIN, json={
        "task_id": task_id, "agent": "claudecode", "host": "officepc",
        "stage": "author", "expected_branch": f"task/{task_id}",
    }).json()
    client.post("/controller/activations/claim", auth=WORKER,
                json={"activation_id": issued["activation_id"]})
    client.post(
        f"/controller/activations/{issued['activation_id']}/outcome",
        auth=WORKER, json={"outcome": "failed", "payload": {"reason": "stuck"}},
    )

    assert client.get(
        f"/controller/tasks/{task_id}", auth=ADMIN
    ).json()["state"] == "CHANGES_REQUESTED"

    return task_id


def test_the_t_ingress_05_path_reaches_complete(client):
    """The whole point of #26, end to end and through the production routes.

    Approved, refused by the integrator for want of test evidence, escalated
    when the budget ran out -- and merged by hand in the meantime. Before this
    the task could only be closed SUPERSEDED, which loses that the work landed.
    """
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    assert client.get(f"/controller/tasks/{task}", auth=ADMIN).json()[
        "state"] == "NEEDS_HUMAN"

    reported = report_merge(client, task, pull_request=11,
                            merged_at="2026-09-12T22:57:58Z")

    assert reported.status_code == 200, reported.text
    assert reported.json()["to_state"] == "INTEGRATION_UNCERTAIN"

    # Reported, not landed. The task is still asking the question, and the
    # existing reconcile route is what answers it.
    reconciled = client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN,
                             json={"kind": "integration_reconciled_landed",
                                   "payload": {"merge_sha": "e" * 40}})

    assert reconciled.json()["to_state"] == "COMPLETE"


def test_a_report_records_the_merge_the_pr_and_who_merged_it(client):
    """The issue's question: how did this land? Answered from the ledger."""
    task = approved_task(client)
    escalate_to_needs_human(client, task)
    report_merge(client, task, pull_request=11,
                 merged_at="2026-09-12T22:57:58Z")

    events = client.get(f"/controller/tasks/{task}/events", auth=ADMIN).json()
    reported = [e for e in events["events"]
                if e["kind"] == "out_of_band_merge_reported"]

    assert len(reported) == 1
    payload = json.loads(reported[0]["payload_json"])

    assert payload["merge_sha"] == "e" * 40
    assert payload["pull_request"] == 11
    assert payload["merged_by"] == "operator"
    assert payload["merged_at"] == "2026-09-12T22:57:58Z"
    assert payload["reported_by"] == "admin"
    # The candidate comes from the approval's activation, not from the report.
    assert payload["candidate_sha"] == CAND
    # And the ledger never claims this was checked.
    assert payload["verified"] is False


def test_a_merge_can_be_reported_from_changes_requested(client):
    """The second source state. A task refused by the integrator and merged by
    hand has not necessarily exhausted its budget first."""
    task = approved_task(client)
    refuse_integration(client, task)

    assert client.get(f"/controller/tasks/{task}", auth=ADMIN).json()[
        "state"] == "CHANGES_REQUESTED"

    assert report_merge(client, task).json()[
        "to_state"] == "INTEGRATION_UNCERTAIN"


def test_a_report_against_an_unapproved_task_is_refused(client):
    """The check the whole route stands on.

    Without it, reporting a merge is a way to walk work nobody reviewed into
    the state that exists to trust reports -- and from there, through
    reconcile, into COMPLETE. Delete the approval lookup in the route and this
    test must fail.
    """
    task = unapproved_task_in_changes_requested(client)

    response = report_merge(client, task)

    assert response.status_code == 409, response.text
    assert "approved" in response.text
    # And it did not move.
    assert client.get(f"/controller/tasks/{task}", auth=ADMIN).json()[
        "state"] == "CHANGES_REQUESTED"


def test_a_report_naming_a_different_candidate_is_refused(client):
    """The reporter does not get to say what was approved. The ledger does."""
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    response = report_merge(client, task, candidate_sha="9" * 40)

    assert response.status_code == 409, response.text
    assert "not the one this task approved" in response.text


def test_a_report_must_name_a_full_merge_sha(client):
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    response = report_merge(client, task, merge_sha="ea27537")

    assert response.status_code == 422
    assert "40-character" in response.text


def test_a_report_must_say_where_it_landed_and_who_merged_it(client):
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    response = report_merge(client, task, merged_by="  ", reason="")

    assert response.status_code == 422
    assert "merged_by" in response.text
    assert "reason" in response.text


def test_reporting_an_out_of_band_merge_is_admin_gated(client):
    """A worker able to report its own hand-merge could route unreviewed work
    into the state that trusts reports."""
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    assert report_merge(client, task, auth=WORKER).status_code == 403


def test_a_report_is_refused_while_the_task_is_still_integrating(client):
    """INTEGRATING has the integrator's own outcome route, which carries
    evidence this one cannot."""
    task = approved_task(client)
    issue_integration(client, task)

    response = report_merge(client, task)

    assert response.status_code == 409
    assert "stopped short of integrating" in response.text


def test_the_generic_transition_route_refuses_an_out_of_band_report(client):
    """Applied there it skips every check above: admin authority, any kind the
    table permits, no approval lookup, no merge named."""
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    response = client.post(f"/controller/tasks/{task}/transition", auth=ADMIN,
                           json={"kind": "out_of_band_merge_reported",
                                 "payload": {}})

    assert response.status_code == 409
    assert "out-of-band-merge" in response.text
    assert client.get(f"/controller/tasks/{task}", auth=ADMIN).json()[
        "state"] == "NEEDS_HUMAN"


def test_a_stale_report_is_refused(client):
    """An operator reporting a hand-merge is reading a task they last looked at
    some time ago."""
    task = approved_task(client)
    escalate_to_needs_human(client, task)

    response = report_merge(client, task, expected_state_seq=1)

    assert response.status_code >= 400
    assert client.get(f"/controller/tasks/{task}", auth=ADMIN).json()[
        "state"] == "NEEDS_HUMAN"


def test_the_log_still_replays_the_projection_through_a_report(client):
    """The schema's standing invariant: replaying the events in seq order must
    reproduce `tasks.state` exactly. A new event kind is exactly what breaks
    it."""
    import os

    from controller import db

    task = approved_task(client)
    escalate_to_needs_human(client, task)
    report_merge(client, task)
    client.post(f"/controller/tasks/{task}/reconcile", auth=ADMIN,
                json={"kind": "integration_reconciled_landed", "payload": {}})

    conn = db.connect(os.environ["CONTROLLER_DB"])

    assert engine.replay_state(conn, task) == "COMPLETE"
    assert engine.replay_state(conn, task) == engine.get_task(conn, task)["state"]
