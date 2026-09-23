"""Integration happens in the repository the controller named, and a check
that cannot answer is never recorded as a verdict on the candidate (#78).

Found live: acceptance run 2's candidate was correct, the integrator looked
for it in the production checkout -- which the author never commits in -- and
read git's "no such object" (exit 128) as "not an ancestor". Seq 447 recorded
a valid candidate as defective.

Real git throughout the repository and ancestry tests, because both defects
live in what git actually returns, and a stub that returned 1 where git
returns 128 is exactly the assumption that was wrong.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claude_integration  # noqa: E402
import integrator  # noqa: E402
from integrator import (  # noqa: E402
    Evidence, IntegrationRefused, IntegrationUnverifiable,
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=True,
    ).stdout.strip()


def commit(repo, name, text):
    (Path(repo) / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def split(tmp_path):
    """The deployment as it is since 2026-09-22.

    `dev` is where the author commits; `prod` is a clone taken before the
    candidate existed, which is what the runtime checkout is. The candidate is
    in `dev` and not in `prod`, and `base` is in both.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    git(dev, "init", "-q", "-b", "main")
    git(dev, "config", "user.email", "t@example.com")
    git(dev, "config", "user.name", "t")
    base = commit(dev, "README.md", "# title\n")

    prod = tmp_path / "prod"
    subprocess.run(["git", "clone", "-q", str(dev), str(prod)], check=True)

    git(dev, "checkout", "-q", "-b", "task/T-1-a1")
    candidate = commit(dev, "README.md", "# title\n\n> note\n")

    git(dev, "checkout", "-q", "main")
    git(dev, "checkout", "-q", "-b", "elsewhere", base)
    divergent_base = commit(dev, "other.txt", "x\n")
    git(dev, "checkout", "-q", "main")

    return {
        "dev": str(dev), "prod": str(prod), "base": base,
        "candidate": candidate, "divergent": divergent_base,
    }


# --- is_ancestor: 0, 1, and everything else --------------------------------


def test_a_valid_candidate_is_an_ancestor_answer(split):
    assert integrator.is_ancestor(split["dev"], split["base"], split["candidate"])


def test_a_genuine_non_ancestor_is_a_no(split):
    """Exit 1: git answered, and the answer is no."""
    assert not integrator.is_ancestor(
        split["dev"], split["divergent"], split["candidate"]
    )


def test_a_missing_object_is_not_an_answer(split):
    """Exit 128, which is what seq 447 was. Raised, never returned as False."""
    with pytest.raises(IntegrationUnverifiable) as raised:
        integrator.is_ancestor(split["prod"], split["base"], split["candidate"])

    detail = raised.value.detail
    assert detail["exit_code"] == 128
    assert detail["stderr"], "the stderr git gave is the evidence; keep it"
    assert detail["repo"] == split["prod"]
    assert "exited 128" in raised.value.reason
    assert not raised.value.after_push


# --- run_integration's ancestry step ----------------------------------------


def drive(monkeypatch, repo, *, target, candidate):
    """Stub every step except the ancestry check, which runs real git."""
    built = []

    monkeypatch.setattr(integrator, "approved_candidate", lambda task: candidate)
    monkeypatch.setattr(integrator, "find_pull_request", lambda **kw: 76)
    monkeypatch.setattr(integrator, "pin_target", lambda p: target)
    monkeypatch.setattr(
        integrator, "ci_evidence",
        lambda c, *, repo_slug: (
            Evidence(name="ci:unit", command="pytest", exit_code=0, passed=1),
        ),
    )
    monkeypatch.setattr(integrator, "check_evidence", lambda p, *, required: None)
    monkeypatch.setattr(integrator, "check_pr", lambda p, *, repo_slug: {})
    monkeypatch.setattr(integrator, "check_target_unmoved", lambda p: target)

    def fake_build(plan, *, work_root):
        built.append(plan.repo)
        return "f" * 40

    monkeypatch.setattr(integrator, "build_merge", fake_build)
    monkeypatch.setattr(integrator, "push_if_target_unmoved", lambda p, m: None)
    monkeypatch.setattr(integrator, "verify_landed", lambda p, m: None)
    monkeypatch.setattr(integrator, "check_merge_parents", lambda p, m: None)
    monkeypatch.setattr(integrator, "check_tree_identical", lambda p, m: None)

    def run():
        return integrator.run_integration(
            {"task_id": "T-1", "state": "INTEGRATING"}, repo=repo,
            target_ref="refs/heads/main", branch="task/T-1-a1",
            repo_slug="o/r", work_root="unused", required_suites=[],
            actor="claudecode", ci_wait_seconds=0,
        )

    return run, built


def test_the_valid_candidate_in_the_named_repository_is_merged(monkeypatch, split):
    run, built = drive(monkeypatch, split["dev"], target=split["base"],
                       candidate=split["candidate"])
    run()
    assert built == [split["dev"]]


def test_the_candidate_missing_from_the_repository_is_unverifiable(monkeypatch, split):
    """Seq 447 exactly: the production checkout, a correct candidate."""
    run, built = drive(monkeypatch, split["prod"], target=split["base"],
                       candidate=split["candidate"])

    with pytest.raises(IntegrationUnverifiable) as raised:
        run()

    assert not isinstance(raised.value, IntegrationRefused)
    assert raised.value.detail["exit_code"] == 128
    assert built == [], "nothing may be built on a check that did not answer"


