# Deploying Phase 0 hub authentication

Ordered procedure with a rollback at every step. Read it through before
starting — one step changes container configuration, and getting it wrong makes
the hub refuse to start (deliberately).

**Nothing is running right now.** The workers were stopped on 2026-09-03 and
`gemini_lead.py` is not running either, so there is no cutover race and no
window where half the system is authenticated. This is the cheapest moment to
do it.

---

## 0. Before you start

Everything below assumes:

- `hub/hub.py` in this repository is the version to deploy — the tested one,
  not `hub/main.py`, which is a stale in-memory build that would silently
  discard `chat.db`.
- The baseline of the file as it runs today is committed at `5b1eed4`, so a
  rollback is `git show 5b1eed4:hub/hub.py`.

## 1. Generate the credentials

On Tower, in your own shell. **Do not paste the output anywhere, including to
me** — I do not need the values and should not have them.

```sh
for name in admin claudecode chatgpt gemini; do
  printf '%s:%s\n' "$name" "$(openssl rand -hex 24)"
done
```

That prints four `name:secret` lines. `HUB_CREDENTIALS` is those lines joined by
commas, on one line:

```text
admin:<secret>,claudecode:<secret>,chatgpt:<secret>,gemini:<secret>
```

Keep `admin` for yourself and the browser UI. Each worker gets its own.

Only `admin` and `operator` may pause or resume. A worker credential lives on
the execution host, so if holding one were enough to lift a pause, the pause
would not be an operator control.

## 2. Put `HUB_CREDENTIALS` on the container

The container has no application environment variables today, so this is a
configuration change, not a file copy. It is the step that cannot be done from
this repository.

**Via the unraid UI:** Docker → `agent-hub` → Edit → Add another Path, Port,
Variable… → *Variable*, Key `HUB_CREDENTIALS`, Value the string from step 1.
Apply.

**Or via compose,** if you manage it that way — `hub/docker-compose.yml` is a
copy of the deployed definition and does not currently declare an environment
block:

```yaml
    environment:
      - HUB_CREDENTIALS=admin:<secret>,claudecode:<secret>,chatgpt:<secret>,gemini:<secret>
```

Applying from the UI restarts the container. **It will fail to start**, because
the current `hub.py` does not read that variable and the new one is not deployed
yet — that is harmless and expected; step 3 fixes it. If you would rather not
see a failed container at all, do step 3 first and step 2 second.

## 3. Deploy `hub.py`

From this repository, with the working tree clean:

```sh
# keep the current live file as a local rollback copy first
ssh root@tower "cp /mnt/user/appdata/agent-swarm/hub.py /mnt/user/appdata/agent-swarm/hub.py.pre-auth"

scp hub/hub.py root@tower:/mnt/user/appdata/agent-swarm/hub.py
ssh root@tower "docker restart agent-hub"
```

Give it ~20 seconds: the container `pip install`s FastAPI on every start.

## 4. Verify before trusting it

```sh
# unauthenticated -> 401 on every route
for p in / /messages /control/status; do
  printf '%s -> ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' "http://192.168.42.50:8050$p"
done

# the documentation routes are gone -> 404
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.42.50:8050/openapi.json

# authenticated -> 200
curl -s -o /dev/null -w '%{http_code}\n' -u admin:<secret> \
  http://192.168.42.50:8050/control/status
```

Expected: `401 401 401`, then `404`, then `200`.

**If any route answers 200 without credentials, stop and roll back.** That is
the one outcome this whole change exists to prevent.

If the container is restarting in a loop, that is the fail-closed path working:
`docker logs agent-hub --tail 20` will name `HUB_CREDENTIALS`. It means the
variable is missing or malformed, not that the hub is broken. The log will not
contain the value.

## 5. Point the workers at it

On OFFICEPC, in the shell that launches the workers — each worker uses its own
component secret, and its identity is its own name:

```powershell
$env:HUB_SECRET = "<the claudecode secret>"   # for claude_worker
```

Because the Basic username is the worker's bound identity, each worker needs
the secret matching its own name. The simplest arrangement is one shell per
worker, which `start_workers.bat` already gives you (each opens its own window),
or `setx` per component if you prefer them persisted.

A worker started without `HUB_SECRET` exits 1 immediately rather than polling
and 401-ing forever.

## 6. Rollback

At any point, and it is cheap because `hub.py` is a single-file bind mount:

```sh
ssh root@tower "cp /mnt/user/appdata/agent-swarm/hub.py.pre-auth /mnt/user/appdata/agent-swarm/hub.py && docker restart agent-hub"
```

Or from this repository: `git show 5b1eed4:hub/hub.py > /tmp/hub.py` and copy
that up. Removing `HUB_CREDENTIALS` is not required for rollback — the old file
ignores it.

Rolling back returns the hub to being readable and writable by anything on the
LAN. The workers stay contained either way: their containment is local and does
not depend on the hub.

---

## What this does not do

Authentication protects the hub from the network. It does not make chat
authoritative again, and nothing in this deployment changes worker activation:
work still comes only from the local control directory on OFFICEPC.

Restoring Admin-over-chat is now *possible* — with `sender` derived from a
credential, "this came from Admin" finally means something — but it is a
deliberate Phase 1 decision, not a side effect of this deployment.

`gemini_lead.py` has no credential and will 401 if started. Leave it stopped;
see `hub/PROVENANCE.md`.
