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
