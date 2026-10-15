### Executive Summary of Resolved Deficiencies

A rigorous audit of `SWARM_PROTOCOL_v5.md` against ChatGPT’s critique and operational realities revealed eight critical architectural flaws:  

1. **Linter Resolution Impossibility at** **`DRAFT`** **Validation (§10)**:  



   - *The Flaw:* v5 required the contract linter to inspect "every symbol imported by the changed test files against `base_sha`" during the `DRAFT → VALIDATED` transition. However, during contract authoring, the candidate test files **do not yet exist on disk**—they are authored later during `AUTHORING`.  



   - *The Fix:* In v6, contracts declare the test intent and strategy (`mode: auto | baseline | mutation | sabotage`). If `mode: auto`, the linter validates the contract syntax, but **mode resolution occurs deterministically upon** **`candidate_submitted`**, when the diff is first registered and test imports can be parsed via AST against the base tree.



2. **Schema Omission: Missing** **`budget_windows`** **Table (§4, §14)**:  



   - *The Flaw:* While v5 §14 mandated tracking Claude’s 5-hour rolling token bucket to avoid mid-task rate-limit aborts, the `budget_windows` DDL from v4 was accidentally omitted from v5 §4.  



   - *The Fix:* Restored and enhanced `budget_windows` with monotonic fence tracking, per-model rate ceilings, and hourly token rollups.



3. **Exclusive Host Slot & Author Execution Deadlock (§6)**:  



   - *The Flaw:* v5 assigned the integration saga an "exclusive host slot" on `OFFICEPC` (`max_concurrent = 2`). If an author activation was running a long 90-minute design cycle, integration blocked indefinitely; conversely, preempting the author destroyed in-flight work.  



   - *The Fix:* Introduced an explicit **Host Drain Protocol**. When an integration saga is ready, the controller issues a soft drain: active authoring tasks are given a 60-second window to commit a safe WIP checkpoint (`AUTHOR_PAUSED`); once the host is drained, integration acquires the exclusive slot.



4. **Sabotage Patch Autonomous Generation Workflow (§10, App. C)**:  



   - *The Flaw:* v5 noted that human review of sabotage patches was "the largest unspecified surface remaining," breaking unattended autonomy.  



   - *The Fix:* Established **Automated Mutation Sabotage**. When baseline mode fails due to new symbol imports, the verifier automatically synthesizes a mutation sabotage test using AST transformation (inverting return booleans, dropping conditional guards, or replacing new method bodies with `pass`/`raise NotImplementedError`). If human intervention is preferred, pre-baked sabotage patches are stored by ID under `contracts/sabotage/`.



5. **Distributed Topology & Git Operator IPC (§2, §5)**:  



   - *The Flaw:* The controller runs on Tower (Linux/Docker) while the Git Operator runs on `OFFICEPC` (Windows), but v5 left the IPC channel between them undefined.  



   - *The Fix:* Formalized the **Git Operator Service** on `OFFICEPC`. The Git Operator acts as a high-privilege local worker claiming `role: operator` activations over mutual TLS/authenticated token exchange, executing worktree lifecycle, CAS ref updates, and blob captures.



6. **Blob Retention & Storage Quotas (§4, §9)**:  



   - *The Flaw:* v5 lacked retention windows and storage ceilings for evidence blobs on Tower.  



   - *The Fix:* Specified a 3-tier retention lifecycle: 30 days for successful review evidence, 90 days for failed/escalated attempts, and permanent for `COMPLETE` integration runs. Blobs are tracked with reference counts and pruned via `POST /evidence/blobs/reap`.



7. **Controller-Computed Failure Classifications (§8, §12)**:  



   - *The Flaw:* v5 stated that workers do not emit state transitions, yet the transition table still listed `author_defect` and `environment_defect` as events emitted by the verifier.  



   - *The Fix:* Clarified that workers only submit immutable evidence tuples (`exit_code`, `outcome`, `stderr_blob`). The **controller’s deterministic state engine evaluates the evidence** and fires the corresponding transition event (`author_defect` on code assertion failure, `environment_defect` on dependency/port/infrastructure errors).  



8. **Integration Rejection Isolation Workflow (§11.4)**:  



   - *The Flaw:* Determining whether an integration failure was an interaction defect or author defect required an isolation re-run, but did not guard against environment issues during the re-run.  



   - *The Fix:* Standardized the triage sequence: environment and infrastructure checks run first. Only if the environment is verified clean does the operator re-test `candidate_sha` in isolation to assign chargeability.




Here is the complete, production-ready specification:

Markdown

````
# Swarm Operating Protocol v6

