"""Ingest for external review, controller half (#92).

Pins section 8 of `docs/design/92-ingest-contract.md`: the stored request, the
ingest activation's inputs, recovery, and every check the controller makes on
a worker's report before applying it. Controller primitives only, against a
temporary database -- no worker, no repository, no network.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from controller import activations, engine, external, outcomes, progression, states
from controller.db import open_controller_db
from controller.states import (
    ADMIN, AUTHOR, CONTROLLER, EXTERNAL_STATES, OPERATOR, VERIFIER,
)

T0 = 1_000_000.0
LEASE = 10.0
DEADLINE = 30.0
TASK = "EXT-1"
REPO = "C:/git/agent-swarm"
SLUG = "Decksx/agent-swarm"
HEAD = "a" * 40
BASE = "b" * 40
MERGE_BASE = "c" * 40
PROJECTS = {"agenthub": REPO}
REPOS = {"agenthub": SLUG}


@pytest.fixture
def conn(tmp_path):
    connection = open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, "OFFICEPC", 2)
    yield connection
    connection.close()


def request(conn, task_id=TASK, **overrides):
    fields = dict(
        task_id=task_id, project="agenthub", pr_number=102,
        objective="Review against the stated criteria", projects=PROJECTS,
        repos=REPOS, actor="admin", now=T0,
    )
    fields.update(overrides)
    return external.create(conn, **fields)


def issue(conn, task_id=TASK, *, now=T0, lease=LEASE, **kw):
    return activations.issue(
        conn, task_id=task_id, agent="claudecode", host="OFFICEPC", stage="ingest",
        lease_seconds=lease, hard_deadline_seconds=DEADLINE, now=now, **kw,
    )["activation_id"]


def claim(conn, aid, now=T0 + 1):
    return activations.claim(conn, activation_id=aid, agent="claudecode", now=now)


def body(text="Fixes the thing.\n\nGenerated with [Claude Code]"):
    return {
        "pr_body": text, "pr_body_truncated": False,
        "pr_body_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def registered(**overrides):
    payload = {
        "schema_version": 1, "project": "agenthub", "repo_location": REPO,
        "repo_slug": SLUG, "repo_id": "0dc8a2e4d227ab03", "pr_number": 102,
        "pr_url": f"https://github.com/{SLUG}/pull/102", "pr_state": "open",
        "pr_draft": False, "pr_title": "Make planning selectable",
        **body(),
        "head_sha": HEAD, "resolved_ref_sha": HEAD, "base_ref_sha": BASE,
        "merge_base": MERGE_BASE, "pin_ref": f"refs/swarm/external/{TASK}",
        "pin_created": True, "changed_files": ["README.md", "planner_cli.py"],
        "author_signals": [{
            "kind": "co_authored_by",
            "value": "Claude Opus 5.5 <noreply@anthropic.com>",
            "source": "commit:" + HEAD,
        }],
    }
    payload.update(overrides)
    return payload


def report(conn, aid, outcome, payload, now=T0 + 2):
    return outcomes.submit_ingest_outcome(
        conn, activation_id=aid, agent="claudecode", outcome=outcome,
        payload=payload, now=now,
    )


def ingesting(conn, **request_overrides):
    request(conn, **request_overrides)
    aid = issue(conn)
    claim(conn, aid)
    return aid


def state(conn, task_id=TASK):
    return engine.get_task(conn, task_id)["state"]


# --- The state table ----------------------------------------------------------------


def test_operator_authority_can_only_claim_on_the_external_chain():
    """The generic /result route applies any kind under the activation's role.
    On the external chain an ingest activation's OPERATOR role must reach the
    claim and nothing else -- not registration, refusal, review or integration."""
    reachable = sorted(
        (frm, kind) for (frm, kind), t in states.TRANSITIONS.items()
        if frm in EXTERNAL_STATES and OPERATOR in t.authorities
    )

    assert reachable == [("EXTERNAL_INGEST_ASSIGNED", "activation_claimed")]


@pytest.mark.parametrize("kind", [
    "external_candidate_registered", "external_ingest_refused", "environment_defect",
])
@pytest.mark.parametrize("authority", [AUTHOR, VERIFIER, OPERATOR, ADMIN])
def test_only_the_controller_ends_an_ingest(kind, authority):
    with pytest.raises(states.NotAuthorized):
        states.resolve("EXTERNAL_INGESTING", kind, authority)


@pytest.mark.parametrize("kind", [
    "external_candidate_registered", "external_ingest_refused", "environment_defect",
])
@pytest.mark.parametrize("start", ["EXTERNAL_PENDING", "EXTERNAL_INGEST_ASSIGNED"])
def test_an_ingest_cannot_end_before_it_is_claimed(kind, start):
    with pytest.raises(states.UndefinedTransition):
        states.resolve(start, kind, CONTROLLER)


def test_a_refusal_is_terminal_failure():
    assert states.resolve(
        "EXTERNAL_INGESTING", "external_ingest_refused", CONTROLLER
    ).to_state == "FAILED"


@pytest.mark.parametrize("start, kind", [
    ("EXTERNAL_INGEST_ASSIGNED", "lease_expired"),
    ("EXTERNAL_INGEST_ASSIGNED", "hard_deadline_reached"),
    ("EXTERNAL_INGESTING", "lease_expired"),
    ("EXTERNAL_INGESTING", "deadline_without_checkpoint"),
])
def test_a_lapsed_ingest_goes_back_to_pending(start, kind):
    assert states.resolve(start, kind, CONTROLLER).to_state == "EXTERNAL_PENDING"


# --- The request --------------------------------------------------------------------


def test_a_request_becomes_a_pending_task_with_its_request_stored_immutably(conn):
    created = request(conn, at_sha=HEAD.upper(), paths=["b.py", "a.py", "b.py"],
                      authored_by=["openai", "anthropic"])

    task = engine.get_task(conn, TASK)
    assert task["state"] == "EXTERNAL_PENDING"
    assert task["base_sha"] == "" and task["proof_mode"] == "branch_only"
    assert task["objective"] == "Review against the stated criteria"

    stored = json.loads(task["contract_yaml"])
    assert stored == {
        "external": {
            "schema_version": 1, "project": "agenthub", "repo_location": REPO,
            "repo_slug": SLUG, "pr_number": 102, "at_sha": HEAD,
            "paths": ["a.py", "b.py"], "authored_by": ["anthropic", "openai"],
        },
        "kind": "external_review", "schema_version": 7,
    }
    assert task["contract_yaml"] == external.canonical(stored)
    assert task["contract_hash"] == created["contract_hash"]
    assert external.load_request(conn, TASK) == stored["external"]


@pytest.mark.parametrize("overrides, message", [
    ({"project": "nope"}, "unknown project"),
    ({"pr_number": 0}, "pr_number"),
    ({"pr_number": "102"}, "pr_number"),
    ({"pr_number": True}, "pr_number"),
    ({"at_sha": "abc123"}, "at_sha"),
    ({"objective": "   "}, "objective"),
    ({"paths": []}, "paths"),
    ({"paths": ["../escape"]}, "repository-relative"),
    ({"paths": ["/abs"]}, "repository-relative"),
    ({"authored_by": ["martian"]}, "authored_by"),
    ({"task_id": "bad..id"}, "task_id"),
    ({"task_id": "x.lock"}, "task_id"),
    ({"task_id": "-dash"}, "task_id"),
])
def test_a_bad_request_is_refused_and_writes_nothing(conn, overrides, message):
    with pytest.raises(external.ExternalRequestRefused, match=message):
        request(conn, **overrides)

    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_a_project_without_a_repo_slug_is_not_enabled(conn):
    with pytest.raises(external.ExternalReviewDisabled, match="not enabled"):
        request(conn, repos={})

    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("value, message", [
    ("", "unset"),
    ("{not json", "not valid JSON"),
    ('["agenthub"]', "JSON object"),
    ('{"agenthub": "--help"}', "owner/name"),
    ('{"agenthub": "no-slash"}', "owner/name"),
])
def test_bad_repo_configuration_disables_external_review_only(value, message):
    with pytest.raises(external.ExternalReviewDisabled, match=message):
        external.parse_repos(value)


def test_the_slug_rule_is_the_registrys():
    """Copied because repo_registry is not deployed to Tower; held equal here."""
    import repo_registry

    assert external.REPO_SLUG_RE.pattern == repo_registry.REPO_SLUG.pattern


def test_a_transition_failure_leaves_no_task_behind(conn, monkeypatch):
    def refuse(*args, **kwargs):
        raise states.UndefinedTransition("refused for the test")

    monkeypatch.setattr(engine, "apply_transition_within", refuse)

    with pytest.raises(states.UndefinedTransition):
        request(conn)

    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM task_versions").fetchone()[0] == 0


# --- Issue and claim ----------------------------------------------------------------


def test_issue_fills_the_activation_from_the_stored_request(conn):
    request(conn, at_sha=HEAD)
    aid = issue(conn)

    row = activations.get_activation(conn, aid)
    assert (row["role"], row["stage"]) == ("operator", "ingest")
    assert row["expected_branch"] == f"refs/swarm/external/{TASK}"
    assert row["expected_candidate"] == HEAD
    assert row["expected_parent"] is None
    assert row["repo_location"] == REPO
    assert state(conn) == "EXTERNAL_INGEST_ASSIGNED"


@pytest.mark.parametrize("field, value", [
    ("expected_branch", "refs/heads/main"),
    ("expected_candidate", "d" * 40),
    ("expected_parent", "d" * 40),
    ("repo_location", "C:/elsewhere"),
])
def test_issue_refuses_inputs_that_differ_from_the_request(conn, field, value):
    request(conn)

    with pytest.raises(activations.ActivationError, match="stored request"):
        issue(conn, **{field: value})

    assert state(conn) == "EXTERNAL_PENDING"


def test_an_ingest_activation_is_only_for_an_external_request(conn):
    engine.create_task(conn, task_id="T-AUTHORED", title="t", objective="o",
                       contract_yaml="schema_version: 7\n", base_sha="0" * 40,
                       created_by="admin")

    with pytest.raises(activations.ActivationError, match="not an external-review"):
        issue(conn, "T-AUTHORED")


def test_the_claim_carries_the_external_inputs(conn):
    request(conn, at_sha=HEAD)
    aid = issue(conn)
    claimed = claim(conn, aid)

    assert claimed["stage"] == "ingest"
    assert claimed["external"] == {
        "schema_version": 1, "project": "agenthub", "repo_location": REPO,
        "repo_slug": SLUG, "pr_number": 102, "at_sha": HEAD, "paths": None,
        "pin_ref": f"refs/swarm/external/{TASK}",
        "scratch_ref_prefix": f"refs/swarm/ingest-tmp/{TASK}/{aid}",
        "reclaimable_scratch_prefixes": [],
    }
    assert state(conn) == "EXTERNAL_INGESTING"
    assert "lease_seconds_remaining" in claimed
    assert not {"lease_expires_at", "hard_deadline_at"} & set(claimed)


def test_other_stages_carry_no_external_inputs(conn):
    engine.create_task(conn, task_id="T-AUTH", title="t", objective="o",
                       contract_yaml="schema_version: 7\n", base_sha="0" * 40,
                       created_by="admin")
    engine.apply_transition(conn, task_id="T-AUTH", kind="contract_validated",
                            actor="t", authority=CONTROLLER)
    engine.apply_transition(conn, task_id="T-AUTH", kind="queued", actor="t",
                            authority=CONTROLLER)
    aid = activations.issue(
        conn, task_id="T-AUTH", agent="claudecode", host="OFFICEPC", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch="task/T-AUTH-a1", repo_location=REPO,
    )["activation_id"]

    assert "external" not in claim(conn, aid, now=None)


def test_dead_attempts_scratch_refs_are_listed_as_reclaimable(conn):
    request(conn)
    first = issue(conn)
    claim(conn, first)
    activations.sweep_expired(conn, now=T0 + LEASE + 5)
    assert state(conn) == "EXTERNAL_PENDING"

    second = issue(conn, now=T0 + 20)
    claimed = claim(conn, second, now=T0 + 21)

    assert claimed["external"]["reclaimable_scratch_prefixes"] == [
        f"refs/swarm/ingest-tmp/{TASK}/{first}"
    ]
    assert claimed["external"]["scratch_ref_prefix"].endswith(second)


def test_the_live_attempt_is_never_reclaimable(conn):
    request(conn)
    aid = issue(conn)

    assert external.claim_inputs(
        conn, activations.get_activation(conn, aid)
    )["reclaimable_scratch_prefixes"] == []


@pytest.mark.parametrize("status", ["ISSUED", "CLAIMED"])
def test_no_live_attempt_is_reclaimable_even_if_one_existed(conn, status):
    """The state machine allows one live ingest per task, so this cannot
    happen today. If it ever did, deleting a live sibling's scratch refs would
    pull objects out from under it -- so the listing checks status itself
    rather than relying on that."""
    request(conn)
    aid = issue(conn)
    row = activations.get_activation(conn, aid)
    conn.execute(
        "INSERT INTO activations (activation_id, task_id, task_version, agent, "
        "host, role, stage, attempt_no, issued_at, lease_expires_at, "
        "hard_deadline_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sibling", TASK, row["task_version"], "claudecode", "officepc",
         "operator", "ingest", 2, T0, T0 + LEASE, T0 + DEADLINE, status),
    )
    conn.commit()

    assert external.claim_inputs(conn, row)["reclaimable_scratch_prefixes"] == []


# --- Recovery -----------------------------------------------------------------------


@pytest.mark.parametrize("claimed", [False, True], ids=["assigned", "running"])
@pytest.mark.parametrize("timeout", ["lease", "deadline"])
def test_expiry_returns_ingest_to_pending_and_a_fresh_attempt_is_issued(
    conn, claimed, timeout,
):
    request(conn)
    aid = issue(conn, lease=DEADLINE * 2 if timeout == "deadline" else LEASE)
    if claimed:
        claim(conn, aid)

    when = T0 + (DEADLINE if timeout == "deadline" else LEASE)
    swept = activations.sweep_expired(conn, now=when)

    assert [s["activation_id"] for s in swept] == [aid]
    assert state(conn) == "EXTERNAL_PENDING"
    assert engine.replay_state(conn, TASK) == "EXTERNAL_PENDING"

    routing = progression.Routing(ingester="claudecode", host="OFFICEPC")
    issued = progression.advance(conn, routing=routing, now=when + 1)
    assert [r["issued"] for r in issued] == [True]


def test_a_late_report_after_expiry_is_refused(conn):
    aid = ingesting(conn)
    activations.sweep_expired(conn, now=T0 + LEASE + 1)

    with pytest.raises(activations.ActivationNotLive):
        report(conn, aid, "registered", registered(), now=T0 + LEASE + 2)

    assert state(conn) == "EXTERNAL_PENDING"


def test_a_report_after_cancellation_is_refused(conn):
    aid = ingesting(conn)
    engine.apply_transition(conn, task_id=TASK, kind="admin_cancelled",
                            actor="admin", authority=ADMIN)

    with pytest.raises(states.TransitionRejected):
        report(conn, aid, "registered", registered())

    assert state(conn) == "CANCELLED"


# --- The report ---------------------------------------------------------------------


def test_a_valid_report_pins_the_candidate_and_records_the_evidence(conn):
    aid = ingesting(conn)
    result = report(conn, aid, "registered", registered())

    assert result["to_state"] == "READY_EXTERNAL_REVIEW"
    task = engine.get_task(conn, TASK)
    assert task["approved_candidate_sha"] is None

    event = conn.execute(
        "SELECT * FROM events WHERE kind = 'external_candidate_registered'"
    ).fetchone()
    stored = json.loads(event["payload_json"])
    assert stored["head_sha"] == HEAD and stored["merge_base"] == MERGE_BASE
    assert stored["changed_files"] == ["README.md", "planner_cli.py"]
    assert stored["outcome"] == "registered" and stored["outcome_by"] == "claudecode"
    assert event["authority"] == CONTROLLER
    assert engine.replay_state(conn, TASK) == "READY_EXTERNAL_REVIEW"


def test_a_duplicate_report_replays_and_a_different_one_conflicts(conn):
    aid = ingesting(conn)
    first = report(conn, aid, "registered", registered())
    again = report(conn, aid, "registered", registered())

    assert again["replayed"] is True and again["event_id"] == first["event_id"]

    with pytest.raises(activations.ConflictingResult):
        report(conn, aid, "blocked", {"schema_version": 1,
                                      "reason_code": "worker_error", "detail": "x"})


# --- Replay before liveness (contract 8.3) ------------------------------------------
#
# A worker whose accepted report lost its response must be able to resend it
# and get the same answer, however late. Nothing else may skip liveness.


@pytest.mark.parametrize("outcome, payload, to_state", [
    ("registered", registered(), "READY_EXTERNAL_REVIEW"),
    ("refused", {"schema_version": 1, "reason_code": "pr_not_found", "detail": "d"},
     "FAILED"),
    ("blocked", {"schema_version": 1, "reason_code": "gh_auth", "detail": "d"},
     "EXTERNAL_INGEST_BLOCKED"),
])
@pytest.mark.parametrize("resend_at", [
    T0 + 3,                      # immediately, against a DONE activation
    T0 + LEASE + 5,              # after the lease lapsed
    T0 + DEADLINE + 5,           # after the hard deadline
], ids=["done", "after-lease", "after-deadline"])
def test_a_lost_response_is_answered_by_an_identical_redelivery(
    conn, outcome, payload, to_state, resend_at,
):
    aid = ingesting(conn)
    accepted = report(conn, aid, outcome, payload)
    assert activations.get_activation(conn, aid)["status"] == activations.DONE

    activations.sweep_expired(conn, now=resend_at)
    again = report(conn, aid, outcome, payload, now=resend_at)

    assert again["replayed"] is True
    assert again["event_id"] == accepted["event_id"]
    assert again["to_state"] == to_state
    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE activation_id = ? "
        "AND kind NOT IN ('ingest_activation_issued', 'activation_claimed')",
        (aid,),
    ).fetchone()[0] == 1, "a replay must not append a second event"


@pytest.mark.parametrize("resend_at", [T0 + 3, T0 + DEADLINE + 5])
def test_a_differing_redelivery_is_refused_even_late(conn, resend_at):
    aid = ingesting(conn)
    report(conn, aid, "registered", registered())

    with pytest.raises(activations.ConflictingResult):
        report(conn, aid, "registered", registered(pin_created=False), now=resend_at)


@pytest.mark.parametrize("after_result", [False, True])
def test_another_agent_cannot_report_or_replay(conn, after_result):
    aid = ingesting(conn)
    if after_result:
        report(conn, aid, "registered", registered())

    with pytest.raises(activations.NotTheAssignedWorker):
        outcomes.submit_ingest_outcome(conn, activation_id=aid, agent="gemini",
                                       outcome="registered", payload=registered(),
                                       now=T0 + 3)


@pytest.mark.parametrize("late_at, refusal", [
    (T0 + LEASE, activations.LeaseExpired),
    (T0 + DEADLINE, activations.DeadlineExceeded),
])
def test_a_genuinely_new_late_report_is_refused(conn, late_at, refusal):
    """No result was recorded, so this is a first submission and liveness
    applies -- before any sweep has run, and whatever the worker believed."""
    aid = ingesting(conn)

    with pytest.raises(refusal):
        report(conn, aid, "registered", registered(), now=late_at)

    assert state(conn) == "EXTERNAL_INGESTING"
    assert activations.get_activation(conn, aid)["result_request_hash"] is None


def test_an_ingest_report_against_another_stages_result_is_a_conflict(conn):
    """The replay key carries the stage, so it can never match another stage's
    recorded result -- it is a conflict, not a replay and not a new result."""
    aid = ingesting(conn)
    report(conn, aid, "registered", registered())
    review = activations.issue(
        conn, task_id=TASK, agent="claudecode", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"refs/swarm/external/{TASK}", expected_parent=MERGE_BASE,
        expected_candidate=HEAD, repo_location=REPO, now=T0 + 3,
    )["activation_id"]
    activations.claim(conn, activation_id=review, agent="claudecode", now=T0 + 4)
    outcomes.submit_result(conn, activation_id=review, agent="claudecode",
                           kind="note", payload={"text": "x"}, now=T0 + 5)

    with pytest.raises(activations.ConflictingResult):
        report(conn, review, "registered", registered(), now=T0 + 6)


@pytest.mark.parametrize("overrides", [
    {"project": "other"},
    {"repo_location": "C:/elsewhere"},
    {"repo_slug": "Someone/else"},
    {"repo_id": "XYZ"},
    {"pr_number": 103},
    {"pr_number": True},
    {"pr_url": "https://github.com/Someone/else/pull/102"},
    {"pr_url": f"https://github.com/{SLUG}/pull/1022"},
    {"pr_url": f"http://github.com/{SLUG}/pull/102"},
    {"pr_state": "draft"},
    {"pr_draft": "no"},
    {"pr_title": "x" * 1025},
    {"pr_body_sha256": "0" * 64},
    {"pr_body_sha256": "short"},
    {"head_sha": HEAD.upper(), "resolved_ref_sha": HEAD.upper()},
    {"resolved_ref_sha": "d" * 40},
    {"base_ref_sha": "nope"},
    {"merge_base": HEAD},
    {"pin_ref": "refs/swarm/external/OTHER"},
    {"pin_created": 1},
    {"changed_files": []},
    {"changed_files": ["b.py", "a.py"]},
    {"changed_files": ["a.py", "a.py"]},
    {"changed_files": ["../outside.py"]},
    {"author_signals": [{"kind": "family", "value": "anthropic", "source": "pr_body"}]},
    {"author_signals": [{"kind": "co_authored_by", "value": "x", "source": "commit:abc"}]},
    {"schema_version": 2},
    {"sha_matches": True},
    # Exact matching: `$` also matches before a trailing newline (Codex, #107).
    {"head_sha": HEAD + "\n", "resolved_ref_sha": HEAD + "\n"},
    {"base_ref_sha": BASE + "\n"},
    {"merge_base": MERGE_BASE + "\n"},
    {"repo_id": "0dc8a2e4d227ab03\n"},
    {"pr_body_truncated": True,
     "pr_body_sha256": hashlib.sha256(b"x").hexdigest() + "\n"},
    {"author_signals": [{"kind": "co_authored_by", "value": "x",
                         "source": "commit:" + HEAD + "\n"}]},
    # Integers are ints, not floats or booleans.
    {"pr_number": 102.0},
    {"schema_version": True},
    {"schema_version": 1.0},
    # Wrong types where a membership test follows: a 422, never a 500.
    {"pr_state": []},
    {"pr_state": {"open": True}},
    {"author_signals": [{"kind": [], "value": "x", "source": "pr_body"}]},
    {"author_signals": [{"kind": "co_authored_by", "value": [], "source": "pr_body"}]},
    {"author_signals": [{"kind": "co_authored_by", "value": "x", "source": {}}]},
    {"author_signals": ["not an object"]},
    {"author_signals": {"kind": "co_authored_by"}},
    {"changed_files": [["README.md"]]},
    {"changed_files": "README.md"},
    {"pr_title": None},
    {"pr_body": 7},
])
def test_a_report_the_request_contradicts_is_refused_and_records_nothing(conn, overrides):
    aid = ingesting(conn)

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "registered", registered(**overrides))

    assert state(conn) == "EXTERNAL_INGESTING"
    assert activations.get_activation(conn, aid)["status"] == activations.CLAIMED
    # Still able to say what it should have said.
    assert report(conn, aid, "registered", registered())["to_state"] == "READY_EXTERNAL_REVIEW"


@pytest.mark.parametrize("key", sorted(external.REGISTERED_KEYS))
def test_every_registered_field_is_required(conn, key):
    aid = ingesting(conn)
    payload = registered()
    del payload[key]

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "registered", payload)


def test_the_operators_sha_is_checked_by_the_controller(conn):
    aid = ingesting(conn, at_sha="d" * 40)

    with pytest.raises(activations.IngestReportInvalid, match="at_sha"):
        report(conn, aid, "registered", registered())


def test_a_truncated_body_may_carry_the_full_bodys_hash(conn):
    aid = ingesting(conn)
    payload = registered(pr_body="cut", pr_body_truncated=True,
                         pr_body_sha256=hashlib.sha256(b"cut and more").hexdigest())

    assert report(conn, aid, "registered", payload)["to_state"] == "READY_EXTERNAL_REVIEW"


def test_a_colon_inside_a_git_path_is_an_ordinary_character(conn):
    """Only a one-letter first segment before the colon (`a:b`) is refused,
    because on Windows that is a drive-relative path, not a repository one."""
    aid = ingesting(conn)
    payload = registered(changed_files=["docs/x:y.txt", "notes:2026.md"])

    assert report(conn, aid, "registered", payload)["to_state"] == "READY_EXTERNAL_REVIEW"


@pytest.mark.parametrize("path", ["C:/x.py", "c:x.py", "a:b", "/abs.py", "\\abs.py"])
def test_absolute_and_drive_paths_are_still_refused(conn, path):
    aid = ingesting(conn)

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "registered", registered(changed_files=[path]))


def test_the_pr_slug_compares_case_insensitively(conn):
    aid = ingesting(conn)
    payload = registered(repo_slug=SLUG.lower(),
                         pr_url=f"https://github.com/{SLUG.upper()}/pull/102")

    assert report(conn, aid, "registered", payload)["to_state"] == "READY_EXTERNAL_REVIEW"


def test_an_oversized_report_is_refused(conn):
    aid = ingesting(conn)
    signals = [{"kind": "pr_body_footer", "value": "x" * 512, "source": "pr_body"}] * 300

    with pytest.raises(activations.IngestReportInvalid, match="over 131072"):
        report(conn, aid, "registered", registered(author_signals=signals))


@pytest.mark.parametrize("reason, observed", [
    ("pr_not_found", {}),
    ("head_moved", {"head_sha": HEAD, "resolved_ref_sha": "d" * 40}),
    ("pin_conflict", {"head_sha": HEAD, "existing_pin_sha": "d" * 40}),
    ("no_merge_base", {"head_sha": HEAD, "base_ref_sha": BASE}),
    ("empty_range", {"head_sha": HEAD}),
    ("evidence_too_large", {"head_sha": HEAD}),
])
def test_a_refusal_fails_the_task(conn, reason, observed):
    aid = ingesting(conn)
    result = report(conn, aid, "refused", {"schema_version": 1, "reason_code": reason,
                                           "detail": "d", "observed": observed})

    assert result["to_state"] == "FAILED"
    assert engine.get_task(conn, TASK)["approved_candidate_sha"] is None


def test_an_at_sha_mismatch_refusal_is_checked_against_the_request(conn):
    aid = ingesting(conn, at_sha="d" * 40)
    payload = {"schema_version": 1, "reason_code": "at_sha_mismatch", "detail": "d"}

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "refused", {**payload, "observed": {"head_sha": "d" * 40}})

    assert report(conn, aid, "refused", {**payload, "observed": {"head_sha": HEAD}})[
        "to_state"] == "FAILED"


@pytest.mark.parametrize("payload", [
    {"reason_code": "head_moved", "observed": {"head_sha": HEAD, "resolved_ref_sha": HEAD}},
    {"reason_code": "head_moved", "observed": {"head_sha": HEAD}},
    {"reason_code": "pin_conflict", "observed": {"head_sha": HEAD, "existing_pin_sha": HEAD}},
    {"reason_code": "at_sha_mismatch", "observed": {"head_sha": HEAD}},
    {"reason_code": "github_unreachable", "observed": {}},
    {"reason_code": "pr_not_found", "observed": {"head_sha": "nope"}},
    {"reason_code": "pr_not_found", "observed": {"other_sha": HEAD}},
    {"reason_code": "pr_not_found", "observed": {}, "stderr": "raw"},
    {"reason_code": "pr_not_found", "observed": {}, "detail": "x" * 2001},
    # Wrong types before membership tests (Codex, #107).
    {"reason_code": ["pr_not_found"], "observed": {}},
    {"reason_code": {"pr_not_found": 1}, "observed": {}},
    {"reason_code": None, "observed": {}},
    {"reason_code": "pr_not_found", "observed": []},
    {"reason_code": "pr_not_found", "observed": {"head_sha": HEAD + "\n"}},
    {"reason_code": "pr_not_found", "observed": {}, "schema_version": True},
])
def test_an_inconsistent_refusal_is_refused(conn, payload):
    aid = ingesting(conn)
    full = {"schema_version": 1, "detail": "d", **payload}

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "refused", full)

    assert state(conn) == "EXTERNAL_INGESTING"


@pytest.mark.parametrize("reason", sorted(external.BLOCKED_REASONS))
def test_blocked_is_repairable_and_not_charged(conn, reason):
    aid = ingesting(conn)
    result = report(conn, aid, "blocked", {"schema_version": 1, "reason_code": reason,
                                           "detail": "could not reach GitHub"})

    assert result["to_state"] == "EXTERNAL_INGEST_BLOCKED"
    assert activations.get_activation(conn, aid)["chargeable_attempt"] == 0

    engine.apply_transition(conn, task_id=TASK, kind="environment_repaired",
                            actor="admin", authority=CONTROLLER)
    assert state(conn) == "EXTERNAL_PENDING"


@pytest.mark.parametrize("reason", [["gh_auth"], {"gh_auth": 1}, 3])
def test_a_blocked_report_with_a_non_string_reason_is_refused(conn, reason):
    aid = ingesting(conn)

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "blocked", {"schema_version": 1, "reason_code": reason,
                                      "detail": "d"})

    assert state(conn) == "EXTERNAL_INGESTING"


def test_any_unanticipated_shape_is_a_refused_report_not_a_crash(conn, monkeypatch):
    """The safety net behind the explicit type checks: whatever a check trips
    over becomes ReportInvalid, so the route answers 422 rather than 500."""
    aid = ingesting(conn)

    def explode(*args, **kwargs):
        raise TypeError("unhashable type: 'list'")

    monkeypatch.setattr(external, "_check_registered", explode)

    with pytest.raises(activations.IngestReportInvalid, match="malformed report"):
        report(conn, aid, "registered", registered())

    assert state(conn) == "EXTERNAL_INGESTING"


@pytest.mark.parametrize("task_id", ["EXT-1\n", "ok\n"])
def test_a_task_id_with_a_trailing_newline_is_refused(conn, task_id):
    with pytest.raises(external.ExternalRequestRefused, match="task_id"):
        request(conn, task_id=task_id)


def test_a_slug_with_a_trailing_newline_disables_external_review():
    with pytest.raises(external.ExternalReviewDisabled):
        external.parse_repos('{"agenthub": "Decksx/agent-swarm\\n"}')


def test_an_unknown_blocked_reason_is_refused(conn):
    aid = ingesting(conn)

    with pytest.raises(activations.IngestReportInvalid):
        report(conn, aid, "blocked", {"schema_version": 1, "reason_code": "pr_not_found",
                                      "detail": "a refusal is not an environment defect"})


def test_an_ingest_report_cannot_land_on_another_stage(conn):
    """The /ingest route against a review activation is refused (403)."""
    request(conn)
    aid = issue(conn)
    claim(conn, aid)
    report(conn, aid, "registered", registered())
    review = activations.issue(
        conn, task_id=TASK, agent="gemini", host="OFFICEPC", stage="review",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch=f"refs/swarm/external/{TASK}", expected_parent=MERGE_BASE,
        expected_candidate=HEAD, repo_location=REPO,
    )["activation_id"]

    with pytest.raises(activations.NotAReviewActivation):
        outcomes.submit_ingest_outcome(
            conn, activation_id=review, agent="gemini", outcome="registered",
            payload=registered(),
        )


def test_the_generic_result_route_cannot_end_an_ingest(conn):
    """OPERATOR authority, applied through /result, can register nothing."""
    aid = ingesting(conn)

    for kind in ("external_candidate_registered", "external_ingest_refused",
                 "environment_defect", "external_review_judged"):
        with pytest.raises(states.TransitionRejected):
            outcomes.submit_result(conn, activation_id=aid, agent="claudecode",
                                   kind=kind, payload={}, now=T0 + 2)

    assert state(conn) == "EXTERNAL_INGESTING"


# --- Progression --------------------------------------------------------------------


def test_progression_issues_ingest_only_with_an_ingester(conn):
    request(conn)

    unconfigured = progression.advance(
        conn, routing=progression.Routing(host="OFFICEPC"), now=T0)
    assert unconfigured[0]["reason_code"] == "routing_missing"
    assert "ingester" in unconfigured[0]["reason"]
    assert unconfigured[0]["persistent"] is True

    routing = progression.Routing(ingester="claudecode", host="OFFICEPC")
    first = progression.advance(conn, routing=routing, now=T0)
    again = progression.advance(conn, routing=routing, now=T0 + 1)

    assert first[0]["issued"] is True and first[0]["stage"] == "ingest"
    assert first[0]["expected_branch"] == f"refs/swarm/external/{TASK}"
    assert first[0]["repo_location"] == REPO
    # Issuing moved the task out of EXTERNAL_PENDING, so a second poll has
    # nothing to consider and cannot issue a duplicate.
    assert again == []
    assert state(conn) == "EXTERNAL_INGEST_ASSIGNED"
    assert conn.execute(
        "SELECT COUNT(*) FROM activations WHERE task_id = ?", (TASK,)
    ).fetchone()[0] == 1


def test_progression_does_not_issue_ingest_for_a_blocked_task(conn):
    aid = ingesting(conn)
    report(conn, aid, "blocked", {"schema_version": 1, "reason_code": "gh_auth",
                                  "detail": "gh is not logged in"})
    routing = progression.Routing(ingester="claudecode", host="OFFICEPC")

    assert progression.advance(conn, routing=routing, now=T0 + 3) == []


def test_progression_stops_at_ready_for_external_review(conn):
    """#92 issues ingest only. Reviews of external candidates are #93."""
    aid = ingesting(conn)
    report(conn, aid, "registered", registered())
    routing = progression.Routing(ingester="claudecode", verifier="gemini",
                                  integrator="claudecode", host="OFFICEPC")

    assert progression.advance(conn, routing=routing, now=T0 + 3) == []
    assert state(conn) == "READY_EXTERNAL_REVIEW"
