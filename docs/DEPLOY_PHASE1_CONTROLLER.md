# Deploying the controller onto the hub

Deployed 2026-09-09 from `phase1/mvp-slice`. This is the first deployment since
the Phase 0 hub, and the first that changes the container's mount shape.

**What this deployment does not do:** it does not touch the workers. They still
take work only from the local control directory on OFFICEPC and cannot be
activated by chat. Converting them is the next step and is deliberately
separate, because it is the one that can strand the operator.

---

## 1. What was deployed

| | |
| --- | --- |
| Branch | `phase1/mvp-slice` |
| Candidate SHA | `4f2a7e79e718bc075028b2635a9bd109b9231b43` |
| Recorded at | `10af904f72f4f4d35f3b85d5b258353f229ccee4` (adds the verifier, not deployed) |
| Host | Tower, container `agent-hub` |
| Mount shape | **changed** — application directory, was a single file |

Eight files, byte-verified against the repository at the time of deploy:

```text
3f27f9499068d79024abf032e7e6dbe23d8af34576187e73ae1657ac19b98811  app/hub.py
8e0053d6de6168543a2e71af7b9c17fd24a6ac9cebd752f81bd0e7e612e85812  app/controller/__init__.py
5631994b21f57760d0a757b496405a7908d38b1c3067b452af8223fdd1646007  app/controller/activations.py
0b7ecf421c92dd9e81a4818ea2ae518562409433838331bf1020cf392831b206  app/controller/api.py
dc214d49172dfcd25ce30b6e93bc601d70c401f3ee47b9caeb06ef7834d5bee1  app/controller/db.py
0d07a971b22b83c17b39ef85a274e145f890d179c6686ad4ed8cc58fdc7c4165  app/controller/engine.py
e7239eb565e362a418e65fa01a8c55194d2f21ab08f8e8787b502158296014d8  app/controller/schema.py
00ba692186d3e74c0ed657140cc73e5121bffec1d4daa3efe925389382cf8130  app/controller/states.py
```

Each digest was computed locally before the copy and again on Tower after it,
and matched. `git show HEAD:<path> | sha256sum` reproduces all eight.

Nothing else about the container changed: same image, same port, same
`--env-file`, same `/data` mount, same restart policy, same command. Two
additions, both required by the import:

- `-v /mnt/user/appdata/agent-swarm/app:/app` replaces
  `-v /mnt/user/appdata/agent-swarm/hub.py:/app/hub.py`;
- `-e PYTHONPATH=/app`, so `from controller import api` resolves from a known
  path rather than depending on uvicorn's working-directory behaviour. The
  previous deployment worked without it because a single module in the working
  directory is found either way; a package is worth being explicit about.

## 2. Rollback, preserved before the recreate

**The Phase 0 artifact was never modified.** `/mnt/user/appdata/agent-swarm/hub.py`
is still the authenticated Phase 0 hub, digest
`de7d7db2da8a81546f2a1e22cca9172a81c589231c1c7f045408e12432db3a38`, verified
immediately before and after staging. The new tree was created *alongside* it
at `app/`, so rolling back restores nothing — it only points the container at
the file that never moved.

The container's exact prior configuration was captured to
`/mnt/user/appdata/agent-swarm/container.pre-controller.json`
(`docker inspect`, 8649 bytes) before the recreate.

To roll back:

```sh
docker stop agent-hub && docker rm agent-hub
docker run -d \
  --name agent-hub \
  --restart unless-stopped \
  --env-file /mnt/user/appdata/agent-swarm/hub.env \
  -p 8050:8050 \
  -v /mnt/user/appdata/agent-swarm/data:/data \
  -v /mnt/user/appdata/agent-swarm/hub.py:/app/hub.py \
  -w /app \
  python:3.11-slim \
  sh -c "pip install fastapi uvicorn pydantic && uvicorn hub:app --host 0.0.0.0 --port 8050"
```

That is the Phase 0 command verbatim, with no `PYTHONPATH` and the single-file
mount. `app/` can be left in place; nothing reads it once the mount is gone.

`/data/controller.db` is created by the new code and ignored by the old, so a
rollback leaves it dormant rather than needing to be removed. `chat.db` is
untouched by any of this.

## 3. The deploy

```sh
docker stop agent-hub && docker rm agent-hub
docker run -d \
  --name agent-hub \
  --restart unless-stopped \
  --env-file /mnt/user/appdata/agent-swarm/hub.env \
  -e PYTHONPATH=/app \
  -p 8050:8050 \
  -v /mnt/user/appdata/agent-swarm/data:/data \
  -v /mnt/user/appdata/agent-swarm/app:/app \
  -w /app \
  python:3.11-slim \
  sh -c "pip install fastapi uvicorn pydantic && uvicorn hub:app --host 0.0.0.0 --port 8050"
```

`docker rm` discards nothing — both volumes are bind mounts onto the array.
Unraid still has no `docker compose` subcommand and `docker restart` still does
not reload `--env-file`; `hub/docker-compose.yml` is a record of the intended
shape, not the thing that runs.

It answered in about two seconds and the log ended at `Application startup
complete` / `Uvicorn running on http://0.0.0.0:8050`. That startup line is
itself evidence the controller imported and its schema was created, because
`hub.py` imports the package and calls `ensure_database()` at module scope with
no `try`/`except` — a bad mount fails to start rather than serving chat with a
dead controller.

## 4. Verification, on the running container

`hub/verify_deploy.py`, 33 checks, **all passed, exit 0**:

- **Anonymous callers refused, 401 on all ten routes** — the six Phase 0 routes
  and the four new controller routes. The controller routes are checked here
  precisely because mounting a router onto an authenticated app is the change
  most likely to leave an unauthenticated surface, and it would look fine in
  every local test.
- **`/docs`, `/redoc`, `/openapi.json` still 404.**
- **Each of the four components authenticates as itself**, with
  `/control/status` returning `you=<its own name>`.
- **Controller mounted**, `schema_version 1`, zero tasks and zero activations —
  a fresh database, which is what it should be.
- **Admin authority intact**: chatgpt, claudecode and gemini each get 403 from
  `POST /controller/tasks` and from `POST /control/pause`.
- **Worker claim authenticated and self-scoped**: each worker's claim returns
  200 with `agent` equal to its own name and no activation, the correct answer
  for an empty queue.
- **Global pause engages and releases**, and is left released.

Credential isolation was re-run after the deploy and is unchanged: exact
identity matrix, 0 of 12 cross pairs authenticated.

Local evidence behind the candidate, all exit 0:

```text
python -m pytest tests/ -q                    166 passed
<venv>/python -m pytest hub/ -q                66 passed
python tests/bypass_matrix.py                  27/27 guards load-bearing
python workspace/guard_check.py                FAILURES: none
```

`tests/` grew from 152 to 166 with the review-gate suite; `hub/` from 43 to 66
with the controller API suite.

## 5. What is now reachable, and what it means

The controller is live behind the same credentials as chat, at `/controller/*`.
It has no tasks and issues nothing on its own. **No worker knows it exists** —
the three workers are unchanged and still claim from the local control
directory, so this deployment changes what the hub *can* do and not what the
swarm *does*.

That is deliberate: the worker conversion is the step that can strand the
operator, and it is easier to diagnose a controller that is wrong before
anything depends on it than after.
