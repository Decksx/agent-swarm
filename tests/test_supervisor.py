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

import os
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
    control_dir, spawned, host
):
    """A worker an operator started, or one an earlier supervisor left behind.

    Spawning beside it would give one identity two claimants, each believing
    it is alone.
    """
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    started = {e["kwargs"]["env"]["AGENT_IDENTITY"] for e in spawned}

    assert "gemini" not in started
    assert started == set(supervisor.WORKERS) - {"gemini"}


def test_a_worker_that_cannot_be_identified_is_left_alone(
    control_dir, spawned, host
):
    """Cannot tell is not the same as no worker there.

    A command line this cannot read may belong to the running worker, and
    starting a second one on that guess is the duplicate the lock exists to
    prevent. The cost of being wrong the other way is one worker not started
    and reported, which an operator can see and act on.
    """
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")
    host.command_lines[9999] = None

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert "gemini" not in {e["kwargs"]["env"]["AGENT_IDENTITY"] for e in spawned}


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


# --- Shutdown is requested by a flag, not a signal ---------------------------
#
# The unit tests called `shutdown()` directly and passed, and the first live
# stop still left three workers polling: `taskkill` without /F posts WM_CLOSE,
# which a background console process ignores, and /F terminates without running
# any handler. The operator was told the swarm had stopped and it had not.
#
# A file is checked rather than delivered, so it cannot be missed.


def test_a_stop_flag_ends_the_loop(control_dir, spawned):
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    assert not sup.stopping

    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")
    sup.tick(now=101.0)

    assert sup.stopping is True


def test_a_stop_flag_stops_before_starting_anything(control_dir, spawned):
    """So a stop racing a restart does not spawn a worker on the way out."""
    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")
    sup = build(control_dir, spawned)

    sup.tick(now=100.0)

    assert spawned == []


def test_a_stop_flag_stops_advancing(control_dir, spawned):
    controller = Controller()
    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")
    sup = build(control_dir, spawned, controller=controller)

    sup.tick(now=100.0)

    assert controller.calls == []


def test_the_flag_is_cleared_so_the_next_start_is_not_stopped(
    control_dir, spawned
):
    sup = build(control_dir, spawned)
    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")

    sup.clear_stop_request()

    assert not (control_dir / supervisor.STOP_FILENAME).exists()
    assert sup.stop_requested() is False


def test_the_run_loop_shuts_down_and_clears_on_the_flag(control_dir, spawned):
    """The whole path the operator actually takes, rather than shutdown()
    called directly -- which is what passed while the live stop failed."""
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    assert all(child.running() for child in sup.children.values())

    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")
    sup.tick(now=101.0)
    sup.shutdown()
    sup.clear_stop_request()

    assert not any(child.running() for child in sup.children.values())
    assert all(entry["process"].terminated for entry in spawned)
    assert not (control_dir / supervisor.STOP_FILENAME).exists()


# --- A stop that fails must not report success -------------------------------
#
# `Child.stop` cleared its process handle whether or not the process died, and
# `running()` asks that handle -- so every stop looked successful to the only
# check that ran afterwards. `shutdown` then logged `all workers stopped` over
# a worker that was still polling, which is the failure the flag-based stop was
# supposed to have ended.


class Unstoppable(FakeProcess):
    """A child that survives terminate and kill. Real enough: a handle the OS
    will not let this process touch behaves exactly like this."""

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("worker", timeout or 0)


@pytest.fixture
def survivor(monkeypatch):
    """Spawns one worker that cannot be stopped, and two ordinary ones."""
    made = []

    def fake_popen(argv, **kwargs):
        kind = Unstoppable if not made else FakeProcess
        process = kind(pid=6000 + len(made))
        made.append({"argv": argv, "kwargs": kwargs, "process": process})
        return process

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    return made


def test_a_stop_that_did_not_stop_the_process_says_so(control_dir, survivor):
    sup = build(control_dir, survivor)
    sup.tick(now=100.0)

    child = next(c for c in sup.children.values()
                 if c.process is survivor[0]["process"])

    assert child.stop(timeout=0.0) is False
    assert child.running() is True


def test_a_surviving_worker_is_still_reported_as_running(control_dir, survivor):
    """The handle is the only remaining way to ask about the process, so a
    failed stop has to keep it."""
    sup = build(control_dir, survivor)
    sup.tick(now=100.0)

    sup.shutdown()

    assert any(child.running() for child in sup.children.values())
    assert any(w["running"] for w in sup.status()["workers"].values())


