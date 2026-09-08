"""Global pause, the Admin activation path, and the control status view.

Phase 0 asks for a deterministic pause that prevents new work from starting,
and for Admin control to keep working. Those pull in opposite directions --
a stop that also stops the operator is not useful -- so both are asserted here
against the same machinery.
"""

from __future__ import annotations

import pytest

import claude_worker
from test_chat_cannot_activate import run_worker_loop


# --- Proof 7: authorized Admin control still works --------------------------


def test_admin_issued_activation_runs(monkeypatch, control):
    """The operator path is not merely un-blocked, it actually executes.

    Everything else in this suite proves work does *not* start. Without this
    test, a worker that refused everything unconditionally would look fully
    contained and be completely broken, and nothing would tell the difference.
    """
    control.issue_activation("claudecode", "run the preflight")

    invocations, _ = run_worker_loop(claude_worker, monkeypatch, control, [[], []])

    assert len(invocations) == 1
    assert "run the preflight" in invocations[0]


def test_admin_activation_result_is_posted_to_admin(monkeypatch, control):
    """The result goes back to the operator, not to a peer worker."""
    control.issue_activation("claudecode", "report status")

    _, fake_requests = run_worker_loop(claude_worker, monkeypatch, control, [[], []])

    assert fake_requests.posts, "no result was posted"
    assert fake_requests.posts[-1]["json"]["target"] == "@Admin"


def test_activation_is_consumed_exactly_once_across_many_polls(
    monkeypatch, control
):
    """Proof 9 for real work: five polls, one activation, one execution."""
    control.issue_activation("claudecode", "only once please")

    invocations, _ = run_worker_loop(
        claude_worker, monkeypatch, control, [[], [], [], [], []], polls=5
    )

    assert len(invocations) == 1


# --- Proof 8: global pause prevents new work --------------------------------


def test_pause_sentinel_prevents_execution(monkeypatch, control):
    """A paused host starts nothing, even with work already queued."""
    control.engage_pause("operator halted the swarm")
    control.issue_activation("claudecode", "must not run")

    invocations, _ = run_worker_loop(claude_worker, monkeypatch, control, [[], []])

    assert invocations == []


def test_pause_leaves_the_queued_work_intact(monkeypatch, control):
    """A pause defers work; it does not consume it.

    The pause is checked *before* the claim for exactly this reason. Checking
    after would have eaten the activation and then declined to run it, which
    looks identical in a log and loses the task.
    """
    control.engage_pause()
    control.issue_activation("claudecode", "deferred, not destroyed")

    run_worker_loop(claude_worker, monkeypatch, control, [[], []])

    assert control.control_status()["pending_activations"] == 1

    control.release_pause()
    claimed = control.claim_activation("claudecode")
    assert claimed is not None and claimed["task"] == "deferred, not destroyed"


def test_env_var_pause_is_independent_of_the_sentinel(monkeypatch, control):
    """Either stop alone holds the host.

    Two mechanisms because they fail differently: the file survives a restart
    and is what an operator reaches for, the variable is process-local and is
    what a launcher sets. Neither depends on the other.
    """
    monkeypatch.setenv("SWARM_PAUSED", "1")
    assert control.is_paused()

    monkeypatch.delenv("SWARM_PAUSED")
    assert not control.is_paused()

    control.engage_pause()
    assert control.is_paused()


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "engaged"])
def test_truthy_pause_values_engage(monkeypatch, control, value):
    monkeypatch.setenv("SWARM_PAUSED", value)
    assert control.is_paused()


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_explicitly_off_pause_values_do_not_engage(monkeypatch, control, value):
    monkeypatch.setenv("SWARM_PAUSED", value)
    assert not control.is_paused()


def test_unreadable_pause_flag_fails_closed(monkeypatch, control):
    """An unreadable stop signal is treated as engaged.

    The asymmetry is deliberate: a spurious pause costs a delay, while a missed
    one costs an unattended model run holding Bash authority.
    """
    control.engage_pause("some note")

    def boom(*_args, **_kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(type(control.PAUSE_PATH), "read_text", boom)

    reason = control.pause_reason()
    assert reason is not None and "failing closed" in reason


# --- The readable control status --------------------------------------------


def test_control_status_reports_the_containment_facts(control):
    """The status view answers the questions Phase 0 says must be visible."""
    status = control.control_status("claudecode")

    assert status["chat_is_authoritative"] is False
    assert status["paused"] is False
    assert status["pending_activations"] == 0

    control.issue_activation("claudecode", "queued work")
    control.engage_pause("maintenance window")

    status = control.control_status("claudecode")
    assert status["paused"] is True
    assert "maintenance window" in status["pause_reason"]
    assert status["pending_activations"] == 1


def test_status_is_written_where_an_operator_can_read_it(control):
    """`status.json` is produced, not just returned in-process."""
    import json

    control.write_status("claudecode")

    on_disk = json.loads(control.STATUS_PATH.read_text(encoding="utf-8"))
    assert on_disk["identity"] == "claudecode"
    assert on_disk["chat_is_authoritative"] is False


# --- The containment invariant is enforced, not merely documented -----------


@pytest.mark.parametrize(
    "worker_name", ["claude_worker", "chatgpt_worker", "gemini_worker"]
)
def test_workers_refuse_to_start_if_chat_becomes_authoritative(
    monkeypatch, control, worker_name
):
    """Flipping the constant stops the swarm rather than re-enabling chat.

    Nothing in the poll loop reads CHAT_IS_AUTHORITATIVE -- chat cannot start
    work because no code path leads from a message to execution. That is a
    structural property, and structural properties are the kind that get
    reintroduced by accident, so the constant is given teeth here: turning it
    back on means deleting a refusal in three separate files, which is visible
    in review.
    """
    import importlib

    worker = importlib.import_module(worker_name)

    monkeypatch.setattr(worker, "configure_logging", lambda: None)
    monkeypatch.setattr(worker.swarm_control, "CHAT_IS_AUTHORITATIVE", True)

    if worker_name == "claude_worker":
        monkeypatch.setattr(worker, "ensure_requests", lambda: object())
        monkeypatch.setattr(worker.shutil, "which", lambda _n: "/fake/claude")
    else:
        deps = (object(), object(), object()) if worker_name == "gemini_worker" else (object(), object())
        monkeypatch.setattr(worker, "ensure_dependencies", lambda: deps)

    # Tripwire past the guard. Without it, a build in which the refusal has
    # been removed does not fail this test -- it reaches the real poll loop and
    # hangs forever against the live hub, which is a much worse failure mode
    # than a red assertion. Found the hard way: the bypass matrix hung here.
    class ReachedTheLoop(Exception):
        pass

    def tripwire():
        raise ReachedTheLoop

    monkeypatch.setattr(worker, "load_last_seen_id", tripwire)

    assert worker.main() == 2
