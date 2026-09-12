"""A worker reaches the repository it works in, or it blocks on everything.

`chatgpt_worker` reads `AUTHOR_PROJECT` at import and refuses to author
without it; `gemini_worker` reads `REVIEW_REPO` and refuses to review without
it. `worker_ctl.sh` defaults both for a worker started by hand, so a worker
started that way has always had them -- and the supervisor path, which is how
the runtime actually starts, set neither. The two launchers agreed on the
values and disagreed on whether anybody applied them, which is the shape of
defect that survives a reading of either file alone.

The consequence was not a degraded worker. It was a worker that accepted
activations, blocked each one naming the variable, and kept doing so: a
correct refusal repeated indefinitely, which reads in the ledger as the task
being wrong rather than the host. The reviewer's half is the worse of the
two, because a task whose review comes back blocked still reads as a task
under review, and nothing about the state says nobody is coming.

They are tested together because they are one defect with two names. Fixing
the author's and not the reviewer's is exactly the mistake that happened, so
a test that covered only one would have passed through it.

So this runs the real `swarm_ctl.sh start` against a fixture checkout whose
supervisor is a stub that records the environment it was handed, and asserts
on what the process actually received -- not on the presence of a line in the
script. The last test follows the same values one hop further, through
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


def same_path(path: Path, text: str) -> bool:
    """Whether `text` names `path`.

    Compared with separators normalised and case folded, because the shell
    says `/c/Users/...` and python says `C:/Users/...` for the same directory,
    and what is asserted is which checkout was named, not how it was spelled.
    """
    return Path(text).resolve() == Path(path).resolve()


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
    env.pop("REVIEW_REPO", None)
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


def test_the_supervisor_is_started_knowing_where_to_review(checkout):
    """The reviewer's half of the same defect.

    Asserted as the checkout the script belongs to rather than a literal,
    because `REPO` is derived from `BASH_SOURCE`: a supervisor started from a
    worktree must review that worktree, not whichever path was written down.
    """
    root, _ = checkout
    handed = start(checkout)

    assert same_path(root, handed["REVIEW_REPO"])


def test_an_operator_can_still_say_where_to_review(checkout, tmp_path):
    """The default is a default, exactly as it is for the project name."""
    elsewhere = tmp_path / "another-checkout"
    elsewhere.mkdir()

    handed = start(checkout, {"REVIEW_REPO": sh(elsewhere)})

    assert same_path(elsewhere, handed["REVIEW_REPO"])


INTEGRATION_VARIABLES = (
    "INTEGRATION_REPO",
    "INTEGRATION_TARGET_REF",
    "INTEGRATION_REPO_SLUG",
    "INTEGRATION_WORK_ROOT",
    # Not in the worker's required-variable check -- an empty value is legal
    # there and means "any green check will do". It is required here because
    # that default is a weaker gate than this swarm wants.
    "INTEGRATION_REQUIRED_SUITES",
)


def test_the_integrator_is_given_every_variable_it_refuses_without(checkout):
    """All four, or the only stage that reaches a real remote blocks.

    `execute_integration` checks them as a set and refuses on the first
    absent one, so three out of four is worth exactly as much as none: an
    integration activation spent to be told the host is not configured.
    """
    handed = start(checkout)

    absent = [name for name in INTEGRATION_VARIABLES if not handed.get(name)]

    assert absent == [], f"the integrator would refuse: {absent} not provided"


def test_the_launcher_provides_exactly_what_the_worker_demands(checkout):
    """The list in the script and the list in the worker cannot drift apart.

    Read out of `claude_worker` rather than written down twice. A variable
    added to that check and not to the launcher is a stage that stops
    working, and nothing else in the suite would notice.
    """
    import re

    source = (REPO_ROOT / "claude_worker.py").read_text(encoding="utf-8")
    block = source[source.index("def execute_integration"):]
    block = block[:block.index("refuse(f\"{name} is not configured")]
    demanded = set(re.findall(r'"(INTEGRATION_[A-Z_]+)"', block))

    assert demanded, "could not find the integrator's required-variable check"

    handed = start(checkout)

    assert demanded <= set(INTEGRATION_VARIABLES)
    assert all(handed.get(name) for name in demanded)


def test_the_required_suites_are_named(checkout):
    """An unnamed requirement is not a requirement.

    `check_evidence` with an empty `required` demands only that some green
    check-run exists, which a workflow running one trivial job satisfies
    while proving nothing about the tests. The names turn a missing suite
    into a refusal.
    """
    handed = start(checkout)
    named = [s for s in handed["INTEGRATION_REQUIRED_SUITES"].split(",") if s.strip()]

    assert len(named) >= 2, f"only {named} required; a single suite is not a gate"


def test_the_required_suites_are_check_run_names_not_paths(checkout):
    """They are matched against GitHub check-run names, not files.

    A path here reads as configured and can never match, so the integrator
    would refuse every future integration with "required suite has no
    evidence" and the cause would look like CI rather than this line.
    """
    handed = start(checkout)

    for name in handed["INTEGRATION_REQUIRED_SUITES"].split(","):
        name = name.strip()
        assert name
        assert "/" not in name and not name.endswith(".py"), name


def test_the_merge_target_is_a_full_ref(checkout):
    """`main` and `refs/heads/main` are not the same thing to git.

    A bare branch name resolves against whatever happens to match first,
    which for the one stage that pushes to a real remote is not a risk worth
    carrying for four saved characters.
    """
    handed = start(checkout)

    assert handed["INTEGRATION_TARGET_REF"].startswith("refs/")


def test_the_integrator_does_not_merge_inside_the_canonical_checkout(checkout):
    """The work root is somewhere else, on purpose.

    Cloning and merging in the checkout a person is working in means a failed
    integration leaves their tree to be repaired by hand, and a successful one
    can race whatever they were editing.
    """
    root, _ = checkout
    handed = start(checkout)

    assert not same_path(root, handed["INTEGRATION_WORK_ROOT"])


def test_an_operator_can_still_say_where_integration_lands(checkout, tmp_path):
    """Every one of them stays overridable, as the other two are."""
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()

    handed = start(checkout, {
        "INTEGRATION_TARGET_REF": "refs/heads/release",
        "INTEGRATION_REPO_SLUG": "Someone/else",
        "INTEGRATION_WORK_ROOT": sh(elsewhere),
    })

    assert handed["INTEGRATION_TARGET_REF"] == "refs/heads/release"
    assert handed["INTEGRATION_REPO_SLUG"] == "Someone/else"
    assert same_path(elsewhere, handed["INTEGRATION_WORK_ROOT"])


def test_a_worker_inherits_what_the_supervisor_was_given(monkeypatch):
    """The last hop. `child_env` copies the environment; nothing re-adds these."""
    import supervisor

    monkeypatch.setenv("AUTHOR_PROJECT", "agenthub")
    monkeypatch.setenv("REVIEW_REPO", r"C:\git\claude-agent-hub")
    monkeypatch.setenv("INTEGRATION_REPO", r"C:\git\claude-agent-hub")
    monkeypatch.setenv("INTEGRATION_TARGET_REF", "refs/heads/main")
    monkeypatch.setenv("INTEGRATION_REPO_SLUG", "Decksx/agent-swarm")
    monkeypatch.setenv("INTEGRATION_WORK_ROOT", r"C:\git\.swarm-integration")
    monkeypatch.setenv("INTEGRATION_REQUIRED_SUITES", "pytest-unit,pytest-bypass")
    monkeypatch.setenv("CHATGPT_HUB_SECRET", "irrelevant")
    monkeypatch.setenv("GEMINI_HUB_SECRET", "irrelevant")
    monkeypatch.setenv("CLAUDECODE_HUB_SECRET", "irrelevant")

    authoring = supervisor.Supervisor.child_env(
        object.__new__(supervisor.Supervisor), "chatgpt"
    )
    reviewing = supervisor.Supervisor.child_env(
        object.__new__(supervisor.Supervisor), "gemini"
    )

    integrating = supervisor.Supervisor.child_env(
        object.__new__(supervisor.Supervisor), "claudecode"
    )

    assert authoring["AUTHOR_PROJECT"] == "agenthub"
    assert reviewing["REVIEW_REPO"] == r"C:\git\claude-agent-hub"
    assert all(integrating.get(name) for name in INTEGRATION_VARIABLES)
    assert integrating["INTEGRATION_TARGET_REF"] == "refs/heads/main"
