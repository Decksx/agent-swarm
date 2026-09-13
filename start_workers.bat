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
REM Phase 0 containment: chat cannot start work. The workers narrate to the hub
REM and are readable there, but they take activations only from the local
REM control directory, which the hub cannot reach. To drive one:
REM     python swarm_control.py issue claudecode "run the preflight"
REM     python swarm_control.py status
REM
REM To stop the swarm starting anything, without killing the processes:
REM     python swarm_control.py pause "reason"
REM     python swarm_control.py resume
REM Or set SWARM_PAUSED=1 in this window before launching.
REM
REM The old REPLY_COOLDOWN_SECONDS / MAX_REPLIES_PER_WINDOW / REPLY_WINDOW_SECONDS
REM throttles are gone. They braked a chat-driven loop that can no longer form;
REM setting them now has no effect. See docs/PHASE0_CONTAINMENT.md.
REM
REM To stop them: close each window, press Ctrl+C in each, or from PowerShell:
REM     Get-Process python ^| Where-Object { $_.CommandLine -match 'agent-swarm' } ^| Stop-Process -Force
REM ===========================================================================

setlocal
cd /d "%~dp0"

REM Hub credentials are PER COMPONENT, and each worker must receive only its
REM own. Set these three in the shell that runs this script:
REM
REM     set HUB_SECRET_CLAUDECODE=<the claudecode secret>
REM     set HUB_SECRET_CHATGPT=<the chatgpt secret>
REM     set HUB_SECRET_GEMINI=<the gemini secret>
REM
REM Why per component rather than one HUB_SECRET: the hub takes the component
REM name from the Basic *username* and checks only the secret, so a secret that
REM is valid for two components authenticates as either one -- whichever name
REM the caller types. A worker holding a secret shared with admin could pause
REM the swarm and post messages the hub itself would attribute to Admin. The
REM four deployed components each have a distinct secret (verified with
REM hub/auth_matrix.py), which is what makes that impossible, and it stays
REM impossible only if no worker is handed a secret that is not its own.
REM
REM The launches below therefore do not simply inherit this shell's
REM environment. Each child sets HUB_SECRET from its own component variable and
REM then clears all three, so a worker process holds exactly one credential and
REM cannot read its peers'. The doubled percent signs matter: they pass the
REM variable NAME to the child, which expands it itself, so no secret value
REM ever appears on a command line where any process on this machine could read
REM it.
REM
REM Missing variables fail closed rather than falling back to a shared value,
REM but that is enforced below rather than by the child, and the difference was
REM measured rather than assumed: when a variable is not set, cmd does NOT
REM expand "%%NAME%%" to nothing -- it leaves the literal text. A worker launched
REM that way would receive HUB_SECRET set to the string "%HUB_SECRET_CHATGPT%",
REM which is not empty, passes the worker's own placeholder check, and then
REM 401s against the hub on every poll while looking like it started fine. So
REM each launch is guarded on its variable being present and is skipped loudly
REM otherwise.
if "%GEMINI_API_KEY%"=="" echo [warn] GEMINI_API_KEY not set - gemini_worker will log an error and exit.
if "%OPENAI_API_KEY%"=="" echo [warn] OPENAI_API_KEY not set - chatgpt_worker will log an error and exit.
if not "%HUB_SECRET%"=="" echo [warn] HUB_SECRET is set in this shell and is ignored - the per-component variables are used instead.

REM Chat is narration only -- no message can start work, and nothing reads the
REM narration log's contents for any decision; its one consumer counts rows for
REM `swarm_control.py status`. At the 3-second default the three workers made
REM 86,400 authenticated GET /messages per day to keep a log nobody reads
REM automatically. Sixty seconds keeps the record and the live terminal useful
REM while costing 1,440 requests per worker per day.
REM
REM Set here rather than changed in the workers, so the value is visible at the
REM point the swarm is started. Applied only when POLL_SECONDS is unset, so an
REM operator who exports a different value before running this script keeps it
REM -- a default belongs in the launcher, but overriding a deliberate choice
REM does not. Phase 1 should remove the chat poll from the workers altogether
REM once the narration count can be asked for on demand.
if "%POLL_SECONDS%"=="" set POLL_SECONDS=60

REM Each worker runs in its own window via "cmd /k" so a startup failure
REM (missing key, bad model id) stays on screen instead of the window closing
REM before you can read it. The "cd /d" above already put this shell in the
REM .bat's own folder and each child inherits that directory, so the scripts
REM are named relatively rather than through "%~dp0" -- which would have to be
REM quoted inside an already-quoted "cmd /k" string.
REM
REM Read each line as: take my own secret, forget everybody else's, then run.
if "%HUB_SECRET_CLAUDECODE%"=="" echo [error] HUB_SECRET_CLAUDECODE not set - claude_worker NOT launched.
if not "%HUB_SECRET_CLAUDECODE%"=="" start "claude_worker"  cmd /k "set HUB_SECRET=%%HUB_SECRET_CLAUDECODE%%&set HUB_SECRET_CLAUDECODE=&set HUB_SECRET_CHATGPT=&set HUB_SECRET_GEMINI=&python claude_worker.py"

if "%HUB_SECRET_CHATGPT%"=="" echo [error] HUB_SECRET_CHATGPT not set - chatgpt_worker NOT launched.
if not "%HUB_SECRET_CHATGPT%"=="" start "chatgpt_worker" cmd /k "set HUB_SECRET=%%HUB_SECRET_CHATGPT%%&set HUB_SECRET_CLAUDECODE=&set HUB_SECRET_CHATGPT=&set HUB_SECRET_GEMINI=&python chatgpt_worker.py"

if "%HUB_SECRET_GEMINI%"=="" echo [error] HUB_SECRET_GEMINI not set - gemini_worker NOT launched.
if not "%HUB_SECRET_GEMINI%"=="" start "gemini_worker"  cmd /k "set HUB_SECRET=%%HUB_SECRET_GEMINI%%&set HUB_SECRET_CLAUDECODE=&set HUB_SECRET_CHATGPT=&set HUB_SECRET_GEMINI=&python gemini_worker.py"

echo.
echo Launched every worker whose component credential was present, each in its
echo own window holding only its own secret. Any [error] line above names a
echo worker that was deliberately not started.
echo Close a window (or press Ctrl+C in it) to stop that worker.
endlocal
