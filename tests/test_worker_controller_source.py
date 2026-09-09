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

    def __init__(self, activations=(), claim_raises=None):
        self.pending = list(activations)
        self.claims = 0
        self.reports = []
        self.claim_raises = claim_raises
        # The real queue carries both, and the worker reads them to pace its
        # next poll. A stub without them would pass tests the worker fails.
        self.retry_after = 0.0
        self.backoff = controller_client.Backoff(5.0, 60.0)

    def claim(self):
        self.claims += 1
        if self.claim_raises is not None:
            raise self.claim_raises
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
    """A process that died mid-task must not re-run it *itself*.

    Fail-safe, not exactly-once. What this protects is the controller's state:
    no result is invented for a run nobody observed. It does not and cannot
    protect the repository -- the model may have committed before the crash,
    and once the lease expires a replacement activation runs the same task
    again on top of that. See docs/PHASE1_MVP_LIMITS.md.
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
            headers = {}

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


def test_a_rejected_credential_is_raised_and_not_backed_off():
    """Fatal, not slow.

    A credential cannot change inside a running process, so backing off
    produces a worker that is alive, logging, and structurally incapable of
    ever doing work -- which is harder to notice than an exit.
    """
    queue = queue_against(FailingRequests(status=401))

    with pytest.raises(controller_client.Unauthenticated):
        queue.claim()

    assert queue.backoff.current == 0.0, "a fatal failure should not back off"


def test_a_forbidden_claim_is_fatal_too():
    """403 on the claim route names no activation, so it is about the worker."""
    queue = queue_against(FailingRequests(status=403))

    with pytest.raises(controller_client.ClaimForbidden):
        queue.claim()


def test_a_forbidden_result_is_not_fatal():
    """403 when reporting is about one activation and clears on the next claim.

    Killing the worker for it would turn a stale lease into an outage.
    """
    transport = FailingRequests(status=403)
    queue = queue_against(transport)

    assert queue.report("act-1", outcome="candidate") is None
    assert transport.calls == 1


def test_a_429_is_honoured_rather_than_guessed_at():
    """The server named an interval; inventing another is worse either way."""

    class Throttling:
        calls = 0

        def request(self, method, url, **kw):
            Throttling.calls += 1

            class R:
                status_code = 429
                headers = {"Retry-After": "45"}

                @staticmethod
                def json():
                    return {}

                text = ""

            return R()

    queue = queue_against(Throttling())

    assert queue.claim() is None
    assert queue.retry_after == 45.0
    assert queue.backoff.current == 0.0, "a throttle is not an outage"


def test_a_missing_retry_after_falls_back_to_a_sane_wait():
    class Throttling:
        def request(self, method, url, **kw):
            class R:
                status_code = 429
                headers = {}

                @staticmethod
                def json():
                    return {}

                text = ""

            return R()

    queue = queue_against(Throttling())
    queue.claim()

    assert queue.retry_after == 30.0


def test_a_server_error_backs_off_but_a_fatal_one_does_not():
    """5xx resolves on its own; 401 does not. They must not share a path."""
    server = queue_against(FailingRequests(status=503))
    assert server.claim() is None
    assert server.backoff.current > 0

    auth = queue_against(FailingRequests(status=401))
    with pytest.raises(controller_client.Unauthenticated):
        auth.claim()
    assert auth.backoff.current == 0.0


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


def test_the_worker_exits_with_a_distinct_code_on_a_rejected_credential(
    monkeypatch, control
):
    """Exit 4, not exit 1 and not a crash.

    A supervisor has to be able to tell "this worker's credential is wrong"
    from "the claude binary is missing" (127) and from "chat was made
    authoritative" (2), because only one of them is fixed by editing the
    launcher's environment.
    """
    queue = StubQueue(claim_raises=controller_client.Unauthenticated("401"))
    fake_requests = FakeRequests([[], []])

    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", "controller")
    monkeypatch.setattr(claude_worker, "STATE_FILE", control.CONTROL_DIR / "s")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", control.CONTROL_DIR / "i")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(claude_worker, "save_last_seen_id", lambda _id: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: fake_requests)
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(
        claude_worker.controller_client, "ControllerQueue", lambda *a, **k: queue
    )
    monkeypatch.setattr(claude_worker.time, "sleep", lambda _s: None)

    assert claude_worker.main() == 4
    assert queue.claims == 1, "it should have stopped after the first refusal"


def test_a_forbidden_claim_also_exits(monkeypatch, control):
    queue = StubQueue(claim_raises=controller_client.ClaimForbidden("403"))
    fake_requests = FakeRequests([[], []])

    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", "controller")
    monkeypatch.setattr(claude_worker, "STATE_FILE", control.CONTROL_DIR / "s")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", control.CONTROL_DIR / "i")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(claude_worker, "save_last_seen_id", lambda _id: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: fake_requests)
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(
        claude_worker.controller_client, "ControllerQueue", lambda *a, **k: queue
    )
    monkeypatch.setattr(claude_worker.time, "sleep", lambda _s: None)

    assert claude_worker.main() == 4


def test_a_throttle_paces_the_next_poll(monkeypatch, control):
    """The worker waits what the server asked, not POLL_SECONDS."""
    queue = StubQueue([])
    queue.retry_after = 45.0
    slept = []

    monkeypatch.setattr(claude_worker, "POLL_SECONDS", 3.0)
    run_loop_slept(monkeypatch, control, queue, slept)

    assert max(slept) == 45.0


def run_loop_slept(monkeypatch, control, queue, slept):
    fake_requests = FakeRequests([[], [], []])

    monkeypatch.setattr(claude_worker, "ACTIVATION_SOURCE", "controller")
    monkeypatch.setattr(claude_worker, "STATE_FILE", control.CONTROL_DIR / "s")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", control.CONTROL_DIR / "i")
    monkeypatch.setattr(claude_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(claude_worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(claude_worker, "save_last_seen_id", lambda _id: None)
    monkeypatch.setattr(claude_worker, "ensure_requests", lambda: fake_requests)
    monkeypatch.setattr(claude_worker.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(claude_worker, "run_task", lambda b, t: ("x", 0))
    monkeypatch.setattr(
        claude_worker.controller_client, "ControllerQueue", lambda *a, **k: queue
    )

    def bounded_sleep(seconds):
        slept.append(seconds)
        if len(slept) >= 2:
            raise LoopFinished

    monkeypatch.setattr(claude_worker.time, "sleep", bounded_sleep)

    with pytest.raises(LoopFinished):
        claude_worker.main()
