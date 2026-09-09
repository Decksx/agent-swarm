"""Scan the hub's SQLite database for credential-shaped strings.

Why this is a script rather than a result
-----------------------------------------

The hub database lives on Tower at
``/mnt/user/appdata/agent-swarm/data/chat.db`` (mounted into the container as
``/data/chat.db``). It is not reachable from the execution host, and it holds
the messages accumulated while the hub was unauthenticated and readable by
anyone on the LAN -- which is exactly why it is worth scanning and exactly why
nobody who lacks access can report on it. This script is the scan; the operator
runs it and reports the counts.

What it will and will not print
-------------------------------

**It never prints a matched value, and never prints message content.** For each
hit it reports the table, the column, which pattern matched, and the row's
primary key. That is enough to find the row and decide what to do about it, and
not enough to leak the secret into a terminal, a transcript, or this
repository's history -- the three places a scan for secrets most often puts one.

It opens the database read-only through a ``file:...?mode=ro`` URI, so it cannot
modify the hub's data even if the hub is running while it is used.

The ``hex48`` pattern deserves a note: the hub credentials are
``openssl rand -hex 24`` output, which has no distinguishing prefix and so is
invisible to the shape-based redaction in ``swarm_control.py``. Matching exactly
48 hex characters is the only way to see one. It is the pattern most likely to
produce a false positive, and a false positive here is cheap.

Usage
-----

::

    python scan_hub_db.py                       # /data/chat.db, inside the container
    python scan_hub_db.py /mnt/user/appdata/agent-swarm/data/chat.db

Exit status is 0 when nothing matched and 1 when anything did, so it can be
used as a check rather than read by eye.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "/data/chat.db"

# Named so a report can say which shape was found without quoting the value.
PATTERNS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    "google": re.compile(r"AIza[A-Za-z0-9_\-]{16,}"),
    "github": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "slack": re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
    "pem": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "basic_auth": re.compile(r"[Bb]asic\s+[A-Za-z0-9+/]{12,}={0,2}"),
    # The hub credential shape: openssl rand -hex 24. Bounded on both sides so
    # a 64-character sha256 digest does not match a 48-character window inside
    # it.
    "hex48": re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{48}(?![0-9a-fA-F])"),
}


def text_columns(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Return (table, column, primary_key_expression) for every text column.

    The schema is read from the database rather than hardcoded, so this keeps
    working if the hub's tables change and does not silently skip a column that
    was added after it was written. ``rowid`` is used as the key expression
    unless the table declares its own INTEGER PRIMARY KEY.
    """
    found: list[tuple[str, str, str]] = []

    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]

    for table in tables:
        columns = list(conn.execute(f'PRAGMA table_info("{table}")'))
        key = "rowid"
        for column in columns:
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            if column[5] and str(column[2]).upper() == "INTEGER":
                key = column[1]
                break

        for column in columns:
            name, declared = column[1], str(column[2]).upper()
            # Scan anything that can hold text. SQLite is dynamically typed, so
            # a column declared BLOB or with no type at all can still contain a
            # string; only the numeric declarations are safe to skip.
            if declared in {"INTEGER", "REAL", "NUMERIC"}:
                continue
            found.append((table, name, key))

    return found


def scan(db_path: str) -> int:
    """Scan and print a report. Returns the number of matching cells."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"

    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        print(f"cannot open {db_path} read-only: {exc}")
        return -1

    conn.text_factory = str
    hits = 0
    rows_scanned = 0

    print(f"database : {db_path}")

    targets = text_columns(conn)
    print(f"columns  : {len(targets)} text-capable columns across "
          f"{len({t for t, _, _ in targets})} tables")
    print()

    for table, column, key in targets:
        query = f'SELECT "{key}", "{column}" FROM "{table}"'
        for row_key, value in conn.execute(query):
            rows_scanned += 1
            if not isinstance(value, str):
                continue
            for pattern_name, pattern in PATTERNS.items():
                count = len(pattern.findall(value))
                if count:
                    hits += 1
                    # Deliberately no value, no excerpt, no character counts
                    # around the match -- only where to look.
                    print(
                        f"MATCH  table={table} column={column} "
                        f"{key}={row_key} pattern={pattern_name} "
                        f"occurrences={count}"
                    )

    conn.close()

    print()
    print(f"cells scanned : {rows_scanned}")
    print(f"matches       : {hits}")
    print("RESULT: clean" if hits == 0 else "RESULT: review the rows listed above")

    return hits


def main(argv: list[str]) -> int:
    db_path = argv[1] if len(argv) > 1 else DEFAULT_DB
    hits = scan(db_path)

    if hits < 0:
        return 2

    return 0 if hits == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
