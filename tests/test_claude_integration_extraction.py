"""Integration lives in `claude_integration`, and nothing about it moved but the file.

Extracted from `claude_worker` so that module fits the author's file view
(#25). These pin the three things a move like that can quietly break: an
import cycle, the entry point callers and tests use, and where the worker's
identity comes from.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _fresh_import(statement: str) -> subprocess.CompletedProcess:
    """Run an import in a clean interpreter, so no earlier test has warmed it."""
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )


def test_the_extracted_module_does_not_import_the_worker():
    done = _fresh_import(
        "import sys, claude_integration; "
        "assert 'claude_worker' not in sys.modules, 'claude_integration imported claude_worker'"
    )
    assert done.returncode == 0, done.stderr


def test_either_module_imports_first_without_a_cycle():
    for statement in (
        "import claude_worker, claude_integration",
        "import claude_integration, claude_worker",
    ):
        done = _fresh_import(statement)
        assert done.returncode == 0, f"{statement}: {done.stderr}"


def test_the_worker_entry_point_is_still_where_callers_find_it():
    import claude_integration
    import claude_worker

    assert callable(claude_worker.execute_integration)
    assert claude_worker.execute_integration is not claude_integration.execute_integration
    assert claude_integration.log is claude_worker.log


@pytest.fixture
def integrating(monkeypatch):
    """An integrate activation the path accepts, and a stub integrator that records its call."""
    for name, value in (
        ("INTEGRATION_REPO", "C:/repo"),
        ("INTEGRATION_TARGET_REF", "refs/heads/main"),
        ("INTEGRATION_REPO_SLUG", "owner/repo"),
        ("INTEGRATION_WORK_ROOT", "C:/work"),
        ("INTEGRATION_REQUIRED_SUITES", "ci:a,ci:b"),
    ):
        monkeypatch.setenv(name, value)

    calls = []
    stub = types.ModuleType("integrator")

    class IntegrationRefused(Exception):
        pass

    def run_integration(task_record, **kwargs):
        calls.append(kwargs)
        return {"candidate_sha": "1" * 40, "merge_sha": "2" * 40,
                "target_ref": kwargs["target_ref"]}

    stub.IntegrationRefused = IntegrationRefused
    stub.run_integration = run_integration
    monkeypatch.setitem(sys.modules, "integrator", stub)

    activation = {
        "activation_id": "act-1", "task_id": "T-1", "stage": "integrate",
        "expected_branch": "task/T-1-a1",
        "task_record": {"task_id": "T-1", "state": "INTEGRATING"},
    }
    return activation, calls


class Queue:
    def __init__(self):
        self.reports = []

    def report_integration(self, activation_id, *, outcome, payload):
        self.reports.append((activation_id, outcome, payload))


def test_a_patched_worker_identity_reaches_the_integrator(monkeypatch, integrating):
    """Read at call time from `claude_worker`, not captured at import."""
    import claude_worker

    activation, calls = integrating
    monkeypatch.setattr(claude_worker, "AGENT_IDENTITY", "patched-identity")
    queue = Queue()

    claude_worker.execute_integration(activation, queue)

    assert [c["actor"] for c in calls] == ["patched-identity"]
    assert calls[0]["required_suites"] == ["ci:a", "ci:b"]
    assert queue.reports == [("act-1", "integrated", {
        "candidate_sha": "1" * 40, "merge_sha": "2" * 40, "target_ref": "refs/heads/main",
    })]


def test_dispatch_still_reaches_integration_through_the_worker(monkeypatch, integrating):
    """`execute_activation` routes through `claude_worker.execute_integration`."""
    import claude_worker

    activation, calls = integrating
    seen = []
    monkeypatch.setattr(claude_worker, "execute_integration",
                        lambda a, q=None: seen.append(a["activation_id"]))

    claude_worker.execute_activation(None, "claude", activation, Queue())

    assert seen == ["act-1"]
    assert calls == []
