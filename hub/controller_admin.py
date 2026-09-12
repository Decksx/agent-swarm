"""Operator CLI for the controller, run on the host that holds hub.env.

The controller's admin routes need an admin credential. This is the way to use
them without one ever appearing in a shell history, a terminal, or a
transcript: the script reads `hub.env` on the host that already has it, builds
the Authorization header itself, and prints only ids and states.

It is the counterpart to `swarm_control.py`, which is the operator's lever on
the execution host. This one is the lever on the control plane.

Usage::

    python3 controller_admin.py status
    python3 controller_admin.py capacity OFFICEPC 1
    python3 controller_admin.py create-task T-1 "title" "objective" --ready
    python3 controller_admin.py issue T-1 claudecode OFFICEPC author
    python3 controller_admin.py show T-1
    python3 controller_admin.py events T-1
    python3 controller_admin.py sweep

Every subcommand takes ``--env-file`` (default
``/mnt/user/appdata/agent-swarm/hub.env``) and ``--url`` (default loopback).
"""

from __future__ import annotations

import argparse
import io
import os
import base64
import json
import sys
import urllib.error
import urllib.request

DEFAULT_ENV = "/mnt/user/appdata/agent-swarm/hub.env"
DEFAULT_URL = "http://127.0.0.1:8050"
ADMIN = "admin"


def read_secret(path: str, component: str) -> str:
    """The component's credential, from the environment or the host's env file.

    `HUB_SECRET` first, because this now runs from an operator's machine as
    well as on the host: the env file lives on Tower and is not readable from
    anywhere else. The variable is the same one every worker uses, so a
    credential is passed the same way everywhere and never written to a second
    file on a second machine.
    """
    from_env = os.environ.get("HUB_SECRET", "").strip()

    if from_env:
        return from_env

    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("HUB_CREDENTIALS="):
                continue

            raw = line.partition("=")[2].strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                raw = raw[1:-1]

            for entry in raw.split(","):
                name, sep, secret = entry.strip().partition(":")
                if sep and name.strip().lower() == component:
                    return secret.strip()

    raise SystemExit(f"no {component!r} credential in {path}")


