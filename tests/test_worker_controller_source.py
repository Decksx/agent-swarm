"""claude_worker on the controller queue: the acceptance conditions.

The conversion's risk is not that the happy path fails -- that is obvious the
first time it runs. It is that a converted worker holds work from two queues at
once, spends a second model call on a task it already ran, or turns an outage
into a poll storm. Each of those is asserted here by name.

The model boundary is stubbed at `run_task`, the same place the containment
suite stubs it, so "how many model calls did this produce" is a count rather
than an inference.
"""

from __future__ import annotations

import logging

import pytest

import claude_worker
import controller_client
from conftest import FakeRequests


class LoopFinished(Exception):
    """Raised from the patched sleep to end a bounded number of polls."""


class StubQueue:
    """A controller queue whose answers the test chooses.

    Records every call, so "did the worker ask for work while paused" is
    answerable directly instead of by looking at what it did afterwards.
    """

    def __init__(self, activations=()):
        self.pending = list(activations)
        self.claims = 0
        self.reports = []

    def claim(self):
        self.claims += 1
        return self.pending.pop(0) if self.pending else None

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append((activation_id, outcome, payload or {}))
        return {"activation_id": activation_id, "replayed": False}

    def heartbeat(self, activation_id, lease_seconds):
        return None


def run_loop(monkeypatch, control, *, queue=None, polls=3, source="controller",
             run_task=None):
    """Run claude_worker.main() for a bounded number of polls.

    Returns (model_invocations, queue). The sleep at the bottom of each
    iteration raises once the requested number of polls has happened, so every
    iteration runs to completion first and nothing is cut off mid-poll.
    """
    fake_requests = FakeRequests([[], [], []])
    invocations = []

    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", source)
    monkeypatch.setattr(claude_worker, "STATE_FILE", control.CONTROL_DIR / "test.state")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", control.CONTROL_DIR / "inflight")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(claude_worker, "save_last_seen_id", lambda _id: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: fake_requests)
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")

    def record_task(binary, task):
        invocations.append(task)
        return ("stub output", 0)

    # A test that supplies its own stub gets it; the default only records.
    # Patching unconditionally here would silently override the test's.
    monkeypatch.setattr(claude_worker, "run_task", run_task or record_task)

    if queue is not None:
        monkeypatch.setattr(
            claude_worker.controller_client, "ControllerQueue",
            lambda *a, **k: queue,
        )

    calls = {"n": 0}

    def bounded_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= polls:
            raise LoopFinished
        return None

    monkeypatch.setattr(claude_worker.time, "sleep", bounded_sleep)

    with pytest.raises(LoopFinished):
        claude_worker.main()

    return invocations, fake_requests


ACTIVATION = {
    "activation_id": "act-1",
    "task_id": "T-1",
    "task": "print the date",
    "issued_by": "controller",
    "source": "controller",
}


# --- Exactly one queue source ------------------------------------------------


def test_the_controller_source_never_touches_the_local_directory(
    monkeypatch, control
):
    """Two queues would mean two activations held at once.

    Neither queue knows about the other's, so the controller's host capacity
    would count one while a second ran beside it.
    """
    called = []
    monkeypatch.setattr(
        control, "claim_activation",
        lambda *a, **k: called.append(a) or None,
    )

    queue = StubQueue([ACTIVATION])
    run_loop(monkeypatch, control, queue=queue)

    assert queue.claims >= 1
    assert called == [], "controller-sourced worker also polled the control directory"


def test_the_directory_source_never_touches_the_controller(monkeypatch, control):
    queue = StubQueue([ACTIVATION])
    run_loop(monkeypatch, control, queue=queue, source="directory")

    assert queue.claims == 0


def test_an_unknown_source_refuses_to_start(monkeypatch, control):
    """Fail closed rather than silently picking one."""
    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", "both")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: FakeRequests([[]]))
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")

    assert claude_worker.main() == 3