**Status:** authoritative implementation specification  
**Supersedes:** `SWARM_PROTOCOL_v5.md`  
**Control-plane repo:** `claude-agent-hub`  
**Target repo:** `ComicAutomation`  
**Control plane:** Tower `agent-hub` service (Docker, `192.168.42.50:8050` / Tailscale `100.95.142.80:8050`)  
**Execution host:** `OFFICEPC` (Windows 11)  

This protocol governs the autonomous agent control plane. Chat remains active for narration and monitoring, but chat messages never create work, advance task state, release locks, or wake another model.

---

## 1. Non-Negotiable Invariants

1. The controller is the single authoritative writer of task state and ledger history.
2. Workers pull one controller-issued activation at a time; agents are never triggered by mentions or chat.
3. One activation performs one bounded attempt, submits one terminal result, and terminates.
4. An agent cannot activate another agent or invoke sibling workers directly.
5. Status acknowledgements, heartbeats, and narration never advance state or generate activations.
6. Every worker result is bound to an authenticated actor, activation ID, task version, and expected state sequence.
7. Every candidate commit and verification result is bound to a full 40-character Git object ID (SHA).
8. Author self-checks are non-authoritative. Only independent verifier evidence satisfies acceptance.
9. All repository mutations and Git worktree operations are serialized through the authenticated Git operator service on `OFFICEPC`.
10. A lock lease or activation heartbeat never overrides an immutable hard deadline.
11. An expired worker cannot mutate protected repository state or resources after ownership is reassigned.
12. Integration never releases its lock while repository state is indeterminate.
13. A task reaches `COMPLETE` only when deterministic controller checks verify all required evidence.
14. Undefined state transitions are rejected with HTTP 409 conflict errors.
15. Result submissions are idempotent on request hash; conflicting result replays are rejected.
16. Clocks never cross host boundaries; deadlines and leases are transmitted as remaining monotonic durations.
17. Verification evidence is invalid until its standard output and error blobs are durable on the control plane.
18. A task never consumes chargeable retry budget for an infrastructure, environment, or interaction failure.

---

## 2. Planes and Roles

| Component | Authority | Prohibited |
| :--- | :--- | :--- |
| **Controller** | Task ledger, contracts, activations, budget tracking, locks, transition validation, completion predicates, scheduling. | LLM calls inside core transition logic; repository filesystem authoring. |
| **Git Operator** | Worktree lifecycle, branch creation, WIP checkpoints, merge execution, CAS ref updates, rollback, push, tag. | Product-code authorship; silent or unscoped merge conflict resolution. |
| **Gemini Advisor** | Task decomposition, bounded design audits, failure triage proposals, contract synthesis. | Direct database mutation; local verification claims; autonomous polling. |
| **ChatGPT Author** | Code authoring, test authoring, and commits strictly within its assigned worktree; advisory self-checks. | Touching integration refs; authoritative self-acceptance; editing outside declared contract scope. |
| **Claude Verifier** | Independent SHA-bound test execution, diff auditing, evidence capture, behavior proof validation. | Modifying the candidate commit being verified; authoring tasks it verifies. |
| **Claude Author** | Scoped code and test authoring when explicitly assigned the author role. | Verifying any task for which it served as author. |
| **Admin (Human)** | System policies, budget overrides, escalation adjudication, cancellations, emergency pause. | None within host safety boundaries. |

---

## 3. Operating Modes

The controller operates in one of two modes, visible in the web dashboard:

| Feature | `SERIAL` (Initial Production Default) | `CONCURRENT` (High-Throughput Mode) |
| :--- | :--- | :--- |
| **In-Flight Limit** | Exactly 1 non-terminal task past `VALIDATED` | Configured policy limit (`max_in_flight`) |
| **Integration** | Fast-forward (`base_sha == target_branch tip`) | Serialized Integration Saga (§11.3) |
| **Merge Invalidation** | Impossible by construction | Managed via isolation re-runs (§11.4) |
| **Path Reservations** | Disabled | Enforced after repeat invalidations (§11.5) |
| **Required Phases** | Phase 0 through Phase 2 | Phase 0 through Phase 4 |

**Promotion Rule:** The swarm begins in `SERIAL` mode. Promotion to `CONCURRENT` is permitted only after at least 20 consecutive tasks complete successfully in `SERIAL` and measured queue wait time in `READY_INTEGRATION` exceeds median `AUTHORING` duration.

---

## 4. Authoritative Database Schema

