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
THREAD = "01a14068-d723-76a0-a86d-c7d7b34c1b30"
WORKSPACE = r"C:\Users\david\Documents\Codex"
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


def prepare(env, state_path: Path, cli: str, cli_sha256: str, config_sha256: str) -> int:
    if state_path.exists():
        old = json.loads(state_path.read_text(encoding="utf-8"))
        if not old.get("used") and env.now() < old["enable_by"]:
            env.say(f"REFUSED: proof {old['proof_id']} is prepared and unused until its window ends")
            return 1
    proof_id = secrets.token_hex(4)
    cursor = int(env.rows("SELECT value FROM meta WHERE key = 'cursor'")[0]["value"])
    state = dict(proof_id=proof_id, prepared_at=env.now(), enable_by=env.now() + ENABLE_WINDOW,
                 cli=cli, cli_sha256=cli_sha256, config_sha256=config_sha256, baseline=cursor,
                 probe1=probes(proof_id)[0], probe2=probes(proof_id)[1], used=False)
    problems = preflight(env, state, enabled=0, closed=False)
    if problems:
        env.say("REFUSED: " + "; ".join(problems))
        return 1
    save(state_path, state)
    env.say(f"prepared proof {proof_id}; enable window ends in {ENABLE_WINDOW // 60} min")
    env.say(f"David posts, after ENABLED: {state['probe1']}")
    return 0


class Proof:
    def __init__(self, env, state: dict):
        self.env, self.s = env, state
        self.r = dict(proof_id=state["proof_id"], verdict=None, why=[], launches={}, probe2="not posted")
        self.sources: dict = {}     # message_id -> "probe1" | "probe2"

    def stop(self, verdict: str, why: str) -> str:
        # A later failure (say, disable not confirmed) outranks an earlier pass.
        if self.r["verdict"] in (None, "passed", "partial"):
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
                self.r["probe2"] = "not exercised"
                env.say("probe2 not exercised: the probe1 run ended before it could be posted")
        # A delivery is only evidence of the CLOSED path if exactly one
        # headless launch carried it; an ACK from an open app has none.
        launched = lambda mid: len(self.r["launches"].get(str(mid), {})) == 1  # noqa: E731
        second = by_kind.get("probe2")
        done = (first is not None and state.get(first) == "delivered" and launched(first) and not live
                and (self.r["probe2"] == "not exercised"
                     or (state.get(second) == "delivered" and launched(second))))
        if done:
            return "passed" if self.r["probe2"] != "not exercised" else "partial"
        return None

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
        deadline = env.now() + SETTLE
        while env.now() < deadline and env.rows("SELECT 1 FROM reservations WHERE recipient = ?", LEAD):
            env.sleep(5)
        self.r["reservation_released"] = not env.rows("SELECT 1 FROM reservations WHERE recipient = ?", LEAD)
        self.r["final_deliveries"] = [(d["message_id"], d["state"], d["reason"]) for d in self.deliveries()]
        self.r["attempt_states"] = [(a["message_id"], a["state"], a["exit_code"]) for a in self.attempts()]


def run(env, state_path: Path, poll: float = 5.0) -> int:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("used"):
        env.say(f"REFUSED: proof {state['proof_id']} was already used; prepare a new one")
        return 1
    if env.now() >= state["enable_by"]:
        env.say(f"REFUSED: proof {state['proof_id']}'s enable window has ended")
        return 1
    state["used"], state["run_started"] = True, env.now()
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
        rc, out = env.relay_cli("enable", "--lead", LEAD)
        proof.r["enable"] = dict(at=enabled_at, rc=rc, out=out)
        if rc != 0 or preflight(env, state, enabled=1, closed=True):
            proof.stop("failed", f"enable did not take cleanly: rc {rc} {out}")
            return 1
        env.say(f"ENABLED. David posts exactly: {state['probe1']}")
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
        rc, out = env.relay_cli("disable", "--lead", LEAD)
        stored = env.rows("SELECT enabled FROM sessions WHERE recipient = ?", LEAD)
        proof.r["disable"] = dict(rc=rc, out=out, stored_enabled=stored[0]["enabled"] if stored else None)
        if not stored or stored[0]["enabled"] != 0:
            proof.stop("failed", "codex-lead is not confirmed disabled")
        env.say(f"disabled: rc {rc}, stored enabled={proof.r['disable']['stored_enabled']}")
        try:
            proof.cleanup()
            proof.r["statuses"] = [(m["id"], m["content"][:300]) for m in env.statuses(state["baseline"])]
            proof.r["config_sha256_after"] = sha256(env.config)
            proof.r["new_session_files"] = env.new_session_files(state["run_started"])
        except Exception as exc:  # noqa: BLE001
            proof.stop("failed", f"cleanup: {type(exc).__name__}: {exc}")
        save(state_path.with_name(state_path.stem + ".result.json"), proof.r)
        env.say(f"RESULT {proof.r['verdict']}: {'; '.join(proof.r['why']) or 'no stop reasons'}")
    return 0 if proof.r["verdict"] in ("passed", "partial") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(HERE / "control" / "lead_relay.db"))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--cli", required=True)
    p.add_argument("--cli-sha256", required=True)
    p.add_argument("--config-sha256", required=True)
    sub.add_parser("run")
    args = parser.parse_args(argv)
    db = Path(args.db)
    state_path = db.with_name("codex_closed_proof.json")
    env = Env(db)
    if args.command == "prepare":
        return prepare(env, state_path, args.cli, args.cli_sha256.lower(), args.config_sha256.lower())
    return run(env, state_path)


if __name__ == "__main__":
    sys.exit(main())
