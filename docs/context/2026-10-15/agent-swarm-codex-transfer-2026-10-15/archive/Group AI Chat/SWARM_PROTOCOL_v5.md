# Swarm Operating Protocol v5

**Status:** implementation candidate
**Supersedes:** `SWARM_PROTOCOL_v4.md`
**Control-plane repo:** `claude-agent-hub`
**Target repo:** `ComicAutomation`
**Control plane:** Tower `agent-hub` service
**Execution host:** `OFFICEPC`

This protocol replaces conversational agent coordination with a deterministic, event-driven
control plane. Chat remains available for narration and questions, but chat messages never create
work, advance task state, release locks, or wake another model.

The controller and worker harnesses enforce this document. Prompt compliance is useful but is not
a safety boundary.

### Changes from v4

| # | Change | Reason |
| --- | --- | --- |
| 1 | `behavior_proof.mode` decided by the linter at validation time | v4's baseline mode fails collection whenever a test imports new API — the common case, not the edge case, and it escalated to a human every time |
| 2 | `integration_rejected` chargeability determined by an isolation re-run; path reservations after repeated invalidation | v4 could burn an author's retry budget for sibling merges landing first |
| 3 | Explicit integration queue ordering with aging | v4 serialized integration but nothing chose the next task; priority alone starves |
| 4 | Deadlines transmitted as remaining durations; harness uses a monotonic clock | Absolute timestamps computed on Tower and enforced on OFFICEPC drift |
| 5 | Evidence bodies uploaded content-addressed to the hub before a result is accepted | v4's evidence pointed at OFFICEPC temp paths; a reap or rebuild made every `COMPLETE` unprovable |
| 6 | `max_concurrent_activations` per execution host; integration takes an exclusive host slot | Everything runs on one 3900X; contention produced timeouts classified non-chargeable, so the system retried into the same contention |
| 7 | Protocol schema migration rule for in-flight tasks | v4 froze `schema_version` per task version but never said what happens on controller upgrade |
| 8 | Two operating modes: `SERIAL` and `CONCURRENT`, with `SERIAL` as the starting default | Most of the integration machinery exists to make concurrency safe; on one repo with one host and one human, concurrency may never be needed |

---

## 1. Non-negotiable invariants

1. The controller is the sole writer of authoritative task state.
2. Workers pull one controller-issued activation at a time. They are never activated by chat.
3. One activation performs one bounded attempt, submits one terminal result, and stops.
4. A worker cannot activate another worker.
5. Status acknowledgements and narration never produce activations.
6. Every worker result is bound to its authenticated identity, activation, task version, and
   expected state sequence.
7. Every candidate and verification result is bound to a full Git object ID.
8. Author self-checks are advisory. Only independent verifier evidence satisfies acceptance.
9. Administrative Git operations are serialized through one operator service.
10. A lock lease and an activation heartbeat never override a non-renewable hard deadline.
11. An expired owner cannot mutate a protected resource after ownership is reassigned.
12. Integration never releases its lock while repository state is uncertain.
13. A task can reach `COMPLETE` only when deterministic controller checks prove every required
    condition.
14. Undefined state transitions are rejected.
15. Duplicate requests are idempotent; conflicting replays are rejected.
16. No wall-clock timestamp is compared across hosts. Deadlines cross the boundary as durations.
17. Evidence is not acceptable until its content is durable on the control plane.
18. A task never consumes chargeable budget for a failure it did not cause.

---

## 2. Planes and roles

| Component | Authority | Prohibited |
| --- | --- | --- |
| Controller | Contracts, task state, activations, budgets, locks, transition validation, completion decisions, scheduling | LLM calls inside transition logic; repository authoring |
| Git operator | Worktree lifecycle, protected refs, merge objects, ref advancement, rollback, push, tag | Product-code authorship; unscoped conflict resolution |
| Gemini advisor | Draft decomposition, bounded design review, ambiguous-failure proposals | Direct state mutation; claims of local verification; autonomous polling |
| ChatGPT author | Scoped edits and commits in its allocated worktree; advisory targeted self-checks | Integration refs; authoritative acceptance; editing outside contract scope |
| Claude verifier | Independent SHA-bound gates and review evidence | Modifying the candidate being verified |
| Claude author | May author when explicitly assigned | Verifying the same task it authored |
| Admin | Policy, escalations, standing authorizations, cancellation, emergency pause | None within the host's governing safety policy |

The controller is deterministic. Gemini is invoked as a bounded function and returns a proposal;
the controller validates that proposal before any state changes.

Authoritative instructions come from the host's system and tool policies, Admin directives, the
frozen task contract, and explicitly trusted repository policy files (`trusted_policy_files`)
pinned at the contract's base SHA. All other repository content, logs, fixtures, commit messages,
and external text are untrusted data.

---

## 3. Operating modes

The controller runs in one of two modes, set by Admin policy and visible in the UI.

| | `SERIAL` (start here) | `CONCURRENT` |
| --- | --- | --- |
| `max_in_flight` | 1 non-terminal task past `VALIDATED` | policy value |
| Integration | Target tip always equals `base_sha`; fast-forward | Full saga (§11) |
| Merge invalidation | Cannot occur | Possible; §11.4 applies |
| Path reservations | Not needed | Required |
| Required phases | 0–2 | 0–4 |

`SERIAL` is not a degraded mode. It is the correct mode for one repository, one execution host,
and one human, and it removes most of the machinery in §11 while preserving every safety property
that addresses an observed failure: no loops, no silent worker death, SHA-bound evidence, enforced
scope, atomic results, bounded attempts.

