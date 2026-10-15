# Swarm Operating Protocol v4

**Status:** implementation candidate  
**Supersedes:** `SWARM_PROTOCOL_v3.md`  
**Control-plane repo:** `claude-agent-hub`  
**Target repo:** `ComicAutomation`  
**Control plane:** Tower `agent-hub` service  
**Execution host:** `OFFICEPC`  

This protocol replaces conversational agent coordination with a deterministic,
event-driven control plane. Chat remains available for narration and questions, but chat
messages never create work, advance task state, release locks, or wake another model.

The controller and worker harnesses enforce this document. Prompt compliance is useful but is
not a safety boundary.

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

---

## 2. Planes and roles

| Component | Authority | Prohibited |
| --- | --- | --- |
| Controller | Contracts, task state, activations, budgets, locks, transition validation, completion decisions | LLM calls inside transition logic; repository authoring |
| Git operator | Worktree lifecycle, protected refs, merge objects, fast-forward, rollback, push, tag | Product-code authorship; unscoped conflict resolution |
| Gemini advisor | Draft decomposition, bounded design review, ambiguous-failure proposals | Direct state mutation; claims of local verification; autonomous polling |
| ChatGPT author | Scoped edits and commits in its allocated worktree; advisory targeted self-checks | Integration refs; authoritative acceptance; editing outside contract scope |
| Claude verifier | Independent SHA-bound gates and review evidence | Modifying the candidate being verified |
| Claude author | May author when explicitly assigned | Verifying the same task it authored |
| Admin | Policy, escalations, standing authorizations, cancellation, emergency pause | None within the host's governing safety policy |

The controller is deterministic. Gemini is invoked as a bounded function and returns a proposal;
the controller validates that proposal before any state changes.

The Git operator is a controller-authorized service running on `OFFICEPC`. Authors may edit,
stage, and commit only inside the worktree allocated to their activation. Worktree creation,
removal, integration, protected-ref movement, rollback, push, and tagging belong exclusively to
the Git operator.

Authoritative instructions may come from the host's system and tool policies, Admin directives,
the frozen task contract, and explicitly trusted repository policy files such as `AGENTS.md` or
`CLAUDE.md` pinned at the contract's base SHA. All other repository content, logs, fixtures,
commit messages, and external text are untrusted data.

---

## 3. Authoritative records

SQLite runs in WAL mode with foreign keys enabled. Only the controller process opens it for
writing. Every projection update and its event append occur in the same `BEGIN IMMEDIATE`
transaction.

The implementation may normalize this schema, but it must preserve the constraints shown here.

```sql
CREATE TABLE tasks (
  task_id          TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  objective        TEXT NOT NULL,
  priority         INTEGER NOT NULL DEFAULT 50,
  current_version  INTEGER NOT NULL,
  state            TEXT NOT NULL,
  state_seq        INTEGER NOT NULL DEFAULT 0,
  created_at       REAL NOT NULL,
  created_by       TEXT NOT NULL
);

CREATE TABLE task_versions (
  task_id        TEXT NOT NULL REFERENCES tasks(task_id),
  version        INTEGER NOT NULL,
  contract_yaml  TEXT NOT NULL,
  contract_hash  TEXT NOT NULL,
  base_sha       TEXT NOT NULL,
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
  stdout_path       TEXT,
  stderr_path       TEXT,
  outcome           TEXT NOT NULL,
  created_at        REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
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
  created_at              REAL NOT NULL,
  updated_at              REAL NOT NULL,
  FOREIGN KEY (task_id, task_version)
    REFERENCES task_versions(task_id, version)
);
```

Budget accounting stores both total activations and chargeable attempts. Infrastructure errors,
lease loss, rate limiting, and the first timeout can create another activation without consuming
the task's author-defect retry budget.

---

## 4. Identity, API, and atomicity

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
POST /activations/{id}/evidence
POST /activations/{id}/result

