"""Planner transports never acquire author or controller authority."""

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import planner_cli


@pytest.fixture
def transport(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(planner_cli.shutil, "which", lambda name: name + ".exe")
    monkeypatch.setattr(planner_cli, "setting", lambda name:
                        str(tmp_path) if name == "CLAUDE_RATE_GUARD_DIR" else None)

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


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_provider_credentials_cannot_override_cached_cli_login(provider, transport, monkeypatch):
    names = ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
             "GOOGLE_API_KEY", "OTHER_API_KEY", "ANTHROPIC_AUTH_TOKEN",
             "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS")
    for name in names:
        monkeypatch.setenv(name, "not-a-real-credential")
    monkeypatch.setenv("CODEX_HOME", "cached-login-directory")
    planner_cli.generate(provider, "plan")
    assert not set(names).intersection(transport["env"])
    assert transport["env"]["CODEX_HOME"] == "cached-login-directory"


def test_configured_codex_binary_works_without_path(transport, monkeypatch, tmp_path):
    binary = tmp_path / "directory with spaces" / "codex.exe"
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.setattr(planner_cli, "setting", lambda name: str(binary) if name == "CODEX_CLI" else None)
    monkeypatch.setattr(planner_cli.shutil, "which", lambda _: None)
    assert planner_cli.resolve_binary("codex") == str(binary)


def test_invalid_configured_binary_never_silently_selects_path(transport, monkeypatch):
    monkeypatch.setattr(planner_cli, "setting", lambda _: "relative/codex.exe")
    with pytest.raises(planner_cli.PlannerCliError, match="CODEX_CLI"):
        planner_cli.generate("codex", "plan")


def test_missing_codex_explains_how_to_configure_it(transport, monkeypatch):
    monkeypatch.setattr(planner_cli.shutil, "which", lambda _: None)
    with pytest.raises(planner_cli.PlannerCliError, match="set CODEX_CLI"):
        planner_cli.generate("codex", "plan")


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_error_marker_wins_over_a_success_marker(provider, transport, monkeypatch):
    original = planner_cli.subprocess.run

    def mixed(command, **kwargs):
        result = original(command, **kwargs)
        if provider == "codex":
            result.stdout += '\n' + json.dumps({"type": "error", "message": "private provider content"})
        else:
            data = json.loads(result.stdout)
            data["is_error"] = True
            result.stdout = json.dumps(data)
        return result

    monkeypatch.setattr(planner_cli.subprocess, "run", mixed)
    with pytest.raises(planner_cli.PlannerCliError, match="did not complete"):
        planner_cli.generate(provider, "plan")


def test_claude_refuses_an_active_worker_hold_before_starting(transport):
    root = Path(planner_cli.setting("CLAUDE_RATE_GUARD_DIR"))
    (root / "claude_worker.ratelimit").write_text(str(time.time() + 600))
    with pytest.raises(planner_cli.PlannerCliError, match="planning held"):
        planner_cli.generate("claude", "plan")
    assert not transport, "the CLI must not be launched during a hold"
    assert not (root / "claude_worker.usage").exists()


def test_claude_reads_worker_usage_before_starting(transport, monkeypatch):
    root = Path(planner_cli.setting("CLAUDE_RATE_GUARD_DIR"))
    planner_cli.claude_rate_guard.write_usage(root / "claude_worker.usage", [(time.time(), 6)])
    monkeypatch.setenv("RATE_LIMIT_WARN_SECONDS", "5")
    with pytest.raises(planner_cli.PlannerCliError, match="planning held"):
        planner_cli.generate("claude", "plan")
    assert not transport


@pytest.mark.parametrize("outcome", ["success", "failed", "timeout"])
def test_claude_records_duration_even_when_the_call_fails(outcome, transport, monkeypatch):
    root = Path(planner_cli.setting("CLAUDE_RATE_GUARD_DIR"))
    clock = iter([10.0, 13.0])
    monkeypatch.setattr(planner_cli, "time", SimpleNamespace(time=lambda: 1000.0,
                                                          monotonic=lambda: next(clock)))
    if outcome != "success":
        def fail(*a, **kw):
            if outcome == "timeout":
                raise subprocess.TimeoutExpired("claude", 1)
            return SimpleNamespace(returncode=1, stdout="", stderr="private diagnostic")
        monkeypatch.setattr(planner_cli.subprocess, "run", fail)
    if outcome == "success":
        planner_cli.generate("claude", "plan")
    else:
        with pytest.raises(planner_cli.PlannerCliError):
            planner_cli.generate("claude", "plan")
    assert planner_cli.claude_rate_guard.read_usage(root / "claude_worker.usage") == [(1000.0, 3.0)]


def test_claude_requires_an_explicit_shared_worker_directory(transport, monkeypatch):
    monkeypatch.setattr(planner_cli, "setting", lambda _: None)
    with pytest.raises(planner_cli.PlannerCliError, match="CLAUDE_RATE_GUARD_DIR"):
        planner_cli.generate("claude", "plan")
    assert not transport


def test_unrecorded_usage_cannot_return_a_successful_plan(transport, monkeypatch):
    monkeypatch.setattr(planner_cli.claude_rate_guard, "write_usage", lambda *a: False)
    with pytest.raises(planner_cli.PlannerCliError, match="could not record"):
        planner_cli.generate("claude", "plan")
