"""`worker_ctl.sh` acts on the checkout it belongs to, and no other.

`REPO` was written out as `/c/git/claude-agent-hub`, and every action `cd`s to
it before running anything -- so the script ran against that one directory
however it had been invoked.

`deploy_controller.sh` derives its own repository from `BASH_SOURCE` and
copies from it correctly, then hands its closing parity check to this script.
A deploy from a worktree therefore copied the right files, matched every
digest on the host, and reported the build of `main`. The check that exists to
catch a stale deployment was reading a different tree than the one deployed.

`start` shared the defect with a worse outcome: a worker launched from a
worktree ran `main`'s script while the operator believed they were exercising
the checkout they were standing in.

These run the real script against real fixture checkouts. Each fixture stubs
the python programs the action would invoke -- preflight, the controller admin
client, the worker script -- so what is asserted is which file got run, which
is precisely the thing that was wrong.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"


pytestmark = pytest.mark.skipif(
    not Path(BASH).exists(), reason="these exercise the shell script directly"
)


def sh(path: Path) -> str:
    """A Windows path as the shell sees it: C:\\git\\x -> /c/git/x."""
    text = str(path).replace("\\", "/")

    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]

    return text


def same_path(path: Path, text: str) -> bool:
    """Whether `text` names `path`.

    Compared case-insensitively with separators normalised, because the shell
    says `/c/Users/...` and python says `C:/Users/...` for the same file, and
    what is being asserted is which file ran, not how it was spelled.
    """
    return str(path).replace("\\", "/").lower() in text.replace("\\", "/").lower()


def run(script: Path, *args, cwd: Path, env=None, timeout=120):
    environment = dict(os.environ)
    environment.update(env or {})

    return subprocess.run(
        [BASH, sh(script), *args],
        cwd=str(cwd), capture_output=True, encoding="utf-8",
        errors="replace", timeout=timeout, env=environment,
    )


def checkout(root: Path, marker: str) -> Path:
    """A fixture checkout whose python programs announce which tree they are.

    Only the pieces `worker_ctl.sh` reaches: the script itself, the programs it
    runs, and the credential fetch it does first. Everything else is absent on
    purpose -- a test that copied the whole repository would pass even if the
    script found some *other* complete repository.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "hub").mkdir(exist_ok=True)

    source = (REPO_ROOT / "worker_ctl.sh").read_text(encoding="utf-8")

    # The credential fetch reaches Tower over ssh. Replaced so these run
    # offline and assert routing rather than connectivity.
    source = source.replace(
        "fetch_secret() {",
        'fetch_secret() { echo "fixture-secret"; return 0; }\n\n_unused_fetch() {',
        1,
    )
    (root / "worker_ctl.sh").write_text(source, encoding="utf-8")

    def program(kind):
        """A stub that announces which tree and which program it is."""
        return (
            "import sys\n"
            f"print({marker!r} + '-' + {kind!r} + ' ' + "
            "__file__.replace(chr(92), '/'))\n"
            "sys.exit(0)\n"
        )

    (root / "preflight.py").write_text(program("PREFLIGHT"), encoding="utf-8")
    (root / "hub" / "controller_admin.py").write_text(
        program("ADMIN"), encoding="utf-8")

    for name in ("claude_worker.py", "gemini_worker.py", "chatgpt_worker.py"):
        (root / name).write_text(program("WORKER"), encoding="utf-8")

    return root


@pytest.fixture
def trees(tmp_path):
    """Two checkouts, so "it used the right one" is a distinguishable claim."""
    return (
        checkout(tmp_path / "primary", "PRIMARY"),
        checkout(tmp_path / "worktree", "WORKTREE"),
    )


# --- The script acts on its own checkout -------------------------------------


def test_running_from_another_directory_still_uses_the_scripts_checkout(trees,
                                                                        tmp_path):
    """The shape of the defect: invoked from elsewhere, it ran elsewhere."""
    primary, worktree = trees
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()

    result = run(worktree / "worker_ctl.sh", "preflight", "claudecode",
                 cwd=elsewhere)

    assert "WORKTREE" in result.stdout, result.stdout + result.stderr
    assert "PRIMARY" not in result.stdout