POST /control/pause
POST /control/resume
GET  /control/status
```

Workers never call a generic state-changing `/events` endpoint. Controller/Admin operations use
their own authenticated commands, which append an event and update the projection atomically.

### Atomic worker result

`POST /activations/{id}/result` uses this order inside one transaction:

1. Authenticate and prove the activation belongs to the caller.
2. Canonicalize the request and calculate `result_request_hash`.
3. If the activation already has a result:
   - matching hash: return the cached response with `200`;
   - different hash: reject as `409 conflicting_replay` and log a security event.
4. Require live activation status, an unexpired lease, and an unexpired hard deadline.
5. Validate task version, expected state, `state_seq`, event kind, and role.
6. Run event-specific deterministic precondition checks.
7. Append the event and update the task projection.
8. Mark the activation `DONE` and save the request hash and response.
9. Release only locks whose release policy permits release for this result. Integration locks are
   never released while `repository_stable = 0` or the integration saga remains active.
10. Commit.

Incremental evidence submission does not advance state. Evidence rows are immutable. A worker
cannot satisfy a gate merely by emitting `gates_passed`; the controller computes gate completion
from evidence.

---

## 5. Task contract

Contracts are immutable per version and live in controller storage. Commands are never loaded
from the candidate worktree.

```yaml
schema_version: 4
task_id: T-0042
version: 1
title: Harden CBZ parser against malformed ComicInfo.xml
objective: Reject malformed metadata without changing established public behavior.

roles:
  author: chatgpt
  verifier: claude

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
    required: false
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

The contract linter verifies schema, full object IDs, branch existence, dependency acyclicity,
role separation, scope intersections, command availability, behavior-proof selectors, registered
locks, budgets, authorization profile, and absence of overlap with unordered active tasks.

A standing authorization profile is an Admin-owned, versioned policy record. It can preauthorize
operations such as ordinary migrations when that authority has already been granted. It cannot
override host safety controls or silently expand a task's declared scope.

---

## 6. State machine

### States

| State | Meaning |
| --- | --- |
| `DRAFT` | Contract is being prepared |
| `VALIDATED` | Contract passed deterministic linting |
| `READY_AUTHOR` | Dependencies permit an author activation |
| `AUTHOR_ASSIGNED` | Author activation issued but not claimed |
| `AUTHORING` | Author activation running |
| `AUTHOR_PAUSED` | Safe WIP checkpoint captured; resumable |
| `AUTHOR_BLOCKED` | Author-stage environment problem |
| `READY_REVIEW` | Candidate submitted and awaiting verifier |
| `REVIEW_ASSIGNED` | Verifier activation issued but not claimed |
| `REVIEWING` | Verifier activation running |
| `REVIEW_PAUSED` | Review checkpoint captured; resumable |
| `REVIEW_BLOCKED` | Review-stage environment problem |
| `CHANGES_REQUESTED` | Candidate needs chargeable author correction |
| `READY_INTEGRATION` | Controller proved all review requirements |
| `INTEGRATING` | Serialized integration saga owns integration fence |
| `REVERTING` | Target was mutated and the same saga is restoring it |
| `NEEDS_HUMAN` | A specific Admin decision is required |
| `COMPLETE` | Tested object integrated and refs verified |
| `FAILED` | Unrecoverable or budget-exhausted |
| `CANCELLED` | Cancelled by Admin |
| `SUPERSEDED` | Replaced by another task/version |
| `EXPIRED` | Human escalation expired |
| `REVERTED` | Previously complete change was later reverted |

Terminal states are `COMPLETE`, `FAILED`, `CANCELLED`, `SUPERSEDED`, `EXPIRED`, and `REVERTED`.

### Principal transitions

| From | Event | To | Authority |
| --- | --- | --- | --- |
| `DRAFT` | `contract_validated` | `VALIDATED` | controller |
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
| `REVIEWING` | `decision_required` | `NEEDS_HUMAN` | verifier/controller |
| `REVIEWING` | `lease_expired` | `READY_REVIEW` | controller |
| `REVIEWING` | `hard_deadline_reached` | `READY_REVIEW` or `REVIEW_PAUSED` | controller/operator |
| `REVIEW_PAUSED` | `review_activation_issued` | `REVIEW_ASSIGNED` | controller |
| `REVIEW_BLOCKED` | `environment_repaired` | `READY_REVIEW` | controller |
| `CHANGES_REQUESTED` | `retry_authorized` | `READY_AUTHOR` | controller |
| `CHANGES_REQUESTED` | `budget_exhausted` | `NEEDS_HUMAN` | controller |
| `READY_INTEGRATION` | `integration_started` | `INTEGRATING` | controller/operator |
| `INTEGRATING` | `integration_rejected` | `CHANGES_REQUESTED` | controller/operator |
| `INTEGRATING` | `integration_completed` | `COMPLETE` | controller |
| `INTEGRATING` | `rollback_started` | `REVERTING` | controller/operator |
| `REVERTING` | `rollback_completed` | `CHANGES_REQUESTED` | controller/operator |
| `REVERTING` | `repository_uncertain` | `NEEDS_HUMAN` | controller/operator |
| `COMPLETE` | `regression_reverted` | `REVERTED` | Admin/controller |

