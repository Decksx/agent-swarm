"""Refuse to run against a controller that is not this checkout.

Two live runs were spent against a stale deployment before this existed. Both
times the symptom was misleading rather than obvious -- an API silently
ignoring a field it did not know, an activation issued that the current code
would have refused -- and the time went into diagnosis, not the fix.

This is the automatic version of the check that was previously "remember to
deploy". It asks the running controller what it is, computes what this checkout
would deploy, and exits non-zero if they differ, naming the files.

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
    deployed = {
        "build_id": status.get("build_id"),
        "files": status.get("files", {}),
    }
    result = build.compare(expected, deployed)

    schema = status.get("schema_version")
    print(f"preflight: controller schema {schema}, build {str(deployed['build_id'])[:12]}")
    print(f"preflight: this checkout   build {str(expected['build_id'])[:12]}")

    failed = False

    if args.expect_schema is not None and schema != args.expect_schema:
        print(
            f"preflight: FAIL schema version is {schema}, expected "
            f"{args.expect_schema}"
        )
        failed = True

    if not result["match"]:
        print("preflight: FAIL the deployed controller is not this checkout")

        for name in result["differing"]:
            print(f"  differs            : {name}")
        for name in result["missing_from_deployment"]:
            print(f"  missing on the hub : {name}")
        for name in result["not_in_the_repository"]:
            print(f"  extra on the hub   : {name}")

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

    print("preflight: OK, the deployed controller is this checkout")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
