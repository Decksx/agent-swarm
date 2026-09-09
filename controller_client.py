"""Worker-side client for the controller's HTTP API.

This is the queue source that replaces the local control directory. It is a
separate module from ``swarm_control`` because the two are alternatives, not
layers: a worker uses exactly one of them for its whole life, chosen at
startup, and keeping them apart makes "which source is this worker on" a
question with a visible answer rather than an inference from behaviour.

What this module deliberately does not do
-----------------------------------------

It does not decide whether to run anything. It fetches work and reports
outcomes; the pause check, the rate guard and the model invocation stay in the
worker. A queue client that could also start work would be a second activation
path, which is the thing Phase 0 removed.

It also never reads a task from chat. The only inputs are the controller's own
responses, authenticated with this worker's own credential.

Failure handling
----------------

Transport and server failures are reported and backed off, never retried
tightly. A worker that polls a broken hub every three seconds turns one outage
into a log nobody can read and a hub nobody can restart; a worker that gives up
silently looks healthy while doing nothing. `Backoff` grows the interval to a
cap and says so once per state change rather than once per attempt.

An authentication failure is treated differently from a server failure, and
loudly. A 401 does not resolve itself: the credential is wrong, and every
subsequent poll will fail the same way. It backs off to the cap immediately
instead of climbing there over several minutes of noise.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("controller_client")


class ControllerError(Exception):
    """The controller could not be reached, or refused in a way worth stopping for."""


class Unauthenticated(ControllerError):
    """The hub rejected this worker's credential."""


class Backoff:
    """Bounded exponential backoff with a readable log.

    Separate from the polling loop so the loop reads as "claim, run, report"
    and the retry policy can be asserted on its own. Logs on transition rather
    than per attempt: a hub that is down for an hour should produce a handful
    of lines, not twelve hundred.
    """

    def __init__(self, base: float, cap: float) -> None:
        self.base = base
        self.cap = cap
        self.current = 0.0
        self.consecutive = 0

    def reset(self) -> None:
        """Called after any success. Recovery is worth one line."""
        if self.consecutive:
            log.info(
                "controller reachable again after %d consecutive failures",
                self.consecutive,
            )

        self.current = 0.0
        self.consecutive = 0

    def fail(self, reason: str, *, straight_to_cap: bool = False) -> float:
        """Record a failure and return how long to wait."""
        self.consecutive += 1
        previous = self.current

        if straight_to_cap:
            self.current = self.cap
        else:
            self.current = min(self.cap, self.base if not self.current else self.current * 2)

        # First failure, or the interval changed: worth saying. Otherwise this
        # is the same outage still going and the log already says so.
        if self.consecutive == 1 or self.current != previous:
            log.warning(
                "controller unavailable (%s); backing off to %.0fs "
                "[failure %d]",
                reason,
                self.current,
                self.consecutive,
            )

        return self.current