def test_a_second_checkout_reports_its_own_build_not_the_first(trees):
    """Exactly what the deploy's closing check got wrong."""
    primary, worktree = trees

    from_primary = run(primary / "worker_ctl.sh", "preflight", "claudecode",
                       cwd=primary)
    from_worktree = run(worktree / "worker_ctl.sh", "preflight", "claudecode",
                        cwd=primary)

    assert "PRIMARY" in from_primary.stdout
    assert "WORKTREE" in from_worktree.stdout, from_worktree.stdout


def test_preflight_runs_the_scripts_own_preflight_file(trees):
    primary, worktree = trees

    result = run(worktree / "worker_ctl.sh", "preflight", "gemini", cwd=primary)

    assert same_path(worktree / "preflight.py", result.stdout)


def test_admin_uses_the_scripts_own_controller_client(trees):
    primary, worktree = trees

    result = run(worktree / "worker_ctl.sh", "admin", "tasks", cwd=primary)

    assert "WORKTREE" in result.stdout, result.stdout + result.stderr
    assert same_path(worktree / "hub" / "controller_admin.py", result.stdout)


def scratch_dir() -> Path:
    """The script's own scratch directory, read from the script.

    Hardcoded there, and deliberately left alone by this fix -- the brief was
    the checkout root and the interpreter, not the scratch or control
    directories. Read rather than duplicated so this test cannot drift from it.
    """
    for line in (REPO_ROOT / "worker_ctl.sh").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.startswith("SCRATCH="):
            raw = line.split("=", 1)[1].strip().strip('"')

            if raw.startswith("/") and raw[2:3] == "/":
                raw = raw[1].upper() + ":" + raw[2:]

            return Path(raw)

    raise AssertionError("worker_ctl.sh declares no SCRATCH")


def test_start_launches_the_scripts_own_worker(trees):
    """The defect with the worst outcome: a worker launched from a worktree
    ran `main`'s script and reviewed `main`'s code, while the operator believed
    they were exercising the checkout they were standing in.

    Asserted on the launcher output, which is the only place the launched
    process speaks -- `start` backgrounds it and returns.
    """
    primary, worktree = trees
    launcher = scratch_dir() / "claudecode.launcher.out"
    before = launcher.stat().st_size if launcher.exists() else 0

    run(worktree / "worker_ctl.sh", "start", "claudecode", cwd=primary,
        env={"GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k"})

    deadline = time.monotonic() + 60

    while time.monotonic() < deadline:
        if launcher.exists() and launcher.stat().st_size > before:
            break
        time.sleep(0.2)

    with io.open(launcher, encoding="utf-8", errors="replace") as handle:
        handle.seek(before)
        launched = handle.read()

    assert "WORKTREE-WORKER" in launched, launched[:800]
    assert "PRIMARY-WORKER" not in launched
    assert same_path(worktree / "claude_worker.py", launched)


# --- Paths with spaces --------------------------------------------------------


def test_a_checkout_path_containing_spaces_works(tmp_path):
    """`$(dirname "${BASH_SOURCE[0]}")` is quoted, and the test says so."""
    spaced = checkout(tmp_path / "a path with spaces" / "repo", "SPACED")

    result = run(spaced / "worker_ctl.sh", "preflight", "chatgpt", cwd=tmp_path)

    assert "SPACED" in result.stdout, result.stdout + result.stderr


def test_a_spaced_checkout_reaches_its_own_files(tmp_path):
    spaced = checkout(tmp_path / "another path" / "repo", "SPACED")

    result = run(spaced / "worker_ctl.sh", "admin", "tasks", cwd=tmp_path)

    assert "SPACED" in result.stdout, result.stdout + result.stderr


# --- The interpreter is chosen, not inherited --------------------------------


@pytest.fixture
def decoy_python(tmp_path):
    """A `python` earlier on PATH than the real one, which fails loudly."""
    bin_dir = tmp_path / "decoy-bin"
    bin_dir.mkdir()

    for name in ("python", "python.exe", "python.bat"):
        target = bin_dir / name
        if name.endswith(".bat"):
            target.write_text("@echo DECOY PYTHON WAS USED\r\n@exit /b 3\r\n",
                              encoding="utf-8")
        else:
            target.write_text(
                "#!/bin/sh\necho 'DECOY PYTHON WAS USED'\nexit 3\n",
                encoding="utf-8",
            )
            target.chmod(0o755)

    return bin_dir


