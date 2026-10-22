"""One bounded Codex CLOSED-path bridge proof (#113).

The plan is docs/design/113-codex-closed-proof-plan.md. `prepare` records a
fresh proof id, the two literal probes and the facts the run must still find;
`run` is one-use: it waits for the app to be fully closed, enables codex-lead
through the supported CLI, watches only the two named probe sources, and on
every way out disables codex-lead and stops only the proof's own processes,
identified by pid and creation time. It creates no schedule and never writes
the relay database itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
LEAD = "codex-lead"
# The successor interactive Codex lead (hive #1851, #1856). The retired thread
# 01a14068 is kept as evidence and is never a target again.
THREAD = "01a1609d-cd64-7bd1-9880-2b5b488509d4"
WORKSPACE = r"C:\git\agent-swarm"
STATE_NAME = "codex_closed_proof.01a1609d.json"
# Proof 53e110d6 on the retired thread was cancelled before enable and its
# claim kept (#133). It is reconciled once, append-only, and its files must
# stay byte-for-byte as they were; nothing about it is reset or reused.
OLD_PROOF = "53e110d6"
OLD_OWNER = (47792, "134370937802738350")      # pid, creation (FILETIME ticks)
OLD_FILES = {
    "codex_closed_proof.json": "98f4102198abc8bad6a23534ed8787783ca66ec4851008733485fccdc193ab93",
    "codex_closed_proof.53e110d6.cancelled.txt": "92650ee384da5405c5052bb203d8cbf32aa223b3df6ebc83949d7d07d7f2030a",
    "codex_closed_proof.53e110d6.log": "df48b98f75f9dce3c021895129a6ae9b3fca1279f364e897bffc68e8e71a25a5",
}
RECONCILED = "codex_closed_proof.53e110d6.reconciled.json"
ENABLE_WINDOW = 30 * 60   # prepare -> the app must be closed and enabled by then
PROOF_WINDOW = 30 * 60    # enable -> everything finished
ACK_WITHIN = 10 * 60      # a probe's delivery -> its ACK
RUN_LIMIT = 15 * 60       # a launched proof run -> stopped by this script
SETTLE = 120              # after cleanup, for the relay to record the exit
TERMINAL = ("delivered", "failed", "uncertain", "cancelled")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probes(proof_id: str) -> tuple[str, str]:
    return (
        f"@codex-lead BRIDGE-PROOF {proof_id}: bounded relay test. Post the ACK line for "
        "this attempt, then exactly one status line giving your thread id and workspace, "
        "then stop. No engineering work, schedules or handoffs.",
        f"HANDOFF @codex-lead: BRIDGE-PROOF-2 {proof_id}: second bounded relay test. "
        "Post the ACK line for this attempt only, then stop.",
    )


def save(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


class Env:
    """Every side effect, so the tests can replace them."""

    def __init__(self, db: Path):
        from lead_relay_backends import ProcessApi
        from lead_relay_codex import CodexBackend, desktop_app_server
        self.db_path = db
        self.backend = CodexBackend()
        self.processes = ProcessApi()
        self.app_server = desktop_app_server
        self.config = Path.home() / ".codex" / "config.toml"

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def say(self, line: str) -> None:
        print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {line}", flush=True)

    def relay_cli(self, *args: str) -> tuple[int, str]:
        out = subprocess.run([sys.executable, str(HERE / "lead_relay.py"), "--db", str(self.db_path),
                              *args], capture_output=True, text=True, timeout=60)
        return out.returncode, (out.stdout + out.stderr).strip()

    def post(self, text: str) -> str:
        import lead_chat
        return str(lead_chat.post("claude-lead", text))

    def statuses(self, since_id: int) -> list:
        import lead_chat
        return [m for m in lead_chat.read("claude-lead", since_id=since_id) if m["sender"] == LEAD]

    def image(self, pid: int) -> Optional[str]:
        """The executable behind a live pid (QueryFullProcessImageNameW)."""
        if os.name != "nt":
            return None
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            buf, size = ctypes.create_unicode_buffer(32768), ctypes.c_ulong(32768)
            return buf.value if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else None
        finally:
            k32.CloseHandle(handle)

    def new_session_files(self, since: float) -> list:
        root = self.backend.home / "sessions"
        return sorted(str(p) for p in root.rglob("*.jsonl*")
                      if p.stat().st_mtime >= since and THREAD not in p.name.lower())

    def rows(self, sql: str, *params) -> list:
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()


def _same(a: Optional[str], b: Optional[str]) -> bool:
    norm = lambda p: os.path.normcase(os.path.normpath(p[4:] if p.startswith("\\\\?\\") else p))  # noqa: E731
    return bool(a) and bool(b) and norm(a) == norm(b)


def preflight(env, state: dict, *, enabled: int, closed: bool) -> list:
    """What is wrong with starting (or continuing to) enable; empty means go."""
    from lead_relay_backends import Session
    from lead_relay_codex import CLOSED
    problems = []
    rows = env.rows("SELECT * FROM sessions WHERE recipient = ?", LEAD)
    if len(rows) != 1:
        return [f"{LEAD} is not registered"]
    s = rows[0]
    if (s["backend"], s["session_id"].lower()) != ("codex", THREAD) or not _same(s["workspace"], WORKSPACE):
        problems.append(f"binding is {s['backend']} {s['session_id']} {s['workspace']}")
    if not _same(s["cli"], state["cli"]):
        problems.append(f"registered cli is {s['cli']}")
    if s["enabled"] != enabled:
        problems.append(f"enabled is {s['enabled']}, expected {enabled}")
    if not Path(state["cli"]).is_file() or sha256(Path(state["cli"])) != state["cli_sha256"]:
        problems.append("cli file missing or its sha256 changed")
    if sha256(env.config) != state["config_sha256"]:
        problems.append("config.toml sha256 changed")
    session = Session(LEAD, "codex", s["session_id"], s["workspace"], s["cli"], bool(s["enabled"]))
    try:
        command = env.backend.command(session)
        if not _same(command[0], state["cli"]):
            problems.append(f"backend would launch {command[0]}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"no launch command: {exc}")
    busy = env.rows("SELECT message_id, state FROM deliveries WHERE recipient = ? AND state NOT IN "
                    "(?, ?, ?, ?)", LEAD, *TERMINAL)
    if busy:
        problems.append(f"{LEAD} has non-terminal deliveries {busy}")
    if env.rows("SELECT 1 FROM reservations WHERE recipient = ?", LEAD):
        problems.append(f"{LEAD} has a reservation")
    if closed:
        if env.app_server():
            problems.append("the desktop app-server is running")
        own = env.backend.ownership(session)
        if own != CLOSED:
            problems.append(f"ownership is {own}")
    return problems


def claim(state_path: Path) -> Optional[int]:
    """This driver's own OS lock (not the relay's), held for a whole prepare or
    run, so a second driver can never read the same state as unclaimed. None
    if another live driver holds it; the kernel drops it if this one dies."""
    from lead_relay_backends import AlreadyRunning, acquire_lock
    try:
        return acquire_lock(state_path.with_name(state_path.name + ".lock"))
    except AlreadyRunning:
        return None


def result_path(state_path: Path, proof_id: str) -> Path:
    return state_path.with_name(f"codex_closed_proof.{proof_id}.result.json")


def old_proof_problems(env, control: Path) -> list:
    """Why the retired proof is not safely closed: files changed, owner alive."""
    problems = []
    for name, digest in OLD_FILES.items():
        path = control / name
        if not path.is_file() or sha256(path) != digest:
            problems.append(f"{name} is missing or changed")
    if env.processes.is_same(*OLD_OWNER):
        problems.append(f"the old driver pid {OLD_OWNER[0]} is still running")
    return problems


def reconcile(env, control: Path) -> int:
    """Record, once and append-only, that proof 53e110d6 ended cancelled before
    enable with no launch and no result. Its own files are left untouched."""
    old_state = control / "codex_closed_proof.json"
    lock = claim(old_state)          # the old driver's own lock: no live owner
    if lock is None:
        env.say("REFUSED: a driver holds the old proof's lock")
        return 1
    try:
        receipt = control / RECONCILED
        if receipt.exists():
            env.say(f"REFUSED: {RECONCILED} already exists")
            return 1
        problems = old_proof_problems(env, control)
        old = json.loads(old_state.read_text(encoding="utf-8")) if old_state.is_file() else {}
        if (old.get("proof_id"), old.get("status")) != (OLD_PROOF, "claimed"):
            problems.append(f"old state is {old.get('proof_id')} {old.get('status')}")
        if result_path(old_state, OLD_PROOF).exists():
            problems.append("the old proof has a result file")
        # Any launch that overlapped the old run, however early its row was
        # created or its process started (Codex, #135 at 9af2ed2).
        launched = env.rows("SELECT attempt_id FROM attempts WHERE recipient = ? AND launched_at "
                            "IS NOT NULL AND (ended_at IS NULL OR ended_at >= ?)",
                            LEAD, old.get("run_started", 0))
        if launched:
            problems.append(f"{LEAD} attempts launched since the old run started: {launched}")
        stored = env.rows("SELECT enabled FROM sessions WHERE recipient = ?", LEAD)
        if not stored or stored[0]["enabled"] != 0:
            problems.append(f"{LEAD} is not registered disabled")
        if env.rows("SELECT 1 FROM reservations WHERE recipient = ?", LEAD):
            problems.append(f"{LEAD} has a reservation")
        if problems:
            env.say("REFUSED: " + "; ".join(problems))
            return 1
        body = dict(proof_id=OLD_PROOF, verdict="cancelled before enable", launches=0, result=None,
                    reconciled_at=env.now(), owner=list(OLD_OWNER), files=OLD_FILES)
        try:
            fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # never overwrites
        except FileExistsError:
            env.say(f"REFUSED: {RECONCILED} appeared while reconciling")
            return 1
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(body, out, indent=1, sort_keys=True)
        env.say(f"reconciled {OLD_PROOF}: {body['verdict']}; old files unchanged")
        return 0
    finally:
        os.close(lock)


def prepare(env, state_path: Path, cli: str, cli_sha256: str, config_sha256: str) -> int:
    lock = claim(state_path)
    if lock is None:
        env.say("REFUSED: another proof driver is running")
        return 1
    try:
        control = state_path.parent
        receipt = control / RECONCILED
        problems = old_proof_problems(env, control)
        if not receipt.is_file():
            problems.append(f"proof {OLD_PROOF} is not reconciled ({RECONCILED} missing)")
        elif json.loads(receipt.read_text(encoding="utf-8")).get("files") != OLD_FILES:
            problems.append(f"{RECONCILED} does not match the retained files")
        if problems:
            env.say("REFUSED: " + "; ".join(problems))
            return 1
        if state_path.exists():
            old = json.loads(state_path.read_text(encoding="utf-8"))
            if old.get("status") == "claimed":
                # Its driver is gone (we hold the lock) but never finished:
                # that needs reconciling by hand, not a fresh proof on top.
                env.say(f"REFUSED: proof {old['proof_id']} was claimed and never finished; reconcile it first")
                return 1
            if old.get("status") == "prepared" and env.now() < old["enable_by"]:
                env.say(f"REFUSED: proof {old['proof_id']} is prepared and unused until its window ends")
                return 1
        proof_id = secrets.token_hex(4)
        cursor = int(env.rows("SELECT value FROM meta WHERE key = 'cursor'")[0]["value"])
        state = dict(proof_id=proof_id, prepared_at=env.now(), enable_by=env.now() + ENABLE_WINDOW,
                     cli=cli, cli_sha256=cli_sha256, config_sha256=config_sha256, baseline=cursor,
                     probe1=probes(proof_id)[0], probe2=probes(proof_id)[1], status="prepared")
        problems = preflight(env, state, enabled=0, closed=False)
        if problems:
            env.say("REFUSED: " + "; ".join(problems))
            return 1
        save(state_path, state)
        env.say(f"prepared proof {proof_id}; enable window ends in {ENABLE_WINDOW // 60} min")
        env.say(f"David posts, after ENABLED: {state['probe1']}")
        return 0
    finally:
        os.close(lock)


class Proof:
    def __init__(self, env, state: dict):
        self.env, self.s = env, state
        self.r = dict(proof_id=state["proof_id"], verdict=None, why=[], launches={}, probe2="not posted")
        self.sources: dict = {}     # message_id -> "probe1" | "probe2"

    def stop(self, verdict: str, why: str) -> str:
        # A later failure (say, disable not confirmed) outranks an earlier pass.
        if self.r["verdict"] in (None, "passed"):
            self.r["verdict"] = verdict
        self.r["why"].append(why)
        self.env.say(f"STOP {verdict}: {why}")
        return verdict

    def deliveries(self) -> list:
        return self.env.rows("SELECT message_id, sender, content, state, reason, received_at FROM "
                             "deliveries WHERE recipient = ? AND message_id > ? ORDER BY message_id",
                             LEAD, self.s["baseline"])

    def attempts(self) -> list:
        if not self.sources:
            return []
        marks = ",".join("?" * len(self.sources))
        return self.env.rows(f"SELECT * FROM attempts WHERE recipient = ? AND message_id IN ({marks})",
                             LEAD, *self.sources)

    def step(self) -> Optional[str]:
        """One look. A verdict ends the run; None means keep watching."""
        env, now = self.env, self.env.now()
        rows = self.deliveries()
        # probe2 must wait for the probe1 run (§7 item 6), so its ACK clock
        # starts only once that run has ended.
        p1 = [mid for mid, kind in self.sources.items() if kind == "probe1"]
        p1_ended = [a["ended_at"] for a in self.attempts() if p1 and a["message_id"] == p1[0]
                    and a["launched_at"]]
        for d in rows:
            if d["message_id"] not in self.sources:
                text = d["content"].strip()
                kind = ("probe1" if d["sender"] == "admin" and text == self.s["probe1"]
                        and "probe1" not in self.sources.values() else
                        "probe2" if d["sender"] == "claude-lead" and text == self.s["probe2"]
                        and "probe2" not in self.sources.values() else None)
                if kind is None:
                    return self.stop("failed", f"unexpected {LEAD} delivery #{d['message_id']} "
                                               f"from {d['sender']}")
                self.sources[d["message_id"]] = kind
                env.say(f"{kind} is #{d['message_id']}")
                if d["received_at"] < self.r["enable"]["at"]:
                    return self.stop("failed", f"{kind} #{d['message_id']} arrived before enable")
            if d["state"] in ("failed", "uncertain", "cancelled"):
                return self.stop("failed", f"#{d['message_id']} {d['state']} ({d['reason']})")
            since = d["received_at"]
            if self.sources[d["message_id"]] == "probe2":
                since = max([since] + p1_ended) if p1_ended and all(p1_ended) else None
            if d["state"] not in TERMINAL and since is not None and now - since > ACK_WITHIN:
                return self.stop("failed", f"no ACK for #{d['message_id']} within {ACK_WITHIN // 60} min")
        by_kind = {kind: mid for mid, kind in self.sources.items()}
        state = {d["message_id"]: d["state"] for d in rows}
        live = {}
        for a in self.attempts():
            if not a["launched_at"]:
                continue
            seen = self.r["launches"].setdefault(str(a["message_id"]), {})
            if a["attempt_id"] not in seen:
                image = env.image(a["pid"]) if env.processes.is_same(a["pid"], a["proc_start"]) else None
                seen[a["attempt_id"]] = dict(pid=a["pid"], proc_start=a["proc_start"],
                                             launched_at=a["launched_at"], image=image)
                env.say(f"launch for #{a['message_id']}: pid {a['pid']} image {image}")
                if len(seen) > 1:
                    return self.stop("failed", f"more than one launch for #{a['message_id']}")
                if image is not None and not _same(image, self.s["cli"]):
                    return self.stop("inconclusive", f"launched {image}, not the registered cli")
                if self.sources[a["message_id"]] == "probe2":
                    first = self.r["launches"].get(str(by_kind.get("probe1")), {})
                    if any(env.processes.is_same(f["pid"], f["proc_start"]) for f in first.values()):
                        return self.stop("failed", "probe2 launched while the probe1 run was alive")
            if env.processes.is_same(a["pid"], a["proc_start"]):
                live[a["message_id"]] = a
                if now - a["launched_at"] > RUN_LIMIT:
                    return self.stop("failed", f"run for #{a['message_id']} past {RUN_LIMIT // 60} min")
        first = by_kind.get("probe1")
        if self.r["probe2"] == "not posted" and first is not None:
            if first in live:
                self.r["probe2"] = env.post(self.s["probe2"])
                self.r["probe2_posted_at"] = now
                env.say(f"probe2 posted while the probe1 run is alive: {self.r['probe2']}")
            elif state.get(first) in TERMINAL:
                # probe2 goes out the moment the probe1 run is seen alive, so
                # this means it never was: no executable identity, and §7
                # item 6 not exercised. Never a pass.
                self.r["probe2"] = "not exercised"
                return self.stop("inconclusive", "the probe1 run was never observed alive; "
                                                 "no executable identity, item 6 not exercised")
        # A delivery is only evidence of the CLOSED path if exactly one
        # headless launch carried it; an ACK from an open app has none.
        launched = lambda mid: len(self.r["launches"].get(str(mid), {})) == 1  # noqa: E731
        second = by_kind.get("probe2")
        done = (first is not None and state.get(first) == "delivered" and launched(first) and not live
                and state.get(second) == "delivered" and launched(second))
        if not done:
            return None
        # The liveness check above only sees an overlap that spans a sample;
        # the relay's own rows decide item 6 (Codex, #133 at 317a547).
        runs = {a["message_id"]: a for a in self.attempts() if a["launched_at"]}
        ended, began = runs[first]["ended_at"], runs[second]["launched_at"]
        if ended is None or began is None:
            return None     # unproven yet; the proof window bounds the wait
        if began < ended:
            return self.stop("failed", f"probe2 launched at {began} before the probe1 run ended at {ended}")
        return "passed"

    def cleanup(self) -> None:
        """Stop only the proof's own runs, by pid and creation time, then settle."""
        env = self.env
        for a in self.attempts():
            if not a["launched_at"]:
                continue
            rec = self.r["launches"].setdefault(str(a["message_id"]), {}).setdefault(
                a["attempt_id"], dict(pid=a["pid"], proc_start=a["proc_start"], launched_at=a["launched_at"]))
            while env.processes.is_same(a["pid"], a["proc_start"]) and env.now() < a["launched_at"] + RUN_LIMIT:
                env.sleep(5)
            if env.processes.is_same(a["pid"], a["proc_start"]):
                env.processes.kill_tree(a["pid"])
                for _ in range(30):
                    if not env.processes.is_same(a["pid"], a["proc_start"]):
                        break
                    env.sleep(1)
                rec["killed"] = True
            rec["confirmed_exited"] = not env.processes.is_same(a["pid"], a["proc_start"])
            if not rec["confirmed_exited"]:
                self.stop("failed", f"pid {a['pid']} not confirmed stopped")
        def settled() -> bool:
            unrecorded = [a for a in self.attempts() if a["launched_at"] and not a["usage_recorded"]]
            return not unrecorded and not env.rows("SELECT 1 FROM reservations WHERE recipient = ?", LEAD)
        deadline = env.now() + SETTLE
        while env.now() < deadline and not settled():
            env.sleep(5)
        self.r["relay_settled"] = settled()
        self.r["final_deliveries"] = [(d["message_id"], d["state"], d["reason"]) for d in self.deliveries()]
        self.r["attempt_states"] = [(a["message_id"], a["state"], a["exit_code"], a["usage_recorded"])
                                    for a in self.attempts()]
        if not self.r["relay_settled"]:
            self.stop("failed", "the relay has not released the reservation or recorded usage")

    def evidence(self) -> None:
        """Final facts a pass depends on, checked however fast the run finished."""
        env, s = self.env, self.s
        self.r["config_sha256_after"] = sha256(env.config)
        if self.r["config_sha256_after"] != s["config_sha256"]:
            self.stop("failed", "config.toml changed during the proof")
        cli_ok = Path(s["cli"]).is_file() and sha256(Path(s["cli"])) == s["cli_sha256"]
        if not cli_ok:
            self.stop("inconclusive", "the registered cli changed during the proof")
        rows = env.rows("SELECT * FROM sessions WHERE recipient = ?", LEAD)
        if (len(rows) != 1 or rows[0]["session_id"].lower() != THREAD
                or not _same(rows[0]["workspace"], WORKSPACE) or not _same(rows[0]["cli"], s["cli"])):
            self.stop("failed", "the codex-lead binding changed during the proof")
        self.r["new_session_files"] = env.new_session_files(s["run_started"])
        if self.r["new_session_files"]:
            self.stop("failed", f"new session files {self.r['new_session_files']}")
        unknown = [aid for runs in self.r["launches"].values() for aid, rec in runs.items()
                   if not rec.get("image")]
        if unknown:
            self.stop("inconclusive", f"no executable identity recorded for {unknown}")