class ControllerQueue:
    """One worker's view of the controller.

    `agent` is not sent anywhere. The controller derives it from the
    credential, and it is kept here only so log lines can name the worker.
    """

    def __init__(
        self,
        requests: Any,
        *,
        base_url: str,
        auth: tuple,
        agent: str,
        timeout: float = 15.0,
        backoff_base: float = 5.0,
        backoff_cap: float = 300.0,
    ) -> None:
        self.requests = requests
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.agent = agent
        self.timeout = timeout
        self.backoff = Backoff(backoff_base, backoff_cap)

    # --- transport -----------------------------------------------------------

    def _call(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        """One authenticated request. Raises ControllerError on any failure."""
        url = f"{self.base_url}{path}"

        try:
            response = self.requests.request(
                method, url, json=payload, auth=self.auth, timeout=self.timeout
            )
        except Exception as exc:
            raise ControllerError(f"{method} {path}: {exc}") from exc

        if response.status_code == 401:
            raise Unauthenticated(
                f"{method} {path}: 401 -- this worker's hub credential was rejected"
            )

        if response.status_code >= 400:
            # The body is the controller's own message: "activation is DONE",
            # "lease has expired". Carried through rather than flattened,
            # because it is the only thing that distinguishes a conflict a
            # worker should accept from one it should report.
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except Exception:
                detail = (response.text or "")[:200]

            raise ControllerError(f"{method} {path}: {response.status_code} {detail}")

        try:
            return response.json()
        except Exception as exc:
            raise ControllerError(f"{method} {path}: unreadable response: {exc}") from exc

    # --- queue ---------------------------------------------------------------

    def claim(self) -> Optional[dict]:
        """Claim this worker's next activation, or None.

        Returns None both when the queue is empty and when the controller
        cannot be reached. Those are different for logging -- the second backs
        off and the first does not -- but identical for the caller, which has
        nothing to run either way.
        """
        try:
            body = self._call("POST", "/controller/activations/claim")
        except Unauthenticated as exc:
            # Straight to the cap: a rejected credential does not fix itself,
            # and climbing there over several minutes only adds noise.
            self.backoff.fail(str(exc), straight_to_cap=True)
            return None
        except ControllerError as exc:
            self.backoff.fail(str(exc))
            return None

        self.backoff.reset()
        activation = body.get("activation")

        if activation is None:
            return None

        return self._with_task_text(activation)

    def _with_task_text(self, activation: dict) -> Optional[dict]:
        """Attach the task's own text to a claimed activation.

        The activation names a task; the prompt is the task's title and
        objective. Fetched here so the worker receives the same shape the local
        control directory produced and needs no branch of its own.

        A task that cannot be fetched is reported as blocked rather than run.
        Running with a placeholder prompt would spend a model call on nothing
        and record a result the controller would take at face value.
        """
        task_id = activation.get("task_id")

        try:
            task = self._call("GET", f"/controller/tasks/{task_id}")
        except ControllerError as exc:
            log.error("claimed %s but could not read task %s: %s",
                      activation.get("activation_id"), task_id, exc)
            self.report(
                activation.get("activation_id"),
                outcome="blocked",
                payload={"reason": f"task {task_id} unreadable"},
            )
            return None

        objective = (task.get("objective") or "").strip()
        title = (task.get("title") or "").strip()

        return {
            **activation,
            "task": f"{title}\n\n{objective}".strip() if title else objective,
            "issued_by": "controller",
            "source": "controller",
        }

    def heartbeat(self, activation_id: str, lease_seconds: float) -> Optional[dict]:
        try:
            return self._call(
                "POST",
                f"/controller/activations/{activation_id}/heartbeat",
                {"lease_seconds": lease_seconds},
            )
        except ControllerError as exc:
            # Not fatal on its own: the lease may still be alive, and the
            # result submission will find out authoritatively.
            log.warning("heartbeat for %s failed: %s", activation_id, exc)
            return None

    def report(
        self,
        activation_id: str,
        *,
        outcome: str,
        payload: Optional[dict] = None,
    ) -> Optional[dict]:
        """Report an author activation's outcome, retrying on transport failure.

        Retried because losing a result is worse than sending it twice: the
        controller keys idempotency on the request, so a redelivery of the same
        outcome replays the stored response instead of applying it again. The
        retry loop is bounded, and a refusal that is not a transport problem --
        a lapsed lease, a conflicting result -- is reported once and not
        retried, because retrying it unchanged would produce the same refusal
        forever.
        """
        body = {"outcome": outcome, "payload": payload or {}}
        path = f"/controller/activations/{activation_id}/outcome"
        delay = 2.0

        for attempt in range(1, 6):
            try:
                response = self._call("POST", path, body)
            except Unauthenticated as exc:
                log.error("cannot report %s: %s", activation_id, exc)
                return None
            except ControllerError as exc:
                message = str(exc)

                # 4xx from the controller means it decided, not that the
                # network dropped. Sending it again changes nothing.
                if any(code in message for code in (" 403 ", " 404 ", " 409 ", " 400 ")):
                    log.error("controller refused the result for %s: %s",
                              activation_id, message)
                    return None

                if attempt == 5:
                    log.error("giving up reporting %s after %d attempts: %s",
                              activation_id, attempt, message)
                    return None

                log.warning("reporting %s failed (attempt %d): %s; retrying in %.0fs",
                            activation_id, attempt, message, delay)
                time.sleep(delay)
                delay = min(60.0, delay * 2)
                continue

            if response.get("replayed"):
                log.info("result for %s was already recorded; replayed", activation_id)

            return response

        return None
