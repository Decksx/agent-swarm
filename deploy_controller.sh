#!/usr/bin/env bash
# Put this checkout on Tower and prove the hub is running it.
#
# The deploy used to be a sequence of remembered steps -- copy eight files,
# check the digests, recreate the container, remember to run the preflight --
# and two live runs were spent against a controller that had missed one of
# them. A remembered sequence is not a procedure; this is the procedure.
#
# It refuses more often than it runs:
#
#   * if the files it would deploy differ from HEAD, because a deployed build
#     that corresponds to no commit cannot be gone back to, and every piece of
#     evidence produced against it names a build nobody can reconstruct;
#   * if any file arrives on the host with a different digest than it left
#     with, because a partial copy is the failure that looks most like success;
#   * if the required test suites do not pass, checked here rather than by
#     an operator running pytest beforehand and reading the result. A suite
#     was once run as `pytest | tail`, which reports the exit status of tail;
#     the failures scrolled past, the status was 0, and the deploy went out.
#     A gate a person performs is a gate that is sometimes not performed, and
#     one that reads a verdict through a pipe is worse than none at all
#     because it produces a green line either way;
#   * if the hub does not come back up;
#   * if the preflight does not go green afterwards, which is the only
#     statement that means anything -- the copy having "worked" is not
#     evidence that the process is running what was copied.
#
# There is no flag to skip the tests. --allow-uncommitted exists because an
# operator can knowingly deploy an experiment and discount the evidence from
# it; there is no equivalent reading of "deployed with failing tests", and a
# bypass that exists is a bypass that gets used at the moment it matters most.
#
# The restart is the point, not an afterthought. Copying files into a running
# container's mount changes what is on disk and nothing about what is loaded;
# the controller reports both, and this waits for them to agree.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST=tower.local
APP=/mnt/user/appdata/agent-swarm/app
CONTAINER=agent-hub
HUB_URL="http://192.168.42.50:8050"
PYTHON="${DEPLOY_PYTHON:-python}"

ALLOW_UNCOMMITTED=0
TESTS_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --allow-uncommitted)
      ALLOW_UNCOMMITTED=1 ;;
    # Runs the gate and stops. Not a bypass -- the opposite of one: it is how
    # the gate gets run without a deploy attached, so failing it is cheap.
    --tests-only)
      TESTS_ONLY=1 ;;
    -h|--help)
      echo "usage: deploy_controller.sh [--allow-uncommitted] [--tests-only]"
      exit 0 ;;
    *)
      echo "deploy: unknown argument $arg"; exit 2 ;;
  esac
done

cd "$REPO"

# --- What would be deployed -------------------------------------------------