def call(url, secret, method, path, body=None):
    """Return (status, parsed). Prints nothing; the caller decides."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    token = base64.b64encode(f"{ADMIN}:{secret}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}

    if data is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url + path, data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, None
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, None
    except Exception as exc:
        print(f"cannot reach {url}: {exc}")
        raise SystemExit(2)


def show(status, body):
    print(f"HTTP {status}")
    if body is not None:
        print(json.dumps(body, indent=2, sort_keys=True))
    return 0 if status < 400 else 1


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=DEFAULT_ENV)
    parser.add_argument("--url", default=DEFAULT_URL)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("sweep")

    p = sub.add_parser("repair")
    p.add_argument("task_id")

    p = sub.add_parser("capacity")
    p.add_argument("host")
    p.add_argument("max_concurrent", type=int)

    p = sub.add_parser("create-task")
    p.add_argument("task_id")
    p.add_argument("title")
    p.add_argument("objective")
    p.add_argument("--base-sha", default="0" * 40)
    p.add_argument(
        "--contract-file",
        help="path to the contract to store with the task. A task whose "
             "contract does not declare allowed_paths cannot be authored: "
             "the worker blocks it before calling the model.",
    )
    p.add_argument(
        "--allowed-path", action="append", default=[],
        help="build a minimal contract declaring this path as WRITABLE. "
             "Repeatable. Mutually exclusive with --contract-file.",
    )
    p.add_argument(
        "--context-path", action="append", default=[],
        help="a file or directory the author is shown READ-ONLY, so it can "
             "see what its change has to fit: the interface it calls, the "
             "caller it must not break, the test that pins the behaviour. "
             "Repeatable. It must exist at the base commit or the task blocks "
             "before the model is called. Do not use --allowed-path to let an "
             "author read something -- that buys understanding with write "
             "authority, and a writable file can come back rewritten.",
    )
    p.add_argument(
        "--proof-mode", default="baseline",
        choices=["baseline", "sabotage", "both", "branch_only"],
        help="what the task must produce to be believed. `branch_only` "
             "stops at a candidate on a branch; the default also requires "
             "a baseline run. It is stored on the task version, which is "
             "where a worker reads it -- not in the contract text, so it "
             "does not move the contract hash.",
    )
    p.add_argument(
        "--ready",
        action="store_true",
        help="also move it out of DRAFT to READY_AUTHOR",
    )

    p = sub.add_parser("ready")
    p.add_argument("task_id")

    p = sub.add_parser("issue")
    p.add_argument("task_id")
    p.add_argument("agent")
    p.add_argument("host")
    p.add_argument("stage", choices=["author", "review", "integrate"])
    p.add_argument("--lease-seconds", type=float, default=900.0)
    p.add_argument("--hard-deadline-seconds", type=float, default=5400.0)
    # A review activation without a branch is unreviewable: the controller has
    # no working copy, so this is the only way it can say what to look at.
    p.add_argument("--expected-branch", default=None)
    p.add_argument("--expected-parent", default=None)
    p.add_argument("--expected-candidate", default=None)
    # Required for a review, and not verified by the controller -- it names a
    # path on another host. It exists so the ledger can answer "which checkout
    # was this reviewed in".
    p.add_argument("--repo-location", default=None)

    p = sub.add_parser("show")
    p.add_argument("task_id")

    p = sub.add_parser("events")
    p.add_argument("task_id")

    p = sub.add_parser("retry")
    p.add_argument("task_id")

    # A proposal that was looked at and turned down needs somewhere to go. It
    # is not a failure -- nothing was attempted -- and leaving it in DRAFT
    # records only that nobody got to it, which is the opposite of what
    # happened. CANCELLED is terminal, so the reason travels with it: a
    # rejected task whose ledger does not say why is a task somebody proposes
    # again.
    p = sub.add_parser("cancel")
    p.add_argument("task_id")
    p.add_argument(
        "--reason", required=True,
        help="why it was rejected. Required: this is the only record of the "
             "judgment, and the state alone says a decision was made without "
             "saying what it was.",
    )

    args = parser.parse_args(argv[1:])
    secret = read_secret(args.env_file, ADMIN)
    url = args.url.rstrip("/")

    if args.command == "status":
        return show(*call(url, secret, "GET", "/controller/status"))

    if args.command == "sweep":
        return show(*call(url, secret, "POST", "/controller/activations/sweep"))

    if args.command == "capacity":
        return show(*call(url, secret, "POST", "/controller/hosts", {
            "host": args.host, "max_concurrent": args.max_concurrent,
        }))

    if args.command == "create-task":
        if args.contract_file and args.allowed_path:
            print("give --contract-file or --allowed-path, not both")
            return 2

        if args.contract_file and args.context_path:
            print("give --contract-file or --context-path, not both")
            return 2

        if args.context_path and not args.allowed_path:
            # A reading list with no write authority describes a task that can
            # read and not act. The worker would block on the contract anyway;
            # saying so here costs nothing and names the actual omission.
            print(
                "--context-path needs --allowed-path: a task that may read "
                "but not write cannot be authored"
            )
            return 2

        if args.contract_file:
            contract = io.open(args.contract_file, encoding="utf-8").read()
        elif args.allowed_path:
            entries = "".join(f"  - {entry}\n" for entry in args.allowed_path)
            contract = (
                "schema_version: 7\n"
                f"task_id: {args.task_id}\n"
                "allowed_paths:\n"
                f"{entries}"
            )

            # Written after allowed_paths, never merged into it. The two lists
            # authorise different things, and a contract that ran them together
            # would hand the author write access to its own reference material.
            if args.context_path:
                reading = "".join(f"  - {entry}\n" for entry in args.context_path)
                contract += f"context_paths:\n{reading}"
        else:
            # Deliberately not a default that would authorise anything. The
            # task is created and will block at authoring, naming the reason,
            # which is better than a contract nobody wrote being honoured.
            contract = "schema_version: 7\n"

        status, body = call(url, secret, "POST", "/controller/tasks", {
            "task_id": args.task_id,
            "title": args.title,
            "objective": args.objective,
            "base_sha": args.base_sha,
            "contract_yaml": contract,
            "proof_mode": args.proof_mode,
        })

        if status >= 400 or not args.ready:
            return show(status, body)

        print(f"created {args.task_id}")
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/ready"
        ))

    if args.command == "retry":
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/retry"
        ))

    if args.command == "cancel":
        # Through the generic transition route, because `admin_cancelled` is
        # genuinely an admin-authority transition -- unlike `ready`, where the
        # operator asks and the controller decides. A person rejecting a
        # proposal is the decision, and the ledger should say so.
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/transition",
            {"kind": "admin_cancelled", "payload": {"reason": args.reason}},
        ))

    if args.command == "repair":
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/repair"
        ))

    if args.command == "ready":
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/ready"
        ))

    if args.command == "issue":
        return show(*call(url, secret, "POST", "/controller/activations", {
            "task_id": args.task_id,
            "agent": args.agent,
            "host": args.host,
            "stage": args.stage,
            "lease_seconds": args.lease_seconds,
            "hard_deadline_seconds": args.hard_deadline_seconds,
            "expected_branch": args.expected_branch,
            "expected_parent": args.expected_parent,
            "expected_candidate": args.expected_candidate,
            "repo_location": args.repo_location,
        }))

    if args.command == "show":
        return show(*call(url, secret, "GET", f"/controller/tasks/{args.task_id}"))

    if args.command == "events":
        status, body = call(
            url, secret, "GET", f"/controller/tasks/{args.task_id}/events"
        )

        if status >= 400 or not body:
            return show(status, body)

        # Compact by default: the payloads are large and the interesting part
        # of an event log is the sequence of who did what under what authority.
        print(f"HTTP {status}")
        for event in body.get("events", []):
            print(
                "  seq={seq:<3} {kind:<32} {frm} -> {to}  "
                "actor={actor} authority={authority}".format(
                    seq=event.get("seq"),
                    kind=event.get("kind"),
                    frm=event.get("from_state"),
                    to=event.get("to_state"),
                    actor=event.get("actor"),
                    authority=event.get("authority"),
                )
            )
        return 0

    parser.error(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