Every nonterminal state also accepts Admin cancellation or supersession. `NEEDS_HUMAN` has no
generic `resume` transition. The Admin response must select one explicit, validated action such
as `return_to_author`, `return_to_review`, `create_contract_version`, `fail`, or `cancel`.

### Deterministic completion predicates

The controller emits `review_requirements_satisfied` only if:

- the candidate is the current candidate for the current task version;
- the diff gate passed;
- every required review gate has authoritative `PASS` evidence from the assigned verifier;
- evidence targets the exact candidate SHA and current contract hash;
- required behavior proof succeeded;
- no unresolved scope violation, inconclusive proof, or flake report exists.

The controller emits `integration_completed` only if:

- every integration gate passed against the exact proposed integration SHA;
- the integration saga reports `repository_stable = 1`;
- the protected local and required remote refs equal that SHA;
- ref advancement used compare-and-swap against the recorded prior tip;
- required logs and evidence are durable.

---

## 7. Activations, leases, and checkpoints

An activation has a renewable liveness lease and an immutable hard deadline. A dedicated harness
thread sends heartbeats, but no heartbeat extends `hard_deadline_at`. At the deadline, the harness
cancels child processes, requests a safe checkpoint when the stage permits it, submits its final
result, and stops.

The conditional deadline transitions above are deterministic: use the paused state only when a
valid checkpoint was durably captured in the same controller transaction; otherwise return to the
stage's ready state. Lease or deadline recovery quarantines the abandoned worktree before a new
activation is issued. A late process may continue writing only to that isolated quarantined
worktree; its state changes and candidate submission are rejected.

Workers claim at most one activation. After submitting a result they do not claim again until the
current invocation has exited. Infrastructure replacement activations set
`chargeable_attempt = 0`; author-defect retries set it to `1`.

### Safe author checkpoint

An author checkpoint is accepted only after the Git operator:

1. Stops further author writes.
2. Captures the allocated worktree as a WIP commit under
   `refs/swarm-checkpoints/{task}/{version}/{activation}`.
3. Records the WIP SHA, parent SHA, changed paths, and patch hash.
4. Confirms the worktree is clean after capture.
5. Appends `checkpoint_captured` atomically with transition to `AUTHOR_PAUSED`.

The WIP commit is not a candidate and cannot be reviewed or integrated. A replacement author
activation receives the checkpoint ref and resumes in the same scoped worktree or a new worktree
created from that WIP SHA.

Review checkpoints contain completed gate IDs and immutable evidence IDs. A replacement verifier
may reuse only eligible hermetic evidence; all other pending or interrupted gates rerun.

Integration is not model-checkpointable. The deterministic integration saga either reaches a
stable outcome or holds the integration lock and globally pauses protected Git operations for
recovery.

---

## 8. Git isolation and candidate rules

Each author attempt receives a unique worktree and branch:

```text
D:\wt\{task_id}-{activation_id}
swarm/{task_id}/v{version}/a{attempt}
```

Candidate SHAs use one of two contract-recorded ancestry modes:

- `squash`: candidate has `base_sha` as its direct parent;
- `stacked`: candidate has the previous candidate as direct parent, while all gates evaluate the
  complete `base_sha..candidate` change.

The object-level diff gate calculates `git diff --name-status base_sha candidate_sha` and proves
that changed paths are a subset of allowed files/directories. It rejects forbidden paths,
unauthorized merges, submodule changes, escaping symlinks, generated artifacts, prohibited
deletions, and prohibited case-only renames.

The verifier uses a detached clean worktree at the exact candidate SHA. Author self-check results
are recorded with `authoritative = 0`; verifier results use `authoritative = 1`.

---

## 9. Behavior proof and evidence

Behavior proof executes only named selectors. The baseline uses the candidate's relevant test
changes applied to a disposable base worktree, then executes those selectors. A qualifying
baseline failure must match the declared exception type and message pattern. Collection, import,
fixture, environment, and usage errors are inconclusive.

Candidate selectors must pass at the candidate SHA. Critical guards should additionally use a
reviewed, machine-readable sabotage patch in a disposable worktree and prove the named tests fail
when the guard is disabled.

Baseline-fail/candidate-pass proves that a test distinguishes the change. Sabotage proves that the
test depends on the modified guard. Neither alone proves that the requested semantics are correct;
independent diff/design review remains required when the contract calls for it.

