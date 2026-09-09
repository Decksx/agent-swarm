"""Post-deployment verification for the hub, run on the host that holds hub.env.

What this is for
----------------

The hub suite proves the code behaves. This proves the *deployment* behaves:
that the container came up with the credentials it was given, that every route
including the newly mounted controller still refuses an anonymous caller, that
the documentation routes are still gone, and that admin authority is still
admin-only. Those are properties of a running container and a bind mount, and
no local test can establish them.

It prints component names, route paths and HTTP status codes. **It never
prints a credential**, and it reads `hub.env` only to build request headers.

Side effects, stated because a verifier that writes is worth being explicit
about: the pause check engages and then releases the global pause, and leaves
it released. It writes nothing to the chat database -- sender derivation is
covered by the hub test suite, and adding a verification message to the
operator's message log to re-prove it is not worth the row.

Usage::

    python3 verify_deploy.py --env-file /mnt/user/appdata/agent-swarm/hub.env

Exit status is 0 when every check passes and 1 when any fails, so a deploy
script can gate on it rather than on someone reading the output.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8050"

# Routes that must answer 401 without a credential. The controller routes are
# in this list because a new router mounted onto an authenticated app is
# exactly the change that can quietly add an unauthenticated surface.
PROTECTED = [
    ("GET", "/"),
    ("GET", "/messages"),
    ("POST", "/send"),
    ("GET", "/control/status"),
    ("POST", "/control/pause"),
    ("POST", "/control/resume"),
    ("GET", "/controller/status"),
    ("POST", "/controller/activations/claim"),
    ("POST", "/controller/tasks"),
    ("GET", "/controller/tasks/anything"),
]

# Removed rather than protected: they handed the whole API surface to any LAN
# caller and nothing operational reads them.
GONE = ["/docs", "/redoc", "/openapi.json"]


def read_credentials(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("HUB_CREDENTIALS="):
                raw = line.partition("=")[2].strip()
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                    raw = raw[1:-1]
                out = {}
                for entry in raw.split(","):
                    name, sep, secret = entry.strip().partition(":")
                    if sep:
                        out[name.strip().lower()] = secret.strip()
                return out

    raise SystemExit(f"no HUB_CREDENTIALS in {path}")


def call(url, method, path, secret_for=None, secret=None, body=None, timeout=10):
    """Return (status, parsed_body_or_None). Never raises for an HTTP status."""
    data = None
    headers = {}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if secret_for is not None:
        token = base64.b64encode(
            f"{secret_for}:{secret}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    request = urllib.request.Request(
        url + path, data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None


def main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv[1:])

    creds = read_credentials(args.env_file)
    url = args.url.rstrip("/")
    failures = []

    def check(label, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print(f"hub        : {url}")
    print(f"components : {len(creds)} ({', '.join(sorted(creds))})")
    print()

    print("--- anonymous callers are refused -------------------------------")
    for method, path in PROTECTED:
        status, _ = call(url, method, path, body={} if method == "POST" else None)
        check(f"{method:4} {path:34} 401", status == 401, f"got {status}")

    print()
    print("--- documentation routes are gone -------------------------------")
    for path in GONE:
        status, _ = call(url, "GET", path)
        check(f"GET  {path:34} 404", status == 404, f"got {status}")

    print()
    print("--- each component authenticates as itself ----------------------")
    for name in sorted(creds):
        status, body = call(url, "GET", "/control/status", name, creds[name])
        who = (body or {}).get("you")
        check(f"{name:12} /control/status 200, you={name}",
              status == 200 and who == name, f"got {status}, you={who}")

    print()
    print("--- the controller is mounted and authenticated -----------------")
    status, body = call(url, "GET", "/controller/status", "admin", creds["admin"])
    check("admin  /controller/status 200", status == 200, f"got {status}")
    if body:
        check("controller schema_version == 1",
              body.get("schema_version") == 1,
              f"got {body.get('schema_version')}")
        print(f"      tasks={body.get('tasks')} activations={body.get('activations')}")

    print()
    print("--- admin authority is still admin-only -------------------------")
    for name in sorted(n for n in creds if n not in ("admin", "operator")):
        status, _ = call(url, "POST", "/controller/tasks", name, creds[name], body={
            "task_id": "verify-should-not-exist", "title": "t", "objective": "o",
            "base_sha": "0" * 40,
        })
        check(f"{name:12} cannot create a task (403)", status == 403, f"got {status}")

        status, _ = call(url, "POST", "/control/pause", name, creds[name],
                         body={"reason": "verification probe"})
        check(f"{name:12} cannot pause (403)", status == 403, f"got {status}")

    print()
    print("--- a worker claim is authenticated and finds only its own ------")
    for name in sorted(n for n in creds if n not in ("admin", "operator")):
        status, body = call(url, "POST", "/controller/activations/claim",
                            name, creds[name])
        agent = (body or {}).get("agent")
        check(f"{name:12} claim 200, agent={name}",
              status == 200 and agent == name, f"got {status}, agent={agent}")

    print()
    print("--- global pause engages and releases ---------------------------")
    status, _ = call(url, "POST", "/control/pause", "admin", creds["admin"],
                     body={"reason": "deployment verification"})
    check("admin can pause (200)", status == 200, f"got {status}")

    status, body = call(url, "GET", "/control/status", "admin", creds["admin"])
    check("status reports paused", bool((body or {}).get("paused")),
          f"paused={(body or {}).get('paused')}")

    status, _ = call(url, "POST", "/control/resume", "admin", creds["admin"])
    check("admin can resume (200)", status == 200, f"got {status}")

    status, body = call(url, "GET", "/control/status", "admin", creds["admin"])
    check("status reports not paused, and is left that way",
          not (body or {}).get("paused"),
          f"paused={(body or {}).get('paused')}")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILED -- {', '.join(failures)}")
        return 1

    print("RESULT: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
