"""`--proof-mode` has to reach the task record, not just the parser.

A proof mode the CLI accepts and drops is worse than one it refuses. The task
is created, it reads as configured, and the worker is handed `baseline` -- so
a `branch_only` task is asked for a baseline run it was never scoped to
produce, and the mismatch surfaces at authoring rather than at registration.

The contract hash is the other half. `proof_mode` is stored on the task
version and deliberately not written into the contract text, so two tasks with
the same contract and different proof modes hash identically. A test that let
the hash move would be recording that the flag had been smuggled into the
contract body, where changing it later would invalidate every reference to the
old hash.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hub"))

import controller_admin  # noqa: E402
from controller import engine  # noqa: E402


@pytest.fixture
def sent(monkeypatch):
    """Every call the CLI makes, without one leaving the process."""
    calls = []

    def capture(url, secret, method, path, body=None):
        calls.append({"method": method, "path": path, "body": body})
        return 200, {"task_id": "T-1", "version": 1, "state": "DRAFT"}

    monkeypatch.setattr(controller_admin, "call", capture)
    monkeypatch.setenv("HUB_SECRET", "test-secret")
    return calls


def create(argv):
    return [
        "controller_admin.py", "create-task", "T-1", "title", "objective",
        "--base-sha", "a" * 40, *argv,
    ]


def test_the_requested_proof_mode_is_in_the_request(sent):
    assert controller_admin.main(
        create(["--allowed-path", "hub/hub.py", "--proof-mode", "branch_only"])
    ) == 0

    assert len(sent) == 1
    assert sent[0]["path"] == "/controller/tasks"
    assert sent[0]["body"]["proof_mode"] == "branch_only"


def test_an_unstated_proof_mode_is_still_the_baseline(sent):
    assert controller_admin.main(create(["--allowed-path", "hub/hub.py"])) == 0
    assert sent[0]["body"]["proof_mode"] == "baseline"


def test_a_proof_mode_the_database_would_refuse_is_refused_here(sent):
    with pytest.raises(SystemExit) as refused:
        controller_admin.main(
            create(["--allowed-path", "hub/hub.py", "--proof-mode", "trust-me"])
        )

    assert refused.value.code == 2
    assert sent == []


def test_the_flag_does_not_move_the_contract_hash(sent):
    for mode in ("baseline", "branch_only"):
        controller_admin.main(
            create(["--allowed-path", "hub/hub.py", "--proof-mode", mode])
        )

    baseline, branch_only = sent
    assert baseline["body"]["contract_yaml"] == branch_only["body"]["contract_yaml"]
    assert engine.contract_hash(baseline["body"]["contract_yaml"]) ==         engine.contract_hash(branch_only["body"]["contract_yaml"])


def test_the_cli_offers_exactly_what_the_schema_permits():
    """The CLI's choices and the table's CHECK cannot drift apart.

    If they do, one of the two is a lie: either the CLI refuses a mode the
    controller would store, or it accepts one the insert will reject with a
    constraint error that names nothing useful.
    """
    schema = (ROOT / "controller" / "schema.py").read_text(encoding="utf-8")
    constraint = re.search(
        r"proof_mode\s+TEXT NOT NULL\s+CHECK \(proof_mode IN \(([^)]*)\)",
        schema,
    )
    assert constraint, "could not find the proof_mode CHECK in schema.py"

    permitted = set(re.findall(r"'([a-z_]+)'", constraint.group(1)))

    parser_choices = set()
    for action in _create_task_parser()._actions:
        if action.dest == "proof_mode":
            parser_choices = set(action.choices)

    assert parser_choices == permitted


def _create_task_parser():
    import argparse

    holder = {}
    real = argparse.ArgumentParser.add_subparsers

    def remember(self, *args, **kwargs):
        sub = real(self, *args, **kwargs)
        add_parser = sub.add_parser

        def wrapped(name, *a, **kw):
            parser = add_parser(name, *a, **kw)
            holder[name] = parser
            return parser

        sub.add_parser = wrapped
        return sub

    argparse.ArgumentParser.add_subparsers = remember
    try:
        try:
            controller_admin.main(["controller_admin.py"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.add_subparsers = real

    return holder["create-task"]