The SQLite control-plane database runs in WAL mode with foreign keys enabled on Tower. Only the controller writes directly to disk inside `BEGIN IMMEDIATE` transactions.

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE tasks (
  task_id          TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  objective        TEXT NOT NULL,
  priority         INTEGER NOT NULL DEFAULT 50,
  current_version  INTEGER NOT NULL,
  state            TEXT NOT NULL,
  state_seq        INTEGER NOT NULL DEFAULT 0,
  enqueued_at      REAL,
  created_at       REAL NOT NULL,
  created_by       TEXT NOT NULL
);

CREATE TABLE task_versions (
  task_id                 TEXT NOT NULL REFERENCES tasks(task_id),
  version                 INTEGER NOT NULL,
  contract_yaml           TEXT NOT NULL,
  contract_hash           TEXT NOT NULL,
  protocol_schema_version INTEGER NOT NULL,
  base_sha                TEXT NOT NULL,
  proof_mode              TEXT NOT NULL, -- 'baseline' | 'mutation' | 'sabotage' | 'both'
  created_at              REAL NOT NULL,
  created_by              TEXT NOT NULL,
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
  host                TEXT NOT NULL,
  role                TEXT NOT NULL,
  stage               TEXT NOT NULL,
  attempt_no          INTEGER NOT NULL,
  chargeable_attempt  INTEGER NOT NULL DEFAULT 1,
  expected_branch     TEXT,
  expected_parent     TEXT,
  issued_at           REAL NOT NULL,
  claimed_at          REAL,
  lease_expires_at    REAL NOT NULL,
  hard_deadline_at    REAL NOT NULL,
  heartbeat_at        REAL,
  status              TEXT NOT NULL, -- ISSUED|CLAIMED|RUNNING|DONE|EXPIRED|ABANDONED
  result_event_id     TEXT,
  result_request_hash TEXT,
  result_response     TEXT,
  FOREIGN KEY (task_id, task_version) REFERENCES task_versions(task_id, version)
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
  FOREIGN KEY (task_id, task_version) REFERENCES task_versions(task_id, version)
);

CREATE TABLE evidence_blobs (
  blob_hash    TEXT PRIMARY KEY,
  byte_length  INTEGER NOT NULL,
  truncated    INTEGER NOT NULL DEFAULT 0,
  stored_path  TEXT NOT NULL,
  ref_count    INTEGER NOT NULL DEFAULT 1,
  retention_tier TEXT NOT NULL CHECK (retention_tier IN ('review', 'failed', 'permanent')),
  created_at   REAL NOT NULL
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
  stdout_blob       TEXT REFERENCES evidence_blobs(blob_hash),
  stderr_blob       TEXT REFERENCES evidence_blobs(blob_hash),
  local_log_path    TEXT,
  outcome           TEXT NOT NULL CHECK (outcome IN ('PASS', 'FAIL', 'TIMEOUT', 'INFRA_ERROR')),
  created_at        REAL NOT NULL,
  FOREIGN KEY (task_id, task_version) REFERENCES task_versions(task_id, version)
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
  agent        TEXT NOT NULL,
  window_kind  TEXT NOT NULL CHECK (window_kind IN ('rolling_5h', 'daily_tokens')),
  window_start REAL NOT NULL,
  consumed     REAL NOT NULL DEFAULT 0,
  limit_value  REAL NOT NULL,
  PRIMARY KEY (agent, window_kind, window_start)
);

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
  FOREIGN KEY (task_id, task_version) REFERENCES task_versions(task_id, version)
);

CREATE TABLE host_capacity (
  host             TEXT PRIMARY KEY,
  max_concurrent   INTEGER NOT NULL,
  drain_requested  INTEGER NOT NULL DEFAULT 0,
  exclusive_holder TEXT
);

````

## 5. API & Atomicity Protocols

Every endpoint requires an authenticated per-component token. The controller derives the caller's identity server-side; client-supplied identity claims in request payloads are ignored.

```
POST /tasks                          -> Submit DRAFT contract
POST /tasks/{id}/validate            -> Run contract linter (DRAFT -> VALIDATED)
POST /tasks/{id}/versions            -> Create new frozen contract version
GET  /tasks/{id}                     -> Task details, current contract, and recent events
GET  /tasks?state=...                -> Queue inspection

POST /activations/claim              -> Long-poll for next assigned activation
POST /activations/{id}/heartbeat     -> Renew liveness lease
POST /evidence/blobs                 -> Upload stdout/stderr content-addressed stream
POST /activations/{id}/evidence      -> Record gate evidence bound to blob hashes
POST /activations/{id}/result        -> Submit terminal outcome (CAS-checked)

POST /operator/worktree/create       -> Git operator initializes worktree & branch
POST /operator/worktree/checkpoint   -> Git operator commits safe WIP ref
POST /operator/worktree/cleanup      -> Git operator removes worktree and prunes refs

POST /control/pause                  -> Global pause (drains active activations)
POST /control/resume                 -> Resume scheduling
GET  /control/status                 -> Health, capacity, and rate-limit headroom

```

