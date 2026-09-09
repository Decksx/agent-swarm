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

Applying restarts the container, and **it starts normally**. The `hub.py`
running today does not read `HUB_CREDENTIALS` and ignores it like any other
unknown variable, so the hub keeps serving unauthenticated until step 3 — no
outage, no failed container.

That is why this step goes first. Doing it in this order means there is never a
moment where the authenticated `hub.py` is deployed without a credential to
read, which is the one combination that does stop the container.

An earlier draft of this document claimed the container would fail here. It was
wrong, and the correction matters because it changes the safe ordering.

## 3. Deploy `hub.py` and recreate the container

**Unraid has no `docker compose` subcommand**, and `docker restart` does not
pick up a new `env_file` or `--env-file`. The container has to be recreated.

```sh
cd /mnt/user/appdata/agent-swarm
cp hub.py hub.py.pre-auth
cp /path/to/hub_authenticated.py hub.py
sha256sum hub.py          # compare against the repository copy before restarting

if command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d
else
  docker stop agent-hub && docker rm agent-hub
  docker run -d     --name agent-hub     --restart unless-stopped     --env-file /mnt/user/appdata/agent-swarm/hub.env     -p 8050:8050     -v /mnt/user/appdata/agent-swarm/data:/data     -v /mnt/user/appdata/agent-swarm/hub.py:/app/hub.py     -w /app     python:3.11-slim     sh -c "pip install fastapi uvicorn pydantic && uvicorn hub:app --host 0.0.0.0 --port 8050"
fi
```

`docker rm` discards nothing: both volumes are bind mounts onto the array, so
`chat.db` and `hub.py` are not in the container layer. Every flag above is taken
from `docker inspect` of the container as it ran; the only addition is
`--env-file`.

Give it ~30 seconds — the container `pip install`s FastAPI on every start.
`docker logs agent-hub --tail 8` should end at `Uvicorn running on
http://0.0.0.0:8050`.

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

`GET /control/pause` answers **405**, not 401. FastAPI matches the method before
it runs the dependency, so a wrong-method request is rejected before
authentication. It reveals that the route exists and nothing else; a `POST`
without a credential is a 401.

**If any route answers 200 without credentials, stop and roll back.** That is
the one outcome this whole change exists to prevent.

If the container is restarting in a loop, that is the fail-closed path working:
`docker logs agent-hub --tail 20` will name `HUB_CREDENTIALS`. It means the
variable is missing or malformed, not that the hub is broken. The log will not
contain the value.

## 5. Point the workers at it

On OFFICEPC, in the shell that launches the workers — set one variable per
component, not one shared `HUB_SECRET`:

```powershell
$env:HUB_SECRET_CLAUDECODE = "<the claudecode secret>"
$env:HUB_SECRET_CHATGPT    = "<the chatgpt secret>"
$env:HUB_SECRET_GEMINI     = "<the gemini secret>"
```

`start_workers.bat` gives each worker `HUB_SECRET` from its own variable and
clears all three in the child, so a worker process holds exactly one credential
and cannot read its peers'. A component whose variable is missing is not
launched at all, and the launcher says which one and why.

A worker started without `HUB_SECRET` exits 1 immediately rather than polling
and 401-ing forever.

> **Corrected 2026-09-09.** This section previously showed a single
> `$env:HUB_SECRET` and said "the simplest arrangement is one shell per worker,
> which `start_workers.bat` already gives you (each opens its own window)".
> That was wrong twice over, and it is recorded rather than quietly replaced
> because it is the kind of mistake that reads as correct.
>
> Each worker does get its own *window*, but `start` hands every child the
> launching shell's environment, so all three inherited the same `HUB_SECRET`.
> With the four deployed components holding distinct secrets, that meant at most
> one worker could authenticate and the other two would 401 on every poll —
> silently, because `fetch_messages` logs a warning and returns an empty list.
>
> It was also a security boundary, not just an operational one. The hub takes
> the component name from the Basic username and verifies only the secret, so
> any worker holding a secret shared with another component can authenticate as
> that component by typing its name. Had the workers been made to work by giving
> all four components one shared secret, every worker would have held Admin's
> stop button. `hub/auth_matrix.py` is the check that this has not happened;
> see `docs/PHASE0_CLOSEOUT.md` section 4.

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


---

## Deployment record — 2026-09-09

Deployed and verified. Measured from OFFICEPC against the running hub, not
inferred:

```text
GET  /                 401     GET  /openapi.json    404
GET  /messages         401     GET  /docs            404
GET  /control/status   401     GET  /redoc           404
POST /send             401     www-authenticate: Basic realm="Agent Swarm Hub"
POST /control/pause    401
POST /control/resume   401

as admin:wrong         401
as nosuchcomponent:x   401
as admin:<empty>       401
```

`docker ps` reported `Up 30 seconds` and the log ended at `Application startup
complete` — which is itself evidence that `HUB_CREDENTIALS` parsed, because a
missing or malformed value raises at import and the container would be
restarting instead.

Deployed file SHA-256, matching the repository copy at the time of deploy:

```text
de7d7db2da8a81546f2a1e22cca9172a81c589231c1c7f045408e12432db3a38
```

Credentials live in `/mnt/user/appdata/agent-swarm/hub.env`, mode 600, generated
on Tower with `openssl rand -hex 24` and never echoed to a terminal, pasted into
a transcript, or seen by me. Rollback copies are `hub.py.pre-auth` and
`docker-compose.yml.pre-auth` in the same directory.

**Two corrections this deployment forced**, both recorded above rather than
quietly edited: unraid has no `docker compose` subcommand, and `docker restart`
does not reload `--env-file`, so the container must be recreated rather than
restarted.

The authenticated path was verified by the operator, who holds the credential:
`GET /control/status` with the `admin` pair answered **200**. I never held a
credential, so I could prove only that the hub refuses; that it admits is the
operator's measurement, and both halves are needed. A hub that refused
everything would have passed every check I could run on my own and been
completely broken.

**Phase 0 is complete on both planes**: the execution host (workers take work
only from the local control directory) and the control plane (every hub route
authenticated, sender derived server-side).
