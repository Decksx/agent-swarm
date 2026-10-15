"""Planner transports never acquire author or controller authority."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import planner_cli


@pytest.fixture
def transport(monkeypatch):
    seen = {}
    monkeypatch.setattr(planner_cli.shutil, "which", lambda name: name + ".exe")

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        if command[0] == "codex.exe":
            Path(command[command.index("--output-last-message") + 1]).write_text(
                "  a complete plan — café  ", encoding="utf-8",
            )
            output = json.dumps({"type": "turn.completed"})
        else:
            output = json.dumps({"subtype": "success", "is_error": False,
                                 "result": "  a complete plan — café  ",
                                 "modelUsage": {"reported-claude-model": {}}})
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(planner_cli.subprocess, "run", run)
    return seen


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_prompt_is_stdin_in_an_empty_directory_without_controller_secrets(
    provider, transport, monkeypatch,
):
    monkeypatch.setenv("HUB_SECRET", "operator-secret")
    monkeypatch.setenv("GEMINI_HUB_SECRET", "worker-secret")
    monkeypatch.setenv("HUB_CREDENTIALS", "credential-table")
    prompt = 'untrusted $(shell); `command` "quotes" — text'
    result = planner_cli.generate(provider, prompt, model="explicit-model")
    assert result.text == "a complete plan — café"
    assert transport["input"] == prompt
    assert prompt not in transport["command"]
    assert transport.get("shell", False) is False
    assert not Path(transport["cwd"]).exists(), "scratch directory leaked"
    assert not any(k == "HUB_SECRET" or k == "HUB_CREDENTIALS"
                   or k.endswith("_HUB_SECRET") for k in transport["env"])
    command = transport["command"]
    assert command[command.index("--model") + 1] == "explicit-model"


def test_codex_has_no_shell_apps_or_delegation(transport):
    result = planner_cli.generate("codex", "plan")
    command = transport["command"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command and "--ephemeral" in command
    assert 'web_search="disabled"' in command
    disabled = {command[i + 1] for i, arg in enumerate(command) if arg == "--disable"}
    assert {"shell_tool", "unified_exec", "apps", "hooks", "remote_plugin",
            "multi_agent", "goals"} <= disabled
    assert "--model" not in command
    assert result.reported_models == (), "do not invent the CLI's default model"


def test_claude_keeps_login_but_disables_tools_hooks_and_mcp(transport):
    result = planner_cli.generate("claude", "plan")
    command = transport["command"]
    assert "--bare" not in command, "bare mode cannot use subscription OAuth"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert json.loads(command[command.index("--settings") + 1])["disableAllHooks"]
    assert command[command.index("--disallowedTools") + 1] == "mcp__*"
    assert "--strict-mcp-config" in command
    assert json.loads(command[command.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert result.reported_models == ("reported-claude-model",)


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("failure", ["missing", "timeout", "nonzero", "malformed", "partial"])
def test_incomplete_or_failed_calls_never_return_a_plan(
    provider, failure, transport, monkeypatch,
):
    if failure == "missing":
        monkeypatch.setattr(planner_cli.shutil, "which", lambda _: None)
    else:
        def fail(command, **kwargs):
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 1, output="partial private content")
            if failure == "nonzero":
                return SimpleNamespace(returncode=7, stdout="private output", stderr="secret key")
            output = "broken json" if failure == "malformed" else json.dumps(
                {"type": "turn.failed", "subtype": "error_max_turns", "result": "partial"}
            )
            if provider == "codex" and failure == "partial":
                Path(command[command.index("--output-last-message") + 1]).write_text("partial")
            return SimpleNamespace(returncode=0, stdout=output, stderr="secret key")
        monkeypatch.setattr(planner_cli.subprocess, "run", fail)
    with pytest.raises(planner_cli.PlannerCliError) as caught:
        planner_cli.generate(provider, "plan")
    assert "private" not in str(caught.value) and "secret key" not in str(caught.value)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_empty_reply_is_refused(provider, transport, monkeypatch):
    original = planner_cli.subprocess.run

    def empty(command, **kwargs):
        result = original(command, **kwargs)
        if provider == "codex":
            Path(command[command.index("--output-last-message") + 1]).write_text(" ")
        else:
            result.stdout = json.dumps({"subtype": "success", "result": " "})
        return result

    monkeypatch.setattr(planner_cli.subprocess, "run", empty)
    with pytest.raises(planner_cli.PlannerCliError, match="empty reply"):
        planner_cli.generate(provider, "plan")
