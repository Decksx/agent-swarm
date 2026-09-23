"""Integration waits for the candidate's CI instead of racing it (#32, part B).

With publication automatic, a candidate's pull request opens when it is
submitted and CI starts then -- `pytest-unit` takes six to eleven minutes. Review
takes seconds, so integration is issued while the checks are still running.
The integrator refused on "not completed", which sent a good candidate back to
CHANGES_REQUESTED for being quick.

`await_ci` waits, within a bound, and renews the lease while it does. These
drive it with a scripted `gh` and a fake clock, so the minutes cost nothing
and every sleep and heartbeat is counted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

import integrator
from integrator import Evidence, IntegrationRefused

CANDIDATE = "a" * 40
TARGET = "b" * 40
MERGED = "c" * 40
REQUIRED = ("ci:pytest-unit", "ci:pytest-bypass")
# The real one, kept before any test replaces it with a stub.
AWAIT_CI = integrator.await_ci


def run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status,
            "conclusion": conclusion if status == "completed" else None, "id": 1}


GREEN = [run("pytest-unit"), run("pytest-bypass")]
RUNNING = [run("pytest-unit", "in_progress"), run("pytest-bypass")]


@pytest.fixture
def ci(monkeypatch):
    """Scripted check-run reads, a fake clock, and a record of every wait.

    `script` is consumed one read per poll; the last entry repeats. An entry
    is a list of runs, or an int exit code for a failed read.
    """
    state = {"now": 0.0, "sleeps": [], "reads": [], "beats": 0, "script": []}

    def fake_gh(*args):
        state["reads"].append(args)
        index = min(len(state["reads"]) - 1, len(state["script"]) - 1)
        entry = state["script"][index]

        if isinstance(entry, int):
            return subprocess.CompletedProcess(args, entry, "", "HTTP 502")

        out = "\n".join(json.dumps(r) for r in entry)
        return subprocess.CompletedProcess(args, 0, out, "")

    def fake_sleep(seconds):
        # A wait with no working bound would spin forever on a fake clock;
        # this makes that a failure instead of a hung suite.
        assert len(state["sleeps"]) < 500, "the wait never ended"
        state["sleeps"].append(seconds)
        state["now"] += seconds

    def beat():
        state["beats"] += 1

    monkeypatch.setattr(integrator, "_gh", fake_gh)
    monkeypatch.setattr(integrator, "_sleep", fake_sleep)
    monkeypatch.setattr(integrator, "_clock", lambda: state["now"])
    state["beat"] = beat
    return state


def wait(ci, *script, required=REQUIRED, seconds=1500.0, poll=30.0):
    ci["script"] = list(script)
    integrator.await_ci(
        CANDIDATE, repo_slug="o/r", required=required, wait_seconds=seconds,
        poll_seconds=poll, heartbeat=ci["beat"],
    )


# --- Finishing ---------------------------------------------------------------


def test_finished_ci_returns_without_waiting(ci):
    wait(ci, GREEN)

    assert ci["sleeps"] == [] and ci["beats"] == 0


def test_running_ci_is_waited_for(ci):
    wait(ci, RUNNING, RUNNING, GREEN)

    assert ci["sleeps"] == [30.0, 30.0]
    assert len(ci["reads"]) == 3


def test_every_read_is_for_the_exact_commit(ci):
    wait(ci, RUNNING, GREEN)

    assert all(CANDIDATE in " ".join(args) for args in ci["reads"])


def test_a_required_suite_not_yet_reported_is_waited_for(ci):
    wait(ci, [run("pytest-bypass")], GREEN)

    assert len(ci["sleeps"]) == 1


def test_no_checks_at_all_is_not_finished(ci):
    """CI that has not registered yet is not CI that passed."""
    wait(ci, [], [], GREEN, required=())

    assert len(ci["sleeps"]) == 2


@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_a_clean_non_success_conclusion_ends_the_wait(ci, conclusion):
    """Ended, not accepted: `check_evidence` still judges a skipped suite."""
    wait(ci, [run("pytest-unit"), run("pytest-bypass", conclusion=conclusion)])

    assert ci["sleeps"] == []


# --- Refusing ----------------------------------------------------------------


@pytest.mark.parametrize("conclusion", [
    "failure", "cancelled", "timed_out", "action_required", "startup_failure",
    "stale", "",
])
def test_a_red_check_refuses_at_once_and_names_itself(ci, conclusion):
    with pytest.raises(IntegrationRefused, match="finished red") as refused:
        wait(ci, [run("pytest-unit", "in_progress"),
                  run("pytest-bypass", conclusion=conclusion)])

    assert "ci:pytest-bypass" in str(refused.value)
    assert ci["sleeps"] == []


def test_a_wait_that_runs_out_refuses_and_says_what_was_outstanding(ci):
    with pytest.raises(IntegrationRefused, match="did not finish within 100s") as refused:
        wait(ci, [run("pytest-unit", "queued")], seconds=100.0)

    message = str(refused.value)
    assert "ci:pytest-unit" in message
    assert "ci:pytest-bypass" in message
    assert "Nothing was merged" in message


def test_the_wait_is_bounded_by_its_limit_not_by_the_poll(ci):
    with pytest.raises(IntegrationRefused):
        wait(ci, RUNNING, seconds=100.0, poll=30.0)

    assert sum(ci["sleeps"]) == pytest.approx(100.0)
    assert ci["sleeps"] == [30.0, 30.0, 30.0, 10.0]


def test_a_failed_read_is_retried_rather_than_treated_as_a_verdict(ci):
    wait(ci, 1, GREEN)

    assert len(ci["sleeps"]) == 1


def test_reads_that_keep_failing_are_named_when_the_wait_runs_out(ci):
    with pytest.raises(IntegrationRefused, match="last read failed") as refused:
        wait(ci, 1, seconds=60.0)

    assert "HTTP 502" in str(refused.value)


# --- The lease ---------------------------------------------------------------


def test_the_lease_is_renewed_before_every_sleep(ci):
    wait(ci, RUNNING, RUNNING, RUNNING, GREEN)

    assert ci["beats"] == len(ci["sleeps"]) == 3


def test_no_sleep_is_longer_than_the_poll_interval(ci):
    wait(ci, *([RUNNING] * 20), GREEN, poll=45.0)

    assert max(ci["sleeps"]) <= 45.0


# --- Where the wait sits in run_integration -----------------------------------


def stub_integration(monkeypatch, order):
    def step(name, value=None):
        def record(*a, **kw):
            order.append(name)
            return value
        return record

    monkeypatch.setattr(integrator, "find_pull_request", step("pr", 91))
    monkeypatch.setattr(integrator, "await_ci", step("await_ci"))
    monkeypatch.setattr(integrator, "pin_target", step("pin", TARGET))
    monkeypatch.setattr(integrator, "ci_evidence", step("evidence", (
        Evidence(name="ci:pytest-unit", command="c", exit_code=0, passed=1),)))
    monkeypatch.setattr(integrator, "check_evidence", step("check_evidence"))
    monkeypatch.setattr(integrator, "check_pr", step("check_pr", {}))
    monkeypatch.setattr(integrator, "check_target_unmoved", step("unmoved", TARGET))
    monkeypatch.setattr(integrator, "_git", lambda repo, *a:
                        subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(integrator, "build_merge", step("merge", MERGED))
    for name in ("push_if_target_unmoved", "verify_landed",
                 "check_merge_parents", "check_tree_identical"):
        monkeypatch.setattr(integrator, name, step(name))


def integrate(**kw):
    return integrator.run_integration(
        {"task_id": "T-1", "state": "INTEGRATING",
         "approved_candidate_sha": CANDIDATE},
        repo="/r", target_ref="refs/heads/main", branch="task/T-1-a1",
        repo_slug="o/r", work_root="/w", required_suites=REQUIRED, **kw)


def test_the_wait_comes_after_the_pr_and_before_the_target_is_pinned(monkeypatch):
    order = []
    stub_integration(monkeypatch, order)

    integrate(ci_wait_seconds=1500)

    assert order[:4] == ["pr", "await_ci", "pin", "evidence"]


def test_no_wait_configured_means_no_wait(monkeypatch):
    order = []
    stub_integration(monkeypatch, order)

    integrate()

    assert "await_ci" not in order


def test_a_refused_wait_merges_nothing(monkeypatch):
    order = []
    stub_integration(monkeypatch, order)

    def refuse(*a, **kw):
        raise IntegrationRefused("CI did not finish")

    monkeypatch.setattr(integrator, "await_ci", refuse)

    with pytest.raises(IntegrationRefused):
        integrate(ci_wait_seconds=1500)

    assert "merge" not in order and "pin" not in order


def test_the_wait_is_handed_the_suites_and_the_heartbeat(monkeypatch):
    stub_integration(monkeypatch, [])
    seen = {}
    monkeypatch.setattr(integrator, "await_ci",
                        lambda sha, **kw: seen.update(kw, sha=sha))
    beat = object()

    integrate(ci_wait_seconds=900, ci_poll_seconds=20, heartbeat=beat)

    assert seen["sha"] == CANDIDATE
    assert seen["required"] == REQUIRED
    assert (seen["wait_seconds"], seen["poll_seconds"]) == (900, 20)
    assert seen["heartbeat"] is beat


def test_ci_that_finishes_during_the_wait_integrates(monkeypatch, ci):
    """The whole path: running twice, then green, then the merge."""
    order = []
    stub_integration(monkeypatch, order)
    monkeypatch.setattr(integrator, "await_ci", AWAIT_CI)
    ci["script"] = [RUNNING, RUNNING, GREEN]

    record = integrate(ci_wait_seconds=1500, heartbeat=ci["beat"])

    assert record["merge_sha"] == MERGED
    assert ci["beats"] == 2
    assert "merge" in order


# --- claude_integration configures it -----------------------------------------


@pytest.fixture
def integrating(monkeypatch):
    for name, value in (
        ("INTEGRATION_TARGET_REF", "refs/heads/main"),
        ("INTEGRATION_REPO_SLUG", "owner/repo"),
        ("INTEGRATION_WORK_ROOT", "C:/work"),
        ("INTEGRATION_REQUIRED_SUITES", "ci:pytest-unit,ci:pytest-bypass"),
    ):
        monkeypatch.setenv(name, value)

    for name in ("INTEGRATION_CI_WAIT_SECONDS", "INTEGRATION_CI_POLL_SECONDS",
                 "INTEGRATION_LEASE_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    calls = []
    stub = types.ModuleType("integrator")

    class Refused(Exception):
        pass

    def run_integration(task_record, **kwargs):
        calls.append(kwargs)
        kwargs["heartbeat"]()
        return {"candidate_sha": "1" * 40, "merge_sha": "2" * 40,
                "target_ref": kwargs["target_ref"]}

    stub.IntegrationRefused = Refused
    stub.IntegrationUnverifiable = type("IntegrationUnverifiable", (Exception,), {})
    stub.run_integration = run_integration
    monkeypatch.setitem(sys.modules, "integrator", stub)

    # Repository selection has its own tests (test_integration_repo.py). Here
    # only the filesystem and git checks are stubbed; the rule that an
    # activation must name its repository stays real (#78).
    import claude_integration
    monkeypatch.setattr(claude_integration.Path, "is_dir", lambda self: True)
    monkeypatch.setattr(claude_integration, "_git_succeeds", lambda *a: True)

    activation = {
        "activation_id": "act-1", "task_id": "T-1", "stage": "integrate",
        "expected_branch": "task/T-1-a1",
        "repo_location": "C:/repo",
        "task_record": {"task_id": "T-1", "state": "INTEGRATING"},
    }
    return activation, calls


class Queue:
    def __init__(self):
        self.reports = []
        self.beats = []

    def report_integration(self, activation_id, *, outcome, payload):
        self.reports.append((activation_id, outcome, payload))

    def heartbeat(self, activation_id, lease_seconds):
        self.beats.append((activation_id, lease_seconds))


def execute(activation):
    import claude_integration

    queue = Queue()
    claude_integration.execute_integration(activation, queue, actor="claudecode")
    return queue


def test_the_integrator_waits_by_default(integrating):
    activation, calls = integrating
    queue = execute(activation)

    assert calls[0]["ci_wait_seconds"] == 1500
    assert calls[0]["ci_poll_seconds"] == 30
    assert queue.beats == [("act-1", 900)]
    assert queue.reports[0][1] == "integrated"


def test_the_wait_is_configurable(integrating, monkeypatch):
    activation, calls = integrating
    monkeypatch.setenv("INTEGRATION_CI_WAIT_SECONDS", "600")
    monkeypatch.setenv("INTEGRATION_CI_POLL_SECONDS", "15")
    monkeypatch.setenv("INTEGRATION_LEASE_SECONDS", "300")

    queue = execute(activation)

    assert (calls[0]["ci_wait_seconds"], calls[0]["ci_poll_seconds"]) == (600, 15)
    assert queue.beats == [("act-1", 300)]


@pytest.mark.parametrize("name,value", [
    ("INTEGRATION_CI_WAIT_SECONDS", "twenty minutes"),
    ("INTEGRATION_CI_WAIT_SECONDS", "-1"),
    ("INTEGRATION_CI_POLL_SECONDS", "0"),
    ("INTEGRATION_CI_POLL_SECONDS", "900"),
    ("INTEGRATION_LEASE_SECONDS", "30"),
])
def test_an_unusable_wait_setting_is_refused_before_anything(
    integrating, monkeypatch, name, value
):
    activation, calls = integrating
    monkeypatch.setenv(name, value)

    queue = execute(activation)

    assert calls == []
    assert queue.reports[0][1] == "blocked"
    assert "INTEGRATION_" in queue.reports[0][2]["reason"]
