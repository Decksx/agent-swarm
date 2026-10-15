"""Prompt-only CLI planners, isolated from the repository and controller."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import claude_rate_guard
from host_settings import setting
from swarm_control import AlreadyRunning


class PlannerCliError(Exception):
    """A CLI planner could not produce a complete reply."""


@dataclass(frozen=True)
class Reply:
    text: str
    reported_models: tuple[str, ...] = ()


def resolve_binary(provider: str) -> str:
    configured = setting(f"{provider.upper()}_CLI")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise PlannerCliError(f"{provider.upper()}_CLI must name an existing absolute executable path")
        return str(path)
    binary = shutil.which(provider)
    if not binary:
        raise PlannerCliError(
            f"{provider} CLI not found; set {provider.upper()}_CLI to its absolute path or add it to PATH"
        )
    return binary


def _claude_usage() -> tuple[Path, float]:
    root = setting("CLAUDE_RATE_GUARD_DIR")
    if not root:
        raise PlannerCliError(
            "set CLAUDE_RATE_GUARD_DIR to the live Claude worker's usage directory before planning"
        )
    directory = Path(root).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        raise PlannerCliError("CLAUDE_RATE_GUARD_DIR must name an existing absolute directory")
    usage = directory / "claude_worker.usage"
    cooldown = float(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", str(5 * 3600)))
    warn = float(os.environ.get("RATE_LIMIT_WARN_SECONDS", str(4.5 * 3600)))
    if not all(math.isfinite(value) and value > 0 for value in (warn, cooldown)):
        raise ValueError("Claude rate thresholds must be positive and finite")
    reason, _ = claude_rate_guard.rate_limit_reason(
        None, ratelimit_path=directory / "claude_worker.ratelimit",
        usage_window=claude_rate_guard.read_usage(usage),
        warn_seconds=warn,
        cooldown_seconds=cooldown,
    )
    if reason:
        raise PlannerCliError(f"Claude planning held: {reason}")
    return usage, cooldown


def generate(provider: str, prompt: str, *, model: str | None = None,
             timeout: float = 600) -> Reply:
    if provider not in ("codex", "claude"):
        raise PlannerCliError(f"unsupported CLI planner: {provider}")
    binary = resolve_binary(provider)
    usage = None
    try:
        if provider == "claude":
            usage = _claude_usage()
    except (OSError, ValueError):
        raise PlannerCliError("could not read Claude's shared usage guard") from None

    # No repository, controller credential, project hooks or MCP configuration
    # belongs in a planning call. Context is supplied by the common pipeline.
    env = {k: v for k, v in os.environ.items()
           if not (k.upper() in {
               "HUB_SECRET", "HUB_CREDENTIALS", "OPENAI_API_KEY", "CODEX_API_KEY",
               "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
               "ANTHROPIC_AUTH_TOKEN", "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
               "GOOGLE_APPLICATION_CREDENTIALS",
           } or k.upper().endswith(("_HUB_SECRET", "_API_KEY")))}
    with tempfile.TemporaryDirectory(prefix="swarm-planner-") as scratch:
        answer = Path(scratch) / "answer.txt"
        if provider == "codex":
            command = [binary, "exec", "--ignore-user-config", "--ephemeral",
                       "--skip-git-repo-check", "--sandbox", "read-only",
                       "--json", "--output-last-message", str(answer),
                       "--config", 'web_search="disabled"']
            for feature in ("shell_tool", "unified_exec", "apps", "hooks",
                            "remote_plugin", "multi_agent", "goals"):
                command += ["--disable", feature]
            if model:
                command += ["--model", model]
            command += ["-"]
        else:
            # Bare mode ignores subscription OAuth credentials. Suppress
            # discovery through settings/tool flags while retaining CLI login.
            command = [binary, "--print", "--tools", "",
                       "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                       "--disable-slash-commands", "--disallowedTools", "mcp__*",
                       "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--no-session-persistence", "--output-format", "json"]
            if model:
                command += ["--model", model]
        start_time, started = time.time(), time.monotonic()
        try:
            result = subprocess.run(
                command, input=prompt, cwd=scratch, env=env,
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise PlannerCliError(f"{provider} planner timed out") from None
        except OSError:
            raise PlannerCliError(f"{provider} planner could not start") from None
        finally:
            if usage is not None:
                try:
                    claude_rate_guard.record_usage(
                        usage[0], [], start_time, time.monotonic() - started,
                        usage[1], strict=True,
                    )
                except (OSError, AlreadyRunning):
                    # Never return a successful plan whose usage went missing.
                    raise PlannerCliError("could not record Claude planner usage") from None
        if result.returncode:
            # Provider diagnostics may contain credentials or the entire
            # snapshot. Never copy stderr into reports or hub messages.
            raise PlannerCliError(
                f"{provider} planner exited with code {result.returncode}"
            )
        try:
            if provider == "codex":
                events = [json.loads(line) for line in result.stdout.splitlines()
                          if line.strip()]
                if (not any(e.get("type") == "turn.completed" for e in events)
                        or any(e.get("type") in ("error", "turn.failed")
                               for e in events)):
                    raise PlannerCliError("codex planner did not complete a turn")
                text = answer.read_text(encoding="utf-8").strip()
                models = tuple(sorted({e["model"] for e in events
                                       if isinstance(e.get("model"), str)}))
            else:
                data = json.loads(result.stdout)
                if data.get("is_error") or data.get("subtype") != "success":
                    raise PlannerCliError("claude planner did not complete a turn")
                text = data["result"].strip()
                models = tuple(sorted(data.get("modelUsage", {})))
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            raise PlannerCliError(f"{provider} planner returned an invalid reply") from None
        if not text:
            raise PlannerCliError(f"{provider} planner returned an empty reply")
        return Reply(text=text, reported_models=models)
