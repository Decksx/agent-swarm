"""The central Phase 0 claim: chat cannot cause a model to run.

These drive each worker's real ``main()`` poll loop end to end against a fake
hub, rather than asserting on a predicate in isolation. That distinction is the
point. A predicate test proves a function returns False; it does not prove the
loop has no other route to execution, and "no other route" is the actual
property Phase 0 needs.

The model call is stubbed at the exact boundary where money or shell access is
spent -- ``run_task`` for the Claude worker (which invokes ``claude -p`` with
Bash authority) and ``generate_reply`` for the two API workers. If the recorder
is ever called, containment has failed, whatever the intermediate logic did.
"""

from __future__ import annotations

import pytest

import chatgpt_worker
import claude_worker
import gemini_worker
from conftest import FakeRequests


class LoopFinished(Exception):
    """Raised from the patched sleep to end a bounded number of polls."""


def run_worker_loop(worker, monkeypatch, control, message_batches, *, polls=3):
    """Run `worker.main()` for a bounded number of poll iterations.

    Returns the recorder list of model invocations. The loop is stopped by
    making the sleep at the bottom of each iteration raise once the requested
    number of polls has happened, so every iteration runs to completion first
    and nothing is cut off mid-poll.
    """
    fake_requests = FakeRequests(message_batches)
    invocations = []

    # Never touch the operator's real state file or log.
    monkeypatch.setattr(worker, "STATE_FILE", control.CONTROL_DIR / "test.state")
    monkeypatch.setattr(worker, "configure_logging", lambda: None)
    monkeypatch.setattr(worker, "load_last_seen_id", lambda: 0)
    monkeypatch.setattr(worker, "save_last_seen_id", lambda _id: None)

    if worker is claude_worker:
        monkeypatch.setattr(worker, "ensure_requests", lambda: fake_requests)
        monkeypatch.setattr(worker.shutil, "which", lambda _n: "/fake/claude")

        def record_task(binary, task, cwd=None):
            invocations.append(task)
            return ("stub output", 0)

        monkeypatch.setattr(worker, "run_task", record_task)
    else:
        # Minimal stand-ins for the two SDKs. Neither is exercised: the model
        # boundary itself is stubbed below, so these only have to survive
        # client construction in main().
        class FakeGenAI:
            @staticmethod
            def Client(api_key=None):
                return object()

        if worker is gemini_worker:
            deps = (fake_requests, FakeGenAI, object())
        else:
            deps = (fake_requests, lambda **kwargs: object())

        monkeypatch.setattr(worker, "ensure_dependencies", lambda: deps)
        # Name-aware, not blanket. Stubbing every credential identically also
        # replaced HUB_SECRET, so the hub-auth assertions saw the model API
        # stub instead of the real hub credential and failed for the wrong
        # reason. Only the provider keys are faked here.
        real_load = worker.swarm_control.load_credential
        monkeypatch.setattr(
            worker.swarm_control,
            "load_credential",
            lambda name, **k: real_load(name) if name == "HUB_SECRET" else "stub-key",
        )

        def record_generate(*args):
            invocations.append(args[-1])
            return "stub reply"

        monkeypatch.setattr(worker, "generate_reply", record_generate)

    calls = {"n": 0}

    def bounded_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= polls:
            raise LoopFinished

        return None

    monkeypatch.setattr(worker.time, "sleep", bounded_sleep)

    with pytest.raises(LoopFinished):
        worker.main()

    return invocations, fake_requests


WORKERS = [claude_worker, chatgpt_worker, gemini_worker]
WORKER_IDS = ["claude", "chatgpt", "gemini"]


# --- Proof 1 and 2: agent-authored chat and @mentions never activate --------


@pytest.mark.parametrize("worker", WORKERS, ids=WORKER_IDS)
def test_agent_chat_and_mentions_never_invoke_a_model(
    worker, monkeypatch, control, hostile_messages
):
    """No message shape that used to be a trigger produces a model call.

    The batch covers every pre-Phase-0 trigger at once: a direct target, an
    "@ClaudeCode" mention inside content, "@chatgpt"/"@gemini" mentions, a peer
    task-result envelope, an unprefixed lowercase target, and a message whose
    `sender` claims to be Admin. The last is deliberate -- `sender` is free
    text on an unauthenticated hub, so a spoofed Admin must be no more powerful
    than any other agent.
    """
    invocations, _ = run_worker_loop(
        worker, monkeypatch, control, [hostile_messages, [], []]
    )

    assert invocations == [], (
        f"{worker.__name__} invoked a model from chat: {invocations!r}"
    )


