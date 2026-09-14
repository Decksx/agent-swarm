"""The rate guard's logic lives in `claude_rate_guard`; its state stays in `claude_worker`.

Extracted so `claude_worker` fits the author's file view (#25). The guard is
configured by patching `claude_worker` -- in tests, and through the module's
own globals at runtime -- so the move is only safe if every one of those
values is still read when the guard runs, not captured when it was imported.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = 1_000_000.0


def _fresh_import(statement: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )


def test_the_guard_module_does_not_import_the_worker():
    done = _fresh_import(
        "import sys, claude_rate_guard; "
        "assert 'claude_worker' not in sys.modules, 'claude_rate_guard imported claude_worker'"
    )
    assert done.returncode == 0, done.stderr


def test_either_module_imports_first_without_a_cycle():
    for statement in (
        "import claude_worker, claude_rate_guard",
        "import claude_rate_guard, claude_worker",
    ):
        done = _fresh_import(statement)
        assert done.returncode == 0, f"{statement}: {done.stderr}"


def test_the_names_stay_on_the_worker_and_share_its_logger():
    import claude_rate_guard
    import claude_worker

    for name in ("rate_limit_reason", "_read_holdoff", "_read_usage", "_write_usage",
                 "_purge_old_usage", "_current_usage_total", "_record_usage",
                 "_begin_holdoff", "_end_holdoff", "record_rate_limit_alert_sent",
                 "RATELIMIT_PATH", "USAGE_PATH", "RATE_LIMIT_WARN_SECONDS",
                 "RATE_LIMIT_COOLDOWN_SECONDS", "_process_usage_window",
                 "_rate_limit_alert_sent"):
        assert hasattr(claude_worker, name), name
    assert claude_rate_guard.log is claude_worker.log


@pytest.fixture
def worker(tmp_path, monkeypatch):
    import claude_worker

    monkeypatch.setattr(claude_worker, "RATELIMIT_PATH", tmp_path / "first.rl")
    monkeypatch.setattr(claude_worker, "USAGE_PATH", tmp_path / "first.usage")
    monkeypatch.setattr(claude_worker, "RATE_LIMIT_WARN_SECONDS", 100.0)
    monkeypatch.setattr(claude_worker, "RATE_LIMIT_COOLDOWN_SECONDS", 50.0)
    monkeypatch.setattr(claude_worker, "_process_usage_window", [])
    return claude_worker


def test_paths_patched_after_import_are_the_ones_used(worker, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "RATELIMIT_PATH", tmp_path / "second.rl")
    monkeypatch.setattr(worker, "USAGE_PATH", tmp_path / "second.usage")

    worker._record_usage(NOW - 1.0, 150.0)
    assert worker.rate_limit_reason(now=NOW) is not None

    assert (tmp_path / "second.usage").exists() and (tmp_path / "second.rl").exists()
    assert not (tmp_path / "first.usage").exists() and not (tmp_path / "first.rl").exists()


def test_thresholds_patched_after_import_are_the_ones_used(worker, monkeypatch):
    monkeypatch.setattr(worker, "_process_usage_window", [(NOW - 1.0, 150.0)])
    monkeypatch.setattr(worker, "RATE_LIMIT_WARN_SECONDS", 1000.0)
    assert worker.rate_limit_reason(now=NOW) is None

    monkeypatch.setattr(worker, "RATE_LIMIT_WARN_SECONDS", 120.0)
    monkeypatch.setattr(worker, "RATE_LIMIT_COOLDOWN_SECONDS", 7200.0)
    reason = worker.rate_limit_reason(now=NOW)
    assert reason == "worker usage 0.0h reached the 0.0h window; holding off for 2.0h"
    assert float(worker.RATELIMIT_PATH.read_text(encoding="utf-8")) == NOW + 7200.0


def test_the_window_is_read_from_and_stored_back_on_the_worker(worker, monkeypatch):
    patched = [(NOW - 100.0, 5.0), (NOW - 1.0, 7.0)]
    monkeypatch.setattr(worker, "_process_usage_window", patched)

    assert worker._current_usage_total(NOW) == 7.0
    assert worker._process_usage_window == [(NOW - 1.0, 7.0)]

    worker._record_usage(NOW, 3.0)
    assert worker._process_usage_window == [(NOW - 1.0, 7.0), (NOW, 3.0)]
    assert worker._read_usage() == [(NOW - 1.0, 7.0), (NOW, 3.0)]


def test_the_alert_flag_is_still_set_on_the_worker(monkeypatch):
    import claude_worker

    monkeypatch.setattr(claude_worker, "_rate_limit_alert_sent", False)
    claude_worker.record_rate_limit_alert_sent()
    assert claude_worker._rate_limit_alert_sent is True
