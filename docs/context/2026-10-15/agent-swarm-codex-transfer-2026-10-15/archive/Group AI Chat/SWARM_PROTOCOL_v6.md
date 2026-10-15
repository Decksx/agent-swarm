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