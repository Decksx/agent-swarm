"""Prompt-only CLI planners, isolated from the repository and controller."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class PlannerCliError(Exception):
    """A CLI planner could not produce a complete reply."""


@dataclass(frozen=True)
class Reply:
    text: str
    reported_models: tuple[str, ...] = ()


def generate(provider: str, prompt: str, *, model: str | None = None,
             timeout: float = 600) -> Reply:
    if provider not in ("codex", "claude"):
        raise PlannerCliError(f"unsupported CLI planner: {provider}")
    binary = shutil.which(provider)
    if not binary:
        raise PlannerCliError(f"{provider} CLI is not installed or not on PATH")

    # No repository, controller credential, project hooks or MCP configuration
    # belongs in a planning call. Context is supplied by the common pipeline.
    env = {k: v for k, v in os.environ.items()
           if not (k == "HUB_SECRET" or k == "HUB_CREDENTIALS"
                   or k.endswith("_HUB_SECRET"))}
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