**Promotion criterion.** Move to `CONCURRENT` only when measured queue depth justifies it: after
at least twenty completed tasks, if median time spent in `READY_INTEGRATION` exceeds median time
spent in `AUTHORING`, concurrency is buying something. Otherwise it is not.

The rest of this document specifies `CONCURRENT`. Everything in it applies to `SERIAL` except
§11.4 (merge invalidation), §11.5 (reservations), and §3 of the scheduler (aging), which are
unreachable when `max_in_flight = 1`.

---

## 4. Authoritative records

SQLite in WAL mode with foreign keys enabled. Only the controller process opens it for writing.
Every projection update and its event append occur in the same `BEGIN IMMEDIATE` transaction.

The implementation may normalize this schema, but it must preserve the constraints shown.

```sql
CREATE TABLE tasks (
  task_id          TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  objective        TEXT NOT NULL,
  priority         INTEGER NOT NULL DEFAULT 50,
  current_version  INTEGER NOT NULL,
  state            TEXT NOT NULL,
  state_seq        INTEGER NOT NULL DEFAULT 0,
  enqueued_at      REAL,                    -- set on first entry to READY_INTEGRATION; aging basis
  created_at       REAL NOT NULL,
  created_by       TEXT NOT NULL
);

CREATE TABLE task_versions (
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  version        INTEGER NOT NULL,
  contract_yaml  TEXT NOT NULL,
  contract_hash  TEXT NOT NULL,
  protocol_schema_version INTEGER NOT NULL,  -- frozen; see §17
  base_sha       TEXT NOT NULL,
  proof_mode     TEXT NOT NULL,              -- resolved by the linter; see §10
  created_at     REAL NOT NULL,
  created_by     TEXT NOT NULL,
  PRIMARY KEY (task_id, version)
);

CREATE TABLE task_deps (
  task_id      TEXT NOT NULL REFERENCES tasks(task_id),
  depends_on   TEXT NOT NULL REFERENCES tasks(task_id),
  kind         TEXT NOT NULL CHECK (kind IN ('blocks', 'prefer_after')),
  PRIMARY KEY (task_id, depends_on),
  CHECK (task_id <> depends_on)
);

CREATE TABLE activations (
  activation_id       TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL,
  task_version        INTEGER NOT NULL,
  agent               TEXT NOT NULL,
  host                TEXT NOT NULL,           -- execution host, for concurrency caps
  role                TEXT NOT NULL,
  stage               TEXT NOT NULL,
  attempt_no          INTEGER NOT NULL,
  chargeable_attempt  INTEGER NOT NULL DEFAULT 1,
  expected_branch     TEXT,
  expected_parent     TEXT,
  issued_at           REAL NOT NULL,           -- controller clock; never sent to the harness
  claimed_at          REAL,
  lease_expires_at    REAL NOT NULL,           -- controller clock
  hard_deadline_at    REAL NOT NULL,           -- controller clock
  heartbeat_at        REAL,
  status              TEXT NOT NULL,
  result_event_id     TEXT,
  result_request_hash TEXT,
  result_response     TEXT,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

CREATE TABLE events (
  seq              INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id         TEXT NOT NULL UNIQUE,
  task_id          TEXT NOT NULL,
  task_version     INTEGER NOT NULL,
  activation_id    TEXT REFERENCES activations(activation_id),
  source_event_id  TEXT REFERENCES events(event_id),
  actor            TEXT NOT NULL,
  kind             TEXT NOT NULL,
  from_state       TEXT,
  to_state         TEXT,
  payload_json     TEXT NOT NULL DEFAULT '{}',
  created_at       REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

CREATE TABLE evidence (
  evidence_id       TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL,
  task_version      INTEGER NOT NULL,
  activation_id     TEXT NOT NULL REFERENCES activations(activation_id),
  authoritative     INTEGER NOT NULL CHECK (authoritative IN (0, 1)),
  target_sha        TEXT NOT NULL,
  gate_id           TEXT NOT NULL,
  command_hash      TEXT NOT NULL,
  contract_hash     TEXT NOT NULL,
  shell             TEXT NOT NULL,
  hermetic          INTEGER NOT NULL DEFAULT 0,
  worktree_clean    INTEGER NOT NULL,
  exit_code         INTEGER,
  duration_ms       INTEGER,
  environment_hash  TEXT NOT NULL,
  fixture_hash      TEXT,
  stdout_blob       TEXT REFERENCES evidence_blobs(blob_hash),  -- durable, on control plane
  stderr_blob       TEXT REFERENCES evidence_blobs(blob_hash),
  local_log_path    TEXT,                     -- convenience only; never the record
  outcome           TEXT NOT NULL,
  created_at        REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

CREATE TABLE evidence_blobs (
  blob_hash    TEXT PRIMARY KEY,             -- sha256 of stored bytes
  byte_length  INTEGER NOT NULL,
  truncated    INTEGER NOT NULL DEFAULT 0,
  stored_path  TEXT NOT NULL,                -- appdata, content-addressed, on Tower
  created_at   REAL NOT NULL
);

CREATE TABLE resource_epochs (
  lock_name   TEXT PRIMARY KEY,
  next_epoch  INTEGER NOT NULL
);

CREATE TABLE locks (
  lock_name      TEXT PRIMARY KEY REFERENCES resource_epochs(lock_name),
  holder         TEXT NOT NULL,
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  fence_epoch    INTEGER NOT NULL,
  acquired_at    REAL NOT NULL,
  expires_at     REAL NOT NULL
);

-- CONCURRENT mode only. Time-boxed claim on a path set after repeated
-- merge invalidation, so a task cannot be starved by siblings.
CREATE TABLE path_reservations (
  reservation_id TEXT PRIMARY KEY,
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  paths_json     TEXT NOT NULL,
  granted_at     REAL NOT NULL,
  expires_at     REAL NOT NULL
);

CREATE TABLE integration_runs (
  integration_id          TEXT PRIMARY KEY,
  task_id                 TEXT NOT NULL,
  task_version            INTEGER NOT NULL,
  candidate_sha           TEXT NOT NULL,
  expected_target_tip     TEXT NOT NULL,
  proposed_sha            TEXT,
  prior_remote_tip        TEXT,
  phase                   TEXT NOT NULL,
  fence_epoch             INTEGER NOT NULL,
  repository_stable       INTEGER NOT NULL DEFAULT 1,
  invalidation_count      INTEGER NOT NULL DEFAULT 0,
  created_at              REAL NOT NULL,
  updated_at              REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

CREATE TABLE host_capacity (
  host            TEXT PRIMARY KEY,
  max_concurrent  INTEGER NOT NULL,
  exclusive_holder TEXT                      -- activation_id holding the exclusive host slot
);
```

