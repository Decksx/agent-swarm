# Agent Swarm imported project context

## #92 worker/CLI first implementation and PR #104 reconciliation — 2026-10-15

PR #104 is merged as `2a7290077c0403a479bd6d621c9fbacaa9dd5bd9`. The isolated
worker branch merged that documentation without rewriting either rollout
account. Claude's receipt records its initial supervisor 24568; the subsequent
Codex verification/restart above records supervisor 9372. These are successive
operations, not simultaneous supervisor instances. Production remains at
`d2493667391244ca10226894b171a7590d5e1708`; no new rollout was performed here.

The worker branch now adds `claude_ingest.py`: registered repository binding,
bounded monotonic commands with lease checkpoints, GitHub identity/PR metadata,
head plus exact-base fetch, SHA/range verification, raw authorship provenance,
bounded complete evidence, create-only final pin CAS and task-scoped stale-ref
cleanup. It changes no working branch and calls no model. A late lost lease
can leave an orphan pin but cannot accept/register evidence. Oversized transport
diagnostics remain environment defects rather than judgments on the PR.

The admin `external-review` subcommand sends only the agreed request shape to
`POST /controller/external-reviews`, preserves operator text and optional-field
omission, and never falls back to ordinary task creation. Tests use local Git
remotes and a stub forge; no network/model call or controller task is needed.
The shared test control fixture now isolates usage paths and memory per test,
addressing the held-mutex/fake-sleep harness failure seen during rollout.

