# Current project checkpoint — 2026-10-15

## Goal and priorities

Build a working Agent Swarm pipeline from operator chat through authoring, independent review, CI, integration and an accurately recorded result. Make progress, verdicts, refusals and blockers visible in the hub room. Reduce operator translation and wasted model calls. Reliability of the ledger is a correctness requirement: a missing object must not become a candidate rejection, a local review must not become a fictitious controller verdict, and an observed merge must not be described as an integrator action.

Historical direction deprioritizes unrelated external security work on this private LAN. Preserve the evidence boundaries needed for correct operation. Agent-to-agent chat once produced loops; the September handoff describes only admin/operator senders creating work. Do not assume unrestricted worker messages are commands.

## PR #96: merge decision pending

| Field | Verified value |
| --- | --- |
| PR | https://github.com/Decksx/agent-swarm/pull/96 |
| Scope | Issue #91; external-review slice 1; accepted design §4 |
| State | Open, not draft, not merged; API reports mergeable |
| Candidate | `4ce87b2232a74fa00de711736269c4b0a66abbc2` |
| Base | `983e32482d2ac5331cf54292341a19659c250da8` |
| Head branch | `feat/91-external-review-states` |
| CI run | https://github.com/Decksx/agent-swarm/actions/runs/36067727716 |
| CI jobs | `pytest-unit` and `pytest-bypass`: completed/success |
| Review | OfficePC Codex reports PASS for this candidate; supplied by David on October 15 |

The CI run was retrieved by candidate SHA and its two jobs checked. No tests were rerun in the handoff session. No merge, GitHub review/comment submission, deployment, supervisor restart or production mutation was performed. A PR API merge_commit_sha on an open PR is not a receipt for a completed merge.

Slice 1 adds seven external-review states, isolated transitions and narration. The generic admin route refuses `external_review_requested` until the dedicated ingress exists. External verdicts are terminal and cannot grant integration approval. Every blocked stage repairs to its own start. Existing tasks retain their ordinary paths.

The earlier automated finding was at `c5891f2e9a`; the current candidate includes the route refusal and regressions. The OfficePC review explicitly checked that refusal leaves the task and event history unchanged.

### Validation limits to preserve

The remote review reports an initial combined run of 2,184 passed, 18 failed and 30 skipped. All 18 failures were in an unchanged shell suite selecting WSL Bash on a host with no WSL distribution. With Git Bash and Python311 prepended to process PATH, the three PATH-sensitive shell suites reported 22 passed and 30 skipped, including all previous failures. The complete combined suite was not rerun after the PATH correction. Do not rewrite this as one completely green local full-suite run.

The 30 skips comprise 20 supervisor-launcher checks whose SSH stub could not shadow the host binary and 10 scheduled-task checks requiring registration/removal permission. Focused controller, external-review, narration and API suites reported 356 passed, no failures/skips, and one dependency deprecation warning. Five independent guard mutations were detected. The raw logs remain OfficePC artifacts, not verified contents of this package.

Before external assigned/running states become reachable in production, extend activation lease/deadline recovery for those states. The state table's recovery transitions alone do not establish activation recovery support.

## Accepted external-review decisions

Use `sources/design-at-983e324.md`, merged via PR #90, rather than the older archived draft.

- Verdict only: the swarm judges an external PR and a person merges it. The external chain never enters authoring, ordinary review or integration, and never writes `approved_candidate_sha`.
- A new task for each immutable head SHA. A pushed head requires a new review; the old verdict stays attached to its original SHA.
- `satisfied`, `changes_requested` and `decision_required` all end in `EXTERNAL_REVIEWED`. External `decision_required` does not mean ordinary `NEEDS_HUMAN`.
- The operator supplies the objective. Show the author's PR body as claims, not as the review contract. Optional paths constrain scope; absent paths describe the pinned changed-file set.
- Fetch once during ingest into `refs/swarm/external/<task_id>`. Verify the fetched object against GitHub's head and any operator-named SHA; compute the review range from merge-base. Review stays offline in the activation-named checkout with lazy fetching disabled.
- Keep missing/moved PR refusals distinct from git/GitHub environment defects. Repair must not record a judgment that never happened.
- Collect author families from commit trailers, agent footers and author emails, unioned with operator declarations. A verifier must belong to another family. No eligible verifier means a persistent `no_eligible_verifier` decline, announced once.
- No budget beyond explicit operator submission. Chat uses draft then confirm.
- From slice 5 onward every main merge must come through the swarm or have an exact-head `external_review_judged` event; no exemptions.

## Next implementation sequence

