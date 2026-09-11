"""The worker runs the stage it was given, and only that.

The stage used to be ignored entirely. Every activation went down the author
path: the model was called, a candidate was extracted from whatever came back,
and the result was reported through the author outcome route. An integration
activation issued to this worker would have spent a model call producing a
candidate for a task that already had an approved one, and reported it against
the wrong route -- so the merge would never happen and the ledger would say
something that did not.

The properties pinned here are countable on purpose: one claim, zero model
calls, one merge attempt, one outcome. Each was a way the old path could go
wrong silently.
"""

from __future__ import annotations

import pytest

import claude_worker
import integrator


CAND = "1" * 40
TARGET = "2" * 40
MERGE = "3" * 40


class Queue:
    """Records what the worker reported, and through which route."""

    def __init__(self):
        self.author_reports = []
        self.integration_reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.author_reports.append({"outcome": outcome, "payload": payload or {}})

    def report_integration(self, activation_id, *, outcome, payload=None):
        self.integration_reports.append(
            {"outcome": outcome, "payload": payload or {}}
        )

    @property
    def only(self):
        assert len(self.integration_reports) == 1, self.integration_reports
        return self.integration_reports[0]


class NoModel:
    """Any use of this fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"a model was reached ({name})")


@pytest.fixture
def counted(monkeypatch):
    """Counts model invocations through the worker's own call path."""
    state = {"calls": 0}

    def fake_run(*args, **kwargs):
        state["calls"] += 1
        raise AssertionError("the model was called")

    monkeypatch.setattr(claude_worker, "run_claude", fake_run, raising=False)
    return state


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for name, value in (
        ("INTEGRATION_REPO", str(tmp_path / "repo")),
        ("INTEGRATION_TARGET_REF", "refs/heads/master"),
        ("INTEGRATION_REPO_SLUG", "owner/repo"),
        ("INTEGRATION_WORK_ROOT", str(tmp_path / "work")),
    ):
        monkeypatch.setenv(name, value)


def activation(**over):
    base = {
        "activation_id": "A-1",
        "task_id": "T-1",
        "stage": "integrate",
        "task_record": {
            "task_id": "T-1",
            "state": "INTEGRATING",
            "approved_candidate_sha": CAND,
            "pr_number": 7,
        },
    }
    base.update(over)
    return base


# --- Dispatch ---------------------------------------------------------------


def test_an_unknown_stage_is_refused_before_any_model_call(counted):
    """A worker that does not know what it was asked to do must not do the
    only thing it knows how to do."""
    queue = Queue()

    claude_worker.execute_activation(
        NoModel(), "claude", activation(stage="review"), queue
    )

    assert counted["calls"] == 0
    assert queue.author_reports[0]["outcome"] == "blocked"
    assert "not one this worker runs" in queue.author_reports[0]["payload"]["reason"]


def test_an_integration_activation_never_reaches_the_model(
    monkeypatch, configured, counted
):
    queue = Queue()
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: {"candidate_sha": CAND, "merge_sha": MERGE,
                            "target_ref": "refs/heads/master"},
    )

    claude_worker.execute_activation(
        NoModel(), "claude", activation(), queue
    )

    assert counted["calls"] == 0
    assert queue.only["outcome"] == "integrated"


def test_an_integration_reports_through_the_integration_route(
    monkeypatch, configured
):
    """Not the author route. The controller checks the stage, but sending it
    to the right place is the worker's job."""
    queue = Queue()
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: {"candidate_sha": CAND, "merge_sha": MERGE,
                            "target_ref": "refs/heads/master"},
    )

    claude_worker.execute_activation(NoModel(), "claude", activation(), queue)

    assert len(queue.integration_reports) == 1
    assert queue.author_reports == []


def test_exactly_one_merge_attempt_and_one_outcome(monkeypatch, configured):
    """A second attempt would be a second merge of a candidate that may
    already be on the target."""
    attempts = {"count": 0}

    def once(task, **kw):
        attempts["count"] += 1
        return {"candidate_sha": CAND, "merge_sha": MERGE,
                "target_ref": "refs/heads/master"}

    monkeypatch.setattr(integrator, "run_integration", once)
    queue = Queue()

    claude_worker.execute_activation(NoModel(), "claude", activation(), queue)

    assert attempts["count"] == 1
    assert len(queue.integration_reports) == 1


# --- The authority a side effect requires -----------------------------------


