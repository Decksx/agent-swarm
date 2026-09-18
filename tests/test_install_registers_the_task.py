"""`install` registers the task it claims to, or fails saying it did not (#48).

`swarm_ctl.sh install` printed

    registered AgentSwarmSupervisor (at logon, rechecked every 5 minutes)

and exited 0 having registered nothing. `Register-ScheduledTask` had thrown
HRESULT 0x80041318 -- the repetition duration was `[TimeSpan]::MaxValue`, which
serialises to P99999999DT23H59M59S and fails Task Scheduler's own XML
validation -- and the success line sat after the command with no error check,
inside a `powershell.exe -Command` block whose failure never reached the
shell's exit status.

The cost was specific: #46 exists so the swarm restarts itself, and the
command that arms that had been reporting success while leaving the old
logon-only task in place. The self-heal was not armed, and the only evidence
against it was a CIM exception printed above a line saying it was.

These register a throwaway task and read back what Task Scheduler actually
stored, because that is the seam that broke. A test that asserted on the text
of the script would have passed against the version that did not work.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
POWERSHELL = shutil.which("powershell") or "powershell.exe"

# Never the real one. Every test here registers and unregisters under this
# name, so a bug in the fixture cannot disturb the task the host runs on.
PROBE_TASK = "AgentSwarmSupervisorTest48"


def powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", script],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )


def _host_registers_tasks() -> bool:
    """Whether this host lets us register a scheduled task at all.

    Probed rather than assumed from the platform: a CI runner may have
    `powershell.exe` and no permission to register anything, and "it is
    Windows" is a guess about why rather than the condition itself.
    """
    if not Path(BASH).exists():
        return False

    probe = powershell(
        f"try {{ "
        f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c echo hi'; "
        f"Register-ScheduledTask -TaskName '{PROBE_TASK}Probe' -Action $a "
        f"-Trigger (New-ScheduledTaskTrigger -AtLogOn) -Force -ErrorAction Stop | Out-Null; "
        f"Unregister-ScheduledTask -TaskName '{PROBE_TASK}Probe' -Confirm:$false; "
        f"Write-Output 'REGISTER_OK' }} catch {{ Write-Output 'REGISTER_NO' }}"
    )

    return "REGISTER_OK" in (probe.stdout or "")


HOST_REGISTERS_TASKS = _host_registers_tasks()

needs_scheduler = pytest.mark.skipif(
    not HOST_REGISTERS_TASKS,
    reason="needs a host where a scheduled task can be registered and removed",
)


STUB_SSH = "#!/usr/bin/env bash\necho -n 'stub-credential'\n"


def sh(path: Path) -> str:
    r"""A Windows path as the shell sees it: C:\git\x -> /c/git/x."""
    text = str(path).replace("\\", "/")

    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]

    return text


def remove_probe_task() -> None:
    powershell(
        f"Unregister-ScheduledTask -TaskName '{PROBE_TASK}' -Confirm:$false "
        f"-ErrorAction SilentlyContinue"
    )


@pytest.fixture
def checkout(tmp_path):
    """A copy of the real control script, with its credential fetch stubbed.

    The task is removed before and after, so a failing test cannot leave one
    behind for the next.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "swarm_ctl.sh", root / "swarm_ctl.sh")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = binaries / "ssh"
    stub.write_text(STUB_SSH, encoding="utf-8", newline="")
    stub.chmod(0o755)

    remove_probe_task()

    try:
        yield root, binaries
    finally:
        remove_probe_task()


def install(checkout, **overrides) -> subprocess.CompletedProcess:
    """Run the real `swarm_ctl.sh install` against the throwaway task name."""
    root, binaries = checkout

    env = dict(os.environ)
    env["PATH"] = str(binaries) + os.pathsep + env["PATH"]
    env["SWARM_CONTROL_DIR"] = str(root / "control")
    env["SWARM_TASK_NAME"] = PROBE_TASK
    env.update({name: str(value) for name, value in overrides.items()})

    return subprocess.run(
        [BASH, sh(root / "swarm_ctl.sh"), "install"],
        cwd=str(root), env=env, capture_output=True,
        encoding="utf-8", errors="replace", timeout=180,
    )


