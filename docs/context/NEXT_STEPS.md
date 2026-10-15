# Next steps after the Codex import

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
