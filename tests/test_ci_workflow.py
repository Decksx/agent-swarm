"""`pytest-unit` still means "every core and hub test passed".

The integrator requires the check runs `pytest-unit` and `pytest-bypass` by
name and refuses on any red check (`integrator.py`, INTEGRATION_REQUIRED_SUITES
in `swarm_ctl.sh`). When the suites were split into parallel jobs to shorten
CI, `pytest-unit` became a job that runs no tests itself and succeeds only when
the suite jobs it waits on succeeded. These pin that, because each way of
getting it wrong leaves a green `pytest-unit` that proves less than it says:

- a suite job it does not wait on can fail without turning it red;
- without `if: always()` it is *skipped* when a suite fails. The CI wait
  treats a skipped check as FINISHED_CLEAN; final evidence (`ci_evidence`)
  rejects it, but the required check should be red, not skipped;
- a suite left out of every job is never run at all.

Read as text rather than parsed, so the test needs nothing CI does not install.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def jobs() -> dict:
    """{job id: its block of text}, split on the two-space job keys."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text[text.index("\njobs:\n") + len("\njobs:\n"):]
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", body)

    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def runs(block: str) -> list:
    """The pytest invocations in a job's run steps."""
    return re.findall(r"(?m)^\s*pytest\s+(.+)$", block)


def suite_jobs() -> dict:
    """Jobs that run tests from tests/ (other than bypass) or hub/."""
    found = {}

    for name, block in jobs().items():
        for args in runs(block):
            if args.startswith("hub/") or (
                args.startswith("tests/") and '-k "bypass"' not in args
            ):
                found[name] = block

    return found


def needs_of(block: str) -> set:
    match = re.search(r"(?m)^    needs:\s*\[([^\]]*)\]", block)

    return {n.strip() for n in match.group(1).split(",")} if match else set()


def test_the_required_checks_are_jobs():
    assert {"pytest-unit", "pytest-bypass"} <= set(jobs())


def test_every_suite_runs_somewhere():
    invocations = [args for block in jobs().values() for args in runs(block)]

    assert any(a.startswith("tests/") and '-k "not bypass"' in a for a in invocations)
    assert any(a.startswith("tests/") and '-k "bypass"' in a for a in invocations)
    assert any(a.startswith("hub/") for a in invocations)


def test_pytest_unit_waits_on_every_suite_job():
    unit = jobs()["pytest-unit"]
    suites = set(suite_jobs()) - {"pytest-unit"}

    assert suites, "no job runs the core or hub suites"
    assert suites <= needs_of(unit), (
        f"pytest-unit does not wait on {sorted(suites - needs_of(unit))}; "
        "a failure there would not turn the required check red"
    )


def test_pytest_unit_reports_even_when_a_suite_fails():
    assert re.search(r"(?m)^    if:\s*always\(\)\s*$", jobs()["pytest-unit"]), (
        "without if: always() the aggregate is skipped when a suite fails, "
        "and the integrator's CI wait reads skipped as clean"
    )


def test_pytest_unit_requires_each_suite_to_have_succeeded():
    """`always()` makes it run; this makes it fail unless each suite succeeded.
    Anything else -- failure, cancelled, skipped -- must turn it red."""
    unit = jobs()["pytest-unit"]
    suites = set(suite_jobs()) - {"pytest-unit"}

    for suite in sorted(suites):
        assert f'test "${{{{ needs.{suite}.result }}}}" = "success"' in unit, (
            f"pytest-unit does not require {suite} to have succeeded"
        )
