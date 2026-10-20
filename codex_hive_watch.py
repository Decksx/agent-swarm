"""Durable inbox for a finite native same-chat Codex watcher pilot (#113).

No scheduling, model launch, merge or deployment occurs here. A poll returns
at most one claimed, head-bound handoff for the existing assistant to handle.
Runtime state is separate from the production relay and belongs outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlparse
import uuid

REPOS = {"swarm": "Decksx/agent-swarm", "comic": "Decksx/cbz-automation-suite"}
CHAT_PATH = Path(r"C:\swarm-prod\agent-swarm\lead_chat.py")
HISTORY = Path(r"C:\Users\david\.codex\thread_history_1.sqlite")
SHA = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])")
ENVELOPE = re.compile(r"^\s*(HANDOFF|REVIEW|QUESTION)\s+@codex-lead\s*:", re.I)
NOTICE = re.compile(r"RELAY DELIVER #(\d+) → @codex-lead attempt=([A-Za-z0-9_-]{20,80}) \(live\)")
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE runs (turn TEXT PRIMARY KEY, started REAL NOT NULL, finished REAL, result TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY, disposition TEXT NOT NULL, work_key TEXT, sent_at TEXT);
CREATE TABLE work (key TEXT PRIMARY KEY, repo TEXT NOT NULL, pr INTEGER NOT NULL,
 head TEXT NOT NULL, kind TEXT NOT NULL, source INTEGER NOT NULL, content TEXT NOT NULL,
 state TEXT NOT NULL, owner_turn TEXT, report TEXT);
CREATE UNIQUE INDEX one_active ON work(state) WHERE state = 'active';
CREATE TABLE acks (source INTEGER NOT NULL, token TEXT NOT NULL, notice INTEGER NOT NULL,
 state TEXT NOT NULL, receipt INTEGER, PRIMARY KEY(source, token));
"""


class WatchError(Exception):
    """Visible refusal; never a reason to reset a claim or widen access."""


def initialize(root: Path, *, thread: str, baseline: int, expires: float,
               control: Path, chat_sha256: str, max_turns: int = 12, now=time.time) -> None:
    """Create one fresh pilot, refusing reuse, an unbounded window or budget."""
    if (not root.is_absolute() or not control.is_absolute()
            or str(uuid.UUID(thread)) != thread
            or type(baseline) is not int or baseline < 0
            or type(max_turns) is not int or not 1 <= max_turns <= 12
            or not isinstance(chat_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", chat_sha256)
            or not 0 < expires - now() <= 3600):
        raise WatchError("absolute paths, exact thread, baseline and <=12 turns/1 hour required")
    resolved = root.resolve()
    codex_data = (Path.home() / ".codex").resolve()
    if (resolved == codex_data or codex_data in resolved.parents
            or any((p / ".git").exists() for p in (resolved, *resolved.parents))):
        raise WatchError("runtime state must be outside Git and Codex data")
    root.mkdir(exist_ok=False)
    config = dict(schema_version=2, thread=thread, baseline=baseline, chat_sha256=chat_sha256,
                  created=now(), expires=expires, control=str(control), max_turns=max_turns)
    with sqlite3.connect(root / "watch.sqlite") as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO meta VALUES (?, ?)",
                       [("config", json.dumps(config)), ("cursor", str(baseline))])


def identity(history: Path = HISTORY, environ=None) -> tuple[str, str]:
    """Read only this environment thread's unique current turn metadata.

    No message bodies or state edits. The reviewed schema has no token-usage
    fields; metrics must report that absence instead of estimating token cost.
    Schema drift, missing metadata or overlap refuses work, with no fallback.
    """
    thread = (os.environ if environ is None else environ).get("CODEX_THREAD_ID", "")
    if str(uuid.UUID(thread)) != thread:
        raise WatchError("actual environment thread unavailable")
    with sqlite3.connect(history.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT turn_id FROM thread_turns WHERE thread_id=? "
                          "AND status='inProgress'", (thread,)).fetchall()
    if len(rows) != 1 or str(uuid.UUID(rows[0][0])) != rows[0][0]:
        raise WatchError("unique actual in-progress turn unavailable")
    return thread, rows[0][0]


