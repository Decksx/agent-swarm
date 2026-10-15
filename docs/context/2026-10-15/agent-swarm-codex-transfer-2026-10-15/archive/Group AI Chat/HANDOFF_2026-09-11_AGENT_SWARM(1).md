# Agent Swarm Session Handoff

**Prepared:** 2026-09-11  
**Purpose:** Clear the current Claude Code and ChatGPT/Codex context windows without losing the verified project state or restarting completed work.

## 1. User objective and priorities

The immediate objective is a genuinely unattended three-agent development system:

- Gemini inspects registered repositories, evaluates milestones, proposes grounded tasks, and reviews candidates.
- ChatGPT authors bounded changes from controller-issued activations.
- Claude Code performs terminal-capable execution, testing, debugging, and deterministic integration.
- The controller owns task state, leases, handoffs, and the evidence ledger.
- The user must not have to copy and paste messages between agents or manually start every stage.

Optimize for finishing real projects faster. Do not reopen completed security-hardening work unless a security mechanism is directly breaking functionality. The installation is a private homelab. Existing component credentials and server-bound identity are deployed and working; retain them, but do not spend new sessions expanding the threat model.

## 2. Authoritative repository checkpoint

**Repository:** `Decksx/agent-swarm` (private GitHub repository)  
**Default branch:** `main`  
**Authoritative main commit:** `ac5fef6761349c73819a3e0a8d05677997f67f48`  
**Merge:** PR #2, “Automate candidate publication and controller stage handoffs”  
**Reviewed feature head:** `e66fb26320c42a2317637433571f4044bff1dbb7`  
**Merge tree:** byte-identical to the reviewed feature head  
**Merge parents:** previous main `d3d8ea66ffe9c2fb3e4cc473f5898b91d1ec9f03` and reviewed head `e66fb26320c42a2317637433571f4044bff1dbb7`

Do not resume from `phase1/mvp-slice`, `feature/unattended-handoff`, or another historical branch. First fetch and verify local `main` against the exact commit above. Determine the local repository root with Git rather than assuming a path.

## 3. Deployed state on Tower

Reported and reviewed live state after the final deployment:

| Item | State |
|---|---|
| Controller build | `6c9099d404a1` |
| Controller schema | 4 |
| Preflight | Green |
| Tasks | 11: 5 `CANCELLED`, 2 `COMPLETE`, 4 `READY_INTEGRATION` |
| Activations | 22: 19 `DONE`, 3 `EXPIRED`, 0 live |
| Capacity | one row: `officepc = 3` |
| Events | 90 |
| Test gate | 799 main tests + 127 hub tests |

The deployed files came from the reviewed feature tree. Because PR #2's merge tree is identical, the merge itself does not require another Tower deployment. Verify with preflight rather than redeploying reflexively.

## 4. What is completed

### Phase 0 containment

- Hub endpoints authenticate components and bind identity server-side.
- Workers cannot be activated by chat messages.
- Chat remains narration/operator communication only.
- Global pause is implemented and demonstrated.
- Historical hub database credential-pattern scan was clean: 1,134 text cells, zero matches.
- Provider-key rotation was operator-attested.
- Message timestamps include date, time, and timezone in the browser; agent-readable transcripts carry timestamps.

Do not repeat Phase 0 analysis.

### Controller and task lifecycle

- Versioned contracts, event log, replayable projection, state transitions, stale-write checks, idempotent result delivery, leases, heartbeats, expiry sweep, host capacity, and pause behavior exist.
- Controller HTTP routes are deployed.
- Review approval records the exact approved candidate SHA.
- Integrations that expire enter `INTEGRATION_UNCERTAIN` rather than being retried blindly.
- Reconciliation records landed/absent/failed outcomes.
- Activation insertion and the corresponding task transition now occur inside one `BEGIN IMMEDIATE` transaction.
- Real threaded tests prove concurrent issue/advance calls create exactly one activation and transition.

### Worker execution

- Claude, Gemini, and ChatGPT can claim controller activations.
- ChatGPT authoring is bounded by `allowed_paths` and read-only `context_paths`.
- Missing/unreadable scope and missing context fail before a model call.
- Authoring happens in isolated Git worktrees at the task's exact base SHA.
- Candidate publication pushes the exact SHA without force and creates or reuses exactly one matching PR.
- Publication failures block rather than regenerate a valid candidate.
- Explicit `proof_mode: branch_only` works through the real API under schema 4.
- Host names are trimmed and case-folded at capacity registration and activation issuance.
- Worker single-instance locking and actual child-process termination were previously demonstrated.