Budget accounting stores both total activations and chargeable attempts. Infrastructure errors,
lease loss, rate limiting, the first timeout, and non-author integration rejections create another
activation without consuming the task's author-defect retry budget.

---

## 5. Identity, API, and atomicity

Every endpoint requires an authenticated per-component credential. The server derives the actor
from the credential; client-supplied identity fields are ignored. Authorization requires:

```text
authenticated agent == activation.agent
activation belongs to the requested task and version
activation role permits the requested operation
activation has not passed hard_deadline_at
task state and state_seq match the request
```

Core endpoints:

```text
POST /tasks
POST /tasks/{id}/validate
POST /tasks/{id}/versions
GET  /tasks/{id}
GET  /tasks?state=...

POST /activations/claim
POST /activations/{id}/heartbeat
POST /evidence/blobs                 -- content-addressed upload, returns blob_hash
POST /activations/{id}/evidence      -- references blob_hash values; never file paths
POST /activations/{id}/result

POST /control/pause
POST /control/resume
GET  /control/status
```

Workers never call a generic state-changing `/events` endpoint. Controller and Admin operations
use their own authenticated commands, which append an event and update the projection atomically.

### Clocks never cross the host boundary

The controller stores absolute times on its own clock. Responses to `/activations/claim` and
`/activations/{id}/heartbeat` carry **durations**, not timestamps:

```json
{
  "activation_id": "…",
  "lease_seconds_remaining": 300,
  "hard_deadline_seconds_remaining": 4820,
  "server_seq": 918
}
```

The harness converts these against its own monotonic clock (`time.monotonic()`, never
`time.time()`), and re-derives on every heartbeat response. No comparison is ever made between an
OFFICEPC timestamp and a Tower timestamp. The controller remains authoritative: a result rejected
for deadline expiry is final regardless of what the harness believed.

### Atomic worker result

`POST /activations/{id}/result` uses this order inside one transaction:

1. Authenticate and prove the activation belongs to the caller.
2. Canonicalize the request and calculate `result_request_hash`.
3. If the activation already has a result: matching hash returns the cached response with `200`;
   a different hash is rejected as `409 conflicting_replay` and logged as a security event.
4. Require live activation status, an unexpired lease, and an unexpired hard deadline.
5. Validate task version, expected state, `state_seq`, event kind, and role.
6. Verify that every evidence row referenced by this result has durable blobs (§9). A result
   citing evidence whose blobs are absent or incomplete is rejected as `409 evidence_not_durable`.
7. Run event-specific deterministic precondition checks.
8. Append the event and update the task projection.
9. Mark the activation `DONE`; save request hash and response.
10. Release the host slot; release only locks whose release policy permits it. Integration locks
    are never released while `repository_stable = 0` or the saga remains active.
11. Commit.

Incremental evidence submission does not advance state. Evidence rows are immutable. A worker
cannot satisfy a gate by emitting a passing event; the controller computes gate completion from
evidence rows.

---

## 6. Scheduling and capacity

### Host capacity

Every activation is issued against a host. The controller does not issue an activation when

```text
active_activations(host) >= host_capacity.max_concurrent
  OR host_capacity.exclusive_holder IS NOT NULL
```

OFFICEPC starts at `max_concurrent = 2`. An integration saga takes the **exclusive host slot**:
no author self-check or verification gate runs while integration gates run. This matters because
contention-induced timeouts are classified `INFRA_ERROR` and are non-chargeable, so without a cap
the system retries directly into the contention that caused the failure.

### Integration queue order (`CONCURRENT` mode)

`READY_INTEGRATION` tasks are ordered by a deterministic score, recomputed at each saga start:

```text
score = priority + (age_minutes / aging_divisor) + (25 × invalidation_count)
```

with `aging_divisor` an Admin policy value (start at 30). Highest score integrates next. Ties
break on `enqueued_at`, then `task_id`. Aging and the invalidation term together guarantee that a
repeatedly invalidated or low-priority task eventually reaches the front. Without them, priority
alone starves work indefinitely — the same defect as a rigid `base_sha` rule, relocated into the
scheduler.

---

## 7. Task contract

Contracts are immutable per version and live in controller storage. Commands are never loaded from
the candidate worktree.