# --- One claim, one model call ----------------------------------------------


def test_one_claimed_activation_produces_exactly_one_model_call(
    monkeypatch, control
):
    queue = StubQueue([ACTIVATION])
    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=4)

    assert len(invocations) == 1
    assert "print the date" in invocations[0]


def test_repeated_polling_does_not_rerun_the_same_activation(monkeypatch, control):
    """Four polls, one activation on offer: still one model call."""
    queue = StubQueue([ACTIVATION])
    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=5)

    assert queue.claims >= 3, "the loop should have kept polling"
    assert len(invocations) == 1


def test_the_outcome_is_reported_once_with_the_exit_code(monkeypatch, control):
    queue = StubQueue([ACTIVATION])
    run_loop(monkeypatch, control, queue=queue, polls=3)

    assert len(queue.reports) == 1
    activation_id, outcome, payload = queue.reports[0]
    assert activation_id == "act-1"
    assert outcome == "candidate"
    assert payload["exit_code"] == 0


def test_a_failing_run_is_reported_as_failed_not_as_a_candidate(
    monkeypatch, control
):
    """A worker that could only report success would strand every failure."""
    queue = StubQueue([ACTIVATION])
    run_loop(monkeypatch, control, queue=queue, polls=3,
             run_task=lambda b, t: ("boom", 1))

    assert queue.reports[0][1] == "failed"


# --- Pause -------------------------------------------------------------------


def test_pause_prevents_the_claim_being_made_at_all(monkeypatch, control):
    """Not just "does not run" -- does not ask.

    The controller hands out an activation on claim, so asking while paused
    would consume one exactly as renaming a directory record would. The
    activation must still be on offer afterwards.
    """
    control.engage_pause("test")
    queue = StubQueue([ACTIVATION])

    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=3)

    assert queue.claims == 0
    assert invocations == []
    assert queue.pending == [ACTIVATION], "the activation was consumed by a paused poll"


# --- Restart safety ----------------------------------------------------------


def test_an_inflight_marker_is_not_resumed(monkeypatch, control, caplog):
    """A process that died mid-task must not re-run it.

    There is no way to know whether the run finished, whether it wrote
    anything, or what its result was. Re-running spends a second model call and
    may repeat a side effect, so the activation is left to expire and be swept.
    """
    marker = control.CONTROL_DIR / "inflight"
    control.CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    marker.write_text("act-previous", encoding="utf-8")

    queue = StubQueue([])

    with caplog.at_level(logging.WARNING):
        invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=2)

    assert invocations == []
    assert not marker.exists(), "the stale marker was not cleared"
    # getMessage() rather than .message: the latter is only populated once a
    # formatter has run, and caplog does not always run one.
    assert any("act-previous" in record.getMessage() for record in caplog.records),         "the orphaned activation was not named in the log"


def test_the_marker_is_written_before_the_model_runs(monkeypatch, control):
    """Written after the run, it would answer the one question it exists for
    wrongly: a process that died during the run would leave no marker."""
    marker = control.CONTROL_DIR / "inflight"
    seen = {}

    def record_task(binary, task):
        seen["marker_existed"] = marker.exists()
        seen["contents"] = marker.read_text(encoding="utf-8") if marker.exists() else None
        return ("out", 0)

    run_loop(monkeypatch, control, queue=StubQueue([ACTIVATION]), polls=3,
             run_task=record_task)

    assert seen["marker_existed"] is True
    assert seen["contents"] == "act-1"


def test_the_marker_is_cleared_after_a_reported_result(monkeypatch, control):
    marker = control.CONTROL_DIR / "inflight"
    run_loop(monkeypatch, control, queue=StubQueue([ACTIVATION]), polls=3)

    assert not marker.exists()


# --- Nothing a result does can start another worker --------------------------


