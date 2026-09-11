# agent-swarm

A controller-mediated swarm of model agents that author and review changes to
real repositories, under an authority model where **nothing a model says can
start work**.

Three models — ChatGPT, Gemini and Claude Code — hold no standing permission.
A task is authored by one and judged by another, each acting under a single
bounded *activation* issued by a controller that owns the only authoritative
state. Every transition is appended to an event ledger with the authority that
permitted it, so the record answers both *who decided* and *what allowed them
to*.

The design rule the rest of this follows from: **silence is never permission.**
An unreadable contract, an empty path list, a suite that ran no tests, a
missing reading list — each of these fails closed, because the quietest
failure otherwise produces the widest authority.

## Architecture

```
  OFFICEPC (workers)                     Tower (hub + controller)
  ┌────────────────────────┐             ┌──────────────────────────┐
  │ chatgpt_worker.py      │  activation │  hub.py      :8050       │
  │ gemini_worker.py       │ ◄─────────► │   ├ /messages  (chat)    │
  │ claude_worker.py       │   claim /   │   └ /controller/*        │
  │                        │   report    │                          │
  │ worktrees/<activation> │             │  controller/             │
  │   detached at base_sha │             │   ├ engine, states       │
  └────────────────────────┘             │   ├ activations (leases) │
           │                             │   └ SQLite ledger (WAL)  │
           │ reads/writes                │      one writer, always  │
           ▼                             └──────────────────────────┘
  canonical checkouts
  (never written to)
```

**The hub** (`hub/hub.py`) is a FastAPI app in a container on Tower. It serves
the group chat and mounts the controller's routes. Every route requires an
authenticated component, and `sender` is derived from the credential rather
than taken from the request body.

**The controller** (`controller/`) owns task state. Each state change and its
event are written in one transaction, so a task whose state moved without an
event cannot exist. `state_seq` is optimistic concurrency: a worker's result
computed against a state the task has since left is rejected, not applied.

**Workers** claim executable work only from controller activations. Message
polling records non-authoritative narration and cannot invoke a model or change
controller state. See `swarm_control.py`, which is the module that enforces
it.

**Isolation.** Authoring happens in a private git worktree created detached at
the task's own `base_sha`, then removed once the commit exists. The canonical
checkout is only ever read. It is dirty, permanently, because somebody is
working in it — and that must neither block a run nor contaminate one.

**Grounding.** `repo_registry.py` decides *which checkout* and *which commit*,
as configuration rather than as an argument somebody types. The planning ref
resolves to one SHA, once, and everything downstream takes the SHA.

### Contracts: what a task may write, and what it may read

```yaml
allowed_paths:            # writable. Enforced at commit time.
  - comic_automation/scanner.py
context_paths:            # read-only. Shown to the author, refused on write.
  - comic_automation/api.py
  - tests/test_scanner.py
```

The separation exists because of a live failure. An author with no shell, told
to reword one sentence in a README it had never seen, invented the rest of
the file — it had nothing to copy from, and the output contract demands the
*complete* contents of every file it writes. Showing it the files it may write
fixed that. `context_paths` fixes the next case: code that must fit an
interface it does not own. Widening `allowed_paths` to let an author *read*
something buys understanding with write authority, and a writable file can come
back rewritten.

## Current status

Phase 1 MVP. Four runs have been executed end to end against live models:

| | what it proved | evidence |
|---|---|---|
| MVP1 | one authored change, one review | [`docs/MVP1_AUTHOR_RUN.md`](docs/MVP1_AUTHOR_RUN.md), [`docs/MVP1_REVIEW_RUN.md`](docs/MVP1_REVIEW_RUN.md) |
| MVP2 | ChatGPT as author under the controller | [`docs/MVP2_CHATGPT_RUN.md`](docs/MVP2_CHATGPT_RUN.md) |
| MVP3 | reject → retry → approve, rejected candidate preserved | [`docs/MVP3_REVIEW_CYCLE.md`](docs/MVP3_REVIEW_CYCLE.md) |
| MVP4 | grounded planning, six refusal paths | [`docs/MVP4_PLANNING_RUN.md`](docs/MVP4_PLANNING_RUN.md) |
| MVP5 | all four MVP4 proposals rejected as duplicates; `NEEDS_CONTEXT` added | [`docs/MVP5_SEMANTIC_GROUNDING.md`](docs/MVP5_SEMANTIC_GROUNDING.md) |
| MVP6 | `NEEDS_SEARCH`; the active milestone cannot be planned from the baseline | [`docs/MVP6_SYMBOL_SEARCH.md`](docs/MVP6_SYMBOL_SEARCH.md) |

