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
import base64
import json
import sys
import urllib.error
import urllib.request

DEFAULT_ENV = "/mnt/user/appdata/agent-swarm/hub.env"
DEFAULT_URL = "http://127.0.0.1:8050"
ADMIN = "admin"


def read_secret(path: str, component: str) -> str:
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
    p.add_argument("stage", choices=["author", "review"])
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
        status, body = call(url, secret, "POST", "/controller/tasks", {
            "task_id": args.task_id,
            "title": args.title,
            "objective": args.objective,
            "base_sha": args.base_sha,
        })

        if status >= 400 or not args.ready:
            return show(status, body)

        print(f"created {args.task_id}")
        return show(*call(
            url, secret, "POST", f"/controller/tasks/{args.task_id}/ready"
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