def github_head(repo: str, number: int) -> str:
    """Resolve only allowlisted repositories, without a shell or mutations."""
    if repo not in REPOS.values() or type(number) is not int or number <= 0:
        raise WatchError("repository outside pilot scope")
    result = subprocess.run(["gh", "pr", "view", str(number), "--repo", repo,
                             "--json", "headRefOid"], check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    head = json.loads(result.stdout).get("headRefOid")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise WatchError("invalid GitHub head")
    return head


def reference(content: str) -> tuple[str, int] | None:
    """Accept an explicit allowed PR URL or a named swarm/comic #number.

    Ambiguous or unspecified project references need clarification, not an
    inferred target. This finite pilot does not execute arbitrary admin text.
    """
    found = set()
    for repo in REPOS.values():
        for match in re.finditer(r"https://github\.com/" + re.escape(repo)
                                 + r"/pull/([1-9][0-9]*)(?=$|[\s/#?)>,])", content, re.I):
            found.add((repo, int(match[1])))
    for label, repo in REPOS.items():
        for match in re.finditer(r"\b" + label + r"\s+(?:PR\s+)?#([1-9][0-9]*)\b", content, re.I):
            found.add((repo, int(match[1])))
    return next(iter(found)) if len(found) == 1 else None


class Watcher:
    """One pilot's durable classification, claim and acknowledgement ledger."""

    def __init__(self, root: Path, *, api, resolve=github_head, actual, now=time.time):
        self.root, self.api, self.resolve, self.actual, self.now = root, api, resolve, actual, now
        self.db = sqlite3.connect((root / "watch.sqlite").resolve().as_uri() + "?mode=rw",
                                  uri=True, isolation_level=None, timeout=0)
        self.db.row_factory = sqlite3.Row
        self.config = json.loads(self.meta("config"))
        if self.config.get("schema_version") != 2 or actual[0] != self.config["thread"]:
            self.close()
            raise WatchError("pilot schema or actual thread mismatch")
        if (type(self.config.get("max_turns")) is not int
                or not 1 <= self.config["max_turns"] <= 12
                or not 0 < self.config["expires"] - self.config["created"] <= 3600
                or not isinstance(self.config.get("chat_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.config["chat_sha256"])
                or not Path(self.config["control"]).is_absolute()):
            self.close()
            raise WatchError("invalid pilot bounds or control path")
        if str(uuid.UUID(actual[1])) != actual[1]:
            self.close()
            raise WatchError("actual turn unavailable")

    def close(self):
        """Release this helper's state connection, never the app writer lock."""
        self.db.close()

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def paused(self):
        """Respect both local pilot/shared stop files and the hub switch."""
        if (self.root / "PAUSED").exists() or (Path(self.config["control"]) / "PAUSED").exists():
            return True
        value = self.api.paused()
        if type(value) is not bool:
            raise WatchError("unverifiable hub pause state")
        return value

    def classify(self, row):
        """Persist a classification and any work/ACK intent before cursor advance."""
        mid, text, sender = row["id"], row.get("content"), row.get("sender")
        disposition, key = "ignored", None
        if not isinstance(text, str):
            raise WatchError("malformed message content")
        match = NOTICE.fullmatch(text) if sender == "relay" else None
        if match:
            source, token = int(match[1]), match[2]
            known = self.db.execute("SELECT work_key FROM messages WHERE id=?", (source,)).fetchone()
            if known and known[0]:
                self.db.execute("INSERT OR IGNORE INTO acks VALUES (?, ?, ?, 'pending', NULL)",
                                (source, token, mid))
                disposition = "relay-notice"
            else:
                disposition = "surface:unknown-relay-source"
        elif sender == "claude-lead" and ENVELOPE.match(text):
            ref = reference(text)
            observed = {s.lower() for s in SHA.findall(text)}
            if ref is None or len(observed) != 1:
                disposition = "surface:explicit-project-and-one-full-head-required"
            else:
                repo, number = ref
                head = self.resolve(repo, number)
                if head not in observed:
                    disposition = "surface:head-moved"
                else:
                    kind = ENVELOPE.match(text)[1].lower()
                    key = hashlib.sha256(f"{repo}/{number}/{head}/{kind}".encode()).hexdigest()
                    self.db.execute("INSERT OR IGNORE INTO work VALUES (?, ?, ?, ?, ?, ?, ?, "
                                    "'pending', NULL, NULL)",
                                    (key, repo, number, head, kind, mid, text))
                    disposition = "work"
        elif sender == "admin" and self.api.mentions(row):
            disposition = "surface:operator-message"
        sent_at = row.get("timestamp_utc")
        self.db.execute("INSERT INTO messages VALUES (?, ?, ?, ?)",
                        (mid, disposition, key, sent_at if isinstance(sent_at, str) else None))
        return disposition

    def acknowledge(self):
        """ACK each known relay token once; retain ambiguous sends, never retry."""
        for row in self.db.execute("SELECT * FROM acks WHERE state='pending'").fetchall():
            if self.now() >= self.config["expires"] or self.paused():
                return
            content = f"ACK #{row['source']} {row['token']}"
            found = self.api.find(content, self.config["baseline"])
            if not isinstance(found, list) or any(type(i) is not int or i <= 0 for i in found):
                raise WatchError("invalid ACK find response")
            if found:
                receipt = found[0]
            else:
                if self.now() >= self.config["expires"] or self.paused():
                    return
                # All fallible pre-send checks precede this durable marker.
                # From here a crash is ambiguous, so no automatic resend.
                self.db.execute("UPDATE acks SET state='posting' WHERE source=? AND token=?",
                                (row["source"], row["token"]))
                reply = self.api.post(content)
                receipt = (reply.message_id if reply.state == "confirmed"
                           and type(reply.message_id) is int and reply.message_id > 0 else None)
            self.db.execute("UPDATE acks SET state=?, receipt=? WHERE source=? AND token=?",
                            ("confirmed" if receipt else "uncertain", receipt,
                             row["source"], row["token"]))
            if not receipt:
                raise WatchError("unconfirmed relay ACK; retained, no resend")

    def poll(self):
        """One cheap check, at most one active handoff, no autonomous task execution.

        A persisted polling marker or unfinished claim after a crash blocks
        takeover. This finite pilot stops for reviewed reconciliation instead
        of guessing whether the prior assistant acted.
        """
        turn, started = self.actual[1], self.now()
        if started >= self.config["expires"]:
            return {"state": "expired"}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM runs WHERE turn=?", (turn,)).fetchone():
                result = {"state": "already-polled"}
            elif self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] >= self.config["max_turns"]:
                result = {"state": "budget-exhausted"}
            elif self.meta("polling") or self.db.execute("SELECT 1 FROM work WHERE state='active'").fetchone():
                result = {"state": "attention", "reason": "unfinished-poll-or-claim"}
            elif self.db.execute("SELECT 1 FROM acks WHERE state IN ('posting','uncertain')").fetchone():
                result = {"state": "attention", "reason": "uncertain-ack"}
            else:
                self.db.execute("INSERT INTO runs VALUES (?, ?, NULL, NULL)", (turn, started))
                self.set_meta("polling", turn)
                result = None
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        if result is not None:
            return result
        try:
            result = self._poll(turn)
        except Exception as exc:
            result = {"state": "attention", "reason": str(exc) if isinstance(exc, WatchError)
                      else type(exc).__name__}
        finally:
            # A process crash never executes this: the durable marker then
            # intentionally prevents another scheduled turn taking over.
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] >= self.config["max_turns"]:
                result["stop_after_turn"] = True
            self.db.execute("UPDATE runs SET finished=?, result=? WHERE turn=?",
                            (self.now(), json.dumps(result), turn))
            self.db.execute("DELETE FROM meta WHERE key='polling' AND value=?", (turn,))
            self.db.commit()
        return result

    def _poll(self, turn):
        if self.paused():
            return {"state": "paused"}
        cursor = int(self.meta("cursor"))
        rows = self.api.read(cursor)
        if not isinstance(rows, list) or any(not isinstance(r, dict) or type(r.get("id")) is not int
                                             or r["id"] <= cursor for r in rows):
            raise WatchError("invalid message batch")
        rows = sorted(rows, key=lambda r: r["id"])
        if len({r["id"] for r in rows}) != len(rows):
            raise WatchError("duplicate message id")
        surfaces = []
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in rows[:50]:
                if self.now() >= self.config["expires"]:
                    break
                outcome = self.classify(row)
                if outcome.startswith("surface:"):
                    surfaces.append({"source_id": row["id"], "reason": outcome,
                                       "content": row["content"]})
                self.set_meta("cursor", row["id"])
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        self.acknowledge()
        if self.now() >= self.config["expires"]:
            return {"state": "expired"}
        if self.paused():
            return {"state": "paused"}
        if self.db.execute("SELECT 1 FROM acks WHERE state!='confirmed'").fetchone():
            return {"state": "attention", "reason": "relay-ack-incomplete"}
        task = self.db.execute("SELECT * FROM work WHERE state='pending' ORDER BY source LIMIT 1").fetchone()
        if task is None:
            return {"state": "surface", "messages": surfaces} if surfaces else {"state": "idle"}
        if self.resolve(task["repo"], task["pr"]) != task["head"]:
            self.db.execute("UPDATE work SET state='stale' WHERE key=?", (task["key"],))
            return {"state": "surface", "messages": surfaces + [
                {"source_id": task["source"], "reason": "surface:head-moved", "content": task["content"]}]}
        if self.now() >= self.config["expires"] or self.paused():
            return {"state": "paused-or-expired"}
        self.db.execute("UPDATE work SET state='active', owner_turn=? WHERE key=?", (turn, task["key"]))
        sent = self.db.execute("SELECT sent_at FROM messages WHERE id=?", (task["source"],)).fetchone()
        packet = {"state": "work", "claim": task["key"], "source_id": task["source"],
                "repo": task["repo"], "pr": task["pr"], "head": task["head"],
                "kind": task["kind"], "content": task["content"], "turn": turn,
                "source_timestamp_utc": sent[0], "claimed_at": self.now()}
        if surfaces:
            packet["notices"] = surfaces
        return packet

    def finish(self, claim: str, report: str, *, blocked=False):
        """Record this turn's actual GitHub report; never manufacture a verdict."""
        task = self.db.execute("SELECT * FROM work WHERE key=? AND state='active' AND owner_turn=?",
                               (claim, self.actual[1])).fetchone()
        if task is None:
            raise WatchError("no active claim owned by this actual turn")
        parsed = urlparse(report)
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or parsed.query
                or parsed.path != f"/{task['repo']}/pull/{task['pr']}"
                or not re.fullmatch(r"issuecomment-[1-9][0-9]*", parsed.fragment)):
            raise WatchError("exact PR comment URL required")
        self.db.execute("UPDATE work SET state=?, report=? WHERE key=?",
                        ("blocked" if blocked else "completed", report, claim))
        return {"state": "recorded", "claim": claim, "report": report}

    def guard(self, claim: str):
        """Recheck the owning turn's bounds before an engineering side effect.

        This is a point-in-time check, not a lease or an atomic remote action.
        GitHub merge pins, CI and independent review remain necessary.
        """
        task = self.db.execute("SELECT * FROM work WHERE key=? AND state='active' AND owner_turn=?",
                               (claim, self.actual[1])).fetchone()
        if task is None:
            raise WatchError("no active claim owned by this actual turn")
        if self.now() >= self.config["expires"]:
            return {"state": "expired"}
        if self.paused():
            return {"state": "paused"}
        if self.resolve(task["repo"], task["pr"]) != task["head"]:
            return {"state": "attention", "reason": "head-moved", "source_id": task["source"]}
        if self.now() >= self.config["expires"] or self.paused():
            return {"state": "paused-or-expired"}
        return {"state": "ready", "claim": claim, "head": task["head"]}

    def metrics(self, history=HISTORY):
        """Join only our recorded turn IDs to terminal metadata, without bodies.

        Token usage is unavailable in the reviewed thread_turns schema. Do
        not treat helper duration as whole-turn duration or invent token cost.
        """
        output = []
        with sqlite3.connect(history.resolve().as_uri() + "?mode=ro", uri=True) as db:
            for run in self.db.execute("SELECT * FROM runs ORDER BY started"):
                meta = db.execute("SELECT status, started_at, completed_at, duration_ms "
                                  "FROM thread_turns WHERE thread_id=? AND turn_id=?",
                                  (self.config["thread"], run["turn"])).fetchone()
                output.append({"turn": run["turn"], "helper_seconds":
                               run["finished"] - run["started"] if run["finished"] else None,
                               "result": json.loads(run["result"]) if run["result"] else None,
                               "terminal_metadata": list(meta) if meta else None,
                               "token_usage": None,
                               "token_usage_reason": "not exposed by reviewed metadata schema"})
        return output