### Review and integration

- Gemini builds review evidence from the immutable `base..candidate` range rather than author prose or a moving branch.
- Gemini returns structured verdicts; the controller applies controller-authority transitions only for the live assigned review activation.
- Claude's integration path uses no model call.
- Integration derives the PR from controller-issued branch/candidate facts.
- It builds the merge locally at the pinned target and publishes through a non-force fast-forward push, so a moved target is refused without overwriting anything.
- Completion is recorded only after the remote contains the merge.

### Grounded planning

- Registered repository names and named refs select baselines; planners do not accept arbitrary paths.
- Snapshots distinguish immutable baseline evidence from dirty operational context and enumerate omissions/truncations.
- Planning supports bounded `NEEDS_CONTEXT`, literal-only `NEEDS_SEARCH`, `MILESTONE_READY`, and `BLOCKED_ACTIVE_WORK` outcomes.
- Context accumulates across rounds and call ceilings refuse rather than manufacture tasks.
- Earlier low-quality ComicAutomation proposals were cancelled and retained in the ledger with reasons.

## 5. Live demonstrations already completed

### CND-1: controller-native integration

The author, reviewer, and integrator all worked through controller activations. The candidate was reviewed and integrated with zero model calls from the integration stage. The first author attempt failed due to a driver/harness error and remains honestly recorded.

### CND-2: automated handoffs

**Demo repository:** `Decksx/agent-swarm-integration-demo`  
**PR:** #2  
**Candidate:** `5a9b7b46a6e13ab4f34c35fdbaa3d33ac5b55485`  
**Pinned target:** `7dcb0cc4735d21ed75a31c7dfea8ac05674237f0`  
**Merge:** `b4f8d21036520856b39f3c919905213da9754622`

Independently verified facts:

- Candidate CI check `verify` succeeded.
- The merge has the pinned target as first parent and approved candidate as second parent.
- The merge tree is identical to the approved candidate.
- `notes/unattended-result.md` contains exactly `Controller-native integration completed.` plus one trailing newline.
- Candidate push, PR creation, review activation issuance, and integration activation issuance occurred automatically.

Important limitation: a person still manually invoked each worker process and called `advance`. Handoffs are automated; the runtime is not yet persistent or fully unattended.

## 6. Historical task cleanup decision

Four historical demonstration tasks remain in `READY_INTEGRATION` without `approved_candidate_sha`. They predate schema 3 and can never be integrated under the current evidence rules. Progression correctly declines them, but a scheduler would report those declines forever.

At the beginning of the next session:

1. Query and identify the four exact task IDs; expected identities include the old MVP/DEMO records, but do not act from memory alone.
2. Confirm each has `approved_candidate_sha IS NULL` and no live activation.
3. Cancel each using the existing admin transition with a reason such as: `Historical Phase 1 demonstration; approval predates approved_candidate_sha and is not eligible for integration. Event history retained as evidence.`
4. Confirm the event ledger remains intact and `advance` no longer reports permanent declines.

Cancellation is preferred over adding an archive mechanism in the next branch.

## 7. Next branch: persistent swarm runtime

Create `feature/swarm-supervisor` from synchronized `main` only after the historical-task cleanup.

Scope is deliberately narrow:

1. One single-instance supervisor on OFFICEPC starts and monitors the ChatGPT, Gemini, and Claude worker processes.
2. It restarts crashed workers with bounded exponential backoff and never spawns duplicates.
3. It invokes controller progression and expiry sweep automatically at configurable intervals.
4. Empty queues cause zero model calls and zero chat messages.
5. Global pause prevents new claims and advancement without requiring the supervisor to exit.
6. Shutdown terminates the real Python child processes and leaves zero workers.
7. Logs are concise and timestamped: supervisor lifecycle, child start/stop/restart, progression issues/declines, sweep results, and controller connectivity failures.
8. Provide one install/start/stop/status interface and configure automatic startup on OFFICEPC.
9. Prove single-instance behavior, restart recovery, pause behavior, duplicate prevention, bounded backoff, idle behavior, and clean shutdown.
10. Run a fresh controller-native task from creation to `COMPLETE` with no manual worker start, branch push, PR creation, activation issuance, or `advance` call.