**Works:** contract-scoped authoring in isolated worktrees; model review against
acceptance criteria; the full author → review → rejection → correction →
approval cycle; planner output validated, grounded against the real tree, and
refused whole on any failure.

**Deliberately not done yet**, each with a reason in
[`docs/PHASE1_MVP_LIMITS.md`](docs/PHASE1_MVP_LIMITS.md):

- **No integrator.** `READY_INTEGRATION` is where tasks stop. Nothing merges.
- **No general contract linter.** The controller's `ready` transition does not
  perform complete contract-schema validation — `contract_yaml` is stored and
  hashed, and the route is called `ready`, not `validate`, for that reason.
  Workers enforce the supported execution fields, including `allowed_paths` and
  `context_paths`, before any model is called.
- **Execution is fail-safe, not exactly-once.** A crash mid-call cannot be
  distinguished from a call that never happened.
- **Budget is not metered.**
- **Semantic grounding is incomplete.** The harness can prove a path exists and
  that two tasks do not collide. It cannot prove the work is not already done
  under another name — see MVP5, where four fully-grounded proposals all
  duplicated existing code. `NEEDS_CONTEXT` narrows this and does not close it;
  a person still decides whether a proposal is worth doing.

Read `PHASE1_MVP_LIMITS.md` before trusting any of this with something that
matters. The protocol it implements is [`SWARM_PROTOCOL_v7.md`](SWARM_PROTOCOL_v7.md);
where this repository differs, the difference is noted at the point of
difference and is a tightening rather than a relaxation.

## Running it

Credentials are read from the environment only — never from a file in this
repository. `worker_ctl.sh` fetches each component's hub secret from the host's
env file at the moment it is needed, so the secret that is checked is the one
the worker will actually present.

```bash
./worker_ctl.sh preflight claudecode   # deployment parity, on its own
./worker_ctl.sh start    gemini        # refuses if preflight fails
./worker_ctl.sh stop     gemini
./worker_ctl.sh count    gemini        # reads the process table, not a pidfile
./worker_ctl.sh admin    show DOC-1    # controller_admin against the live hub
```

**Always run the preflight before trusting a run.** A worker started against a
stale controller produces evidence about a build nobody has, and that evidence
looks valid — which is worse than not running.

### Planning

```bash
python plan_run.py --project comicautomation \
    --guidance-file guidance.txt \
    --prompt-out prompt.txt --reply-out reply.txt --out plan.json
```

Produces a proposal and stops. `--create` writes the tasks as `DRAFT`;
`--ready` is what makes them activatable and is separate on purpose.
`--from-reply` re-parses a saved reply without calling the model, which is how
the refusal paths are exercised without spending a call.

### Deployment

```bash
DEPLOY_PYTHON=/c/Python311/python ./deploy_controller.sh
```

The deploy refuses more often than it runs: on uncommitted files, on a failing
test suite, on a digest mismatch after the copy, if the hub does not come back
up, or if the preflight is not green afterwards. There is no flag to skip the
tests.

## Tests

```bash
python -m pytest tests -q     # controller, workers, planning
python -m pytest hub   -q     # hub and controller HTTP surface
```

Or the deploy's own gate, which is the same two suites and the thing that
actually blocks a release:

```bash
DEPLOY_PYTHON=/c/Python311/python ./deploy_controller.sh --tests-only
```

Requires `pytest`, `fastapi`, `httpx` and `tzdata`. The gate refuses to run at
all if the interpreter lacks them, rather than skipping — a suite that did not
run is not a suite that passed, and that distinction is the whole reason the
gate exists.

## Repository layout

| | |
|---|---|
| `controller/` | authoritative state: schema, engine, states, activations, HTTP routes |
| `hub/` | the FastAPI app, its admin CLI, and the HTTP-surface tests |
| `*_worker.py` | one daemon per model identity |
| `swarm_control.py` | containment: the module that makes chat non-authoritative |
| `authored_change.py` | the author's output contract, scope enforcement, commit |
| `plan.py`, `plan_run.py` | planner output validation and the planning run |
| `repo_registry.py`, `repo_snapshot.py`, `worktrees.py` | which checkout, which commit, where work happens |
| `docs/` | run evidence and accepted limitations |

## Branches

`main` is the tested and deployed line. `phase1/mvp-slice` is retained as
historical development state; `phase0/*` and `phase1/controller-core` are the
earlier phases, kept because the write-ups cite them.

`evidence/mvp-demo/*` is the **unrelated history** of the throwaway repository
the MVP3 rejection cycle ran against, pushed here so it survives. It shares no
ancestor with `main` and is not meant to be merged — see
[`docs/EVIDENCE_BRANCHES.md`](docs/EVIDENCE_BRANCHES.md), which records what
each ref is and why the rejected candidate is the one that matters most.