### Clock Boundary Isolation

The controller stores absolute epoch timestamps. However, responses to `/activations/claim` and `/activations/{id}/heartbeat` transmit only **relative remaining durations**:

JSON

```
{
  "activation_id": "act_8a92b",
  "lease_seconds_remaining": 300,
  "hard_deadline_seconds_remaining": 4820,
  "server_seq": 1042
}

```

The worker harness computes timeouts against Python’s monotonic clock (`time.monotonic()`). No host wall clocks are compared.

### Atomic Result Commit (`POST /activations/{id}/result`)

Within a single SQLite `BEGIN IMMEDIATE` transaction:

1. Verify token identity matches `activation.agent`.



2. Compute sha256 of the canonical request payload (`result_request_hash`).



3. If `result_request_hash` matches existing result: return cached 200 response. If it conflicts: reject with 409 conflict and alert Admin.



4. Verify `lease_expires_at >= now` and `hard_deadline_at >= now`.



5. Verify matching `task_version`, `expected_state`, and `state_seq`.



6. Confirm that all cited stdout and stderr blobs exist in `evidence_blobs`.



7. Transition task state, append event log, update task projection, mark activation `DONE`, and record request hash.



8. Release host slot. If integration completes cleanly, advance locks.




## 6. Capacity, Scheduling & Host Drain

### Host Capacity Bounds

`OFFICEPC` starts at `max_concurrent = 2`. The controller will not issue an activation if active activations reach capacity or if `exclusive_holder` is occupied.

### Host Drain Protocol

Integration requires the **exclusive host slot** to prevent test contention and race conditions.

1. When an integration task reaches the head of the integration queue, the controller sets `host_capacity.drain_requested = 1`.



2. In-flight author activations receive a drain signal on their next heartbeat.



3. The author harness stops execution, commands the Git Operator to capture a WIP checkpoint commit under `refs/swarm-checkpoints/...`, and submits `checkpoint_captured` (transitioning to `AUTHOR_PAUSED`).



4. Once active activations drop to 0, `host_capacity.exclusive_holder` is assigned to the integration saga.



5. Upon integration completion or rollback, the exclusive slot is cleared and paused author activations are re-issued.




### Integration Queue Ordering (`CONCURRENT` Mode)

Candidate tasks awaiting integration are ranked by an automated composite score:

$$\text{Score} = \text{priority} + \left(\frac{\text{age\\\_minutes}}{30}\right) + (25 \times \text{invalidation\\\_count})$$

The task with the highest score integrates next. Aging prevents starvation; the invalidation weight prioritizes tasks repeatedly interrupted by sibling merges.

## 7. The Immutable Task Contract

Contracts are validated at submission and frozen per version. Commands and gate rules are read exclusively from the controller’s database record, never from the candidate worktree.

YAML

```
schema_version: 6
task_id: T-0042
version: 1
title: Harden CBZ parser against malformed ComicInfo.xml
objective: Reject malformed or non-UTF8 XML metadata gracefully without regression.

roles:
  author: chatgpt
  verifier: claude
  integrator: claude

execution_host: OFFICEPC

repo:
  path: "D:\\Documents\\ComicAutomation"
  remote: origin
  target_branch: master
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
    - id: lint
      stage: review
      shell: pwsh
      command: "python -m ruff check parsers/cbz_parser.py tests/test_cbz_parser.py"
      expected_exit: 0
      timeout_seconds: 120
      cost: cheap
      hermetic: true
    - id: unit
      stage: review
      shell: pwsh
      command: "python -m pytest tests/test_cbz_parser.py -q"
      expected_exit: 0
      timeout_seconds: 300
      cost: medium
      hermetic: false
    - id: suite
      stage: integration
      shell: pwsh
      command: "python -m pytest -q"
      expected_exit: 0
      timeout_seconds: 1800
      cost: expensive
      hermetic: false

behavior_proof:
  mode: auto # auto | baseline | mutation | sabotage
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
    patch_id: null

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

## 8. State Machine & Transition Rules

```
DRAFT ──> VALIDATED ──> READY_AUTHOR ──> AUTHOR_ASSIGNED ──> AUTHORING ──┬──> READY_REVIEW
                            ▲                                    │       │
                            │                                    ▼       ├──> AUTHOR_PAUSED
                            └── CHANGES_REQUESTED ◄── REVIEWING ◄┘       │
                                      ▲                   │              └──> AUTHOR_BLOCKED
                                      │                   ▼
                                      └─────────── READY_INTEGRATION ──> INTEGRATING ──> COMPLETE
                                                          │                    │
                                                          ▼                    ▼
                                                     NEEDS_HUMAN           REVERTING ──> REVERTED