def run(env, state_path: Path, poll: float = 2.0) -> int:
    lock = claim(state_path)
    if lock is None:
        env.say("REFUSED: another proof driver is running")
        return 1
    try:
        return _run(env, state_path, poll)
    finally:
        os.close(lock)


def _run(env, state_path: Path, poll: float) -> int:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("status") != "prepared":
        env.say(f"REFUSED: proof {state['proof_id']} is {state.get('status')}; prepare a new one")
        return 1
    if env.now() >= state["enable_by"]:
        env.say(f"REFUSED: proof {state['proof_id']}'s enable window has ended")
        return 1
    if result_path(state_path, state["proof_id"]).exists():
        env.say(f"REFUSED: proof {state['proof_id']} already has a result")
        return 1
    state.update(status="claimed", run_started=env.now(), owner_pid=os.getpid())
    save(state_path, state)
    proof = Proof(env, state)
    try:
        while True:
            problems = preflight(env, state, enabled=0, closed=True)
            if not problems:
                break
            if env.now() >= state["enable_by"]:
                proof.stop("expired", "never enabled: " + "; ".join(problems))
                return 1
            env.sleep(poll)
        enabled_at = env.now()
        proof.r["enable"] = dict(at=enabled_at)
        rc, out = env.relay_cli("enable", "--lead", LEAD)
        proof.r["enable"].update(rc=rc, out=out)
        if rc != 0 or preflight(env, state, enabled=1, closed=True):
            proof.stop("failed", f"enable did not take cleanly: rc {rc} {out}")
            return 1
        env.say(f"ENABLED. David posts exactly: {state['probe1']}")
        # Only now, with the enable confirmed, is David told to send probe 1
        # (hive #1893). Not an envelope, so it wakes no one.
        proof.r["ready_posted"] = env.post(
            f"STATUS @admin: proof {state['proof_id']} ENABLED and watching. Paste exactly this, "
            f"once: {state['probe1']}")
        last_files = enabled_at
        while True:
            verdict = proof.step()
            if verdict:
                proof.r["verdict"] = proof.r["verdict"] or verdict
                break
            if env.now() - last_files >= 60:
                last_files = env.now()
                stray = env.new_session_files(enabled_at)
                if stray:
                    proof.stop("failed", f"new session files {stray}")
                    break
            if env.now() - enabled_at > PROOF_WINDOW:
                proof.stop("expired", f"not finished within {PROOF_WINDOW // 60} min of enable")
                break
            env.sleep(poll)
    except Exception as exc:  # noqa: BLE001 -- still disables and cleans up below
        proof.stop("failed", f"{type(exc).__name__}: {exc}")
    finally:
        finish(env, proof, state, state_path)
    return 0 if proof.r["verdict"] == "passed" else 1


