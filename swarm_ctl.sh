#!/usr/bin/env bash
# One interface for the whole runtime: install, start, stop, status, pause.
#
# `worker_ctl.sh` starts one worker and is still the right tool for that. This
# starts the supervisor, which starts all three and keeps them started. The
# difference matters operationally: worker_ctl leaves you responsible for
# noticing a crash, and this does not.
#
# Credentials are fetched the same way worker_ctl fetches them -- from the
# host's own env file, at the moment they are needed -- so they never reach a
# shell history, a second file, or a transcript. The supervisor passes its
# environment to the children, so one fetch covers all three.
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${SUPERVISOR_PYTHON:-/c/Python311/python}"
CONTROL="${SWARM_CONTROL_DIR:-$REPO/control}"
LOG="${SUPERVISOR_LOG:-$CONTROL/supervisor.log}"
URL="${CONTROLLER_URL:-http://192.168.42.50:8050}"
TASK_NAME="AgentSwarmSupervisor"

pidfile() { echo "$CONTROL/supervisor.pid"; }

alive() {
  local pid="$1"
  [ -n "$pid" ] && tasklist //FI "PID eq $pid" //NH 2>/dev/null | grep -q "$pid"
}

# Whether $2 is a live process that really is $1 -- "supervisor", or a worker
# identity. `alive` answers "is something running under this number", which is
# a different question: a process that died without clearing its pid file
# leaves the number for the operating system to hand to anything, so a pid
# file is a claim about the past and not evidence about now.
#
# That gap used to reach the supervisor itself. `stop` read supervisor.pid,
# confirmed only that the number was in use, and sent `taskkill /F` -- at
# whatever had inherited it.
#
# Delegated to supervisor.py, which already has to identify a process before
# terminating one, rather than reimplemented here in shell. Two answers to one
# question is one more than can be kept right.
is_process() {
  [ -n "${2:-}" ] || return 1
  SWARM_CONTROL_DIR="$CONTROL" "$PYTHON" "$REPO/supervisor.py"     --identify "$1" "$2" >/dev/null 2>&1
}

# One component's hub credential, read from the host's env file.
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

