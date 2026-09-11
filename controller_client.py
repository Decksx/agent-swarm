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

Failures are sorted by what the worker can actually do about them, because
"retry" is the wrong answer to most of them:

* **401, or 403 on the claim route** -- fatal. Raised to the worker, which
  exits with a distinct code. A credential cannot change inside a running
  process, so every subsequent poll fails identically; backing off merely
  produces a worker that is alive, logging, and structurally incapable of ever
  doing work. That is harder to notice than a process that exited.
* **429** -- wait exactly as long as the server asked. Inventing a backoff
  against a server that already named an interval is either too eager or too
  slow.
* **Network errors and 5xx** -- bounded exponential backoff. These do resolve
  on their own, and a worker polling a broken hub every three seconds turns one
  outage into a log nobody can read.
* **Any other 4xx** -- a decision, not a failure. Reported once and not
  retried, because the same request produces the same decision.
* **An empty queue** -- not a failure at all. Normal polling cadence.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("controller_client")


class ControllerError(Exception):
    """The controller could not be reached, or refused in a way worth stopping for."""


class Unauthenticated(ControllerError):
    """The hub rejected this worker's credential.

    Fatal by design. A credential cannot change inside a running process, so
    every subsequent poll fails identically -- and a worker that keeps polling
    on a rejected credential is alive, logging, and structurally incapable of
    doing any work. That is harder to notice than a process that exited, and it
    is the same failure the launcher's HUB_SECRET warning exists to prevent.
    """


class ClaimForbidden(ControllerError):
    """The hub authenticated this worker but refused to let it ask for work.

    Also fatal, and separated from a 403 on a *result* route on purpose. A 403
    when reporting an outcome means "that activation is not yours", which is
    about one activation and resolves on the next claim. A 403 on the claim
    route itself means this component may not take work at all, which nothing
    the worker does will change.
    """


class RateLimited(ControllerError):
    """The hub asked this worker to wait a specific amount of time."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Refused(ControllerError):
    """The controller declined for a reason that will not change on retry."""


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

        # How long the server last asked this worker to wait, if it did. Read
        # by the worker to pace its next poll; zero means the ordinary cadence.
        self.retry_after = 0.0

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

        if response.status_code == 429:
            # Honour the interval the server asked for rather than guessing.
            # A client that invents its own backoff against a server that
            # already said how long to wait is either too eager or too slow,
            # and both are worse than doing as it is told.
            raw = ""
            try:
                raw = response.headers.get("Retry-After", "") or ""
            except Exception:
                raw = ""

            try:
                retry_after = float(raw)
            except (TypeError, ValueError):
                retry_after = 30.0

            raise RateLimited(f"{method} {path}: 429", max(1.0, retry_after))

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

            message = f"{method} {path}: {response.status_code} {detail}"

            # 5xx is the server having a bad time and is worth retrying; any
            # other 4xx is a decision, and sending the same request again
            # produces the same decision.
            if response.status_code < 500:
                raise Refused(message)

            raise ControllerError(message)

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
        except Unauthenticated:
            # Raised, not swallowed. The worker exits on this.
            raise
        except Refused as exc:
            # A 403 here is not "that activation is not yours" -- there is no
            # activation in the request. It means this component may not take
            # work, which no amount of polling changes.
            if " 403 " in str(exc):
                raise ClaimForbidden(str(exc)) from exc

            self.backoff.fail(str(exc))
            return None
        except RateLimited as exc:
            log.warning(
                "controller asked for %.0fs before the next claim", exc.retry_after
            )
            self.retry_after = exc.retry_after
            return None
        except ControllerError as exc:
            self.backoff.fail(str(exc))
            return None

        self.retry_after = 0.0
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
            # The whole record, not just the rendered prompt. A reviewer needs
            # the objective and acceptance criteria verbatim to judge against
            # them, and re-deriving those by splitting the prompt back apart
            # would be a second parser to keep in step with the first.
            "task_record": task,
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

    def judge(
        self,
        activation_id: str,
        *,
        judgment: str,
        payload: Optional[dict] = None,
    ) -> Optional[dict]:
        """Submit a review judgment for an activation this worker holds.

        A separate method from `report` and a separate route, because they are
        separate authorities. An author reports what it did; a reviewer's
        judgment is applied by the controller on the strength of the reviewer
        holding that specific live review activation. Collapsing them into one
        call would hide that difference at exactly the place it matters.
        """
        return self._submit(
            f"/controller/activations/{activation_id}/review",
            {"judgment": judgment, "payload": payload or {}},
            activation_id,
        )

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
        return self._submit(
            f"/controller/activations/{activation_id}/outcome",
            {"outcome": outcome, "payload": payload or {}},
            activation_id,
        )

    def report_integration(
        self,
        activation_id: str,
        *,
        outcome: str,
        payload: Optional[dict] = None,
    ) -> Optional[dict]:
        """Report an integration activation's outcome.

        A separate route from `report`, because integration outcomes are not
        the author's and the controller checks the stage: submitting
        `integrated` against an author activation is refused rather than
        applied to the wrong task. Same retry discipline -- losing the result
        of an integration is the worst of the three, because the merge may
        already have happened and the ledger would not say so.
        """
        return self._submit(
            f"/controller/activations/{activation_id}/integration",
            {"outcome": outcome, "payload": payload or {}},
            activation_id,
        )

    def _submit(self, path: str, body: dict, activation_id: str) -> Optional[dict]:
        """Deliver one terminal submission, retrying only what retrying helps.

        Shared by `report` and `judge` because the delivery discipline is the
        same for both and a second copy of it would drift: losing a result is
        worse than sending it twice, since the controller keys idempotency on
        the request and replays rather than reapplying.
        """
        delay = 2.0

        for attempt in range(1, 6):
            try:
                response = self._call("POST", path, body)
            except Unauthenticated as exc:
                log.error("cannot report %s: %s", activation_id, exc)
                return None
            except Refused as exc:
                # The controller decided: a lapsed lease, a conflicting result,
                # an activation that is not this worker's. Retrying sends the
                # same request and gets the same answer. Notably NOT fatal to
                # the worker -- a 403 here is about one activation, and the
                # next claim is unaffected.
                log.error("controller refused the result for %s: %s",
                          activation_id, exc)
                return None
            except RateLimited as exc:
                log.warning("asked to wait %.0fs before reporting %s",
                            exc.retry_after, activation_id)
                time.sleep(exc.retry_after)
                continue
            except ControllerError as exc:
                message = str(exc)

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
