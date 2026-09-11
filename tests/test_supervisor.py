"""The runtime that keeps itself alive.

Everything the controller needs already worked; all of it ran only while
somebody was typing. These pin the properties that make the difference between
a swarm that works and a swarm that keeps working.

Each is a way the loop can fail quietly. A duplicate worker claims activations
for an identity that believes it is alone. An unbounded restart spins on a
missing credential and fills a disk. A pause that tears the runtime down needs
a person to bring it back, which is what a pause is meant to avoid. A shutdown
that signals and forgets leaves workers polling while the operator believes
they stopped.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

import supervisor
import swarm_control


class FakeProcess:
    """A child whose liveness the test decides."""

    def __init__(self, pid=4242, alive=True):
        self.pid = pid
        self._alive = alive
        self.terminated = False
        self.killed = False
        self.waited = False
        self.returncode = None

    def poll(self):
        return None if self._alive else (self.returncode or 0)

    def terminate(self):
        self.terminated = True
        self._alive = False
        self.returncode = -15

    def kill(self):
        self.killed = True
        self._alive = False
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode

    def die(self, code=1):
        self._alive = False
        self.returncode = code


@pytest.fixture
def control_dir(tmp_path, monkeypatch):
    """An isolated control directory, so locks and pauses do not leak."""
    monkeypatch.setattr(swarm_control, "CONTROL_DIR", tmp_path)
    monkeypatch.setattr(swarm_control, "PAUSE_PATH", tmp_path / "PAUSED")
    return tmp_path


@pytest.fixture
def spawned(monkeypatch):
    """Records every spawn and hands back a process the test controls."""
    made = []

    def fake_popen(argv, **kwargs):
        process = FakeProcess(pid=5000 + len(made))
        made.append({"argv": argv, "kwargs": kwargs, "process": process})
        return process

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    return made


class Controller:
    """A stand-in controller that counts what it was asked."""

    def __init__(self, advance=None, sweep=None, fail=False):
        self.calls = []
        self.fail = fail
        self._advance = advance if advance is not None else []
        self._sweep = sweep if sweep is not None else []

    def post(self, url, auth=None, timeout=None):
        self.calls.append(url)

        if self.fail:
            raise OSError("connection refused")

        body = ({"considered": self._advance} if "advance" in url
                else {"reclaimed": self._sweep})

        return type("Response", (), {
            "status_code": 200, "text": "", "json": lambda self=None: body,
        })()


def build(control_dir, spawned, controller=None, **kw):
    args = {
        "repo": Path("."), "python": sys.executable,
        "controller_url": "http://controller", "admin_secret": "s",
        "interval": 0.0,
        "requests_module": controller or Controller(),
    }
    args.update(kw)
    return supervisor.Supervisor(**args)


# --- It starts what it supervises -------------------------------------------


def test_it_starts_every_worker(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    started = {Path(entry["argv"][1]).name for entry in spawned}

    assert started == set(supervisor.WORKERS.values())


def test_each_child_is_told_which_identity_it_is(control_dir, spawned):
    """Bound from the environment the supervisor sets, never inferred."""
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    identities = {e["kwargs"]["env"]["AGENT_IDENTITY"] for e in spawned}

    assert identities == set(supervisor.WORKERS)


def test_children_take_work_from_the_controller_not_from_chat(
    control_dir, spawned
):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert all(
        e["kwargs"]["env"]["ACTIVATION_SOURCE"] == "controller"
        for e in spawned
    )


# --- Duplicate prevention ----------------------------------------------------


def test_a_running_worker_is_not_started_again(control_dir, spawned):
    """The ordinary case, every tick, forever."""
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.tick(now=101.0)
    sup.tick(now=102.0)

    assert len(spawned) == len(supervisor.WORKERS)


def test_a_worker_holding_the_lock_elsewhere_is_left_alone(
    control_dir, spawned, monkeypatch
):
    """A worker an operator started, or one an earlier supervisor left behind.

    Spawning beside it would give one identity two claimants, each believing
    it is alone.
    """
    lock = swarm_control.SingleInstance("gemini", directory=control_dir)
    lock.path.write_text(str(9999), encoding="utf-8")
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda pid: pid == 9999)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    started = {e["kwargs"]["env"]["AGENT_IDENTITY"] for e in spawned}

    assert "gemini" not in started
    assert started == set(supervisor.WORKERS) - {"gemini"}


def test_a_stale_lock_does_not_block_a_start(control_dir, spawned, monkeypatch):
    """Refusing to start after a crash would turn one bad shutdown into an
    outage."""
    lock = swarm_control.SingleInstance("gemini", directory=control_dir)
    lock.path.write_text(str(9999), encoding="utf-8")
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda pid: False)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert "gemini" in {e["kwargs"]["env"]["AGENT_IDENTITY"] for e in spawned}


# --- Restart recovery and bounded backoff ------------------------------------


def test_a_crashed_worker_is_restarted(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.children["chatgpt"].process.die()

    sup.tick(now=100.0)   # notices the exit, sets the backoff
    sup.tick(now=200.0)   # past it

    chatgpt = [e for e in spawned
               if e["kwargs"]["env"]["AGENT_IDENTITY"] == "chatgpt"]

    assert len(chatgpt) == 2
    assert sup.children["chatgpt"].restarts == 1


def test_the_restart_waits_for_its_backoff(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.children["chatgpt"].process.die()
    sup.tick(now=100.0)

    sup.tick(now=100.0 + supervisor.BACKOFF_FLOOR - 1)

    chatgpt = [e for e in spawned
               if e["kwargs"]["env"]["AGENT_IDENTITY"] == "chatgpt"]

    assert len(chatgpt) == 1


def test_repeated_crashes_back_off_exponentially(control_dir, spawned):
    """A worker that dies on startup dies again immediately. Restarting
    instantly turns one missing credential into a spin."""
    sup = build(control_dir, spawned)
    child = sup.children["chatgpt"]
    seen = []
    now = 100.0

    for _ in range(5):
        sup.tick(now=now)
        if child.process is not None:
            child.process.die()
        sup.tick(now=now)
        seen.append(child.backoff)
        now += child.backoff

    assert seen == sorted(seen)
    assert seen[1] > seen[0]


def test_the_backoff_has_a_ceiling(control_dir, spawned):
    """A worker broken for an hour should still be retried: the fix is often
    somebody setting a variable, and they should not have to restart this to
    have it noticed."""
    sup = build(control_dir, spawned)
    child = sup.children["chatgpt"]
    now = 100.0

    for _ in range(30):
        sup.tick(now=now)
        if child.process is not None:
            child.process.die()
        sup.tick(now=now)
        now += child.backoff

    assert child.backoff == supervisor.BACKOFF_CEILING


def test_a_worker_that_stayed_up_gets_its_backoff_forgiven(
    control_dir, spawned
):
    """A crash after an hour is a different event from a crash after a second,
    and carrying the old delay over would punish the wrong one."""
    sup = build(control_dir, spawned)
    child = sup.children["chatgpt"]

    sup.tick(now=100.0)
    child.process.die()
    sup.tick(now=100.0)
    assert child.backoff > supervisor.BACKOFF_FLOOR

    sup.tick(now=100.0 + child.backoff)
    child.process.die()
    sup.tick(now=100.0 + child.backoff + supervisor.BACKOFF_RESET_AFTER + 1)

    assert child.backoff == supervisor.BACKOFF_FLOOR


def test_one_broken_worker_does_not_delay_the_others(control_dir, spawned):
    """The backoff is per identity."""
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.children["chatgpt"].process.die()
    sup.tick(now=100.0)

    assert sup.children["chatgpt"].not_before > 100.0
    assert sup.children["gemini"].not_before == 0.0
    assert sup.children["gemini"].running()


# --- Pause -------------------------------------------------------------------


def test_a_pause_stops_advancement_without_stopping_the_runtime(
    control_dir, spawned
):
    """A pause is an operator saying "stop starting work", not "tear down the
    runtime". Coming back is then a file deletion, not a restart."""
    controller = Controller()
    sup = build(control_dir, spawned, controller=controller)
    sup.tick(now=100.0)
    assert controller.calls

    controller.calls.clear()
    swarm_control.engage_pause("testing")
    sup.tick(now=200.0)

    assert controller.calls == []
    assert all(child.running() for child in sup.children.values())


