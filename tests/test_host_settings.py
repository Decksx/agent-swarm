import contextlib
import sys
from types import SimpleNamespace

import pytest

import host_settings


def test_process_setting_takes_precedence(monkeypatch):
    monkeypatch.setenv("CODEX_CLI", "explicit-process-path")
    assert host_settings.setting("CODEX_CLI") == "explicit-process-path"


def test_fresh_windows_user_setting_is_visible_without_restarting_app(monkeypatch):
    monkeypatch.delenv("CODEX_CLI", raising=False)
    registry = SimpleNamespace(HKEY_CURRENT_USER=1,
        OpenKey=lambda *a: contextlib.nullcontext("key"),
        QueryValueEx=lambda key, name: ("configured-user-path", 1))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    with monkeypatch.context() as scoped:
        scoped.setattr(host_settings.os, "name", "nt")
        actual = host_settings.setting("CODEX_CLI")
    assert actual == "configured-user-path"


def test_host_settings_never_reads_provider_credentials():
    with pytest.raises(ValueError, match="not a supported"):
        host_settings.setting("OPENAI_API_KEY")
