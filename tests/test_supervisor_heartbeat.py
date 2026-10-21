"""The heartbeat's rename survives a transient sharing denial (#72).

Kept apart from test_supervisor.py, which is already past the file view
budget.
"""
from __future__ import annotations

import pytest

import supervisor
import swarm_control


@pytest.fixture
def control_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(swarm_control, "CONTROL_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(supervisor.time, "sleep", slept.append)
    return slept


def deny_replace(monkeypatch, times, error=PermissionError):
    """Make the first `times` renames fail with `error`; count every call."""
    real = supervisor.os.replace
    calls = []

    def replace(src, dst):
        calls.append((src, dst))
        if len(calls) <= times:
            raise error(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(supervisor.os, "replace", replace)
    return calls


def test_a_transient_denial_is_retried_and_the_heartbeat_lands(
    control_dir, sleeps, monkeypatch, caplog
):
    supervisor.write_heartbeat(777, 5000.0)
    calls = deny_replace(monkeypatch, times=2)

    supervisor.write_heartbeat(888, 6000.0)

    assert supervisor.read_heartbeat()["pid"] == 888
    assert len(calls) == 3
    assert sleeps == [0.05, 0.1]
    assert "could not write the heartbeat" not in caplog.text
    assert list(control_dir.glob("*.tmp")) == []


def test_the_last_permitted_attempt_can_still_succeed(
    control_dir, sleeps, monkeypatch, caplog
):
    retries = len(supervisor.HEARTBEAT_REPLACE_DELAYS)
    calls = deny_replace(monkeypatch, times=retries)

    supervisor.write_heartbeat(888, 6000.0)

    assert supervisor.read_heartbeat()["pid"] == 888
    assert len(calls) == retries + 1
    assert "could not write the heartbeat" not in caplog.text


def test_a_persistent_denial_is_bounded_warned_and_keeps_the_last_heartbeat(
    control_dir, sleeps, monkeypatch, caplog
):
    supervisor.write_heartbeat(777, 5000.0)
    good = supervisor.heartbeat_path().read_bytes()
    calls = deny_replace(monkeypatch, times=10**6)

    supervisor.write_heartbeat(888, 6000.0)  # must not raise

    retries = len(supervisor.HEARTBEAT_REPLACE_DELAYS)
    assert len(calls) == retries + 1
    assert sleeps == list(supervisor.HEARTBEAT_REPLACE_DELAYS)
    assert sum(sleeps) <= 0.5
    assert supervisor.heartbeat_path().read_bytes() == good
    assert supervisor.read_heartbeat()["pid"] == 777
    assert caplog.text.count("could not write the heartbeat") == 1
    assert "Access is denied" in caplog.text


def test_an_error_other_than_a_sharing_denial_is_not_retried(
    control_dir, sleeps, monkeypatch, caplog
):
    supervisor.write_heartbeat(777, 5000.0)
    calls = deny_replace(monkeypatch, times=1, error=FileNotFoundError)

    supervisor.write_heartbeat(888, 6000.0)

    assert len(calls) == 1
    assert sleeps == []
    assert supervisor.read_heartbeat()["pid"] == 777
    assert caplog.text.count("could not write the heartbeat") == 1
