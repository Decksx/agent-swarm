"""Authoritative schema for the controller.

This is the only place the shape of authoritative state is defined. It follows
`SWARM_PROTOCOL_v7.md` §4, which allows an implementation to normalize the
layout but requires the constraints to survive; where this differs from the
document, the difference is noted at the table and is a tightening rather than
a relaxation.

Two rules govern everything below and are worth stating before the SQL, because
neither is visible in a `CREATE TABLE`:

* **Only the controller process opens this database for writing.** The
  container runs a single uvicorn worker, which is what makes that true. Adding
  `--workers N` to the run command would put several processes behind the same
  WAL file and corrupt it slowly and confusingly.
* **Every projection update and its event append happen in one
  `BEGIN IMMEDIATE` transaction.** A task whose state moved without an event, or
  an event without the matching state, is unreconstructable after the fact --
  the event log is the audit trail *and* the recovery mechanism, so the two
  cannot drift apart even by a crash.

Foreign keys are enforced (`PRAGMA foreign_keys = ON`), which SQLite does not
do by default. Without it every `REFERENCES` clause here is documentation
rather than a constraint.
"""

from __future__ import annotations

# Bumped whenever the statements below change in a way an existing database
# cannot simply adopt. Startup compares this against `PRAGMA user_version` and
# refuses to run against a database it does not understand, rather than
# applying half-matching SQL to it (§17: startup fails closed).
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- One row per task. `state` and `state_seq` are the projection that the event
-- log can rebuild; `state_seq` increments on every accepted transition and is
-- what a worker's result must match, so a result computed against a state the
-- task has since left is rejected instead of applied to the wrong state.
CREATE TABLE IF NOT EXISTS tasks (
  task_id          TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  objective        TEXT NOT NULL,
  priority         INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  current_version  INTEGER NOT NULL,
  state            TEXT NOT NULL,
  state_seq        INTEGER NOT NULL DEFAULT 0,
  enqueued_at      REAL,
  created_at       REAL NOT NULL,
  created_by       TEXT NOT NULL
);

-- Contracts are immutable per version and live here, never in the candidate
-- worktree. A contract read from the tree being changed could be edited by the
-- author it is meant to constrain.
CREATE TABLE IF NOT EXISTS task_versions (
  task_id                 TEXT NOT NULL REFERENCES tasks(task_id),
  version                 INTEGER NOT NULL,
  contract_yaml           TEXT NOT NULL,
  contract_hash           TEXT NOT NULL,
  protocol_schema_version INTEGER NOT NULL,
  base_sha                TEXT NOT NULL,
  proof_mode              TEXT NOT NULL
                          CHECK (proof_mode IN ('baseline', 'sabotage', 'both')),
  created_at              REAL NOT NULL,
  created_by              TEXT NOT NULL,
  PRIMARY KEY (task_id, version)
);

CREATE TABLE IF NOT EXISTS task_deps (
  task_id      TEXT NOT NULL REFERENCES tasks(task_id),
  depends_on   TEXT NOT NULL REFERENCES tasks(task_id),
  kind         TEXT NOT NULL CHECK (kind IN ('blocks', 'prefer_after')),
  PRIMARY KEY (task_id, depends_on),
  CHECK (task_id <> depends_on)
);

