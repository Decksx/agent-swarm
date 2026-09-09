# Session handoff — Claude Code

**Not a §18 handoff.** Those are generated views of the controller ledger and
are never authoritative. This one is written by hand to survive a context
clear, and it *is* the record until the ledger exists. Verify against the tree
before trusting any of it.

Written 2026-09-09. Repo: `C:\git\claude-agent-hub`.

---

## Where things stand

| | |
| --- | --- |
| Baseline (pre-Phase-0) | `dfba2940dec2c00206cad5658b1aa395e69baebb` on `master` |
| Phase 0 branch | `phase0/containment` @ `8bfdb638e56024cd064d6a874ee3947d4dcad494` |
| Phase 1 branch (current) | `phase1/controller-core` @ `049d2e6` |
| Deployed to Tower | **Phase 0 only.** Phase 1 is not deployed. |
| Merged to `master` | **Nothing.** Both branches are unmerged, pending operator review. |

```powershell
python -m pytest tests/ -q          # 152 passed
python tests/bypass_matrix.py       # 27/27 load-bearing, exit 0
python workspace/guard_check.py     # exit 0, FAILURES: none
```

Hub tests need FastAPI, which the system interpreter does not have. `pytest.ini`
sets `testpaths = tests` so a bare `pytest` does not trip over them. To run them:

```powershell
python -m venv <scratch>\hubvenv
<scratch>\hubvenv\Scripts\python -m pip install fastapi httpx pytest
<scratch>\hubvenv\Scripts\python -m pytest hub/test_hub.py -q   # 37 passed
```

## What Phase 0 did, and it is live

**Execution host (OFFICEPC).** Chat cannot start work — not by `target`, not by
`@mention`, not from any sender. The three workers narrate to the hub and claim
activations from a local control directory the hub cannot reach. Global pause
(`control/PAUSED` or `SWARM_PAUSED`), checked *before* claiming so it defers
work rather than consuming it. `swarm_control.py` has the operator CLI.

**Control plane (Tower).** `hub.py` authenticates all five routes with HTTP
Basic, derives `sender` from the credential, removes `/docs` `/redoc`
`/openapi.json`, adds `/control/status|pause|resume`, and refuses to start
without `HUB_CREDENTIALS`. Deployed and verified 2026-09-09 — see
`docs/DEPLOY_PHASE0_HUB.md` for the record and the rollback.

Credentials are in `/mnt/user/appdata/agent-swarm/hub.env` on Tower, mode 600.
**I have never held one and should not.** The operator verified the
authenticated `200`; I could only prove the hub refuses.

## What Phase 1 has so far

`controller/` — not deployed, not wired to anything yet.

- `schema.py` — 12 tables, 5 indexes, §4. `SCHEMA_VERSION = 1`, never deployed,
  so schema edits are still amendments rather than migrations.
- `db.py` — `BEGIN IMMEDIATE` transactions, WAL, `foreign_keys=ON`,
  `synchronous=FULL`, version check that fails closed, `split_statements`.
- `states.py` — §8 as a table. Undefined `(state, event)` pairs are rejected by
  construction. Authority lives in the same table.
- `engine.py` — event append + projection update in one transaction,
  `expected_state_seq` stale-write guard, idempotent redelivery, conflicting
  replay refused, `replay_state()` for the §18 equivalence test.
- `activations.py` — issue/claim/heartbeat/result, durations-never-timestamps,
  host capacity, expiry sweep that also recovers the task.

## Next steps, in order

1. **Budget cap.** Operator sets a price table (dollars per million tokens, per
   model) in policy; the controller meters usage and caps in dollars, checked
   *before* issuing an activation (§14). Two separate mechanisms: ChatGPT and
   Gemini bill per token against a $10/month plan; Claude Code is a 5-hour
   rolling subscription window. **Do not hardcode provider prices** — look them
   up at implementation time, and keep them operator-configurable so they can
   go stale without lying.
2. **Convert workers to pull from the controller** (`POST /activations/claim`).
   This is the step that can strand the operator, so stop for review first. The
   local control directory stays as the Admin fallback.
3. **Serve the controller from the hub container** — same FastAPI app, separate
   SQLite file at `/data/controller.db`.

### Two decisions the operator has not answered yet

- **Mount shape.** The container bind-mounts a *single file*
  (`/mnt/user/appdata/agent-swarm/hub.py:/app/hub.py`). A `controller/` package
  needs either a directory mount (`…/app:/app`, moving `hub.py` inside) or a
  second mount alongside the file one. I recommended the first. Either way it
  is another container recreate.
- **Order.** Budget cap first, or straight at the worker conversion.

### Agreed and settled

- Controller lives on Tower, in the existing `agent-hub` container.
- The pilot the operator proposed — *"ask which GitHub project to work on, read
  the git, generate a plan of attack"* — is the **Phase 1 acceptance test**, not
  the Phase 2 pilot. It produces no candidate SHA, so it exercises no diff gate,
  no verification gate and no integration saga. A separate boring code pilot is
  still needed for those.
- Hard budget cap, per above.

## Constraints that bite

- **Zero new dependencies in `hub.py`.** The container runs
  `pip install fastapi uvicorn pydantic` at every start with no image build.
  Anything else fails to come back up after a restart.
- **Never add `--workers N`.** A single uvicorn process is what makes "only the
  controller opens the database for writing" true. Multiple processes behind one
  WAL file corrupt it slowly.
- **Repo line endings are LF.** Verified with byte counts, not `grep`.
- `ComicAutomation`, PR #90, production databases and the comic library are all
  out of scope and untouched.

## Traps I hit, so you do not

- **`open(path, "w").write(<expr>)` truncates the file before the expression is
  evaluated.** If the expression raises, you are left with zero bytes. It cost a
  full file recovery. Compute the content first, open for writing last.
- **`/tmp` works for Git Bash redirection but is not a path native Python can
  open.** Use the session scratchpad.
- **`git checkout <file>` to undo a sabotage reverts to the last *commit*.** If
  the file has uncommitted work, that work is gone. Restore from an in-memory
  copy instead.
- **Backslashes in heredocs get collapsed in transport.** Build escapes with
  `chr(92)` when patching a file that contains `\n` as two literal characters.
- **The bypass matrix has corrected me four times.** Twice my expected failure
  sets were wrong, once it exposed a test passing vacuously, once it showed a
  guard I had just written was unreachable and should be deleted. Trust it over
  your own expectations.
- **`docker compose` does not exist on unraid**, and `docker restart` does not
  reload `--env-file`. The container must be recreated.

## Working agreement, learned in-session

The operator values evidence over assertion. Concretely: measure rather than
infer and say which it was; record what you could *not* verify as a gap rather
than reconstructing it plausibly; state corrections plainly and keep going; one
file per commit with a message explaining *why*, not what; and prove a guard is
load-bearing by removing it and naming the tests that fail.
