"""The ingest wire adapter is callable for review; worker dispatch stays off."""

from types import SimpleNamespace

import pytest

import claude_ingest as ingest
import controller_client


def activation():
    return {"activation_id": "act-1", "task_id": "EXT-1", "stage": "ingest",
        "source": "controller", "role": "operator",
        "task_record": {"state": "EXTERNAL_INGESTING", "contract_yaml": "must not parse"},
        "external": {"schema_version": 1, "project": "demo", "repo_location": "C:/git/demo",
            "repo_slug": "owner/repo", "pr_number": 7, "at_sha": None, "paths": None,
            "pin_ref": "refs/swarm/external/EXT-1",
            "scratch_ref_prefix": "refs/swarm/ingest-tmp/EXT-1/act-1",
            "reclaimable_scratch_prefixes": ["refs/swarm/ingest-tmp/EXT-1/dead"]}}


class Queue:
    def __init__(self):
        self.beats = []
        self.reports = []
        self.live = True

    def heartbeat(self, aid, lease):
        self.beats.append((aid, lease))
        return {"hard_deadline_seconds_remaining": 20.0} if self.live else None

    def report_ingest(self, aid, **report):
        self.reports.append((aid, report))


def test_adapter_uses_external_block_and_dedicated_report(monkeypatch):
    queue = Queue()
    def engine(request, **kwargs):
        assert request.repo_slug == "owner/repo" and request.pr_number == 7
        assert request.reclaimable_scratch_prefixes == ("refs/swarm/ingest-tmp/EXT-1/dead",)
        assert kwargs["remaining"] == 20
        assert kwargs["commands"].checkpoint() is None
        return {"wire": "evidence"}
    monkeypatch.setattr(ingest, "ingest", engine)
    ingest.execute_ingest(activation(), queue)
    assert queue.reports == [("act-1", {"outcome": "registered", "payload": {"wire": "evidence"}})]
    assert len(queue.beats) >= 2


@pytest.mark.parametrize("mode", ["state", "source", "role", "pin", "scratch", "schema", "missing"])
def test_bad_activation_cannot_start_engine_or_commands(monkeypatch, mode):
    data, queue = activation(), Queue()
    if mode == "state":
        data["task_record"]["state"] = "EXTERNAL_PENDING"
    elif mode in {"source", "role"}:
        data[mode] = "wrong"
    elif mode == "pin":
        data["external"]["pin_ref"] = "refs/heads/main"
    elif mode == "scratch":
        data["external"]["scratch_ref_prefix"] += "other"
    elif mode == "schema":
        data["external"]["schema_version"] = True
    else:
        del data["external"]
    def forbidden(*args, **kwargs):
        pytest.fail("invalid activation reached ingest")
    monkeypatch.setattr(ingest, "ingest", forbidden)
    ingest.execute_ingest(data, queue)
    assert not queue.beats
    assert queue.reports[0][1]["outcome"] == "blocked"
    assert queue.reports[0][1]["payload"]["reason_code"] == "worker_error"


def test_initial_heartbeat_failure_never_starts_engine(monkeypatch):
    queue = Queue()
    queue.live = False
    monkeypatch.setattr(ingest, "ingest", lambda *a, **k: pytest.fail("lost lease ran"))
    ingest.execute_ingest(activation(), queue)
    assert queue.reports[0][1]["outcome"] == "blocked"


def test_heartbeat_can_shorten_but_never_reset_command_deadline(monkeypatch):
    queue = Queue()
    timings = iter([20.0, 3.0, 30.0])
    monkeypatch.setattr(queue, "heartbeat", lambda *a: {"hard_deadline_seconds_remaining": next(timings)})
    monkeypatch.setattr(ingest.time, "monotonic", lambda: 100.0)
    def engine(request, **kwargs):
        command = kwargs["commands"]
        assert command.deadline == 119.0
        command.checkpoint()
        assert command.deadline == 102.0
        command.checkpoint()
        assert command.deadline == 102.0
        return {}
    monkeypatch.setattr(ingest, "ingest", engine)
    ingest.execute_ingest(activation(), queue)
    assert queue.reports[0][1]["outcome"] == "registered"


@pytest.mark.parametrize("code,wire,extra", [
    ("operator_sha_mismatch", "at_sha_mismatch", {}),
    ("pr_moved", "head_moved", {"observed_sha": "b" * 40}),
    ("pin_conflict", "pin_conflict", {"observed_sha": "b" * 40}),
    ("no_common_ancestor", "no_merge_base", {"base_ref_sha": "c" * 40}),
    ("empty_review_range", "empty_range", {}),
    ("evidence_too_large", "evidence_too_large", {}),
])
def test_refusals_carry_required_observed_shas(code, wire, extra):
    outcome, payload = ingest.failure_payload(ingest.IngestError(code, refusal=True,
        head_sha="a" * 40, **extra))
    assert outcome == "refused" and payload["reason_code"] == wire
    assert payload["observed"]["head_sha"] == "a" * 40
    if code == "pr_moved":
        assert payload["observed"]["resolved_ref_sha"] == "b" * 40
    if code == "pin_conflict":
        assert payload["observed"]["existing_pin_sha"] == "b" * 40


def test_unclassified_error_is_repairable_and_diagnostics_are_static():
    outcome, payload = ingest.failure_payload(ingest.IngestError("secret stderr", refusal=True))
    assert outcome == "blocked" and payload["reason_code"] == "worker_error"
    assert "secret" not in str(payload)


@pytest.mark.parametrize("statuses", [[503, 200], [422], [409]])
def test_report_ingest_retries_transport_only_and_uses_exact_wire(monkeypatch, statuses):
    calls = []
    sequence = iter(statuses)
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs["json"]))
        status = next(sequence)
        return SimpleNamespace(status_code=status, json=lambda: {"replayed": True, "detail": "invalid"})
    monkeypatch.setattr(controller_client.time, "sleep", lambda seconds: None)
    queue = controller_client.ControllerQueue(SimpleNamespace(request=request),
        base_url="http://test", auth=("claudecode", "test"), agent="claudecode")
    payload = {"schema_version": 1, "reason_code": "worker_error", "detail": "d"}
    queue.report_ingest("act-1", outcome="blocked", payload=payload)
    assert len(calls) == len(statuses)
    assert all(c == ("POST", "http://test/controller/activations/act-1/ingest",
                    {"outcome": "blocked", "payload": payload}) for c in calls)


def test_unreadable_ingest_task_reports_via_ingest_route(monkeypatch):
    queue = controller_client.ControllerQueue(None, base_url="http://test", auth=(), agent="claudecode")
    monkeypatch.setattr(queue, "_call", lambda *a: (_ for _ in ()).throw(controller_client.ControllerError("no")))
    reports = []
    monkeypatch.setattr(queue, "report_ingest", lambda aid, **kw: reports.append((aid, kw)))
    monkeypatch.setattr(queue, "report", lambda *a, **k: pytest.fail("author route used"))
    assert queue._with_task_text(activation()) is None
    assert reports[0][1]["payload"]["reason_code"] == "worker_error"
