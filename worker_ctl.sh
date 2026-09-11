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

# The checkout this script belongs to, not a checkout named in advance.
#
# This was `/c/git/claude-agent-hub`, written out. Everything below `cd`s here
# before running anything, so every action ran against that one directory
# however the script had been invoked -- and `deploy_controller.sh`, which
# derives its own repository from `BASH_SOURCE` and copies from it correctly,
# handed its closing parity check to this script and got an answer about a
# different tree. A deploy from a worktree copied the right files, matched
# every digest, and then reported the build of `main`.
#
# `start` had the same defect with a worse outcome: a worker launched from a
# worktree would run `main`'s script and review `main`'s code, while the
# operator believed they were exercising the checkout they were standing in.
#
# Derived the way `swarm_ctl.sh` and `deploy_controller.sh` already derive
# theirs, so all three agree on what "this checkout" means.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The interpreter, chosen once and used for every python this script runs.
#
# Precedence, narrowest context first:
#
#   DEPLOY_PYTHON  set by `deploy_controller.sh` for the duration of one
#                  deploy. It wins because the deploy validated its suites
#                  with that interpreter and its closing parity check has to
#                  be the same one -- a persistent WORKER_PYTHON in the
#                  operator's environment must not quietly redirect it.
#   WORKER_PYTHON  the standalone override, for running this script by hand
#                  against a particular interpreter.
#   python         whatever is first on PATH, which is what this did before
#                  and stays the default so no existing invocation changes.
PYTHON="${DEPLOY_PYTHON:-${WORKER_PYTHON:-python}}"
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

# The hub credential for one component, read from the host's env file. Kept
# here rather than in a shell variable an operator has to remember to set: the
# secret that matters is the one the worker will actually present, and reading
# it from the same place the hub reads it means a preflight that passes is
# evidence about that credential and not about a copy of it.
fetch_secret() {
  ssh -o BatchMode=yes -o ConnectTimeout=20 tower.local "python3 -c \"
import io
for line in io.open('/mnt/user/appdata/agent-swarm/hub.env', encoding='utf-8'):
    line = line.strip()
    if line.startswith('HUB_CREDENTIALS='):
        raw = line.split('=', 1)[1].strip().strip(chr(34)).strip(chr(39))
        for entry in raw.split(','):
            name, _, secret = entry.strip().partition(':')
            if name.strip().lower() == '$1':
                print(secret.strip(), end='')
\"" 2>/dev/null
}

case "$ACTION" in
  preflight)
    # Deployment parity on its own, without starting a worker. The check is
    # worth running after every deploy and before every run, and tying it to
    # launching a process meant it was only ever run when something was about
    # to be started.
    case "$IDENT" in
      claudecode|gemini|chatgpt) COMPONENT="$IDENT" ;;
      *) echo "usage: worker_ctl.sh preflight {claudecode|gemini|chatgpt}"; exit 2 ;;
    esac

    HUB_SECRET="$(fetch_secret "$COMPONENT")"
    if [ -z "$HUB_SECRET" ]; then echo "missing: hub credential for $COMPONENT"; exit 1; fi
    export HUB_SECRET

    cd "$REPO"
    shift 2
    "$PYTHON" preflight.py --url "http://192.168.42.50:8050" --agent "$COMPONENT" "$@"
    ;;

  admin)
    # controller_admin against the live hub, from this machine. The admin
    # credential is fetched the same way the workers' are and handed over in
    # the environment, so it never reaches a shell history, a second file, or
    # a transcript. Everything after `admin` is passed through.
    HUB_SECRET="$(fetch_secret admin)"
    if [ -z "$HUB_SECRET" ]; then echo "missing: hub credential for admin"; exit 1; fi
    export HUB_SECRET

    cd "$REPO"
    shift
    "$PYTHON" hub/controller_admin.py --url "http://192.168.42.50:8050" "$@"
    ;;

  start)
    case "$IDENT" in
      claudecode) SCRIPT=claude_worker.py; COMPONENT=claudecode ;;
      gemini)     SCRIPT=gemini_worker.py; COMPONENT=gemini ;;
      chatgpt)    SCRIPT=chatgpt_worker.py; COMPONENT=chatgpt ;;
      *) echo "usage: worker_ctl.sh start {claudecode|gemini|chatgpt}"; exit 2 ;;
    esac

    HUB_SECRET="$(fetch_secret "$COMPONENT")"

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
    # The registered project this host authors for, by name. Not a path: a
    # path is how a snapshot came to describe the wrong checkout, and the
    # worker resolves the name through repos.json and works in a private
    # worktree at the task's own base_sha.
    export AUTHOR_PROJECT="${AUTHOR_PROJECT:-agenthub}"
    # The reviewer only reads -- rev-parse, diff, log -- so it can point at
    # the canonical checkout directly. Nothing it runs touches a working tree.
    if [ "$IDENT" = "gemini" ]; then export REVIEW_REPO="${REVIEW_REPO_OVERRIDE:-$REPO}"; fi
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
    if ! "$PYTHON" preflight.py --url "http://192.168.42.50:8050" --agent "$COMPONENT"; then
      echo "not starting $IDENT: preflight failed"
      exit 1
    fi

    # No exec: the child stays a child so its pid is recordable and killable.
    "$PYTHON" "$SCRIPT" >> "$SCRATCH/${IDENT}.launcher.out" 2>&1 &
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
    echo "usage: worker_ctl.sh {start|stop|count|preflight|admin} ..."
    exit 2 ;;
esac