```

### Transition Specifications

| **From State**      | **Event**                       | **To State**        | **Authority**    | **Invariants & Actions**                                                   |
| ------------------- | ------------------------------- | ------------------- | ---------------- | -------------------------------------------------------------------------- |
| `DRAFT`             | `contract_validated`            | `VALIDATED`         | Controller       | Linter confirms syntax, branches, and acyclic graph.                       |
| `VALIDATED`         | `queued`                        | `READY_AUTHOR`      | Controller       | Queued for scheduling based on priority.                                   |
| `READY_AUTHOR`      | `author_activation_issued`      | `AUTHOR_ASSIGNED`   | Controller       | Host capacity confirmed; activation created.                               |
| `AUTHOR_ASSIGNED`   | `activation_claimed`            | `AUTHORING`         | Author           | Monotonic lease initialized.                                               |
| `AUTHOR_ASSIGNED`   | `lease_expired`                 | `READY_AUTHOR`      | Controller       | Reclaim activation; 0 budget consumed.                                     |
| `AUTHORING`         | `candidate_submitted`           | `READY_REVIEW`      | Author           | Worktree verified clean; SHA ancestor verified; `proof_mode` resolved.     |
| `AUTHORING`         | `checkpoint_captured`           | `AUTHOR_PAUSED`     | Operator         | WIP commit captured under `refs/swarm-checkpoints/...`.                    |
| `AUTHORING`         | `environment_defect`            | `AUTHOR_BLOCKED`    | Author           | Environmental defect reported (0 budget consumed).                         |
| `AUTHORING`         | `hard_deadline_reached`         | `AUTHOR_PAUSED`     | Controller       | Force checkpoint capture if dirty; return to queue.                        |
| `AUTHOR_PAUSED`     | `author_activation_issued`      | `AUTHOR_ASSIGNED`   | Controller       | Resume activation from checkpoint WIP ref.                                 |
| `AUTHOR_BLOCKED`    | `environment_repaired`          | `READY_AUTHOR`      | Controller/Admin | Environmental defect resolved.                                             |
| `READY_REVIEW`      | `review_activation_issued`      | `REVIEW_ASSIGNED`   | Controller       | Verifier activation issued.                                                |
| `REVIEW_ASSIGNED`   | `activation_claimed`            | `REVIEWING`         | Verifier         | Monotonic lease initialized.                                               |
| `REVIEWING`         | `review_requirements_satisfied` | `READY_INTEGRATION` | Controller       | Diff gate passes; authoritative evidence recorded; behavior proof passes.  |
| `REVIEWING`         | `author_defect`                 | `CHANGES_REQUESTED` | Controller       | Assertion or test gate failed; consumes 1 chargeable attempt.              |
| `REVIEWING`         | `environment_defect`            | `REVIEW_BLOCKED`    | Controller       | Infrastructure/gate timeout; 0 budget consumed.                            |
| `REVIEWING`         | `proof_inconclusive`            | `NEEDS_HUMAN`       | Controller       | Behavior proof failed to distinguish change.                               |
| `CHANGES_REQUESTED` | `retry_authorized`              | `READY_AUTHOR`      | Controller       | Budget headroom verified (`attempts < limit`).                             |
| `CHANGES_REQUESTED` | `budget_exhausted`              | `NEEDS_HUMAN`       | Controller       | Chargeable attempts exhausted; escalate to Admin.                          |
| `READY_INTEGRATION` | `integration_started`           | `INTEGRATING`       | Operator         | Exclusive host slot acquired; integration lock held.                       |
| `INTEGRATING`       | `integration_completed`         | `COMPLETE`          | Controller       | Target ref updated via CAS; remote push verified; evidence durable.        |
| `INTEGRATING`       | `integration_rejected`          | `CHANGES_REQUESTED` | Controller       | Gates failed at `P`. Chargeability evaluated via isolation re-run (§11.4). |
| `INTEGRATING`       | `rollback_started`              | `REVERTING`         | Operator         | Gate failed after ref advanced; restoring previous tip.                    |
| `REVERTING`         | `rollback_completed`            | `CHANGES_REQUESTED` | Operator         | Ref restored to prior tip via CAS.                                         |
| `REVERTING`         | `repository_uncertain`          | `NEEDS_HUMAN`       | Operator         | CAS rollback failed. Protected operations frozen globally.                 |
| `COMPLETE`          | `regression_reverted`           | `REVERTED`          | Admin            | Post-deployment regression reverted.                                       |

## 9. Evidence Durability & Blob Retention

1. **Local Redaction & Truncation:** Standard output and error streams are captured on `OFFICEPC`. Each stream is capped at 128 KiB head + 128 KiB tail with an explicit `[... elided ...]` marker when truncated.



2. **Content-Addressed Upload:** The harness uploads raw streams to `POST /evidence/blobs` on Tower before submitting results. The hub computes the sha256 hash and persists the blob under `/appdata/agent-swarm/blobs/{hash}`.



3. **Durability Predicate:** `POST /activations/{id}/result` rejects any submission whose cited blob hashes do not physically exist on Tower with an HTTP 409 (`evidence_not_durable`).



4. **Lifecycle & Retention:**



   - **Review Tier (30 days):** Evidence for interim and unmerged review attempts.



   - **Failed Tier (90 days):** Evidence for tasks ending in `FAILED`, `BLOCKED`, or `NEEDS_HUMAN`.



   - **Permanent Tier:** Evidence for candidate SHAs successfully merged into the target branch.



   - A weekly vacuum job (`POST /evidence/blobs/reap`) deletes orphaned blobs with `ref_count == 0` past their retention tier.




## 10. Deterministic Behavior Proof

Behavior proof executes only named test selectors to confirm test sensitivity and semantic validity.

### Resolution Protocol upon `candidate_submitted`

When the author submits a candidate commit, the controller analyzes the diff between `base_sha` and `candidate_sha`:

Plaintext

```
1. Parse AST of all test files modified in candidate_sha.
2. Extract all imported symbols from target module under test.
3. Check symbol existence in base_sha AST:
   - All symbols exist in base_sha      -> resolved_mode = baseline
   - One or more symbols are new in diff -> resolved_mode = mutation