Evidence caching is disabled by default. It is allowed only for a gate explicitly declared
hermetic, and the cache key includes:

```text
target SHA + gate ID + command hash + contract hash + environment hash + fixture hash
```

Integration evidence is never cached.

Different outcomes constitute `FLAKE_SUSPECTED` only when that entire identity tuple matches.
Flake-suspected tests are never automatically quarantined. Quarantine requires a separate task,
owner, justification, review, and expiration date.

---

## 10. Runtime isolation and resource locks

Worktrees do not isolate databases, ports, external services, environment variables, temp roots,
Docker names, shared caches, registry state, or the real comic library. Contracts declare these
resources, and the harness enforces their locks for author self-checks as well as verification.

`external_writes: forbidden` and `library_root: forbidden` are defaults. Any exception must be
explicitly authorized and serialized.

Fence epochs are monotonic per protected resource. Releasing a lock does not reset its epoch. The
consumer of a protected resource rejects an operation whose epoch is not the currently active
epoch for that resource. Git integration uses the dedicated `integration` resource epoch; an
unrelated database lock cannot invalidate it.

---

## 11. Integration saga

One integration saga runs at a time under the `integration` lock.

1. Record current protected target tip `T` and candidate `X`.
2. Create a scratch integration worktree at `T`.
3. Merge `X` without resolving conflicts. A conflict creates a separate authored
   conflict-resolution task; the integrator never edits through it silently.
4. Record proposed integration SHA `P` and set `repository_stable = 1` because protected refs have
   not moved.
5. Re-run the scope/contract invalidation checks against `T..P`.
6. Run every integration gate against exactly `P`.
7. If a gate fails before protected refs move, discard the scratch worktree and emit
   `integration_rejected`; no rollback state is required.
8. Advance the local protected ref with compare-and-swap:

   ```text
   git update-ref refs/heads/{target_branch} P T
   ```

9. Push the exact tested object using the recorded expected remote tip. Never create a fresh merge
   during push or integration.
10. Verify every required local and remote ref equals `P`.
11. Persist evidence and emit `integration_completed`.
12. Release the integration lock only after the saga is durable and `repository_stable = 1`.

If a protected ref moved and a later step fails, set `repository_stable = 0`, transition to
`REVERTING`, and keep the integration lock. The same deterministic operator saga attempts a
compare-and-swap restoration to the recorded prior tip. It then either:

- proves all protected refs stable and emits `rollback_completed`; or
- emits `repository_uncertain`, retains the lock, globally pauses protected Git operations, and
  creates a `NEEDS_HUMAN` incident.

Reproducible merge timestamps are unnecessary because the system tests and advances the exact
existing object `P`; it never reconstructs that object after testing.

---

## 12. Failures and human decisions

| Failure | Chargeable | Default outcome |
| --- | --- | --- |
| Author defect, lint/test failure, scope violation | yes | `CHANGES_REQUESTED` |
| Environment defect | no | stage-specific blocked state |
| Network/rate limit/worker crash | no | return to the same ready stage |
| First timeout | no | one replacement activation |
| Repeated timeout | no | stage-specific blocked state |
| Inconclusive behavior proof | no | `NEEDS_HUMAN` |
| Flake suspected under identical evidence identity | no | investigation/escalation |
| Contract ambiguity | no | `NEEDS_HUMAN` |
| Repository state uncertain | no | global Git pause + `NEEDS_HUMAN` |

Every human escalation contains one bounded question and enumerated allowed resolutions. A human
response is an authenticated command, not a chat mention. It returns the task to an explicit stage
or creates a new frozen contract version; it never uses a generic resume.

---

## 13. Security

1. Revoke and replace any API key that appeared in plaintext. Deleting it is insufficient.
2. Inspect Git history and retained document/chat copies to determine exposure.
3. Store replacement credentials in managed secrets or a protected environment file excluded from
   version control.
4. Authenticate every endpoint, including chat endpoints; authorize by role and activation.
5. Keep the hub on LAN/Tailscale unless a reviewed access layer protects it.
6. Fence and truncate untrusted repository/log content before sending it to a model.
7. Scope tools and filesystem access per activation.
8. Record every protected operation with actor, task, activation, contract hash, and fence epoch.

---

## 14. Windows and ComicAutomation rules

- Confirm the actual remote, target branch, and target path during bootstrap; contracts must use
  the verified values. Current project history indicates `master`, not `main`.
