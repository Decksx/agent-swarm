# Swarm Operating Protocol v2

**Repo:** `claude-agent-hub` (control plane) → operating on `ComicAutomation`
**Hub:** `agent-hub` container, Tower `192.168.42.50:8050` (Tailscale `100.95.142.80:8050`)
**Workers:** OFFICEPC `C:\git\claude-agent-hub\` — `claude_worker.py`, `chatgpt_worker.py`, `gemini_worker.py`
**Target repo:** `D:\Documents\ComicAutomation`

This document is the authoritative protocol. It is checked into the control-plane repo and
loaded by every agent at the start of every activation. No agent may improvise a transition,
a command, or a scope that is not defined here.

---

## 0. What changes, and why

The v1 swarm is a **chat room**. Agents poll `/messages`, match on `target`, call a model, and
post free text back. That works for demos and fails for real work, for four structural reasons:

1. **Mentions are the transport.** Any agent can address any other agent, so any agent can
   start a loop. There is no mechanism that can stop it, only a prompt asking nicely.
2. **There is no state.** `messages(id, sender, target, content, timestamp)` cannot express
   "task 14 is at version 3, verified at SHA abc…, waiting on integration." State lives in the
   models' heads, which is why context exhaustion loses work.
3. **Verification is not bound to anything.** "Ran pytest, 117 passed" is a claim about an
   unspecified working tree at an unspecified moment.
4. **Workers are unsupervised.** A crashed worker looks identical to a busy worker. You have
   already hit this three times (Claude worker silent, ChatGPT silent, Gemini silent).

v2 keeps everything you built and adds a **control plane** beside the chat plane.

| Plane | Purpose | Source of truth for |
| --- | --- | --- |
| **Control plane** (new) | Tasks, contracts, events, activations, evidence, locks | Everything that matters |
| **Chat plane** (existing) | Human-readable narration, the live UI, ad-hoc questions | Nothing |

The chat feed becomes a *rendering* of control-plane events plus free-form human messages.
Work never flows through chat. This is the single most important change: it makes loop
prevention mechanical rather than aspirational.

---

## 1. Roles

### Controller (deterministic code — no model)

Runs on Tower alongside the hub. Owns the SQLite database as the single writer. It is the only
component that may:

- create or advance task state
- issue activations
- grant and release resource locks
- decide that a task is complete

The controller contains **no LLM call**. Every decision it makes is a table lookup or a
comparison. This is what makes the system debuggable and what makes loops impossible: a worker
cannot activate another worker because workers have no ability to issue activations.

### Advisor (Gemini) — called as a function, not run as a peer

Gemini stops being a daemon that reads chat and speaks. It becomes a function the controller
calls when a decision genuinely requires judgment:

- decomposing an objective into draft task contracts
- triaging an ambiguous verification failure (author defect vs environment defect)
- reviewing a diff for design concerns the gates cannot express
- adjudicating a spec ambiguity a worker raised

The call takes a bounded **decision packet** (below) and returns a **proposal**. The controller
validates the proposal against the transition table and either applies it or rejects it. A
malformed or out-of-policy proposal is discarded and logged; it never becomes state.

This removes most of the loop risk, most of the token spend, and the "Gemini owns canonical
state but has no file access" contradiction in one move.

### Author (ChatGPT) — writes code, never verifies it

One activation, one bounded attempt, one candidate commit, stop. Has no ability to run the
project's tests, merge, or declare success.

### Operator (Claude Code) — verifies and integrates, never authors what it verifies

Runs on OFFICEPC where the code actually lives. Owns worktree creation, gate execution,
evidence capture, and the integration merge. May author code only for tasks where the author
role is explicitly assigned to it — and a task may never have the same agent as both author and
verifier.

### Admin (you)

Approves destructive operations, resolves escalations, and holds the kill switch. Everything
addressed to `@Admin` lands in a queue with a visible age, not in a chat scrollback.

---

## 2. Data model

Replace the single `messages` table with the following. Keep `messages` as-is for the chat UI
and add a nullable `task_id` so chat can be filtered per task.

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Immutable task identity
CREATE TABLE tasks (
  task_id         TEXT PRIMARY KEY,          -- 'T-0042'
  title           TEXT NOT NULL,
  objective       TEXT NOT NULL,
  parent_task_id  TEXT REFERENCES tasks(task_id),
  priority        INTEGER NOT NULL DEFAULT 50,
  created_at      REAL NOT NULL,
  created_by      TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1,
  state           TEXT NOT NULL,             -- see FSM
  state_seq       INTEGER NOT NULL DEFAULT 0 -- CAS guard
);

-- A version is a frozen contract. Any change to scope, commands,
-- or base_sha creates a new version. Retries do NOT create versions.
CREATE TABLE task_versions (
  task_id       TEXT NOT NULL REFERENCES tasks(task_id),
  version       INTEGER NOT NULL,
  contract_yaml TEXT NOT NULL,
  contract_hash TEXT NOT NULL,               -- sha256 of contract_yaml
  base_sha      TEXT NOT NULL,               -- full 40 chars
  created_at    REAL NOT NULL,
  created_by    TEXT NOT NULL,
  PRIMARY KEY (task_id, version)
);

-- Append-only. State is a projection of this table.
CREATE TABLE events (
  seq             INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        TEXT NOT NULL UNIQUE,      -- client-generated UUID = idempotency key
  task_id         TEXT NOT NULL REFERENCES tasks(task_id),
  task_version    INTEGER NOT NULL,
  source_event_id TEXT,                      -- causal parent, NULL for human/controller origin
  actor           TEXT NOT NULL,             -- 'controller' | 'claude' | 'chatgpt' | 'gemini' | 'admin'
  kind            TEXT NOT NULL,             -- see event catalogue
  from_state      TEXT,
  to_state        TEXT,
  payload_json    TEXT NOT NULL DEFAULT '{}',
  created_at      REAL NOT NULL
);
CREATE INDEX idx_events_task ON events(task_id, seq);

-- One activation = one bounded attempt by one agent.
CREATE TABLE activations (
  activation_id    TEXT PRIMARY KEY,
  task_id          TEXT NOT NULL REFERENCES tasks(task_id),
  task_version     INTEGER NOT NULL,
  agent            TEXT NOT NULL,
  role             TEXT NOT NULL,            -- 'author' | 'verifier' | 'integrator' | 'advisor'
  issued_at        REAL NOT NULL,
  claimed_at       REAL,
  lease_expires_at REAL NOT NULL,
  heartbeat_at     REAL,
  status           TEXT NOT NULL,            -- ISSUED|CLAIMED|RUNNING|DONE|EXPIRED|ABANDONED
  result_event_id  TEXT,
  attempt_no       INTEGER NOT NULL
);

-- SHA-bound proof that a command ran and what it returned.
CREATE TABLE evidence (
  evidence_id     TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  task_version    INTEGER NOT NULL,
  activation_id   TEXT NOT NULL,
  candidate_sha   TEXT NOT NULL,             -- full 40 chars
  worktree_clean  INTEGER NOT NULL,          -- 0/1
  command         TEXT NOT NULL,
  shell           TEXT NOT NULL,             -- 'pwsh' | 'cmd' | 'bash'
  exit_code       INTEGER,
  duration_ms     INTEGER,
  env_fingerprint TEXT NOT NULL,             -- hash of python/node version, OS, lockfile hashes
  stdout_path     TEXT,
  stderr_path     TEXT,
  outcome         TEXT NOT NULL,             -- PASS|FAIL|TIMEOUT|INFRA_ERROR
  created_at      REAL NOT NULL
);
CREATE INDEX idx_evidence_cache ON evidence(candidate_sha, command, env_fingerprint);

-- Runtime resource serialization (see §8).
CREATE TABLE locks (
  lock_name  TEXT PRIMARY KEY,
  holder     TEXT NOT NULL,                  -- activation_id
  task_id    TEXT NOT NULL,
  acquired_at REAL NOT NULL,
  expires_at  REAL NOT NULL
);

-- Rolling budget windows (Claude's 5-hour limit, daily token spend).
CREATE TABLE budget_windows (
  agent        TEXT NOT NULL,
  window_kind  TEXT NOT NULL,                -- 'rolling_5h' | 'daily_tokens'
  window_start REAL NOT NULL,
  consumed     REAL NOT NULL DEFAULT 0,
  limit_value  REAL NOT NULL,
  PRIMARY KEY (agent, window_kind, window_start)
);
```