```yaml
schema_version: 5
task_id: T-0042
version: 1
title: Harden CBZ parser against malformed ComicInfo.xml
objective: Reject malformed metadata without changing established public behavior.

roles:
  author: chatgpt
  verifier: claude

execution_host: OFFICEPC

repo:
  path: "D:\\Documents\\ComicAutomation"
  remote: origin
  target_branch: master            # verified at bootstrap; the linter confirms it exists
  base_sha: "0123456789abcdef0123456789abcdef01234567"

trusted_policy_files:
  - AGENTS.md
  - CLAUDE.md

scope:
  allowed_files:
    - parsers/cbz_parser.py
    - tests/test_cbz_parser.py
  allowed_dirs: []
  forbidden_paths:
    - .github/**
    - .gitattributes
    - requirements*.txt
    - pyproject.toml
    - "**/migrations/**"
  allow_new_files: false
  allow_deletions: false
  allow_case_only_renames: false

author_self_checks:
  - shell: pwsh
    command: "python -m pytest tests/test_cbz_parser.py -q"
    timeout_seconds: 300

verification:
  gates:
    - id: unit
      stage: review
      shell: pwsh
      command: "python -m pytest tests/test_cbz_parser.py -q"
      expected_exit: 0
      timeout_seconds: 300
      hermetic: false
    - id: suite
      stage: integration
      shell: pwsh
      command: "python -m pytest -q"
      expected_exit: 0
      timeout_seconds: 1800
      hermetic: false

behavior_proof:
  mode: auto                       # auto | baseline | sabotage | both — resolved by the linter
  selectors:
    - tests/test_cbz_parser.py::test_rejects_non_utf8_comicinfo
  baseline:
    expected: FAIL
    acceptable_exception_types: [AssertionError]
    acceptable_message_patterns:
      - "expected malformed ComicInfo.xml to be rejected"
  candidate:
    expected: PASS
  sabotage:
    patch_id: null                 # required when the linter resolves mode to sabotage or both

resources:
  database: isolated-test-db
  library_root: forbidden
  external_writes: forbidden
  ports: []
  docker_containers: []
  temp_dir: "D:\\swarm-tmp\\{task_id}\\{activation_id}"
  locks: []

budgets:
  author_chargeable_attempts: 3
  verifier_chargeable_attempts: 3
  activation_hard_minutes: 90
  tool_calls: 60
  estimated_tokens: 150000

authorization:
  profile: comicautomation-standing
  require_admin:
    - force_push
    - history_rewrite
    - release_or_tag
    - write_outside_repo

escalation:
  human_response_timeout_hours: 48
```

### Contract linter

`DRAFT → VALIDATED` verifies schema, full object IDs, branch existence on the remote, dependency
acyclicity, role separation, scope intersections, command availability on the execution host,
behavior-proof selector syntax, registered locks, budgets, authorization profile, declared
execution host, and absence of overlap with unordered active tasks.

It additionally **resolves `behavior_proof.mode`** and freezes the result in
`task_versions.proof_mode` (§10). A contract cannot enter `READY_AUTHOR` with `mode: auto`
unresolved.

A standing authorization profile is an Admin-owned, versioned policy record. It can preauthorize
operations such as ordinary migrations where that authority was already granted. It cannot
override host safety controls or silently expand a task's declared scope.

---

## 8. State machine

### States

| State | Meaning |
| --- | --- |
| `DRAFT` | Contract is being prepared |
| `VALIDATED` | Contract passed deterministic linting |
| `READY_AUTHOR` | Dependencies and capacity permit an author activation |
| `AUTHOR_ASSIGNED` | Author activation issued but not claimed |
| `AUTHORING` | Author activation running |
| `AUTHOR_PAUSED` | Safe WIP checkpoint captured; resumable |
| `AUTHOR_BLOCKED` | Author-stage environment problem |
| `READY_REVIEW` | Candidate submitted and awaiting verifier |
| `REVIEW_ASSIGNED` | Verifier activation issued but not claimed |
| `REVIEWING` | Verifier activation running |
| `REVIEW_PAUSED` | Review checkpoint captured; resumable |
| `REVIEW_BLOCKED` | Review-stage environment problem |
| `CHANGES_REQUESTED` | Candidate needs author correction (chargeable or not; §12) |
| `READY_INTEGRATION` | Controller proved all review requirements |
| `INTEGRATING` | Serialized integration saga owns the integration fence and host slot |
| `REVERTING` | Target was mutated and the same saga is restoring it |
| `NEEDS_HUMAN` | A specific Admin decision is required |
| `COMPLETE` | Tested object integrated and refs verified |
| `FAILED` | Unrecoverable or budget-exhausted |
| `CANCELLED` | Cancelled by Admin |
| `SUPERSEDED` | Replaced by another task/version |
| `EXPIRED` | Human escalation expired |
| `REVERTED` | Previously complete change was later reverted |

Terminal: `COMPLETE`, `FAILED`, `CANCELLED`, `SUPERSEDED`, `EXPIRED`, `REVERTED`.

### Principal transitions