def stored_task() -> dict | None:
    """What Task Scheduler actually holds, or None if it holds nothing."""
    result = powershell(
        f"$t = Get-ScheduledTask -TaskName '{PROBE_TASK}' -ErrorAction SilentlyContinue; "
        f"if (-not $t) {{ Write-Output 'NONE' }} else {{ "
        f"$r = $t.Triggers | Where-Object {{ $_.Repetition.Interval }}; "
        f"@{{ arguments = (($t.Actions | ForEach-Object {{ $_.Arguments }}) -join ' '); "
        f"triggers = @($t.Triggers | ForEach-Object {{ $_.CimClass.CimClassName }}); "
        f"interval = $(if ($r) {{ $r.Repetition.Interval }} else {{ '' }}); "
        f"duration = $(if ($r) {{ $r.Repetition.Duration }} else {{ '' }}); "
        f"restartCount = $t.Settings.RestartCount }} | ConvertTo-Json -Compress }}"
    )
    text = (result.stdout or "").strip()

    return None if text == "NONE" or not text else json.loads(text)


# --- What it registers --------------------------------------------------------


@needs_scheduler
def test_install_registers_a_task_that_runs_ensure(checkout):
    """`start` was the wrong thing to schedule: it returns having abandoned
    what it spawned. The whole of #46 depends on this being `ensure`."""
    finished = install(checkout)
    task = stored_task()

    assert finished.returncode == 0, f"{finished.stdout}\n{finished.stderr}"
    assert task is not None, "install reported success and registered nothing"
    assert "swarm_ctl.sh ensure" in task["arguments"]
    assert "swarm_ctl.sh start" not in task["arguments"]


@needs_scheduler
def test_the_registered_task_actually_repeats(checkout):
    """The defect that mattered: a task with no repetition runs once at logon,
    and nobody logs off."""
    install(checkout)
    task = stored_task()

    assert task["interval"] == "PT5M"
    assert "MSFT_TaskLogonTrigger" in task["triggers"]


@needs_scheduler
def test_the_repetition_duration_is_finite(checkout):
    """`[TimeSpan]::MaxValue` serialises to P99999999DT23H59M59S, which Task
    Scheduler refuses outright. This is the value that broke it."""
    install(checkout)
    duration = stored_task()["duration"]

    assert duration == "P3650D"
    assert "99999999" not in duration


@needs_scheduler
def test_the_interval_is_configurable(checkout):
    """Asserted through the stored task, so the override is proved to reach
    Task Scheduler rather than merely to be read by the script."""
    install(checkout, SWARM_TASK_INTERVAL_MINUTES=11)

    assert stored_task()["interval"] == "PT11M"


@needs_scheduler
def test_the_misleading_restart_policy_is_gone(checkout):
    """RestartCount restarts a task that *fails*. This one returns 0 having
    launched something that may die an hour later, so it never applied --
    protection in appearance only, beside a repetition that is real."""
    install(checkout)

    assert stored_task()["restartCount"] in (0, None)


# --- What it does when it cannot ---------------------------------------------


@needs_scheduler
def test_a_registration_that_fails_exits_nonzero(checkout):
    """The regression. A repetition interval longer than its duration is
    refused by Task Scheduler exactly as the MaxValue duration was; the old
    command printed "registered" over the top of the exception and exited 0.
    """
    finished = install(
        checkout, SWARM_TASK_INTERVAL_MINUTES=2880, SWARM_TASK_DURATION_DAYS=1)

    assert finished.returncode != 0


@needs_scheduler
def test_a_failed_registration_never_claims_to_have_registered(checkout):
    finished = install(
        checkout, SWARM_TASK_INTERVAL_MINUTES=2880, SWARM_TASK_DURATION_DAYS=1)
    said = finished.stdout + finished.stderr

    assert "FAILED to register" in said
    assert "rechecked every" not in said


@needs_scheduler
def test_a_failed_registration_says_the_swarm_will_not_restart_itself(checkout):
    """An operator reading this has to know what they are now without."""
    finished = install(
        checkout, SWARM_TASK_INTERVAL_MINUTES=2880, SWARM_TASK_DURATION_DAYS=1)

    assert "will not restart itself" in finished.stdout + finished.stderr


@needs_scheduler
def test_a_failed_registration_leaves_no_half_made_task(checkout):
    """Better nothing than a task that exists and does not repeat: the second
    is what an operator would read as armed."""
    install(checkout, SWARM_TASK_INTERVAL_MINUTES=2880, SWARM_TASK_DURATION_DAYS=1)
    task = stored_task()

    assert task is None or task["interval"] == ""


@needs_scheduler
def test_installing_twice_is_the_same_as_installing_once(checkout):
    """`-Force` replaces rather than duplicates, and the second run must not
    report failure for finding its own work already there."""
    assert install(checkout).returncode == 0
    second = install(checkout)

    assert second.returncode == 0
    assert stored_task()["interval"] == "PT5M"
