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
#   * if the hub does not come back up;
#   * if the preflight does not go green afterwards, which is the only
#     statement that means anything -- the copy having "worked" is not
#     evidence that the process is running what was copied.
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

for arg in "$@"; do
  case "$arg" in
    --allow-uncommitted)
      ALLOW_UNCOMMITTED=1 ;;
    -h|--help)
      echo "usage: deploy_controller.sh [--allow-uncommitted]"
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

  if [ "$ALLOW_UNCOMMITTED" -eq 0 ]; then
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
"$REPO/worker_ctl.sh" preflight claudecode