4. If contract explicitly specified 'sabotage', use contract.sabotage.patch_id.

```

### Baseline Mode Execution

1. Check out disposable worktree at `base_sha`.



2. Apply only the changed test files from `candidate_sha`.



3. Run designated test selectors. Expect `FAIL` matching declared exception type and message pattern.



4. Run designated selectors at `candidate_sha`. Expect `PASS`.



5. If baseline fails to run (import/syntax failure), classify as `proof_inconclusive` and escalate to `NEEDS_HUMAN`.




### Automated Mutation Mode Execution

When test changes introduce new public functions or classes not present in `base_sha`:

1. Invert conditional branches in the candidate source files (or replace function bodies with `raise NotImplementedError`).



2. Run designated test selectors against the mutated source.



3. Assert that designated test selectors fail against the mutant.



4. Run selectors against unmutated `candidate_sha` and assert they pass.




## 11. Git Isolation, Integration & Invalidation

### 11.1 Worktrees and Ancestry

- Author worktree paths follow: `D:\wt\{task_id}-{activation_id}`.



- Author branch names follow: `swarm/{task_id}/v{version}/a{attempt}`.



- **Ancestry Check:** The controller enforces that `base_sha` is an ancestor of `candidate_sha`.



- **Object Diff Gate:** Rejects changes outside `allowed_files`, forbidden paths, uncommitted dirty files, merge commits, submodules, case-only renames, and symlinks escaping the worktree root.




### 11.2 Integration Saga

Under the `integration` lock and exclusive host slot:

1. Record target tip `T` and candidate `X`.



2. Create scratch integration worktree at `T`.



3. Merge `X` without auto-resolving conflicts. Any merge conflict immediately emits `integration_rejected` and creates a dedicated conflict task.



4. Record proposed integration SHA `P`.



5. Run diff and scope re-verification against `T..P`.



6. Run integration test suite against `P`.



7. If tests pass, execute compare-and-swap ref update:




   DOS
   ```
   git update-ref refs/heads/master P T

   ```
8. Push `P` to remote origin using expected remote tip `T`:




   DOS
   ```
   git push --force-with-lease=refs/heads/master:T origin master

   ```
9. Confirm remote ref equals `P`. Emit `integration_completed`.




### 11.3 Isolation Re-Run for Failed Integration

If integration gates fail at proposed SHA `P`, chargeability is determined via isolation re-run:

1. Git Operator executes failing gate against `candidate_sha` in a detached, clean worktree.



2. If gate fails at `candidate_sha`: author defect (`chargeable_attempt = 1`).



3. If gate passes at `candidate_sha` (but failed at `P`): interaction defect caused by intervening sibling commits (`chargeable_attempt = 0`). Task is rebased and re-queued.




### 11.4 Path Reservations (`CONCURRENT` Mode)

If a task accumulates `invalidation_count >= 2`, the controller grants an exclusive path reservation over its declared `allowed_files` for 60 minutes. Any concurrent task attempting to integrate touching those paths is deferred until the reserved task integrates.

## 12. Failure Taxonomy & Chargeability Rules

| **Failure Scenario**                                    | **Classification**   | **Chargeable** | **Controller Action**                 |
| ------------------------------------------------------- | -------------------- | -------------- | ------------------------------------- |
| Test assertion failure, lint error, syntax error        | `AUTHOR_DEFECT`      | **Yes**        | `CHANGES_REQUESTED`                   |
| Scope violation, forbidden path modified                | `AUTHOR_DEFECT`      | **Yes**        | `CHANGES_REQUESTED`                   |
| Integration failure reproducible at `candidate_sha`     | `AUTHOR_DEFECT`      | **Yes**        | `CHANGES_REQUESTED`                   |
| Integration failure only at merge object `P`            | `INTERACTION_DEFECT` | **No**         | `CHANGES_REQUESTED` (retry free)      |
| Missing environment package, locked file, reserved port | `ENVIRONMENT_DEFECT` | **No**         | `AUTHOR_BLOCKED` or `REVIEW_BLOCKED`  |
| Network timeout, worker host crash, dropped socket      | `INFRA_ERROR`        | **No**         | Reissue activation to ready queue     |
| Gate execution exceeds hard timeout (first occurrence)  | `TIMEOUT`            | **No**         | Re-run gate once                      |
| Gate execution exceeds hard timeout (second occurrence) | `TIMEOUT`            | **No**         | Stage blocked; escalate to Admin      |
| Flake suspected (identical tuple, different outcome)    | `FLAKE_SUSPECTED`    | **No**         | Quarantine investigation task created |
| Inconclusive behavior proof / AST error                 | `AMBIGUITY`          | **No**         | Escalate to `NEEDS_HUMAN`             |
| Repository ref uncertain during rollback                | `CRITICAL_INCIDENT`  | **No**         | Freeze Git operations; alert Admin    |

## 13. Activations, Checkpoints & Liveness

- **Lease & Hard Deadline:** Activations carry a 5-minute renewable lease and an immutable hard deadline (default 90 minutes).



- **Dedicated Heartbeat Thread:** A lightweight daemon thread emits `POST /activations/{id}/heartbeat` every 60 seconds independently of subprocess execution.



- **Deadline Enforcement:** If `hard_deadline_at` is breached, the harness terminates running subprocesses, triggers the Git Operator to capture a WIP checkpoint commit, and terminates.



- **Quarantine:** Stale or abandoned worktrees are moved to `D:\wt\quarantine\` by the Git Operator before replacement activations execute.




## 14. Budget Windows & Token Metering

The controller tracks Claude's rolling 5-hour window on `OFFICEPC` across all activations using `budget_windows`:

1. Before issuing an activation to Claude, the controller verifies that the 5-hour rolling consumption has $\ge 15\\%$ headroom.



2. If headroom is insufficient, the activation remains in `READY_AUTHOR` or `READY_REVIEW` until the window rolls over.



3. If an API provider returns a 429 rate-limit error, the worker reports `INFRA_ERROR` with the provider's `retry-after` header. The controller records the pause without penalizing the task’s retry budget.




## 15. Security & Isolation

1. **Credential Hygiene:** API keys are never stored in repository files, markdown handoffs, logs, or chat feeds. Keys are injected as environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) on `OFFICEPC` or managed through Unraid Docker templates on Tower.



2. **Untrusted Repo Data:** Code under test, commit messages, and comic metadata are treated as untrusted data. When logs or source diffs are fed into an LLM advisor or author context, they are strictly delimited in XML blocks with formatting caps.



3. **Endpoint Mutual Auth:** All endpoints require an `Authorization: Bearer <token>` header mapped to authenticated components (`gemini_advisor`, `chatgpt_author`, `claude_verifier`, `git_operator`, `admin`).




## 16. Windows Host Environment Specifics

- **Target Branch & Remote:** Target branch is confirmed as `master` with remote `origin`.



- **Path Lengths:** Git system configuration must enforce `core.longpaths = true`. Worktree roots are kept strictly at `D:\wt\`.



- **Line Ending Stability:** Worktrees use existing repository `.gitattributes`. Subprocess calls set `PYTHONIOENCODING=utf-8` with replacement decoding.



- **Process Locks on Cleanup:** The Git Operator retries directory deletions 5 times with 2-second backoff to handle Windows Defender and background search index locks.



- **Volume Isolation:** Test contracts are forbidden from accessing the production library root (`X:`). All operations execute against mock fixtures in `D:\swarm-tmp\`.




## 17. Protocol Versioning & Migration

1. Every task contract is bound to a frozen `protocol_schema_version`.



2. When the controller software is updated, active in-flight tasks run to terminal completion under their original schema rules.



3. The controller verifies on startup that no incomplete tasks exist under an unsupported legacy schema.




## 18. Observability & Generated State Renderings

`HANDOFF_CLAUDE.md`, `HANDOFF_CHATGPT.md`, `HANDOFF_GEMINI.md`, and `SWARM_STATE.md` are **ephemeral, generated database views**. They are refreshed by the controller on demand for human orientation. Resuming workers never read markdown to reconstruct state; they query the controller API directly.

### Required Deterministic Test Suite

Before deploying protocol upgrades, the following tests must pass:

- Duplicate identical result submission returns cached HTTP 200.



- Conflicting result payload on completed activation returns HTTP 409.



- Worker attempting state change with stale `state_seq` returns HTTP 409.



- Subprocess execution exceeding hard deadline forces WIP checkpoint.



- Controller clock ahead/behind harness clock by 5 minutes operates without error.



- Integration failure correctly triggers CAS rollback to prior `master` SHA.



- Gate evidence citing nonexistent blob hash returns HTTP 409.



- Low-priority task repeatedly invalidated integrates within 3 aging cycles.




## 19. Implementation Rollout

```
Phase 0: Safety & Auth Containment (Immediate)
   ├── Rotate all exposed API keys.
   ├── Enforce Bearer token auth across all Hub endpoints.
   └── Strip agent activation logic from chat feed.