def poisoned(bin_dir):
    return {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}


def test_the_decoy_is_actually_first_on_path(trees, decoy_python):
    """Otherwise the two tests below would pass for the wrong reason."""
    primary, _ = trees

    result = run(primary / "worker_ctl.sh", "preflight", "claudecode",
                 cwd=primary, env=poisoned(decoy_python))

    assert "DECOY PYTHON WAS USED" in result.stdout + result.stderr


def test_worker_python_wins_over_whatever_is_on_path(trees, decoy_python):
    primary, _ = trees
    environment = poisoned(decoy_python)
    environment["WORKER_PYTHON"] = sys.executable

    result = run(primary / "worker_ctl.sh", "preflight", "claudecode",
                 cwd=primary, env=environment)

    assert "PRIMARY" in result.stdout, result.stdout + result.stderr
    assert "DECOY" not in result.stdout + result.stderr


def test_deploy_python_wins_over_worker_python(trees, decoy_python):
    """The deploy validated its suites with `DEPLOY_PYTHON`, so its closing
    check has to use the same one -- a persistent `WORKER_PYTHON` in the
    operator's environment must not quietly redirect it."""
    primary, _ = trees
    environment = poisoned(decoy_python)
    environment["DEPLOY_PYTHON"] = sys.executable
    environment["WORKER_PYTHON"] = str(decoy_python / "python")

    result = run(primary / "worker_ctl.sh", "preflight", "claudecode",
                 cwd=primary, env=environment)

    assert "PRIMARY" in result.stdout, result.stdout + result.stderr
    assert "DECOY PYTHON WAS USED" not in result.stdout + result.stderr


def test_the_interpreter_choice_reaches_admin_too(trees, decoy_python):
    primary, _ = trees
    environment = poisoned(decoy_python)
    environment["WORKER_PYTHON"] = sys.executable

    result = run(primary / "worker_ctl.sh", "admin", "tasks", cwd=primary,
                 env=environment)

    assert "PRIMARY" in result.stdout, result.stdout + result.stderr


# --- The deploy still fails loudly -------------------------------------------


def test_a_failing_closing_preflight_makes_the_deploy_exit_nonzero(trees):
    """The check is the deploy's last gate. A gate that cannot fail the build
    is not a gate."""
    primary, _ = trees
    (primary / "preflight.py").write_text(
        "import sys\nprint('PREFLIGHT FAILED')\nsys.exit(1)\n", encoding="utf-8"
    )

    result = run(primary / "worker_ctl.sh", "preflight", "claudecode",
                 cwd=primary)

    assert result.returncode != 0
    assert "PREFLIGHT FAILED" in result.stdout


def test_the_deploy_script_propagates_that_failure(tmp_path):
    """`deploy_controller.sh` ends with this check, and its own exit status is
    what any caller keys off."""
    source = (REPO_ROOT / "deploy_controller.sh").read_text(encoding="utf-8")

    assert '"$REPO/worker_ctl.sh" preflight claudecode' in source

    tail = source[source.index('"$REPO/worker_ctl.sh" preflight claudecode'):]

    assert "set -e" in source or "exit" in tail, (
        "the closing check's failure must reach the deploy's exit status"
    )


# --- The derivation itself ----------------------------------------------------


def test_the_repository_is_not_hardcoded_anywhere():
    source = (REPO_ROOT / "worker_ctl.sh").read_text(encoding="utf-8")
    code = [
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    ]

    assert not any("REPO=/c/git/" in line for line in code)
    assert any("BASH_SOURCE" in line for line in code)


def test_every_python_invocation_goes_through_the_chosen_interpreter():
    """A single missed call site would reintroduce half the defect."""
    source = (REPO_ROOT / "worker_ctl.sh").read_text(encoding="utf-8")
    bare = [
        line for line in source.splitlines()
        if not line.strip().startswith("#")
        and line.lstrip().startswith("python ")
    ]

    assert bare == [], bare
