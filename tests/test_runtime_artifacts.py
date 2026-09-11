"""Runtime state does not travel in the repository.

Six live artifacts were committed on the supervisor branch: three `.pid`
locks, `narration.jsonl`, `status.json`, and `supervisor.out`. The chat content
and the operator's file paths were the visible cost.

The dangerous one was the lock files. A `.pid` names a process this host is
willing to terminate during shutdown, so a committed one hands every other
checkout a number that was never a worker on that machine -- and pids are
reused, so by the time it is read it may name anything. Cleanup would then
aim a force-kill at whatever inherited it.

Two independent properties close that, and both are tested: the numbers cannot
reach a commit, and a number alone is not authority to kill (see
`test_supervisor.py`, which pins the second).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Written by a running swarm and read by nothing outside the host it runs on.
RUNTIME_ARTIFACTS = [
    "control/chatgpt.pid",
    "control/gemini.pid",
    "control/claudecode.pid",
    "control/supervisor.pid",
    "control/narration.jsonl",
    "control/status.json",
    "control/supervisor.out",
    "control/supervisor.log",
    "control/PAUSED",
    "control/STOPPING",
    "control/activations/anything.json",
    "control/consumed/anything.json",
]


def git(*args):
    """Run git in the repository, or skip if there is no git to run."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        pytest.skip(f"git is not usable here: {exc}")

    return result


@pytest.fixture(scope="module")
def tracked():
    result = git("ls-files", "-z", "--", "control")

    if result.returncode != 0:
        pytest.skip("not a git checkout")

    return [entry for entry in result.stdout.split("\0") if entry]


def test_no_control_file_is_tracked(tracked):
    """Not one of them is source, and the pid files are actively unsafe."""
    assert tracked == []


@pytest.mark.parametrize("path", RUNTIME_ARTIFACTS)
def test_a_runtime_artifact_would_be_ignored(path):
    """Ignored by pattern, so the next file the runtime grows is covered too.

    Listing the six that were committed would leave the seventh to be found
    the same way the first six were.
    """
    result = git("check-ignore", "--", path)

    assert result.returncode == 0, f"{path} is not ignored"


def test_the_control_directory_is_ignored_as_a_whole():
    """The pattern is the directory, not an enumeration of its contents."""
    result = git("check-ignore", "-v", "--", "control/chatgpt.pid")

    assert result.returncode == 0
    assert "control/" in result.stdout