def test_shutdown_counts_the_workers_that_survived_it(control_dir, survivor):
    sup = build(control_dir, survivor)
    sup.tick(now=100.0)

    assert sup.shutdown() == 1


def test_shutdown_does_not_claim_success_over_a_surviving_worker(
    control_dir, survivor, caplog
):
    sup = build(control_dir, survivor)
    sup.tick(now=100.0)

    with caplog.at_level("INFO", logger="supervisor"):
        sup.shutdown()

    messages = [record.getMessage() for record in caplog.records]

    assert any("still running after shutdown" in m for m in messages)
    assert not any("all workers stopped" in m for m in messages)


def test_the_run_loop_exits_nonzero_when_a_worker_survives(
    control_dir, survivor, monkeypatch
):
    """An operator reads the control script and the control script reads this."""
    monkeypatch.setattr(supervisor.time, "sleep", lambda _seconds: None)
    sup = build(control_dir, survivor)
    sup.tick(now=100.0)

    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")

    assert sup.run() == 1


def test_the_run_loop_exits_zero_when_every_worker_stopped(
    control_dir, spawned, monkeypatch
):
    monkeypatch.setattr(supervisor.time, "sleep", lambda _seconds: None)
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    (control_dir / supervisor.STOP_FILENAME).write_text("stop", encoding="utf-8")

    assert sup.run() == 0


# --- Shutdown leaves zero workers, including ones it did not start ------------
#
# `start` leaves an adopted, manually started or orphaned worker alone on
# purpose: two claimants for one identity is worse than one nobody is watching.
# That reasoning does not survive the operator asking for zero workers. The
# graceful path used to stop only this supervisor's own children, and
# `swarm_ctl stop` reached for the lock files only when the supervisor itself
# timed out -- so an ordinary, successful stop left an adopted worker polling.


@pytest.fixture
def host(monkeypatch):
    """A set of live pids the test controls, and the kills aimed at them."""

    class Host:
        def __init__(self):
            self.live = set()
            self.killed = []
            self.command_lines = {}

        def alive(self, pid):
            return pid in self.live

        def command_line(self, pid):
            return self.command_lines.get(pid)

        def arguments(self, pid):
            """Split by the real splitter, so these exercise it rather than
            standing in for it."""
            command = self.command_lines.get(pid)

            if command is None:
                return None

            return swarm_control.split_command_line(command) or None

        def terminate(self, pid, timeout=20.0):
            self.killed.append(pid)
            self.live.discard(pid)
            return True

    state = Host()
    monkeypatch.setattr(swarm_control, "pid_is_alive", state.alive)
    monkeypatch.setattr(swarm_control, "process_command_line", state.command_line)
    monkeypatch.setattr(swarm_control, "process_arguments", state.arguments)
    monkeypatch.setattr(swarm_control, "terminate_pid", state.terminate)
    return state


def adopt(control_dir, host, identity, pid, command_line):
    """A worker for `identity` that this supervisor did not start."""
    swarm_control.SingleInstance(identity, directory=control_dir).path.write_text(
        str(pid), encoding="utf-8",
    )
    host.live.add(pid)
    host.command_lines[pid] = command_line


def test_shutdown_stops_a_worker_it_did_not_start(control_dir, spawned, host):
    adopt(control_dir, host, "gemini", 9999,
          r"C:\Python311\python.exe C:\gitgent-swarm\gemini_worker.py")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 0
    assert host.killed == [9999]


def test_a_manually_started_worker_is_stopped_too(control_dir, spawned, host):
    """`worker_ctl.sh` and `start_workers.bat` launch with a bare script name
    from the repository, so requiring a path would refuse to stop exactly the
    workers this is for."""
    adopt(control_dir, host, "chatgpt", 7777, "python chatgpt_worker.py")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    sup.shutdown()

    assert host.killed == [7777]


def test_every_adopted_identity_is_stopped(control_dir, spawned, host):
    adopt(control_dir, host, "gemini", 111, "python gemini_worker.py")
    adopt(control_dir, host, "chatgpt", 222, "python chatgpt_worker.py")
    adopt(control_dir, host, "claudecode", 333, "python claude_worker.py")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 0
    assert sorted(host.killed) == [111, 222, 333]


