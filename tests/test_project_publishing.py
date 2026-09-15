"""A project that publishes gets every candidate pushed and proposed (#32).

Chat-started tasks default to `branch_only`, and until now `branch_only` meant
"never published". The integrator lands only a candidate with an open pull
request, so every approved chat task stopped at integration until somebody
pushed its branch and opened the PR by hand.

Where a repository's candidates go is a property of the repository. These
check the three places that decision now lives: the registry that states it,
`publication` that applies it, and both authors that call it -- against real
git repositories and a real bare remote, with only `gh` scripted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import chatgpt_worker
import claude_worker
import publication
import repo_registry
import repo_snapshot
from publication import PublicationError, Target
from repo_registry import RegistryError
from test_author_activation import ANSWER, CONTRACT
from test_author_activation import activation as chatgpt_activation


def git(repo, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    if check:
        assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"

    return result.stdout.strip()


ENTRY = {
    "path": "C:\\git\\x",
    "repo_id": "abc",
    "planning_ref": "refs/heads/main",
    "worktree_root": "C:\\git\\.wt-x",
}


# --- The registry states it, strictly ----------------------------------------


def test_a_publish_block_is_read():
    project = repo_registry.parse("x", {**ENTRY, "publish": {
        "repo_slug": "Decksx/agent-swarm", "target_ref": "refs/heads/main"}})

    assert project.publish_repo_slug == "Decksx/agent-swarm"
    assert project.publish_target_ref == "refs/heads/main"
    assert project.as_dict()["publish"] == {
        "repo_slug": "Decksx/agent-swarm", "target_ref": "refs/heads/main"}


def test_no_publish_block_publishes_nothing_and_says_nothing():
    project = repo_registry.parse("x", dict(ENTRY))

    assert project.publish_repo_slug == "" and project.publish_target_ref == ""
    assert "publish" not in project.as_dict()


@pytest.mark.parametrize("block,named", [
    ("Decksx/agent-swarm", "must be an object"),
    ({"repo_slug": "o/r", "target_ref": "refs/heads/main", "force": True},
     "unknown keys"),
    ({"target_ref": "refs/heads/main"}, "repo_slug"),
    ({"repo_slug": "--help", "target_ref": "refs/heads/main"}, "repo_slug"),
    ({"repo_slug": "o/r/extra", "target_ref": "refs/heads/main"}, "repo_slug"),
    ({"repo_slug": "o/r"}, "target_ref"),
    ({"repo_slug": "o/r", "target_ref": "main"}, "target_ref"),
    ({"repo_slug": "o/r", "target_ref": "refs/tags/v1"}, "target_ref"),
    ({"repo_slug": "o/r", "target_ref": "refs/heads/"}, "target_ref"),
])
def test_a_malformed_publish_block_is_refused(block, named):
    with pytest.raises(RegistryError, match=named):
        repo_registry.parse("x", {**ENTRY, "publish": block})


def test_the_committed_registry_publishes_agenthub_and_nothing_else():
    registry = json.loads(
        (Path(repo_registry.__file__).parent / "repos.json").read_text("utf-8"))
    projects = {name: repo_registry.parse(name, entry)
                for name, entry in registry.items()}

    assert projects["agenthub"].publish_repo_slug == "Decksx/agent-swarm"
    assert projects["agenthub"].publish_target_ref == "refs/heads/main"
    assert projects["comicautomation"].publish_repo_slug == ""


# --- publication applies it ---------------------------------------------------


PUBLISHING = repo_registry.parse("x", {**ENTRY, "publish": {
    "repo_slug": "o/r", "target_ref": "refs/heads/main"}})
LOCAL = repo_registry.parse("x", dict(ENTRY))


@pytest.mark.parametrize("proof", ["branch_only", "baseline", "sabotage", None])
def test_a_publishing_project_publishes_every_proof_mode(proof):
    assert publication.target_for(PUBLISHING, proof) == Target("o/r", "refs/heads/main")


def test_the_project_block_wins_over_the_host_fallback():
    assert publication.target_for(
        PUBLISHING, "baseline", fallback_slug="other/repo",
        fallback_target_ref="refs/heads/master",
    ) == Target("o/r", "refs/heads/main")


def test_the_host_fallback_applies_without_a_block():
    assert publication.target_for(
        LOCAL, "branch_only", fallback_slug="h/r",
        fallback_target_ref="refs/heads/master",
    ) == Target("h/r", "refs/heads/master")


def test_branch_only_without_anywhere_to_publish_stays_local():
    assert publication.target_for(LOCAL, "branch_only") is None


@pytest.mark.parametrize("proof", ["baseline", "both", "", None])
def test_anything_else_without_anywhere_to_publish_is_refused(proof):
    with pytest.raises(PublicationError) as refused:
        publication.target_for(LOCAL, proof)

    assert "repos.json" in str(refused.value)
    assert "PUBLISH_REPO_SLUG" in str(refused.value)


TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"


@pytest.mark.parametrize("text", [
    f"fatal: unable to access 'https://x-access-token:{TOKEN}@github.com/o/r/'",
    f"remote: https://someone:hunter2@github.com/o/r.git rejected",
    f"gh: HTTP 401 for token {TOKEN}",
    "gh: github_pat_" + "11AAAAAAA0abcdefghijklmnopqrstuvwxyz",
])
def test_forge_output_is_scrubbed_of_credentials(text):
    cleaned = publication.scrub(text)

    assert TOKEN not in cleaned
    assert "hunter2" not in cleaned
    assert "github_pat_11" not in cleaned
    assert "REDACTED" in cleaned


def test_scrubbed_output_is_bounded():
    assert len(publication.scrub("x" * 5000)) == 400


def test_publish_for_scrubs_what_it_refuses_with(monkeypatch):
    def refuse(*a, **kw):
        raise PublicationError(f"could not push to https://u:{TOKEN}@github.com/o/r")

    monkeypatch.setattr(publication, "publish_candidate", refuse)

    with pytest.raises(PublicationError) as refused:
        publication.publish_for(
            PUBLISHING, Target("o/r", "refs/heads/main"), branch="task/T-1-a1",
            candidate_sha="a" * 40, task_record={"task_id": "T-1"})

    assert TOKEN not in str(refused.value)


def test_publish_for_carries_the_task_into_the_pull_request(monkeypatch):
    seen = {}
    monkeypatch.setattr(publication, "publish_candidate",
                        lambda repo, **kw: seen.update(kw, repo=repo) or {"pr_number": 3})

    result = publication.publish_for(
        PUBLISHING, Target("o/r", "refs/heads/main"), branch="task/T-1-a1",
        candidate_sha="a" * 40, activation_id="A-1",
        task_record={"task_id": "T-1", "title": "add a note", "objective": "why"},
    )

    assert result == {"pr_number": 3}
    assert seen["repo"] == str(PUBLISHING.path)
    assert (seen["repo_slug"], seen["target_ref"]) == ("o/r", "refs/heads/main")
    assert (seen["task_id"], seen["title"], seen["objective"]) == (
        "T-1", "add a note", "why")
    assert seen["activation_id"] == "A-1"


# --- Both authors call it -----------------------------------------------------


@pytest.fixture
def forge(tmp_path, monkeypatch):
    """A registered, publishing project with a real bare remote; `gh` scripted.

    The pull request listing is empty and creation answers PR #41, which is
    what a first publication sees. Every `gh` call is recorded.
    """
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")

    root = tmp_path / "canonical"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
    (root / "notes").mkdir()
    (root / "notes" / "a.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "origin", "main")

    registry = tmp_path / "repos.json"
    entry = {
        "path": str(root),
        "repo_id": repo_snapshot.repo_id(str(root)),
        "planning_ref": "refs/heads/main",
        "worktree_root": str(tmp_path / "worktrees"),
        "publish": {"repo_slug": "o/r", "target_ref": "refs/heads/main"},
    }
    registry.write_text(json.dumps({"demo": entry}), encoding="utf-8")
    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)

    calls = []

    def fake_gh(*args):
        calls.append(args)
        out = "[]" if args[:2] == ("pr", "list") else "https://github.com/o/r/pull/41\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(publication, "_gh", fake_gh)

    def unpublish():
        entry.pop("publish")
        registry.write_text(json.dumps({"demo": entry}), encoding="utf-8")

    return {"root": root, "remote": remote, "gh": calls,
            "base": git(root, "rev-parse", "HEAD"), "unpublish": unpublish,
            "worktrees": tmp_path / "worktrees"}


def remote_sha(forge, branch):
    return git(forge["remote"], "rev-parse", "--verify", "-q",
               f"refs/heads/{branch}", check=False)


class Queue:
    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({"outcome": outcome, "payload": payload or {}})

    @property
    def last(self):
        assert self.reports, "nothing was reported"
        return self.reports[-1]


def claude_activation(forge, proof="branch_only"):
    return {
        "activation_id": "act-9",
        "task_id": "T-9",
        "task": "add a note",
        "expected_branch": "task/T-9-a1",
        "source": "controller",
        "issued_by": "controller",
        "task_record": {
            "task_id": "T-9", "title": "add a note", "objective": "a note",
            "current_version": 1, "base_sha": forge["base"],
            "proof_mode": proof, "contract_hash": "a" * 64,
            "contract_yaml": "schema_version: 7\nallowed_paths:\n  - notes\n",
        },
    }


def run_claude(monkeypatch, forge, *, proof="branch_only", session=None):
    calls = {"n": 0}

    def fake_run_task(binary, prompt, cwd=None):
        calls["n"] += 1
        (Path(cwd) / "notes" / "new.txt").write_text("note\n", encoding="utf-8")
        git(cwd, "add", "-A")
        git(cwd, "commit", "-q", "-m", "add a note")
        if session:
            session(Path(cwd))
        return ("done", 0)

    monkeypatch.setattr(claude_worker, "AUTHOR_PROJECT", "demo")
    monkeypatch.setattr(claude_worker, "INFLIGHT_PATH", forge["root"].parent / "i")
    monkeypatch.setattr(claude_worker, "post_reply", lambda *a, **k: None)
    monkeypatch.setattr(claude_worker, "run_task", fake_run_task)
    queue = Queue()
    claude_worker._execute_author(None, "claude", claude_activation(forge, proof), queue)
    return queue.last, calls["n"]


def test_claude_publishes_a_branch_only_candidate_of_a_publishing_project(
    monkeypatch, forge
):
    report, _ = run_claude(monkeypatch, forge)
    tip = git(forge["root"], "rev-parse", "refs/heads/task/T-9-a1")

    assert report["outcome"] == "candidate", report
    assert report["payload"]["candidate_sha"] == tip
    assert remote_sha(forge, "task/T-9-a1") == tip
    assert report["payload"]["pr_number"] == 41
    assert report["payload"]["pr_url"] == "https://github.com/o/r/pull/41"
    assert report["payload"]["repo_slug"] == "o/r"
    assert report["payload"]["base"] == "main"


def test_claude_opens_the_pull_request_against_the_projects_target(
    monkeypatch, forge
):
    run_claude(monkeypatch, forge)
    created = [c for c in forge["gh"] if c[:2] == ("pr", "create")]

    assert len(created) == 1
    args = list(created[0])
    assert args[args.index("--repo") + 1] == "o/r"
    assert args[args.index("--base") + 1] == "main"
    assert args[args.index("--head") + 1] == "task/T-9-a1"
    assert "T-9" in args[args.index("--title") + 1]


def test_claude_reports_a_failed_publication_as_blocked(monkeypatch, forge):
    """A remote branch already at another commit is an earlier candidate."""
    git(forge["root"], "push", "-q", "origin", "main:refs/heads/task/T-9-a1")

    report, _ = run_claude(monkeypatch, forge)

    assert report["outcome"] == "blocked", report
    assert "could not be published" in report["payload"]["reason"]
    assert "candidate_sha" not in report["payload"]
    assert report["payload"]["authored_sha"]
    assert remote_sha(forge, "task/T-9-a1") == forge["base"]


def test_claude_publishes_nothing_when_the_checkout_moved(monkeypatch, forge):
    def stray(cwd):
        git(forge["root"], "switch", "-q", "-c", "feat/elsewhere")

    report, _ = run_claude(monkeypatch, forge, session=stray)

    assert report["outcome"] == "blocked"
    assert remote_sha(forge, "task/T-9-a1") == ""
    assert forge["gh"] == []


def test_claude_keeps_branch_only_local_without_a_publish_block(
    monkeypatch, forge
):
    forge["unpublish"]()
    report, _ = run_claude(monkeypatch, forge)

    assert report["outcome"] == "candidate"
    assert "pr_number" not in report["payload"]
    assert remote_sha(forge, "task/T-9-a1") == ""
    assert forge["gh"] == []


def test_claude_refuses_before_the_model_when_a_task_cannot_be_published(
    monkeypatch, forge
):
    forge["unpublish"]()
    report, model_calls = run_claude(monkeypatch, forge, proof="baseline")

    assert model_calls == 0
    assert report["outcome"] == "blocked"
    assert "repos.json" in report["payload"]["reason"]
    assert list(forge["worktrees"].glob("*")) == []


def run_chatgpt(monkeypatch, forge, *, proof="branch_only"):
    monkeypatch.setattr(chatgpt_worker, "AUTHOR_PROJECT", "demo")
    monkeypatch.setattr(chatgpt_worker, "PUBLISH_REPO_SLUG", "")
    calls = {"n": 0}

    def fake_generate_reply(client, messages):
        calls["n"] += 1
        return ANSWER

    monkeypatch.setattr(chatgpt_worker, "generate_reply", fake_generate_reply)
    act = chatgpt_activation(CONTRACT, base=forge["base"])
    act["task_record"]["proof_mode"] = proof
    queue = Queue()
    chatgpt_worker.execute_author(object(), act, queue)
    return queue.last, calls["n"]


def test_chatgpt_publishes_a_branch_only_candidate_of_a_publishing_project(
    monkeypatch, forge
):
    report, _ = run_chatgpt(monkeypatch, forge)

    assert report["outcome"] == "candidate", report
    assert remote_sha(forge, "task/T-1-a1") == report["payload"]["candidate_sha"]
    assert report["payload"]["pr_number"] == 41
    assert report["payload"]["repo_slug"] == "o/r"


def test_chatgpt_uses_the_project_block_with_no_host_setting(monkeypatch, forge):
    report, _ = run_chatgpt(monkeypatch, forge, proof="baseline")

    assert report["outcome"] == "candidate", report
    assert report["payload"]["base"] == "main"


def test_chatgpt_refuses_before_the_model_without_anywhere_to_publish(
    monkeypatch, forge
):
    forge["unpublish"]()
    report, model_calls = run_chatgpt(monkeypatch, forge, proof="baseline")

    assert model_calls == 0
    assert report["outcome"] == "blocked"
    assert "PUBLISH_REPO_SLUG" in report["payload"]["reason"]
