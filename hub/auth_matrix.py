"""Prove each hub credential authenticates exactly one identity.

The property being tested
------------------------

``hub.authenticate()`` establishes identity by taking the component name from
the Basic *username*, looking that name up in ``CREDENTIALS``, and comparing the
Basic *password* against the value it finds. The name is therefore chosen by the
caller and only the secret is checked.

That is sound exactly as long as no two components share a secret. If they do,
identity separation collapses without anything looking wrong: a holder of a
shared secret authenticates as any component that shares it simply by typing a
different username, and every downstream guarantee built on the server deriving
``sender`` -- who posted a message, who may pause the swarm -- becomes a
statement about which name the caller felt like using.

Nothing in the hub can detect this at runtime, because each individual request
is perfectly valid. It has to be checked from outside, by trying every
credential against every identity.

What this reports
-----------------

A matrix of HTTP status codes, one row per credential owner, one column per
username tried, against a read-only endpoint on the live hub. It prints
**component names and status codes only** -- never a secret, never a hash of
one, never a length, and never anything else derived from the value. A length
alone narrows a search; a hash is offline-crackable. Neither belongs in a
terminal or a transcript.

The expected result is the identity matrix: 200 on the diagonal, 401 everywhere
else. Any off-diagonal 200 names two components that share a secret and is a
containment failure, not a warning.

Note that the matrix necessarily reveals *which* components share a credential.
That is the finding, and it is identity information rather than secret material.

Usage
-----

On the host holding the credentials, against the running hub::

    python3 auth_matrix.py --env-file /mnt/user/appdata/agent-swarm/hub.env
    python3 auth_matrix.py --env-file ... --url http://127.0.0.1:8050

If ``--env-file`` is omitted, ``HUB_CREDENTIALS`` is read from the environment.

Exit status is 0 when the matrix is exactly diagonal, 1 when it is not, and 2
when the check could not be completed -- an unreachable hub or an unreadable
credential set is never reported as a pass.

Every non-diagonal probe is a deliberate failed authentication and will appear
in the hub's access log as a 401. That is expected: n*(n-1) of them for n
components, all from loopback, all within a second or two.
"""

from __future__ import annotations

import argparse
import base64
import sys
import urllib.error
import urllib.request
from typing import Dict

# Read-only, and authenticated by any component rather than admin-only, so a
# non-admin credential that authenticates is still visibly a 200 rather than
# being masked as a 403. Using an admin-only route here would make every
# worker row look like a failure for the wrong reason.
PROBE_PATH = "/control/status"

DEFAULT_URL = "http://127.0.0.1:8050"


def parse_credentials(raw: str) -> Dict[str, str]:
    """Parse ``name:secret,name:secret`` exactly as the hub itself does."""
    credentials: Dict[str, str] = {}

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        name, separator, secret = entry.partition(":")
        name = name.strip().lower()
        secret = secret.strip()

        if not separator or not name or not secret:
            raise ValueError("malformed HUB_CREDENTIALS entry")

        credentials[name] = secret

    if not credentials:
        raise ValueError("HUB_CREDENTIALS parsed to no usable entries")

    return credentials


def read_env_file(path: str) -> str:
    """Return the HUB_CREDENTIALS value from a docker --env-file style file.

    The file is opened, the one variable is taken, and nothing else about it is
    retained or reported. Other variables in the file are not this tool's
    business.
    """
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            name, separator, value = line.partition("=")
            if separator and name.strip() == "HUB_CREDENTIALS":
                value = value.strip()
                # Tolerate a quoted value; docker --env-file does not strip
                # quotes, but a human editing the file often adds them.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                return value

    raise ValueError(f"no HUB_CREDENTIALS assignment in {path}")


def probe(url: str, username: str, secret: str, timeout: float) -> int:
    """Return the HTTP status for one (username, secret) pair, or 0 on error."""
    token = base64.b64encode(f"{username}:{secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url + PROBE_PATH,
        headers={"Authorization": f"Basic {token}"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # A 401 is the expected result for most cells here, not an error.
        return exc.code
    except Exception:
        return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv[1:])

    try:
        if args.env_file:
            raw = read_env_file(args.env_file)
        else:
            import os

            raw = os.environ.get("HUB_CREDENTIALS", "")
            if not raw:
                raise ValueError("HUB_CREDENTIALS is not set and no --env-file given")

        credentials = parse_credentials(raw)
    except (OSError, ValueError) as exc:
        # Deliberately does not echo the offending text: a malformed
        # credentials string still contains credentials.
        print(f"cannot read credentials: {type(exc).__name__}")
        return 2

    names = sorted(credentials)
    url = args.url.rstrip("/")

    print(f"hub        : {url}{PROBE_PATH}")
    print(f"components : {len(names)} ({', '.join(names)})")
    print()

    # Reachability first, so an unreachable hub is not silently reported as a
    # wall of 401s that happens to look diagonal-ish.
    if probe(url, names[0], credentials[names[0]], args.timeout) == 0:
        print(f"cannot reach {url}{PROBE_PATH}")
        return 2

    # Column width follows the longest component name, so the header and the
    # status cells stay aligned for any set of names rather than only short
    # ones -- this output gets pasted into reports.
    width = max(len(n) for n in names)
    column = max(5, width)
    header = " " * (width + 2) + "  ".join(n.rjust(column) for n in names)
    print("rows = credential owner, columns = username presented")
    print()
    print(header)

    off_diagonal: list[tuple[str, str]] = []
    diagonal_failures: list[str] = []

    for owner in names:
        secret = credentials[owner]
        cells = []

        for username in names:
            status = probe(url, username, secret, args.timeout)
            cells.append(str(status).rjust(column))

            if username == owner and status != 200:
                diagonal_failures.append(owner)
            elif username != owner and status == 200:
                off_diagonal.append((owner, username))

        print(owner.ljust(width + 2) + "  ".join(cells))

    print()

    if diagonal_failures:
        for owner in diagonal_failures:
            print(f"FAIL  {owner}'s own credential did not authenticate as {owner}")

    for owner, username in off_diagonal:
        print(f"FAIL  {owner}'s credential also authenticates as {username}")

    if off_diagonal or diagonal_failures:
        print()
        print("RESULT: NOT ISOLATED - at least one credential is not bound to one identity")
        return 1

    print("RESULT: isolated - each credential authenticates exactly one identity")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