def test_an_identity_not_supervised_is_not_touched(control_dir, spawned, host):
    """`--only gemini` means this supervisor is responsible for gemini."""
    adopt(control_dir, host, "chatgpt", 7777, "python chatgpt_worker.py")

    sup = build(control_dir, spawned, identities=["gemini"])
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


# --- and never kills a process it cannot identify ----------------------------
#
# A lock file records the pid of a worker that was alive when it was written.
# Pids are reused, so by the time anything reads it the number may belong to
# something the swarm has never met -- and `pid_is_alive` cheerfully confirms
# that it is running. Six of these lock files were committed to git, which
# would have handed a second checkout numbers naming processes on a machine it
# had never started anything on.


def test_a_reused_pid_is_not_killed(control_dir, spawned, host):
    """The number is live and in the lock file, and it is not a worker."""
    adopt(control_dir, host, "gemini", 9999,
          r"C:\Windows\System32\svchost.exe -k netsvcs")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


def test_a_pid_holding_the_wrong_identitys_script_is_not_killed(
    control_dir, spawned, host
):
    """Each identity stops its own worker, not whatever python is running."""
    adopt(control_dir, host, "gemini", 9999, "python chatgpt_worker.py")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


def test_a_pid_whose_command_line_cannot_be_read_is_not_killed(
    control_dir, spawned, host
):
    """Unreadable means no. A process this cannot identify is one it must not
    terminate, however much the operator wants a clean shutdown."""
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")
    host.command_lines[9999] = None

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


def test_a_worker_that_could_not_be_stopped_is_reported_as_remaining(
    control_dir, spawned, host
):
    """Refusing to kill it is right; calling the shutdown clean is not.

    The uncertain case, not the recycled one. A lock whose pid is definitely
    running something else is a stale lock and no worker at all; a lock whose
    pid cannot be read may still be the worker, and a shutdown that cannot
    account for it has not reached zero.
    """
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")
    host.command_lines[9999] = None

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 1


def test_a_recycled_pid_in_a_lock_is_not_a_remaining_worker(
    control_dir, spawned, host
):
    """The other half of the same judgement. Nothing was left running, so
    reporting a survivor would fail a shutdown that succeeded."""
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 0
    assert host.killed == []


def test_an_unstoppable_adopted_worker_is_not_reported_as_stopped(
    control_dir, spawned, host, caplog
):
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")
    host.command_lines[9999] = None
    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    with caplog.at_level("INFO", logger="supervisor"):
        sup.shutdown()

    messages = [record.getMessage() for record in caplog.records]

    assert any("9999" in m for m in messages)
    assert not any("all workers stopped" in m for m in messages)


def test_a_stale_lock_is_not_a_remaining_worker(control_dir, spawned, host):
    """A dead pid in a lock file is a crash's leftovers, not a process."""
    swarm_control.SingleInstance("gemini", directory=control_dir).path.write_text(
        str(9999), encoding="utf-8",
    )

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 0
    assert host.killed == []


# --- The force path uses the same evidence -----------------------------------


def test_reap_stops_an_orphan_without_supervising(control_dir, spawned, host):
    """A supervisor that had to be force-killed never ran its own shutdown, so
    its children outlive it holding the locks."""
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")

    assert supervisor.main(["supervisor.py", "--reap"]) == 0
    assert host.killed == [9999]
    assert spawned == []


def test_reap_refuses_to_kill_what_it_cannot_identify(control_dir, spawned, host):
    adopt(control_dir, host, "gemini", 9999, "python gemini_worker.py")
    host.command_lines[9999] = None

    assert supervisor.main(["supervisor.py", "--reap"]) == 1
    assert host.killed == []


def test_reap_treats_a_recycled_pid_as_nothing_to_reap(control_dir, spawned, host):
    """It is not a worker, so there is nothing to stop and nothing to report
    -- and the process it does name is left running."""
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")

    assert supervisor.main(["supervisor.py", "--reap"]) == 0
    assert host.killed == []
    assert 9999 in host.live


def test_reap_reports_success_when_nothing_is_running(control_dir, spawned, host):
    assert supervisor.main(["supervisor.py", "--reap"]) == 0


def test_reap_needs_no_credential_and_no_controller(control_dir, spawned, host,
                                                    monkeypatch):
    """It runs after a force-kill, when nothing else is guaranteed to work."""
    monkeypatch.delenv("HUB_SECRET", raising=False)

    assert supervisor.main(["supervisor.py", "--reap"]) == 0


