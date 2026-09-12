"""An author reaches its project, or it blocks on every task it is given.

`chatgpt_worker` reads `AUTHOR_PROJECT` at import and refuses to author
without it. `worker_ctl.sh` defaults it for a worker started by hand, so a
worker started that way has always had it -- and the supervisor path, which is
how the runtime actually starts, set it nowhere. The two launchers agreed on
the value and disagreed on whether anybody applied it, which is the shape of
defect that survives a reading of either file alone.

The consequence was not a degraded author. It was an author that accepted
activations, blocked each one naming the variable, and kept doing so: a
correct refusal repeated indefinitely, which reads in the ledger as the task
being wrong rather than the host.

So this runs the real `swarm_ctl.sh start` against a fixture checkout whose
supervisor is a stub that records the environment it was handed, and asserts
on what the process actually received -- not on the presence of a line in the
script. The last test follows the same value one hop further, through
`child_env`, because the supervisor is what a worker inherits from.
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

sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.skipif(
    not Path(BASH).exists(), reason="this exercises the shell script directly"
)


STUB_SUPERVISOR = '''
import json, os, sys, time
from pathlib import Path

control = Path(os.environ["SWARM_CONTROL_DIR"])

if "--identify" in sys.argv:
    # swarm_ctl asks this twice: before starting, to refuse a second
    # supervisor, and after, to confirm one took the lock. Answering by
    # whether the recording exists keeps both answers truthful.
    sys.exit(0 if (control / "environment.json").exists() else 1)

control.mkdir(parents=True, exist_ok=True)
(control / "environment.json").write_text(
    json.dumps(dict(os.environ)), encoding="utf-8"
)
(control / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
time.sleep(20)
'''

STUB_SSH = "#!/usr/bin/env bash\necho -n 'stub-credential'\n"
STUB_POWERSHELL = "#!/usr/bin/env bash\necho ''\n"


def sh(path: Path) -> str:
    r"""A Windows path as the shell sees it: C:\git\x -> /c/git/x."""
    text = str(path).replace("\\", "/")

    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]

    return text


@pytest.fixture
def checkout(tmp_path):
    """A copy of the real control script, with everything it calls stubbed."""
    root = tmp_path / "checkout"
    root.mkdir()

    shutil.copy2(REPO_ROOT / "swarm_ctl.sh", root / "swarm_ctl.sh")
    (root / "supervisor.py").write_text(STUB_SUPERVISOR, encoding="utf-8")
    (root / "preflight.py").write_text("import sys; sys.exit(0)", encoding="utf-8")

    binaries = tmp_path / "bin"
    binaries.mkdir()

    for name, body in (("ssh", STUB_SSH), ("powershell.exe", STUB_POWERSHELL)):
        target = binaries / name
        target.write_text(body, encoding="utf-8", newline="")
        target.chmod(0o755)

    return root, binaries


def start(checkout, extra_env=None):
    """Run the real `swarm_ctl.sh start`; return the environment it passed on."""
    root, binaries = checkout
    control = root / "control"

    env = dict(os.environ)
    env["PATH"] = str(binaries) + os.pathsep + env["PATH"]
    env["SUPERVISOR_PYTHON"] = sh(Path(sys.executable))
    env["SWARM_CONTROL_DIR"] = str(control)
    env.pop("AUTHOR_PROJECT", None)
    env.update(extra_env or {})

    finished = subprocess.run(
        [BASH, sh(root / "swarm_ctl.sh"), "start"],
        cwd=str(root), env=env, capture_output=True,
        encoding="utf-8", errors="replace", timeout=120,
    )

    recorded = control / "environment.json"

    assert recorded.exists(), (
        "the supervisor was never started\n"
        f"stdout: {finished.stdout}\nstderr: {finished.stderr}"
    )

    return json.loads(recorded.read_text(encoding="utf-8"))


def test_the_supervisor_is_started_knowing_which_project_to_author(checkout):
    assert start(checkout)["AUTHOR_PROJECT"] == "agenthub"


def test_an_operator_can_still_say_which_project(checkout):
    """The default is a default. A host pointed elsewhere keeps its answer."""
    handed = start(checkout, {"AUTHOR_PROJECT": "comicautomation"})
    assert handed["AUTHOR_PROJECT"] == "comicautomation"


def test_the_default_names_a_project_that_resolves(checkout):
    """A name the registry does not know would block exactly as an absent one.

    Asserted against the registry rather than against a literal, so a rename
    in `repos.json` fails here instead of at the first activation.
    """
    import repo_registry

    repo_registry.get(start(checkout)["AUTHOR_PROJECT"])


def test_a_worker_inherits_what_the_supervisor_was_given(monkeypatch):
    """The last hop. `child_env` copies the environment; nothing re-adds this."""
    import supervisor

    monkeypatch.setenv("AUTHOR_PROJECT", "agenthub")
    monkeypatch.setenv("CHATGPT_HUB_SECRET", "irrelevant")

    handed = supervisor.Supervisor.child_env(
        object.__new__(supervisor.Supervisor), "chatgpt"
    )

    assert handed["AUTHOR_PROJECT"] == "agenthub"