FILES=(hub/hub.py)
while IFS= read -r f; do FILES+=("$f"); done < <(ls controller/*.py | sort)

echo "deploy: ${#FILES[@]} files from $REPO"

DIRTY="$(git status --porcelain -- "${FILES[@]}")"

if [ -n "$DIRTY" ]; then
  echo "$DIRTY" | sed 's/^/  uncommitted: /'

  # --tests-only deploys nothing, so it has no build to correspond to a
  # commit and nothing to roll back. Refusing it for a dirty tree would make
  # the cheap way to run the gate the one that needs a flag named "and do not
  # trust the result", which is how people stop running it.
  if [ "$ALLOW_UNCOMMITTED" -eq 0 ] && [ "$TESTS_ONLY" -eq 0 ]; then
    echo "deploy: refusing. These files differ from HEAD, so the deployed"
    echo "        build would correspond to no commit -- there would be"
    echo "        nothing to roll back to and nothing to reproduce it from."
    echo "        Commit them, or pass --allow-uncommitted and do not treat"
    echo "        anything the hub produces afterwards as evidence."
    exit 1
  fi

  echo "deploy: continuing with uncommitted files (--allow-uncommitted)"
fi

COMMIT="$(git rev-parse HEAD)"

# The path is not passed in. `$REPO` is an MSYS path (/c/git/...) and Windows
# Python cannot resolve it, so from_repository found no files and returned the
# SHA-256 of the empty string -- a perfectly plausible-looking digest of
# nothing. The count is printed and checked for the same reason: an empty
# manifest has a stable id, so a broken discovery produces a value that
# compares equal to any other broken discovery.
read -r EXPECTED FOUND <<< "$($PYTHON -c "
from controller import build
described = build.from_repository('.')
print(described['build_id'], len(described['files']))
")"

echo "deploy: commit   $COMMIT"
echo "deploy: build id ${EXPECTED:0:12} over $FOUND files"

if [ "$FOUND" -ne "${#FILES[@]}" ]; then
  echo "deploy: FAIL the build manifest has $FOUND files; ${#FILES[@]} are being"
  echo "        deployed. Something is not finding the files it is describing,"
  echo "        and its id describes whatever it did find."
  exit 1
fi

# --- The gate: the suites, before anything leaves this machine --------------
#
# Every verdict below is an exit status read directly from the command that
# produced it. Nothing is piped: `pytest | tail` reports tail's status, which
# is 0 whether the suite passed or burned, and that is the incident this
# exists because of. Output goes to a file, the status comes from `$?`, and
# the file is shown afterwards -- so what is displayed and what is decided on
# are produced by two separate steps and the display cannot change the answer.
#
# Both suites are named as directories, and the count check below is what makes
# that safe. A gate that runs "whatever tests it finds" passes when it finds
# none -- finding none is the exact shape of a broken invocation -- so naming
# files individually was the first instinct. It is the wrong one: a hub test
# file added later would then be silently ungated, and nothing would say so.
# Naming the directory means new tests are gated the day they are written, and
# the "no passing tests" refusal covers the case the naming was protecting
# against.

SUITE_NAMES=(
  "controller, workers and planning"
  "hub and controller HTTP surface"
)
SUITE_ARGS=(
  "tests"
  "hub"
)

LOGDIR="$(mktemp -d)"
trap 'rm -rf "$LOGDIR"' EXIT

# The interpreter that runs the suites is the same one that built the manifest
# above. Two interpreters would mean the tests could pass under one while the
# build id described what the other would import.
if ! "$PYTHON" -c "import pytest" 2>/dev/null; then
  echo "deploy: FAIL $PYTHON has no pytest, so the required suites cannot run."
  echo "        Not skipped: a suite that did not run is not a suite that"
  echo "        passed, and this is the one place that difference decides"
  echo "        whether a build ships. Point DEPLOY_PYTHON at an interpreter"
  echo "        with pytest, fastapi, httpx and tzdata installed."
  exit 1
fi

FAILED=0

for i in "${!SUITE_NAMES[@]}"; do
  name="${SUITE_NAMES[$i]}"
  log="$LOGDIR/suite-$i.log"

  echo "deploy: running suite -- $name"

  # `|| status=$?` rather than `set -e`: a failing suite is a result to report,
  # not a reason to abort before the other suite has been run. An operator
  # seeing one failure wants to know whether the other one also failed.
  status=0
  "$PYTHON" -m pytest ${SUITE_ARGS[$i]} -q > "$log" 2>&1 || status=$?

  # A summary line, for the log. Read after the status, and never instead of
  # it -- this is the pipe that started all this, kept only where it decides
  # nothing.
  summary="$(tail -n 1 "$log" | tr -d '\r')"

  if [ "$status" -ne 0 ]; then
    echo "deploy: FAIL $name (pytest exit $status)"
    echo "$summary" | sed 's/^/        /'
    tail -n 25 "$log" | sed 's/^/        /'
    FAILED=1
    continue
  fi

  # Exit 0 with nothing run. pytest exits 5 for "no tests collected", which
  # the status catches, but a suite whose every test was skipped -- a missing
  # optional dependency, a platform marker -- exits 0 and reports success
  # having verified nothing. "No failures" and "no tests" render almost
  # identically and only one of them is evidence.
  if ! echo "$summary" | grep -Eq '[0-9]+ passed'; then
    echo "deploy: FAIL $name exited 0 but reports no passing tests."
    echo "        \"nothing failed\" is not \"something passed\"."
    echo "$summary" | sed 's/^/        /'
    FAILED=1
    continue
  fi

  echo "deploy: ok   $summary"
done

if [ "$FAILED" -ne 0 ]; then
  echo
  echo "deploy: refusing. The required suites did not pass, and there is no"
  echo "        flag here to say they may be ignored. Fix them, or deploy"
  echo "        the commit that last passed them."
  exit 1
fi

echo "deploy: all ${#SUITE_NAMES[@]} required suites passed"

if [ "$TESTS_ONLY" -eq 1 ]; then
  echo "deploy: --tests-only, so stopping before the copy"
  exit 0
fi

# --- Copy, then prove the copy ----------------------------------------------

echo "deploy: copying to $HOST:$APP"
scp -q hub/hub.py "$HOST:$APP/hub.py"
scp -q controller/*.py "$HOST:$APP/controller/"

# Digests are compared per file rather than trusting scp's exit status. A
# truncated or half-written file is the failure that most resembles success,
# and the build id alone would say only that something differs.
LOCAL="$(
  for f in "${FILES[@]}"; do
    name="$(basename "$f")"
    case "$f" in
      hub/hub.py)  printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "hub.py" ;;
      *)           printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "controller/$name" ;;
    esac
  done | sort -k2
)"

REMOTE="$(ssh "$HOST" "cd $APP && sha256sum hub.py controller/*.py" \
          | awk '{print $1 "  " $2}' | sort -k2)"

if [ "$LOCAL" != "$REMOTE" ]; then
  echo "deploy: FAIL the files on the host are not the files that were sent"
  diff <(echo "$LOCAL") <(echo "$REMOTE") | sed 's/^/  /' || true
  exit 1
fi

echo "deploy: all ${#FILES[@]} digests match on the host"

# --- Restart, because copying changes the disk and not the process ----------
#
# `docker restart` rather than stop/rm/run: nothing about the container's
# shape is changing here, and the documented recreate exists for the case
# where it is. It does not reload --env-file, which this does not need.

echo "deploy: restarting $CONTAINER"
ssh "$HOST" "docker restart $CONTAINER" > /dev/null

for _ in $(seq 1 30); do
  code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$HUB_URL/controller/status" || true)"
  # 401 means the app is up and authenticating; anything is better than 000.
  if [ "$code" = "401" ] || [ "$code" = "200" ]; then break; fi
  sleep 2
done

if [ "$code" != "401" ] && [ "$code" != "200" ]; then
  echo "deploy: FAIL the hub did not answer after the restart (last code: $code)"
  ssh "$HOST" "docker logs --tail 20 $CONTAINER" 2>&1 | sed 's/^/  /' || true
  exit 1
fi

echo "deploy: the hub is answering"

# --- The only statement that means anything ---------------------------------

echo
# The interpreter is passed, not assumed.
#
# `worker_ctl.sh` chooses its own python when nobody tells it which one,
# and a `WORKER_PYTHON` sitting in the operator's environment would win.
# The suites above ran under $PYTHON; a closing check under a different
# interpreter is measuring a different installation than the one this
# deploy validated, which is the drift the check exists to catch.
DEPLOY_PYTHON="$PYTHON" "$REPO/worker_ctl.sh" preflight claudecode