# --- The name has to be the script, not a substring of the command line ------
#
# `gemini_worker.py` is a substring of `backup_gemini_worker.py`, of
# `gemini_worker.py.bak`, and of any command that merely mentions the name.
# A containment test authorizes a force-kill on all three, which is the same
# "the number turned up somewhere" reasoning that made a committed lock file
# dangerous. What is asked instead is which script the process is running.


NEAR_MISSES = [
    "python backup_gemini_worker.py",
    "python gemini_worker.py.bak",
    "python gemini_worker.pyc",
    "python my_gemini_worker.py",
    "python gemini_worker.py.old",
    "python gemini_worker.python",
    r"C:\Python311\python.exe C:\backups\copy_of_gemini_worker.py",
]


@pytest.mark.parametrize("command", NEAR_MISSES)
def test_a_near_matching_script_name_is_not_killed(
    control_dir, spawned, host, command
):
    adopt(control_dir, host, "gemini", 9999, command)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


INCIDENTAL_MENTIONS = [
    'python other_worker.py --log gemini_worker.py',
    'python -c "print(\'gemini_worker.py\')"',
    'python editor.py gemini_worker.py',
    'grep -r gemini_worker.py .',
    'python -m pytest tests/test_gemini_worker.py',
    r'notepad.exe C:\gitgent-swarm\gemini_worker.py',
]


@pytest.mark.parametrize("command", INCIDENTAL_MENTIONS)
def test_a_command_that_merely_mentions_the_script_is_not_killed(
    control_dir, spawned, host, command
):
    """An editor with the file open is not a worker, and neither is a test run
    named after one."""
    adopt(control_dir, host, "gemini", 9999, command)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


REAL_LAUNCHES = [
    # How the supervisor spawns one.
    r"C:\Python311\python.exe C:\gitgent-swarm\gemini_worker.py",
    # How worker_ctl.sh and start_workers.bat launch one.
    "python gemini_worker.py",
    # A path with a space in it, which only survives correct quoting.
    r'"C:\Program Files\Python311\python.exe" "C:\my repo\gemini_worker.py"',
    # POSIX, for the half of this that is not Windows-specific.
    "/usr/bin/python3 /home/david/agent-swarm/gemini_worker.py",
]


@pytest.mark.parametrize("command", REAL_LAUNCHES)
def test_a_real_worker_is_still_stopped(control_dir, spawned, host, command):
    """The tightening must not refuse the launches the runtime actually uses."""
    adopt(control_dir, host, "gemini", 9999, command)

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 0
    assert host.killed == [9999]


def test_a_process_running_no_script_at_all_is_not_killed(
    control_dir, spawned, host
):
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


def test_an_empty_command_line_is_not_an_identification(
    control_dir, spawned, host
):
    adopt(control_dir, host, "gemini", 9999, "   ")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)
    sup.shutdown()

    assert host.killed == []


# --- The supervisor's own pid is checked before it is treated as one ----------
#
# The last number still acted on unchecked. `swarm_ctl stop` read
# supervisor.pid, confirmed only that something was alive under it, and
# eventually sent `taskkill /F`. A supervisor that died without clearing its
# file leaves that number for the operating system to hand to anything, and
# the kill would have landed there.
#
# `--identify` is what the control script asks instead, so these are the shell
# path's tests as much as this file's.


def identify(name, pid):
    return supervisor.main(["supervisor.py", "--identify", name, str(pid)])


def test_a_live_supervisor_is_identified(control_dir, host):
    host.live.add(4321)
    host.command_lines[4321] = (
        r"C:\Python311\python C:\gitgent-swarm\supervisor.py "
        r"--url http://192.168.42.50:8050"
    )

    assert identify("supervisor", 4321) == 0


def test_a_recycled_supervisor_pid_is_not_the_supervisor(control_dir, host):
    """The number is live and it is in supervisor.pid. It is not a supervisor,
    and a nonzero answer is what keeps `taskkill /F` away from it."""
    host.live.add(4321)
    host.command_lines[4321] = r"C:\Windows\System32\svchost.exe -k netsvcs"

    assert identify("supervisor", 4321) == 1


@pytest.mark.parametrize("command", [
    r"C:\Windows\explorer.exe",
    "python -m editor supervisor.py",
    "python -c supervisor.py",
    "python-helper.exe supervisor.py",
    "notepad.exe supervisor.py",
    'python "supervisor.py',
    "python",
])
def test_no_other_process_can_pass_as_the_supervisor(control_dir, host, command):
    host.live.add(4321)
    host.command_lines[4321] = command

    assert identify("supervisor", 4321) == 1