**Single writer.** Only the controller process writes. Workers write exclusively through the
HTTP API. SQLite in WAL mode with one writer is entirely sufficient for this workload; do not
let three daemons open the file directly.

---

## 3. Hub API v2

Existing endpoints stay. New ones:

```
POST   /tasks                      -> create DRAFT task + version 1
POST   /tasks/{id}/validate        -> run contract linter, DRAFT -> VALIDATED
POST   /tasks/{id}/versions        -> new frozen contract version
GET    /tasks?state=...            -> queue views
GET    /tasks/{id}                 -> task + current contract + event tail

POST   /events                     -> append event (idempotent on event_id, CAS on state_seq)

POST   /activations/claim          -> worker long-polls for work assigned to it
POST   /activations/{id}/heartbeat -> extend lease
POST   /activations/{id}/result    -> submit exactly one result, ends the activation

POST   /evidence                   -> record a gate result
GET    /evidence/lookup            -> cache probe: (candidate_sha, command, env_fingerprint)

POST   /locks/acquire              -> blocking or fail-fast
POST   /locks/release

POST   /control/pause              -> global drain: no new activations issued
POST   /control/resume
```

### Two rules that make the whole thing safe

**Rule 1 — Workers pull, they are never pushed to.**
`/activations/claim` replaces target-matching on `/messages`. A worker asks "is there an
activation for me?" and gets at most one. Because only the controller creates activations, and
the controller only creates them per the transition table, an agent physically cannot cause
another agent to run. Delete the `if msg["target"] == "@ClaudeCode"` branch from every worker.

