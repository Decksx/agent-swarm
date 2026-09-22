"""A review never reaches the network, and that is enforced rather than assumed.

The first version of #64 asserted "nothing fetches" by checking the git
subcommands this code launches. That check cannot see the thing it claims to
prevent: in a partial or promisor clone, `cat-file`, `diff` and `rev-parse`
fetch missing objects *from inside git*, with nothing here running `git fetch`.
A reviewer in such a checkout would have silently obtained a candidate the
repository did not hold -- which is precisely the "present or obtainable"
behaviour #64 exists to refuse, arriving through a door the test was not
watching.

So these tests work two ways: every git invocation carries
`GIT_NO_LAZY_FETCH=1`, and a real promisor clone missing the object refuses
rather than fetching it.
"""

from __future__ import annotations

import subprocess

import pytest

import gemini_worker
import review_packet


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          encoding="utf-8", errors="replace", check=check)


def out(repo, *args):
    return git(repo, *args).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    """A repository with two commits, serving partial clones."""
    path = tmp_path / "origin"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    # Required for --filter over the local transport.
    git(path, "config", "uploadpack.allowFilter", "true")
    git(path, "config", "uploadpack.allowAnySHA1InWant", "true")

    (path / "README.md").write_text("one\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "one")
    base = out(path, "rev-parse", "HEAD")

    (path / "README.md").write_text("one\ntwo\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "two")
    candidate = out(path, "rev-parse", "HEAD")

    return {"path": path, "base": base, "candidate": candidate}


# --- The environment every git call runs under -------------------------------


def test_offline_env_disables_lazy_fetch_and_credential_prompts():
    env = review_packet.offline_env({"PATH": "/usr/bin"})

    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # And it does not discard the inherited environment, which git needs to
    # find itself and its config.
    assert env["PATH"] == "/usr/bin"


@pytest.mark.parametrize("case", ["present", "absent", "not_a_repo"])
def test_every_git_call_from_the_worker_runs_offline(tmp_path, monkeypatch, case):
    """The check a subcommand allowlist cannot make."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "f").write_text("x\n", encoding="utf-8")
    git(repo, "add", "f")
    git(repo, "commit", "-qm", "c")
    sha = out(repo, "rev-parse", "HEAD")

    envs = []
    real = subprocess.run

    def recording(args, **kwargs):
        envs.append(kwargs.get("env"))
        return real(args, **kwargs)

    monkeypatch.setattr(gemini_worker.subprocess, "run", recording)

    located = {
        "present": (str(repo), sha),
        "absent": (str(repo), "0" * 40),
        "not_a_repo": (str(tmp_path), sha),
    }[case]

    try:
        gemini_worker.resolve_review_repo(
            {"activation_id": "a1", "repo_location": located[0]},
            located[1], configured="",
        )
    except gemini_worker.ReviewRepoUnusable:
        pass

    assert envs, "expected at least one git call"

    for env in envs:
        assert env is not None, "a git call inherited the ambient environment"
        assert env.get("GIT_NO_LAZY_FETCH") == "1"


def test_every_git_call_from_the_packet_builder_runs_offline(origin, monkeypatch):
    envs = []
    real = subprocess.run

    def recording(args, **kwargs):
        envs.append(kwargs.get("env"))
        return real(args, **kwargs)

    monkeypatch.setattr(review_packet.subprocess, "run", recording)

    review_packet.build(
        str(origin["path"]),
        task={"task_id": "T-1", "title": "t", "objective": "o"},
        base=origin["base"], candidate=origin["candidate"],
    )

    assert envs
    for env in envs:
        assert env is not None
        assert env.get("GIT_NO_LAZY_FETCH") == "1"


# --- A real promisor clone ---------------------------------------------------


@pytest.fixture
def promisor(origin, tmp_path):
    """A partial clone whose blobs live only on the promisor remote."""
    clone = tmp_path / "partial"
    result = subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-local", "-q",
         origin["path"].as_uri(), str(clone)],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )

    if result.returncode != 0:
        pytest.skip(f"partial clone unsupported here: {result.stderr.strip()[:200]}")

    if not out(clone, "config", "--get", "remote.origin.promisor"):
        pytest.skip("clone did not register a promisor remote")

    return {"path": clone, **{k: v for k, v in origin.items() if k != "path"},
            "origin": origin["path"]}


def test_a_promisor_clone_does_not_fetch_to_satisfy_the_candidate_check(promisor):
    """The object is present, so this passes -- and must pass without the
    network, which is what the offline environment guarantees."""
    repo, detail = gemini_worker.resolve_review_repo(
        {"activation_id": "a1", "repo_location": str(promisor["path"])},
        promisor["candidate"], configured="",
    )

    assert repo == str(promisor["path"])
    assert detail["repo_source"] == "activation"


def test_a_promisor_clone_refuses_an_object_only_the_remote_has(promisor):
    """The case that matters. A commit the clone does not hold must be absent,
    not fetched -- even though a reachable promisor remote could supply it."""
    extra = promisor["origin"]
    (extra / "README.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    git(extra, "add", "README.md")
    git(extra, "commit", "-qm", "three")
    only_on_remote = out(extra, "rev-parse", "HEAD")

    with pytest.raises(gemini_worker.ReviewRepoUnusable) as raised:
        gemini_worker.resolve_review_repo(
            {"activation_id": "a1", "repo_location": str(promisor["path"])},
            only_on_remote, configured="",
        )

    assert "does not contain candidate" in raised.value.reason

    # And it really is still only on the remote: nothing pulled it across.
    #
    # This verification must itself run offline. Written without the
    # environment it fetched the object while checking for it, and the
    # assertion failed because the check had just created the thing it was
    # looking for -- which is the defect under test, reproduced by the test.
    assert subprocess.run(
        ["git", "-C", str(promisor["path"]), "cat-file", "-e",
         f"{only_on_remote}^{{commit}}"],
        capture_output=True, check=False, env=review_packet.offline_env(),
    ).returncode != 0


def test_without_the_offline_environment_git_fetches_the_object_itself(promisor):
    """Why the environment is load-bearing rather than decorative.

    Same repository, same commit, same subcommand -- only the environment
    differs. Unguarded, `cat-file -e` reaches the promisor remote and succeeds
    on an object the clone does not hold, so a "is the candidate present"
    check would answer "yes" about something it had just downloaded.
    """
    extra = promisor["origin"]
    (extra / "README.md").write_text("one\ntwo\nfour\n", encoding="utf-8")
    git(extra, "add", "README.md")
    git(extra, "commit", "-qm", "four")
    only_on_remote = out(extra, "rev-parse", "HEAD")

    guarded = subprocess.run(
        ["git", "-C", str(promisor["path"]), "cat-file", "-e",
         f"{only_on_remote}^{{commit}}"],
        capture_output=True, check=False, env=review_packet.offline_env(),
    )

    assert guarded.returncode != 0, "the guarded check should not find it"

    unguarded = subprocess.run(
        ["git", "-C", str(promisor["path"]), "cat-file", "-e",
         f"{only_on_remote}^{{commit}}"],
        capture_output=True, check=False,
    )

    if unguarded.returncode != 0:
        pytest.skip("this git did not lazily fetch; the guard is still correct")

    assert unguarded.returncode == 0


def test_the_packet_builder_fails_closed_when_blobs_are_unreachable(promisor):
    """A partial clone whose promisor remote has gone away cannot produce a
    diff. It must fail, not hang on a fetch or a credential prompt."""
    # Not `rmtree`: a git object store is read-only on Windows and removing it
    # fails for reasons unrelated to this test. Pointing the promisor remote
    # at nothing is the same condition -- the blobs cannot be obtained.
    git(promisor["path"], "remote", "set-url", "origin",
        (promisor["origin"].parent / "gone").as_uri())

    with pytest.raises(review_packet.PacketError):
        review_packet.build(
            str(promisor["path"]),
            task={"task_id": "T-1", "title": "t", "objective": "o"},
            base=promisor["base"], candidate=promisor["candidate"],
        )
