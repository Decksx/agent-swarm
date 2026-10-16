"""The external-review CLI targets only the agreed admin ingress contract."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller_admin


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setenv("HUB_SECRET", "test-only")
    monkeypatch.setattr(controller_admin, "call", lambda *args: calls.append(args) or (201, {}))
    return calls


def command(*args):
    return ["controller_admin.py", "external-review", "EXT-1", "agenthub", "102", " objective\ncriteria ", *args]


def test_external_request_preserves_operator_text_and_omits_unstated_fields(sent):
    assert controller_admin.main(command()) == 0
    assert len(sent) == 1
    assert sent[0][2:] == ("POST", "/controller/external-reviews", {
        "task_id": "EXT-1", "project": "agenthub", "pr_number": 102,
        "objective": " objective\ncriteria ",
    })


def test_explicit_head_scope_and_family_claims_reach_the_dedicated_route(sent):
    assert controller_admin.main(command("--at-sha", "A" * 40,
        "--path", "src/**", "--path", "tests", "--authored-by", "openai", "--authored-by", "human")) == 0
    assert sent[0][-1] == {"task_id": "EXT-1", "project": "agenthub", "pr_number": 102,
        "objective": " objective\ncriteria ", "at_sha": "a" * 40,
        "paths": ["src/**", "tests"], "authored_by": ["openai", "human"]}


@pytest.mark.parametrize("index,value", [(2," "), (3,""), (4,"0"), (4,"-1"), (4,"abc"), (5," \n")])
def test_bad_required_values_are_rejected_without_a_request(sent, index, value):
    argv = command()
    argv[index] = value
    with pytest.raises(SystemExit) as exc:
        controller_admin.main(argv)
    assert exc.value.code == 2 and sent == []


@pytest.mark.parametrize("option,value", [("--at-sha","abc"), ("--at-sha","z"*40),
                                          ("--authored-by","unknown"), ("--path"," ")])
def test_bad_optional_values_are_rejected_without_a_request(sent, option, value):
    with pytest.raises(SystemExit) as exc:
        controller_admin.main(command(option, value))
    assert exc.value.code == 2 and sent == []


@pytest.mark.parametrize("status", [400, 403, 404, 409, 503])
def test_server_refusals_never_fall_back_to_task_creation(sent, monkeypatch, status):
    def refuse(*args):
        sent.append(args)
        return status, {"detail": "external review unavailable"}
    monkeypatch.setattr(controller_admin, "call", refuse)
    assert controller_admin.main(command()) == 1
    assert len(sent) == 1 and sent[0][3] == "/controller/external-reviews"
