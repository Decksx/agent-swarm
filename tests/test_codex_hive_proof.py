"""Temporary state and fake hub only; no scheduling or production access."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import codex_hive_proof as proof


class Hub:
    def __init__(self):
        self.rows = [{"id": 11, "sender": "claude-lead", "target": "@codex-lead",
                      "content": "PROBE @codex-lead: test-probe"}]
        self.reads = 0
        self.posts = []
        self.found = []
        self.error = None
        self.state = "confirmed"

    def read(self, identity, **kwargs):
        assert identity == "codex-lead" and kwargs == {"since_id": 10}
        self.reads += 1
        return self.rows

    def find(self, identity, content, **kwargs):
        assert content == "PROBE-ACK #11 test-probe" and kwargs == {"since_id": 10}
        return self.found

    def post(self, identity, content, *, target):
        self.posts.append((identity, content, target))
        if self.error:
            raise self.error
        return SimpleNamespace(state=self.state, message_id=12)


def call(root, hub, **kwargs):
    return proof.run(root, "test-probe", 10, 100, api=hub, now=kwargs.get("now", lambda: 50))


def test_one_claimant_posts_targeted_receipt_and_later_runs_do_nothing(tmp_path):
    hub = Hub()
    assert call(tmp_path, hub)["state"] == "confirmed"
    assert call(tmp_path, hub)["state"] == "skipped-existing-claim"
    assert hub.reads == 1
    assert hub.posts == [("codex-lead", "PROBE-ACK #11 test-probe", "@claude-lead")]
    assert json.loads((tmp_path / "test-probe" / "result.json").read_text())["ack_id"] == 12


def test_concurrent_claimants_only_one_reads_or_posts(tmp_path):
    hub = Hub()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(tmp_path, hub), range(8)))
    assert sum(r["state"] == "confirmed" for r in results) == 1
    assert hub.reads == len(hub.posts) == 1


@pytest.mark.parametrize("content", ["", "{partial", '{"state":"uncertain"}'])
def test_existing_or_partial_claim_is_never_rearmed(tmp_path, content):
    directory = tmp_path / "test-probe"
    directory.mkdir()
    claim = directory / "claim.json"
    claim.write_text(content)
    hub = Hub()
    assert call(tmp_path, hub)["state"] == "skipped-existing-claim"
    assert hub.reads == 0 and hub.posts == [] and claim.read_text() == content


@pytest.mark.parametrize("error,state", [(OSError("lost response"), "confirmed"),
                                         (None, "unconfirmed"), (None, "mismatch")])
def test_ambiguous_or_unconfirmed_post_is_never_retried(tmp_path, error, state):
    hub = Hub()
    hub.error, hub.state = error, state
    assert call(tmp_path, hub)["state"] == "uncertain"
    assert call(tmp_path, hub)["state"] == "skipped-existing-claim"
    assert len(hub.posts) == 1


def test_expiry_prevents_hub_access_and_recheck_prevents_late_post(tmp_path):
    hub = Hub()
    assert call(tmp_path, hub, now=lambda: 100)["state"] == "expired"
    assert hub.reads == 0
    clock = iter([50, 50, 100])
    assert call(tmp_path, hub, now=lambda: next(clock))["state"] == "expired"
    assert hub.reads == 1 and hub.posts == []


@pytest.mark.parametrize("change", ["no-match", "duplicate", "wrong-sender", "wrong-target", "old-id"])
def test_only_one_exact_fresh_probe_can_be_processed(tmp_path, change):
    hub = Hub()
    if change == "no-match":
        hub.rows = []
    elif change == "duplicate":
        hub.rows *= 2
    else:
        key, value = {"wrong-sender": ("sender", "admin"),
                      "wrong-target": ("target", "@room"), "old-id": ("id", 10)}[change]
        hub.rows[0][key] = value
    assert call(tmp_path, hub)["state"] == "not-proven"
    assert call(tmp_path, hub)["state"] == "skipped-existing-claim"
    assert hub.posts == []


def test_existing_own_ack_is_not_posted_again(tmp_path):
    hub = Hub()
    hub.found = [12]
    assert call(tmp_path, hub)["state"] == "duplicate-suppressed"
    assert hub.posts == []


def test_claim_write_failure_stops_before_hub_and_keeps_claim(tmp_path, monkeypatch):
    def broken(*args):
        raise OSError("disk error")
    hub = Hub()
    monkeypatch.setattr(proof.os, "fsync", broken)
    with pytest.raises(OSError):
        call(tmp_path, hub)
    assert hub.reads == 0 and (tmp_path / "test-probe" / "claim.json").exists()


def test_result_failure_after_post_does_not_authorize_another_post(tmp_path, monkeypatch):
    hub = Hub()
    monkeypatch.setattr(proof, "save", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        call(tmp_path, hub)
    assert call(tmp_path, hub)["state"] == "skipped-existing-claim"
    assert len(hub.posts) == 1
