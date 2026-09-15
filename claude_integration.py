"""Integration: landing an approved candidate, with no model call.

Extracted from `claude_worker` unchanged, so that module fits the author's
file view (#25). `claude_worker.execute_integration` is still the entry point;
it passes the worker's identity in as `actor`, so this module never imports
`claude_worker`. Logging stays on the "claude_worker" logger.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("claude_worker")


def execute_integration(
    activation: dict, queue: Any = None, *, actor: str
) -> None:
    """Land an approved candidate. No model is called anywhere in this path.

    Every question integration asks has a factual answer: is this the approved
    commit, is the target where it was pinned, did the checks pass, did the
    push land. A model could only make those answers less predictable, and the
    one thing an integrator must be is predictable.

    **The authority checks come first and are not negotiable.** A side effect
    that reaches a real repository needs more than a task that looks ready: it
    needs a live activation this worker holds, for the integrate stage, on a
    task the controller has actually moved to INTEGRATING. A bare
    READY_INTEGRATION task is not sufficient -- that is a task nobody has been
    told to integrate, and acting on it would mean this worker decided to.
    """
    activation_id = activation.get("activation_id")
    task_record = activation.get("task_record") or {}
    task_id = activation.get("task_id") or task_record.get("task_id") or "task"

    def refuse(reason: str, outcome: str = "refused", **extra) -> None:
        log.error("integration %s refused: %s", activation_id, reason)
        _report_integration(
            queue, activation_id, outcome, {"reason": reason, **extra}
        )

    if str(activation.get("stage") or "").lower() != "integrate":
        refuse("this is not an integrate activation", outcome="blocked")
        return

    # The controller's own state, not the activation's say-so. An activation
    # is evidence that something was issued; the task's state is evidence that
    # the controller applied it.
    state = str(task_record.get("state") or "").strip()

    if state != "INTEGRATING":
        refuse(
            f"{task_id} is {state or 'in no state at all'}, not INTEGRATING. "
            "An approved task that nobody has been told to integrate is not a "
            "task to integrate; the activation is what says so, and the state "
            "is what proves it was issued.",
            outcome="blocked",
        )
        return

    for name in ("INTEGRATION_REPO", "INTEGRATION_TARGET_REF",
                 "INTEGRATION_REPO_SLUG", "INTEGRATION_WORK_ROOT"):
        if not os.environ.get(name, "").strip():
            refuse(f"{name} is not configured on this host", outcome="blocked")
            return

    # The branch the CONTROLLER issued this activation against. Not a pull
    # request number: nothing in the controller has ever produced one, and the
    # worker taking one from its input would mean whoever assembled that input
    # chose what got merged. The integrator derives the pull request from this
    # branch, the ledger's approved candidate, and the host's configuration,
    # and refuses on anything but exactly one open match.
    branch = str(activation.get("expected_branch") or "").strip()

    if not branch:
        refuse(
            "the activation names no expected_branch, so there is nothing to "
            "find a pull request from. An integrate activation is issued with "
            "the same evidence a review is.",
            outcome="blocked",
        )
        return

    # How long to wait for the candidate's CI before refusing (#32), how
    # often to look, and the lease each look renews. Refused when unreadable
    # rather than defaulted: a typo must not turn the wait off, or into one
    # that outlives the lease.
    try:
        ci_wait = float(os.environ.get("INTEGRATION_CI_WAIT_SECONDS", "1500"))
        ci_poll = float(os.environ.get("INTEGRATION_CI_POLL_SECONDS", "30"))
        lease = float(os.environ.get("INTEGRATION_LEASE_SECONDS", "900"))
    except ValueError as exc:
        refuse(f"an INTEGRATION_CI_* setting is not a number: {exc}",
               outcome="blocked")
        return

    if ci_wait < 0 or not 0 < ci_poll < lease:
        refuse(
            f"INTEGRATION_CI_WAIT_SECONDS={ci_wait:g} must not be negative, and "
            f"INTEGRATION_CI_POLL_SECONDS={ci_poll:g} must be above zero and "
            f"below INTEGRATION_LEASE_SECONDS={lease:g}, or the lease lapses "
            "between heartbeats",
            outcome="blocked",
        )
        return

    def heartbeat() -> None:
        if queue is not None and hasattr(queue, "heartbeat"):
            queue.heartbeat(activation_id, lease)

    try:
        import integrator
    except ImportError as exc:
        refuse(f"the integrator is not importable: {exc}", outcome="blocked")
        return

    log.info(
        "INTEGRATING activation %s for task %s from %s (waiting up to %gs "
        "for CI)", activation_id, task_id, branch, ci_wait,
    )

    try:
        record = integrator.run_integration(
            task_record,
            repo=os.environ["INTEGRATION_REPO"],
            target_ref=os.environ["INTEGRATION_TARGET_REF"],
            branch=branch,
            repo_slug=os.environ["INTEGRATION_REPO_SLUG"],
            work_root=os.environ["INTEGRATION_WORK_ROOT"],
            required_suites=[
                name for name in
                os.environ.get("INTEGRATION_REQUIRED_SUITES", "").split(",")
                if name.strip()
            ],
            actor=actor,
            ci_wait_seconds=ci_wait,
            ci_poll_seconds=ci_poll,
            heartbeat=heartbeat,
        )
    except integrator.IntegrationRefused as exc:
        # Every refusal before the push leaves nothing changed. A refusal
        # after it -- the parent or tree check -- means the merge landed and
        # does not match, which is a reconciliation and says so in its own
        # message rather than being flattened into "refused" here.
        refuse(str(exc))
        return
    except Exception as exc:
        log.error("integration %s failed unexpectedly", activation_id,
                  exc_info=True)
        refuse(f"the integration attempt failed: {exc}", outcome="blocked")
        return

    log.info(
        "INTEGRATED %s: %s -> %s on %s",
        task_id, record["candidate_sha"][:12], record["merge_sha"][:12],
        record["target_ref"],
    )

    _report_integration(queue, activation_id, "integrated", record)


def _report_integration(
    queue: Any, activation_id: Any, outcome: str, payload: dict
) -> None:
    """Report through /integration, never the author route.

    The controller checks the stage, so a misdirected submission is refused
    rather than applied to the wrong task -- but sending it to the right place
    is this worker's job, not the controller's to correct.
    """
    if queue is None:
        log.warning(
            "no controller queue; integration %s outcome %r not reported",
            activation_id, outcome,
        )
        return

    try:
        queue.report_integration(
            activation_id, outcome=outcome, payload=payload
        )
    except Exception:
        log.error(
            "could not report integration %s as %r", activation_id, outcome,
            exc_info=True,
        )