# Every credential the three workers need, in one environment. The supervisor
# hands its own environment to each child, so this is fetched once rather than
# three times.
load_credentials() {
  export HUB_SECRET="$(fetch_secret admin)"
  [ -z "$HUB_SECRET" ] && { echo "missing: admin credential"; return 1; }

  export CHATGPT_HUB_SECRET="$(fetch_secret chatgpt)"
  export GEMINI_HUB_SECRET="$(fetch_secret gemini)"
  export CLAUDECODE_HUB_SECRET="$(fetch_secret claudecode)"

  # The narrator speaks from inside the supervisor, so this one is not passed
  # to a child -- it stays in the supervisor's own environment.
  #
  # Fetched at start like every other secret rather than stored on this host.
  # A credential in a file on OFFICEPC is a credential that outlives the
  # process holding it, survives into backups, and can be read by anything
  # running as this user; one fetched over ssh at start exists only in the
  # memory of the process that needs it.
  #
  # Absence is not fatal here. The supervisor's job is keeping workers alive,
  # and it should not refuse to do that because the room would be quiet --
  # narration itself refuses to start and says why, which is the failure an
  # operator can act on.
  export NARRATOR_HUB_SECRET="$(fetch_secret narrator)"
  [ -z "$NARRATOR_HUB_SECRET" ] && echo "warning: no narrator credential; narration will be disabled"

  export OPENAI_API_KEY="$(powershell.exe -NoProfile -Command \
    '[Environment]::GetEnvironmentVariable("OPENAI_API_KEY","User")' 2>/dev/null | tr -d '\r\n')"
  export GEMINI_API_KEY="$(powershell.exe -NoProfile -Command \
    '[Environment]::GetEnvironmentVariable("GEMINI_API_KEY","User")' 2>/dev/null | tr -d '\r\n')"

  # Which project an author resolves when it is handed a task. A name, never
  # a path: it resolves through repos.json or it does not resolve, which is
  # the check that catches a checkout repointed at another clone.
  #
  # Set here because this is the environment the supervisor hands to each
  # child, and nothing else was setting it for a supervised worker.
  # worker_ctl.sh defaults it for a worker started by hand, so the two
  # paths agreed on the value and disagreed on whether anyone applied it --
  # and an author without it blocks every task it is given, naming the
  # variable. A correct refusal, and a standing outage.
  export AUTHOR_PROJECT="${AUTHOR_PROJECT:-agenthub}"

  # Where the reviewer reads. It only reads -- rev-parse, diff, log -- so it
  # can point at the canonical checkout directly; nothing it runs touches a
  # working tree.
  #
  # The twin of AUTHOR_PROJECT above, and missing for the same reason: it was
  # set in worker_ctl.sh for a worker started by hand and nowhere on the path
  # the runtime actually starts. A reviewer without it does not review badly,
  # it returns a blocked judgment naming the variable -- so a candidate waits
  # for a verdict that is never coming, and the ledger records the task as
  # under review.
  export REVIEW_REPO="${REVIEW_REPO:-$REPO}"

  # Where an approved candidate lands, and how. All four are required by
  # claude_worker.execute_integration, which refuses before touching
  # anything if any one is missing -- the only stage that reaches a real
  # remote, so a missing value is a refusal rather than a default.
  #
  # INTEGRATION_WORK_ROOT is deliberately not the canonical checkout. The
  # integrator clones and merges there, so a merge in progress cannot
  # disturb the tree somebody is working in, and a failed one leaves
  # nothing behind to clean up by hand.
  export INTEGRATION_REPO="${INTEGRATION_REPO:-$REPO}"
  export INTEGRATION_TARGET_REF="${INTEGRATION_TARGET_REF:-refs/heads/main}"
  export INTEGRATION_REPO_SLUG="${INTEGRATION_REPO_SLUG:-Decksx/agent-swarm}"
  export INTEGRATION_WORK_ROOT="${INTEGRATION_WORK_ROOT:-C:/git/.swarm-integration}"

  # The suites the integrator requires evidence from, by check-run name.
  # Left empty, check_evidence only demands that *some* completed green
  # check exists -- which a workflow running one trivial job would satisfy
  # while proving nothing about the tests. Naming them makes a missing
  # suite a refusal rather than a silence.
  #
  # These are matched against the names integrator.ci_evidence() builds,
  # which are the GitHub job name with a "ci:" prefix, so the job
  # pytest-unit arrives as ci:pytest-unit. The prefix is not decoration
  # and omitting it is not close enough: the first real integration
  # refused with "required suite 'pytest-unit' has no evidence.
  # Supplied: ci:pytest-bypass, ci:pytest-unit" -- the same suites under
  # names that did not match.
  #
  # The part after the prefix must still match the job name in
  # .github/workflows/ci.yml exactly. Changing one without the other is a
  # refusal reading "required suite ... has no evidence".
  export INTEGRATION_REQUIRED_SUITES="${INTEGRATION_REQUIRED_SUITES:-ci:pytest-unit,ci:pytest-bypass}"

  export SWARM_CONTROL_DIR="$CONTROL"
  export CONTROLLER_URL="$URL"
  return 0
}