def test_a_pause_does_not_start_new_workers(control_dir, spawned):
    swarm_control.engage_pause("testing")
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert spawned == []


def test_releasing_a_pause_resumes_without_a_restart(control_dir, spawned):
    controller = Controller()
    sup = build(control_dir, spawned, controller=controller)
    swarm_control.engage_pause("testing")
    sup.tick(now=100.0)
    assert controller.calls == []

    swarm_control.release_pause()
    sup.tick(now=200.0)

    assert controller.calls


# --- Idle costs nothing ------------------------------------------------------


def test_an_empty_queue_produces_no_model_call_and_no_message(
    control_dir, spawned
):
    """The supervisor calls two controller routes and nothing else. It has no
    model client and no hub client; reaching either would be an import it does
    not make."""
    controller = Controller(advance=[], sweep=[])
    sup = build(control_dir, spawned, controller=controller)

    for tick in range(5):
        sup.tick(now=100.0 + tick)

    assert all(
        "/controller/tasks/advance" in url
        or "/controller/activations/sweep" in url
        for url in controller.calls
    ), controller.calls


def test_the_supervisor_imports_no_model_sdk():
    """Structural, and worth asserting: the guarantee is that this process
    cannot call a model, not that it currently does not."""
    source = Path(supervisor.__file__).read_text(encoding="utf-8")

    for forbidden in ("import openai", "from openai", "google.genai",
                      "anthropic"):
        assert forbidden not in source


# --- Controller connectivity -------------------------------------------------