| From | Event | To | Authority |
| --- | --- | --- | --- |
| `DRAFT` | `contract_validated` | `VALIDATED` | controller |
| `DRAFT` | `validation_failed` | `DRAFT` | controller |
| `VALIDATED` | `queued` | `READY_AUTHOR` | controller |
| `READY_AUTHOR` | `author_activation_issued` | `AUTHOR_ASSIGNED` | controller |
| `AUTHOR_ASSIGNED` | `activation_claimed` | `AUTHORING` | authenticated author |
| `AUTHOR_ASSIGNED` | `lease_expired` | `READY_AUTHOR` | controller |
| `AUTHOR_ASSIGNED` | `hard_deadline_reached` | `READY_AUTHOR` | controller |
| `AUTHORING` | `candidate_submitted` | `READY_REVIEW` | author |
| `AUTHORING` | `checkpoint_captured` | `AUTHOR_PAUSED` | controller/operator |
| `AUTHORING` | `environment_defect` | `AUTHOR_BLOCKED` | author |
| `AUTHORING` | `author_defect` | `CHANGES_REQUESTED` | author/controller |
| `AUTHORING` | `lease_expired` | `READY_AUTHOR` | controller |
| `AUTHORING` | `hard_deadline_reached` | `READY_AUTHOR` or `AUTHOR_PAUSED` | controller/operator |
| `AUTHOR_PAUSED` | `author_activation_issued` | `AUTHOR_ASSIGNED` | controller |
| `AUTHOR_BLOCKED` | `environment_repaired` | `READY_AUTHOR` | controller |
| `READY_REVIEW` | `review_activation_issued` | `REVIEW_ASSIGNED` | controller |
| `REVIEW_ASSIGNED` | `activation_claimed` | `REVIEWING` | authenticated verifier |
| `REVIEW_ASSIGNED` | `lease_expired` | `READY_REVIEW` | controller |
| `REVIEW_ASSIGNED` | `hard_deadline_reached` | `READY_REVIEW` | controller |
| `REVIEWING` | `review_requirements_satisfied` | `READY_INTEGRATION` | controller |
| `REVIEWING` | `author_defect` | `CHANGES_REQUESTED` | verifier/controller |
| `REVIEWING` | `checkpoint_captured` | `REVIEW_PAUSED` | controller/operator |
| `REVIEWING` | `environment_defect` | `REVIEW_BLOCKED` | verifier |
| `REVIEWING` | `proof_inconclusive` | `NEEDS_HUMAN` | controller |
| `REVIEWING` | `decision_required` | `NEEDS_HUMAN` | verifier/controller |
| `REVIEWING` | `lease_expired` | `READY_REVIEW` | controller |
| `REVIEWING` | `hard_deadline_reached` | `READY_REVIEW` or `REVIEW_PAUSED` | controller/operator |
| `REVIEW_PAUSED` | `review_activation_issued` | `REVIEW_ASSIGNED` | controller |
| `REVIEW_BLOCKED` | `environment_repaired` | `READY_REVIEW` | controller |
| `CHANGES_REQUESTED` | `retry_authorized` | `READY_AUTHOR` | controller |
| `CHANGES_REQUESTED` | `budget_exhausted` | `NEEDS_HUMAN` | controller |
| `READY_INTEGRATION` | `integration_started` | `INTEGRATING` | controller/operator |
| `READY_INTEGRATION` | `reservation_granted` | `READY_INTEGRATION` | controller |
| `INTEGRATING` | `integration_rejected` | `CHANGES_REQUESTED` | controller/operator |
| `INTEGRATING` | `integration_completed` | `COMPLETE` | controller |
| `INTEGRATING` | `rollback_started` | `REVERTING` | controller/operator |
| `REVERTING` | `rollback_completed` | `CHANGES_REQUESTED` | controller/operator |
| `REVERTING` | `repository_uncertain` | `NEEDS_HUMAN` | controller/operator |
| `COMPLETE` | `regression_reverted` | `REVERTED` | Admin/controller |

Every nonterminal state also accepts Admin cancellation or supersession. `NEEDS_HUMAN` has no
generic resume. The Admin response selects one explicit validated action: `return_to_author`,
`return_to_review`, `create_contract_version`, `fail`, or `cancel`.

### Deterministic completion predicates

`review_requirements_satisfied` is emitted only if:

- the candidate is the current candidate for the current task version;
- the diff gate passed;
- every required review gate has authoritative `PASS` evidence from the assigned verifier;
- evidence targets the exact candidate SHA and current contract hash;
- all evidence blobs are durable on the control plane;
- the behavior proof required by `proof_mode` succeeded;
- no unresolved scope violation, inconclusive proof, or flake report exists.

`integration_completed` is emitted only if:

- every integration gate passed against the exact proposed integration SHA;
- the saga reports `repository_stable = 1`;
- protected local and required remote refs equal that SHA;
- ref advancement used compare-and-swap against the recorded prior tip;
- required evidence is durable.

---

## 9. Evidence durability

Evidence is not acceptable until its content lives on the control plane. OFFICEPC temp
directories are reaped, and a `COMPLETE` whose proof is a path on a workstation is not proof.

1. The harness captures stdout and stderr per gate.
2. It truncates each stream to `head_bytes + tail_bytes` (defaults 128 KiB + 128 KiB) with an
   explicit elision marker, and sets `truncated = 1`.
3. It uploads each stream to `POST /evidence/blobs`, which stores it content-addressed under
   appdata on Tower and returns `blob_hash`.
4. `POST /activations/{id}/evidence` references `blob_hash` values. File paths may be recorded in
   `local_log_path` for convenience but are never the record.
5. `POST /activations/{id}/result` rejects any result whose cited evidence has missing or
   incomplete blobs (`409 evidence_not_durable`).

Blob retention follows task retention: blobs referenced by a task in a terminal state are kept for
the Admin-configured retention window, then garbage-collected by reference count.

---

## 10. Behavior proof

Behavior proof executes only named selectors. Two proof mechanisms exist and the linter chooses
between them at validation time — never at review time.

### Linter resolution of `mode: auto`

The linter resolves every symbol imported by the changed test files against `base_sha`:

```text
all imported symbols resolve at base_sha   -> mode = baseline
any imported symbol is new at candidate    -> mode = sabotage  (patch_id required)
contract requests both                     -> mode = both
```

This is the fix for v4's most common escalation. A test for genuinely new functionality imports a
symbol that does not exist at `base_sha`, so the baseline run fails at collection — which v4
classified `INCONCLUSIVE` and escalated to a human. That was the normal case, not the exception.
Resolving the mode at contract-validation time costs nothing and never spends an author and a
verifier activation before discovering the contract could not be proven as written.

### Baseline mode