case "${1:-}" in
  start)
    EXISTING="$(cat "$(pidfile)" 2>/dev/null || true)"
    if is_process supervisor "$EXISTING"; then
      echo "supervisor is already running as pid $EXISTING"
      exit 0
    fi

    load_credentials || exit 1
    mkdir -p "$CONTROL"

    # Deployment parity before anything is claimed, for the same reason
    # worker_ctl checks it: a runtime started against a stale controller
    # produces evidence about a build nobody has.
    cd "$REPO"
    # Preflight authenticates as the agent it names, so it gets that agent's
    # credential rather than the supervisor's admin one. Handing it HUB_SECRET
    # as exported below would check the admin credential against the
    # claudecode component and fail with a 401 that says nothing about
    # deployment parity.
    if ! HUB_SECRET="$CLAUDECODE_HUB_SECRET"          "$PYTHON" preflight.py --url "$URL" --agent claudecode; then
      echo "not starting: preflight failed"
      exit 1
    fi

    "$PYTHON" "$REPO/supervisor.py" --url "$URL" --log "$LOG" \
      >> "$CONTROL/supervisor.out" 2>&1 &
    sleep 4

    STARTED="$(cat "$(pidfile)" 2>/dev/null || true)"
    if is_process supervisor "$STARTED"; then
      echo "supervisor started as pid $STARTED"
    else
      echo "supervisor did not take the lock; see $CONTROL/supervisor.out"
      exit 1
    fi
    ;;

  stop)
    PID="$(cat "$(pidfile)" 2>/dev/null || true)"

    # Whether the supervisor is confirmed gone. Every later step depends on
    # it: the stop request may only be withdrawn once nothing is left to act
    # on it, and the reaper may only run once nothing is left to undo its
    # work.
    GONE=0

    if ! is_process supervisor "$PID"; then
      # Either nothing is there, or the number now belongs to something else.
      # Both mean this repository's supervisor is not running, and neither is
      # a reason to aim a kill anywhere. The second is said out loud, because
      # a stale pid file that names a live stranger is worth knowing about.
      if alive "$PID"; then
        echo "supervisor is not running; $(pidfile) names pid $PID, which is"
        echo "a different process and was left alone"
      else
        echo "supervisor is not running"
      fi
      GONE=1
    else
      # A flag, not a signal. `taskkill` without /F posts WM_CLOSE, which a
      # background console process ignores, and /F terminates without running
      # any handler -- so signalling force-killed the supervisor and left all
      # three workers polling while the operator was told the swarm had
      # stopped. The supervisor polls for this file and shuts its children
      # down itself, which is the only path that actually stops them.
      mkdir -p "$CONTROL"
      echo "stop requested by swarm_ctl at $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "$CONTROL/STOPPING"

      for _ in $(seq 1 45); do
        alive "$PID" || break
        sleep 1
      done

      # Identity again, not just liveness. The wait above polls the cheap
      # question once a second; this is the expensive one, asked at the only
      # moment it decides anything. If the supervisor exited during those 45
      # seconds and its number was reissued, what is alive now is a stranger,
      # and the supervisor is gone either way.
      if ! is_process supervisor "$PID"; then
        GONE=1
        echo "supervisor stopped (pid $PID)"
      else
        echo "supervisor did not stop on request; killing it"
        taskkill //PID "$PID" //F >/dev/null 2>&1

        # Checked, not assumed. `taskkill` can fail -- a process owned by
        # another user, or one the system refuses to terminate -- and it says
        # so on streams this discarded, so the script went on to announce a
        # stop that had not happened. Its exit status is not enough either: it
        # reports that the request was accepted, and termination is
        # asynchronous. The question is whether the pid is still there.
        for _ in $(seq 1 15); do
          alive "$PID" || break
          sleep 1
        done

        if is_process supervisor "$PID"; then
          echo "supervisor (pid $PID) survived taskkill /F"
        else
          GONE=1
          echo "supervisor stopped (pid $PID)"
        fi
      fi
    fi

    if [ "$GONE" -ne 1 ]; then
      # STOPPING stays engaged. Removing it withdrew the shutdown request from
      # a supervisor that may still be reading it, which does not merely fail
      # to stop the swarm -- it restarts it, because a supervisor that resumes
      # ticking spawns a replacement for every worker anything else has just
      # stopped.
      #
      # And no reap, for the same reason. Reaping beside a live supervisor is
      # a race against the process whose whole purpose is to put those workers
      # back, so the honest outcome is to stop here and say why.
      echo "stop failed: the supervisor is still running, so its workers were"
      echo "not touched and the stop request is left engaged. Kill pid $PID by"
      echo "hand, then run stop again."
      exit 1
    fi

    # Withdrawn only now. Nothing is left to read it, and leaving it would
    # stop the next supervisor the moment it started.
    rm -f "$CONTROL/STOPPING"

    # Run whether or not a supervisor was found, because the case that leaves
    # workers behind is exactly the case where one is not: a supervisor that
    # had to be force-killed never ran its own shutdown, so its children
    # outlived it as orphans still holding the identity locks.
    #
    # Delegated to supervisor.py rather than done here with taskkill. This
    # script used to kill whatever pid each lock file named, and a lock file
    # names a pid that was a worker when it was written -- pids are reused, so
    # that is a force-kill aimed by a number which may since have become
    # something else entirely. --reap confirms the process really is that
    # identity's worker before terminating it, on the same evidence the
    # supervisor's own shutdown uses.
    SWARM_CONTROL_DIR="$CONTROL" "$PYTHON" "$REPO/supervisor.py" --reap
    REAPED=$?

    # Whatever the supervisor did or did not manage, the operator asked for
    # zero workers. Reported rather than assumed.
    REMAINING="$(powershell.exe -NoProfile -Command \
      "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match '_worker' }).Count" \
      2>/dev/null | tr -d '\r\n ')"
    echo "workers still running: ${REMAINING:-unknown}"

    # Nonzero unless the count is a confirmed zero, unknown included. This
    # printed a nonzero count and still exited successfully, so every caller
    # that read the exit status rather than the text was told the swarm had
    # stopped while workers were still polling. An unverifiable count is not a
    # success either: "cannot tell" and "none left" are different answers, and
    # only one of them means the operator got what they asked for.
    if [ "${REMAINING:-unknown}" != "0" ] || [ "$REAPED" -ne 0 ]; then
      echo "stop did not reach zero workers"
      exit 1
    fi
    ;;

  status)
    PID="$(cat "$(pidfile)" 2>/dev/null || true)"
    if is_process supervisor "$PID"; then
      echo "supervisor: running (pid $PID)"
    else
      echo "supervisor: not running"
    fi

    if [ -f "$CONTROL/PAUSED" ]; then
      echo "pause     : ENGAGED -- $(cat "$CONTROL/PAUSED" 2>/dev/null | head -c 200)"
    else
      echo "pause     : running"
    fi

    # Identity rather than liveness here too. A lock left by a worker that
    # crashed names a number the host may have reissued, and reporting that as
    # a running worker is how an operator concludes the swarm is up.
    for identity in chatgpt gemini claudecode; do
      WPID="$(cat "$CONTROL/${identity}.pid" 2>/dev/null || true)"
      if is_process "$identity" "$WPID"; then
        echo "  $identity: running (pid $WPID)"
      else
        echo "  $identity: not running"
      fi
    done

    echo "--- last 12 log lines ---"
    tail -n 12 "$LOG" 2>/dev/null || echo "(no log yet)"
    ;;

  pause)
    mkdir -p "$CONTROL"
    shift
    echo "${*:-paused by swarm_ctl}" > "$CONTROL/PAUSED"
    echo "paused. The supervisor stays up and stops claiming and advancing."
    ;;

  resume)
    rm -f "$CONTROL/PAUSED"
    echo "resumed. No restart needed."
    ;;

  install)
    # A scheduled task rather than a service: this runs as the logged-in user
    # because the workers need that user's API keys from the user environment,
    # and a service running as SYSTEM would not have them.
    load_credentials || exit 1
    powershell.exe -NoProfile -Command "
      \$action = New-ScheduledTaskAction -Execute 'C:\\Program Files\\Git\\bin\\bash.exe' \
        -Argument '-lc \"$REPO/swarm_ctl.sh start\"'
      \$trigger = New-ScheduledTaskTrigger -AtLogOn
      \$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries \
        -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 \
        -RestartInterval (New-TimeSpan -Minutes 5)
      Register-ScheduledTask -TaskName '$TASK_NAME' -Action \$action \
        -Trigger \$trigger -Settings \$settings -Force | Out-Null
      Write-Output 'registered $TASK_NAME (at logon)'
    "
    ;;

  uninstall)
    powershell.exe -NoProfile -Command "
      Unregister-ScheduledTask -TaskName '$TASK_NAME' -Confirm:\$false
      Write-Output 'removed $TASK_NAME'
    " 2>/dev/null || echo "no scheduled task to remove"
    ;;

  *)
    echo "usage: swarm_ctl.sh {start|stop|status|pause [reason]|resume|install|uninstall}"
    exit 2 ;;
esac