def test_a_ready_integration_task_is_not_sufficient_to_merge(
    monkeypatch, configured
):
    """The whole guard. An approved task that nobody has been told to
    integrate is not a task to integrate -- the activation is what says so,
    and the state is what proves it was issued."""
    called = {"count": 0}
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: called.__setitem__("count", called["count"] + 1),
    )
    queue = Queue()

    claude_worker.execute_activation(
        NoModel(), "claude",
        activation(task_record={
            "task_id": "T-1", "state": "READY_INTEGRATION",
            "approved_candidate_sha": CAND, "pr_number": 7,
        }),
        queue,
    )

    assert called["count"] == 0
    assert queue.only["outcome"] == "blocked"
    assert "not INTEGRATING" in queue.only["payload"]["reason"]


def test_an_activation_of_another_stage_cannot_reach_the_merge(
    monkeypatch, configured
):
    """Belt and braces: dispatch would not send it here, and it refuses anyway
    if something else calls it directly."""
    called = {"count": 0}
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: called.__setitem__("count", called["count"] + 1),
    )
    queue = Queue()

    claude_worker.execute_integration(activation(stage="author"), queue)

    assert called["count"] == 0
    assert queue.only["outcome"] == "blocked"


def test_an_uncertain_task_is_not_merged(monkeypatch, configured):
    called = {"count": 0}
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: called.__setitem__("count", called["count"] + 1),
    )
    queue = Queue()

    claude_worker.execute_integration(
        activation(task_record={
            "task_id": "T-1", "state": "INTEGRATION_UNCERTAIN",
            "approved_candidate_sha": CAND, "pr_number": 7,
        }),
        queue,
    )

    assert called["count"] == 0
    assert queue.only["outcome"] == "blocked"


def test_a_missing_pull_request_blocks_rather_than_merges(
    monkeypatch, configured
):
    """The review artifact is what a person looked at."""
    called = {"count": 0}
    monkeypatch.setattr(
        integrator, "run_integration",
        lambda task, **kw: called.__setitem__("count", called["count"] + 1),
    )
    queue = Queue()

    claude_worker.execute_integration(
        activation(task_record={
            "task_id": "T-1", "state": "INTEGRATING",
            "approved_candidate_sha": CAND,
        }),
        queue,
    )

    assert called["count"] == 0
    assert queue.only["outcome"] == "blocked"


def test_an_unconfigured_host_blocks_rather_than_guessing(monkeypatch):
    for name in ("INTEGRATION_REPO", "INTEGRATION_TARGET_REF",
                 "INTEGRATION_REPO_SLUG", "INTEGRATION_WORK_ROOT"):
        monkeypatch.delenv(name, raising=False)

    queue = Queue()
    claude_worker.execute_integration(activation(), queue)

    assert queue.only["outcome"] == "blocked"
    assert "not configured" in queue.only["payload"]["reason"]


# --- A refusal is reported, not swallowed -----------------------------------


def test_a_refused_integration_is_reported_as_refused(monkeypatch, configured):
    def refuse(task, **kw):
        raise integrator.IntegrationRefused("the target moved; nothing landed")

    monkeypatch.setattr(integrator, "run_integration", refuse)
    queue = Queue()

    claude_worker.execute_integration(activation(), queue)

    assert queue.only["outcome"] == "refused"
    assert "nothing landed" in queue.only["payload"]["reason"]


def test_an_unexpected_failure_blocks_rather_than_refusing(
    monkeypatch, configured
):
    """`refused` means the checks said no. An unexpected exception means
    nobody knows, and those need different responses."""
    def explode(task, **kw):
        raise RuntimeError("ssh died")

    monkeypatch.setattr(integrator, "run_integration", explode)
    queue = Queue()

    claude_worker.execute_integration(activation(), queue)

    assert queue.only["outcome"] == "blocked"


def test_the_ledger_record_is_what_gets_reported(monkeypatch, configured):
    record = {
        "candidate_sha": CAND, "merge_sha": MERGE,
        "target_sha_before": TARGET, "target_ref": "refs/heads/master",
    }
    monkeypatch.setattr(integrator, "run_integration", lambda task, **kw: record)
    queue = Queue()

    claude_worker.execute_integration(activation(), queue)

    assert queue.only["payload"]["merge_sha"] == MERGE
    assert queue.only["payload"]["target_sha_before"] == TARGET
