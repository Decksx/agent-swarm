"""Non-secret launcher settings, including fresh Windows user settings.

An already-running app need not have inherited a recently configured user
environment value. Only explicitly named, non-secret settings are read here.
"""

import os


def setting(name: str) -> str | None:
    if name not in {"CODEX_CLI", "CLAUDE_CLI", "CLAUDE_RATE_GUARD_DIR"}:
        raise ValueError("not a supported host setting")
    if name in os.environ:
        return os.environ[name].strip() or None
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value).strip() or None
        except OSError:
            pass
    return None