- Keep worktree roots short and check free space before creation.
- Do not perform repository-wide line-ending normalization during swarm bootstrap.
- Treat a newly created dirty worktree as an infrastructure defect and investigate the existing
  repository policy separately.
- Capture native-command exit codes, stdout, and stderr separately under the declared shell.
- Use UTF-8 subprocess decoding with replacement for undecodable diagnostic bytes.
- Retry targeted Windows worktree cleanup, then mark cleanup residue for the reaper. Never delete
  an unresolved broad path.
- Check reserved ports before tests and distinguish reservation from a product failure.
- Never allow ordinary test contracts to read from or write to the authoritative `X:` library.

---

## 15. Observability and generated handoffs

The UI shows the task board, current task version, candidate/integration SHAs, activation lease and
hard deadline, worker heartbeat, resource locks and epochs, budgets, evidence, and the
`NEEDS_HUMAN` queue.

`HANDOFF_CLAUDE.md`, `HANDOFF_CHATGPT.md`, `HANDOFF_GEMINI.md`, and `SWARM_STATE.md` are generated
views of the database. They are never authoritative and are never read back to mutate state. A
resuming worker loads its contract, activation, checkpoint, and relevant event tail from the API.

Required deterministic tests include:

- duplicate identical result;
- conflicting result replay;
- stale task version and stale `state_seq`;
- wrong authenticated worker or role;
- crash before and after transaction commit;
- heartbeat alive past hard deadline;
- author and review checkpoint recovery;
- stage-correct repair from both blocked states;
- late result after lease expiry;
- stale fence after lock reassignment;
- unrelated resource epoch not invalidating integration;
- integration crash before ref movement;
- integration crash after local movement and before remote confirmation;
- external target movement during compare-and-swap;
- required evidence missing, stale, advisory, or bound to the wrong SHA;
- event-log replay exactly matching task projections.

---

## 16. Rollout

### Phase 0 — Immediate containment

1. Rotate exposed credentials and inspect their exposure history.
2. Authenticate every endpoint and bind actor identity server-side.
3. Make workers ignore agent-authored chat messages for activation purposes.
4. Add a visible global pause and verify it prevents new activations.

### Phase 1 — Controller core

1. Implement schema, atomic controller/Admin transitions, and atomic worker results.
2. Implement idempotency hashes, CAS, leases, hard deadlines, and stage-specific recovery.
3. Convert workers to pull exactly one activation.
4. Pass the deterministic transition, replay, identity, and crash tests.

### Phase 2 — Worktrees and verification

1. Implement operator-managed worktrees and scoped author branches.
2. Implement object-level diff gates and candidate ancestry validation.
3. Implement authoritative evidence predicates and behavior proof.
4. Add safe author/reviewer checkpoint capture and resumption.

### Phase 3 — Integration safety

1. Implement per-resource fence epochs and the serialized integration saga.
2. Implement compare-and-swap ref advancement and recovery after every crash point.
3. Verify that the integration lock cannot be released while repository state is uncertain.

### Phase 4 — Budgets, advisor, and UI

1. Implement chargeable-attempt accounting, rate-limit windows, and bounded advisor packets.
2. Generate handoff views from the ledger.
3. Add task, escalation, deadline, evidence, and lock views.

### Pilot acceptance

Use one leaf-module guard and one named behavior test in files untouched by open work. Do not use
`.gitattributes`, migrations, production databases, the authoritative comic library, or PR #90 as
the pilot.

The pilot succeeds only when fault injection proves every safety layer is load-bearing, including
duplicate delivery, worker death, stale fencing, interrupted checkpoints, failed integration, and
controller restart/replay.

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
decision_required          integration_started
integration_rejected       integration_completed
rollback_started           rollback_completed
repository_uncertain       lease_expired
hard_deadline_reached      regression_reverted
return_to_author           return_to_review
create_contract_version    admin_failed
admin_cancelled            superseded
note
```

`note` is advisory and never advances state. No event in this catalogue activates a worker unless
the deterministic transition action explicitly issues an activation.

## Appendix B — Advisor boundary

Each advisor call contains a schema version, one bounded question, an explicit response schema,
and a list of allowed proposals. The advisor receives only the repository map, contract excerpts,
diff/evidence excerpts, and prior decisions necessary for that question. The controller applies no
proposal that violates policy, authorization, state, scope, or deterministic evidence
requirements. Malformed output is logged once and then escalated; the advisor is not called
repeatedly for the same decision.