def test_an_unreachable_controller_is_survived(control_dir, spawned, caplog):
    """Briefly unreachable is ordinary on a home network, and exiting on it
    would need a person to restart the thing that exists to avoid that."""
    sup = build(control_dir, spawned, controller=Controller(fail=True))

    sup.tick(now=100.0)
    sup.tick(now=200.0)

    assert all(child.running() for child in sup.children.values())


def test_connectivity_failures_are_logged(control_dir, spawned, caplog):
    sup = build(control_dir, spawned, controller=Controller(fail=True))

    with caplog.at_level("WARNING"):
        sup.tick(now=100.0)

    assert any("unreachable" in r.message for r in caplog.records)


# --- What it reports ---------------------------------------------------------


def test_an_issued_activation_is_logged(control_dir, spawned, caplog):
    controller = Controller(advance=[
        {"task_id": "T-1", "state": "READY_REVIEW", "stage": "review",
         "issued": True, "agent": "gemini"},
    ])
    sup = build(control_dir, spawned, controller=controller)

    with caplog.at_level("INFO"):
        sup.tick(now=100.0)

    assert any("activation issued: T-1" in r.message for r in caplog.records)


def test_a_sweep_result_is_logged(control_dir, spawned, caplog):
    controller = Controller(sweep=[
        {"task_id": "T-1", "activation_id": "abcdef123456", "stage": "review",
         "reason": "lease_expired", "recovery": "lease_expired"},
    ])
    sup = build(control_dir, spawned, controller=controller)

    with caplog.at_level("WARNING"):
        sup.tick(now=100.0)

    assert any("swept T-1" in r.message for r in caplog.records)


def test_a_restart_is_logged(control_dir, spawned, caplog):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.children["chatgpt"].process.die()

    with caplog.at_level("WARNING"):
        sup.tick(now=100.0)

    assert any("chatgpt exited" in r.message for r in caplog.records)


def test_status_reports_every_worker(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    status = sup.status()

    assert set(status["workers"]) == set(supervisor.WORKERS)
    assert all(w["running"] for w in status["workers"].values())
    assert status["paused"] is False


# --- Shutdown ----------------------------------------------------------------


def test_shutdown_terminates_the_actual_processes(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    sup.shutdown()

    assert all(entry["process"].terminated for entry in spawned)
    assert all(entry["process"].waited for entry in spawned)


def test_shutdown_leaves_no_worker_running(control_dir, spawned):
    """A supervisor that exits while its workers keep polling is worse than
    one that never started."""
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    sup.shutdown()

    assert not any(child.running() for child in sup.children.values())
    assert all(w["running"] is False for w in sup.status()["workers"].values())


def test_a_worker_that_ignores_terminate_is_killed(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    stubborn = spawned[0]["process"]

    def refuse(timeout=None):
        if not stubborn.killed:
            raise subprocess.TimeoutExpired("worker", timeout or 0)
        return -9

    stubborn.terminate = lambda: None
    stubborn.wait = refuse

    sup.shutdown()

    assert stubborn.killed


# --- One supervisor per machine ----------------------------------------------


def test_a_second_supervisor_refuses_to_start(control_dir, monkeypatch):
    lock = swarm_control.SingleInstance("supervisor", directory=control_dir)
    lock.path.write_text(str(4321), encoding="utf-8")
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda pid: pid == 4321)

    second = swarm_control.SingleInstance("supervisor", directory=control_dir)

    with pytest.raises(swarm_control.AlreadyRunning):
        second.acquire()


# --- Each worker gets its own credential -------------------------------------


def test_each_worker_is_given_its_own_hub_secret(control_dir, spawned, monkeypatch):
    """Every worker reads HUB_SECRET and each authenticates as a different
    component, so passing the supervisor's admin secret through would have all
    three presenting the wrong credential."""
    monkeypatch.setenv("HUB_SECRET", "admin-secret")
    monkeypatch.setenv("CHATGPT_HUB_SECRET", "chatgpt-secret")
    monkeypatch.setenv("GEMINI_HUB_SECRET", "gemini-secret")
    monkeypatch.setenv("CLAUDECODE_HUB_SECRET", "claudecode-secret")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    got = {
        e["kwargs"]["env"]["AGENT_IDENTITY"]: e["kwargs"]["env"]["HUB_SECRET"]
        for e in spawned
    }

    assert got == {
        "chatgpt": "chatgpt-secret",
        "gemini": "gemini-secret",
        "claudecode": "claudecode-secret",
    }


def test_a_missing_credential_is_not_substituted(control_dir, spawned, monkeypatch):
    """A worker with no credential says so; one with the wrong credential gets
    a 401 it cannot explain."""
    monkeypatch.setenv("HUB_SECRET", "admin-secret")
    monkeypatch.delenv("GEMINI_HUB_SECRET", raising=False)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    gemini = next(e for e in spawned
                  if e["kwargs"]["env"]["AGENT_IDENTITY"] == "gemini")

    assert "HUB_SECRET" not in gemini["kwargs"]["env"]