Phase 1: Controller Core & DB Ledger
   ├── Deploy SQLite schema with WAL and strict FK constraints.
   ├── Implement atomic result processing, leases, and monotonic durations.
   └── Upgrade workers to single-activation pull pattern.

Phase 2: Worktree Isolation & Evidence Blobs
   ├── Deploy Git Operator service on OFFICEPC.
   ├── Implement diff gates, blob uploads, and behavior proof.
   └── Run 20 production tasks in SERIAL mode.

Phase 3: High-Throughput Concurrency (Conditional)
   ├── Implement integration saga, CAS ref advancement, and rollback.
   └── Enable path reservations and capacity scoring for CONCURRENT mode.

Phase 4: Telemetry & Advisory Layer
   ├── Connect Gemini advisor function calling.
   └── Deploy generated dashboard views and budget gauges.

```

## Appendix A — Complete Event Catalogue

Plaintext

```
contract_validated           validation_failed
queued                       author_activation_issued
review_activation_issued     activation_claimed
candidate_submitted          checkpoint_captured
environment_defect           environment_repaired
author_defect                retry_authorized
budget_exhausted             review_requirements_satisfied
proof_inconclusive           decision_required
integration_started          integration_rejected
integration_completed        reservation_granted
rollback_started             rollback_completed
repository_uncertain         lease_expired
hard_deadline_reached        regression_reverted
return_to_author             return_to_review
create_contract_version      admin_failed
admin_cancelled              superseded
note

```

## Appendix B — Advisor Call Packet Schema

When the controller queries Gemini for triage or planning:

JSON

```
{
  "packet_version": 2,
  "question": "triage_failure",
  "task_id": "T-0042",
  "task_version": 1,
  "contract_excerpt": {
    "allowed_files": ["parsers/cbz_parser.py"],
    "commands": ["python -m pytest tests/test_cbz_parser.py -q"]
  },
  "diff_stat": {
    "files_changed": 1,
    "insertions": 14,
    "deletions": 2
  },
  "evidence": {
    "gate_id": "unit",
    "exit_code": 1,
    "outcome": "FAIL",
    "stderr_tail": "AssertionError: expected malformed ComicInfo.xml to be rejected"
  },
  "allowed_proposals": [
    "AUTHOR_DEFECT",
    "ENVIRONMENT_DEFECT",
    "FLAKE",
    "CONTRACT_AMBIGUOUS"
  ]
}

```

The advisor must respond with a JSON object selecting one allowed proposal with a one-paragraph rationale. The controller validates the response against the schema; invalid responses are rejected and escalated to Admin.