| Slice | Issue | Work |
| --- | --- | --- |
| 1 | #91 / PR #96 | State/ledger foundation; reviewed, pending merge decision |
| 2 | #92 | Dedicated admin ingress, ingest role/stage, Claude worker claim, fetch/pin, evidence and repair |
| 3 | #93 | `@swarm review`, draft/confirm, author-family evidence and cross-family routing |
| 4 | #94 | Map reviewer outcome, publish verdict to ledger/room/PR once, cleanup pinned ref |
| 5 | #95 | First real external review gates a merge; end relayed-verdict practice |

All five issues were open when fetched. Each slice has its own reviewable PR, exact-SHA verdict, guard mutation checks and gated deploy. Respect dependency order, and include lease/deadline recovery before activating the external review path.

The recommended immediate action is to carry the context into OfficePC, recheck #96's candidate/base/CI and production facts, and obtain or apply the operator's explicit merge/deploy instruction under the existing agreement. For an authorized merge, pin the reviewed head: `gh pr merge 96 --repo Decksx/agent-swarm --merge --match-head-commit 4ce87b2232a74fa00de711736269c4b0a66abbc2`. Read and record the actual merge SHA and post-merge checks; do not substitute GitHub's prospective merge SHA.

## Runtime layout and operational rules

These paths come from project records and the new remote review, not a fresh host inspection here.

| Component | Recorded location |
| --- | --- |
| Development | OfficePC `C:\git\agent-swarm` |
| Production | OfficePC `C:\swarm-prod\agent-swarm`, detached/pinned checkout |
| Supervisor recovery | Windows scheduled task `AgentSwarmSupervisor`, every five minutes, production `swarm_ctl.sh ensure` |
| Hub/controller | Tower `agent-hub`, LAN `http://192.168.42.50:8050` |
| Code / data / credentials | `/mnt/user/appdata/agent-swarm/app`, `data/controller.db`, `hub.env` |
| Host connection | Existing OfficePC SSH configuration to `tower.local` |
| Project registry | `repos.json`; historically `agenthub` points to the development checkout |

Keep production isolated from moving development branches. Credentials stay in existing local mechanisms; this handoff contains no new credential transfer. Worker `.state` files were message cursors; starting a fresh runtime without preserving them can replay old chat. Stopping without the supported STOPPED mechanism can let the scheduled task relaunch production.

Recorded deployment sequence: pause and establish idle → explicitly pin production checkout to the intended commit → run the supported deploy gate and build/copy/restart → restart supervisor/workers through supported controls, preserving pause → run scheduled ensure and confirm one supervisor → check running/on-disk/checkout build parity for all identities → resume only as authorized. Read the current scripts before executing the sequence. A controller build digest is not a whole-repository SHA.

PR #96 changes controller code and supervisor-loaded narrator code; deploying it needs a Tower controller build and supervisor restart. The remote review records production at `c93601b`. Its committed differences from the PR base reportedly affect README and design only, so this Git-history difference is not itself proof of a runtime-code mismatch. Current production commit, digests, pause state, active tasks and processes remain to be checked on OfficePC/Tower.

The September 22 handoff grants broad read/write, shell, git, tests, SSH and supported operational access, while reserving merging, Tower deployment and real task issuance for explicit operator go-ahead. Carry this distinction forward unless David updates it; do not repeatedly request access already granted.

## Other project context worth retaining

The current open-issue snapshot also lists #60 (swarm development provenance), #62 (repository organization), #67 (ingress usability), #69 (fetch design), #72 (Windows heartbeat/duplicate supervisor risk), #74 (external review) and #89 (superseded PR annotation). Do not assume an old handoff's entire board remains open.

Issue #58 is currently closed on GitHub, despite slice #95 and the design referring to closing it after first use. The external-review implementation is visibly incomplete. Preserve that status discrepancy; closing an issue does not prove a ledger-native verdict exists. #77 is also closed. The package includes #58's comments and current issue snapshots for context.

Historical failures explain important existing boundaries: review and integration must use the controller-issued repository; missing commit objects must be environment defects, not failed ancestry; approval comes from the pinned activation, not a worker's self-reported SHA; append corrections rather than forging old ledger instructions. A `note` can annotate terminal tasks—the earlier claim that no annotation existed was corrected in PR #96.

Repository cleanup remains separately scoped under #62. Keep evidence and historical branches; do not mix broad moves with functional slices. Prior CI-parallelization requests belong with the planned tests/dependency cleanup, respecting runtime entrypoints and deploy/build parity. Old measured module sizes and old test totals are historical, not current limits verified today.
