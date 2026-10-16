"""Ingest through the worker dispatcher and polling loop, without model spend."""

import time

import pytest

import claude_ingest
import claude_worker
import controller_client
import repo_registry
from test_claude_ingest import Forge, fixture, git  # noqa: F401 (pytest fixture)
from test_ingest_adapter import activation
from test_worker_controller_source import StubQueue, run_loop


class IngestQueue(StubQueue):
    def __init__(self, pending=(), **kwargs):
        StubQueue.__init__(self, pending, **kwargs)
        # Keep dedicated reports separate from the generic author reports.
        self.ingest_reports = []
        self.beats = []

    def heartbeat(self, aid, lease):
        self.beats.append((aid, lease))
        return {"hard_deadline_seconds_remaining": 20.0}

    def report_ingest(self, aid, **report):
        self.ingest_reports.append((aid, report))
        return {"replayed": False}

    def report_integration(self, *args, **kwargs):
        pytest.fail("ingest used the integration route")


@pytest.fixture
def no_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("ingest reached the author/model path")
    monkeypatch.setattr(claude_worker, "_execute_author", forbidden)
    monkeypatch.setattr(claude_worker, "run_task", forbidden)
    return forbidden


@pytest.mark.parametrize("outcome", ["registered", "refused", "blocked"])
def test_dispatch_uses_ingest_authority_heartbeat_and_result_route(monkeypatch, no_model, outcome):
    queue = IngestQueue()
    def engine(request, **kwargs):
        assert request.task_id == "EXT-1" and request.pr_number == 7
        assert kwargs["commands"].checkpoint(force=True) is None
        if outcome == "refused":
            raise claude_ingest.IngestError("pr_not_found", refusal=True)
        if outcome == "blocked":
            raise claude_ingest.IngestError("gh_auth")
        return {"head_sha": "a" * 40}
    monkeypatch.setattr(claude_ingest, "ingest", engine)

    claude_worker.execute_activation(None, "must-not-run", activation(), queue)

    assert [r[1]["outcome"] for r in queue.ingest_reports] == [outcome]
    assert queue.reports == []
    assert len(queue.beats) == 2


@pytest.mark.parametrize("bad", ["state", "source", "role", "external"])
def test_dispatch_rejects_bad_ingest_before_commands(monkeypatch, no_model, bad):
    data, queue = activation(), IngestQueue()
    if bad == "state":
        data["task_record"]["state"] = "EXTERNAL_PENDING"
    elif bad == "external":
        del data["external"]
    else:
        data[bad] = "directory"
    monkeypatch.setattr(claude_ingest, "Commands", no_model)
    monkeypatch.setattr(claude_ingest, "ingest", no_model)

    claude_worker.execute_activation(None, "must-not-run", data, queue)

    assert not queue.beats and not queue.reports
    assert len(queue.ingest_reports) == 1
    assert queue.ingest_reports[0][1]["payload"]["reason_code"] == "worker_error"


def test_directory_ingest_does_not_run_or_write_an_author_result(monkeypatch, control, no_model):
    monkeypatch.setattr(claude_ingest, "Commands", no_model)
    monkeypatch.setattr(claude_worker, "_report", no_model)
    data = activation()
    data["source"] = "directory"

    claude_worker.execute_activation(None, "must-not-run", data)

    assert not list(control.CONTROL_DIR.rglob("*.json"))


@pytest.mark.parametrize("hold", [None, "rate", "busy", "unwritable"])
def test_poll_runs_ingest_once_during_model_holds(monkeypatch, control, no_model, hold):
    if hold == "rate":
        claude_worker.RATELIMIT_PATH.write_text(str(time.time() + 3600))
    elif hold in {"busy", "unwritable"}:
        def unreadable():
            if hold == "busy":
                raise claude_worker.swarm_control.AlreadyRunning("test usage lock")
            raise PermissionError("test usage folder")
        monkeypatch.setattr(claude_worker, "_read_usage", unreadable)
    author = {"activation_id": "author", "stage": "author"}
    # Only test model-free work in the unrestricted case; author behavior is
    # covered by the existing worker-source tests.
    queue = IngestQueue(([author] if hold else []) + [activation()])
    monkeypatch.setattr(claude_ingest, "ingest", lambda *a, **k: {"head_sha": "a" * 40})

    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=3, run_task=no_model)

    assert invocations == [] and queue.reports == []
    assert len(queue.ingest_reports) == 1
    assert queue.ingest_reports[0][1]["outcome"] == "registered"
    assert queue.pending == ([author] if hold else [])
    assert queue.claim_stages == ([None] * 3 if hold is None else [("ingest", "integrate")] * 3)
    assert not claude_worker.INFLIGHT_PATH.exists()


def test_global_pause_leaves_ingest_unclaimed(monkeypatch, control, no_model):
    control.PAUSE_PATH.write_text("paused by test")
    queue = IngestQueue([activation()])
    monkeypatch.setattr(claude_ingest, "ingest", no_model)

    run_loop(monkeypatch, control, queue=queue, polls=2, run_task=no_model)

    assert queue.claims == 0 and queue.pending == [activation()]
    assert queue.ingest_reports == [] and queue.beats == []


@pytest.mark.parametrize("rejected", [False, True])
def test_bad_claim_filter_blocks_ingest_on_its_own_route(monkeypatch, control, no_model, rejected):
    claude_worker.RATELIMIT_PATH.write_text(str(time.time() + 3600))
    queue = IngestQueue(claim_raises=controller_client.StageFilterNotHonoured("missing echo", activation()))
    monkeypatch.setattr(claude_ingest, "execute_ingest", no_model)
    if rejected:
        def refuse(*args, **kwargs):
            queue.ingest_reports.append((args[0], kwargs))
            raise controller_client.Refused("not accepted", status_code=409)
        monkeypatch.setattr(queue, "report_ingest", refuse)

    run_loop(monkeypatch, control, queue=queue, polls=2, run_task=no_model)

    assert len(queue.ingest_reports) == 2 and not queue.reports and not queue.beats
    for _, report in queue.ingest_reports:
        assert report["outcome"] == "blocked"
        assert report["payload"]["reason_code"] == "worker_error"


def test_dispatch_fetches_and_pins_real_git_without_touching_checkout(monkeypatch, no_model, fixture):
    request, registry, commands, _, _, checkout, base, head = fixture
    data, queue = activation(), IngestQueue()
    data["external"]["repo_location"] = request.repo_location
    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)
    def command_factory(remaining, heartbeat):
        return Forge(commands.metadata, remaining=remaining, heartbeat=heartbeat)
    monkeypatch.setattr(claude_ingest, "Commands", command_factory)
    before = (git(checkout, "rev-parse", "HEAD"), git(checkout, "status", "--porcelain"))

    claude_worker.execute_activation(None, "must-not-run", data, queue)

    assert len(queue.ingest_reports) == 1 and not queue.reports
    _, report = queue.ingest_reports[0]
    assert report["outcome"] == "registered", report
    assert report["payload"]["merge_base"] == base
    assert report["payload"]["changed_files"] == ["new.txt"]
    assert git(checkout, "rev-parse", report["payload"]["pin_ref"]) == head
    assert (git(checkout, "rev-parse", "HEAD"), git(checkout, "status", "--porcelain")) == before