def test_a_dead_supervisor_pid_is_not_the_supervisor(control_dir, host):
    """A stale file, which is the ordinary case after a crash."""
    assert identify("supervisor", 4321) == 1


def test_an_unreadable_command_line_is_not_the_supervisor(control_dir, host):
    host.live.add(4321)
    host.command_lines[4321] = None

    assert identify("supervisor", 4321) == 1


def test_a_worker_pid_is_not_the_supervisor(control_dir, host):
    """Each name identifies its own script, so one cannot stand in for another."""
    host.live.add(4321)
    host.command_lines[4321] = "python gemini_worker.py"

    assert identify("supervisor", 4321) == 1
    assert identify("gemini", 4321) == 0
    assert identify("chatgpt", 4321) == 1


def test_an_unknown_name_is_refused_rather_than_guessed(control_dir, host):
    host.live.add(4321)
    host.command_lines[4321] = "python gemini_worker.py"

    assert identify("nonesuch", 4321) == 2


@pytest.mark.parametrize("raw", ["", "  ", "not-a-pid", "12x34"])
def test_a_pid_that_is_not_a_number_is_refused(control_dir, host, raw):
    assert supervisor.main(
        ["supervisor.py", "--identify", "supervisor", raw]
    ) == 2


def test_identify_needs_no_credential_and_no_controller(
    control_dir, host, monkeypatch
):
    """`status` and `stop` both ask it, and neither is guaranteed a
    controller or a secret."""
    monkeypatch.delenv("HUB_SECRET", raising=False)
    host.live.add(4321)
    host.command_lines[4321] = "python gemini_worker.py"

    assert identify("gemini", 4321) == 0


# --- Proof of life, so a death is noticed (#46) ------------------------------
#
# The supervisor and all three workers vanished on 2026-09-15T17:20:48 and
# nothing noticed until an operator looked, three days later. The scheduled
# task that was supposed to cover it ran `start` once at logon: it returned 0
# four seconds after backgrounding the supervisor, so Task Scheduler recorded
# success and abandoned what it had spawned, and its RestartCount -- which
# restarts a task that *fails* -- never applied.
#
# What was missing is a liveness signal a watcher can act on. `supervisor.pid`
# cannot be it: it records a number that was right when it was written, which
# is the whole reason `identifies_script` exists.


def heartbeat(control_dir):
    return supervisor.read_heartbeat()


def test_a_tick_records_that_this_supervisor_is_alive(control_dir, spawned):
    build(control_dir, spawned).tick(now=1000.0)
    record = heartbeat(control_dir)

    assert record["pid"] == os.getpid()
    assert record["at"] == 1000.0


def test_a_paused_supervisor_still_says_it_is_alive(control_dir, spawned):
    """A pause idles the swarm; it does not stop the supervisor.

    If the heartbeat stopped with the work, `ensure` would start a second
    supervisor on top of a perfectly healthy paused one.
    """
    swarm_control.PAUSE_PATH.write_text("paused for a deploy", encoding="utf-8")
    build(control_dir, spawned).tick(now=2000.0)

    assert heartbeat(control_dir)["at"] == 2000.0


def test_a_stopping_supervisor_still_says_it_is_alive(control_dir, spawned):
    """It is alive until it has finished shutting down, and says so."""
    (swarm_control.CONTROL_DIR / supervisor.STOP_FILENAME).write_text(
        "stop", encoding="utf-8")
    build(control_dir, spawned).tick(now=2500.0)

    assert heartbeat(control_dir)["at"] == 2500.0


def test_the_heartbeat_leaves_no_partial_file(control_dir, spawned):
    """A completed write tidies up after itself."""
    build(control_dir, spawned).tick(now=3000.0)
    left = sorted(p.name for p in swarm_control.CONTROL_DIR.glob("*.tmp"))

    assert left == []


