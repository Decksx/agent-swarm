"""Stage-filtered claims (#23): a held worker can still land approved work.

The rate guard exists to stop model spend. Integration spends none, but the
claim route used to hand out an agent's oldest activation of any stage, so a
worker that could not call a model could not take integration work either --
and an integrate activation issued during a hold-off expired into
INTEGRATION_UNCERTAIN. These pin the three layers that change that: the
controller's filtered claim, the client's check that the filter was honoured,
and the worker loop that asks for it only while held and never while paused.
"""

from __future__ import annotations

import time

import pytest

import claude_rate_guard
import claude_worker
import controller_client
from controller import activations, db, progression
from test_progression import DEADLINE, LEASE, author, make_task, review, routing
from test_worker_controller_source import StubQueue, run_loop


# --- Controller: claim_next and claim_stages ---------------------------------


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "controller.db"))
    db.initialize(connection)
    activations.set_host_capacity(connection, host="officepc", max_concurrent=5)
    return connection


@pytest.fixture
def author_then_integrate(conn):
    """claudecode holds an author activation (older) and an integrate one (newer)."""
    make_task(conn, "T-A")
    author(conn, "T-A")
    reviewing = progression.advance(conn, routing=routing(), task_id="T-A")[0]
    review(conn, "T-A", reviewing["activation_id"])

    make_task(conn, "T-B")
    older = activations.issue(
        conn, task_id="T-B", agent="claudecode", host="officepc", stage="author",
        lease_seconds=LEASE, hard_deadline_seconds=DEADLINE,
        expected_branch="task/T-B", now=time.time() - 60,
    )

    newer = progression.advance(conn, routing=routing(), task_id="T-A")[0]
    assert newer["stage"] == "integrate" and newer["agent"] == "claudecode"
    return older["activation_id"], newer["activation_id"]


def status_of(conn, activation_id):
    return conn.execute(
        "SELECT status FROM activations WHERE activation_id = ?", (activation_id,)
    ).fetchone()["status"]


def test_without_a_filter_the_oldest_activation_of_any_stage_is_claimed(conn, author_then_integrate):
    older, newer = author_then_integrate

    claimed = activations.claim_next(conn, agent="claudecode")

    assert claimed["activation_id"] == older and claimed["stage"] == "author"
    assert status_of(conn, newer) == activations.ISSUED


def test_a_filter_claims_only_its_stages_and_leaves_the_rest_issued(conn, author_then_integrate):
    older, newer = author_then_integrate

    claimed = activations.claim_next(conn, agent="claudecode", stages=["integrate"])

    assert claimed["activation_id"] == newer and claimed["stage"] == "integrate"
    assert status_of(conn, older) == activations.ISSUED
    assert activations.claim_next(conn, agent="claudecode", stages=["integrate"]) is None
    assert activations.claim_next(conn, agent="claudecode")["activation_id"] == older


def test_a_filter_naming_several_stages_is_still_oldest_first(conn, author_then_integrate):
    older, _ = author_then_integrate

    claimed = activations.claim_next(conn, agent="claudecode", stages=["integrate", "author"])

    assert claimed["activation_id"] == older


def test_the_filter_is_canonical_sorted_and_unique():
    assert activations.claim_stages(None) is None
    assert activations.claim_stages(["integrate", "author", "author"]) == ("author", "integrate")
    assert activations.claim_stages(("integrate",)) == ("integrate",)


@pytest.mark.parametrize("bad", [[], (), "integrate", ["bogus"], ["integrate", "bogus"], [None], {"integrate": 1}, 5])
def test_a_filter_that_could_match_nothing_is_refused(conn, bad):
    with pytest.raises(activations.InvalidClaimStages):
        activations.claim_next(conn, agent="claudecode", stages=bad)


# --- Rate guard seam ---------------------------------------------------------


def test_the_seam_names_integration_as_the_only_model_free_stage():
    assert claude_rate_guard.MODEL_FREE_STAGES == frozenset({"integrate"})
    assert claude_rate_guard.claim_stages(False) is None
    assert claude_rate_guard.claim_stages(True) == ("integrate",)
    assert isinstance(claude_rate_guard.claim_stages(True), tuple)


# --- Client: what is sent, and what is accepted back -------------------------


class Recorder:
    """A transport answering the claim route with `claim_body`, and tasks with text."""

    def __init__(self, claim_body):
        self.claim_body = claim_body
        self.calls = []

    def request(self, method, url, json=None, **kw):
        self.calls.append((method, url, json))
        body = self.claim_body if url.endswith("/activations/claim") else {"title": "t", "objective": "o"}

        class Response:
            status_code = 200
            headers = {}
            text = ""

            @staticmethod
            def json():
                return body

        return Response()


def client(transport):
    return controller_client.ControllerQueue(
        transport, base_url="http://hub", auth=("claudecode", "s"),
        agent="claudecode", backoff_base=5.0, backoff_cap=60.0,
    )


