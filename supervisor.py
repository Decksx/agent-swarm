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

**It will not leave workers behind.** Shutdown terminates the actual Python
processes and waits for them, because a supervisor that exits while its
workers keep polling is worse than one that never started: the operator
believes the swarm is stopped and it is not.

That covers workers it did not start, too. One it adopted, one an operator
launched by hand, one orphaned by a supervisor that was killed -- each is left
alone while *running*, because two claimants for an identity is worse than one
nobody is watching, and each is stopped while *stopping*, because the operator
asked for zero workers and got a number.

Before terminating any of them it confirms the pid really is that identity's
worker. A lock file names a process that was alive when it was written; pids
are reused, so a lock left by a worker that crashed can point at anything, and
a force-kill aimed by that number is how a cleanup becomes an outage
somewhere else. A pid it cannot identify is left alone and reported as
unstopped, which is the honest answer rather than the convenient one.

What it reports is measured, never assumed. A stop that threw, a process that
survived being killed, a lock it declined to act on: each leaves a worker
running, each is counted, and the count is the exit status. Reporting from its
own bookkeeping is how the previous shutdown logged `all workers stopped`
while three processes kept polling.

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

    def stop(self, timeout: float = 20.0) -> bool:
        """Terminate the actual process and wait for it. Returns whether it is gone.

        Waited on rather than signalled and forgotten. A supervisor that exits
        while its workers keep polling is worse than one that never started:
        the operator believes the swarm is stopped and it is not.

        The handle is dropped only once the process is really gone. Clearing
        it regardless is how a failed stop became a successful one: `running()`
        asks the handle, so a `None` handle answers "not running" no matter
        what happened to the process, and `shutdown` then logged
        `all workers stopped` over the top of a worker that was still polling.
        A stop that could not finish has to keep the handle, because that
        handle is the only remaining way to ask about the process at all.
        """
        if not self.running():
            self.process = None
            return True

        pid = self.process.pid
        log.info("stopping %s (pid %s)", self.identity, pid)

        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("%s did not stop in %.0fs; killing", self.identity, timeout)

            try:
                self.process.kill()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.error("%s (pid %s) could not be killed", self.identity, pid)
            except Exception:
                # `kill` itself can throw -- a handle the OS will not let this
                # process touch. Swallowed here so the remaining children are
                # still stopped, and caught by the liveness check below rather
                # than by assuming it worked.
                log.error("could not kill %s", self.identity, exc_info=True)
        except Exception:
            log.error("could not stop %s", self.identity, exc_info=True)

        if self.running():
            log.error(
                "%s (pid %s) is still running after being stopped",
                self.identity, pid,
            )
            return False

        self.process = None
        log.info("stopped %s", self.identity)
        return True


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

        remaining = self.shutdown()
        self.clear_stop_request()

        # Nonzero when the runtime did not actually stop. The control script
        # reads this, and an operator reads the control script; a clean exit
        # after a failed shutdown tells both of them the swarm is down when it
        # is not.
        return 1 if remaining else 0

    def identifies_worker(self, identity: str, pid: int) -> bool:
        """Whether `pid` is really this identity's worker, and not a reused number.

        A lock file records the pid of a worker that was alive when it was
        written. A worker that died without releasing leaves that number
        behind, and pids are reused -- so by the time anything reads it, it
        may belong to something else entirely, which `pid_is_alive` happily
        confirms is running.

        That is survivable while only deciding whether to *start* beside it:
        the worst case is one worker not started. It is not survivable while
        deciding what to *terminate*, so the command line is read and has to
        name this identity's script before anything is killed.

        The script name alone, not the repository path: `worker_ctl.sh` and
        `start_workers.bat` both launch with a bare script name from the
        repository as the working directory, so requiring a path would refuse
        to stop exactly the manually started workers this is for. The lock is
        already checkout-scoped -- it lives in this control directory -- so
        what is left to rule out is pid reuse, and a recycled pid running
        `gemini_worker.py` is a gemini worker.

        Unreadable means no. A command line this cannot obtain is a process
        this must not kill.
        """
        script = WORKERS.get(identity)

        if script is None:
            return False

        command = swarm_control.process_command_line(pid)

        if not command:
            log.error(
                "cannot read the command line of pid %s holding the %s lock; "
                "not terminating it", pid, identity,
            )
            return False

        return script.lower() in command.replace("\\", "/").lower()

    def stop_unsupervised(self, identity: str) -> bool:
        """Stop a worker for `identity` that this supervisor did not spawn.

        Returns whether the identity is free of workers afterwards.

        `Child.start` leaves an adopted, manually started or orphaned worker
        alone on purpose, because two claimants for one identity is worse than
        one that nothing is watching. Leaving it alone while *running* is not
        leaving it alone while *stopping*: the operator asked for zero
        workers, and a worker that outlives the supervisor keeps polling and
        claiming with nothing supervising it -- which is the state the whole
        branch exists to end.
        """
        pid = swarm_control.SingleInstance(identity)._holder()

        if pid is None or pid == os.getpid():
            return True

        if not self.identifies_worker(identity, pid):
            log.error(
                "the %s lock names pid %s, which is not a %s worker; leaving "
                "it alone and reporting the identity as unstopped",
                identity, pid, identity,
            )
            return False

        log.info(
            "stopping %s (pid %s), which this supervisor did not start",
            identity, pid,
        )

        if swarm_control.terminate_pid(pid):
            log.info("stopped %s (pid %s)", identity, pid)
            return True

        log.error("%s (pid %s) could not be stopped", identity, pid)
        return False

    def remaining_workers(self) -> dict:
        """Identity -> pid for every supervised identity still running.

        Asked of the host, not of this object's bookkeeping. A child whose
        termination threw is still a process, and a lock held by a worker this
        supervisor never spawned is still a worker -- neither is visible in a
        handle this process happens to hold. Reporting from the handles alone
        is exactly how a shutdown logged `all workers stopped` while three
        processes kept polling.
        """
        remaining = {}

        for identity, child in self.children.items():
            if child.running():
                remaining[identity] = child.pid
                continue

            holder = swarm_control.SingleInstance(identity)._holder()

            if holder is not None:
                remaining[identity] = holder

        return remaining

    def shutdown(self) -> int:
        """Stop every worker for a supervised identity. Returns how many survive.

        Counted rather than asserted, and the count is the return value
        because the process exit status is built from it. Requirement 6 is
        zero workers, and a shutdown that cannot reach zero has to say so
        loudly enough that the operator does not read `stopped` and believe it.
        """
        log.info("shutting down")

        for child in self.children.values():
            child.stop()

        for identity in self.children:
            self.stop_unsupervised(identity)

        remaining = self.remaining_workers()

        if remaining:
            log.error(
                "workers still running after shutdown: %s",
                ", ".join(f"{i} (pid {p})" for i, p in sorted(remaining.items())),
            )
        else:
            log.info("all workers stopped")

        return len(remaining)

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
    parser.add_argument(
        "--reap", action="store_true",
        help="stop any surviving worker and exit; does not supervise",
    )
    args = parser.parse_args(argv[1:])

    configure_logging(Path(args.log) if args.log else None)

    if args.reap:
        # The backstop for the one case the loop cannot cover: a supervisor
        # that had to be force-killed never ran its own shutdown, so its
        # children are orphaned and something else has to stop them.
        #
        # It is this file rather than a few lines of shell because the shell
        # would kill whatever pid the lock file names, and that is precisely
        # the read a recycled pid makes wrong. Reusing `stop_unsupervised`
        # means the emergency path confirms what it is killing on exactly the
        # same evidence the ordinary one does.
        #
        # No lock is taken: by the time this runs the supervisor is gone, and
        # a reap that refused to run because of a lock file left behind by the
        # process it is cleaning up after would be useless.
        reaper = Supervisor(
            repo=HERE, python=args.python, controller_url=args.url,
            admin_secret="", interval=args.interval, identities=args.only,
            requests_module=None,
        )

        for identity in reaper.children:
            reaper.stop_unsupervised(identity)

        remaining = reaper.remaining_workers()

        if remaining:
            log.error(
                "workers still running after reap: %s",
                ", ".join(f"{i} (pid {p})" for i, p in sorted(remaining.items())),
            )
            return 1

        log.info("no workers running")
        return 0

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
