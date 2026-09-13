# Swarm Operating Protocol v7

**Status:** implementation candidate
**Supersedes:** `SWARM_PROTOCOL_v5.md` and the incomplete `SWARM_PROTOCOL_v6.md`
**Control-plane repo:** `agent-swarm` (`Decksx/agent-swarm`)
**Target repo:** `ComicAutomation`
**Control plane:** Tower `agent-hub` service
**Execution host:** `OFFICEPC`

This protocol replaces conversational agent coordination with a deterministic, event-driven
control plane. Chat remains available for narration and questions, but chat messages never create
work, advance task state, release locks, or wake another model.

The controller and worker harnesses enforce this document. Prompt compliance is useful but is not
a safety boundary.

### Changes from v5/v6

| # | Change | Reason |
| --- | --- | --- |
| 1 | Proof strategy is explicit in the frozen contract | Initial linting cannot inspect candidate tests that do not exist yet |
| 2 | Three-way `T/X/P` integration diagnosis | Candidate-only retesting cannot distinguish target regression, candidate defect, and interaction defect |
| 3 | `sensitivity_paths` separate from author `allowed_files` | Scope permission and stale-assumption detection are different concerns |
| 4 | A safe serial integrator is part of Phase 2 | Serial mode still requires tested, CAS-protected ref advancement and recovery |
| 5 | Stage-preserving serial-lane release | A task awaiting a human must not freeze every unrelated task |
| 6 | Cooperative host drain with write-stop acknowledgement | The operator may not snapshot a worktree while its author can still write |
| 7 | Evidence retention belongs to references, not deduplicated blobs | One blob can be referenced by records with different retention requirements |
| 8 | Normal fast-forward push replaces `--force-with-lease` | Tested descendants do not require force semantics |
| 9 | Protocol upgrades may drain or supersede unsafe legacy tasks | A security fix must not preserve known-unsafe behavior until natural completion |
| 10 | Sound v5/v6 additions retained | Durable evidence, monotonic durations, operator IPC, host capacity, and budget windows remain |

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
19. Proof strategy is never invented after authoring merely to make a candidate pass.
20. A protected remote branch is never force-pushed by the autonomous integration path.

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

The Git operator is a high-privilege, non-LLM worker service on `OFFICEPC`. It authenticates to the
controller, pulls only `role: operator` activations, and accepts no direct author/verifier command.
This preserves the rule that workers cannot invoke siblings. Authors may edit and commit inside an
allocated worktree; only the operator creates/removes worktrees and mutates protected refs.

Authoritative instructions come from the host's system and tool policies, Admin directives, the
frozen task contract, and explicitly trusted repository policy files (`trusted_policy_files`)
pinned at the contract's base SHA. All other repository content, logs, fixtures, commit messages,
and external text are untrusted data.

---

## 3. Operating modes

The controller runs in one of two modes, set by Admin policy and visible in the UI.

| | `SERIAL` (start here) | `CONCURRENT` |
| --- | --- | --- |
| `max_executing` | 1 task in an author, review, or integration execution stage | policy value |
| Integration | Tested fast-forward integrator (§11.3) | Full merge saga (§11.3) |
| Merge invalidation | Cannot occur | Possible; §11.4 applies |
| Path reservations | Not needed | Required |
| Required phases | 0–2 | 0–4 |

`SERIAL` is not a degraded mode. It permits only one executing task, but tasks in paused, blocked,
or human-decision states release the execution lane. Such a task must refresh its base and revalidate
its frozen contract before resuming if the target branch moved while the lane was released.

**Promotion criterion.** Consider `CONCURRENT` only after at least twenty successful serial tasks.
Measure arrival rate, completed-task throughput, execution-host utilization, and p50/p95 time spent
waiting in all ready states. Promote only when sustained ready-queue delay is material and the host
has measured capacity to reduce it. `READY_INTEGRATION` alone is not a sufficient signal.

The rest of this document specifies both modes. Concurrent-only behavior is labeled explicitly.

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
  priority         INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
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
  proof_mode     TEXT NOT NULL CHECK (proof_mode IN ('baseline', 'sabotage', 'both')),
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
  original_stream_hash TEXT,                 -- full pre-truncation sha256 when truncated
  original_byte_length INTEGER,
  stored_path  TEXT NOT NULL,                -- appdata, content-addressed, on Tower
  created_at   REAL NOT NULL
);

