"""The authoring path, from an activation to a commit or a refusal.

`execute_author` had no test at all: it was only ever exercised live, one paid
model call at a time. The scope correction runs inside it, and "the parser
refuses" is not the same claim as "the worker refuses before it pays for a
generation" -- so the model client here raises if it is called, which turns the
count into an assertion rather than a hope.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import authored_change
import chatgpt_worker
import repo_registry
import repo_snapshot


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def author_repo(tmp_path, monkeypatch):
    """A registered project whose canonical checkout is dirty, as they are.

    The worker never writes here. This is the shape the real one has:
    somebody is mid-edit, and that must neither stop an authoring run nor
    contaminate one.
    """
    root = tmp_path / "work"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "worker@test")
    git(root, "config", "user.name", "Worker Test")
    (root / "README.md").write_text("# project\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "existing.txt").write_text("old\n", encoding="utf-8")
    (root / "build.sh").write_text("echo build\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")

    # A person's unsaved work, present throughout every test below.
    (root / "notes" / "existing.txt").write_text("edited\n", encoding="utf-8")

    registry = tmp_path / "repos.json"
    registry.write_text(json.dumps({
        "demo": {
            "path": str(root),
            "repo_id": repo_snapshot.repo_id(str(root)),
            "planning_ref": "refs/heads/main",
            "worktree_root": str(tmp_path / "worktrees"),
        }
    }), encoding="utf-8")

    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)
    monkeypatch.setattr(chatgpt_worker, "AUTHOR_PROJECT", "demo")
    return root


def base_of(repo):
    return git(repo, "rev-parse", "HEAD").strip()


class Queue:
    """Records what the worker reported, in order."""

    def __init__(self):
        self.reports = []

    def report(self, activation_id, *, outcome, payload=None):
        self.reports.append({
            "activation_id": activation_id,
            "outcome": outcome,
            "payload": payload or {},
        })

    @property
    def last(self):
        assert self.reports, "the worker reported nothing at all"
        return self.reports[-1]


class NeverCalled:
    """A model client that fails the test if anything asks it for a reply."""

    calls = 0

    def __getattr__(self, name):
        raise AssertionError(
            f"the model was called ({name}) -- the refusal must happen first"
        )


@pytest.fixture
def counted_reply(monkeypatch):
    """Replaces the model call with a scripted answer, counting the calls."""
    state = {"calls": 0, "answer": ""}

    def fake_generate_reply(client, messages):
        state["calls"] += 1
        state["prompt"] = messages[0]["content"]
        return state["answer"]

    monkeypatch.setattr(chatgpt_worker, "generate_reply", fake_generate_reply)
    return state


def activation(contract, *, base, allowed=None, title="add a note"):
    """One author activation, carrying the baseline the controller resolved.

    `base_sha` comes from the task record because the controller decides what
    is branched from. A worker choosing for itself would be choosing what gets
    reviewed.
    """
    return {
        "activation_id": "A-1",
        "task_id": "T-1",
        "expected_branch": "task/T-1-a1",
        "task_record": {
            "title": title,
            "base_sha": base,
            "objective": "add a note",
            "contract_yaml": contract,
            "allowed_paths": allowed,
        },
    }


CONTRACT = "task_id: T-1\nallowed_paths:\n  - notes\n"
ANSWER = (
    "FILE: notes/hello.txt\n"
    f"{authored_change.BEGIN}\n"
    "hello\n"
    f"{authored_change.END}\n"
)


# --- A contract that says nothing stops the work before it costs anything ----


@pytest.mark.parametrize("contract", [
    "task_id: T-1\ntitle: add a note\n",          # no allowed_paths at all
    "",                                            # empty contract
    "allowed_paths:\ntitle: x\n",                  # the key, no entries
    "allowed_paths: []",                           # an empty list
    "task_id: T-1\nallowed_pa",                    # truncated mid-key
    "allowed_paths: everything",                   # a scalar nobody can parse
])
def test_an_unusable_contract_blocks_before_the_model_is_called(
    author_repo, contract
):
    """The refusal is the point; that it is free is why it is placed here.

    Every one of these used to mean "unrestricted". Each is a shape a contract
    genuinely arrives in -- half-written, truncated by a token limit, or in a
    dialect this parser has never seen.
    """
    queue = Queue()
    chatgpt_worker.execute_author(NeverCalled(), activation(contract, base=base_of(author_repo)), queue)

    assert queue.last["outcome"] == "blocked"
    assert "authorise" in queue.last["payload"]["reason"]


def test_a_blocked_contract_leaves_the_repository_untouched(author_repo):
    before = git(author_repo, "status", "--porcelain")
    queue = Queue()
    chatgpt_worker.execute_author(
        NeverCalled(), activation("title: x\n", base=base_of(author_repo)), queue
    )

    assert git(author_repo, "status", "--porcelain") == before
    assert git(author_repo, "branch", "--list", "task/T-1-a1").strip() == ""


# --- A contract that says something is honoured ------------------------------


def test_a_scoped_contract_authors_one_commit_with_one_model_call(
    author_repo, counted_reply
):
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT, base=base_of(author_repo)), queue)

    assert counted_reply["calls"] == 1
    assert queue.last["outcome"] == "candidate"
    assert queue.last["payload"]["files"] == ["notes/hello.txt"]
    assert len(queue.last["payload"]["candidate_sha"]) == 40


def test_the_prompt_names_the_paths_the_task_may_touch(
    author_repo, counted_reply
):
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(object(), activation(CONTRACT, base=base_of(author_repo)), Queue())

    assert "notes" in counted_reply["prompt"]


def test_a_file_outside_the_scope_fails_the_attempt(author_repo, counted_reply):
    """The model answered; the answer was not one it was allowed to give."""
    counted_reply["answer"] = (
        "FILE: build.sh\n"
        f"{authored_change.BEGIN}\n"
        "rm -rf /\n"
        f"{authored_change.END}\n"
    )
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT, base=base_of(author_repo)), queue)

    assert queue.last["outcome"] == "failed"
    assert (author_repo / "build.sh").read_text(encoding="utf-8") == "echo build\n"
    assert git(author_repo, "branch", "--list", "task/T-1-a1").strip() == ""


def test_the_controllers_own_allowed_paths_are_honoured(
    author_repo, counted_reply
):
    """A contract this parser cannot read is fine if the record states it."""
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation("nothing parseable here", base=base_of(author_repo), allowed=["notes"]), queue
    )

    assert queue.last["outcome"] == "candidate"


def test_the_explicit_marker_authors_repository_wide(author_repo, counted_reply):
    """Reachable, deliberately -- and only from the marker."""
    counted_reply["answer"] = (
        "FILE: anywhere.txt\n"
        f"{authored_change.BEGIN}\n"
        "x\n"
        f"{authored_change.END}\n"
    )
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation("allowed_paths: UNRESTRICTED\n", base=base_of(author_repo)), queue
    )

    assert queue.last["outcome"] == "candidate"
    assert queue.last["payload"]["files"] == ["anywhere.txt"]


# --- The other refusals on this path ----------------------------------------


def test_a_dirty_canonical_checkout_does_not_stop_authoring(
    author_repo, counted_reply
):
    """The correction to the earlier rule, which refused outright.

    Refusing whenever somebody had unsaved work was the right instinct in the
    wrong place: the canonical checkout is dirty most of the time, so the
    check fired constantly and would have been switched off. The isolation is
    what makes the unsaved work irrelevant instead of blocking.
    """
    (author_repo / "someone_elses.txt").write_text("edit\n", encoding="utf-8")
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), queue
    )

    assert queue.last["outcome"] == "candidate"
    assert (author_repo / "someone_elses.txt").read_text(encoding="utf-8") == "edit\n"


def test_the_candidate_does_not_contain_the_checkouts_uncommitted_work(
    author_repo, counted_reply
):
    """The thing isolation is for.

    `notes/existing.txt` is edited in the checkout and not committed. It must
    not appear in the candidate's diff, attributed to the model.
    """
    counted_reply["answer"] = ANSWER
    queue = Queue()
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), queue
    )

    candidate = queue.last["payload"]["candidate_sha"]
    changed = git(author_repo, "diff", "--name-only", f"{base_of(author_repo)}..{candidate}")

    assert changed.split() == ["notes/hello.txt"]


def test_the_worktree_is_taken_away_once_the_commit_exists(
    author_repo, counted_reply, tmp_path
):
    """The branch holds the candidate; the tree has done its job."""
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), Queue()
    )

    assert not (tmp_path / "worktrees" / "A-1").exists()
    assert git(author_repo, "branch", "--list", "task/T-1-a1").strip()


def test_a_model_that_returns_nothing_is_blocked_not_failed(
    author_repo, counted_reply
):
    counted_reply["answer"] = None
    queue = Queue()
    chatgpt_worker.execute_author(object(), activation(CONTRACT, base=base_of(author_repo)), queue)

    assert queue.last["outcome"] == "blocked"


# --- A retry is told what was wrong -----------------------------------------


def test_a_retry_carries_the_reviewers_words_into_the_prompt(
    author_repo, counted_reply
):
    """Otherwise the second attempt is the first one re-rolled.

    The budget in `authorize_retry` calls two rejections in a row a loop for
    exactly this reason. Feeding the rationale back is what makes an attempt
    an attempt at the correction.
    """
    counted_reply["answer"] = ANSWER
    act = activation(CONTRACT, base=base_of(author_repo))
    act["task_record"]["last_rejection"] = {
        "rationale": "the file is missing the trailing newline the objective asks for",
    }
    act["expected_branch"] = "task/T-1-a2"

    chatgpt_worker.execute_author(object(), act, Queue())

    assert "REJECTED IN REVIEW" in counted_reply["prompt"]
    assert "trailing newline" in counted_reply["prompt"]


def test_a_first_attempt_is_not_told_about_a_rejection_that_did_not_happen(
    author_repo, counted_reply
):
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), Queue()
    )

    assert "REJECTED IN REVIEW" not in counted_reply["prompt"]


# --- An author cannot edit what it has not been shown ------------------------


def test_the_prompt_carries_the_current_contents_of_in_scope_files(
    author_repo, counted_reply
):
    """The correction a live run forced.

    Asked to reword one sentence in README.md and preserve the rest, an author
    that had never seen the file produced a plausible README for a different
    project -- a hackathon in 2020, an MIT licence -- and dropped every line it
    was told to keep. The output format demands the complete file, so with
    nothing to copy from, inventing was the only move available to it.
    """
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), Queue()
    )

    assert "AS THEY ARE NOW" in counted_reply["prompt"]
    # notes/existing.txt is in scope and committed; its baseline content, not
    # the edited copy sitting in the checkout.
    assert "notes/existing.txt" in counted_reply["prompt"]
    assert "old" in counted_reply["prompt"]
    assert "edited" not in counted_reply["prompt"]


def test_files_outside_the_scope_are_not_shown(author_repo, counted_reply):
    """The prompt is not a place to leak the rest of the repository."""
    counted_reply["answer"] = ANSWER
    chatgpt_worker.execute_author(
        object(), activation(CONTRACT, base=base_of(author_repo)), Queue()
    )

    assert "build.sh" not in counted_reply["prompt"]


def test_an_unrestricted_scope_is_not_shown_the_whole_tree(author_repo):
    """A task authorised everywhere has no relevant files to guess at."""
    scope = authored_change.Scope.everywhere()

    assert authored_change.existing_in_scope(
        str(author_repo), base_of(author_repo), scope
    ) == []


def test_a_file_too_large_to_show_tells_the_author_to_refuse(author_repo):
    """Half a file is worse than none: it reads as the whole file."""
    scope = authored_change.Scope.restricted_to(["notes"])
    shown = authored_change.existing_in_scope(
        str(author_repo), base_of(author_repo), scope, per_file=2
    )

    assert shown[0]["truncated"] is True

    prompt = authored_change.render_author_prompt(
        {"task_id": "T-1", "objective": "o", "allowed_paths": ["notes"]}, shown
    )
    assert "CANNOT_AUTHOR" in prompt
    assert "IS TRUNCATED" in prompt
