# Hub provenance

`hub.py` is the control plane. It runs on Tower, not on OFFICEPC, and this
directory is a working copy — **Tower is authoritative until a change is
deployed back**.

## Where it came from

Copied 2026-09-09 from `/mnt/user/appdata/agent-swarm/hub.py` on Tower, staged
via the `media` share by the operator (the `appdata` share is deliberately not
exported over SMB). Verified byte-identical to the source by SHA-256:

```text
a0f72c41a8549367b5accc087af615ba156ad4878ccc70258a6df3d9618ef91e
```

5975 bytes, pure LF, committed verbatim with no edits so a change has a
baseline to diff against and a rollback to return to.

## How it runs

Container `agent-hub`, id `a56ec0392cd1`, image `library/python:3.11-slim`,
bridge network, `8050/TCP` published on `192.168.42.50:8050`, `WorkingDir=/app`,
no entrypoint. Started with:

```sh
sh -c "pip install fastapi uvicorn pydantic && uvicorn hub:app --host 0.0.0.0 --port 8050"
```

Two consequences, both load-bearing for any patch:

1. **Dependencies are installed at container start from that hardcoded list.**
   There is no `requirements.txt` and no image build. Anything a patch imports
   must be in `fastapi`, `uvicorn`, `pydantic`, or the standard library, or the
   hub will not come back up after a restart.
2. **Only `hub.py` is mounted into the container**, as a single-file bind mount
   (`/app/hub.py` ← `/mnt/user/appdata/agent-swarm/hub.py`). The other files in
   that directory — `main.py`, `gemini_lead.py`, `docker-compose.yml` — are not
   in the container and are not part of the running service.

Volumes: `/data` ← `/mnt/user/appdata/agent-swarm/data`, holding `chat.db`.

## Environment

The container carries **no application environment variables**. Names only, with
values deliberately never collected:

```text
PATH  LANG  GPG_KEY  PYTHON_VERSION  PYTHON_SHA256
```

Those are all stock `python:3.11-slim` image variables. **There is nowhere to
put a credential today**, so adding authentication requires an operator change
to the container configuration as well as a change to this file. That is a
deployment step, not a code step, and it is the reason auth cannot be shipped
by editing `hub.py` alone.

## Deploying a change

Copy back to `/mnt/user/appdata/agent-swarm/hub.py` and `docker restart
agent-hub`. Rollback is the same operation with the baseline commit of this
file. Because it is a single-file bind mount, no rebuild is involved either way.

---

## The rest of `/mnt/user/appdata/agent-swarm/`

Copied 2026-09-09 by the same route and verified by SHA-256. **Only `hub.py` is
mounted into the container**, so none of these is part of the running service.
They are committed because they are part of the deployment and had no version
control, not because they are live.

### `docker-compose.yml`

Matches the running container exactly — same image, ports, both volume mounts,
`working_dir`, and the `pip install fastapi uvicorn pydantic && uvicorn hub:app`
command. It is the file to edit when the hub needs an environment variable,
which is what authentication will require. `restart: unless-stopped`, so the
container comes back by itself after a Tower reboot.

### `main.py` — stale, must not be deployed

An earlier version of the hub keeping messages in a Python list instead of
SQLite. Superseded by `hub.py` and not mounted. Deploying it by mistake would
silently discard every stored message, because nothing in it touches
`/data/chat.db`. It carries the same unescaped-`sender` XSS described below.

### `gemini_lead.py` — a fourth activation source, not contained by Phase 0

This is the orchestrator that drove the swarm, and it was not visible from
OFFICEPC. It polls `/messages`, and on any message whose `target` is `@gemini`,
`gemini` or `lead` — or from `Admin` to `All` — it calls Gemini and posts the
result **addressed to `@ClaudeCode`** by default, or `@ChatGPT`/`@Admin` if the
model's own reply happens to mention one.

Three things about it matter:

1. **It is the loop's engine.** Before Phase 0 its directives target-triggered
   `claude_worker`, which ran `claude -p` with Bash authority and posted its
   result to `@Gemini`, which re-triggered this. That is the whole cycle.
2. **It has no brakes at all.** The three workers each grew a cooldown, a burst
   cap and a verification gate. This has none: no throttle, no cap, no
   self-message check beyond `sender == "Gemini"`, no rate limiting.
3. **It runs on Tower, not OFFICEPC** — `HUB_URL` is hardcoded to
   `http://localhost:8050` — and it is not in the container, so it runs as a
   bare process on the host.

**It is not running.** Measured, not assumed: the newest message on the hub is
5.7 days old, and messages #371–378 are addressed to `@Gemini`, which is exactly
this script's trigger condition. Nothing replied.

Phase 0 containment does **not** cover it. What Phase 0 does do is break the
cycle from the other side: the workers ignore chat entirely, so its directives
can no longer start a model or a shell on OFFICEPC, and `claude_worker` now
replies to `@Admin` rather than `@Gemini`, so restarting it would not resume the
loop. It would still be an unauthenticated, unthrottled model-caller.

**Recommendation: leave it stopped.** Bringing it under control is Phase 1 work
— it is the `Gemini advisor` role in `SWARM_PROTOCOL_v7.md` §2, which is
explicitly out of scope here. Once the hub authenticates, it will fail closed
anyway for want of a credential.

## What the message log shows about the loop

Of 378 stored messages: `Gemini` 182, `ChatGPT` 148, `ClaudeCode` 28,
`Admin` 20. **330 of 378 (87.3%) were agent-to-agent, with 20 (5.3%) from a
human.** That is the measured shape of the system Phase 0 was asked to contain.