**Rule 2 — Every state change goes through `POST /events` with CAS.**

```json
{
  "event_id": "9f2c…",
  "task_id": "T-0042",
  "task_version": 3,
  "source_event_id": "1a8e…",
  "kind": "candidate_submitted",
  "expected_state": "RUNNING",
  "expected_state_seq": 17,
  "payload": { "candidate_sha": "3f6c…40 chars…" }
}
```

The controller rejects the event if `event_id` was already seen (duplicate → 200 with the
original result, not an error), if `task_version` is not current (stale attempt → 409), or if
`expected_state_seq` does not match (concurrent change → 409 with the current state so the
caller can re-read rather than retry blindly).

---

## 4. The task contract

Frozen at version creation. The verification commands live **here**, in the controller's copy —
never read from the candidate worktree. If the author can edit the file that says what to run,
the gate is decorative.

```yaml
schema_version: 2
task_id: T-0042
version: 3
title: "Harden CBZ parser against malformed ComicInfo.xml"
objective: >
  tests/test_cbz_parser.py must cover missing, empty, and non-UTF-8 ComicInfo.xml
  without changing existing public behaviour.

roles:
  author: chatgpt          # may not equal verifier
  verifier: claude
  integrator: claude

repo:
  path: "D:\\Documents\\ComicAutomation"
  remote: origin
  target_branch: main
  base_sha: "9c1f0d4b7e2a5f83c6d1908b4e7a2f35c8d90b16"   # full 40, never abbreviated

scope:
  allowed_files:                  # exact files the author may modify
    - parsers/cbz_parser.py
    - tests/test_cbz_parser.py
  allowed_dirs: []                # prefer empty; dirs are how scope creep happens
  forbidden_paths:
    - .github/**
    - requirements*.txt
    - pyproject.toml
    - "**/migrations/**"
  allow_new_files: true
  allow_deletions: false

verification:
  shell: pwsh
  commands:
    - id: lint
      command: "python -m ruff check parsers/cbz_parser.py tests/test_cbz_parser.py"
      expected_exit: 0
      timeout_seconds: 120
      cost: cheap                 # cheap gates run first; a cheap failure skips expensive ones
    - id: unit
      command: "python -m pytest tests/test_cbz_parser.py -q"
      expected_exit: 0
      timeout_seconds: 300
      cost: medium
    - id: regression
      command: "python -m pytest -q"
      expected_exit: 0
      timeout_seconds: 1800
      cost: expensive
      run_at: integration         # not at review — see §8
  new_test_must_fail_at_base: true   # cheapest anti-tautology check available

resources:
  database: isolated-test-db
  ports: []
  docker_containers: []
  external_writes: forbidden
  temp_dir: "D:\\swarm-tmp\\{task_id}\\{activation_id}"

locks: []                          # e.g. [migration-sequence, integration]

budgets:
  author_activations: 3            # counts activations, not messages
  verifier_activations: 5
  wall_clock_minutes: 90
  tool_calls: 60
  tokens_estimated: 150000

escalation:
  on_budget_exhausted: NEEDS_HUMAN
  on_ambiguity: NEEDS_HUMAN
  human_response_timeout_hours: 48
  on_human_timeout: EXPIRED
```

### The contract linter (run before a task can be assigned)

`DRAFT → VALIDATED` requires all of:

- schema version supported; all required fields present
- `base_sha` exists in the repo and is a full 40-char hex string
- `author != verifier`
- every `allowed_files` entry exists at `base_sha`, or `allow_new_files` is true
- `allowed_files ∩ forbidden_paths = ∅`
- scope does not overlap the scope of any other task in a non-terminal state
- every verification command parses and its executable resolves on the runner
- declared locks exist in the lock registry

