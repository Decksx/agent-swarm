@echo off
REM ===========================================================================
REM Start all three agent-hub workers, each in its own window.
REM
REM Run this from a shell where the API keys are already set, e.g.:
REM     set OPENAI_API_KEY=sk-...
REM     set GEMINI_API_KEY=...
REM     start_workers.bat
REM
REM The workers inherit THIS window's environment. Keys are intentionally NOT
REM stored in this file: a .bat is plaintext and easy to share or check in by
REM accident. Use `setx NAME value` once to persist a key for future shells.
REM
REM Optional throttle overrides (otherwise the built-in defaults apply). The
REM names are shared across all three workers, so one setting governs the swarm:
REM     set REPLY_COOLDOWN_SECONDS=45
REM     set MAX_REPLIES_PER_WINDOW=8
REM     set REPLY_WINDOW_SECONDS=300
REM
REM To stop them: close each window, press Ctrl+C in each, or from PowerShell:
REM     Get-Process python ^| Where-Object { $_.CommandLine -match 'claude-agent-hub' } ^| Stop-Process -Force
REM ===========================================================================

setlocal
cd /d "%~dp0"

REM Non-fatal pre-flight warnings. The claude worker needs the `claude` CLI on
REM PATH (it checks that itself); the other two need their API keys.
if "%GEMINI_API_KEY%"=="" echo [warn] GEMINI_API_KEY not set - gemini_worker will log an error and exit.
if "%OPENAI_API_KEY%"=="" echo [warn] OPENAI_API_KEY not set - chatgpt_worker will log an error and exit.

REM Each worker runs in its own window via "cmd /k" so a startup failure
REM (missing key, bad model id) stays on screen instead of the window closing
REM before you can read it. "%~dp0" is this .bat's own folder, so the launch
REM works regardless of the directory it is started from.
start "claude_worker"  cmd /k python "%~dp0claude_worker.py"
start "chatgpt_worker" cmd /k python "%~dp0chatgpt_worker.py"
start "gemini_worker"  cmd /k python "%~dp0gemini_worker.py"

echo.
echo Launched claude_worker, chatgpt_worker and gemini_worker in separate windows.
echo Close a window (or press Ctrl+C in it) to stop that worker.
endlocal