Apply the candidate's changed test files to a disposable worktree at `base_sha`, execute only the
named selectors, and require `FAIL` matching the declared exception type and message pattern.
Collection, import, fixture, environment, and usage errors are `INCONCLUSIVE` →
`proof_inconclusive` → `NEEDS_HUMAN`. Under §10's linter resolution these should now be rare and
each one indicates a genuine contract problem.

Then execute the selectors at the candidate SHA and require `PASS`.

### Sabotage mode

Apply a reviewed, machine-readable sabotage patch (`patch_id`, stored with the contract) to a
disposable worktree at the candidate SHA, disabling the guard the task added, and prove the named
selectors fail. Then prove they pass unsabotaged.

Sabotage is the stronger proof: baseline-fail/candidate-pass shows the test distinguishes the
change, while sabotage shows the test depends on the specific guard. Neither proves the requested
semantics are correct; independent design review remains required where the contract calls for it.

### Evidence caching

Disabled by default. Permitted only for a gate explicitly declared hermetic, with cache key:

```text
target SHA + gate ID + command hash + contract hash + environment hash + fixture hash
```

Integration evidence is never cached. Differing outcomes constitute `FLAKE_SUSPECTED` only when
that entire identity tuple matches. Flake-suspected tests are never automatically quarantined;
quarantine requires a separate task with an owner, justification, review, and expiry.

---

## 11. Git isolation, integration, and invalidation

### 11.1 Worktrees and candidates

Each author attempt receives a unique worktree and branch:

```text
D:\wt\{task_id}-{activation_id}
swarm/{task_id}/v{version}/a{attempt}
```

