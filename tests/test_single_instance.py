"""One worker per identity, and a lock that a crash cannot wedge.

Four Gemini workers were found alive at once on 2026-09-09, left behind by
launchers whose supervisor was killed without killing the python child. They
did no damage: an activation is claimed atomically, so duplicates poll and find
nothing. But that is a guarantee about the controller, not about the host --
duplicates authenticate, poll, and on a per-token provider a duplicate that
does claim something spends money. Worse, they make "exactly one model call"
unmeasurable, and that is the measurement every live run rests on.

The other half matters as much: a lock that survives a crash and refuses to let
anything start again turns one bad shutdown into an outage. So the stale case
gets as many tests as the contended one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import swarm_control


@pytest.fixture
def lockdir(tmp_path):
    return tmp_path


def lock(identity, directory):
    return swarm_control.SingleInstance(identity, directory)


# --- The contended case -----------------------------------------------------


@pytest.fixture
def live_pid():
    """A real, running process that is not this one.

    A second SingleInstance inside the test process would share this process's
    pid and be allowed through by design, so it cannot exercise the contended
    case at all. Spawning something is the only way to have a pid that is
    genuinely alive and genuinely somebody else.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        yield child.pid
    finally:
        child.kill()
        child.wait(timeout=10)


def test_a_second_worker_for_the_same_identity_is_refused(lockdir, live_pid):
    (lockdir / "gemini.pid").write_text(str(live_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()


def test_the_refusal_names_the_pid_and_the_file(lockdir, live_pid):
    """An operator has to be able to act on it without guessing."""
    (lockdir / "gemini.pid").write_text(str(live_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning) as caught:
        lock("gemini", lockdir).acquire()

    message = str(caught.value)
    assert str(live_pid) in message
    assert "gemini.pid" in message


def test_the_lock_is_not_stolen_from_a_live_holder(lockdir, live_pid):
    """The refusal must leave the file pointing at the process still running."""
    (lockdir / "gemini.pid").write_text(str(live_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()

    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(live_pid)


def test_different_identities_do_not_block_each_other(lockdir):
    """Three workers on one host is the design, not the problem."""
    lock("claudecode", lockdir).acquire()
    lock("gemini", lockdir).acquire()
    lock("chatgpt", lockdir).acquire()

    # No exception is the assertion.
    assert (lockdir / "gemini.pid").exists()


def test_reacquiring_in_the_same_process_is_not_a_conflict(lockdir):
    """Otherwise a restart inside one process would deadlock itself."""
    holder = lock("gemini", lockdir)
    holder.acquire()
    holder.acquire()


# --- The stale case ---------------------------------------------------------


def test_a_lock_held_by_a_dead_process_is_taken_over(lockdir):
    """A crash must not require manual cleanup before anything can run.

    Pid 2**31 - 1 is chosen because it is above every plausible live pid on
    both platforms, so this asserts the takeover rather than accidentally
    testing against a real process.
    """
    (lockdir / "gemini.pid").write_text(str(2 ** 31 - 1), encoding="utf-8")

    lock("gemini", lockdir).acquire()

    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(os.getpid())


@pytest.mark.parametrize("content", ["", "   ", "not-a-pid", "12x34", "-1", "0"])
def test_an_unreadable_lock_is_not_a_permanent_one(lockdir, content):
    """A lock nothing can clear is worse than no lock.

    Unreadable content is treated as no holder. The alternative is a worker
    that can never start again because something once wrote junk to a file.
    """
    (lockdir / "gemini.pid").write_text(content, encoding="utf-8")

    lock("gemini", lockdir).acquire()

    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(os.getpid())


def test_a_missing_lock_directory_is_created(lockdir):
    nested = lockdir / "does" / "not" / "exist"
    lock("gemini", nested).acquire()

    assert (nested / "gemini.pid").exists()


# --- Release ----------------------------------------------------------------


def test_releasing_lets_the_next_worker_start(lockdir):
    first = lock("gemini", lockdir)
    first.acquire()
    first.release()

    lock("gemini", lockdir).acquire()


def test_releasing_a_lock_we_do_not_hold_leaves_it_alone(lockdir):
    """A worker must not be able to unlock somebody else on the way out.

    The exiting process is not necessarily the holder -- it may have failed to
    acquire in the first place -- and deleting the file regardless would let a
    third worker in beside the one still running.
    """
    (lockdir / "gemini.pid").write_text(str(2 ** 31 - 1), encoding="utf-8")
    other = lock("gemini", lockdir)
    other.release()

    assert (lockdir / "gemini.pid").exists()


# --- pid_is_alive -----------------------------------------------------------


def test_this_process_is_alive():
    assert swarm_control.pid_is_alive(os.getpid()) is True


def test_an_implausible_pid_is_not_alive():
    assert swarm_control.pid_is_alive(2 ** 31 - 1) is False


@pytest.mark.parametrize("pid", [0, -1, -99999])
def test_a_nonsense_pid_is_not_alive(pid):
    assert swarm_control.pid_is_alive(pid) is False


# --- Identifying the process behind a pid -----------------------------------
#
# `pid_is_alive` answers "is something running under this number", which is the
# right question before starting beside it and the wrong one before killing it.
# A worker that died without releasing leaves its number in the lock file, the
# operating system hands that number to something else, and the check passes on
# a process the swarm has never met. These cover the difference.


def test_a_process_reports_the_command_line_it_was_started_with():
    command = swarm_control.process_command_line(os.getpid())

    assert command is not None
    assert Path(sys.executable).name.lower() in command.lower()


def test_a_spawned_process_is_identifiable_by_its_command_line(live_pid):
    """The property a shutdown relies on: the pid can be checked, not trusted."""
    command = swarm_control.process_command_line(live_pid)

    assert command is not None
    assert "time.sleep" in command


def test_a_dead_pid_has_no_command_line():
    assert swarm_control.process_command_line(2 ** 31 - 1) is None


@pytest.mark.parametrize("pid", [0, -1, -99999])
def test_a_nonsense_pid_has_no_command_line(pid):
    assert swarm_control.process_command_line(pid) is None


# --- Stopping a process this one did not spawn -------------------------------


def test_terminate_pid_stops_a_real_process(live_pid):
    """`Popen.terminate` is unavailable for a worker somebody else started."""
    assert swarm_control.pid_is_alive(live_pid) is True

    assert swarm_control.terminate_pid(live_pid, timeout=30.0) is True
    assert swarm_control.pid_is_alive(live_pid) is False


def test_terminate_pid_is_satisfied_by_a_process_that_is_already_gone():
    """Nothing to stop is the outcome asked for, not a failure."""
    assert swarm_control.terminate_pid(2 ** 31 - 1) is True
