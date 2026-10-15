# Agent Swarm imported project context

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