Ancestry modes recorded in the contract: `squash` (candidate's direct parent is `base_sha`) or
`stacked` (parent is the previous candidate, while gates evaluate the whole `base_sha..candidate`
change).

The object-level diff gate computes `git diff --name-status base_sha candidate_sha` and proves
changed paths are a subset of allowed files and directories. It rejects forbidden paths,
unauthorized merges, submodule changes, escaping symlinks, generated artifacts, prohibited
deletions, and prohibited case-only renames.

The verifier uses a detached clean worktree at the exact candidate SHA. Author self-check evidence
is `authoritative = 0`; verifier evidence is `authoritative = 1`.

### 11.2 Runtime isolation

Worktrees do not isolate databases, ports, external services, environment variables, temp roots,
Docker names, shared caches, registry state, or the authoritative comic library on `X:`. Contracts
declare these resources and the harness enforces their locks for author self-checks as well as
verification. `external_writes: forbidden` and `library_root: forbidden` are defaults; exceptions
must be authorized and serialized.

Fence epochs are monotonic **per protected resource**. Releasing a lock does not reset its epoch.
The consumer of a protected resource rejects an operation whose epoch is not the currently active
epoch for that resource, so an unrelated database lock cannot invalidate an integration fence.

### 11.3 Integration saga

One saga at a time under the `integration` lock and the exclusive host slot.

1. Record current protected target tip `T` and candidate `X`.
2. Create a scratch integration worktree at `T`.
3. Merge `X` without resolving conflicts. A conflict creates a separate authored
   conflict-resolution task; the integrator never edits through it silently.
4. Record proposed integration SHA `P`; `repository_stable = 1` because protected refs have not
   moved.
5. Re-run scope and contract-invalidation checks against `T..P` (§11.4).
6. Run every integration gate against exactly `P`.
7. If a gate fails before protected refs move, discard the scratch worktree and emit
   `integration_rejected`. No rollback state is required.
8. Advance the local protected ref with compare-and-swap:
   `git update-ref refs/heads/{target_branch} P T`
9. Push the exact tested object against the recorded expected remote tip. Never create a fresh
   merge during push or integration.
10. Verify every required local and remote ref equals `P`.
11. Persist evidence and emit `integration_completed`.
12. Release the integration lock and host slot only after the saga is durable and
    `repository_stable = 1`.

If a protected ref moved and a later step fails: set `repository_stable = 0`, transition to
`REVERTING`, and **keep the lock**. The same deterministic saga attempts compare-and-swap
restoration to the recorded prior tip, then either proves all protected refs stable and emits
`rollback_completed`, or emits `repository_uncertain`, retains the lock, globally pauses protected
Git operations, and creates a `NEEDS_HUMAN` incident.

Reproducible merge timestamps are unnecessary: the system tests and advances the exact existing
object `P` and never reconstructs it after testing.

### 11.4 Integration rejection is not automatically the author's fault

`integration_rejected` sends the task to `CHANGES_REQUESTED`, but chargeability is determined by
an isolation re-run, not assumed:

```text
re-run the failing integration gate against candidate_sha alone
  fails there too   -> chargeable_attempt = 1   (genuine author defect)
  passes at X, fails at P -> chargeable_attempt = 0  (interaction defect)
```

An interaction defect is recorded on the integration run, increments `invalidation_count`, and may
warrant a new task rather than a retry — the change was correct in isolation and the conflict is
between two correct changes. Without this rule a task burns its retry budget because siblings
landed first, which is the same starvation the rigid `base_sha` rule produced, moved downstream.

Scope invalidation by merge (`T..P` touches files outside the contract's allowed set because
intervening commits modified them) is likewise `chargeable_attempt = 0`.

### 11.5 Path reservations

When `invalidation_count` reaches the Admin policy threshold (start at 2), the controller grants
the task a `path_reservations` row over its `allowed_files` with a bounded expiry (start at 60
minutes). While the reservation is live, any other task whose scope intersects those paths waits
at `READY_INTEGRATION` regardless of score. Reservations expire unconditionally; they are a
starvation guard, not a lock.

---

## 12. Failures and human decisions

| Failure | Chargeable | Default outcome |
| --- | --- | --- |
| Author defect, lint/test failure, scope violation | yes | `CHANGES_REQUESTED` |
| Integration gate failure reproducing at `candidate_sha` | yes | `CHANGES_REQUESTED` |
| Integration gate failure only at `P` (interaction) | no | `CHANGES_REQUESTED` + invalidation |
| Scope invalidated by intervening merge | no | `CHANGES_REQUESTED` + invalidation |
| Environment defect | no | stage-specific blocked state |
| Network / rate limit / worker crash | no | return to the same ready stage |
| Host contention timeout | no | requeue behind the capacity cap |
| First gate timeout | no | one replacement activation |
| Repeated gate timeout | no | stage-specific blocked state |
| Inconclusive behavior proof | no | `NEEDS_HUMAN` |
| Flake suspected under identical evidence identity | no | investigation/escalation |
| Contract ambiguity | no | `NEEDS_HUMAN` |
| Repository state uncertain | no | global Git pause + `NEEDS_HUMAN` |

Every human escalation contains one bounded question and enumerated allowed resolutions. A human
response is an authenticated command, not a chat mention. It returns the task to an explicit stage
or creates a new frozen contract version; it never uses a generic resume.

---

## 13. Activations, leases, and checkpoints

An activation has a renewable liveness lease and an immutable hard deadline. A dedicated harness
thread sends heartbeats, independent of model and subprocess execution, and no heartbeat extends
the hard deadline. Both are tracked as durations against the harness's monotonic clock (§5).

At the deadline the harness cancels child processes, requests a safe checkpoint when the stage
permits it, submits its final result, and stops. Use the paused state only when a valid checkpoint
was durably captured in the same controller transaction; otherwise return to the stage's ready
state. Lease or deadline recovery quarantines the abandoned worktree before a new activation is
issued. A late process may continue writing only to that quarantined worktree; its state changes
and candidate submissions are rejected.

Workers claim at most one activation and do not claim again until the current invocation exits.
Infrastructure replacement activations set `chargeable_attempt = 0`.

### Safe author checkpoint

Accepted only after the Git operator:

1. Stops further author writes.
2. Captures the allocated worktree as a WIP commit under
   `refs/swarm-checkpoints/{task}/{version}/{activation}`.
3. Records WIP SHA, parent SHA, changed paths, and patch hash.
4. Confirms the worktree is clean after capture.
5. Appends `checkpoint_captured` atomically with the transition to `AUTHOR_PAUSED`.

The WIP commit is not a candidate and cannot be reviewed or integrated. A replacement author
activation receives the checkpoint ref and resumes in the same scoped worktree or a new worktree
created from that WIP SHA.

Review checkpoints contain completed gate IDs and immutable evidence IDs. A replacement verifier
reuses only eligible hermetic evidence; all other pending or interrupted gates rerun.

Integration is not model-checkpointable. The saga either reaches a stable outcome or holds the
integration lock and globally pauses protected Git operations for recovery.

---

## 14. Rate limits and budgets

The Claude 5-hour rolling window is a resource shared across every activation on the execution
host; a worker sees only its own session. The controller tracks it and checks the bucket before
issuing an activation — insufficient headroom leaves the task in its ready state rather than
starting work that will die halfway. A rate-limit response is reported as an infrastructure error
with a reset time and consumes no chargeable budget. Time-to-reset is visible in the UI.

Contract budgets bound the work, not the context: `activation_hard_minutes`, `tool_calls`, and
`estimated_tokens` are enforced by the harness. When a bound is hit the harness checkpoints and
stops, and a fresh activation resumes from the contract and checkpoint. Nothing important ever
lives only in a model's context.

---

## 15. Security

1. Revoke and replace any API key that appeared in plaintext. Deleting it is insufficient.
2. Inspect Git history and retained document and chat copies to determine exposure.
3. Store replacement credentials in managed secrets or a protected environment file excluded from
   version control.
4. Authenticate every endpoint, including chat endpoints; authorize by role and activation.
5. Keep the hub on LAN/Tailscale unless a reviewed access layer protects it.
6. Fence and truncate untrusted repository and log content before sending it to a model. Evidence
   blobs are data, never instructions.
7. Scope tools and filesystem access per activation.
8. Record every protected operation with actor, task, activation, contract hash, and fence epoch.

---

## 16. Windows and ComicAutomation rules

- Confirm the actual remote, target branch, and repository path during bootstrap; contracts use
  the verified values. Project history indicates `master`, not `main`.
- Keep worktree roots short (`D:\wt\…`) and check free space before creation. Nothing swarm-related
  on `G:`.
- Do not perform repository-wide line-ending normalization during swarm bootstrap. The diff gate
  compares committed objects and is unaffected by `core.autocrlf`.
- Treat a newly created dirty worktree as an infrastructure defect; investigate the existing
  `.gitattributes` policy separately, as its own reviewed task.
- Capture native-command exit codes, stdout, and stderr separately under the declared shell. Never
  infer failure from non-empty stderr.
- Use UTF-8 subprocess decoding with replacement for undecodable diagnostic bytes; set
  `PYTHONIOENCODING=utf-8` in the harness rather than relying on the launching shell.
- Retry targeted worktree cleanup, then mark residue for the reaper. Never delete an unresolved
  broad path.
- Check reserved port ranges before tests and distinguish reservation from product failure.
- Never allow ordinary test contracts to read or write the authoritative `X:` library.

---

## 17. Protocol versioning

`task_versions.protocol_schema_version` is frozen when a version is created. On controller upgrade:

- in-flight tasks run to a terminal state under their frozen schema;
- new task versions use the new schema;
- the controller refuses to start if it finds a non-terminal task at an unsupported schema, rather
  than silently reinterpreting it.

---

## 18. Observability and generated handoffs

The UI shows the task board, operating mode, current task version, candidate and integration SHAs,
lease and hard-deadline countdowns, worker heartbeats, resource locks and epochs, host capacity
utilization, integration queue order with scores, budgets, evidence, and the `NEEDS_HUMAN` queue.

`HANDOFF_CLAUDE.md`, `HANDOFF_CHATGPT.md`, `HANDOFF_GEMINI.md`, and `SWARM_STATE.md` are generated
views of the database. They are never authoritative and are never read back to mutate state. A
resuming worker loads its contract, activation, checkpoint, and relevant event tail from the API.

### Required deterministic tests

- duplicate identical result; conflicting result replay;
- stale task version and stale `state_seq`;
- wrong authenticated worker or role;
- crash before and after transaction commit;
- heartbeat alive past hard deadline;
- clock skew: harness clock ahead of and behind the controller by ±5 minutes;
- author and review checkpoint recovery;
- stage-correct repair from both blocked states;
- late result after lease expiry; quarantined worktree write attempt;
- stale fence after lock reassignment;
- unrelated resource epoch not invalidating integration;
- result citing evidence with missing blobs;
- integration crash before ref movement;
- integration crash after local movement and before remote confirmation;
- external target movement during compare-and-swap;
- integration rejection that reproduces at `candidate_sha` vs one that does not;
- starvation: a low-priority task repeatedly invalidated must integrate within a bounded number of
  cycles;
- host capacity cap prevents issuance; exclusive slot excludes concurrent gates;
- required evidence missing, stale, advisory, or bound to the wrong SHA;
- event-log replay exactly matching task projections.

---

## 19. Rollout

### Phase 0 — Immediate containment

1. Rotate exposed credentials and inspect their exposure history.
2. Authenticate every endpoint and bind actor identity server-side.
3. Make workers ignore agent-authored chat messages for activation purposes.
4. Add a visible global pause and verify it prevents new activations.

### Phase 1 — Controller core

1. Schema, atomic controller/Admin transitions, atomic worker results.
2. Idempotency hashes, CAS, leases as durations, hard deadlines, stage-specific recovery.
3. Host capacity accounting.
4. Convert workers to pull exactly one activation.
5. Pass the deterministic transition, replay, identity, clock-skew, and crash tests.

### Phase 2 — Worktrees and verification

1. Operator-managed worktrees and scoped author branches.
2. Object-level diff gates and candidate ancestry validation.
3. Evidence blob upload and the durability predicate.
4. Authoritative evidence predicates and behavior proof, including linter mode resolution.
5. Safe author and reviewer checkpoint capture and resumption.

**Stop here and run in `SERIAL` mode.** Complete at least twenty real tasks before deciding
whether Phase 3 is needed. Record, per task: wall-clock duration, chargeable attempts, time in
`READY_INTEGRATION`, and human interventions. If median `READY_INTEGRATION` time does not exceed
median `AUTHORING` time, concurrency is not the bottleneck and Phase 3 is unnecessary work.

### Phase 3 — Concurrency and integration safety (only if the measurement justifies it)

1. Per-resource fence epochs and the serialized integration saga.
2. Compare-and-swap ref advancement and recovery from every crash point.
3. Invalidation classification, path reservations, and integration queue aging.
4. Verify the integration lock cannot be released while repository state is uncertain.

### Phase 4 — Budgets, advisor, and UI

1. Chargeable-attempt accounting, rate-limit windows, bounded advisor packets.
2. Generated handoff views.
3. Task, escalation, deadline, evidence, lock, and queue views.

### Pilot acceptance

Use one leaf-module guard and one named behavior test in files untouched by open work. Do not use
`.gitattributes`, migrations, production databases, the authoritative comic library, or PR #90 as
the pilot.

The pilot succeeds only when fault injection proves every safety layer is load-bearing, including
duplicate delivery, worker death, stale fencing, interrupted checkpoints, failed integration,
clock skew, and controller restart and replay.

---

## Appendix A — Event catalogue

```text
contract_validated         validation_failed
queued                     author_activation_issued
review_activation_issued   activation_claimed
candidate_submitted        checkpoint_captured
environment_defect         environment_repaired
author_defect              retry_authorized
budget_exhausted           review_requirements_satisfied
proof_inconclusive         decision_required
integration_started        integration_rejected
integration_completed      reservation_granted
rollback_started           rollback_completed
repository_uncertain       lease_expired
hard_deadline_reached      regression_reverted
return_to_author           return_to_review
create_contract_version    admin_failed
admin_cancelled            superseded
note
```

`note` is advisory and never advances state. No event activates a worker unless the deterministic
transition action explicitly issues an activation.

## Appendix B — Advisor boundary

Each advisor call carries a schema version, one bounded question, an explicit response schema, and
a list of allowed proposals. The advisor receives only the repository map, contract excerpts,
diff and evidence excerpts, and prior decisions necessary for that question. Decomposition
questions receive a repository map and open-task scopes; triage questions receive a failure packet.
The controller applies no proposal that violates policy, authorization, state, scope, or
deterministic evidence requirements. Malformed output is logged once and then escalated; the
advisor is not called repeatedly for the same decision.

## Appendix C — Open questions for review

1. `max_concurrent = 2` on OFFICEPC is a guess. Measure gate wall-clock under 1, 2, and 3
   concurrent activations before fixing the value.
2. The aging divisor (30) and reservation threshold (2) are policy guesses that only matter in
   `CONCURRENT` mode. Do not tune them before Phase 3 exists.
3. Sabotage patches must be reviewed by a human before first use. There is currently no defined
   authoring workflow for them — this is the largest unspecified surface remaining.
4. Blob retention window is unset. It determines how long a `COMPLETE` remains independently
   provable.
