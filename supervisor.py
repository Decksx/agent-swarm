"""One process that keeps the swarm alive while nobody is watching.

Everything the controller needs already exists and every stage boundary is
automated. What is missing is that all of it runs only while a person is
typing: three workers started by hand, `advance` invoked by hand, the sweep
invoked by hand. This is the process that does those things on a timer.

Deliberately small
------------------

It starts three child processes, restarts them when they die, and calls two
controller routes on an interval. It makes no decisions about work: it does
not choose tasks, does not plan, does not judge, and calls no model itself.
Everything it triggers is something the controller was already willing to do.

That boundary is the reason it can be trusted to run unattended. A supervisor
that could decide anything would be a fourth agent with no review and no
ledger; this one is a clock and a restart loop.

What it will not do
-------------------

**It will not start a second worker for an identity.** Each child holds its own
`SingleInstance` lock, and this checks liveness before spawning -- two
independent guards, because the cost of getting it wrong is two processes
claiming activations for one identity and each believing it is alone.

**It will not restart faster than its backoff allows.** A worker that dies on
startup -- a missing credential, a syntax error -- dies again immediately, and
an unbounded restart loop turns that into a spin that fills a disk with logs.
Exponential with a ceiling, and the delay is per identity so one broken worker
does not slow the others.

**It will not run while paused.** The pause flag stops claims and advancement
and leaves the supervisor up, because a pause is an operator saying "stop
starting work", not "tear down the runtime". Coming back is then a file
deletion rather than a restart.

**It will not leave children behind.** Shutdown terminates the actual Python
processes and waits for them, because a supervisor that exits while its
workers keep polling is worse than one that never started: the operator
believes the swarm is stopped and it is not.

Idle costs nothing
------------------

An empty queue produces no model call and no message. The workers poll the
controller and are told there is nothing; `advance` looks for tasks in two
states and finds none. Nothing in this path talks to a model, and nothing
posts to the hub.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import swarm_control

HERE = Path(__file__).resolve().parent

# The identities this supervises, and the script each one runs.
WORKERS = {
    "chatgpt": "chatgpt_worker.py",
    "gemini": "gemini_worker.py",
    "claudecode": "claude_worker.py",
}

# Restart backoff. Doubling from the floor to the ceiling, per identity.
#
# The floor is not zero: a worker that dies during startup dies again
# immediately, and restarting instantly turns one broken credential into a
# spin that fills a disk. The ceiling is not unbounded either -- a worker
# broken for an hour should still be retried, because the fix is often
# somebody setting an environment variable and not wanting to restart the
# supervisor to have it noticed.
BACKOFF_FLOOR = 5.0
BACKOFF_CEILING = 300.0

# How long a worker must stay up before its backoff is forgiven. Without this
# a worker that crashes every ten minutes keeps its longest delay forever.
BACKOFF_RESET_AFTER = 120.0

# How an operator asks for shutdown.
#
# A file rather than a signal, because a signal does not reliably arrive. On
# Windows `taskkill` without /F posts WM_CLOSE, which a background console
# process ignores, and `taskkill /F` terminates without running any handler at
# all -- so the first live stop force-killed the supervisor and left all three
# workers polling. The operator was told the swarm had stopped and it had not.
#
# The pause flag already worked this way for the same reason. A file is checked
# rather than delivered, so it cannot be missed, and it survives the supervisor
# being busy when it is written.
STOP_FILENAME = "STOPPING"

log = logging.getLogger("supervisor")


class Child:
    """One supervised worker, and everything known about its restarts."""

    def __init__(self, identity: str, script: str, python: str, repo: Path):
        self.identity = identity
        self.script = script
        self.python = python
        self.repo = repo
        self.process: Optional[subprocess.Popen] = None
        self.backoff = BACKOFF_FLOOR
        self.not_before = 0.0
        self.started_at = 0.0
        self.restarts = 0

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process is not None else None

    def running(self) -> bool:
        """Whether this child is alive, asked of the process and not a flag."""
        if self.process is None:
            return False

        return self.process.poll() is None

    def lock_holder(self) -> Optional[int]:
        """The pid holding this identity's lock, if any is alive.

        The second guard. A worker started outside this supervisor -- by an
        operator, or by an earlier supervisor that was killed without
        stopping its children -- holds the lock, and spawning beside it would
        give one identity two claimants.
        """
        lock = swarm_control.SingleInstance(self.identity)
        return lock._holder()

    def start(self, now: float, env: dict) -> bool:
        """Spawn the worker, unless something says not to. Returns whether it did."""
        if self.running():
            return False

        if now < self.not_before:
            return False

        holder = self.lock_holder()

        if holder is not None:
            # Not an error, and not a reason to back off: something is running
            # this identity, which is the state the supervisor wants. Adopting
            # it is not possible -- the process is not this one's child -- so
            # it is left alone and reported.
            log.info(
                "%s is already running as pid %s (not started by this "
                "supervisor); leaving it alone", self.identity, holder,
            )
            self.not_before = now + BACKOFF_FLOOR
            return False

        self.process = subprocess.Popen(
            [self.python, str(self.repo / self.script)],
            cwd=str(self.repo),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # A new process group on POSIX so a signal to the supervisor does
            # not race the children; on Windows the equivalent flag keeps
            # Ctrl-C from reaching them before the supervisor can order a
            # shutdown itself.
            **(
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt" else {"start_new_session": True}
            ),
        )
        self.started_at = now
        log.info("started %s as pid %s", self.identity, self.process.pid)
        return True

    def note_exit(self, now: float) -> None:
        """Record that the child is gone and decide when to try again."""
        code = self.process.poll() if self.process is not None else None
        uptime = now - self.started_at if self.started_at else 0.0

        if uptime >= BACKOFF_RESET_AFTER:
            # It ran long enough to have been working. A crash after an hour
            # is a different event from a crash after a second, and carrying
            # the old delay over would punish the wrong one.
            self.backoff = BACKOFF_FLOOR
        else:
            self.backoff = min(self.backoff * 2, BACKOFF_CEILING)

        self.restarts += 1
        self.not_before = now + self.backoff
        self.process = None

        log.warning(
            "%s exited (code %s) after %.0fs; restarting in %.0fs "
            "(restart %d)",
            self.identity, code, uptime, self.backoff, self.restarts,
        )

    def stop(self, timeout: float = 20.0) -> None:
        """Terminate the actual process and wait for it.

        Waited on rather than signalled and forgotten. A supervisor that exits
        while its workers keep polling is worse than one that never started:
        the operator believes the swarm is stopped and it is not.
        """
        if not self.running():
            self.process = None
            return

        pid = self.process.pid
        log.info("stopping %s (pid %s)", self.identity, pid)

        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("%s did not stop in %.0fs; killing", self.identity, timeout)
            self.process.kill()

            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.error("%s (pid %s) could not be killed", self.identity, pid)
        except Exception:
            log.error("could not stop %s", self.identity, exc_info=True)

        self.process = None
        log.info("stopped %s", self.identity)


class Supervisor:
    """The loop. One instance per machine, enforced by its own lock."""

    def __init__(
        self,
        *,
        repo: Path,
        python: str,
        controller_url: str,
        admin_secret: str,
        interval: float,
        identities=None,
        requests_module=None,
    ):
        self.repo = repo
        self.python = python
        self.controller_url = controller_url.rstrip("/")
        self.admin_secret = admin_secret
        self.interval = interval
        self.requests = requests_module
        self.children = {
            identity: Child(identity, script, python, repo)
            for identity, script in WORKERS.items()
            if identities is None or identity in identities
        }
        self.stopping = False
        self.last_tick = 0.0
        self._paused = False

    # --- the controller side -------------------------------------------------

    def _post(self, path: str) -> Optional[dict]:
        """One admin call, or None if the controller could not be reached.

        Connectivity failures are logged and survived. The controller being
        briefly unreachable is an ordinary event on a home network, and a
        supervisor that exited on one would need a person to restart it --
        which is the thing it exists to avoid.
        """
        if self.requests is None:
            return None

        try:
            response = self.requests.post(
                f"{self.controller_url}{path}",
                auth=("admin", self.admin_secret),
                timeout=20,
            )
        except Exception as exc:
            log.warning("controller unreachable at %s: %s", path, exc)
            return None

        if response.status_code >= 400:
            log.warning(
                "controller refused %s: %s %s",
                path, response.status_code, response.text[:200],
            )
            return None

        try:
            return response.json()
        except ValueError:
            log.warning("controller returned unreadable JSON from %s", path)
            return None

    def advance(self) -> None:
        """Issue whatever next stage is unambiguous, and say what happened."""
        body = self._post("/controller/tasks/advance")

        if body is None:
            return

        considered = body.get("considered") or []
        issued = [r for r in considered if r.get("issued")]
        declined = [r for r in considered if not r.get("issued")]

        for record in issued:
            log.info(
                "activation issued: %s %s -> %s (%s)",
                record.get("task_id"), record.get("state"),
                record.get("stage"), record.get("agent"),
            )

        for record in declined:
            # Declines are logged at debug because a healthy swarm produces
            # them constantly -- a task mid-stage is a decline every tick --
            # and at info they would bury the events that matter.
            log.debug(
                "activation declined: %s (%s)",
                record.get("task_id"), record.get("reason"),
            )

        if not considered:
            log.debug("advance: nothing ready")

    def sweep(self) -> None:
        """Reclaim anything past its lease, and report what was reclaimed."""
        body = self._post("/controller/activations/sweep")

        if body is None:
            return

        reclaimed = body.get("reclaimed") or []

        for item in reclaimed:
            log.warning(
                "swept %s (%s, stage %s): %s -> %s",
                item.get("task_id"), item.get("activation_id", "")[:8],
                item.get("stage"), item.get("reason"), item.get("recovery"),
            )

        if not reclaimed:
            log.debug("sweep: nothing expired")

    # --- the loop ------------------------------------------------------------

    def child_env(self, identity: str) -> dict:
        """The environment one worker is started with.

        Inherited, with the identity pinned and **that identity's own hub
        credential** put where the worker looks for it.

        Every worker reads `HUB_SECRET`, and each authenticates as a different
        component -- so passing the supervisor's own admin secret through
        would have all three presenting the wrong credential and being
        refused. The per-identity secrets arrive as `CHATGPT_HUB_SECRET` and
        friends, fetched once by the control script, and are mapped here.

        An identity whose secret is absent is still started: the worker's own
        startup refuses with a message naming the credential, which is a
        better error than anything this could invent, and it keeps the mapping
        from silently substituting one identity's secret for another's.
        """
        env = dict(os.environ)
        env["AGENT_IDENTITY"] = identity
        env["ACTIVATION_SOURCE"] = "controller"

        secret = os.environ.get(f"{identity.upper()}_HUB_SECRET", "").strip()

        if secret:
            env["HUB_SECRET"] = secret
        else:
            # Removed rather than left as the supervisor's. A worker with no
            # credential says so; a worker with the wrong one gets a 401 it
            # cannot explain.
            env.pop("HUB_SECRET", None)

        return env

    def stop_requested(self) -> bool:
        """Whether an operator has asked this to shut down."""
        return (swarm_control.CONTROL_DIR / STOP_FILENAME).exists()

    def clear_stop_request(self) -> None:
        """Remove the flag, so the next start is not stopped immediately."""
        try:
            (swarm_control.CONTROL_DIR / STOP_FILENAME).unlink()
        except OSError:
            pass

    def tick(self, now: Optional[float] = None) -> None:
        """One pass: reap, restart, and drive the controller."""
        now = time.time() if now is None else now

        if self.stop_requested():
            log.info("stop requested")
            self.stopping = True
            return

        paused = swarm_control.is_paused()

        if paused != self._paused:
            reason = swarm_control.pause_reason() or "(no reason recorded)"
            log.warning(
                "pause %s: %s", "engaged" if paused else "released", reason,
            )
            self._paused = paused

        for child in self.children.values():
            if child.process is not None and not child.running():
                child.note_exit(now)

        if paused:
            # Children are left running. They check the pause flag themselves
            # before claiming, so a paused swarm is a set of idle processes
            # rather than a torn-down runtime -- and coming back is a file
            # deletion, not a restart.
            return

        for child in self.children.values():
            child.start(now, self.child_env(child.identity))

        if now - self.last_tick >= self.interval:
            self.last_tick = now
            self.advance()
            self.sweep()

    def run(self) -> int:
        """Until told to stop."""
        log.info(
            "supervising %s every %.0fs against %s",
            ", ".join(sorted(self.children)), self.interval, self.controller_url,
        )

        while not self.stopping:
            try:
                self.tick()
            except Exception:
                # One bad tick must not end the runtime. Whatever it was will
                # very likely recur next tick, and it will be logged again.
                log.error("tick failed", exc_info=True)

            time.sleep(1.0)

        self.shutdown()
        self.clear_stop_request()
        return 0

    def shutdown(self) -> None:
        log.info("shutting down")

        for child in self.children.values():
            child.stop()

        remaining = [c.identity for c in self.children.values() if c.running()]

        if remaining:
            log.error("workers still running after shutdown: %s", remaining)
        else:
            log.info("all workers stopped")

    def status(self) -> dict:
        return {
            "paused": swarm_control.is_paused(),
            "workers": {
                child.identity: {
                    "running": child.running(),
                    "pid": child.pid,
                    "restarts": child.restarts,
                    "backoff": child.backoff,
                }
                for child in self.children.values()
            },
        }


def configure_logging(path: Optional[Path] = None) -> None:
    """Timestamped, to the console and to a file.

    The format is not decoration. A supervisor's log is read after the fact,
    when somebody wants to know why a worker was not running at three in the
    morning, and a line without a timestamp cannot answer that.
    """
    handlers: list = [logging.StreamHandler(sys.stdout)]

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        handlers=handlers,
        force=True,
    )


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get(
        "CONTROLLER_URL", "http://192.168.42.50:8050"))
    parser.add_argument(
        "--interval", type=float,
        default=float(os.environ.get("SUPERVISOR_INTERVAL", "20")),
        help="seconds between advance/sweep passes",
    )
    parser.add_argument(
        "--python", default=os.environ.get("SUPERVISOR_PYTHON", sys.executable)
    )
    parser.add_argument(
        "--only", action="append", default=None,
        help="supervise only this identity. Repeatable.",
    )
    parser.add_argument("--log", default=os.environ.get("SUPERVISOR_LOG", ""))
    args = parser.parse_args(argv[1:])

    configure_logging(Path(args.log) if args.log else None)

    secret = os.environ.get("HUB_SECRET", "").strip()

    if not secret:
        log.error(
            "HUB_SECRET is not set. The supervisor calls the controller as "
            "admin to advance and sweep; without it there is nothing it can do "
            "but restart workers."
        )
        return 2

    try:
        import requests
    except ImportError:
        log.error("requests is not installed")
        return 2

    lock = swarm_control.SingleInstance("supervisor")

    try:
        lock.acquire()
    except swarm_control.AlreadyRunning as exc:
        log.error("%s", exc)
        return 1

    supervisor = Supervisor(
        repo=HERE, python=args.python, controller_url=args.url,
        admin_secret=secret, interval=args.interval, identities=args.only,
        requests_module=requests,
    )

    def stop(signum, _frame):
        log.info("signal %s received", signum)
        supervisor.stopping = True

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), stop)
            except (ValueError, OSError):
                pass

    try:
        return supervisor.run()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