def finish(env, proof: "Proof", state: dict, state_path: Path) -> None:
    """Every recovery stage runs, whatever an earlier one raised."""
    r = proof.r
    r["disable"] = {}
    try:
        rc, out = env.relay_cli("disable", "--lead", LEAD)
        r["disable"].update(rc=rc, out=out)
    except Exception as exc:  # noqa: BLE001
        r["disable"]["error"] = f"{type(exc).__name__}: {exc}"
    try:
        stored = env.rows("SELECT enabled FROM sessions WHERE recipient = ?", LEAD)
        r["disable"]["stored_enabled"] = stored[0]["enabled"] if stored else None
    except Exception as exc:  # noqa: BLE001
        r["disable"]["stored_enabled"] = None
        r["disable"]["verify_error"] = f"{type(exc).__name__}: {exc}"
    r["disable"]["confirmed"] = r["disable"]["stored_enabled"] == 0
    if not r["disable"]["confirmed"]:
        proof.stop("failed", "codex-lead is NOT confirmed disabled: run "
                             "`lead_relay.py disable --lead codex-lead` and check it")
    env.say(f"disable: {r['disable']}")
    for name, stage in (("cleanup", proof.cleanup), ("evidence", proof.evidence)):
        try:
            stage()
        except Exception as exc:  # noqa: BLE001
            proof.stop("failed", f"{name}: {type(exc).__name__}: {exc}")
    try:
        r["statuses"] = [(m["id"], m["content"][:300]) for m in env.statuses(state["baseline"])]
    except Exception as exc:  # noqa: BLE001 -- informational; the hive is the record
        r["statuses"] = f"unread: {type(exc).__name__}: {exc}"
    try:
        save(result_path(state_path, state["proof_id"]), r)
        state.update(status="finished", verdict=r["verdict"])
        save(state_path, state)
    except Exception as exc:  # noqa: BLE001 -- the terminal still gets the whole result
        env.say(f"RESULT NOT SAVED ({type(exc).__name__}: {exc}): {json.dumps(r, sort_keys=True)}")
    env.say(f"RESULT {r['verdict']}: {'; '.join(r['why']) or 'no stop reasons'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(HERE / "control" / "lead_relay.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--cli", required=True)
    p.add_argument("--cli-sha256", required=True)
    p.add_argument("--config-sha256", required=True)
    sub.add_parser("run")
    sub.add_parser("reconcile-old", help=f"record proof {OLD_PROOF} as cancelled before enable, once")
    args = parser.parse_args(argv)
    db = Path(args.db)
    state_path = db.with_name(STATE_NAME)
    env = Env(db)
    if args.command == "reconcile-old":
        return reconcile(env, db.parent)
    if args.command == "prepare":
        return prepare(env, state_path, args.cli, args.cli_sha256.lower(), args.config_sha256.lower())
    return run(env, state_path)


if __name__ == "__main__":
    sys.exit(main())
