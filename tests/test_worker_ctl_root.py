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
    # The scratch directory too, which is otherwise a real shared path on this
    # machine. Left alone, `start` appended to the operator's actual launcher
    # log and consulted the standalone-worker pid files beside it -- so the
    # suite both wrote to live state and could pass or fail on what happened to
    # be running. Redirected here rather than in the script, because the
    # script's own scratch path is deliberately outside this change's scope.
    scratch = root / "scratch"
    scratch.mkdir(exist_ok=True)
    redirected = []

    for line in source.splitlines():
        if line.startswith("SCRATCH="):
            line = 'SCRATCH="' + sh(scratch) + '"'
        redirected.append(line)

    source = "\n".join(redirected) + "\n"

    assert 'SCRATCH="' + sh(scratch) + '"' in source, (
        "the scratch redirect did not apply"
    )

    (root / "worker_ctl.sh").write_text(source, encoding="utf-8")

    def program(kind):
        """A stub that announces which tree and which program it is.

        The worker stub also writes its pid where the real worker's
        `SingleInstance` writes one -- `$SWARM_CONTROL_DIR/$AGENT_IDENTITY.pid`,
        both exported by `start`. Without that the launcher output was the only
        thing a start produced, and a test claiming the pid file landed in the
        fixture would have been asserting something nothing did.
        """
        lines = ["import os, pathlib, sys"]

        if kind == "WORKER":
            lines += [
                "control = os.environ.get('SWARM_CONTROL_DIR')",
                "identity = os.environ.get('AGENT_IDENTITY')",
                "if control and identity:",
                "    directory = pathlib.Path(control)",
                "    directory.mkdir(parents=True, exist_ok=True)",
                "    (directory / (identity + '.pid')).write_text(",
                "        str(os.getpid()), encoding='utf-8')",
            ]

        lines += [
            f"print({marker!r} + '-' + {kind!r} + ' ' + "
            "__file__.replace(chr(92), '/'))",
            "sys.exit(0)",
        ]

        return "\n".join(lines) + "\n"

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


def test_start_launches_the_scripts_own_worker(trees):
    """The defect with the worst outcome: a worker launched from a worktree
    ran `main`'s script and reviewed `main`'s code, while the operator believed
    they were exercising the checkout they were standing in.

    Asserted on the launcher output, which is the only place the launched
    process speaks -- `start` backgrounds it and returns. That output lands in
    the fixture's own scratch directory, so this says nothing about, and writes
    nothing to, whatever else is running on this machine.
    """
    primary, worktree = trees
    launcher = worktree / "scratch" / "claudecode.launcher.out"

    run(worktree / "worker_ctl.sh", "start", "claudecode", cwd=primary)

    deadline = time.monotonic() + 60

    while time.monotonic() < deadline and not launcher.exists():
        time.sleep(0.2)

    assert launcher.exists(), "start never launched anything"

    launched = launcher.read_text(encoding="utf-8", errors="replace")

    assert "WORKTREE-WORKER" in launched, launched[:800]
    assert "PRIMARY-WORKER" not in launched
    assert same_path(worktree / "claude_worker.py", launched)


def test_start_touches_only_its_own_scratch(trees):
    """The other half of hermeticity: the lock as well as the log.

    `claudecode`, not `gemini`. The gemini and chatgpt branches overwrite the
    key the test supplies with `[Environment]::GetEnvironmentVariable(...,
    "User")` from the host, so starting gemini here passed only because this
    machine happens to hold that credential and would exit before launching
    anything on a clean one. `claudecode` reads no user-level key, which is why
    the neighbouring launch test already uses it.
    """
    primary, worktree = trees

    run(worktree / "worker_ctl.sh", "start", "claudecode", cwd=primary)

    pid_file = worktree / "scratch" / "swarm_control" / "claudecode.pid"
    deadline = time.monotonic() + 60

    while time.monotonic() < deadline and not pid_file.exists():
        time.sleep(0.2)

    assert pid_file.exists(), "the worker took no lock inside the fixture"
    assert pid_file.read_text(encoding="utf-8").strip().isdigit()

    other = sorted(
        p.relative_to(primary).as_posix()
        for p in (primary / "scratch").rglob("*") if p.is_file()
    )

    assert other == [], f"it wrote into the other checkout's scratch: {other}"


def test_start_still_launches_when_the_host_holds_no_user_level_key(trees,
                                                                    tmp_path):
    """A clean machine, simulated rather than described.

    `powershell.exe` is shadowed by one that returns nothing, which is what
    `[Environment]::GetEnvironmentVariable(..., "User")` yields where the
    credential was never set. Starting gemini or chatgpt under this exits
    before launching anything; claudecode is unaffected, and that is the whole
    reason this suite uses it.
    """
    primary, worktree = trees
    shadow = tmp_path / "clean-host"
    shadow.mkdir()
    (shadow / "powershell.exe").write_text("", encoding="utf-8")
    (shadow / "powershell").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (shadow / "powershell").chmod(0o755)

    run(worktree / "worker_ctl.sh", "start", "claudecode", cwd=primary,
        env={"PATH": str(shadow) + os.pathsep + os.environ.get("PATH", "")})

    launcher = worktree / "scratch" / "claudecode.launcher.out"
    deadline = time.monotonic() + 60

    while time.monotonic() < deadline and not launcher.exists():
        time.sleep(0.2)

    assert launcher.exists(), "claudecode depended on a host credential after all"
    assert "WORKTREE-WORKER" in launcher.read_text(encoding="utf-8",
                                                   errors="replace")