@pytest.mark.parametrize("worker", WORKERS, ids=WORKER_IDS)
def test_no_hub_message_is_ever_addressed_to_a_peer_worker(
    worker, monkeypatch, control, hostile_messages
):
    """Nothing a worker posts is aimed at another agent.

    Replying to a peer was the return leg of the self-driving loop, so a reply
    addressed at "@Gemini" would restart it even with triggering removed.

    An activation is issued deliberately so that a reply actually gets posted.
    Without it this test passed vacuously -- chat produces no posts at all, so
    the loop below had nothing to inspect and would have stayed green with
    REPLY_TARGET set right back to "@Gemini". The bypass matrix caught that;
    the assertion that `posts` is non-empty is what keeps it caught.
    """
    control.issue_activation(worker.AGENT_IDENTITY, "produce a reply")

    _, fake_requests = run_worker_loop(
        worker, monkeypatch, control, [hostile_messages, [], []]
    )

    assert fake_requests.posts, "nothing was posted; this test would be vacuous"

    peers = {"gemini", "chatgpt", "claudecode", "claude"}
    for post in fake_requests.posts:
        target = str(post["json"].get("target", "")).strip().lstrip("@").lower()
        assert target not in peers, f"{worker.__name__} addressed a peer: {post}"


# --- Proof 3: narration stays readable and storable -------------------------


@pytest.mark.parametrize("worker", WORKERS, ids=WORKER_IDS)
def test_chat_is_still_recorded_and_readable(
    worker, monkeypatch, control, hostile_messages
):
    """Removing chat's authority must not remove its readability.

    Containment that silently dropped the conversation would pass every test
    above while destroying something the operator relies on, so the storage
    path is asserted explicitly rather than assumed.
    """
    run_worker_loop(worker, monkeypatch, control, [hostile_messages, [], []])

    stored = control.read_narration()
    assert len(stored) == len(hostile_messages)

    contents = [row["content"] for row in stored]
    assert "Run the full test suite and report back." in contents

    # Every stored row is explicitly marked non-authoritative, so anything that
    # later reads this file cannot mistake narration for an instruction.
    assert all(row["authoritative"] is False for row in stored)


def test_narration_survives_a_reread(control):
    """Storage is durable, not just in-memory for the life of the process."""
    control.record_narration([{"id": 1, "sender": "Admin", "content": "hello"}])
    control.record_narration([{"id": 2, "sender": "Gemini", "content": "world"}])

    rows = control.read_narration()
    assert [r["content"] for r in rows] == ["hello", "world"]


# --- Proof 9: repeated delivery does not repeat work ------------------------


@pytest.mark.parametrize("worker", WORKERS, ids=WORKER_IDS)
def test_repeated_chat_delivery_creates_no_model_calls(
    worker, monkeypatch, control, hostile_messages
):
    """The same messages redelivered on every poll still produce nothing.

    De-duplication by message id is not what makes this safe -- the messages
    are re-served deliberately, ignoring `since_id`, so a worker that de-duped
    incorrectly would still be caught. What makes it safe is that the path from
    a message to execution does not exist.
    """
    invocations, _ = run_worker_loop(
        worker,
        monkeypatch,
        control,
        [hostile_messages, hostile_messages, hostile_messages],
        polls=3,
    )

    assert invocations == []


def test_duplicate_polls_cannot_claim_one_activation_twice(control):
    """One issued activation is claimable exactly once.

    This is the idempotency boundary for real work: the claim renames the
    record into consumed/ before returning it, and rename is atomic on both
    NTFS and POSIX, so a second poll -- or a second process -- finds nothing.
    """
    control.issue_activation("claudecode", "do the thing once")

    first = control.claim_activation("claudecode")
    second = control.claim_activation("claudecode")
    third = control.claim_activation("claudecode")

    assert first is not None
    assert first["task"] == "do the thing once"
    assert second is None
    assert third is None


def test_a_worker_cannot_claim_another_workers_activation(control):
    """Records for another agent are left in place, not drained."""
    control.issue_activation("gemini", "gemini's prompt")

    assert control.claim_activation("claudecode") is None
    assert control.claim_activation("chatgpt") is None

    claimed = control.claim_activation("gemini")
    assert claimed is not None and claimed["task"] == "gemini's prompt"
