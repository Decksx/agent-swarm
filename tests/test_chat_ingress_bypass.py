"""Fault injection for controller/drafts.py: each guard is load-bearing.

A passing `test_chat_ingress.py` is equally consistent with the guards being
unreachable code that fails nothing when removed. So each guard below is taken
out by an exact source substitution, the patched source is loaded as a separate
module, and a named test from that suite is run against it and must fail. The
same test is run against the unpatched source first and must pass, so a failure
is attributable to the removed guard rather than to the harness.

Nothing is written to disk. `bypass_matrix.py` patches files in place and
needs a sidecar to recover from a killed run; loading the patched text into a
fresh module object has no file to leave behind.
"""

from __future__ import annotations

import inspect
import types
from pathlib import Path

import pytest

import test_chat_ingress as suite

DRAFTS_PATH = Path(suite.drafts_module.__file__)


class Bypass:
    def __init__(self, name, old, new, test_name, rationale):
        self.name = name
        self.old = old
        self.new = new
        self.test_name = test_name
        self.rationale = rationale


BYPASSES = [
    Bypass(
        "create_table_if_not_exists",
        old="CREATE TABLE IF NOT EXISTS task_drafts",
        new="CREATE TABLE task_drafts",
        test_name="test_create_drafts_table_twice_keeps_rows",
        rationale="a second create_drafts_table call must be a no-op",
    ),
    Bypass(
        "hash_equality",
        old="    if stored_hash != expected_hash:\n",
        new="    if False:\n",
        test_name="test_hash_mismatch_raises_and_changes_nothing",
        rationale="a confirmation under the wrong hash must be refused",
    ),
    Bypass(
        "compare_and_swap_in_one_transaction",
        old=(
            "    with transaction(conn):\n"
            "        _check_draft(conn, draft_id, expected_hash)\n"
            "        _mark_confirmed(conn, draft_id, now)\n"
        ),
        new=(
            "    with transaction(conn):\n"
            "        _check_draft(conn, draft_id, expected_hash)\n"
            "    with transaction(conn):\n"
            "        _mark_confirmed(conn, draft_id, now)\n"
        ),
        test_name="test_interleaved_writer_cannot_cut_between_compare_and_swap",
        rationale="a writer between the compare and the swap gets its edit "
        "confirmed under a hash that described something else",
    ),
    Bypass(
        "pending_only",
        old="    if status != PENDING:\n",
        new="    if False:\n",
        test_name="test_confirmed_draft_cannot_be_confirmed_again",
        rationale="a replayed confirmation must not restamp a confirmed draft",
    ),
    Bypass(
        "draft_exists",
        old="    if found is None:\n",
        new="    if False:\n",
        test_name="test_confirming_a_missing_draft_raises",
        rationale="a missing draft must be named as missing, not fail obscurely",
    ),
    Bypass(
        "hash_sorts_keys",
        old="content, sort_keys=True, separators=",
        new="content, separators=",
        test_name="test_hash_is_stable_and_ignores_key_order",
        rationale="the same content built in a different order is the same draft",
    ),
    Bypass(
        "rows_read_by_position",
        old="    draft = dict(zip(DRAFT_COLUMNS, row))\n",
        new="    draft = dict(row)\n",
        test_name="test_works_with_and_without_a_row_factory",
        rationale="a plain connection returns tuples, which dict() cannot read",
    ),
]


def load_drafts(source: str, label: str) -> types.ModuleType:
    """Execute `source` as a sibling of controller.drafts, without importing it.

    `__package__` is set so the module's `from .db import transaction` resolves
    to the real controller.db exactly as it does for the installed module.
    """
    module = types.ModuleType(f"controller._drafts_{label}")
    module.__package__ = "controller"
    module.__file__ = str(DRAFTS_PATH)
    exec(compile(source, str(DRAFTS_PATH), "exec"), module.__dict__)

    return module


def run_suite_test(test_name: str, drafts, workdir: Path) -> BaseException | None:
    """Run one test from test_chat_ingress against `drafts`.

    Returns the exception it failed with, or None if it passed. `BaseException`
    because `pytest.raises` reports a missing exception with `pytest.fail`,
    which is not an `Exception`.
    """
    test = getattr(suite, test_name)
    parameters = inspect.signature(test).parameters
    workdir.mkdir()
    arguments = {}
    conn = None

    if "drafts" in parameters:
        arguments["drafts"] = drafts

    if "conn" in parameters:
        conn = suite.make_conn(workdir / "drafts.db")
        arguments["conn"] = conn

    if "tmp_path" in parameters:
        arguments["tmp_path"] = workdir

    try:
        test(**arguments)
    except (Exception, pytest.fail.Exception) as failure:
        return failure
    finally:
        if conn is not None:
            conn.close()

    return None


def test_every_bypass_names_a_real_test():
    for bypass in BYPASSES:
        assert callable(getattr(suite, bypass.test_name, None)), bypass.name


@pytest.mark.parametrize("bypass", BYPASSES, ids=lambda b: b.name)
def test_guard_is_load_bearing(bypass, tmp_path):
    source = DRAFTS_PATH.read_text(encoding="utf-8")

    assert source.count(bypass.old) == 1, (
        f"{bypass.name}: the guard text must occur exactly once in "
        f"{DRAFTS_PATH.name}, or the bypass is not removing what it names"
    )

    intact = load_drafts(source, "intact")
    patched = load_drafts(source.replace(bypass.old, bypass.new), bypass.name)

    control = run_suite_test(bypass.test_name, intact, tmp_path / "intact")
    assert control is None, (
        f"{bypass.test_name} fails even with the guard present: {control!r}"
    )

    failure = run_suite_test(bypass.test_name, patched, tmp_path / "bypassed")
    assert failure is not None, (
        f"removing {bypass.name} did not fail {bypass.test_name}, so that test "
        f"does not hold the guard ({bypass.rationale})"
    )