Contract authoring is the highest-leverage step in the whole pipeline, and in v1 it is owned by
nobody. A bad contract costs a full activation cycle to discover. This linter is cheap and pays
for itself immediately.

---

## 5. The state machine

### States

| State | Meaning | Terminal |
| --- | --- | --- |
| `DRAFT` | Contract being written | no |
| `VALIDATED` | Passed the linter, not yet queued | no |
| `READY` | Queued, dependencies satisfied | no |
| `ASSIGNED` | Activation issued to author | no |
| `RUNNING` | Author claimed the activation | no |
| `READY_FOR_REVIEW` | Candidate SHA submitted | no |
| `REVIEWING` | Verifier claimed the activation | no |
| `CHANGES_REQUESTED` | Author defect found | no |
| `READY_FOR_INTEGRATION` | All review gates passed | no |
| `INTEGRATING` | Integration lock held | no |
| `BLOCKED` | Environment/dependency defect, machine-resolvable | no |
| `NEEDS_HUMAN` | Requires Admin decision | no |
| `COMPLETE` | Integrated and post-integration verified | **yes** |
| `FAILED` | Budget exhausted or unrecoverable | **yes** |
| `CANCELLED` | Admin cancelled | **yes** |
| `SUPERSEDED` | Replaced by another task | **yes** |
| `EXPIRED` | Human escalation timed out | **yes** |
| `REVERTED` | Was COMPLETE; integration later reverted | **yes** |

### Transitions

| From | Event | To | Who may emit |
| --- | --- | --- | --- |
| `DRAFT` | `contract_validated` | `VALIDATED` | controller |
| `DRAFT` | `validation_failed` | `DRAFT` | controller |
| `VALIDATED` | `queued` | `READY` | controller |
| `READY` | `activation_issued` | `ASSIGNED` | controller |
| `ASSIGNED` | `activation_claimed` | `RUNNING` | author |
| `ASSIGNED` | `lease_expired` | `READY` | controller |
| `RUNNING` | `candidate_submitted` | `READY_FOR_REVIEW` | author |
| `RUNNING` | `decision_required` | `NEEDS_HUMAN` | author |
| `RUNNING` | `environment_defect` | `BLOCKED` | author |
| `RUNNING` | `attempt_failed` | `CHANGES_REQUESTED` | author |
| `RUNNING` | `lease_expired` | `CHANGES_REQUESTED` | controller |
| `READY_FOR_REVIEW` | `activation_issued` | `REVIEWING` | controller |
| `REVIEWING` | `gates_passed` | `READY_FOR_INTEGRATION` | verifier |
| `REVIEWING` | `author_defect` | `CHANGES_REQUESTED` | verifier |
| `REVIEWING` | `scope_violation` | `CHANGES_REQUESTED` | verifier |
| `REVIEWING` | `environment_defect` | `BLOCKED` | verifier |
| `REVIEWING` | `lease_expired` | `READY_FOR_REVIEW` | controller |
| `CHANGES_REQUESTED` | `retry_authorized` | `ASSIGNED` | controller |
| `CHANGES_REQUESTED` | `budget_exhausted` | `NEEDS_HUMAN` | controller |
| `READY_FOR_INTEGRATION` | `base_moved` | `CHANGES_REQUESTED` | controller |
| `READY_FOR_INTEGRATION` | `integration_lock_acquired` | `INTEGRATING` | controller |
| `INTEGRATING` | `integrated_and_verified` | `COMPLETE` | integrator |
| `INTEGRATING` | `merge_conflict` | `NEEDS_HUMAN` | integrator |
| `INTEGRATING` | `post_integration_failed` | `NEEDS_HUMAN` | integrator |
| `BLOCKED` | `environment_repaired` | `READY_FOR_REVIEW` | controller |
| `BLOCKED` | `escalated` | `NEEDS_HUMAN` | controller |
| `NEEDS_HUMAN` | `admin_resumed` | `READY` | admin |
| `NEEDS_HUMAN` | `admin_failed` | `FAILED` | admin |
| `NEEDS_HUMAN` | `admin_cancelled` | `CANCELLED` | admin |
| `NEEDS_HUMAN` | `response_timeout` | `EXPIRED` | controller |
| `COMPLETE` | `revert_integrated` | `REVERTED` | integrator |
| *any non-terminal* | `superseded_by` | `SUPERSEDED` | admin |
| *any non-terminal* | `admin_cancelled` | `CANCELLED` | admin |

Anything not in this table is rejected. No agent improvises a transition. Note that every
non-terminal state has at least one outbound edge — `BLOCKED` and `NEEDS_HUMAN` in particular
both have exits, which v1 lacks, and `COMPLETE` is not the end of the line because
post-integration failures are real.