def test_a_half_written_heartbeat_never_replaces_a_good_one(
    control_dir, monkeypatch
):
    """The reason it is written to a temporary name and replaced.

    Anything reading this decides whether to start a second supervisor. A
    reader that caught the file mid-write would find no usable heartbeat and
    conclude the live supervisor was gone -- so a write that dies partway
    must leave the last good answer standing, not a truncated one.
    """
    supervisor.write_heartbeat(777, 5000.0)
    write_text = supervisor.Path.write_text

    def dies_partway(self, data, **kwargs):
        write_text(self, data[: len(data) // 2], **kwargs)
        raise OSError("interrupted partway through")

    monkeypatch.setattr(supervisor.Path, "write_text", dies_partway)
    supervisor.write_heartbeat(888, 6000.0)

    assert supervisor.read_heartbeat()["pid"] == 777


def test_a_heartbeat_that_cannot_be_written_does_not_end_the_runtime(
    control_dir, spawned, monkeypatch
):
    """A supervisor that cannot write its heartbeat is still supervising."""
    def refuse(*args, **kwargs):
        raise OSError("disk is full")

    monkeypatch.setattr(supervisor.Path, "write_text", refuse)
    build(control_dir, spawned).tick(now=3500.0)  # must not raise

    assert supervisor.read_heartbeat() is None


# --- Reading it back ---------------------------------------------------------


def live_supervisor(monkeypatch, pid):
    """Make `pid` look like a running supervisor to the liveness check.

    `script_identity`, not `identifies_script`: since #52 the liveness check
    asks the tri-state question, and patching the boolean wrapper would leave
    the real one to answer for itself -- which for a pid nothing spawned is
    None, the "cannot tell" branch. These tests would then pass through a
    branch they are not about.
    """
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: p == pid)
    monkeypatch.setattr(
        supervisor, "script_identity", lambda p, script: p == pid)


def test_a_fresh_heartbeat_from_a_live_supervisor_is_alive(
    control_dir, monkeypatch
):
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, 5000.0)

    assert supervisor.supervisor_is_live(now=5010.0) is True


def test_no_heartbeat_at_all_is_not_alive(control_dir):
    assert supervisor.supervisor_is_live(now=5000.0) is False


def test_a_stale_heartbeat_is_not_alive(control_dir, monkeypatch):
    """The wedged case: the process is there and has stopped saying so."""
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, 5000.0)
    late = 5000.0 + supervisor.HEARTBEAT_STALE_SECONDS + 1

    assert supervisor.supervisor_is_live(now=late) is False


def test_a_fresh_heartbeat_naming_a_dead_pid_is_not_alive(
    control_dir, monkeypatch
):
    """What a supervisor killed between ticks leaves behind.

    `script_identity` is made to say yes, so the only thing that can
    produce False here is the liveness check itself. Left to answer for
    itself it would say None anyway, and since #52 that branch reports
    alive -- so the test would pass or fail for the wrong reason.
    """
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: False)
    monkeypatch.setattr(supervisor, "script_identity", lambda p, script: True)
    supervisor.write_heartbeat(777, 5000.0)

    assert supervisor.supervisor_is_live(now=5010.0) is False


def test_a_fresh_heartbeat_naming_a_recycled_pid_is_not_alive(
    control_dir, monkeypatch
):
    """Alive, and read, and not a supervisor. The case the check exists for.

    `script_identity` rather than the boolean wrapper: a *readable* command
    line naming something else is a verdict, and #52 must not have turned it
    into the ambiguity next door.
    """
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: True)
    monkeypatch.setattr(supervisor, "script_identity", lambda p, script: False)
    supervisor.write_heartbeat(777, 5000.0)

    assert supervisor.supervisor_is_live(now=5010.0) is False


@pytest.mark.parametrize("body", [
    "",                       # truncated to nothing
    "{",                      # caught mid-write, had this not been atomic
    '{"at": 1.0}',            # no pid
    '{"pid": "777", "at": 1}',  # a pid that is not a number
    '{"pid": 777}',           # no timestamp
    '{"pid": 777, "at": "soon"}',
    '["pid", 777]',           # not an object at all
])
def test_an_unusable_heartbeat_reads_as_none(control_dir, body):
    supervisor.heartbeat_path().write_text(body, encoding="utf-8")

    assert supervisor.read_heartbeat() is None
    assert supervisor.supervisor_is_live(now=0.0) is False


# --- What `swarm_ctl.sh ensure` asks -----------------------------------------


def liveness():
    return supervisor.main(["supervisor.py", "--liveness"])


def test_liveness_exits_zero_for_a_live_supervisor(control_dir, monkeypatch):
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, time.time())

    assert liveness() == 0


def test_liveness_exits_nonzero_when_there_is_none(control_dir):
    assert liveness() == 1


def test_liveness_exits_nonzero_for_a_stale_heartbeat(control_dir, monkeypatch):
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(
        777, time.time() - supervisor.HEARTBEAT_STALE_SECONDS - 1)

    assert liveness() == 1


