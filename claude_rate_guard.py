"""The model-usage rate guard, as logic over state the caller passes in.

Extracted from `claude_worker` unchanged in behaviour, so that module fits the
author's file view (#25). The state -- the hold-off and usage paths, both
thresholds, and the in-memory usage window -- still lives in `claude_worker`,
which passes it in on every call and stores back any window returned. That is
what keeps a value patched on `claude_worker` effective at call time, and it
is why this module never imports `claude_worker`. Logging stays on the
"claude_worker" logger.

After the window trips, the worker waits RATE_LIMIT_COOLDOWN_SECONDS and then
resumes by itself. Previously it stopped accepting work until somebody
restarted it, which is a manual step in a system whose whole point is not
needing one -- and an operator who did not notice would find a worker that
looked healthy and had quietly stopped working hours earlier.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("claude_worker")

# Stages whose execution never invokes the model (#23). Integration is git and
# the forge, checked fact by fact; a hold-off on model usage has no reason to
# stop it, and stopping it strands approved work in INTEGRATING.
MODEL_FREE_STAGES = frozenset({"integrate"})


def claim_stages(held: bool) -> tuple[str, ...] | None:
    """What a claim may take: None for anything, or only model-free stages when held.

    A sorted tuple rather than the frozenset, so what crosses the HTTP boundary
    is deterministic.
    """
    return tuple(sorted(MODEL_FREE_STAGES)) if held else None


def read_holdoff(ratelimit_path: Path) -> float:
    """The epoch time the current hold-off ends, or 0.0 if there is none."""
    try:
        return float(ratelimit_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        # Missing is the ordinary case; unreadable is treated the same way
        # rather than as an indefinite hold, because a file nothing can parse
        # would otherwise stop this worker forever.
        return 0.0


def read_usage(usage_path: Path) -> list[tuple[float, float]]:
    """Persisted (started, seconds) records. Missing is empty; malformed warns."""
    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise TypeError(type(raw).__name__)
        return [(float(started), float(seconds)) for started, seconds in raw]
    except FileNotFoundError:
        return []
    except (OSError, TypeError, ValueError):
        log.warning("could not read usage file; treating as empty")
        return []


def write_usage(usage_path: Path, usage_window: list[tuple[float, float]]) -> None:
    """Persist the rolling window of usage seconds."""
    try:
        with open(usage_path, "w", encoding="utf-8") as f:
            json.dump(usage_window, f)
    except OSError as exc:
        log.error("could not persist usage: %s", exc)


def purge_old_usage(
    usage_window: list[tuple[float, float]], now: float, cooldown_seconds: float
) -> list[tuple[float, float]]:
    """Remove usage outside the rolling window; returns a new list."""
    cutoff = now - cooldown_seconds
    return [
        (timestamp, usage) for (timestamp, usage) in usage_window
        if timestamp >= cutoff
    ]


def current_usage_total(
    usage_window: list[tuple[float, float]], now: float, cooldown_seconds: float
) -> tuple[list[tuple[float, float]], float]:
    """The purged window, and the total usage seconds within it."""
    usage_window = purge_old_usage(usage_window, now, cooldown_seconds)
    return usage_window, sum(usage for _, usage in usage_window)


def record_usage(
    usage_path: Path, usage_window: list[tuple[float, float]],
    start_time: float, elapsed_time: float, cooldown_seconds: float,
) -> list[tuple[float, float]]:
    """Record model usage; appends to the given list, returns the purged one."""
    usage_window.append((start_time, elapsed_time))
    usage_window = purge_old_usage(usage_window, start_time, cooldown_seconds)
    write_usage(usage_path, usage_window)
    return usage_window


def begin_holdoff(ratelimit_path: Path, now: float, cooldown_seconds: float) -> float:
    """Start a hold-off and return when it ends."""
    until = now + cooldown_seconds

    try:
        ratelimit_path.write_text(f"{until:.0f}", encoding="utf-8")
    except OSError as exc:
        log.error("could not persist the rate hold-off: %s", exc)

    return until


def end_holdoff(ratelimit_path: Path) -> None:
    """Clear the hold-off."""
    try:
        ratelimit_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("could not clear the rate hold-off: %s", exc)


def rate_limit_reason(
    now: float | None, *, ratelimit_path: Path,
    usage_window: list[tuple[float, float]],
    warn_seconds: float, cooldown_seconds: float,
) -> tuple[str | None, list[tuple[float, float]]]:
    """Why no new work should be claimed right now (or None), and the window.

    Recovers on its own. When the hold-off deadline passes, the deadline is
    cleared, and work resumes with no restart and no operator action.

    Deliberately returns a reason rather than calling anything: this is
    consulted before the claim, so a guarded worker takes no activation and
    makes no provider call at all. Claiming and then refusing would consume
    work it had already decided not to do.
    """
    now = time.time() if now is None else now
    until = read_holdoff(ratelimit_path)

    if until:
        if now < until:
            return (
                f"rate hold-off until {time.strftime('%H:%M:%S', time.localtime(until))} "
                f"({(until - now) / 60:.0f} min remaining)"
            ), usage_window

        end_holdoff(ratelimit_path)
        log.info("rate hold-off has expired; accepting work again")
        return None, usage_window

    usage_window, total_usage = current_usage_total(usage_window, now, cooldown_seconds)

    if total_usage >= warn_seconds:
        until = begin_holdoff(ratelimit_path, now, cooldown_seconds)
        return (
            f"worker usage {total_usage/3600:.1f}h reached the "
            f"{warn_seconds / 3600:.1f}h window; holding off for "
            f"{cooldown_seconds / 3600:.1f}h"
        ), usage_window

    return None, usage_window