-- An activation is one worker's permission to make one bounded attempt.
--
-- `lease_expires_at` and `hard_deadline_at` are stored on the controller clock
-- and are NEVER sent to a harness: responses carry remaining durations instead,
-- because comparing an OFFICEPC timestamp with a Tower timestamp is a bug
-- waiting for the two clocks to drift (§5).
--
-- `result_request_hash` is what makes a duplicate delivery idempotent: the same
-- request returns the cached response, a different one for the same activation
-- is a conflicting replay and is refused.
CREATE TABLE IF NOT EXISTS activations (
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
  status              TEXT NOT NULL,
  result_event_id     TEXT,
  result_request_hash TEXT,
  result_response     TEXT,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

-- The append-only audit trail. `seq` is the total order; `event_id` is the
-- caller-visible identity and is UNIQUE so a retried append cannot duplicate a
-- row. Replaying this table in `seq` order must reproduce `tasks.state`
-- exactly -- that equivalence is asserted by the tests, because an audit log
-- that cannot rebuild the projection is a log, not a source of truth.
CREATE TABLE IF NOT EXISTS events (
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

-- `authoritative` separates a verifier's evidence from an author's advisory
-- self-check. Only authoritative rows can satisfy a gate; an author cannot
-- pass its own work by running the tests itself.
CREATE TABLE IF NOT EXISTS evidence (
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
  local_log_path    TEXT,
  outcome           TEXT NOT NULL,
  created_at        REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);

-- Content-addressed, so two runs producing identical output store one copy.
CREATE TABLE IF NOT EXISTS evidence_blobs (
  blob_hash            TEXT PRIMARY KEY,
  byte_length          INTEGER NOT NULL,
  truncated            INTEGER NOT NULL DEFAULT 0,
  original_stream_hash TEXT,
  original_byte_length INTEGER,
  stored_path          TEXT NOT NULL,
  created_at           REAL NOT NULL
);

-- Retention belongs to the reference, not the blob (§9). One deduplicated blob
-- can support both a throwaway review attempt and a completed integration, and
-- deleting it on the review's schedule would destroy the integration proof.
CREATE TABLE IF NOT EXISTS evidence_blob_refs (
  evidence_id      TEXT NOT NULL REFERENCES evidence(evidence_id),
  blob_hash        TEXT NOT NULL REFERENCES evidence_blobs(blob_hash),
  stream_kind      TEXT NOT NULL
                   CHECK (stream_kind IN ('stdout', 'stderr', 'attachment')),
  retention_class  TEXT NOT NULL
                   CHECK (retention_class IN ('review', 'failure', 'integration')),
  retain_until     REAL,
  PRIMARY KEY (evidence_id, blob_hash, stream_kind)
);

-- Fence epochs are monotonic per protected resource and are NOT reset by a
-- release, so a holder that wakes up after losing its lock cannot act on a
-- resource that has since been reassigned.
CREATE TABLE IF NOT EXISTS resource_epochs (
  lock_name   TEXT PRIMARY KEY,
  next_epoch  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS locks (
  lock_name      TEXT PRIMARY KEY REFERENCES resource_epochs(lock_name),
  holder         TEXT NOT NULL,
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  fence_epoch    INTEGER NOT NULL,
  acquired_at    REAL NOT NULL,
  expires_at     REAL NOT NULL
);

-- Spend, metered per agent and model. `limit_value` and `consumed` are in
-- whatever unit `window_kind` names -- this build uses dollars for the paid
-- providers and seconds of rolling window for the subscription-billed one,
-- which is why the unit is not baked into the column name.
CREATE TABLE IF NOT EXISTS budget_windows (
  agent         TEXT NOT NULL,
  model         TEXT NOT NULL,
  window_kind   TEXT NOT NULL,
  window_start  REAL NOT NULL,
  consumed      REAL NOT NULL DEFAULT 0,
  limit_value   REAL NOT NULL,
  update_seq    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (agent, model, window_kind, window_start)
);

CREATE TABLE IF NOT EXISTS host_capacity (
  host                  TEXT PRIMARY KEY,
  max_concurrent        INTEGER NOT NULL,
  drain_requested       INTEGER NOT NULL DEFAULT 0,
  exclusive_holder_kind TEXT CHECK (
                          exclusive_holder_kind IN ('activation', 'integration')
                          OR exclusive_holder_kind IS NULL),
  exclusive_holder_id   TEXT
);

-- Indexes for the queries the scheduler actually runs: find ready tasks, find
-- a host's live activations, and replay one task's events in order.
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, priority DESC);
CREATE INDEX IF NOT EXISTS idx_activations_status ON activations(status, host);
CREATE INDEX IF NOT EXISTS idx_activations_task ON activations(task_id, task_version);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id, task_version, gate_id);
"""

# Tables listed for the tests and for the startup check. Kept explicit rather
# than derived from the SQL text so that a table silently dropped from
# SCHEMA_SQL fails a test instead of quietly disappearing from both.
EXPECTED_TABLES = (
    "tasks",
    "task_versions",
    "task_deps",
    "activations",
    "events",
    "evidence",
    "evidence_blobs",
    "evidence_blob_refs",
    "resource_epochs",
    "locks",
    "budget_windows",
    "host_capacity",
)