def test_a_genuine_non_ancestor_is_still_refused(monkeypatch, split):
    """The guard this sits beside must keep working (T-INFRA-03)."""
    run, built = drive(monkeypatch, split["dev"], target=split["divergent"],
                       candidate=split["candidate"])

    with pytest.raises(IntegrationRefused, match="is not an ancestor"):
        run()

    assert built == []


def test_an_unanswerable_check_after_the_push_is_marked_as_such(monkeypatch, split):
    """verify_landed: the merge may be on the target, so it is `after_push`."""
    plan = integrator.Plan(
        task_id="T-1", repo=split["prod"], candidate_sha=split["candidate"],
        target_ref="refs/heads/main", target_sha_expected=split["base"],
    )
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 0, "", "")
        if a[0] == "fetch" else subprocess.run(
            ["git", *a], cwd=repo, capture_output=True, text=True),
    )
    monkeypatch.setattr(integrator, "pin_target", lambda p: split["candidate"])

    with pytest.raises(IntegrationUnverifiable) as raised:
        integrator.verify_landed(plan, "e" * 40)

    assert raised.value.after_push


# --- the worker integrates where the activation says, and nowhere else ------


@pytest.fixture
def worker(monkeypatch, tmp_path, split):
    """The worker path with real repository checks and a recording integrator.

    `INTEGRATION_REPO` is set to the production checkout on purpose: it is
    the old source of truth, and nothing may read it any more.
    """
    for name, value in (
        ("INTEGRATION_REPO", split["prod"]),
        ("INTEGRATION_TARGET_REF", "refs/heads/main"),
        ("INTEGRATION_REPO_SLUG", "o/r"),
        ("INTEGRATION_WORK_ROOT", str(tmp_path / "work")),
    ):
        monkeypatch.setenv(name, value)

    state = {"repo": None, "raise": None}

    def run_integration(task, **kw):
        state["repo"] = kw["repo"]
        if state["raise"] is not None:
            raise state["raise"]
        return {"candidate_sha": split["candidate"], "merge_sha": "f" * 40,
                "target_ref": kw["target_ref"]}

    monkeypatch.setattr(integrator, "run_integration", run_integration)

    reports = []

    class Queue:
        def report_integration(self, activation_id, *, outcome, payload):
            reports.append((outcome, payload))

    def run(**over):
        activation = {
            "activation_id": "A-1", "task_id": "T-1", "stage": "integrate",
            "expected_branch": "task/T-1-a1",
            "expected_candidate": split["candidate"],
            "repo_location": split["dev"],
            "task_record": {"task_id": "T-1", "state": "INTEGRATING",
                            "approved_candidate_sha": split["candidate"]},
            **over,
        }
        claude_integration.execute_integration(activation, Queue(), actor="claudecode")
        return reports

    state["run"] = run
    return state


def test_split_checkouts_integrate_in_the_named_one(worker, split):
    reports = worker["run"]()

    assert worker["repo"] == split["dev"]
    assert worker["repo"] != split["prod"]
    assert [o for o, _ in reports] == ["integrated"]


def test_no_repo_location_fails_closed_without_falling_back(worker, split):
    """INTEGRATION_REPO is a usable repository here, and is still not used."""
    reports = worker["run"](repo_location=None)

    assert worker["repo"] is None, "the integrator must never have been called"
    [(outcome, payload)] = reports
    assert outcome == "unverifiable"
    assert "names no repo_location" in payload["reason"]


def test_a_named_repository_lacking_the_candidate_fails_closed(worker, split):
    reports = worker["run"](repo_location=split["prod"])

    assert worker["repo"] is None
    [(outcome, payload)] = reports
    assert outcome == "unverifiable"
    assert "does not contain candidate" in payload["reason"]
    assert payload["candidate_sha"] == split["candidate"]


@pytest.mark.parametrize("make", ["missing", "not_git"])
def test_an_unusable_named_repository_fails_closed(worker, tmp_path, make):
    path = tmp_path / make
    if make == "not_git":
        path.mkdir()

    reports = worker["run"](repo_location=str(path))

    assert worker["repo"] is None
    assert [o for o, _ in reports] == ["unverifiable"]


def test_an_unverifiable_check_is_reported_as_unverifiable(worker, split):
    worker["raise"] = IntegrationUnverifiable(
        "git exited 128", detail={"exit_code": 128, "stderr": "fatal: x"}
    )

    [(outcome, payload)] = worker["run"]()

    assert outcome == "unverifiable"
    assert payload["exit_code"] == 128
    assert payload["stderr"] == "fatal: x"


def test_an_unverifiable_check_after_the_push_is_reported_as_uncertain(worker):
    worker["raise"] = IntegrationUnverifiable("x", after_push=True)

    assert [o for o, _ in worker["run"]()] == ["uncertain"]


def test_a_genuine_refusal_is_still_refused(worker):
    worker["raise"] = IntegrationRefused("the pinned target is not an ancestor")

    assert [o for o, _ in worker["run"]()] == ["refused"]