---

## 6. Activations, leases, and the orphan reaper

This is the fix for "I restarted the Claude worker and it still won't reply."

1. Controller issues an activation with `lease_expires_at = now + lease_seconds`.
2. Worker long-polls `/activations/claim`, receives **at most one**, sets status `CLAIMED`.
3. Worker heartbeats every `lease_seconds / 3`. A missed heartbeat is visible immediately in
   the UI as a stale activation, not as silence.
4. Worker submits exactly one result via `/activations/{id}/result` and stops. It does not poll
   again until it has finished.
5. If the lease expires with no result, the reaper marks the activation `EXPIRED` and applies
   the `lease_expired` transition.

**Idempotency on reclaim.** A late worker may still be alive and may have already committed.
Before reissuing, the reaper checks for the expected artifact — does a commit exist on
`swarm/{task_id}/v{version}` whose parent is `base_sha`? If yes, treat the attempt as completed
and transition to `READY_FOR_REVIEW` using that SHA. Late results from an expired activation
are recorded as evidence but never applied as state.

**Retry budgets count activations**, never messages or conversation turns.

---

## 7. Verification, bound to a SHA

The author's output is a **full 40-character commit SHA on a task branch**, nothing else. No
"see the branch", no abbreviated `4a8b1c2`.

```
1. Author commits to swarm/{task_id}/v{version}, reports candidate_sha = X.
2. Controller verifies X's parent chain includes contract.base_sha. If not -> CHANGES_REQUESTED.
3. Verifier runs the diff gate (below) against X.
4. Verifier creates/resets a worktree to exactly X:
     git worktree add --detach D:\wt\{task_id}-{activation_id} X
   and asserts `git status --porcelain` is empty.
5. Cache probe: for each command, GET /evidence/lookup on
   (X, command, env_fingerprint). A hit is reused; verification of an
   unchanged tree is free.
6. Run gates cheap -> expensive, stopping at first failure.
7. Record evidence: SHA, command, shell, exit code, duration, env fingerprint,
   stdout/stderr paths.
8. Remove the worktree (see §9 for why this needs retries on Windows).
```

### The diff gate

```
changed_paths(base_sha, candidate_sha) ⊆ (allowed_files ∪ allowed_dirs)
```

Also reject, mechanically:

- any uncommitted change in the candidate worktree
- a candidate whose merge base with `base_sha` is not `base_sha` (rebased or wrong base)
- unauthorized merge commits on the task branch
- new or modified submodules
- symlinks whose target escapes the worktree
- files matching `forbidden_paths`
- generated artifacts (`__pycache__`, `*.pyc`, `.pytest_cache`, build output)
- deletions when `allow_deletions: false`

Emit the actual changed-path list into the event payload. When this gate fires you want to see
what it saw, not "scope violation."

### The self-verification hole

If `allowed_files` includes `tests/`, the author can make a failing test pass by editing the
test. Three cheap mitigations, all of which you should run:

1. **Commands come from the controller's contract copy**, never from the worktree.
2. **Test-file changes get their own diff-gate class** and are surfaced separately in the
   review event, so a diff that touches only tests is immediately obvious.
3. **`new_test_must_fail_at_base`** — check out `base_sha`, copy in only the changed test files,
   and assert the new tests fail. Then run them at `X` and assert they pass. This costs one
   extra test run and catches both tautological tests and tests-edited-to-pass. It is the
   highest-value check in this entire document relative to its cost.

---

## 8. Runtime isolation and integration

### Git isolation ≠ runtime isolation

Worktrees isolate files, index, and `HEAD`. They do not isolate:

shared databases · fixed TCP ports · temp directories · caches outside the worktree ·
environment variables · Docker container names · external services · git hooks · repo-level
config · the Windows registry · anything the tests touch on the `X:` comic library volume

The last one matters specifically for `ComicAutomation`: tests that walk or write to the real
library are not isolated by any worktree. Declare a fixture root per activation
(`resources.temp_dir`) and make `external_writes: forbidden` the default.

Serialize by lock whenever tasks touch: database migrations, dependency lockfiles, release
metadata, generated schemas, or the same Docker container name — even when the source files
differ.

### Integration is the real serialization point

`READY_FOR_INTEGRATION` does not mean "merge now." It means "eligible to enter the merge train."

- One global `integration` lock. One task integrates at a time.
- Before merging, re-check that `target_branch` still points at `base_sha`. If it moved, the
  candidate was verified in a context that no longer exists → `base_moved` →
  `CHANGES_REQUESTED` with a new version carrying the new `base_sha`. A rebase produces a new
  candidate SHA and therefore a new verification cycle. This is not a retry and must not consume
  the author's retry budget.
