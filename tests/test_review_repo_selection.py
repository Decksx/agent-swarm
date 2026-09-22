"""Which checkout a review happens in, and what happens when it cannot (#64).

The controller records `repo_location` on a review activation at issue time,
the same way it records `expected_candidate`. The worker used to warn when its
own `REVIEW_REPO` disagreed and then review in `REVIEW_REPO` anyway -- so the
ledger could record a verdict naming a candidate the reviewer never saw.

Found in production the first time the runtime checkout and the task repository
were different directories, which is a configuration nothing had exercised
because the two had always been the same tree by coincidence. These tests are
that configuration, made permanent: every case here has an activation
repository and an environment repository that are not the same path.
"""

from __future__ import annotations

import subprocess

import pytest

import gemini_worker


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


def make_repo(path, content="one\n"):
    """A real repository with one commit, and that commit's sha."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    (path / "README.md").write_text(content, encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "one")

    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    """Two repositories that share no history, as the two checkouts did."""
    named = tmp_path / "named"
    configured = tmp_path / "configured"

    return {
        "named": named, "named_sha": make_repo(named, "named\n"),
        "configured": configured,
        "configured_sha": make_repo(configured, "configured\n"),
    }


def activation(repo_location=None, candidate=None):
    return {"activation_id": "a1", "repo_location": repo_location,
            "expected_candidate": candidate}


# 1. The activation's repository wins over a conflicting environment one.


def test_the_activation_repository_overrides_a_conflicting_review_repo(repos):
    repo, detail = gemini_worker.resolve_review_repo(
        activation(str(repos["named"]), repos["named_sha"]),
        repos["named_sha"],
        configured=str(repos["configured"]),
    )

    assert repo == str(repos["named"])
    assert detail["repo_source"] == "activation"
    # Both paths are recorded, so the ledger says what was asked for and what
    # this host had configured.
    assert detail["repo_location"] == str(repos["named"])
    assert detail["review_repo"] == str(repos["configured"])


# 2. A candidate only the activation's repository has reviews successfully.


def test_a_candidate_only_the_named_repository_has_is_accepted(repos):
    repo, detail = gemini_worker.resolve_review_repo(
        activation(str(repos["named"]), repos["named_sha"]),
        repos["named_sha"],
        configured=str(repos["configured"]),
    )

    assert repo == str(repos["named"])
    assert detail["repo_used"] == str(repos["named"])


# 3. A candidate only the *environment* repository has is refused.
#
#    This is the production failure inverted. Falling back here is exactly what
#    would produce a verdict about a tree the controller never named.


def test_a_candidate_only_the_configured_repository_has_is_refused(repos):
    with pytest.raises(gemini_worker.ReviewRepoUnusable) as raised:
        gemini_worker.resolve_review_repo(
            activation(str(repos["named"]), repos["configured_sha"]),
            repos["configured_sha"],
            configured=str(repos["configured"]),
        )

    assert "does not contain candidate" in raised.value.reason
    assert "not falling back" in raised.value.reason
    # And it still records both paths.
    assert raised.value.detail["repo_location"] == str(repos["named"])
    assert raised.value.detail["review_repo"] == str(repos["configured"])


# 4. No repository on the activation falls back to the environment.


def test_an_activation_naming_no_repository_falls_back(repos):
    repo, detail = gemini_worker.resolve_review_repo(
        activation(None, repos["configured_sha"]),
        repos["configured_sha"],
        configured=str(repos["configured"]),
    )

    assert repo == str(repos["configured"])
    assert detail["repo_source"] == "environment"


def test_no_repository_anywhere_is_refused(repos):
    with pytest.raises(gemini_worker.ReviewRepoUnusable) as raised:
        gemini_worker.resolve_review_repo(
            activation(None, repos["named_sha"]), repos["named_sha"],
            configured="",
        )

    assert "named no repo_location" in raised.value.reason


# 5. Nothing fetches, on any path.


@pytest.mark.parametrize("case", ["present", "absent", "missing", "not_a_repo"])
def test_no_git_fetch_happens_on_any_path(repos, tmp_path, monkeypatch, case):
    """A reviewer that reaches for the network to find the commit it was told
    to review is answering a different question than the one asked."""
    seen = []
    real = subprocess.run

    def recording(args, **kwargs):
        seen.append(list(args))
        return real(args, **kwargs)

    monkeypatch.setattr(gemini_worker.subprocess, "run", recording)

    located = {
        "present": (str(repos["named"]), repos["named_sha"]),
        "absent": (str(repos["named"]), repos["configured_sha"]),
        "missing": (str(tmp_path / "nowhere"), repos["named_sha"]),
        "not_a_repo": (str(tmp_path), repos["named_sha"]),
    }[case]

    try:
        gemini_worker.resolve_review_repo(
            activation(located[0], located[1]), located[1],
            configured=str(repos["configured"]),
        )
    except gemini_worker.ReviewRepoUnusable:
        pass

    # Compare the git subcommand, never the rendered command line: the temp
    # directory contains this test's own name, so a substring check for
    # "fetch" matches the path and passes or fails for the wrong reason.
    subcommands = [c[3] for c in seen if len(c) > 3 and c[:2] == ["git", "-C"]]

    if case == "missing":
        # Refused on the path check, before git is invoked at all. Stronger
        # than "did not fetch": it did not reach for the repository at all.
        assert subcommands == [], subcommands
    else:
        assert subcommands, seen

    assert not ({"fetch", "pull", "remote", "clone"} & set(subcommands)), subcommands


# 6. The refusal is an environment defect: repairable, and not an attempt.


def test_the_refusal_is_reported_as_blocked_not_as_a_verdict(repos, monkeypatch):
    """`blocked` maps to `environment_defect`, which reaches REVIEW_BLOCKED and
    is repairable; `changes_requested` would record a judgment about a change
    nobody looked at, and would spend the author's budget doing it."""
    submitted = {}

    class Queue:
        def judge(self, activation_id, judgment, payload=None):
            submitted.update(activation_id=activation_id, judgment=judgment,
                             payload=payload or {})

    monkeypatch.setattr(gemini_worker, "REVIEW_REPO", str(repos["configured"]))

    gemini_worker.execute_review(
        None, None,
        {"activation_id": "a1", "repo_location": str(repos["named"]),
         "expected_branch": "task/x", "expected_parent": repos["named_sha"],
         "expected_candidate": repos["configured_sha"]},
        Queue(),
    )

    assert submitted["judgment"] == "blocked"
    assert "does not contain candidate" in submitted["payload"]["reason"]
    assert submitted["payload"]["repo_location"] == str(repos["named"])
    assert submitted["payload"]["review_repo"] == str(repos["configured"])


def test_environment_defect_does_not_charge_an_author_attempt():
    """`_finalize(uncharge=...)` keys on the transition, and
    `environment_defect` is the kind it uncharges -- a run that never got far
    enough to judge is not an attempt (#21)."""
    from controller import outcomes

    # In `controller.outcomes` since #61 split the terminal-submission path.
    assert outcomes.REVIEW_JUDGMENTS["blocked"][0] == "environment_defect"