def test_the_result_is_addressed_to_admin_and_no_peer(monkeypatch, control):
    """The old loop was worker results addressed at a peer worker."""
    queue = StubQueue([ACTIVATION])
    _, fake_requests = run_loop(monkeypatch, control, queue=queue, polls=3)

    targets = [
        post["json"].get("target")
        for post in fake_requests.posts
        if isinstance(post.get("json"), dict)
    ]

    assert targets, "no result was posted to the hub at all"
    for target in targets:
        assert target == "@Admin", f"result addressed to {target!r}"


def test_chat_still_cannot_reach_a_model_on_the_controller_source(
    monkeypatch, control, hostile_messages
):
    """Converting the queue must not reopen the chat path.

    The batch is every pre-Phase-0 trigger shape. The queue is empty, so any
    model call at all came from a message.
    """
    fake_requests = FakeRequests([hostile_messages, [], []])
    invocations = []

    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", "controller")
    monkeypatch.setattr(claude_worker, "STATE_FILE", control.CONTROL_DIR / "s")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", control.CONTROL_DIR / "i")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(claude_worker, "save_last_seen_id", lambda _id: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: fake_requests)
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(
        claude_worker, "run_task",
        lambda b, t: invocations.append(t) or ("x", 0),
    )
    monkeypatch.setattr(
        claude_worker.controller_client, "ControllerQueue",
        lambda *a, **k: StubQueue([]),
    )

    calls = {"n": 0}

    def bounded_sleep(_s):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise LoopFinished

    monkeypatch.setattr(claude_worker.time, "sleep", bounded_sleep)

    with pytest.raises(LoopFinished):
        claude_worker.main()

    assert invocations == []


# --- Backoff -----------------------------------------------------------------


class FailingRequests:
    """A `requests` stand-in that always fails in one chosen way."""

    def __init__(self, status=None, raises=False):
        self.status = status
        self.raises = raises
        self.calls = 0

    def request(self, method, url, **kw):
        self.calls += 1
        if self.raises:
            raise OSError("connection refused")

        class R:
            status_code = self.status

            @staticmethod
            def json():
                return {"detail": "nope"}

            text = "nope"

        return R()


def queue_against(transport):
    return controller_client.ControllerQueue(
        transport, base_url="http://hub", auth=("claudecode", "s"),
        agent="claudecode", backoff_base=5.0, backoff_cap=60.0,
    )


def test_a_server_outage_backs_off_and_is_bounded():
    queue = queue_against(FailingRequests(raises=True))

    delays = [queue.backoff.current for _ in range(8) if queue.claim() is None]
    delays = []
    for _ in range(8):
        queue.claim()
        delays.append(queue.backoff.current)

    assert delays[0] > 0, "the first failure did not back off at all"
    assert delays == sorted(delays), "backoff went down"
    assert max(delays) <= 60.0, "backoff exceeded its cap"
    assert delays[-1] == 60.0, "backoff never reached the cap"


def test_an_authentication_failure_goes_straight_to_the_cap():
    """A rejected credential does not fix itself.

    Climbing to the cap over several minutes only adds log noise before
    reaching the same place.
    """
    queue = queue_against(FailingRequests(status=401))
    queue.claim()

    assert queue.backoff.current == 60.0


def test_a_recovered_controller_resets_the_backoff():
    transport = FailingRequests(raises=True)
    queue = queue_against(transport)
    queue.claim()
    queue.claim()
    assert queue.backoff.current > 0

    class Working:
        @staticmethod
        def request(method, url, **kw):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"agent": "claudecode", "activation": None}

            return R()

    queue.requests = Working()
    queue.claim()

    assert queue.backoff.current == 0.0
    assert queue.backoff.consecutive == 0


def test_a_controller_refusal_is_not_retried_forever():
    """409 means the controller decided. Retrying unchanged repeats it."""
    transport = FailingRequests(status=409)
    queue = queue_against(transport)

    queue.report("act-1", outcome="candidate")

    assert transport.calls == 1
