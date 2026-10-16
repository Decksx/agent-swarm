"""Real HTTP claim/heartbeat/result paths through the worker's ingest dispatch."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claude_ingest
import claude_worker
import controller_client
from test_controller_api import as_
from test_external_review_routes import client, registered, request_body  # noqa: F401


@pytest.mark.parametrize("mode,expected", [
    ("registered", "READY_EXTERNAL_REVIEW"),
    ("lost_response", "READY_EXTERNAL_REVIEW"),
    ("invalid", "EXTERNAL_INGEST_BLOCKED"),
    ("refused", "FAILED"),
    ("blocked", "EXTERNAL_INGEST_BLOCKED"),
])
def test_claim_dispatch_and_result_roundtrip(client, monkeypatch, mode, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("ingest reached authoring, integration or a model")
    monkeypatch.setattr(claude_worker, "_execute_author", forbidden)
    monkeypatch.setattr(claude_worker, "run_task", forbidden)
    monkeypatch.setattr(claude_worker, "execute_integration", forbidden)
    monkeypatch.setattr(controller_client.time, "sleep", lambda *args: None)
    beats, deliveries, responses = [], [], []

    def engine(request, **kwargs):
        assert request.pr_number == 102
        kwargs["commands"].checkpoint(force=True)
        if mode == "refused":
            raise claude_ingest.IngestError("pr_not_found", refusal=True)
        if mode == "blocked":
            raise claude_ingest.IngestError("gh_auth")
        evidence = registered()
        if mode == "invalid":
            evidence["pin_ref"] = "wrong"
        return evidence
    monkeypatch.setattr(claude_ingest, "ingest", engine)

    def transport(method, url, *, json, auth, timeout):
        response = client.request(method, url, json=json, headers={"X-Test-Agent": auth[0]})
        if url.endswith("/heartbeat"):
            beats.append(response.status_code)
        if url.endswith("/ingest"):
            deliveries.append(json)
            responses.append(response)
            if mode == "lost_response" and len(deliveries) == 1:
                assert response.status_code == 200, response.text
                raise OSError("accepted response lost")
        return response

    response = as_(client, "admin", "post", "/controller/external-reviews", json=request_body())
    assert response.status_code == 200, response.text
    assert as_(client, "admin", "post", "/controller/tasks/advance").status_code == 200
    queue = controller_client.ControllerQueue(SimpleNamespace(request=transport),
        base_url="http://testserver", auth=("claudecode", "test"), agent="claudecode")
    claimed = queue.claim(stages=("ingest", "integrate"))
    assert claimed["task_record"]["state"] == "EXTERNAL_INGESTING"

    claude_worker.execute_activation(None, "must-not-run", claimed, queue)

    task = as_(client, "admin", "get", "/controller/tasks/EXT-1").json()
    assert task["state"] == expected
    assert beats == [200, 200]
    if mode == "lost_response":
        assert len(deliveries) == 2 and deliveries[0] == deliveries[1]
        assert responses[1].json()["replayed"] is True
        assert responses[0].json()["event_id"] == responses[1].json()["event_id"]
    elif mode == "invalid":
        assert [r.status_code for r in responses] == [422, 200]
        assert [r["outcome"] for r in deliveries] == ["registered", "blocked"]
        assert deliveries[1]["payload"]["reason_code"] == "worker_error"
    else:
        assert len(deliveries) == 1 and responses[0].status_code == 200