INTEGRATE = {"activation_id": "act-i", "task_id": "T-A", "stage": "integrate"}
AUTHOR = {"activation_id": "act-a", "task_id": "T-B", "stage": "author"}


def test_an_unfiltered_claim_sends_no_body():
    transport = Recorder({"agent": "claudecode", "activation": None})

    assert client(transport).claim() is None
    assert transport.calls[0] == ("POST", "http://hub/controller/activations/claim", None)


def test_a_filtered_claim_sends_a_sorted_json_list_and_accepts_an_honoured_reply():
    transport = Recorder({"agent": "claudecode", "activation": INTEGRATE,
                          "applied_stages": ["integrate"]})

    claimed = client(transport).claim(stages=frozenset({"integrate"}))

    assert transport.calls[0][2] == {"stages": ["integrate"]}
    assert claimed["activation_id"] == "act-i"


@pytest.mark.parametrize("reply", [
    {"agent": "claudecode", "activation": AUTHOR},
    {"agent": "claudecode", "activation": None},
    {"agent": "claudecode", "activation": INTEGRATE, "applied_stages": ["author", "integrate"]},
    {"agent": "claudecode", "activation": AUTHOR, "applied_stages": ["integrate"]},
])
def test_a_reply_that_did_not_honour_the_filter_is_raised_with_its_activation(reply):
    with pytest.raises(controller_client.StageFilterNotHonoured) as caught:
        client(Recorder(reply)).claim(stages=("integrate",))

    assert caught.value.activation == reply["activation"]


# --- Worker loop ---------------------------------------------------------------


@pytest.fixture
def rate_files(monkeypatch, control):
    control.CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(claude_worker, "RATELIMIT_PATH", control.CONTROL_DIR / "rl")
    monkeypatch.setattr(claude_worker, "USAGE_PATH", control.CONTROL_DIR / "usage")
    monkeypatch.setattr(claude_worker, "_process_usage_window", [])
    return control.CONTROL_DIR


def hold_off(rate_files):
    (rate_files / "rl").write_text(str(time.time() + 3600), encoding="utf-8")


def worker_activation(activation_id, stage):
    return {"activation_id": activation_id, "task_id": "T-" + activation_id, "task": "x",
            "issued_by": "controller", "source": "controller", "stage": stage}


def test_a_held_worker_runs_integration_and_leaves_author_work_queued(monkeypatch, control, rate_files):
    hold_off(rate_files)
    authoring = worker_activation("a", "author")
    integrating = worker_activation("i", "integrate")
    queue = StubQueue([authoring, integrating])
    integrated = []
    monkeypatch.setattr(claude_worker, "execute_integration",
                        lambda activation, q=None: integrated.append(activation["activation_id"]))

    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=3)

    assert integrated == ["i"]
    assert invocations == []
    assert queue.pending == [authoring]
    assert set(queue.claim_stages) == {("integrate",)}


def test_a_worker_that_is_not_held_claims_without_a_filter(monkeypatch, control, rate_files):
    queue = StubQueue()

    run_loop(monkeypatch, control, queue=queue, polls=2)

    assert queue.claim_stages and set(queue.claim_stages) == {None}


def test_a_paused_worker_neither_claims_nor_consults_the_rate_guard(monkeypatch, control, rate_files):
    hold_off(rate_files)
    control.PAUSE_PATH.write_text("paused by test", encoding="utf-8")
    consulted = []
    monkeypatch.setattr(claude_worker, "rate_limit_reason", lambda now=None: consulted.append(now))
    queue = StubQueue([worker_activation("i", "integrate")])

    run_loop(monkeypatch, control, queue=queue, polls=3)

    assert queue.claims == 0
    assert consulted == []
    assert (rate_files / "rl").exists(), "the hold-off moved while paused"


def test_an_activation_outside_the_filter_is_reported_blocked_and_never_run(monkeypatch, control, rate_files):
    hold_off(rate_files)
    stray = worker_activation("stray", "author")
    queue = StubQueue(claim_raises=controller_client.StageFilterNotHonoured("ignored", stray))
    integrated = []
    monkeypatch.setattr(claude_worker, "execute_integration",
                        lambda activation, q=None: integrated.append(activation))

    invocations, _ = run_loop(monkeypatch, control, queue=queue, polls=2)

    assert invocations == [] and integrated == []
    assert queue.reports and all(r[0] == "stray" and r[1] == "blocked" for r in queue.reports)


def test_a_held_worker_on_the_local_directory_still_takes_nothing(monkeypatch, control, rate_files):
    hold_off(rate_files)
    taken = []
    monkeypatch.setattr(claude_worker.swarm_control, "claim_activation",
                        lambda identity: taken.append(identity))

    invocations, _ = run_loop(monkeypatch, control, polls=2, source="directory")

    assert taken == [] and invocations == []