def test_liveness_needs_no_credential_and_no_controller(
    control_dir, monkeypatch
):
    """The scheduled task runs it every five minutes; it must not need either."""
    monkeypatch.delenv("HUB_SECRET", raising=False)
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, time.time())

    assert liveness() == 0


def test_liveness_starts_nothing(control_dir, spawned, monkeypatch):
    """It answers a question. `ensure` decides what to do about the answer."""
    monkeypatch.delenv("HUB_SECRET", raising=False)
    liveness()

    assert spawned == []


# --- The reason has to name what failed (#50) --------------------------------
#
# The warning said "heartbeat Ns old (stale past 120s)" whatever had gone
# wrong. When the #48 scheduled task could not reach powershell.exe, the
# identity check answered False and the log blamed a heartbeat that was zero
# seconds old -- sending whoever read it to look at the clock. A diagnostic
# that names the wrong cause is worse than none.


def test_a_live_supervisor_reads_as_alive_and_says_so(control_dir, monkeypatch):
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5010.0)

    assert alive is True
    assert "777" in reason and "10s old" in reason


def test_no_heartbeat_says_there_is_no_heartbeat(control_dir):
    alive, reason = supervisor.liveness(now=5000.0)

    assert alive is False
    assert "no usable heartbeat" in reason
    assert "stale" not in reason


def test_a_stale_heartbeat_says_stale_and_nothing_else(control_dir, monkeypatch):
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, 5000.0)
    late = 5000.0 + supervisor.HEARTBEAT_STALE_SECONDS + 10
    alive, reason = supervisor.liveness(now=late)

    assert alive is False
    assert "past the 120s limit" in reason
    assert "not running" not in reason
    assert "not a supervisor" not in reason


def test_a_dead_pid_says_the_pid_is_dead_not_that_it_is_stale(
    control_dir, monkeypatch
):
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: False)
    monkeypatch.setattr(supervisor, "script_identity", lambda p, script: True)
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5010.0)

    assert alive is False
    assert "is not running" in reason
    assert "past the" not in reason


def test_a_recycled_pid_says_recycled_and_not_that_it_is_stale(
    control_dir, monkeypatch
):
    """Since #52 this reason names only recycling.

    It used to offer "or this host cannot read process command lines" as the
    alternative, because the two were indistinguishable. They are not any
    more: an unreadable command line is its own branch, and it reports alive.
    Leaving the old wording here would describe a case this one no longer is.
    """
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: True)
    monkeypatch.setattr(supervisor, "script_identity", lambda p, script: False)
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5010.0)

    assert alive is False
    assert "the number was recycled" in reason
    assert "past the" not in reason


def test_a_fresh_heartbeat_is_never_described_as_stale(control_dir, monkeypatch):
    """The exact defect: 'heartbeat 0s old (stale past 120s)'."""
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: True)
    monkeypatch.setattr(supervisor, "script_identity", lambda p, script: False)
    supervisor.write_heartbeat(777, 5000.0)
    _, reason = supervisor.liveness(now=5000.0)

    assert "stale" not in reason


def test_supervisor_is_live_still_answers_the_plain_question(
    control_dir, monkeypatch
):
    """Most callers want the answer, not the reason; the old name still works."""
    live_supervisor(monkeypatch, 777)
    supervisor.write_heartbeat(777, 5000.0)

    assert supervisor.supervisor_is_live(now=5010.0) is True
    assert supervisor.supervisor_is_live(
        now=5000.0 + supervisor.HEARTBEAT_STALE_SECONDS + 1) is False


# --- "I could not look" is not "I looked and it is something else" (#52) -----
#
# The #48 scheduled task kept starting a second supervisor against a healthy
# one. Not PATH -- #50 fixed a real latent bug there, but not this. A probe run
# from inside a real scheduled task showed Win32_Process.CommandLine coming
# back EMPTY from a non-interactive security context, while the identical query
# from an interactive session returned the full line. process_arguments
# answered None, identifies_script turned that into False, and `ensure` read
# "not a supervisor" as permission to spawn one.
#
# swarm_control already says None means "cannot tell, so do not act". That is
# right for a kill. `ensure`'s action is a start, and the same ambiguity there
# has the opposite safe answer: with a fresh heartbeat and a live pid, an
# unreadable command line must defer to the heartbeat.