def production_api(expected_sha256):
    """Use the existing non-admin lead helper; never read/print a credential."""
    raw = CHAT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise WatchError("production chat helper bytes changed; review before using")
    spec = importlib.util.spec_from_file_location("_watch_lead_chat", CHAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    # Execute precisely the verified bytes, not a second mutable file read.
    exec(compile(raw, str(CHAT_PATH), "exec"), mod.__dict__)

    class API:
        def paused(self):
            headers = mod._auth("codex-lead", mod.secret_for("codex-lead"))
            reply = mod.urllib_transport("GET", mod.HUB_URL + "/control/status", headers, None)
            if reply.status != 200 or not isinstance(reply.body, dict) or type(reply.body.get("paused")) is not bool:
                raise WatchError("hub pause unavailable")
            return reply.body["paused"]

        def read(self, cursor):
            return mod.read("codex-lead", since_id=cursor)

        def mentions(self, row):
            return mod.mentions(row, "codex-lead")

        def find(self, content, baseline):
            return mod.find("codex-lead", content, since_id=baseline)

        def post(self, content):
            return mod.post("codex-lead", content, target="@room")

    return API()


def main(argv=None):
    """Explicit init/poll/finish/metrics; this CLI never creates a schedule."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--thread", required=True)
    init.add_argument("--baseline", type=int, required=True)
    init.add_argument("--expires", required=True)
    init.add_argument("--control", required=True, type=Path)
    init.add_argument("--chat-sha256", required=True)
    sub.add_parser("poll")
    sub.add_parser("metrics")
    guard = sub.add_parser("guard")
    guard.add_argument("--claim", required=True)
    finish = sub.add_parser("finish")
    finish.add_argument("--claim", required=True)
    finish.add_argument("--report", required=True)
    finish.add_argument("--blocked", action="store_true")
    args = parser.parse_args(argv)
    watch = None
    try:
        actual = identity()
        if args.command == "init":
            if args.thread != actual[0] or not args.expires.endswith("Z"):
                raise WatchError("actual thread and UTC-Z expiry required")
            expires = datetime.fromisoformat(args.expires.replace("Z", "+00:00")).timestamp()
            initialize(args.root, thread=args.thread, baseline=args.baseline,
                       expires=expires, control=args.control, chat_sha256=args.chat_sha256)
            result = {"state": "initialized"}
        else:
            watch = Watcher(args.root, api=None, actual=actual)
            if args.command in ("poll", "guard"):
                watch.api = production_api(watch.config["chat_sha256"])
            if args.command == "poll":
                result = watch.poll()
            elif args.command == "metrics":
                result = {"state": "metrics", "runs": watch.metrics()}
            elif args.command == "guard":
                result = watch.guard(args.claim)
            else:
                result = watch.finish(args.claim, args.report, blocked=args.blocked)
    except Exception as exc:
        result = {"state": "attention", "reason": str(exc) if isinstance(exc, WatchError)
                  else type(exc).__name__}
    finally:
        if watch is not None:
            watch.close()
    print(json.dumps(result))
    return 1 if result["state"] == "attention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
