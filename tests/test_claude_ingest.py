"""Real fetch/CAS tests with a local forge and stubbed GitHub metadata."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import replace

import pytest

import claude_ingest as ingest


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


class Forge(ingest.Commands):
    def __init__(self, metadata, **kwargs):
        super().__init__(kwargs.get("remaining", 60), kwargs.get("heartbeat", lambda: True))
        self.metadata = metadata
        self.commands = []
        self.missing = False

    def run(self, args, repo, **kwargs):
        self.commands.append(args)
        if args[0] == "gh":
            self.checkpoint()
            if "/pulls/" not in args[-1]:
                return 0, json.dumps({"full_name": "Owner/Repo"})
            if self.missing:
                raise ingest.IngestError("not_found", command="gh")
            return 0, json.dumps(self.metadata)
        return super().run(args, repo, **kwargs)


@pytest.fixture
def fixture(tmp_path):
    source, remote, checkout = (tmp_path / name for name in ("source", "remote.git", "checkout"))
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.email", "author@example.test")
    git(source, "config", "user.name", "Test")
    (source / "base.txt").write_text("baseline\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "baseline")
    base = git(source, "rev-parse", "HEAD")
    git(source, "checkout", "-b", "candidate")
    (source / "new.txt").write_text("candidate\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "change\n\nCo-Authored-By: Agent <noreply@anthropic.com>")
    head = git(source, "rev-parse", "HEAD")
    git(source, "clone", "--bare", str(source), str(remote))
    git(remote, "update-ref", "refs/pull/7/head", head)
    git(source, "clone", "--single-branch", "--branch", "main", str(remote), str(checkout))
    identity = hashlib.sha256(base.encode()).hexdigest()[:16]
    registry = tmp_path / "repos.json"
    registry.write_text(json.dumps({"demo": {"path": str(checkout), "repo_id": identity,
        "planning_ref": "refs/heads/main", "worktree_root": str(tmp_path / "worktrees"),
        "publish": {"repo_slug": "Owner/Repo", "target_ref": "refs/heads/main"}}}))
    request = ingest.Request("EXT-1", "act-1", "demo", str(checkout), "owner/repo", 7)
    metadata = {"head": {"sha": head}, "base": {"sha": base}, "number": 7,
        "html_url": "https://github.com/OWNER/REPO/pull/7", "state": "open", "draft": False,
        "body": "Generated with Claude Code", "title": "Change", "user": {"login": "operator"}}
    return request, registry, Forge(metadata), source, remote, checkout, base, head


def run(fixture, **kwargs):
    request, registry, commands, *_ = fixture
    return ingest.ingest(request, remaining=60, heartbeat=lambda: True,
                         registry=registry, commands=commands, **kwargs)


@pytest.mark.parametrize("state,draft,merged", [("open",False,None), ("open",True,None),
                                               ("closed",False,None), ("closed",False,"2026-10-15")])
def test_pins_all_pr_states_without_touching_worktree(fixture, state, draft, merged):
    request, _, commands, _, _, checkout, base, head = fixture
    commands.metadata.update(state=state, draft=draft, merged_at=merged)
    before = (git(checkout, "rev-parse", "HEAD"), git(checkout, "status", "--porcelain"))
    evidence = run(fixture)
    assert evidence["head_sha"] == evidence["resolved_ref_sha"] == head
    assert evidence["base_ref_sha"] == evidence["merge_base"] == base
    assert evidence["changed_files"] == ["new.txt"]
    assert evidence["pr_state"] == state and evidence["pr_draft"] == draft
    assert evidence["pin_ref"] == "refs/swarm/external/EXT-1"
    assert git(checkout, "rev-parse", evidence["pin_ref"]) == head
    assert (git(checkout, "rev-parse", "HEAD"), git(checkout, "status", "--porcelain")) == before
    assert "Co-Authored-By" in evidence["author_signals"][0]["message"]
    assert evidence["author_signals"][-1]["body"] == commands.metadata["body"]
    fetch = next(c for c in commands.commands if "fetch" in c)
    assert f"+{base}:refs/swarm/ingest-tmp/{request.task_id}/{request.activation_id}/base" in fetch
    assert not any("checkout" in c or "push" in c for c in commands.commands)


@pytest.mark.parametrize("mode", ["operator", "moved", "missing", "conflict", "empty", "unrelated"])
def test_input_refusals_never_replace_or_create_a_bad_pin(fixture, mode):
    request, registry, commands, source, remote, checkout, base, head = fixture
    expected = {"operator":"operator_sha_mismatch", "moved":"pr_moved", "missing":"pr_not_found",
                "conflict":"pin_conflict", "empty":"empty_review_range", "unrelated":"no_common_ancestor"}
    if mode == "operator":
        fixture = (replace(request, at_sha="a"*40), *fixture[1:])
    elif mode == "moved":
        git(remote, "update-ref", "refs/pull/7/head", base)
    elif mode == "missing":
        commands.missing = True
    elif mode == "conflict":
        git(checkout, "update-ref", "refs/swarm/external/EXT-1", base)
    elif mode == "empty":
        commands.metadata["head"]["sha"] = base
        git(remote, "update-ref", "refs/pull/7/head", base)
    else:
        git(source, "checkout", "--orphan", "unrelated")
        git(source, "commit", "-m", "unrelated")
        unrelated = git(source, "rev-parse", "HEAD")
        git(source, "push", str(remote), "HEAD:refs/heads/unrelated")
        commands.metadata["base"]["sha"] = unrelated
    with pytest.raises(ingest.IngestError) as exc:
        run(fixture)
    assert exc.value.code == expected[mode] and exc.value.refusal
    pin = git(checkout, "show-ref", "--verify", "--hash", "refs/swarm/external/EXT-1", check=False)
    assert pin == (base if mode == "conflict" else "")


def test_existing_identical_pin_is_idempotent(fixture):
    first = run(fixture)
    second = run(fixture)
    assert first == second


def test_concurrent_different_pin_wins_without_being_overwritten(fixture, monkeypatch):
    _, _, commands, _, _, checkout, base, _ = fixture
    original = commands.run
    raced = []
    def race(args, repo, **kwargs):
        if "update-ref" in args and "refs/swarm/external/EXT-1" in args and not raced:
            raced.append(True)
            git(checkout, "update-ref", "refs/swarm/external/EXT-1", base)
        return original(args, repo, **kwargs)
    monkeypatch.setattr(commands, "run", race)
    with pytest.raises(ingest.IngestError, match="pin_conflict") as exc:
        run(fixture)
    assert exc.value.refusal and raced
    assert git(checkout, "rev-parse", "refs/swarm/external/EXT-1") == base


def test_merged_pr_fetches_a_base_object_missing_from_the_checkout(fixture):
    _, _, commands, source, remote, checkout, base, _ = fixture
    git(source, "checkout", "main")
    (source / "later-base.txt").write_text("later target commit\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "target advanced")
    advanced = git(source, "rev-parse", "HEAD")
    git(source, "push", str(remote), "HEAD:refs/heads/main")
    absent = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", advanced], capture_output=True)
    assert absent.returncode != 0
    commands.metadata.update(state="closed", merged_at="2026-10-15")
    commands.metadata["base"]["sha"] = advanced
    evidence = run(fixture)
    assert evidence["base_ref_sha"] == advanced and evidence["merge_base"] == base


def test_lost_lease_after_pin_leaves_only_an_orphan_not_accepted_evidence(fixture):
    _, _, commands, _, _, checkout, _, head = fixture
    pin = "refs/swarm/external/EXT-1"
    commands.heartbeat = lambda: not bool(git(checkout, "show-ref", "--verify", "--hash", pin, check=False))
    with pytest.raises(ingest.IngestError, match="lease_lost"):
        run(fixture)
    assert git(checkout, "rev-parse", pin) == head


@pytest.mark.parametrize("mode", ["slug", "path", "base_missing", "identity", "metadata"])
def test_environment_defects_are_not_judgments_on_the_pr(fixture, mode):
    request, registry, commands, _, _, _, _, _ = fixture
    if mode == "slug":
        fixture = (replace(request, repo_slug="wrong/repo"), *fixture[1:])
    elif mode == "path":
        fixture = (replace(request, repo_location=str(registry.parent)), *fixture[1:])
    elif mode == "base_missing":
        commands.metadata["base"]["sha"] = "a"*40
    elif mode == "identity":
        data = json.loads(registry.read_text())
        data["demo"]["repo_id"] = "wrong"
        registry.write_text(json.dumps(data))
    else:
        commands.metadata["head"] = []
    with pytest.raises(ingest.IngestError) as exc:
        run(fixture)
    assert not exc.value.refusal


def test_only_proven_stale_refs_of_the_same_task_are_deleted(fixture):
    _, _, _, _, _, checkout, base, _ = fixture
    stale = "refs/swarm/ingest-tmp/EXT-1/expired/head"
    live = "refs/swarm/ingest-tmp/EXT-1/live/base"
    unknown = "refs/swarm/ingest-tmp/EXT-1/unknown/head"
    other = "refs/swarm/ingest-tmp/EXT-2/expired/head"
    for ref in (stale,live,unknown,other):
        git(checkout, "update-ref", ref, base)
    run(fixture, scratch_is_live=lambda aid: {"expired":False,"live":True}.get(aid))
    assert not git(checkout, "show-ref", "--verify", "--hash", stale, check=False)
    for ref in (live,unknown,other):
        assert git(checkout, "rev-parse", ref) == base


def test_complete_evidence_overflow_refuses_before_final_pin(fixture, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_EVIDENCE", 1800)
    fixture[2].metadata["body"] = "x"*2000
    with pytest.raises(ingest.IngestError, match="evidence_too_large") as exc:
        run(fixture)
    assert exc.value.refusal
    assert not git(fixture[5], "show-ref", "--verify", "--hash", "refs/swarm/external/EXT-1", check=False)


def test_exhausted_deadline_and_lost_lease_stop_commands(tmp_path):
    with pytest.raises(ingest.IngestError, match="deadline_exhausted"):
        ingest.Commands(0, lambda: True)
    for live in (False, None):
        command = ingest.Commands(5, lambda: live)
        with pytest.raises(ingest.IngestError, match="lease_lost"):
            command.run([sys.executable, "-c", "raise AssertionError('must not run')"], tmp_path)


def test_long_command_stops_at_remaining_deadline(tmp_path):
    command = ingest.Commands(1.2, lambda: True)
    started = time.monotonic()
    with pytest.raises(ingest.IngestError, match="deadline_exhausted"):
        command.run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path)
    assert time.monotonic() - started < 5


def test_expired_budget_cannot_start_a_command(tmp_path, monkeypatch):
    command = ingest.Commands(5, lambda: True)
    command.deadline = time.monotonic() - 1
    def forbidden(*args, **kwargs):
        raise AssertionError("command started after deadline")
    monkeypatch.setattr(ingest.subprocess, "Popen", forbidden)
    with pytest.raises(ingest.IngestError, match="deadline_exhausted"):
        command.run(["gh", "api", "repos/owner/repo"], tmp_path)


def test_process_failure_never_exposes_stderr(tmp_path):
    command = ingest.Commands(5, lambda: True)
    with pytest.raises(ingest.IngestError) as exc:
        command.run([sys.executable, "-c", "import sys; sys.stderr.write('private token'); sys.exit(7)"], tmp_path)
    assert exc.value.code == "command_failed"
    assert "private" not in str(exc.value) + str(exc.value.facts)


def test_command_output_is_bounded_without_truncating_accepted_evidence(tmp_path):
    command = ingest.Commands(5, lambda: True)
    with pytest.raises(ingest.IngestError, match="evidence_too_large") as exc:
        command.run([sys.executable, "-c", f"print('x'*{ingest.MAX_EVIDENCE + 1})"], tmp_path, evidence=True)
    assert exc.value.refusal


def test_oversized_transport_diagnostics_are_an_environment_problem(tmp_path):
    command = ingest.Commands(5, lambda: True)
    with pytest.raises(ingest.IngestError, match="diagnostic_overflow") as exc:
        command.run([sys.executable, "-c", f"import sys; sys.stderr.write('x'*{ingest.MAX_EVIDENCE + 1})"], tmp_path)
    assert not exc.value.refusal


def test_non_evidence_command_overflow_is_not_a_pr_refusal(tmp_path):
    command = ingest.Commands(5, lambda: True)
    with pytest.raises(ingest.IngestError, match="command_output_overflow") as exc:
        command.run([sys.executable, "-c", f"print('x'*{ingest.MAX_EVIDENCE + 1})"], tmp_path)
    assert not exc.value.refusal
