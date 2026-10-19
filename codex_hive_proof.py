"""One local processing attempt for the finite same-thread watcher proof.

This does not create a schedule, resume a conversation or perform engineering.
Runtime claims/results belong in the original workspace, never in Git.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PRODUCTION_CHAT = Path(r"C:\swarm-prod\agent-swarm\lead_chat.py")
PROBE_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")


def production_chat():
    """Load exactly the pinned production helper, even in a dev checkout."""
    name = "_codex_proof_production_chat"
    spec = importlib.util.spec_from_file_location(name, PRODUCTION_CHAT)
    if spec is None or spec.loader is None:
        raise ImportError("production chat helper unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def save(path: Path, data: dict):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def run(root: Path, probe: str, baseline: int, expires: float, *, api, now=time.time):
    """At most one claimant may read/process this probe; uncertainty never retries.

    The caller must verify the actual app thread/run identity. A CLI argument
    alone cannot prove that the scheduler returned to the correct thread.
    """
    if not root.is_absolute() or not PROBE_ID.fullmatch(probe):
        raise ValueError("absolute runtime root and safe probe id required")
    if type(baseline) is not int or baseline < 0:
        raise ValueError("nonnegative integer baseline required")
    if now() >= expires:
        return {"state": "expired", "probe": probe}
    directory = root / probe
    directory.mkdir(parents=True, exist_ok=True)
    try:
        stream = (directory / "claim.json").open("x", encoding="utf-8")
    except FileExistsError:
        return {"state": "skipped-existing-claim", "probe": probe}
    with stream:
        json.dump({"probe": probe, "baseline": baseline, "claimed_at": now()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    result = {"state": "not-proven", "probe": probe}
    try:
        rows = api.read("codex-lead", since_id=baseline)
        matches = [row for row in rows if isinstance(row, dict)
                   and type(row.get("id")) is int and row["id"] > baseline
                   and row.get("sender") == "claude-lead"
                   and row.get("target") == "@codex-lead"
                   and row.get("content") == f"PROBE @codex-lead: {probe}"]
        if len(matches) != 1:
            result["reason"] = "expected-one-fresh-probe"
        else:
            source = matches[0]["id"]
            content = f"PROBE-ACK #{source} {probe}"
            found = api.find("codex-lead", content, since_id=baseline)
            if not isinstance(found, list) or any(type(i) is not int or i <= 0 for i in found):
                raise ValueError("invalid find response")
            result["source_id"] = source
            if found:
                result.update(state="duplicate-suppressed", ack_ids=found)
            elif now() >= expires:
                result.update(state="expired", reason="expired-before-post")
            else:
                # Exactly one call. The existing helper confirms by read-back.
                receipt = api.post("codex-lead", content, target="@claude-lead")
                confirmed = (receipt.state == "confirmed"
                             and type(receipt.message_id) is int and receipt.message_id > 0)
                result.update(state="confirmed" if confirmed else "uncertain",
                              ack_id=receipt.message_id)
    except Exception as exc:  # Claim remains even if a post's response was lost.
        result.update(state="uncertain", error=type(exc).__name__)
    save(directory / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--probe", required=True)
    parser.add_argument("--baseline", required=True, type=int)
    parser.add_argument("--expires", required=True, help="ISO UTC expiry, ending in Z")
    args = parser.parse_args(argv)
    try:
        if not args.expires.endswith("Z"):
            raise ValueError("UTC expiry required")
        expiry = datetime.fromisoformat(args.expires[:-1] + "+00:00").timestamp()
        result = run(args.root, args.probe, args.baseline, expiry, api=production_chat())
    except Exception as exc:
        result = {"state": "not-proven", "error": type(exc).__name__}
    print(json.dumps(result))
    return 0 if result["state"] in ("confirmed", "duplicate-suppressed",
                                    "skipped-existing-claim") else 1


if __name__ == "__main__":
    raise SystemExit(main())
