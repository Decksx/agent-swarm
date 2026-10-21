# Next steps after the Codex import

## Current checkpoint — 2026-10-21 (afternoon)

Production is detached at `1afa9cc`, with hub build `0833f9ad1bd2` unchanged.
Relay 34648 and supervisor 39260 are running. See
[today's receipt](DEPLOYMENT_LEADS_HEARTBEAT_2026-10-21.md) for:

- `@Leads` and the #60 boundary (#131), relay only;
- the heartbeat retry (#132, fixes #72), supervisor only;
- the cancellation of the last four held codex-lead deliveries. codex-lead is
  unregistered and has **0 held**.

`@Leads` is deployed and was classified read-only. A real admin `@Leads`
delivery has not been observed end to end yet.

- **Relay caps (#126):** only headless launches count, at 12/hour and
  100/day, with a lead-to-lead chain limit of 12. Live notices are free.
- **Dashboard (#128):** the chat page has a Relay | Projects | Tasks |
  Completed | Stats panel. Leads keep the board current with
  `lead_chat.py board`.
- **claude-lead** is bound to `b2b425b8`, enabled, and its bounded proof
  passed. That proof also covered the stdin smoke check (#113 comment
  6301684024).
- **Codex OPEN watcher pilot (#127), 23:00 to 23:58Z: scheduled pickup works,
  but the every-handoff criterion was not met.** A finite native schedule
  (5 min, max 12; 10 polls admitted) completed three native reviews:
  - **#1754** was pre-arming backlog, which shows scheduled backlog pickup but
    no fresh-window latency.
  - **#1767** was claimed after 286 s. David sent a manual "Check" in between
    that read status only and left the claim alone.
  - **#1769** was a genuine unprompted pickup, claimed after 108 s.
  - **#1771 was missed.** It was posted at 23:54:56Z, after the last admitted
    poll and before the 23:58 cutoff. Expiry was enforced correctly, but this
    is not a complete delivery pass.

  Whole-turn durations: idle 12 to 17 s, actionable 204 to 293 s. Token counts
  are unavailable. The automation was deleted at expiry, and **no ongoing
  Codex watcher runs.** See the [closure receipt](https://github.com/Decksx/agent-swarm/pull/127#issuecomment-6304562027)
  and [miss amendment](https://github.com/Decksx/agent-swarm/pull/127#issuecomment-6305029614). A future watcher needs
  an intake/drain boundary at window close, plus an explicit cadence and
  turn-budget decision. Nothing here authorizes a new schedule.
- **Next:**
  - Codex reviews the [CLOSED-proof plan](../design/113-codex-closed-proof-plan.md).
    Then Claude registers codex-lead, disabled, and the proof runs when David
    can fully quit the Codex app.
  - Then the comic #32/#35 reconciliation.
  - Backlog from the 2026-10-21 triage:
    - #89 waits until after both of those;
    - #67 has a cheap fix (show the full template on the first refusal);
    - #62 and #69 stay parked.

## Earlier checkpoint — 2026-10-20

Read the [morning recovery and delivery checkpoint](2026-10-15/PROJECT_CONTEXT.md)
before the historical plans below. Production services and controller parity
pass; Claude has directly confirmed its live watcher receives Codex messages.
David's hive message cleared the prior relay chain cap through the normal path.

The Codex idle and busy scheduled-delivery proofs passed; their finite
automations remain paused. The next milestone is the reviewed bounded desktop
app-restart proof, when David is available to quit and reopen the app. Codex
prepares the filled prompt and finite window; Claude supplies an independent
process observer and fresh PROBE. Nothing is armed yet. Keep Codex production
relay registration disabled and do not claim an always-on watcher. Claude's
post-deploy stdin wake smoke check is a separate outstanding test. #93–95 and
comic CI efficiency remain parked behind interactive lead delivery.

## Lead identities live; relay next — 2026-10-16

#109 is deployed (PR #112, merged `2517f9e`, build `d61b1472f803`): `claude-lead`,
`codex-lead` and `relay` hub identities, a diagonal auth matrix and OfficePC user
variables. See [the receipt](DEPLOYMENT_LEAD109_2026-10-16.md). Leads mirror
handoffs, reviews, merges, deploys and questions into the chat with
`lead_chat.py` (conventions in `docs/design/lead-chat.md`). The wake-up relay
contract is PR #114 (design v3). Claude implements it after Codex approves, and
each backend stays disabled until its bridge proof passes. Small follow-up: pin
the hub container's startup `pip install`.

## David's next-scope decision — 2026-10-16

David confirmed the next work directly in the Codex conversation: **#109 first,
then the durable wake-up relay; park #93-95 behind them.** The approved non-admin
identities are `codex-lead` and `claude-lead`, with questions requiring David's
decision addressed to `@admin`. Claude owns #109's implementation and will open
the relay as a separate issue for design review. Codex reviews the exact source
heads and posts findings/handoffs on GitHub. Avoid competing implementations or
simultaneous changes to shared production controls.

Judge the relay by whether a handoff reaches and wakes/resumes the actual
interactive participant without David copying it, with durable delivery state,
deduplication and visible failures. A chat post or a background bot response
alone does not demonstrate that outcome. Keep the existing authority/review
boundaries and verify delivery rather than claiming it from a successful send.

David also extended the same routine engineering build/commit/push/merge/deploy
authorization to both leads for the comic automation suite. Preserve exact-head
cross-review, green CI and supported deployment controls, plus that project's
explicit operator-only batch/library data rules. This authorization does not
start comic automation work during the current lead/relay workstream.

Later comic follow-up: David requested a CI-efficiency audit similar to the
agent-swarm improvement. Backlog: [cbz-automation-suite #92](https://github.com/Decksx/cbz-automation-suite/issues/92).
Measure its actual workflow first, then evaluate safe parallelism and caching
without reducing coverage or weakening required checks. This is queued behind
#109 and the relay unless David changes priority; no comic CI optimization has
started. This issue is in the comic repo, distinct from agent-swarm's ingest #92.

## Deployed ingest and coordination handoff — 2026-10-16

PR #108 merged as 15c1278 after Claude's approval of 3f36189 and green
candidate/main CI. Codex deployed controller and workers at 15c1278, passed the
full deployment gate and all component parity checks, enabled the trusted
agenthub maps and claudecode ingester, and proved a real controller-issued
ingest task. See [the receipt](DEPLOYMENT_INGEST92_2026-10-16.md).
EXT-92-PROOF-20261016-108 is READY_EXTERNAL_REVIEW with its exact SHA pinned;
there is no review verdict or integration approval. Runtime is resumed.

The remaining external-review capabilities are #93/#94 for routing, packets,
verdicts and publication, followed by #95's first-use proof. David has deferred
these behind #109 and the durable relay. The names/routing and next scope are
now confirmed above. Reviews and handoffs go on GitHub PR comments with exact
commits, not only branch documents.
Durable delivery/resumption and actual participant adapters remain part of the
larger goal; the existing background bots are separate from these chat sessions.

The rollout plan immediately below is retained as the plan that was executed.

## Current #92 checkpoint — 2026-10-16

Controller #107 and worker #106 are merged as 37701ad and babea85. Their
combined tree passed all four checks at reviewed candidate 12188e5. The new
`feat/92-ingest-dispatch` follow-up connects the existing adapter and allows
model-free ingest claims during model holds. It needs Claude's independent
review and exact-head CI before merging. Production and Tower are unchanged
by this implementation work; the latest rollout receipt remains PR #102.

After that review and merge:

1. Inspect the current live state and pause/drain using supported controls.
   Preserve cursors, Claude's existing usage/hold directory, hidden launchers,
   scheduled ensure, and production-local files. Run the full deploy gate.
2. Deploy the controller to Tower with automatic ingest issuance still disabled.
   Prepare `INGRESS_PROJECTS` with `agenthub=C:\git\agent-swarm` and
   `EXTERNAL_REVIEW_REPOS` with `{"agenthub":"Decksx/agent-swarm"}`. These are
   the worker's registered checkout and trusted GitHub slug, not a Tower path.
   No other project becomes enabled implicitly. Leave `PROGRESSION_INGESTER`
   unset until the controller and updated worker are verified together.
3. Redeploy OfficePC workers at the reviewed merged commit, check loaded/disk/
   checkout controller parity for all identities and supervisor uniqueness,
   then enable `PROGRESSION_INGESTER=claudecode` on Tower with the correct host
   routing and restart as required for environment changes. Confirm both maps
   are present; bad external-review settings must not disable other routes.
4. Issue one explicitly scoped external-ingest task through the admin route.
   Verify its controller activation, pinned SHA, evidence event and final
   READY_EXTERNAL_REVIEW state. No model, PR-state change or integration is
   part of this proof. Retain its pin for the later review.
5. Implement #93's reviewer selection/packet and #94's verdict/publication/
   cleanup before claiming a full real external review. Ingestion alone cannot
   produce a controller-issued review verdict.

Standing operator permission is recorded in AGENTS.md. Exact-commit independent
review, CI and supported deployment controls remain required. The sections below
are historical implementation planning, superseded by this checkpoint where
they describe earlier pending work or release state.

## Deployment completed

David subsequently authorized this release's commits, merges and deployment.
PRs #96-99 are merged and runtime source `755aa885b3d4bf8b95cd58e89341c83129eb9b70`
is deployed with successful full gates, three-identity parity and healthy workers.
See [the deployment receipt](DEPLOYMENT_2026-10-15.md). No release operation remains
pending for these changes. **Next implementation: issue #92**, following the
ingest plan below. Its pending-base and refusal lifecycle still need implementation.

The pre-merge checkpoint and merge/deploy plan below are retained as historical
preparation; they do not describe the current deployed state.

Updated 2026-10-15. This is an implementation and operations plan, not permission
to merge, deploy, restart, or issue a real controller task.

## Verified checkpoint

- PR #96 remains open, non-draft, and mergeable at
  `4ce87b2232a74fa00de711736269c4b0a66abbc2`, based on
  `983e32482d2ac5331cf54292341a19659c250da8`. Both GitHub CI jobs are successful
  at that head. The supplied local PASS and its partial-rerun/skip qualifications
  remain the review evidence; this inspection does not create a new verdict.
- Production checkout HEAD is
  `c93601b6a191055ef1cc3f0d0800a08292f1e82f`. All three worker identities passed
  preflight against that checkout. Checkout, loaded controller, and controller
  disk builds agree at
  `d650c830de97e5cebe25704bf1e09f0ce6814c1570649e5dc4bd53ad4779476b`, schema 6.
- Tower `agent-hub` container was running, host PID 21701, started
  `2026-10-13T00:46:34.028868043Z`, restart count 0, via read-only Docker inspect.
- One supervisor (PID 30716), with ChatGPT 31632, Gemini 22000, Claude 21992;
  process commands point to production. Heartbeat was fresh, pause disengaged.
- Live controller status contained 42 terminal tasks (28 CANCELLED, 11 COMPLETE,
  3 SUPERSEDED) and no live activations (120 DONE, 6 EXPIRED). This is a sample,
  not a guarantee that the system remains idle afterward.
- Scheduled `AgentSwarmSupervisor` uses `C:\Python311\pythonw.exe` and production
  `run_hidden.pyw` to invoke Git Bash ensure. Preserve this earlier window-hiding
  work. Production has modified `swarm_ctl.sh` and untracked `run_hidden.pyw`;
  development also has modified `tests/test_install_registers_the_task.py`.
  None was changed or staged in this work.
- Historical supervisor logs show intermittent heartbeat-file replacement errors.
  The current heartbeat is fresh; retain those observations for #72 rather than
  treating the log alone as current failure or changing runtime during this task.

## Implemented prerequisite: recovery

Draft PR: https://github.com/Decksx/agent-swarm/pull/97

Head: `84edbea40e78035ecad56bee3d6c4d931b405031`.
Branch: `fix/92-external-review-recovery`.
Development worktree: `C:\git\agent-swarm-worktrees\external-review-recovery`.
Dependency/base branch: `feat/91-external-review-states` (PR #96).

The state table already defines external lease/deadline transitions, but
`activations._recovery_kind` omitted both external review states. The sweep
expired the activation without recovering the task. The fix includes those
states in the existing assigned/running classifications. It does not expose
external ingress or complete #92.

Validation on the candidate source:

- 232 tests passed in 195.84 seconds; no failures or skips, two deprecation
  warnings. Suites: external recovery/states, controller activations/states,
  progression, integration race, author activation/budget, and controller API.
- Four timeout cases reproduced the defect against unchanged #96 before the fix.
  Four moved-on cases passed before the fix. The new regression suite has eight
  cases and checks reissue, pinned range, ledger replay, old-permission refusal,
  exact boundaries and no terminal/blocked reopening.
- Three independent in-memory mutations detected exactly their expected failures:
  omit assigned recovery (two), omit running recovery (two), put running external
  work in the assigned group (one). No on-disk source sabotage.
- Whitespace check passed. No full repository suite was run for this change.
  Tests used temporary databases and did not call the live controller or models.
- PR #97 has no CI checks because the workflow only triggers PRs targeting main.
  Its base deliberately isolates the two-file follow-up from #96. Retarget to
  main after #96 merges, then obtain CI and independent exact-head review before
  treating it as merge-ready. Local tests are not a review verdict.

## PR96 merge and deployment plan

1. Obtain explicit operator go-ahead under root `AGENTS.md`. Recheck #96's head,
   base, mergeability, and the successful check runs immediately before merging.
   A changed candidate requires fresh review.
2. Merge only the reviewed head:
   `gh pr merge 96 --repo Decksx/agent-swarm --merge --match-head-commit 4ce87b2232a74fa00de711736269c4b0a66abbc2`.
   Read `mergedAt` and the actual merge commit afterward; do not use an open PR's
   prospective merge SHA as a completed-merge receipt.
3. With deployment authorization, inspect the current production diff and control
   scripts again, pause using supported controls, and verify no active work.
   Preserve the hidden launcher, task registration, control flags and cursors.
   Do not force-reset the production checkout or discard its local fixes.
4. Advance the pinned production checkout explicitly to the actual merge commit.
   Check that local shell changes can be preserved; resolve a conflict as real
   work rather than replacing them. Run the existing deploy gate with Git Bash
   and `DEPLOY_PYTHON=C:/Python311/python`. Its full tests must pass before copy
   and Tower restart. The supplied earlier partial full-suite rerun is not a
   substitute for the deploy gate.
5. Deploy the controller through `deploy_controller.sh`. PR96 also changes
   supervisor-loaded narrator code, so restart supervisor/workers through the
   supported controls while preserving pause, then check scheduled ensure,
   supervisor uniqueness, workers and cursors. Recheck the currently installed
   hidden scheduled-launcher path instead of reinstalling an older visible one.
6. Verify running/disk/checkout controller parity for all three identities and
   record actual merge/build/process evidence. Resume only as authorized. Keep
   external ingress unavailable until its later implementation is reviewed.

## #92 implementation plan

Issue #92 is still open and is not implemented by the recovery PR. Follow
`docs/design/74-external-review.md` section 6, with these code-level seams:

1. **Represent a pending external request honestly.** Current task versions
   require `base_sha` before a task or activation exists, but ingest is what
   discovers the external range. Define an explicit external task kind/request
   record and pending-base representation through a tested schema migration;
   do not invent a zero SHA or claim an author produced the candidate. Preserve
   the operator's objective, optional paths, expected head and family declarations
   as immutable request data. A proposed approach is nullable base for pending
   external tasks plus a separate version-bound external-request record, with
   ordinary creation/ready routes rejecting that representation. This is an
   implementation proposal, not an addition to the accepted design yet.
2. **Dedicated ingress and activation.** Add an admin-only request route and
   matching `controller_admin` command in a bounded module rather than expanding
   the already large API file unnecessarily. Validate request identity, project,
   PR number, objective and optional full SHA before creating work. Add `ingest`
   to `activations.STAGE_ROLES` with its own role/event and explicit repository
   binding. Keep capacity handling, idempotency, task-version and liveness checks
   as controller decisions. Generic `external_review_requested` stays refused.
3. **Recovery before reachability.** Define issuance/claim and lease/deadline
   events for an ingest operating in `EXTERNAL_PENDING`, including claim/retry
   self-transitions if that state represents both pending and active ingest.
   Test expiry before claim, during fetch, after pinning but before report, and
   after task cancellation. Extend the sweep when ingest is added; the current
   prerequisite covers external review assigned/running, not a future ingest
   activation. Repair returns `EXTERNAL_INGEST_BLOCKED` to `EXTERNAL_PENDING`.
4. **Model-free worker path.** Add a small external-ingest module, an explicit
   branch in `claude_worker.execute_activation`, and the stage to supported claim
   filters, including `claude_rate_guard`'s model-free stages. Route ingest
   failures through their own outcome method in `controller_client`; never
   accidentally report them through author or integration outcomes. No model
   call, candidate publication, merge, or integration approval on this path.
5. **Fetch, verify, and record.** In the activation-named registered checkout,
   ask GitHub for the PR identity/head/base and author claims, fetch the PR head
   to `refs/swarm/external/<task_id>`, and compare the resulting object to both
   GitHub's head and any operator-specified SHA. Compute merge-base and changed
   files, require the base object to be locally available or report an environment
   defect, and retain author emails/trailers/known footers as raw evidence.
   A reviewer must never repair a missing object by fetching later.
6. **Outcome and evidence boundary.** Add a dedicated ingest outcome handler,
   bound to the current live ingest activation and request version. Validate full
   SHAs, range and request consistency and durably record
   `external_candidate_registered` with head/base/merge-base, files, PR identity,
   ref and author signals. Absent/moved PRs are refusals; git/GitHub failures are
   environment defects. Neither is a review judgment. Define a durable, visible
   refusal outcome without abusing `EXTERNAL_REVIEWED` or author-defect paths.
7. **Stop at pinned readiness.** Slice 2 ends in `READY_EXTERNAL_REVIEW`. Do not
   enable progression issuing external reviews through the ordinary author-based
   lookup; it would demand a nonexistent producing author activation. Cross-family
   routing and chat confirmation remain #93; review outcome/publication/ref cleanup
   remain #94. Preserve pinned refs through recoverable failures.
8. **Verification and rollout.** Use a temporary bare Git remote and GitHub stubs
   for real fetch/race/missing-object tests; add API identity, stale version,
   duplicate report, capacity, repair and migration regressions. Mutation-check
   both SHA comparisons, ordinary-route refusal and the no-integration boundary.
   Run required full gates, obtain independent review at the exact candidate,
   then request the operator's merge/deploy go-ahead. Real ingestion remains gated.

The schema and refusal lifecycle are implementation seams that the high-level
design does not fully spell out. Resolve them in code/design review before
making the ingress reachable; a quick fetch helper alone would leave the
controller unable to represent its inputs and failures accurately.
