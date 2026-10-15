# Agent Swarm imported project context

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