def test_start_needs_no_user_level_credential_for_claudecode(trees):
    """Stated so the choice of identity above cannot quietly drift back.

    Neither the hub credential nor any API key comes from the host for this
    path: the fixture stubs `fetch_secret`, and `claudecode` has no PowerShell
    lookup to stub.
    """
    source = (REPO_ROOT / "worker_ctl.sh").read_text(encoding="utf-8")
    lookups = [
        line for line in source.splitlines()
        if "GetEnvironmentVariable" in line and not line.strip().startswith("#")
    ]

    assert lookups, "the lookups this avoids should still exist for the others"
    assert all("claudecode" not in line for line in lookups)


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


def closing_handoff(root: Path, target: Path) -> Path:
    """The deploy's last two lines, taken from the real script and made runnable.

    Its error-handling setting and its closing invocation are copied out of
    `deploy_controller.sh` rather than retyped, so a change to either in the
    real file changes what this executes. Everything before them -- the ssh,
    the suites, the container restart -- is what makes running the whole thing
    impractical here, and none of it is what is being asserted.
    """
    source = (REPO_ROOT / "deploy_controller.sh").read_text(encoding="utf-8")

    errexit = next(
        line for line in source.splitlines() if line.startswith("set -")
    )
    closing = next(
        line for line in source.splitlines()
        if "worker_ctl.sh" in line and "preflight" in line
        and not line.strip().startswith("#")
    )

    script = root / "closing.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        + errexit + "\n"
        + 'REPO="' + sh(target) + '"\n'
        + 'PYTHON="${DEPLOY_PYTHON:-python}"\n'
        + closing + "\n"
        + 'echo "DEPLOY REACHED THE END"\n',
        encoding="utf-8",
    )

    return script


def test_a_failing_closing_preflight_fails_the_deploy_process(trees, tmp_path):
    """Executed, not read.

    The previous version of this asserted that `set -e` appeared somewhere in
    the source, which would have held just as well if the closing invocation
    had been changed to swallow its status.
    """
    primary, _ = trees
    (primary / "preflight.py").write_text(
        "import sys\nprint('PREFLIGHT FAILED')\nsys.exit(1)\n", encoding="utf-8"
    )

    result = run(closing_handoff(tmp_path, primary), cwd=tmp_path)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "PREFLIGHT FAILED" in result.stdout
    assert "DEPLOY REACHED THE END" not in result.stdout


def test_a_passing_closing_preflight_lets_the_deploy_finish(trees, tmp_path):
    """The other side, so the test above cannot be passing because the harness
    fails for some unrelated reason."""
    primary, _ = trees

    result = run(closing_handoff(tmp_path, primary), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRIMARY-PREFLIGHT" in result.stdout
    assert "DEPLOY REACHED THE END" in result.stdout


def test_the_deploy_hands_its_own_interpreter_to_the_closing_check(
    trees, tmp_path, decoy_python
):
    """No DEPLOY_PYTHON supplied, a conflicting WORKER_PYTHON in the environment.

    The deploy resolves `PYTHON` to `python` and runs its suites with it. If it
    does not pass that choice on, `worker_ctl.sh` picks up WORKER_PYTHON and
    the closing check measures a different installation than the one the deploy
    validated -- the exact drift the interpreter selection exists to prevent.
    """
    primary, _ = trees
    environment = dict(os.environ)
    environment.pop("DEPLOY_PYTHON", None)
    environment["WORKER_PYTHON"] = str(decoy_python / "python")

    result = subprocess.run(
        [BASH, sh(closing_handoff(tmp_path, primary))],
        cwd=str(tmp_path), capture_output=True, encoding="utf-8",
        errors="replace", timeout=120, env=environment,
    )
    combined = result.stdout + result.stderr

    assert "DECOY PYTHON WAS USED" not in combined, combined[:600]
    assert "PRIMARY-PREFLIGHT" in result.stdout, combined[:600]


def test_an_explicit_deploy_python_still_reaches_the_closing_check(
    trees, tmp_path, decoy_python
):
    primary, _ = trees
    environment = poisoned(decoy_python)
    environment["DEPLOY_PYTHON"] = sys.executable
    environment["WORKER_PYTHON"] = str(decoy_python / "python")

    result = run(closing_handoff(tmp_path, primary), cwd=tmp_path,
                 env=environment)

    assert "DECOY PYTHON WAS USED" not in result.stdout + result.stderr
    assert "PRIMARY-PREFLIGHT" in result.stdout


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
