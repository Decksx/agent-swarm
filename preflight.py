"""Refuse to run against a controller that is not this checkout.

Two live runs were spent against a stale deployment before this existed. Both
times the symptom was misleading rather than obvious -- an API silently
ignoring a field it did not know, an activation issued that the current code
would have refused -- and the time went into diagnosis, not the fix.

This is the automatic version of the check that was previously "remember to
deploy". It asks the running controller what it is, computes what this checkout
would deploy, and exits non-zero if they differ, naming the files.

The hub reports two builds: the one it started with, and the one on its disk
now. Both must equal this checkout. A deploy that copies files without
restarting satisfies the second and not the first, and a check that read only
the disk would pass while the old code kept serving -- so the difference
between them is a verdict of its own.

Called by the worker launchers before they start anything. A worker that starts
against a stale controller produces evidence about a build nobody has, which is
worse than not running at all, because the evidence looks valid.

Usage::

    python preflight.py --url http://192.168.42.50:8050 --agent claudecode
    python preflight.py --url ... --agent claudecode --expect-schema 2

The credential comes from ``HUB_SECRET`` in the environment -- the same one the
worker is about to use, so a preflight that passes is also evidence that the
worker's own credential works.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller import build  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent


def fetch_status(url: str, agent: str, secret: str, timeout: float = 15.0) -> dict:
    token = base64.b64encode(f"{agent}:{secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url.rstrip("/") + "/controller/status",
        headers={"Authorization": f"Basic {token}"},
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def diagnose(expected: dict, loaded: dict, disk: dict) -> dict:
    """Which of the three builds disagree, and what to do about it.

    Three builds, because the two obvious ones are not enough:

    * `expected` -- what this checkout would deploy.
    * `loaded`   -- what the controller process started with.
    * `disk`     -- what is sitting on the host right now.

    "Never deployed" and "deployed but never restarted" both show up as "the
    controller is not running my code", and the fixes are different. Worse,
    the second one *passes* a check that only reads the host's files: they are
    correct, and the running process is not. That is the original incident with
    better camouflage, so it gets its own verdict and its own instruction.

    Only unanimity is OK. Anything else names the files and says which of the
    three pairs disagreed.
    """
    running = build.compare(expected, loaded)
    host = build.compare(expected, disk)
    restart = build.compare(loaded, disk)

    lines = []

    def name_files(result: dict, prefix: str) -> None:
        for name in result["differing"]:
            lines.append(f"  {prefix} differs            : {name}")
        for name in result["missing_from_deployment"]:
            lines.append(f"  {prefix} missing             : {name}")
        for name in result["not_in_the_repository"]:
            lines.append(f"  {prefix} unexpected          : {name}")

    if running["match"] and host["match"] and restart["match"]:
        return {"ok": True, "verdict": "current", "lines": []}

    if not loaded.get("build_id") and not disk.get("build_id"):
        return {
            "ok": False,
            "verdict": "predates_this_check",
            "lines": [
                "  the hub reported no build at all. That controller predates "
                "this check, which means it also predates everything else in "
                "this checkout.",
            ],
        }

    if host["match"] and not restart["match"]:
        lines.append(
            "  the files on the host are this checkout, but the running "
            "process started with different ones. It was deployed and not "
            "restarted, and it is still serving the old code."
        )
        name_files(restart, "started-with vs on-disk:")

        return {"ok": False, "verdict": "not_restarted", "lines": lines}

    if running["match"] and not host["match"]:
        lines.append(
            "  the running process is this checkout, but the files under it "
            "are not. Something wrote to the host after it started. Restart "
            "to load whatever is there now, or restore it -- and until then "
            "a build id read from that disk describes nobody's code."
        )
        name_files(host, "checkout vs on-disk:")

        return {"ok": False, "verdict": "changed_since_startup", "lines": lines}

    if restart["match"] and not host["match"]:
        lines.append(
            "  the host is running exactly what was deployed to it, and that "
            "is not this checkout. It was never deployed."
        )
        name_files(host, "checkout vs hub:")

        return {"ok": False, "verdict": "not_deployed", "lines": lines}

    lines.append(
        "  the checkout, the running process and the host's files are three "
        "different builds. Deploy this checkout and restart, then run this "
        "again before trusting anything the hub says."
    )
    name_files(host, "checkout vs on-disk:")
    name_files(running, "checkout vs running:")

    return {"ok": False, "verdict": "inconsistent", "lines": lines}


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--expect-schema", type=int, default=None,
        help="refuse unless the controller reports this schema version",
    )
    parser.add_argument(
        "--allow-mismatch", action="store_true",
        help="report the difference and continue anyway. For diagnosing a "
             "mismatch, never for working around one.",
    )
    args = parser.parse_args(argv[1:])

    secret = os.environ.get("HUB_SECRET", "")

    if not secret:
        print("preflight: HUB_SECRET is not set")
        return 2

    try:
        status = fetch_status(args.url, args.agent, secret)
    except urllib.error.HTTPError as exc:
        # 401 here is worth its own message: it is the other thing that stops a
        # worker dead, and it is not a build problem.
        if exc.code == 401:
            print(f"preflight: the hub rejected the {args.agent!r} credential (401)")
            return 3

        print(f"preflight: /controller/status returned {exc.code}")
        return 3
    except Exception as exc:
        print(f"preflight: cannot reach {args.url}: {exc}")
        return 3

    expected = build.from_repository(REPO_ROOT)
    loaded = {
        "build_id": status.get("loaded_build_id"),
        "files": status.get("loaded_files", {}),
    }
    disk = {
        "build_id": status.get("disk_build_id"),
        "files": status.get("disk_files", {}),
    }
    result = diagnose(expected, loaded, disk)

    schema = status.get("schema_version")
    print(f"preflight: controller schema {schema}")
    print(f"preflight: this checkout    build {str(expected['build_id'])[:12]}")
    print(f"preflight: hub is running   build {str(loaded['build_id'])[:12]}")
    print(f"preflight: hub has on disk  build {str(disk['build_id'])[:12]}")

    failed = False

    if args.expect_schema is not None and schema != args.expect_schema:
        print(
            f"preflight: FAIL schema version is {schema}, expected "
            f"{args.expect_schema}"
        )
        failed = True

    if not result["ok"]:
        print(
            f"preflight: FAIL the deployed controller is not this checkout "
            f"({result['verdict']})"
        )

        for line in result["lines"]:
            print(line)

        failed = True

    if failed:
        if args.allow_mismatch:
            print("preflight: continuing anyway (--allow-mismatch)")
            return 0

        print(
            "preflight: refusing to run. Deploy this checkout, or pass "
            "--allow-mismatch if you are deliberately testing against an old "
            "build and will not treat the result as evidence."
        )
        return 1

    print(
        "preflight: OK, the deployed controller is this checkout, and it "
        "is running it"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