Do not add autonomous Gemini planning in this branch. Once the runtime remains alive unattended, the following branch should connect the existing grounded planner to periodic repository/milestone inspection and controller task creation.

## 8. Required working discipline

- Inspect current files and Git state before editing.
- Work from exact commits and full SHAs.
- Preserve unrelated dirty work and existing line endings.
- Use isolated worktrees for authored changes and reviews.
- Never use piped output as the test exit status; capture the test process status directly.
- Demonstrate that new guards are load-bearing by removing/bypassing them and observing named test failures where practical.
- Never claim live deployment, test, review, or integration from prose alone; retain concrete evidence.
- Do not rewrite historical events to make the ledger look cleaner.
- Do not fabricate controller events for work that happened outside the controller.
- Avoid broad redesigns while closing the persistent-runtime slice.

## 9. Copy-ready prompt for a fresh Claude Code session

```text
You are resuming the private Decksx/agent-swarm project as the primary systems executor.

Read this entire handoff first. Do not begin from prior conversation memory:
HANDOFF_2026-09-11_AGENT_SWARM.md

Then:
1. Locate the local repository using Git and inspect the tree without modifying it.
2. Fetch origin and verify main is exactly ac5fef6761349c73819a3e0a8d05677997f67f48. If it differs, stop and report the discrepancy.
3. Run the existing preflight and confirm Tower is on build 6c9099d404a1, schema 4, with zero live activations and officepc capacity 3. Do not redeploy if the byte-derived build matches.
4. Identify the four historical READY_INTEGRATION tasks with NULL approved_candidate_sha, verify they have no live activations, and cancel them with explicit historical-evidence reasons. Preserve their event histories.
5. Create feature/swarm-supervisor from main.
6. Implement only the persistent runtime described in handoff section 7.
7. Test locally, prove new guards are load-bearing, and preserve line endings.
8. Run one live unattended acceptance task through COMPLETE without manually starting workers or issuing/calling stage handoffs.
9. Stop before merging. Push the branch and report the exact head, test counts, live process count, task/activation counts, and acceptance ledger.

Priorities: functionality, autonomy, and speed. Do not reopen completed security work or begin autonomous planner scheduling in this branch.
```

## 10. Copy-ready prompt for a fresh ChatGPT/Codex session

```text
We are resuming review and technical-lead work on the private GitHub repository Decksx/agent-swarm.

Read the attached HANDOFF_2026-09-11_AGENT_SWARM.md completely. Treat its exact commits and independently verified statements as the starting checkpoint, but re-check any new Claude claims against the pushed code and GitHub state.

Current authoritative main is ac5fef6761349c73819a3e0a8d05677997f67f48. PR #2 is merged and its merge tree is identical to reviewed head e66fb26320c42a2317637433571f4044bff1dbb7. Tower reportedly runs the same tree as build 6c9099d404a1 with schema 4.

Claude's next branch should be feature/swarm-supervisor. Review it specifically for:
- duplicate processes after concurrent starts or supervisor restarts;
- restart storms and unbounded backoff;
- workers or progression acting while globally paused;
- idle polling causing model calls or chat chatter;
- child processes surviving supervisor shutdown;
- stale deployment versus running-code detection;
- two progression pollers creating duplicate activations;
- expiry sweep and progression interfering with each other;
- tests that use synthetic inputs unavailable through production routes;
- line-ending churn or masked test exit codes.

Do not broaden the work into new security hardening. Do not schedule Gemini planning until the persistent worker/controller loop has passed a real unattended acceptance run.
```

## 11. Useful project references

Start with the repository `README.md`, then consult:

- `SWARM_PROTOCOL_v7.md`
- `docs/PHASE0_VERIFICATION.md`
- `docs/PHASE0_CLOSEOUT.md`
- `docs/MVP3_REVIEW_CYCLE.md`
- `docs/MVP4_PLANNING_RUN.md`
- `docs/MVP5_SEMANTIC_GROUNDING.md`
- `docs/MVP7_TERMINAL_OUTCOMES.md`
- `docs/MVP8_CONTROLLER_NATIVE_INTEGRATION.md`
- `docs/PHASE1_MVP_LIMITS.md`
- `docs/EVIDENCE_BRANCHES.md`

Prefer current code and ledger state over stale prose. Where a historical document describes a limitation later fixed, retain it as history and consult subsequent resolution records.