def opaque_command_line(monkeypatch):
    """The condition the scheduled task runs under: alive, and unreadable."""
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: True)
    monkeypatch.setattr(swarm_control, "process_arguments", lambda p: None)


def test_an_unreadable_command_line_is_not_a_verdict(control_dir, monkeypatch):
    opaque_command_line(monkeypatch)

    assert supervisor.script_identity(777, "supervisor.py") is None


def test_a_command_line_naming_something_else_is_a_verdict(
    control_dir, monkeypatch
):
    monkeypatch.setattr(
        swarm_control, "process_arguments", lambda p: ["python", "gemini_worker.py"])

    assert supervisor.script_identity(777, "supervisor.py") is False


def test_a_command_line_naming_the_script_is_a_verdict(control_dir, monkeypatch):
    monkeypatch.setattr(
        swarm_control, "process_arguments", lambda p: ["python", "supervisor.py"])

    assert supervisor.script_identity(777, "supervisor.py") is True


# --- The kill path keeps its strict boolean ----------------------------------


@pytest.mark.parametrize("arguments,identified", [
    (None, False),                             # cannot tell -- never a yes
    (["python", "gemini_worker.py"], False),   # read, and it is not this
    (["python", "supervisor.py"], True),
])
def test_identifies_script_answers_only_true_or_false(
    control_dir, monkeypatch, arguments, identified
):
    """`--identify` feeds `swarm_ctl.sh stop`, which sends taskkill /F. That
    path must not come to rest on None being falsy in Python."""
    monkeypatch.setattr(swarm_control, "process_arguments", lambda p: arguments)
    answer = supervisor.identifies_script(777, "supervisor.py")

    assert answer is identified
    assert isinstance(answer, bool)


# --- What liveness does with each of the three -------------------------------


def test_an_opaque_identity_defers_to_a_fresh_heartbeat(control_dir, monkeypatch):
    """The regression. Before #52 this was False, and `ensure` started a
    second supervisor on top of a healthy one every five minutes."""
    opaque_command_line(monkeypatch)
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5001.0)

    assert alive is True
    assert "could not be read" in reason
    assert "unverified" in reason


def test_an_opaque_identity_does_not_claim_to_have_checked(
    control_dir, monkeypatch
):
    """A log that implied a verified identity would hide the very condition
    that made this take three attempts to find."""
    opaque_command_line(monkeypatch)
    supervisor.write_heartbeat(777, 5000.0)
    _, reason = supervisor.liveness(now=5001.0)
    verified, _ = supervisor.liveness(now=5001.0)

    assert reason != f"supervisor pid 777 heartbeat 1s old"
    assert verified is True


def test_an_opaque_identity_cannot_rescue_a_stale_heartbeat(
    control_dir, monkeypatch
):
    """Deferring to the heartbeat is only defensible while there is one to
    defer to. A supervisor that stopped writing is gone, readable or not."""
    opaque_command_line(monkeypatch)
    supervisor.write_heartbeat(777, 5000.0)
    late = 5000.0 + supervisor.HEARTBEAT_STALE_SECONDS + 1

    assert supervisor.liveness(now=late)[0] is False


def test_an_opaque_identity_cannot_rescue_a_dead_pid(control_dir, monkeypatch):
    """The pid is checked first and is its own fact; nothing about an
    unreadable command line makes a dead process alive."""
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: False)
    monkeypatch.setattr(swarm_control, "process_arguments", lambda p: None)
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5001.0)

    assert alive is False
    assert "is not running" in reason


def test_a_recycled_pid_is_still_refused(control_dir, monkeypatch):
    """The case the identity check exists for has to survive #52: a readable
    command line naming something else is a verdict, not an ambiguity."""
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda p: True)
    monkeypatch.setattr(
        swarm_control, "process_arguments", lambda p: ["python", "gemini_worker.py"])
    supervisor.write_heartbeat(777, 5000.0)
    alive, reason = supervisor.liveness(now=5001.0)

    assert alive is False
    assert "the number was recycled" in reason
    assert "could not be read" not in reason


def test_liveness_exits_zero_for_an_opaque_but_beating_supervisor(
    control_dir, monkeypatch
):
    """What `swarm_ctl.sh ensure` asks, under the scheduled task's own
    conditions. This exit status is the whole point: 1 here is what made the
    task spawn a duplicate."""
    opaque_command_line(monkeypatch)
    supervisor.write_heartbeat(777, time.time())

    assert supervisor.main(["supervisor.py", "--liveness"]) == 0
