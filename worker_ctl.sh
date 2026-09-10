#!/usr/bin/env bash
# Start or stop one worker, managing the actual python process.
#
# The earlier launchers used `exec python`, which replaces the shell -- so the
# supervisor's idea of "the task" and the process actually doing the work were
# the same pid only by luck, and killing the task left four python processes
# alive on 2026-09-09.
#
# Stopping reads the worker's OWN lock file, which the worker writes from
# inside python with os.getpid(). The shell's $! is not usable here: under Git
# Bash it returns a bash-internal pid -- 1601 where the real Windows pid was
# 28096 -- so a stop built on it silently matches nothing, which is how four
# processes survived in the first place.
#
# The lock is also the second line of defence: even if this script is bypassed
# entirely, a second worker for the same identity refuses to start.
set -u

SCRATCH="/c/Users/david/AppData/Local/Temp/claude/C--git-ComicAutomation/79c29907-5e10-4e70-81df-064f20d57600/scratchpad"
REPO=/c/git/claude-agent-hub
ACTION="${1:-}"
IDENT="${2:-}"

# The worker records its own Windows pid here on startup.
pidfile() { echo "$SCRATCH/swarm_control/${1}.pid"; }

alive() {
  local pid="$1"
  [ -n "$pid" ] && tasklist //FI "PID eq $pid" //NH 2>/dev/null | grep -q "$pid"
}

count_workers() {
  powershell.exe -NoProfile -Command \
    "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match '${1}_worker' }).Count" \
    2>/dev/null | tr -d '\r\n '
}

case "$ACTION" in
  start)
    case "$IDENT" in
      claudecode) SCRIPT=claude_worker.py; COMPONENT=claudecode ;;
      gemini)     SCRIPT=gemini_worker.py; COMPONENT=gemini ;;
      chatgpt)    SCRIPT=chatgpt_worker.py; COMPONENT=chatgpt ;;
      *) echo "usage: worker_ctl.sh start {claudecode|gemini|chatgpt}"; exit 2 ;;
    esac

    HUB_SECRET="$(ssh -o BatchMode=yes -o ConnectTimeout=20 tower.local "python3 -c \"
import io
for line in io.open('/mnt/user/appdata/agent-swarm/hub.env', encoding='utf-8'):
    line = line.strip()
    if line.startswith('HUB_CREDENTIALS='):
        raw = line.split('=', 1)[1].strip().strip(chr(34)).strip(chr(39))
        for entry in raw.split(','):
            name, _, secret = entry.strip().partition(':')
            if name.strip().lower() == '$COMPONENT':
                print(secret.strip(), end='')
\"" 2>/dev/null)"

    if [ -z "$HUB_SECRET" ]; then echo "missing: hub credential for $COMPONENT"; exit 1; fi
    export HUB_SECRET

    if [ "$IDENT" = "gemini" ]; then
      export GEMINI_API_KEY="$(powershell.exe -NoProfile -Command '[Environment]::GetEnvironmentVariable("GEMINI_API_KEY","User")' 2>/dev/null | tr -d '\r\n')"
      [ -z "$GEMINI_API_KEY" ] && { echo "missing: GEMINI_API_KEY"; exit 1; }
    fi
    if [ "$IDENT" = "chatgpt" ]; then
      export OPENAI_API_KEY="$(powershell.exe -NoProfile -Command '[Environment]::GetEnvironmentVariable("OPENAI_API_KEY","User")' 2>/dev/null | tr -d '\r\n')"
      [ -z "$OPENAI_API_KEY" ] && { echo "missing: OPENAI_API_KEY"; exit 1; }
    fi

    export ACTIVATION_SOURCE=controller
    export AGENT_IDENTITY="$IDENT"
    export WORKSPACE="$SCRATCH/mvp_workspace"
    export REVIEW_REPO="$SCRATCH/mvp_workspace"
    # ChatGPT authors in its own checkout, so its demonstration cannot be
    # confused with the claude/gemini one.
    export AUTHOR_REPO="$SCRATCH/chatgpt_workspace"
    if [ "$IDENT" = "gemini" ]; then export REVIEW_REPO="$SCRATCH/chatgpt_workspace"; fi
    export POLL_SECONDS=5
    export TASK_TIMEOUT=600
    export SWARM_CONTROL_DIR="$SCRATCH/swarm_control"

    # Checked before launching, so the message can tell "started" from
    # "already running". Reporting the existing pid as if we had started it is
    # how an operator ends up believing a second worker is live.
    EXISTING="$(cat "$(pidfile "$IDENT")" 2>/dev/null || true)"
    if alive "$EXISTING"; then
      echo "$IDENT is already running as pid $EXISTING; not starting another"
      exit 0
    fi

    cd "$REPO"

    # Deployment parity, before anything is claimed. A worker started against
    # a stale controller produces evidence about a build nobody has, and that
    # evidence looks valid -- which is worse than not running.
    if ! python preflight.py --url "http://192.168.42.50:8050" --agent "$COMPONENT"; then
      echo "not starting $IDENT: preflight failed"
      exit 1
    fi

    # No exec: the child stays a child so its pid is recordable and killable.
    python "$SCRIPT" >> "$SCRATCH/${IDENT}.launcher.out" 2>&1 &
    # Deliberately not recording $! -- see the note at the top. The worker
    # writes its own pid to the lock file, and that is the one that is real.
    sleep 4
    STARTED="$(cat "$(pidfile "$IDENT")" 2>/dev/null || true)"
    if alive "$STARTED"; then
      echo "started $IDENT as pid $STARTED"
    else
      echo "$IDENT did not take the lock; see $SCRATCH/${IDENT}.launcher.out"
    fi
    ;;

  stop)
    PID="$(cat "$(pidfile "$IDENT")" 2>/dev/null || true)"
    if alive "$PID"; then
      taskkill //PID "$PID" //F >/dev/null 2>&1 || kill -9 "$PID" 2>/dev/null || true
      echo "stopped $IDENT (pid $PID)"
    else
      echo "$IDENT is not running"
    fi
    rm -f "$(pidfile "$IDENT")"
    ;;

  count)
    # Counted by inspecting the process table, not by trusting a pid file.
    # The whole point is to notice processes nothing is tracking.
    powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match '${IDENT%code}_worker' }).Count" 2>/dev/null | tr -d '
'
    ;;

  *)
    echo "usage: worker_ctl.sh {start|stop|count} {claudecode|gemini|chatgpt}"
    exit 2 ;;
esac
