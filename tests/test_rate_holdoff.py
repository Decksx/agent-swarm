"""The rate window holds work off, then lets it go again by itself.

The previous guard stopped accepting work and required a restart to clear.
That is a manual step in a system whose stated purpose is not needing one, and
its failure mode is quiet: an operator who did not notice would find a worker
that looked healthy and had stopped working hours earlier.

Two properties are asserted here that pull against each other. It must hold
off, and it must stop holding off -- and the second is the one a test
protects, because a guard that never releases still passes every "did it
refuse?" test anyone would write.
"""

from __future__ import annotations

import time

import pytest

import claude_worker


@pytest.fixture
def guard(tmp_path, monkeypatch):
    """A worker whose rate state lives in a tmpdir, with a short window."""
    monkeypatch.setattr(claude_worker, "RATELIMIT_PATH", tmp_path / "rl")
    monkeypatch.setattr(claude_worker, "USAGE_PATH", tmp_path / "usage")
    monkeypatch.setattr(claude_worker, "RATE_LIMIT_WARN_SECONDS", 100.0)
    monkeypatch.setattr(claude_worker, "RATE_LIMIT_COOLDOWN_SECONDS", 50.0)
    # Set initial usage to some example values
    usage_example = [(time.monotonic() - 60, 30.0), (time.monotonic() - 30, 70.0)]
    claude_worker._write_usage(usage_example)
    return claude_worker


NOW = 1_000_000.0

# --- New tests for rolling window and usage ----------------------------------

def test_idle_and_paused_time_accrues_no_usage(guard):
    """Verify that time outside model invocation does not increase usage."""
    initial_usage = claude_worker._current_usage_total(NOW)
    # Simulate idle time
    time.sleep(0.1)
    usage_after_idle = claude_worker._current_usage_total(NOW + 0.1)
    assert usage_after_idle == initial_usage, "Idle time increased usage"

def test_usage_older_than_rolling_window_is_purged(guard, monkeypatch):
    """Verify that usage outside of the rolling window is excluded."""
    monkeypatch.setattr(guard, "_process_usage_window", [(NOW - 60, 25.0)])
    total_usage = guard._current_usage_total(NOW)
    assert total_usage == 0.0, "Outdated usage was not purged from the rolling window"

def test_a_corrupt_usage_file_does_not_hold_off(guard, monkeypatch, tmp_path):
    """Verify behavior with a corrupt usage file."""
    monkeypatch.setattr(guard, "USAGE_PATH", tmp_path / "corrupt_usage")
    tmp_path.joinpath("corrupt_usage").write_text("not-a-json", encoding="utf-8")

    # Act: Check if the system starts with new usage
    total_usage = guard._current_usage_total(NOW)
    assert total_usage == 0.0, "Non-zero total usage despite corrupt usage file (should default to 0)"

    # No hold-off should still be in place
    reason = guard.rate_limit_reason(now=NOW)
    assert reason is None, f"Unexpected hold-off state: {reason}"

# --- Tripping ---------------------------------------------------------------


def test_a_fresh_worker_is_not_held_off(guard):
    assert guard.rate_limit_reason(now=NOW) is None


def test_crossing_the_window_starts_a_hold_off(guard, monkeypatch):
    monkeypatch.setattr(
        guard, "_process_usage_window", [(NOW - 200.0, 130.0)]
    )
    guard._write_usage(guard._process_usage_window)

    reason = guard.rate_limit_reason(now=NOW)

    assert reason is not None
    assert "holding off" in reason
    assert guard.RATELIMIT_PATH.exists()


def test_the_deadline_is_recorded_on_disk(guard, monkeypatch):
    """On disk, not in memory: restarting must not clear a hold-off.

    Restarting a process to escape a rate limit is exactly what should not
    work, and an in-memory deadline would make it work.
    """
    monkeypatch.setattr(
        guard, "_process_usage_window", [(NOW - 200.0, 130.0)]
    )
    guard._write_usage(guard._process_usage_window)
    guard.rate_limit_reason(now=NOW)

    recorded = float(guard.RATELIMIT_PATH.read_text(encoding="utf-8"))

    assert recorded == pytest.approx(NOW + 50.0, abs=1)


def test_a_hold_off_survives_a_restart(guard, monkeypatch):
    """Simulated by resetting the usage baseline, which is what a restart does."""
    guard.RATELIMIT_PATH.write_text(str(NOW + 50.0), encoding="utf-8")
    monkeypatch.setattr(guard, "_process_usage_window", [])

    assert guard.rate_limit_reason(now=NOW) is not None


# --- Releasing --------------------------------------------------------------


def test_the_hold_off_ends_by_itself(guard):
    """The property the old guard did not have, and the reason for this file."""
    guard.RATELIMIT_PATH.write_text(str(NOW), encoding="utf-8")

    assert guard.rate_limit_reason(now=NOW + 1) is None
    assert not guard.RATELIMIT_PATH.exists()


def test_releasing_restarts_the_window_rather_than_tripping_again(guard, monkeypatch):
    """Without this the worker trips on its very next check, forever.

    The uptime that caused the hold-off is still on the clock when it ends, so
    a release that did not reset the baseline would immediately re-trip and the
    worker would never accept work again.
    """
    monkeypatch.setattr(guard, "_process_usage_window", [(NOW - 5000.0, 0.0)])
    guard.RATELIMIT_PATH.write_text(str(NOW), encoding="utf-8")

    assert guard.rate_limit_reason(now=NOW + 1) is None
    # The very next check must also pass.
    assert guard.rate_limit_reason(now=NOW + 2) is None


def test_a_hold_off_still_active_is_reported_with_time_remaining(guard):
    guard.RATELIMIT_PATH.write_text(str(NOW + 600.0), encoding="utf-8")

    reason = guard.rate_limit_reason(now=NOW)

    assert "remaining" in reason


# --- Failing open rather than wedging ---------------------------------------


@pytest.mark.parametrize("junk", ["", "   ", "not-a-number", "1e"])
def test_an_unparseable_deadline_does_not_hold_forever(guard, junk):
    """A file nothing can read must not stop this worker permanently.

    The asymmetry against the pause flag is deliberate. An unreadable pause
    fails closed, because a missed pause lets work start that an operator
    believed was held. An unreadable rate file fails open, because the worst
    case is spending against a limit the provider itself will enforce, and the
    alternative is a worker that can never run again.
    """
    guard.RATELIMIT_PATH.write_text(junk, encoding="utf-8")

    assert guard.rate_limit_reason(now=NOW) is None


# --- No provider call while guarded -----------------------------------------


def test_the_guard_is_consulted_before_any_claim(monkeypatch, control):
    """A guarded worker must take no activation at all.

    Claiming and then declining consumes work it already knew it would not do,
    and the task then waits out a whole lease to find out.
    """
    import controller_client  # noqa: F401
    from test_worker_controller_source import StubQueue, run_loop

    monkeypatch.setattr(
        claude_worker, "RATELIMIT_PATH", control.CONTROL_DIR / "rl"
    )
    (control.CONTROL_DIR).mkdir(parents=True, exist_ok=True)
    (control.CONTROL_DIR / "rl").write_text(str(time.time() + 3600), encoding="utf-8")

    activation = {
        "activation_id": "act-1", "task_id": "T-1", "task": "do a thing",
        "issued_by": "controller", "source": "controller",
    }
    queue = StubQueue([activation])

    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=3)

    assert queue.claims == 0, "a guarded worker asked for work"
    assert invocations == [], "a guarded worker called the model"
    assert queue.pending == [activation], "the activation was consumed"

