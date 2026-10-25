# Codex lead successor handoff — 2026-10-25

Owner: codex-lead. Reviewer/cutover owner: claude-lead. David authorized a
fresh thread in chat and hive **#2735**. This is a concrete handoff and
**proposed** cutover, not a claim that the relay binding has changed.
All timestamps in this record use fixed UTC-6.

## Why a successor is needed

The retired candidate is thread
`01a1609d-cd64-7bd1-9880-2b5b488509d4`, workspace `C:\git\agent-swarm`.
The relay killed its #2646 attempt after 45 minutes at **2026-10-24
20:46:14** (hive #2711). The old turn prefix `01a170ca` remained
`inProgress`, holding reservation prefix `e7c8dfdf`; this is not ongoing
execution. Claude reported the stale row alongside the current live turn
in #2734. On 2026-10-25 David's new message resumed interactive work;
Codex recovered the files without editing Codex history or relay state.

The successor is the fresh **local Agent Swarm project** thread
`01a1744a-a2e9-7e61-8f82-1b3694a8a4e3`, titled
**codex-lead successor 2026-10-25**, created through the app tool using the
saved project/workspace and configured default model (no override).
Its bounded bootstrap turn `01a1744a-aa2e-7351-b321-fd048e513066`
**completed at 12:21:04**, with no error. The app's exact-thread read shows
idle; the final response reports the runtime id, verified workspace
`C:\git\agent-swarm`, standby and no relay ownership. The observed tools
were read-only instruction/context/workspace reads. No rebind or enablement
has occurred; bootstrap completion does not grant relay ownership.

## Engineering state at the clean break

- **Comic #130, Codex-owned planner:** exact
  `5219265e5b273dedc5bf15622be636fba7a7bd4d`, committed and pushed on
  `feat/canonical-readonly-plan-20261024`, based on merged master
  `5b00c34831ac509882c29549f247f2658c377867`.
  [Fresh review handoff](https://github.com/Decksx/cbz-automation-suite/pull/130#issuecomment-6401267098),
  confirmed hive **#2742**. Claude owns independent re-review; Codex owns
  fixes/pinned merge after approval and green exact-head CI. No approval
  or live run is claimed. Full **3858 passed / 8 skipped**, +76 planner
  tests on reviewed master 3782/8. Twenty-five guard mutants killed
  (24 single failures and seven metadata cases), bytes restored. The
  final exclusive-output test was run separately after 75 focused passes;
  all 76 are in the full run. Real tmp executor integration covers generated
  volume apply/recover/undo and family apply/re-plan/new-v3 evidence.
  Protocol: `docs/canonical_naming_plan.md` in the comic PR.
- **Comic #132, Claude-owned watcher hold:** changes requested at exact
  `9aa95a1a61268bbe958fa853b074b06abc706022`.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/132#issuecomment-6401286299),
  confirmed hive **#2745**. A failed arrival-name restoration loses the
  hold on retry; a successful restoration leaves the AI-original pair
  keyed to a stale path and offloads the deferred original. Both reproduced
  through the entry point in legacy/resolver modes, tmp-only. Focused
  **68 passed**; no independent full suite on this rejected head. Claude
  accepted both findings (#2747) and owns fixes/fresh handoff. David chose
  option (b): approved noise keeps keep-larger, distinguishing/unknown tags
  hold. Do not re-ask that decision.
- **Comic #133, Claude-owned malformed-number follow-up:** approved at
  `ee98a40c94f7198cc5c3545b63edba22e65bd64e`.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/133#issuecomment-6401316430),
  confirmed hive **#2749**. Own focused **91**, full **3873/8**, four guard
  mutants killed (6/5/5/2 failures), source restored; mixed-ending deltas
  verified. Claude owns the pinned merge after CI and combined-tree checks
  if master moves. Do not claim deployed until a receipt exists.
- **Swarm #157, Claude's dated night checkpoint:** approved at
  `c986568745b101b7840e58fe47c02ac2a1829c92` after correcting the timeout
  versus stale-turn distinction in both docs.
  [Review](https://github.com/Decksx/agent-swarm/pull/157#issuecomment-6401368146).
  Codex owns pinned merge after exact-head CI and tree parity. Later
  recovery/review events belong in a new checkpoint, not rewritten history.

Before acting, fetch the current PR heads and receipts; changed candidates
need fresh review. These are lead-run PR records, not controller verdicts.

## Runtime and authorization

Claude's latest receipt (#2703): David's checkout
`C:\git\ComicAutomation` is `2c4ae3d7b40b4bb2d4036bf8e5b9a546fb28f763`
(#129), tracked tree clean; watcher **43624**, started **2026-10-24
20:36:02**, same resolver arguments, clean log. GUI **11832** remains.
This later receipt is attributed to Claude. Codex independently checked
the earlier 20:01:34 restart (GUI11832/watcher48284, old44320 absent).

Completed on Oct24: comic #126/#127/#128/#129; G: test-DB re-certify
**58,246** after verified backup, separate postflight passed, **178 stale
+13 tied** left legacy (#2672). #128 is a prototype with no live caller;
no marker schema was installed on G:. No live rename was performed here.

Standing engineering permission covers commits/pushes/merges/deploys with
exact-head review, CI and rollout evidence. David #2646 also approves the
separate progress-table installer for now and the eventual read-only live
plan. **Claude owns the Tower dry run after #130 passes. Batch apply still
needs David's approval of its exact plan digest and operational preflight.**
Do not launch perceptual backfill: that remains operator-only. Preserve
decensor originals. Frontend off-network access is an eventual requirement,
not a public-exposure receipt. Frontend scope/design remains Claude-owned.

## Local work and evidence

All listed checkouts were isolated; preserve other work and do not clean
the shared roots. Read their status before changes.

- `C:\git\cbz-canonical-plan-20261024`: #130 implementation, clean after push.
- `C:\git\cbz-canonical-plan-mutants-20261024`: detached #130 mutation
  checkout; original source bytes restored, clean.
- `C:\git\cbz-review-132-20261025`: detached reviewed/rejected #132 head.
- `C:\git\cbz-review-133-20261025` and
  `C:\git\cbz-review-133-mutants-20261025`: detached approved #133 head;
  mutation source restored, clean.
- `C:\git\cbz-review-128-r3-20261024`: approved e3abec4; full3521/8 and
  six guard mutants killed (12/1/1/1/1/1), restored. Claude merged it as
  5b00c34; combined tree41ee067d passed3782/8 (#2707).
- `C:\git\agent-swarm-preflight-20261023`: owned documentation worktree.
  Do not switch the shared `C:\git\agent-swarm` development checkout.

Private probes/results are under
`C:\Users\david\Documents\Codex\control\`: `canonical_plan_guard_mutants*`,
`canonical_plan_contract_probe.py`, `comic132_probes.py`,
`comic133_mutants.py`, and earlier `comic128_*` / `comic129_*` probes.
They contain only tmp fixtures and no credentials. Do not commit runtime
logs, controller DBs, secret-bearing settings or generated live reports.

## Proposed cutover and its current gate

Use the reviewed #133/#135 successor pattern; preserve all old evidence.

1. Create an inert successor in the saved Agent Swarm project. Its bounded
   first turn reads AGENTS/context/this file, reports thread/workspace and
   stops. No engineering, posting, schedules, workers or state changes.
   Verify that exact bootstrap turn is terminal; an ACK is not completion.
2. Claude reviews the exact handoff and actual successor id. End this old
   engineering turn at the clean break; never resume engineering on the
   retired thread after cutover. Keep the old conversation/history intact.
3. **Current mechanical gate:** production `lead_relay_cli.py` lines170-173
   refuses registration while *any* reservation exists for the recipient,
   including the retained timed-out one. Fresh-thread creation alone does
   not bypass it. The October21 migration had no reservation; this case
   differs. Do not delete/update the reservation by SQL or mark the Codex
   orphan turn completed. Hive #2757 asks Claude to own a reviewed,
   narrowly fenced supported successor-transition route before cutover.
4. That route must retain old attempt/reservation evidence, prove the old
   process identity exited/timed out, forbid reusing its session, fence live
   work and register only the named successor **disabled**. Exact old
   attempt ids/process identities and fresh state must be read and checked
   by its prepare step; prefixes here are not executable selectors. Claude
   accepted route-change ownership in hive **#2760**, including checks of
   `_maybe_release` and usage paths after rebind; Codex owns exact-head
   review. This remains a proposed contract, not an approved bypass.
5. Audit the proof/lifecycle helpers for hardcoded thread ids and their
   retired-turn inventory. Any needed retargeting/exclusion is a separately
   reviewed code candidate with CI and deployment receipts. Do not broaden
   UNKNOWN to idle or silently ignore arbitrary active turns.
6. Only after supported registration: verify actual binding/workspace/CLI,
   preserve queued deliveries and ACK current notices explicitly, then run
   the bounded bridge proof before enablement. Do not replay room history,
   create schedules or close the app while a live turn remains. The
   interactive successor and background-worker connections remain distinct.

If a gate fails, preserve evidence and report it; creation of a fresh task
is not proof that the relay migrated or headless delivery works.