- Merge or cherry-pick **exactly X**.
- Run the `run_at: integration` gates (the full suite) against the resulting integration SHA.
- Only then `COMPLETE`.
- If post-integration gates fail: revert, transition `COMPLETE → REVERTED`, and open a new task.
  Any task whose `base_sha` was the reverted commit is auto-flagged.

**Merge conflicts are authored work.** They involve judgment about code and therefore need a
contract, a scope, and evidence. A conflict creates a new task; the integrator does not quietly
resolve it inside the integration lock. This is where an unaudited edit would otherwise slip in
at exactly the worst moment.

---

## 9. Windows-specific requirements

Everything runs on OFFICEPC against `D:\Documents\ComicAutomation`. These will bite before any
of the interesting problems do.

**Line endings — fix this first.** Without a committed `.gitattributes`, `core.autocrlf`
differences between worktrees make the diff gate see whole-file changes on files nobody touched.
The gate is unusable until this is normalized.

```gitattributes
* text=auto eol=lf
*.ps1 text eol=crlf
*.cmd text eol=crlf
*.bat text eol=crlf
*.png binary
*.cbz binary
```

**Long paths.** Worktree root plus nested test fixtures blows past 260 characters.

```powershell
git config --system core.longpaths true
# and enable LongPathsEnabled in the registry
```

Keep worktrees at a short root — `D:\wt\{task_id}` — never nested inside the repo.

**File locks on cleanup.** Defender, open Python handles, and Docker bind mounts will make
`git worktree remove` fail. This is the single most common source of accumulated garbage.

```powershell
# cleanup must retry, then force, then prune
for ($i=0; $i -lt 5; $i++) {
  git worktree remove --force $wt 2>$null
  if (-not (Test-Path $wt)) { break }
  Start-Sleep -Seconds 2
}
git worktree prune
```

Add a disk quota check on `D:` before creating a worktree, and a reaper that prunes worktrees
for tasks in terminal states. Note the existing warning about `G:` at 93% — no swarm artifacts
on `G:`, ever.

**Case-insensitive filesystem.** Rename-only-by-case changes are silently lost and the diff gate
will not see what you think it sees. Reject case-only renames in the gate.

**Symlinks** require elevated privileges to create on Windows, which affects both the symlink
escape check and any tooling that assumes them. The check still runs; creation may not work.

**Exit codes and shells.** `expected_exit: 0` is meaningless without a declared shell. PowerShell
`$LASTEXITCODE` vs `$?` differ for native commands, and stderr output does not imply failure.
The contract declares `shell: pwsh`; the runner captures exit code, stdout, and stderr
separately and never infers failure from stderr being non-empty.

**Encoding.** You already hit this. Every subprocess read uses `encoding="utf-8",
errors="replace"`, and every worker sets `PYTHONIOENCODING=utf-8` at startup rather than relying
on the launching shell.

**Ports.** Windows reserves port ranges dynamically (`netsh interface ipv4 show
excludedportrange protocol=tcp`). A test that binds a fixed port will fail intermittently and
look exactly like flakiness. Declare ports in `resources.ports` and have the runner check
availability before the gate runs, reporting `INFRA_ERROR` rather than `FAIL` if the port is
reserved.

---

## 10. Budgets, context limits, and handoff

### Your handoff question, answered

You asked whether the three agents should share one `handoff.md` or keep their own. Neither, in
the sense that matters: **markdown is never the source of truth.** The ledger is. Per-agent
handoff files are fine as a *rendering* of the ledger for the specific purpose of restarting a
Claude Code session, but if a fact exists only in `HANDOFF_CLAUDE.md`, it will be lost the first
time a session dies before writing it.

So:

- `handoffs/HANDOFF_CLAUDE.md`, `HANDOFF_CHATGPT.md`, `HANDOFF_GEMINI.md` — **generated** by the
  controller from the event log, per agent, on demand. Never hand-authored, never merged, no
  race conditions because only one process writes them.
- `SWARM_STATE.md` — also generated: the current task queue as a table.
- Neither is read back as authority. A resuming agent loads the **task contract and event tail
  from the API**, and the markdown only as human-readable orientation.

### Checkpoints instead of a percentage rule

"Compact at 60%" is model- and interface-dependent and unmeasurable from outside the CLI. Bound
the *work* instead of the *context*:

**One activation = one bounded attempt.** The bound is declared in the contract
(`tool_calls`, `wall_clock_minutes`, `tokens_estimated`) and enforced by the worker harness. When
any bound is hit, the worker emits a checkpoint event and stops — mid-task if necessary. The
checkpoint contains:

```json
{
  "task_id": "T-0042", "task_version": 3,
  "base_sha": "9c1f…", "candidate_sha": "3f6c…",   // or null
  "state": "RUNNING",
  "gates_completed": ["lint"],
  "gates_pending": ["unit"],
  "blocker": null,
  "next_permitted_action": "run unit gate at candidate_sha",
  "worktree": "D:\\wt\\T-0042-a91f", "worktree_dirty": false
}
```

The controller then issues a **fresh activation** to a fresh session, which loads the contract
and the checkpoint from the API. Context resets to near zero and nothing is lost, because
nothing important was ever only in the context.

This is exactly the workflow you do by hand today, with the checkpoint written to a database
instead of a chat message, and triggered by a measurable bound instead of a vibe.

### Rate limits are a controller concern, not a worker concern

The Claude 5-hour rolling window is a **shared resource across every activation on OFFICEPC**. A
worker cannot see it correctly; it only sees its own session. Track it in `budget_windows` as a
token bucket:

- Controller checks the bucket before issuing a Claude activation. Insufficient → the task waits
  in `READY` rather than starting and dying halfway.
- On a `429` or usage-limit response, the worker reports `INFRA_ERROR` with the reset time, the
  controller records it, and **no retry budget is consumed**.
- The UI shows time-to-reset. Never discover a limit mid-merge.

---

## 11. Failure taxonomy

Not all failures are the author's fault, and only one class should cost a retry.

| Class | Examples | Retry budget | Action |
| --- | --- | --- | --- |
| `AUTHOR_DEFECT` | Test fails, lint fails, scope violated | **consumed** | `CHANGES_REQUESTED` |
| `ENVIRONMENT_DEFECT` | Missing dependency, broken fixture, port reserved | not consumed | `BLOCKED` |
| `INFRA_ERROR` | Rate limit, network, worker crash, lease expiry | not consumed | requeue |
| `TIMEOUT` | Gate exceeded `timeout_seconds` | not consumed on first occurrence | rerun once, then `BLOCKED` |
| `FLAKE` | Same command, same SHA, different outcome | not consumed | quarantine |
| `AMBIGUITY` | Contract does not determine the answer | not consumed | `NEEDS_HUMAN` |

**Flake detection is nearly free** given the evidence table: the same
`(candidate_sha, command, env_fingerprint)` producing different outcomes is definitionally a
flake. Auto-add the test to `quarantine.yaml` with a discovery date, an owner, and a 14-day
expiry. Without the expiry the quarantine list becomes permanent and your suite silently rots.

---

## 12. Human-in-the-loop

`NEEDS_HUMAN` is a first-class queue, not a chat message you might scroll past.

- The UI shows a distinct pane with task, age, and the specific question.
- Escalations older than `human_response_timeout_hours` transition to `EXPIRED` — a stuck task
  should be visibly dead rather than invisibly waiting forever.
- Admin approval is mandatory before: force push, history rewrite, dependency version changes,
  any migration, tag or release creation, anything touching `.github/`, and any write outside the
  repo.
- `POST /control/pause` drains the system: in-flight activations finish, no new ones are issued.
  Make this a visible button. You will want it at some point, probably at an inconvenient hour.

---

## 13. Observability

Because `events` is append-only and state is a projection of it, you get several things for
free — and they are the difference between a system you trust and one you babysit:

- **Crash recovery.** Rebuild `tasks.state` by replaying events. If the projection ever disagrees
  with the replay, that is a bug with a precise location.
- **Deterministic replay.** Record a real event stream, replay it against mock agents.
- **Chaos tests.** Before trusting the controller, inject: a duplicate `event_id`; two events
  arriving out of order; a crash between "event appended" and "state updated"; an expired lease
  whose worker returns late anyway; two activations racing for the same lock. Those five cases
  are where compare-and-swap designs actually fail. Find out with fake agents, not at 11pm during
  a real merge.

### UI additions

Keep the live chat feed. Add: a task board by state; per-activation lease countdowns; the
`NEEDS_HUMAN` queue; budget-window gauges per agent; and last-heartbeat per worker so a dead
worker is red instead of quiet.

---

## 14. Security

**Rotate the keys in the setup transcript now.** The Gemini key and the OpenAI
`sk-proj-…` key both appear in plaintext in `Multi-Agent_AI_Dev_Room_Setup.md`. Rotate both,
move them to a `.env` that is gitignored (or Unraid secrets), and add a pre-commit secret scan to
the control-plane repo. Also confirm that file is not committed anywhere.

