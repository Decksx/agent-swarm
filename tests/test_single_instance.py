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
import time
from pathlib import Path

import pytest

import swarm_control

REPO_ROOT = Path(__file__).resolve().parent.parent


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


@pytest.fixture
def live_worker_pid(tmp_path_factory):
    """A real process that genuinely is a gemini worker.

    Genuine by the only test that decides anything: the script it is running.
    A plain `python -c` sleeper is what a *recycled* pid looks like, so it
    cannot stand in for the contended case any more -- it is the other case.
    """
    directory = tmp_path_factory.mktemp("worker")
    script = directory / "gemini_worker.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    child = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        yield child.pid
    finally:
        child.kill()
        child.wait(timeout=10)


def test_a_second_worker_for_the_same_identity_is_refused(
    lockdir, live_worker_pid
):
    (lockdir / "gemini.pid").write_text(str(live_worker_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()


def test_the_refusal_names_the_pid_and_the_file(lockdir, live_worker_pid):
    """An operator has to be able to act on it without guessing."""
    (lockdir / "gemini.pid").write_text(str(live_worker_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning) as caught:
        lock("gemini", lockdir).acquire()

    message = str(caught.value)
    assert str(live_worker_pid) in message
    assert "gemini.pid" in message


def test_the_lock_is_not_stolen_from_a_live_holder(lockdir, live_worker_pid):
    """The refusal must leave the file pointing at the process still running."""
    (lockdir / "gemini.pid").write_text(str(live_worker_pid), encoding="utf-8")

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()

    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(
        live_worker_pid
    )


# --- The recycled case ------------------------------------------------------
#
# The failure that took an identity out of the swarm on its first live start.
# `chatgpt.pid` held a number from the previous run, Windows reissued it to
# the claudecode worker two seconds earlier, and the chatgpt worker read a
# live pid out of its own lock file and refused to start. Permanently: nothing
# rewrites a lock nobody can take.


def test_a_lock_whose_pid_was_reused_is_taken_over(lockdir, live_pid):
    """`live_pid` is alive and is not a gemini worker, which is precisely what
    a reissued number looks like."""
    (lockdir / "gemini.pid").write_text(str(live_pid), encoding="utf-8")

    lock("gemini", lockdir).acquire()

    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(os.getpid())


def test_taking_over_a_reused_pid_does_not_touch_that_process(lockdir, live_pid):
    """The whole point of reading it rather than trusting it: the stranger
    that inherited the number is somebody else's process."""
    (lockdir / "gemini.pid").write_text(str(live_pid), encoding="utf-8")

    lock("gemini", lockdir).acquire()

    assert swarm_control.pid_is_alive(live_pid) is True


def test_one_identity_does_not_take_over_another_identitys_worker(
    lockdir, live_worker_pid
):
    """A gemini worker in `chatgpt.pid` is a recycled number from chatgpt's
    point of view, and still a running worker from gemini's."""
    (lockdir / "chatgpt.pid").write_text(str(live_worker_pid), encoding="utf-8")
    (lockdir / "gemini.pid").write_text(str(live_worker_pid), encoding="utf-8")

    lock("chatgpt", lockdir).acquire()

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()

    assert swarm_control.pid_is_alive(live_worker_pid) is True


def test_a_supervisor_lock_holding_a_reused_pid_is_taken_over(lockdir, live_pid):
    """`supervisor.pid` goes stale the same way, and locked the supervisor out
    of its own machine for the same reason."""
    (lockdir / "supervisor.pid").write_text(str(live_pid), encoding="utf-8")

    lock("supervisor", lockdir).acquire()

    assert (lockdir / "supervisor.pid").read_text(encoding="utf-8") == str(
        os.getpid()
    )
    assert swarm_control.pid_is_alive(live_pid) is True


def test_a_holder_that_cannot_be_identified_still_blocks(lockdir, monkeypatch):
    """Cannot tell is not evidence of absence.

    A command line that cannot be read may belong to the running worker, and
    taking the lock on that guess is the duplicate this exists to prevent.
    """
    (lockdir / "gemini.pid").write_text(str(9999), encoding="utf-8")
    monkeypatch.setattr(swarm_control, "pid_is_alive", lambda pid: pid == 9999)
    monkeypatch.setattr(swarm_control, "process_arguments", lambda pid: None)

    with pytest.raises(swarm_control.AlreadyRunning):
        lock("gemini", lockdir).acquire()


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


# --- Which script a process is running ---------------------------------------
#
# The question a shutdown actually has to answer before it terminates
# something. "Does the command line contain `gemini_worker.py`" is not that
# question: `backup_gemini_worker.py` contains it, `gemini_worker.py.bak`
# contains it, and so does a text editor with the file open.


def split(command):
    return swarm_control.split_command_line(command)


def test_arguments_are_split_on_whitespace():
    assert split("python gemini_worker.py") == ["python", "gemini_worker.py"]


def test_a_quoted_path_with_a_space_stays_one_argument():
    command = r'"C:\Program Files\Python311\python.exe" "C:\my repo\gemini_worker.py"'

    assert split(command) == [
        r"C:\Program Files\Python311\python.exe",
        r"C:\my repo\gemini_worker.py",
    ]


def test_backslashes_in_a_windows_path_survive_the_split():
    """POSIX rules would read each one as an escape and eat it, which turns
    every Windows path into a different string."""
    command = r"C:\Python311\python.exe C:\gitgent-swarm\gemini_worker.py"

    assert split(command)[-1].endswith("gemini_worker.py")
    assert split(command)[-1].count("\\") >= 2 or "/" in split(command)[-1]


@pytest.mark.parametrize("command", [
    'python "gemini_worker.py',
    "python 'gemini_worker.py",
    'python -c "import x; y(\'gemini_worker.py',
])
def test_a_command_line_that_will_not_parse_is_refused(command):
    """Refused, not split on whitespace.

    The old fallback looked conservative and was not: whitespace-splitting an
    unterminated quote manufactures `'gemini_worker.py` as an argument out of
    text that was never one, and a caller matching whole arguments then finds
    a match nobody wrote. Refusing is the only answer that cannot invent one.
    """
    assert split(command) is None


@pytest.mark.parametrize("command,expected", [
    ("python gemini_worker.py", "gemini_worker.py"),
    (r"C:\Python311\python.exe C:\git\agent-swarm\gemini_worker.py",
     "gemini_worker.py"),
    ("/usr/bin/python3 /home/david/agent-swarm/gemini_worker.py",
     "gemini_worker.py"),
    ("pythonw.exe gemini_worker.py", "gemini_worker.py"),
    ("python3.11 gemini_worker.py", "gemini_worker.py"),
])
def test_the_script_a_python_process_is_running_is_named(command, expected):
    assert swarm_control.running_python_script(split(command)) == expected


@pytest.mark.parametrize("command", [
    # Not a python process at all. Both name the script as a whole argument.
    "grep -r gemini_worker.py .",
    r"notepad.exe C:\git\agent-swarm\gemini_worker.py",
    "code.exe gemini_worker.py",
    "tar -cf backup.tar gemini_worker.py",
    # A python process running no script.
    'python -c "print(1)"',
    "python -m pytest tests/",
    "python",
])
def test_a_process_running_no_python_script_names_none(command):
    assert swarm_control.running_python_script(split(command)) is None


@pytest.mark.parametrize("command,expected", [
    # The script is the first .py after the interpreter. What follows it
    # belongs to the script and says nothing about what is running.
    ("python other_worker.py --log gemini_worker.py", "other_worker.py"),
    ("python editor.py gemini_worker.py", "editor.py"),
])
def test_only_the_script_counts_and_not_its_arguments(command, expected):
    assert swarm_control.running_python_script(split(command)) == expected


@pytest.mark.parametrize("command", [
    "python backup_gemini_worker.py",
    "python my_gemini_worker.py",
    "python gemini_worker2.py",
    r"C:\Python311\python.exe C:\backups\copy_of_gemini_worker.py",
])
def test_a_near_matching_name_is_a_different_script(command):
    """Each of these contains `gemini_worker.py`. None of them is it."""
    running = swarm_control.running_python_script(split(command))

    assert running is not None
    assert running != "gemini_worker.py"


@pytest.mark.parametrize("command", [
    "python gemini_worker.py.bak",
    "python gemini_worker.pyc",
    "python gemini_worker.python",
])
def test_a_name_that_is_not_a_python_file_names_no_script(command):
    """Also a refusal, by a different route: the argument contains the
    script name and is not a script."""
    assert swarm_control.running_python_script(split(command)) is None


def test_this_process_is_running_this_test_file():
    """The whole chain against a real pid: arguments, then the script."""
    arguments = swarm_control.process_arguments(os.getpid())

    assert arguments is not None
    assert Path(sys.executable).name.lower() in arguments[0].lower()


def test_a_dead_pid_has_no_arguments():
    assert swarm_control.process_arguments(2 ** 31 - 1) is None


def test_a_spawned_process_reports_its_arguments(live_pid):
    arguments = swarm_control.process_arguments(live_pid)

    assert arguments is not None
    assert any("time.sleep" in argument for argument in arguments)


# --- Only the launch shapes this repository actually uses ---------------------
#
# A general reading of a python command line has to know which options take a
# value, that `-c` and `-m` end the options and mean no script is being run,
# and what a bare `-` means. Every one it gets wrong is a process somebody is
# authorized to kill. There are four launch shapes here, all of them
# `interpreter script [script arguments]`, so that is all that is recognised.


# Every way this repository starts a python process, verbatim.
REPOSITORY_LAUNCHES = [
    # supervisor.py spawning a worker: [python, str(repo / script)].
    (r"C:\Python311\python.exe C:\gitgent-swarm\gemini_worker.py",
     "gemini_worker.py"),
    # worker_ctl.sh: python "$SCRIPT", from the repository.
    ("python claude_worker.py", "claude_worker.py"),
    # start_workers.bat: python chatgpt_worker.py, from the repository.
    ("python chatgpt_worker.py", "chatgpt_worker.py"),
    # swarm_ctl.sh start: "$PYTHON" "$REPO/supervisor.py" --url ... --log ...
    (r"C:\Python311\python C:\gitgent-swarm\supervisor.py "
     r"--url http://192.168.42.50:8050 --log C:\gitgent-swarm\control\supervisor.log",
     "supervisor.py"),
    # swarm_ctl.sh stop: the reaper.
    (r"C:\Python311\python C:\gitgent-swarm\supervisor.py --reap",
     "supervisor.py"),
    # A python whose own path has a space in it.
    (r'"C:\Program Files\Python311\python.exe" "C:\my repo\gemini_worker.py"',
     "gemini_worker.py"),
]


@pytest.mark.parametrize("command,expected", REPOSITORY_LAUNCHES)
def test_a_real_launch_is_identified(command, expected):
    """The narrowing must not refuse the processes it exists to stop."""
    assert swarm_control.running_python_script(split(command)) == expected


# The forms the review named, and the rest of the family they belong to.
MISIDENTIFIED_FORMS = [
    # -m runs a module. The .py after it is that module's argument.
    "python -m editor gemini_worker.py",
    "python -m http.server gemini_worker.py",
    # -c runs the next argument as source code, whatever it looks like.
    "python -c gemini_worker.py",
    'python -c "import gemini_worker.py"',
    # Begins with "python" and is not python.
    "python-helper.exe gemini_worker.py",
    "python_wrapper.exe gemini_worker.py",
    "pythonista.exe gemini_worker.py",
    "py-spy record -- gemini_worker.py",
    # An interpreter option this repository never uses. Refusing costs a
    # worker left running and reported; accepting costs a wrong kill.
    "python -W ignore gemini_worker.py",
    "python -u gemini_worker.py",
    # No script at all.
    "python",
    "python -i",
]


@pytest.mark.parametrize("command", MISIDENTIFIED_FORMS)
def test_a_form_that_is_not_a_plain_script_launch_is_refused(command):
    assert swarm_control.running_python_script(split(command)) is None


@pytest.mark.parametrize("command", [
    'python "gemini_worker.py',
    "python 'gemini_worker.py",
    'python gemini_worker.py "--flag',
])
def test_a_command_line_that_will_not_parse_identifies_nothing(command):
    """The refusal has to survive the whole chain, not just the splitter."""
    arguments = split(command)

    assert arguments is None
    assert swarm_control.running_python_script(arguments) is None


# --- Acquisition is atomic, because the operating system says so -------------
#
# Reading the pid file, judging its holder, removing a stale one and creating
# the replacement are four filesystem operations, and every gap between them
# is a gap two workers can both walk through. Three versions of this failed
# there. A check-then-write let every racer judge one stale lock and all of
# them write. An exclusive create fixed that and left the clearing step, so
# all of them still removed the lock and one removed the lock another had just
# taken. Comparing the contents before removing looked like it bound the two
# together and did not: the comparison is about a file a racer can replace
# before the removal reaches it.
#
# None of that is visible in a race that happens to come out right, which is
# why these do not race. A worker is parked inside the critical section on
# purpose, and what the other one can and cannot do while it is parked is the
# assertion.


# One racer. Hooks `_holder`, which acquire() calls inside the mutex, so the
# hook is the inside of the critical section -- observable, and pausable.
RACER = '''
import pathlib, sys, time

sys.path.insert(0, sys.argv[1])
import swarm_control

identity, lockdir, markers, name, mode = sys.argv[2:7]
markers = pathlib.Path(markers)
inside = markers / (name + "-entered")
resume = markers / (name + "-continue")
finish = markers / "finish"

real_holder = swarm_control.SingleInstance._holder


def hooked(self):
    inside.write_text("x", encoding="utf-8")

    if mode == "wait":
        while not resume.exists():
            time.sleep(0.01)

    return real_holder(self)


swarm_control.SingleInstance._holder = hooked

try:
    swarm_control.SingleInstance(identity, lockdir).acquire()
except swarm_control.AlreadyRunning:
    print("REFUSED", flush=True)
else:
    print("ACQUIRED", flush=True)

    # Held until the test says otherwise. A winner that exited would leave a
    # genuinely stale lock, and the next racer would be right to take it.
    while not finish.exists():
        time.sleep(0.01)
'''


@pytest.fixture
def racers(lockdir):
    """Starts real gemini workers that contend for one lock."""
    markers = lockdir / "markers"
    markers.mkdir()

    # Named for the identity, so each racer is a process that genuinely is the
    # worker it claims to be and the identity check recognises it.
    script = lockdir / "gemini_worker.py"
    script.write_text(RACER, encoding="utf-8")

    started = []

    def start(name, mode="signal", identity="gemini"):
        child = subprocess.Popen(
            [sys.executable, str(script), str(REPO_ROOT), identity,
             str(lockdir), str(markers), name, mode],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8",
        )
        started.append(child)
        return child

    start.markers = markers
    start.entered = lambda name: (markers / (name + "-entered")).exists()
    start.resume = lambda name: (markers / (name + "-continue")).write_text(
        "x", encoding="utf-8"
    )
    start.finish = lambda: (markers / "finish").write_text("x", encoding="utf-8")

    def await_marker(path, timeout=60.0):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if path.exists():
                return True

            time.sleep(0.01)

        return False

    start.await_marker = await_marker

    try:
        yield start
    finally:
        (markers / "finish").write_text("x", encoding="utf-8")

        for child in started:
            child.kill()
            child.wait(timeout=10)


STALE = str(2 ** 31 - 1)


def test_a_racer_holds_the_section_while_it_replaces_a_stale_lock(
    lockdir, racers
):
    """A is parked inside the critical section; B must not get in.

    Not "B usually loses" -- B cannot begin. The marker B writes is the first
    statement inside the section, so its absence is proof that B reached the
    mutex and stopped there.
    """
    (lockdir / "gemini.pid").write_text(STALE, encoding="utf-8")

    first = racers("A", mode="wait")
    assert racers.await_marker(racers.markers / "A-entered"), "A never entered"

    second = racers("B")

    # Long enough that B would have finished several times over: the section
    # it is waiting on is one file read and one identity check.
    time.sleep(3.0)

    assert not racers.entered("B"), "B entered the section while A held it"
    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == STALE, (
        "B removed or replaced the stale lock while A held the section"
    )

    racers.resume("A")

    assert first.stdout.readline().strip() == "ACQUIRED"
    assert second.stdout.readline().strip() == "REFUSED"


def test_the_second_racer_sees_the_first_as_the_genuine_holder(lockdir, racers):
    """Once B is let in, the lock names a live gemini worker -- so B refuses
    for the right reason, rather than taking over a lock it thinks is stale."""
    (lockdir / "gemini.pid").write_text(STALE, encoding="utf-8")

    first = racers("A", mode="wait")
    racers.await_marker(racers.markers / "A-entered")
    second = racers("B")
    time.sleep(1.0)
    racers.resume("A")

    assert first.stdout.readline().strip() == "ACQUIRED"
    assert second.stdout.readline().strip() == "REFUSED"

    recorded = (lockdir / "gemini.pid").read_text(encoding="utf-8").strip()

    assert recorded == str(first.pid)
    assert swarm_control.pid_is_alive(first.pid) is True


def test_exactly_one_of_many_contenders_acquires(lockdir, racers):
    """Five at once on one stale lock, and the answer does not depend on how
    the scheduler happened to order them."""
    (lockdir / "gemini.pid").write_text(STALE, encoding="utf-8")

    children = [racers(f"R{n}") for n in range(5)]
    outcomes = [child.stdout.readline().strip() for child in children]

    assert outcomes.count("ACQUIRED") == 1, outcomes
    assert outcomes.count("REFUSED") == 4, outcomes


def test_a_crash_inside_the_section_releases_the_mutex(lockdir, racers):
    """The property that makes it safe to hold across a blocking check.

    Both `LockFile` and `flock` attach to the open handle, so a process killed
    rather than shut down has its lock released by the kernel. If they did
    not, one crashed worker would wedge its identity until somebody deleted a
    file -- which is the failure this whole branch exists to end, reintroduced
    one layer down.
    """
    (lockdir / "gemini.pid").write_text(STALE, encoding="utf-8")

    crasher = racers("A", mode="wait")
    assert racers.await_marker(racers.markers / "A-entered"), "A never entered"

    crasher.kill()          # TerminateProcess: no handler, no cleanup
    crasher.wait(timeout=10)

    started = time.monotonic()
    lock("gemini", lockdir).acquire()
    waited = time.monotonic() - started

    assert waited < swarm_control.MUTEX_TIMEOUT / 2, (
        f"waited {waited:.1f}s; the mutex was not released by the kernel"
    )
    assert (lockdir / "gemini.pid").read_text(encoding="utf-8") == str(os.getpid())