-- Retention belongs to each reference, not the deduplicated blob. A single blob
-- may support both a temporary review and a completed integration.
CREATE TABLE evidence_blob_refs (
  evidence_id      TEXT NOT NULL REFERENCES evidence(evidence_id),
  blob_hash        TEXT NOT NULL REFERENCES evidence_blobs(blob_hash),
  stream_kind      TEXT NOT NULL CHECK (stream_kind IN ('stdout', 'stderr', 'attachment')),
  retention_class  TEXT NOT NULL CHECK (retention_class IN ('review', 'failure', 'integration')),
  retain_until     REAL,                     -- NULL only for Admin-retained integration proof
  PRIMARY KEY (evidence_id, blob_hash, stream_kind)
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

CREATE TABLE budget_windows (
  agent         TEXT NOT NULL,
  model         TEXT NOT NULL,
  window_kind   TEXT NOT NULL,
  window_start  REAL NOT NULL,
  consumed      REAL NOT NULL DEFAULT 0,
  limit_value   REAL NOT NULL,
  update_seq    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (agent, model, window_kind, window_start)
);

-- CONCURRENT mode only. Time-boxed claim on a path set after repeated
-- merge invalidation, so a task cannot be starved by siblings.
CREATE TABLE path_reservations (
  reservation_id TEXT PRIMARY KEY,
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  granted_at     REAL NOT NULL,
  expires_at     REAL NOT NULL
);

CREATE TABLE path_reservation_items (
  reservation_id TEXT NOT NULL REFERENCES path_reservations(reservation_id),
  normalized_path TEXT NOT NULL,             -- repo-relative, slash-normalized, case-folded on Windows
  PRIMARY KEY (reservation_id, normalized_path)
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
  drain_requested INTEGER NOT NULL DEFAULT 0,
  exclusive_holder_kind TEXT,                -- 'activation' | 'integration'
  exclusive_holder_id TEXT
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

# The Git operator uses the same claim/heartbeat/evidence/result lifecycle with role=operator.
# There is no worker-accessible endpoint that directly commands protected Git mutations.

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
for deadline expiry is final regardless of what the harness believed. The harness remembers the
highest `server_seq` and discards any delayed heartbeat response carrying a lower sequence.

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

OFFICEPC starts at `max_concurrent = 1` in serial mode. Before concurrent mode, benchmark 1, 2,
and 3 simultaneous representative gates and set the value from measured throughput and tail
latency. An integration saga takes the **exclusive host slot**:
no author self-check or verification gate runs while integration gates run. This matters because
contention-induced timeouts are classified `INFRA_ERROR` and are non-chargeable, so without a cap
the system retries directly into the contention that caused the failure.

### Cooperative host drain

The controller never snapshots a worktree merely because a drain timer expired. To drain:

1. Set `drain_requested = 1`; issue no new activations on the host.
2. Active harnesses receive `DRAIN_REQUESTED` on heartbeat and stop launching new tools.
3. Each harness stops or completes its current interruptible operation and returns
   `WRITES_STOPPED` with its last worktree operation sequence.
4. Only after that acknowledgement may the Git operator fence the worktree, verify that no author
   process retains write authority, and capture a WIP checkpoint.
5. When all active holders acknowledge or reach lease/hard-deadline recovery, acquire the exclusive
   integration slot.

An unresponsive author is never snapshotted concurrently. Its worktree is quarantined after lease
or hard-deadline recovery. Safety takes precedence over an integration-start deadline.

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
schema_version: 7
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
  # Paths whose intervening modification may invalidate the candidate's assumptions.
  # These may be broader than the paths the author is allowed to edit.
  sensitivity_paths:
    - parsers/cbz_parser.py
    - comic_automation/schema.py

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
  mode: baseline                   # required: baseline | sabotage | both
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
    patch_id: null                 # required for sabotage or both
    patch_sha256: null
    target_symbols: []

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
execution host, normalized `sensitivity_paths`, and absence of overlap with unordered active
tasks. `behavior_proof.mode` must already be explicit. For `sabotage` or `both`, the linter also
requires a stored patch, matching checksum, target-symbol allowlist, and proof that the patch
touches only disposable copies of contract-authorized source files.

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
| `AUTHORING` | `environment_defect` | `AUTHOR_BLOCKED` | controller |
| `AUTHORING` | `author_defect` | `CHANGES_REQUESTED` | controller |
| `AUTHORING` | `lease_expired` | `READY_AUTHOR` | controller |
| `AUTHORING` | `deadline_checkpointed` | `AUTHOR_PAUSED` | controller/operator |
| `AUTHORING` | `deadline_without_checkpoint` | `READY_AUTHOR` | controller |
| `AUTHOR_PAUSED` | `author_activation_issued` | `AUTHOR_ASSIGNED` | controller |
| `AUTHOR_BLOCKED` | `environment_repaired` | `READY_AUTHOR` | controller |
| `READY_REVIEW` | `review_activation_issued` | `REVIEW_ASSIGNED` | controller |
| `REVIEW_ASSIGNED` | `activation_claimed` | `REVIEWING` | authenticated verifier |
| `REVIEW_ASSIGNED` | `lease_expired` | `READY_REVIEW` | controller |
| `REVIEW_ASSIGNED` | `hard_deadline_reached` | `READY_REVIEW` | controller |
| `REVIEWING` | `review_requirements_satisfied` | `READY_INTEGRATION` | controller |
| `REVIEWING` | `author_defect` | `CHANGES_REQUESTED` | controller |
| `REVIEWING` | `checkpoint_captured` | `REVIEW_PAUSED` | controller/operator |
| `REVIEWING` | `environment_defect` | `REVIEW_BLOCKED` | controller |
| `REVIEWING` | `proof_inconclusive` | `NEEDS_HUMAN` | controller |
| `REVIEWING` | `decision_required` | `NEEDS_HUMAN` | verifier/controller |
| `REVIEWING` | `lease_expired` | `READY_REVIEW` | controller |
| `REVIEWING` | `deadline_checkpointed` | `REVIEW_PAUSED` | controller/operator |
| `REVIEWING` | `deadline_without_checkpoint` | `READY_REVIEW` | controller |
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

Workers submit observations and evidence; they do not select failure classes. The controller uses
contract-defined exit codes and machine-checkable predicates. An assertion is not automatically an
author defect, and a missing package is not automatically environmental—the author may have added
an undeclared dependency. If deterministic rules cannot classify the cause, the controller records
`decision_required`; an advisor may propose a class, but unresolved ambiguity enters
`NEEDS_HUMAN` rather than being guessed.

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
   explicit elision marker, sets `truncated = 1`, and records the original byte length and
   pre-truncation SHA-256.
3. It uploads each stream to `POST /evidence/blobs`, which stores it content-addressed under
   appdata on Tower and returns `blob_hash`. The hub—not the client—computes and verifies the hash,
   enforces size limits, and chooses the storage path; no client path is accepted.
4. `POST /activations/{id}/evidence` references `blob_hash` values. File paths may be recorded in
   `local_log_path` for convenience but are never the record.
5. `POST /activations/{id}/result` rejects any result whose cited evidence has missing or
   incomplete blobs (`409 evidence_not_durable`).

Retention is evaluated per `evidence_blob_refs` row. Default policy is 30 days for superseded
review attempts and 90 days for failures or escalations. Integration proof is retained until an
Admin-configured date or with `retain_until = NULL` when the Admin explicitly selects indefinite
retention. Storage quotas and backups are Admin policy. A blob is garbage-collected only after no
unexpired reference remains; denormalized reference counters are never authoritative.

---

## 10. Behavior proof

Behavior proof executes only named selectors. The contract author selects `baseline`, `sabotage`,
or `both` before validation. The controller never synthesizes a weaker proof after seeing the
candidate. A new API that cannot collect on the base normally uses sabotage; a behavior change
whose tests collect on the base may use baseline.

### Baseline mode

Apply the candidate's changed test files to a disposable worktree at `base_sha`, execute only the
named selectors, and require `FAIL` matching the declared exception type and message pattern.
Collection, import, fixture, environment, and usage errors are `INCONCLUSIVE` →
`proof_inconclusive` → `NEEDS_HUMAN`. This indicates that the frozen proof contract was not
executable as written.

Then execute the selectors at the candidate SHA and require `PASS`.

### Sabotage mode

Apply the reviewed, machine-readable sabotage patch identified by `patch_id` to a disposable
worktree at the candidate SHA, disabling only the declared target symbol or guard. The operator
verifies the patch checksum and changed-path allowlist. The mutant must parse, import, and collect;
otherwise the proof is inconclusive. The named selectors must fail with the declared signature,
and must pass in the untouched candidate worktree.

Sabotage patches are created through a separate scoped task or included in the original frozen
contract before author activation. An advisor may propose a mutation, but proposed text is never
executed as authoritative proof until it passes contract validation. Generic blind AST operations
such as inverting arbitrary branches or replacing arbitrary bodies do not qualify.

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

One saga at a time under the `integration` lock and exclusive host slot.

1. Fetch without changing protected refs. Record local and remote target tip `T` and candidate `X`.
   If the required local and remote tips disagree, stop for reconciliation.
2. In `SERIAL`, require `T == base_sha` and require `X` to be a tested descendant suitable for a
   fast-forward; set proposed integration object `P = X`. If the serial lane had been released and
   `T` moved, create a refreshed contract version instead of integrating stale work.
3. In `CONCURRENT`, evaluate invalidation (§11.4), create a scratch worktree at `T`, and merge `X`
   without resolving conflicts. A conflict creates a separate authored conflict-resolution task.
   Record the resulting proposed integration object as `P`.
4. `repository_stable = 1` because protected refs have not moved. Run the object diff gate on
   `T..P` to prove what the proposed object contributes. Do not use this comparison to detect
   intervening changes; §11.4 uses `base_sha..T` for that purpose.
5. Run every integration gate against exactly `P` and durably upload its evidence.
6. If a gate fails before protected refs move, perform three-way diagnosis (§11.5), discard the
   scratch worktree, and emit the classified rejection. No rollback is required.
7. Advance the local protected ref with compare-and-swap:
   `git update-ref refs/heads/{target_branch} P T`.
8. Push the exact tested descendant with a normal explicit refspec:
   `git push origin P:refs/heads/{target_branch}`. Never use force or `--force-with-lease` in the
   autonomous integration path. A remote race must fail closed.
9. Verify every required local and remote ref equals `P`.
10. Persist the saga record and emit `integration_completed`.
11. Release the lock and host slot only after the saga is durable and
    `repository_stable = 1`.

If a protected ref moved and a later step fails: set `repository_stable = 0`, transition to
`REVERTING`, and **keep the lock**. The same deterministic saga attempts compare-and-swap
restoration to the recorded prior tip, then either proves all protected refs stable and emits
`rollback_completed`, or emits `repository_uncertain`, retains the lock, globally pauses protected
Git operations, and creates a `NEEDS_HUMAN` incident.

Reproducible merge timestamps are unnecessary: the system tests and advances the exact existing
object `P` and never reconstructs it after testing.

### 11.4 Intervening-change invalidation (`CONCURRENT` only)

Permission scope and assumption scope are distinct:

- `allowed_files` and `allowed_dirs` limit what the author may change.
- `sensitivity_paths` identify files whose intervening modification may invalidate the candidate's
  design or verification assumptions.

Before constructing `P`, compute:

```text
intervening_paths = changed_paths(base_sha, T)
potentially_invalidated = intervening_paths ∩ sensitivity_paths
```

An empty intersection proceeds. A nonempty intersection triggers the contract's declared
invalidation policy: either mandatory re-review against `T`, or a refreshed contract version. It
is non-chargeable. `T..P` is still checked afterward, but only to validate the proposed object's
own contribution.

### 11.5 Three-way integration-failure diagnosis

After a gate fails at `P`, first prove the environment and fixtures are stable. Then execute the
same command, contract hash, environment hash, and fixture identity in clean worktrees at target
tip `T`, candidate `X`, and proposed result `P`:

| `T` | `X` | `P` | Classification | Chargeable action |
| --- | --- | --- | --- | --- |
| PASS | PASS | FAIL | `INTERACTION_DEFECT` | no; conflict/integration task |
| FAIL | PASS | FAIL | `TARGET_REGRESSION` | no; block merge train and investigate target |
| PASS | FAIL | FAIL | `CANDIDATE_DEFECT` | yes, after repeat confirms non-flake |
| PASS | PASS | PASS on repeat | `FLAKE_SUSPECTED` | no; investigate |
| Any infrastructure or fixture mismatch | — | — | `ENVIRONMENT_DEFECT` | no; stage-specific block |
| Any other combination | — | — | `AMBIGUOUS_FAILURE` | no; bounded escalation |

A prior PASS and a new FAIL for the same full evidence identity is flake suspicion, not immediate
author blame. The controller never classifies from `X/P` alone.

### 11.6 Path reservations (`CONCURRENT` only)

When `invalidation_count` reaches the Admin policy threshold (start at 2), the controller grants
the task a bounded reservation over normalized `allowed_files ∪ sensitivity_paths` (start at 60
minutes). While it is live, another task whose proposed changes intersect those normalized paths
waits at `READY_INTEGRATION`. Reservation items are rows, not opaque JSON, so overlap is checked
consistently on Windows. Reservations expire unconditionally; they are a starvation guard, not a
filesystem or Git lock.

---

## 12. Failures and human decisions

| Failure | Chargeable | Default outcome |
| --- | --- | --- |
| Author defect, lint/test failure, scope violation | yes | `CHANGES_REQUESTED` |
| `T` passes, `X` fails, `P` fails under identical conditions | yes after repeat | `CHANGES_REQUESTED` |
| `T` and `X` pass, `P` fails | no | interaction task + invalidation |
| `T` fails, `X` passes, `P` fails | no | block merge train; investigate target regression |
| Sensitivity path changed since `base_sha` | no | re-review or refreshed contract version |
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

- classify the release as backward-compatible, behavior-changing, or security-critical;
- compatible in-flight tasks may finish under a still-supported frozen schema;
- behavior-changing upgrades drain new issuance and require explicit migration or a new task
  version before affected tasks resume;
- security-critical upgrades pause immediately and cancel, supersede, or migrate unsafe legacy
  activations—known-unsafe behavior is never allowed to run merely because it was previously frozen;
- new task versions use the new schema;
- startup fails closed if any nonterminal task uses an unsupported schema without an explicit,
  tested migration decision.

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
- stale heartbeat response with a lower `server_seq` is ignored;
- drain never snapshots before `WRITES_STOPPED` acknowledgement;
- an unresponsive drain holder reaches quarantine without a concurrent snapshot;
- author and review checkpoint recovery;
- stage-correct repair from both blocked states;
- late result after lease expiry; quarantined worktree write attempt;
- stale fence after lock reassignment;
- unrelated resource epoch not invalidating integration;
- result citing evidence with missing blobs;
- integration crash before ref movement;
- integration crash after local movement and before remote confirmation;
- external target movement during compare-and-swap;
- all deterministic `T/X/P` diagnostic classifications, including a pre-broken target;
- `T..P` is not used as evidence of changes between `base_sha` and `T`;
- sensitivity-path intersection forces re-review or a refreshed version;
- autonomous integration never invokes a force push;
- serial integration completes safely before concurrent features exist;
- a human-blocked task releases the serial lane and revalidates before resumption;
- starvation: a low-priority task repeatedly invalidated must integrate within a bounded number of
  cycles;
- host capacity cap prevents issuance; exclusive slot excludes concurrent gates;
- required evidence missing, stale, advisory, or bound to the wrong SHA;
- one deduplicated blob referenced by two retention classes survives until its final reference
  expires;
- a security-critical upgrade prevents unsafe legacy activation resumption;
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

### Phase 2 — Worktrees, verification, and safe serial integration

1. Operator-managed worktrees and scoped author branches.
2. Object-level diff gates and candidate ancestry validation.
3. Evidence blob upload and the durability predicate.
4. Authoritative evidence predicates and explicit behavior-proof strategies.
5. Safe author and reviewer checkpoint capture and resumption.
6. Serial integration gates, exact-object fast-forward, local ref CAS, normal remote push, remote
   confirmation, and recovery at every crash point.
7. Prove that blocked and human-decision tasks release the serial execution lane and are
   revalidated against the current target before resuming.

**Stop here and run in `SERIAL` mode.** Complete at least twenty real tasks before deciding
whether Phase 3 is needed. Record, per task: wall-clock duration, chargeable attempts, time in
all ready states, p95 queue age, execution-host utilization, arrival rate, completed-task
throughput, and human interventions. Promote only when sustained queueing—not review quality or
human delay—is the measured bottleneck.

### Phase 3 — Concurrency and integration safety (only if the measurement justifies it)

1. Concurrent merge-object construction and cooperative host drain.
2. Per-resource fence epochs and the serialized concurrent integration saga.
3. `base_sha..T` sensitivity invalidation and `T/X/P` failure diagnosis.
4. Normalized path reservations and integration queue aging.
5. Verify the integration lock cannot be released while repository state is uncertain.

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
drain_requested            writes_stopped
environment_defect         environment_repaired
author_defect              retry_authorized
budget_exhausted           review_requirements_satisfied
proof_inconclusive         decision_required
integration_started        integration_rejected
integration_completed      reservation_granted
interaction_defect         target_regression
candidate_defect           sensitivity_invalidated
rollback_started           rollback_completed
repository_uncertain       lease_expired
hard_deadline_reached      deadline_checkpointed
deadline_without_checkpoint regression_reverted
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

## Appendix C — Deployment policy values

These values are deliberately policy rather than protocol invariants:

1. `max_concurrent` starts at 1 and changes only after the Phase 3 host benchmark.
2. The aging divisor and reservation threshold are set when concurrent mode is enabled; initial
   candidates are 30 minutes and two invalidations.
3. Evidence retention uses the defaults in §9 unless Admin selects different dates and quotas.
4. Standing authorization profiles are versioned separately and referenced by contract hash.