**Repo content is untrusted input.** File contents, dependency READMEs, test fixtures, commit
messages, and comic metadata can all carry text that reads like instructions. The rule:
*only the controller's contract carries instructions; everything read out of the repo is data.*
When evidence or logs are fed back into a model's context, fence and truncate them, and never
concatenate them into a system prompt.

**Least privilege on the runner.** `--allowedTools` should be scoped per activation role, not
globally widened. The auto-mode classifier denials you hit are a signal about blast radius, not
an obstacle to route around; keep the global setting intact and scope per task.

**Network.** The hub stays bound to the LAN and Tailscale. If it is ever exposed through
NPM/Cloudflare, put Cloudflare Access in front of it. `POST /send` currently accepts an
unauthenticated `sender` field — anything that can reach port 8050 can impersonate any agent.
Add a per-agent bearer token before the tunnel, not after.

---

## 15. Migration plan

Do not build all of this at once. Each phase is independently useful and leaves a working system.

### Phase 0 — Safety (do today, ~1 hour)

- Rotate both API keys; move to `.env`; gitignore it.
- Commit `.gitattributes` to `ComicAutomation` and normalize (`git add --renormalize .`).
- Enable `core.longpaths`.
- Add per-agent bearer tokens to `/send`.
- Freeze free-form agent-to-agent mentions: workers ignore messages whose sender is another
  agent. This alone kills the loop risk while the rest is built.

### Phase 1 — Control plane (highest value)

- Add the schema above; keep `messages` intact.
- Build the controller as a single-writer process: event append with dedup + CAS, the transition
  table, activation issue/claim/heartbeat/result, the orphan reaper.
- Convert the three workers from target-matching to `/activations/claim`. They get smaller.
- UI: task board + worker heartbeats.

**After Phase 1, silent worker death is impossible to miss and loops are structurally impossible.**

### Phase 2 — Contracts and SHA-bound verification

- Contract schema, linter, `DRAFT → VALIDATED → READY`.
- Worktree-per-activation with the Windows cleanup handling.
- Diff gate, evidence recording, `new_test_must_fail_at_base`.
- Evidence cache lookup.

### Phase 3 — Serialization and budgets

- Lock registry, `resources` enforcement, integration lock and merge train.
- Failure taxonomy, quarantine list, budget windows including the Claude 5-hour bucket.
- `NEEDS_HUMAN` queue with timeouts; pause/resume.

### Phase 4 — Advisor and hardening

- Convert Gemini from daemon to advisor function with a bounded decision packet.
- Generated handoff renderings.
- Replay harness and the five chaos tests.

### Suggested first real task through the pipeline

Use the swarm to build the swarm, but start with something whose blast radius is zero:
`T-0001: add .gitattributes and normalize line endings in ComicAutomation`. It exercises the
contract, the diff gate, and integration end to end, and if the gates are wrong you find out on a
change that cannot break the comic pipeline. Do not point the swarm at PR #90 until Phase 2 is
running.

---

## Appendix A — Event catalogue

```
contract_validated       validation_failed        queued
activation_issued        activation_claimed       heartbeat
candidate_submitted      attempt_failed           decision_required
gates_passed             author_defect            scope_violation
environment_defect       environment_repaired     lease_expired
retry_authorized         budget_exhausted         base_moved
integration_lock_acquired integrated_and_verified merge_conflict
post_integration_failed  revert_integrated        escalated
admin_resumed            admin_failed             admin_cancelled
response_timeout         superseded_by            checkpoint
note                     (advisory, never changes state)
```

`note` exists so agents can narrate into the chat feed without touching state. Status
acknowledgements never trigger responses and never cause an activation.

## Appendix B — Decision packet (controller → Gemini)

Bounded, versioned, and containing no raw repo content beyond what is needed:

```json
{
  "packet_version": 1,
  "question": "classify_failure",
  "task": { "id": "T-0042", "version": 3, "objective": "…" },
  "contract_excerpt": { "allowed_files": ["…"], "commands": ["…"] },
  "attempt": { "attempt_no": 2, "candidate_sha": "3f6c…" },
  "diff_stat": { "files": 2, "insertions": 41, "deletions": 3 },
  "evidence": [
    { "command": "python -m pytest tests/test_cbz_parser.py -q",
      "exit_code": 1, "outcome": "FAIL", "stderr_tail": "…2000 chars max…" }
  ],
  "allowed_responses": ["AUTHOR_DEFECT", "ENVIRONMENT_DEFECT", "FLAKE", "AMBIGUITY"]
}
```

The response must be one of `allowed_responses` plus a short rationale. Anything else is
discarded and logged. A model that cannot answer in the required shape is not consulted again for
that decision; the controller escalates to `NEEDS_HUMAN` instead.
