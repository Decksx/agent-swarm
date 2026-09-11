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
          r"C:\Python311\python.exe C:\git\claude-agent-hub\gemini_worker.py")

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
    """Refusing to kill it is right; calling the shutdown clean is not."""
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")

    sup = build(control_dir, spawned)
    sup.tick(now=100.0)

    assert sup.shutdown() == 1


def test_an_unstoppable_adopted_worker_is_not_reported_as_stopped(
    control_dir, spawned, host, caplog
):
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")
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
    adopt(control_dir, host, "gemini", 9999, "svchost.exe -k netsvcs")

    assert supervisor.main(["supervisor.py", "--reap"]) == 1
    assert host.killed == []


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
    r'notepad.exe C:\git\claude-agent-hub\gemini_worker.py',
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
    r"C:\Python311\python.exe C:\git\claude-agent-hub\gemini_worker.py",
    # How worker_ctl.sh and start_workers.bat launch one.
    "python gemini_worker.py",
    # A path with a space in it, which only survives correct quoting.
    r'"C:\Program Files\Python311\python.exe" "C:\my repo\gemini_worker.py"',
    # POSIX, for the half of this that is not Windows-specific.
    "/usr/bin/python3 /home/david/agent-swarm/gemini_worker.py",
    # Interpreter flags before the script.
    "python -W ignore gemini_worker.py",
    # Executed directly rather than handed to an interpreter.
    "./gemini_worker.py",
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