Validation on the implementation candidate: 172 focused checks passed, covering
the engine, CLI, view budgets, worker loop, claims, rate guard and narration.
All eleven in-memory mutations were caught: both SHA comparisons, create-only
CAS, complete evidence bound, lease-loss refusal, live-scratch protection,
base-object fetch, deadline enforcement, dedicated CLI route, optional at_sha
and exact objective preservation. Python compilation and whitespace checks
passed (preserving the tracked CLI's CRLF line endings). Exact-head CI and
Claude's independent review are still required before integrating this slice.

Controller activation/result glue, worker ingest dispatch and model-free claim
changes are deliberately not enabled yet. Claude must confirm the exact
activation payload, dedicated result API/outcomes and prior-activation liveness
lookup before those are connected. The core and CLI are reviewable independent
work, not a claim that #92 is complete or deployed. Claude leads controller
implementation and end-to-end checks; Codex owns this worker/admin branch.

## PR #102 merged/deployed; standing operator permission — 2026-10-15

David granted explicit standing permission for this project's commits, pushes,
merges and deployments. Do not ask for that permission again for routine work
within the project. Keep review/CI evidence exact, preserve ledger meaning and
use supported runtime controls; work still needs controller-issued activations.

PR #102 merged with a pinned head check as
`d2493667391244ca10226894b171a7590d5e1708`, from approved candidate
`9b7282a39fc3ed0b5698d4f07d905f90d1be8e73`. Claude's final no-findings review
is comment 6203010215. Candidate CI `38811541122` and merged-main CI
`38814198397` both passed all four checks and 2,317 tests without skips.
The reviewed source and merge have equal trees.

The complete local deployment gate passed 2,307 tests with ten local scheduler
permission skips after isolating test interpreters' usage directories. The
initial shared-directory run failed a bounded-loop harness test; a held-lock
probe reproduced it and release passed. Neither source nor selection changed
for the successful rerun. See the full receipt for this qualification.

Production is clean and running at the merge, with one supervisor (9372) and
ChatGPT/Gemini/Claude workers (2152/7912/41944). Heartbeat and hidden ensure
passed; unpaused state and cursors were preserved (1490 each; narrator 525).
All three identities passed parity at unchanged controller build
`cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`, schema 6;
no Tower code or restart was needed. The production checkout had independently
advanced to the same target while validation ran; this sequence verified it
and performed a supported stop/restart rather than claiming that checkout.

The updated Claude worker is deployed with CLAUDE_RATE_GUARD_DIR naming its
existing production state directory. One real planner smoke returned
CLAUDE_SHARED_GUARD_OK, reported claude-opus-5-5, and charged 6.219 seconds to
the shared usage file. Shared Claude planning is now available; no controller
task was created. See `../DEPLOYMENT_PR102_2026-10-15.md` for the full receipt.

Next: Claude leads #92 controller work; Codex's worker/CLI preparation is in
`C:\git\agent-swarm-worktrees\external-ingest-worker`, branch
`feat/92-external-ingest-worker`, based on the deployed merge. The new
`docs/design/92-worker-implementation-plan.md` scopes that half and its tests.
No #92 runtime implementation or external-ingress configuration is deployed.
The following section preserves Claude's earlier receipt from PR #104. Its
process IDs predate the later Codex verification receipt; its no-planner-call
statement describes that earlier rollout only.

## PR #102 merged and worker rollout — 2026-10-15

David authorized commit, merge and deployment. Claude's final exact-head check
of `9b7282a39fc3ed0b5698d4f07d905f90d1be8e73` found no remaining issues
(https://github.com/Decksx/agent-swarm/pull/102#issuecomment-6203010215).
PR #102 merged, pinned to that head, as
`d2493667391244ca10226894b171a7590d5e1708`. All four checks passed on the
merge commit in CI run `38814198397`.

PR #102 changed no controller or hub files, so Tower was not rebuilt or
restarted. The controller build stays
`cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`, schema 6.
The controller had no live activations at rollout (120 DONE, 6 EXPIRED).

OfficePC worker rollout, using the supported controls only:

- `swarm_ctl.sh pause`, then `stop`: supervisor 38900 and its three workers
  stopped, and no swarm processes remained.
- `C:\swarm-prod\agent-swarm` moved from `db0bd5b` to detached `d249366`.
  `git diff --quiet HEAD` is clean, and the changed worker and planner files
  match their git objects.
- Started through the scheduled task's own hidden launcher (`run_hidden.pyw` →
  `swarm_ctl.sh start`). Start-up preflight passed, then `resume`.
- Result: supervisor PID 24568 with a fresh heartbeat; ChatGPT 39064, Gemini
  37416 and Claude 31928, all its children and all running from production.
  The Claude worker log shows "resuming from message id 1490".
- Worker cursors stayed at 1490 for all three identities; the narrator cursor
  stayed at 525.
- `worker_ctl.sh preflight claudecode`: checkout, running and on-disk builds
  all `cc1d4f0214fe`. `ensure` reported a live supervisor. A manual run of the
  scheduled `AgentSwarmSupervisor` task returned 0 and left one supervisor.

Shared Claude usage accounting:

- The user-level `CLAUDE_RATE_GUARD_DIR` resolves to `C:\swarm-prod\agent-swarm`,
  the worker's existing state directory, so its usage history carries over.
  There was no active hold-off file.
- No "shared usage unavailable" warning was logged after start.
- The updated worker is now deployed and verified, so `--planner claude` may be
  used.
- No planner call, real controller task, or Tower change was made in this
  rollout.

Next: Claude starts the controller side of #92 under
`docs/design/92-ingest-contract.md`; Codex owns the ingest worker and admin CLI.

## PR #102 worker read-failure recovery and final contract conditions — 2026-10-15

Claude reviewed `0fbdc67869a121b7ba5181e8da9709e4b452a396` at
https://github.com/Decksx/agent-swarm/pull/102#issuecomment-6202675380.
That exact head passed all four checks in CI `38808564835`: 1,982 core,
318 hub and eight bypass tests (2,308 passed, no failures/skips), in 3m12s.
The Windows read-lock race and deploy-order findings were accepted as resolved.
Claude identified a worker crash if the new usage mutex cannot be acquired or
opened; the planner already handles that error.

The worker now uses one guarded refresh at startup and on every unpaused poll.
OSError/AlreadyRunning preserves in-memory usage, logs once per failure streak,
and pauses model claims while allowing model-free controller stages. Directory
mode takes no work during this hold. A successful later read merges disk and
memory and clears the failure flag. 159 focused worker-loop, rate-guard,
planner, host-setting and prompt tests passed on Windows. Coverage includes
startup/poll failures for both busy and unwritable locks in both queue modes,
real held-mutex recovery, preserved pending usage and automatic retry. Five
new mutations were caught, together with the previous thirteen. Fresh CI and
Claude's exact-head review remain required for this follow-up candidate.

EXTERNAL_REVIEW_REPOS is approved subject to Claude's conditions, now in the
#92 contract: both maps required, existing REPO_SLUG validation, bad settings
disable only external review without blocking controller startup, case-insensitive
slug/URL matching, fixable slug mismatches, and deployment presence reporting
without printing values. SERIAL enforcement is explicitly unimplemented; the
acceptance wording now says ingest does not count toward any execution lane.
Fetch the exact reported baseRefOid as well as the head, including for merged
PRs, keeping both objects through range computation. No #92 runtime code,
merge, deployment, restart, paid planner call or real task issuance occurred.
Claude planning remains off until the updated worker is deployed and verified.

## PR #102 Windows read locking and accepted #92 amendments — 2026-10-15

Claude's re-review of `d9762b7b274be5093ceec4c0d6b496e836c27d92` is at
https://github.com/Decksx/agent-swarm/pull/102#issuecomment-6201870664.
All six earlier findings were accepted as fixed. That exact candidate passed
all four CI checks in run `38802984535`: 1,979 core, 318 hub and eight bypass
tests (2,305 passed, no failures/skips), in 3m50s. This evidence belongs to
that commit, not the subsequent read-lock changes below.

The new source takes the usage writer's OS mutex for public reads, holding it
until the read handle closes. The writer uses a private already-locked reader
to avoid recursive acquisition. Planner preflight converts mutex contention
into a clear refusal before any call. A real cross-process open-file test
checks read/write exclusion and persistence after the reader closes. All 126
focused planner/host-setting/rate-guard/prompt tests passed on Windows. Three
new in-memory mutations (unlocked read, different read mutex and unhandled
preflight lock contention) were caught, as were the ten previous mutations.
Fresh exact-head CI and Claude's renewed review are required after this change.

Deployment order is explicit in README and the leadership design: do not use
Claude planning until the updated worker has been deployed/restarted and its
running source and effective guard directory checked. Keep the existing state
directory (`C:\swarm-prod\agent-swarm` on OfficePC), hold and usage files. The
old worker can erase planner records; the documentation change does not fix
the already-running old process. No deployment/restart or paid planner call
was performed in this follow-up. Token-only CLI hosts need a stored login;
inherited OAuth/access-token overrides remain intentionally excluded.

David explicitly chose all PR states (open, draft, closed, merged) and normal
host-slot consumption outside the SERIAL engineering limit. Historical reviews
record their actual review time without changing PR state or implying approval
preceded an old merge. The #92 contract now includes Claude's amendments:
OPERATOR boundary tests, generic full-base validation, branch_only proof_mode,
controller-owned result checks, deadline-derived timeouts, task-scoped scratch
cleanup and the exact admin request. The accepted #74 design lists the new
assigned/running states and revised pin procedure. A proposed trusted controller
EXTERNAL_REVIEW_REPOS map closes the missing-slug source; Claude still needs
to check that configuration detail. No #92 runtime implementation is included.

## PR #102 review follow-up and #92 contract answers — 2026-10-15

Claude's independent engineering review of `055471f` is recorded at
https://github.com/Decksx/agent-swarm/pull/102#issuecomment-6201292059.
It requests fixes before leaving draft; it is not a controller-ledger verdict.

The follow-up source removes inherited provider API keys/token overrides from
CLI child environments, adds explicit CODEX_CLI / CLAUDE_CLI binary settings,
and makes Claude planning honor the live worker's shared usage directory and
hold. Failed and timed-out calls record duration too. The worker refreshes the
shared file before checking its budget; completed calls merge under a kernel
lock and persist with atomic replacement so stale process windows cannot erase
each other. The elapsed-time proxy is retained, not presented as a provider
quota measurement. Shared accounting requires deploying/restarting the updated
Claude worker; no such deployment has occurred.
Merging legacy usage windows also preserves repeated identical call records;
the timestamp/duration pair is not treated as a unique record ID.

On OfficePC, non-secret Windows user settings now name the installed Codex
executable in CODEX_CLI and the existing production state directory in
CLAUDE_RATE_GUARD_DIR. The resolver sees fresh user settings even from an app
with older inherited environment. A check with Codex removed from PATH still
resolved the configured executable; cached login reports ChatGPT with API-key
overrides removed. Existing keys were not changed or printed.

Saved replies now record null planner/provider values; reported-model metadata
is explicitly all models the CLI reports using, including auxiliaries. The
leadership design's deploy note identifies the Gemini system-prompt change and
the Claude accounting change. Tests include mixed success/error provider
responses, missing/explicit executable paths, environment filtering, shared
holds and usage, duration on failure/timeout and accounting-write refusal.
The first focused run passed 97 checks; broader regressions and exact-head CI
are required for the follow-up candidate, followed by Claude's renewed review.

`docs/design/92-ingest-contract.md` records Codex's five technical answers for
Claude to check before #92 implementation: FAILED for refusal; explicit assigned
and running ingest states with recovery; an empty external-only base sentinel
kept on the immutable request version and the real range in the registered event;
bounded structured event evidence; and create-only final pins with SHA compare-
and-swap, distinct from activation/lease fencing. Claude leads controller work;
Codex implements the model-free worker/admin CLI against the agreed contract.
No #92 code, task issuance, merge or runtime rollout is part of this follow-up.

## Parallel CI merged; leadership branch refreshed — 2026-10-15

Claude implemented CI parallelization in PR #103. Codex independently reviewed
`2332071beb6acd4fad75018e5997d9445994d783` with no blocking findings: focused
local checks passed (15 passed, ten scheduler-permission skips), all 16 aggregate
status combinations behaved correctly, and six workflow mutations were caught.
The final clarification commit `602ed8ec30eeb9e31c7ee48ab8dc2f1cdddb812d` changes
comments, docstrings and an assertion diagnostic only. Codex subsequently
verified equal parsed workflow semantics and equal test logic after excluding
documentation and assertion messages; the original review is not relabelled as
a fresh full review of that later commit.

PR #103 merged as `fa02750f872f184ae7c8e7244ec8805ec56c5ceb`. Candidate CI run
`38796469904` passed all four checks in 3m55s with the pip cache restored.
Merged-main run `38797078339` passed all four in 4m26s: 1,926 core, 318 hub and
eight bypass tests, 2,252 total with no failures or skips. The first parallel run
`38793695024` took 4m38s versus 15m49s for baseline `38783027648`. These are
observed runs, not a guarantee of future runner duration.

The workflow now runs core and hub suites concurrently with pytest-xdist and
uses a pip cache. `pytest-unit` remains the required aggregate, always reports,
and demands success from both suites; `pytest-bypass` remains required. The
scheduled-task fixture isolates both tests and collection probes per worker.
No tests were removed or moved to a lighter tier. A skipped check is tolerated
while waiting for CI but rejected by the integrator's final evidence validation.

Codex merged this main into PR #102's development branch at
`12a19162cf881e4b6bc87f9efbbdfb28fc36e3cb`, without rebasing or altering Claude's
work. The merge was clean; 33 workflow, planner-transport and model-call checks
passed locally. This context update accompanies the refreshed candidate; fresh
CI and Claude's exact-head engineering review remain the next gates. PR #102
stays draft. Production remains at the Argon release below; no worker restart,
Tower deployment, real task issuance or additional merge was performed here.

Follow-up: make `test_worker_ctl_root.py` select Git Bash explicitly on OfficePC
instead of accepting the WSL launcher first on PATH. Keep that separate from
the leadership change. Claude's CI worktree was reported removed after merge;
the remote CI branch need not be deleted to use the merged workflow.

## Shared engineering leadership — 2026-10-15

David confirmed that both Codex and Claude should lead interactive project work
and serve as automated planners. The development implementation now defaults
`plan_run.py` to Codex and supports `--planner claude` / `--planner gemini` and
`SWARM_PLANNER`. Existing snapshot, context/search budget, validation and DRAFT
creation logic remains shared. The installed CLIs run prompt-only in temporary
directories; controller credentials are excluded, execution/integrations are
disabled, and provider failure does not select another lead.

`AGENTS.md` and the new `CLAUDE.md` establish the interactive co-lead workflow.
See `docs/design/engineering-leadership.md` for the interfaces and Claude's
immediate assignment: independently review this implementation, then propose
and lead the next #92 ingress slice. No review was sent on David's behalf and
no controller-ledger verdict is claimed. This source is pending CI/review and
is not yet the production checkout.

Validation: 220 targeted tests passed, including planner transports, the shared
planning pipeline and the worker model-call path. Three independent in-memory
mutations were caught: leaked controller credentials, enabled shell execution,
and acceptance of an incomplete Codex turn. Real Codex and Claude CLI adapters
passed connectivity checks and generated grounded proposals for a disposable
repository through the full planning pipeline (two Codex calls including search;
one Claude call). The fixture repository stayed unchanged and no controller
task was created. Claude reported `claude-opus-5-5`; Codex did not report a model
version, so its evidence honestly records `cli-default` with no reported model.

## Gemini Argon configuration — 2026-10-15

David requested the newer Argon model for Gemini and asked whether hive
coordination still works. The active worker and operator planner now default to
`gemini-4-argon`, with the existing `GEMINI_MODEL` and `GEMINI_PLANNER_MODEL`
launch-environment overrides (and planner `--model`) retained. Google's
[model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)
confirms the identifier. The configured API credential successfully retrieved
this model and completed a small real generation returning `ARGON_OK`, reporting
model version `gemini-4-argon`, through the installed `google-genai` 2.22.0 SDK.
No SDK upgrade or automatic fallback was introduced.

Authenticated hive reads and controller status both returned HTTP 200; Gemini
and Claude workers were running. Chat remains narration: ordinary mentions
cannot call models, and work still requires controller-issued activations.
The retired `hub/gemini_lead.py` is not the active worker.

PR #101 merged at `db0bd5b64af89bef2ad2d86b53950d96527b1c96`; its candidate
`9b02c97da29b7cc42ed9b581435ba33a9992b54a` passed all 2,245 CI tests in run
`38783027648`, plus 307 targeted local tests. Production is pinned to that merge.
Supported pause/stop and hidden start/resume controls restarted the workers;
the Gemini startup log confirms `gemini-4-argon`. Supervisor PID 42044 and
ChatGPT/Gemini/Claude PIDs 41380/17344/26120 were healthy and unpaused, with a
fresh heartbeat. All worker cursors stayed at 1490 and narrator cursor at 525.
Gemini preflight passed at unchanged controller build
`cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`.
Tower code was unchanged; no controller restart or real task issuance occurred.

## Previous controller deployment checkpoint — 2026-10-15

David authorized commit, merge and deployment. PRs #96, #97, #98 and #99 are
merged, and production is pinned to runtime source commit
`755aa885b3d4bf8b95cd58e89341c83129eb9b70`. The full local deploy gate passed
2,235 tests with ten scheduler-permission skips and no failures; combined
release CI passed all 2,245 tests. All three worker identities passed parity at
controller build `cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`.
The swarm is running and unpaused with one supervisor and one of each worker;
scheduled hidden ensure returned 0, cursors were preserved, and no real task
was issued. See `docs/context/DEPLOYMENT_2026-10-15.md` for receipts and backups.

Issue #92 is the next implementation step; ingress is not yet enabled. The
earlier ingestion/preparation records below are historical and their statements
about pending merges or deployment are superseded by this checkpoint.

## Publication correction

GitHub push protection found a Google Cloud credential in the raw historical
chat, despite the supplied handoff's statement that credentials were absent.
The published archive redacts the affected command and regenerates its checksum
manifest; `docs/context/ARCHIVE_REDACTION.md` describes the correction. The original
attachment remains local. The original import checks below describe that earlier
pass and do not imply the published copy is byte-identical to the raw attachment.

## Work after setup: 2026-10-15

Live PR96 and production checks now match the imported checkpoint. All three
production preflights passed at controller build
`d650c830de97e5cebe25704bf1e09f0ce6814c1570649e5dc4bd53ad4779476b`.
The runtime was unpaused and idle, with one supervisor and one of each worker.
No production controls or task state were changed.

The missing external-review expiry recovery was reproduced and fixed in isolated
development worktree `C:\git\agent-swarm-worktrees\external-review-recovery`.
Draft PR #97: https://github.com/Decksx/agent-swarm/pull/97, head
`84edbea40e78035ecad56bee3d6c4d931b405031`, stacked on PR96's branch.
232 targeted tests passed with no failures/skips and two warnings; three
independent in-memory mutations were detected. Full ingest #92 is not complete;
the draft does not enable ingress, and has no automatic CI at its feature-branch
base. No independent review verdict has been claimed for the new code.

See `docs/context/NEXT_STEPS.md` for exact evidence, the proposed #92
implementation, and the concrete PR96 merge/deploy sequence. Operator go-ahead
for merging/deploying remains pending. Older sections below describe the
earlier ingestion/setup pass and retain their original evidence limits.

## Git project setup after ingestion

The imported context now lives inside the existing `C:\git\agent-swarm` Git
repository, with root `AGENTS.md` and `docs/context/README.md` entry points.
The dedicated local branch is `docs/codex-project-context`, created from the
reviewed PR96 candidate. The reviewed feature branch was not advanced. Existing
uncommitted edits were preserved and are not part of the context commit.

The sections below record the earlier ingestion pass; their statements about
what was changed refer to that pass. This follow-up adds project documentation
and a local Git commit only. GitHub and production state have not been rechecked.
Codex sidebar registration was completed on 2026-10-15 with David's explicit
permission to automate project setup. The app lists **Agent Swarm**, project ID
`466ce426-aff5-4a45-a7de-6a20bd5c395a`, at `C:\git\agent-swarm` and recognizes it
as a Git repository. This import conversation was moved into the project.

Imported on 2026-10-15 from David's attached
`agent-swarm-codex-transfer-2026-10-15.zip`.

## Import result

The full outer ZIP was extracted into `agent-swarm-codex-transfer-2026-10-15/`.
All 50 entries listed in its `SHA256SUMS.txt` passed SHA-256 verification.
Original files, historical duplicates, and the two nested review ZIPs were kept
unchanged. The archive contains 51 files including the checksum manifest.

Read for this import: START_HERE, CURRENT_STATE, suggested agent additions,
PR96 remote review, accepted design, README snapshot, issues #91-95, source
inventory, September 22 handoff, and the existing development session handoffs.
The remaining history is available for targeted consultation; it has not all
been read line by line. Integrity verification is not verification of the claims
inside those documents.

This imports the supplied project knowledge into this workspace. The transfer
does not contain the full ChatGPT conversation history, the 19 omitted images,
credentials, controller database, worker state, or raw PR96 test logs.

## Read next

Paths below are relative to `agent-swarm-codex-transfer-2026-10-15/`:

| Source | Purpose |
| --- | --- |
| `CURRENT_STATE.md` | Detailed checkpoint, operating agreements, dependencies, evidence limits |
| `reviews/PR96-remote-review-2026-10-15.md` | Supplied local review and exact test qualifications |
| `sources/design-at-983e324.md` | Accepted external-review design, superseding the archived draft |
| `sources/issue-92.json` | Next implementation slice: dedicated ingress and fetch/pin |
| `sources/pr96-snapshot.json`, `sources/ci-at-4ce87b2.json` | Historical GitHub snapshot, not a live recheck |
| `archive/Group AI Chat/` | Prior protocols, handoffs, discussion, review packets |

Current code, accepted design, exact-commit evidence, and live controller facts
establish behavior. Retain discrepancies rather than silently resolving them in
favor of an old document. Even the recent README snapshot contains old MVP status.

## Project purpose and design

Build a working operator-chat -> author -> independent review -> CI -> integration
pipeline, with accurate ledger evidence and visible progress and blockers in the
hub room. Avoid worker-to-worker chat loops and unnecessary model calls.

The current milestone is external PR review, issue #74, split across #91-95:

1. #91 / PR #96: separate external-review states, ledger events, narration.
2. #92: dedicated admin ingress, ingest role/stage, Claude worker claim,
   fetch/pin, evidence, repair.
3. #93: `@swarm review`, draft/confirm, author-family evidence, independent routing.
4. #94: verdict in ledger/room/PR, idempotent publication, pinned-ref cleanup.
5. #95: first real use; require a swarm verdict for subsequent main merges.

External review produces a verdict only; it cannot enter integration or write
`approved_candidate_sha`. Each head SHA gets a new task. Operator objectives are
the review contract; author PR text is labelled as claims. Ingest fetches once
and pins `refs/swarm/external/<task_id>`; review is offline in the activation's
named checkout. Missing/moved PR refusals differ from environment defects. Review
must use another model family. Add activation lease/deadline recovery before
external assigned/running states become reachable.

## Supplied PR96 evidence

- Candidate: `4ce87b2232a74fa00de711736269c4b0a66abbc2`.
- Base: `983e32482d2ac5331cf54292341a19659c250da8`.
- Package reports open, mergeable, and both CI jobs successful. Not rechecked live.
- Supplied OfficePC review reports PASS for slice 1. This is local review evidence,
  not a submitted GitHub approval or a controller-ledger verdict.
- Initial combined tests: 2,184 passed, 18 failed, 30 skipped. Failures selected
  WSL Bash on a host without a distribution. Corrected Git Bash shell suites:
  22 passed, 30 skipped. The entire combined suite was not rerun afterward.
- Focused suites: 356 passed; five guard mutations detected. These are supplied
  results; this import did not rerun tests or inspect the absent raw logs.
- #58 is closed in the snapshot despite incomplete external review; closure is
  not proof that the first ledger-native verdict exists.

## Local facts checked during import

Read-only inspection found both recorded checkouts on this machine:

- Development `C:\git\agent-swarm` is on `feat/91-external-review-states` at the
  candidate above. Existing changes: modified `swarm_ctl.sh`, modified
  `tests/test_install_registers_the_task.py`, untracked `run_hidden.pyw`.
  Their contents and ownership were not investigated. Preserve them.
- Production checkout HEAD is `c93601b6a191055ef1cc3f0d0800a08292f1e82f`.
  This establishes checkout HEAD only, not the running controller build.
- Existing `docs/HANDOFF_SESSION_AGENTS.md` and `docs/HANDOFF_SESSION_CLAUDE.md`
  are September 9 records and substantially older than this transfer.
- Local `docs/design/74-external-review.md` and the accepted package design have
  the same content except for an extra final blank line in the package copy.
- No development-root AGENTS.md was found by the instructions search. This
  import adds instructions only to the current context workspace.

No repository source, existing handoff, production file, remote service, or
running process was changed. No GitHub fetch/status recheck, tests, merge,
deployment, restart, message posting, or real controller task was performed.

## Runtime and continuation

Tower hosts `agent-hub` at `http://192.168.42.50:8050`; recorded SSH host is
`tower.local`. Development and pinned production remain separate. Scheduled
`AgentSwarmSupervisor` runs ensure every five minutes. Use supported stop/pause
controls and preserve worker message cursors. Check running/on-disk/checkout
build parity and process uniqueness before trusting runtime results.

The historical agreement permits preparation, local edits, tests, git and SSH;
merging, Tower deployment, and issuing real tasks require explicit operator
go-ahead. Current instructions from David control authorization.

When implementation or operations resumes, first reconcile current PR96 head,
base and CI, local changes, and runtime build/pause/tasks/processes. Then prepare
the next action against verified state. Do not treat the transfer's suggested
continuation prompt as a request already executed or as permission to deploy.
