"""Exercise the hidden scheduled launcher with real, harmless child processes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PYTHONW = Path(sys.executable).with_name("pythonw.exe")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PYTHONW.exists(), reason="requires Windows pythonw.exe",
)


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "scheduled checkout"
    root.mkdir()
    script = root / "run_hidden.pyw"
    shutil.copy2(Path(__file__).resolve().parents[1] / "run_hidden.pyw", script)
    control = tmp_path / "runtime control"
    env = {**os.environ, "SWARM_CONTROL_DIR": str(control)}

    def run(*command):
        result = subprocess.run(
            [str(PYTHONW), str(script), *command], env=env,
            cwd=tmp_path, capture_output=True, text=True, timeout=20,
        )
        return result.returncode, (control / "scheduled_ensure.log").read_text(encoding="utf-8")

    return run, root


@pytest.mark.parametrize("exit_code", [0, 7])
def test_launcher_records_child_output_and_returns_its_status(launcher, exit_code):
    run, root = launcher
    code = (
        "import os, sys; print('cwd=' + os.getcwd()); "
        "print('stdin=' + repr(sys.stdin.read())); "
        "print('child stdout'); print('child stderr', file=sys.stderr); "
        f"sys.exit({exit_code})"
    )

    status, log = run(sys.executable, "-c", code)

    assert status == exit_code
    assert f"cwd={root}" in log
    assert "stdin=''" in log
    assert "child stdout" in log
    assert "child stderr" in log


def test_missing_command_is_reported_as_a_failure(launcher):
    run, _ = launcher

    status, log = run()

    assert status == 2
    assert "missing command" in log


def test_unlaunchable_command_is_logged_without_claiming_success(launcher):
    run, root = launcher

    status, log = run(str(root / "missing-program.exe"))

    assert status == 1
    assert "FileNotFoundError" in log


def test_consecutive_runs_append_instead_of_replacing_evidence(launcher):
    run, _ = launcher
    assert run(sys.executable, "-c", "print('first ensure')")[0] == 0

    status, log = run(sys.executable, "-c", "print('second ensure')")

    assert status == 0
    assert log.count("first ensure") == 1
    assert log.count("second ensure") == 1
