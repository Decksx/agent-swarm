# Next steps after the Codex import

## Review checkpoint — 2026-10-24

- Comic #126 exact `2c4b2c1fbadd9a9e5488467358c30ba7570ea184` is
  **changes requested**, not approved: the new CJK fallback turns trailing
  multi-dot runs into numeric fields (`第1..話` -> chapter 1,
  `第1.2.巻` -> volume 1.2). Claude owns refusal guards, parse/XML witnesses
  and the fresh exact-head handoff. Codex's full suite passed **3459/8**;
  see [the actionable review](https://github.com/Decksx/cbz-automation-suite/pull/126#issuecomment-6390022554).
- Step 6 is complete: comic #127 merged `1206674`, swarm context #150
  merged `870fc92`, each pinned to Claude-approved heads after green CI,
  with identical reviewed/merged trees. Board 33 is done. The pending
  review/merge wording in the earlier checkpoint below is superseded.

## Restart checkpoint — 2026-10-24

- Comic #123 is merged as `3d68ccca`; its tested tree is `b52e1b5a`
  (**3396/8**). Older pending-merge statements below are superseded.
- Codex completed #112 step 6's isolated Komga measurement and cleanup;
  report [#127](https://github.com/Decksx/cbz-automation-suite/pull/127) at
  exact `edacb182756503b50d735ba6c4fa6ba61db9b9ea`. Ordinary renames
  changed IDs and preserved tested book state; quarantine scan/return
  lost it under auto-trash. Series-level metadata was not measured.
  Both test registrations and copied files are removed, originals and
  live-library configurations verified unchanged. Review/CI/merge receipts
  stay on the PR; no live rename rollout is implied.
- Claude owns #120 and #112 step 7 (fixture-only apply/undo/recover).
  The later live rename dry-run/digest review remains a separate step.

## Supersession approval checkpoint — 2026-10-23, round 5

Comic #123 exact `a2195f45c98d77b66d736790ff85d447c825a0c9` is
[approved](https://github.com/Decksx/cbz-automation-suite/pull/123#issuecomment-6377682077).
The root-name guard resolves the last finding and supersedes the round-4
hold below. Own exact-head **3338/8**; own combined tree `b52e1b5a` with
master `d74afa49` **3396/8**; both root mutants caught and both exact-head
CI checks green. Numeric normalized-whole bounds accepted as implemented.
Claude owns the pinned merge and actual receipt, verifying its tree against
the tested combination or validating a changed base. No live library/DB
operation was performed by Codex; this is a review receipt only.

## Comic review checkpoint — 2026-10-23, round 4

Comic #123 at `05e202f58579a5e10b4ee41dbad3c316f09690e9` is
[changes requested](https://github.com/Decksx/cbz-automation-suite/pull/123#issuecomment-6376893923).
The Image-index and Page-attribute fixes pass; root namespace identity is
still unchecked at the metadata-drop boundary. Claude owns the raw root
guard on both older and keeper, entry-point witnesses and a fresh exact
head. Own full **3333/8**, prior probes safe, four independent mutants
killed and source restored. Combined tree `8e015dd5` was reproduced; its
3391/8 suite is Claude-reported.

Watcher rollout is no longer a pending action: Claude's hive #2464 reports
the #125 merge `d74afa49` deployed to `C:\git\ComicAutomation` and GUI pid
20384 started at **16:13 UTC-6**, with smoke checks passing. This is a
reported GUI rollout receipt, not proof the watcher service is running;
Claude said David starts the watcher from the GUI and no import was
triggered. Details and attribution are at the top of PROJECT_CONTEXT.md.

## Watcher review checkpoint — 2026-10-23

**Follow-up approved:** comic #125 exact
`13040abc8cb2c9882b4e438ff17c11f3ace04544` resolves the excluded-history
cleanup blocker in both merge branches. Codex's
[approval](https://github.com/Decksx/cbz-automation-suite/pull/125#issuecomment-6375751467)
records own full 3290 passed / 8 skipped, eight original probes and two new
late-arrival probes passing, four independent mutants killed and both
exact-head CI checks green. Claude owns the pinned merge and coordinated
watcher rollout under the existing authorization, retaining backup and
postflight receipts. Codex performed no live changes; this is not a rollout
receipt. The earlier candidate's hold below is superseded by this approval.

Comic [#125](https://github.com/Decksx/cbz-automation-suite/pull/125), exact
`f7322e397bb774ece801e55c9ca1806af7388d13`, is **changes requested** in
[Codex's review](https://github.com/Decksx/cbz-automation-suite/pull/125#issuecomment-6375542324).
The two textual conflicts are resolved correctly, and the full suite is
3278 passed / 8 skipped. Independent entry-point probes nevertheless show
that both merge cleanup paths permanently delete excluded source history
after skipping it. Six other routing probes pass; four guard mutants were
killed. Claude owns the cleanup fix and entry-point regressions, followed
by a fresh exact-head review and green CI before merge or live rollout.

David's terminal authorization reported in hive #2442 includes the checkout
switch and GUI restart, so a new permission question is not the remaining
gate. Codex made no live changes in this review. The deployment hold was
delivered in confirmed hive #2443/#2447. The detailed checkpoint is at the
top of `2026-10-15/PROJECT_CONTEXT.md`; it supersedes older watcher-next-step
statements below, not their unrelated project history.

## Authorization update — 2026-10-23, 15:10 UTC-6

David's hive **#2408** authorizes project changes to Tower, `X:\`, `G:\`
and the database on `G:\`, and routine git/deployment operations. This
supersedes the access/deployment permission blockers in earlier checkpoints.
Keep independent exact-head review/CI, backups, plan/digest checks and
postflight verification, with one coordinated live-change owner. Access
permission does not resolve the naming-vocabulary decisions.

Per hive **#2418/#2421**, Claude owns both Tower name scans, the #117 plan
and watcher deployment preflight. Codex stopped its duplicate scan and owns
this authorization record and independent #123 review; Claude owns its fixes.
The next #123 head still needs review. The authorization itself is not an
execution receipt.

## Current checkpoint — 2026-10-23

Supersedes the 2026-10-22 night checkpoint below.
- **Comic master is `e7f1724`.** Today's merges were #117, #118, #121 and
  #119. The combined tree is 3230 passed / 8 skipped.
- **#112 §6 progress:** steps 1–4 are merged.
  - 1: the `series_key` fixpoint;
  - 2: page order;
  - 3: the formatter, plus the shared-core/watcher arrival integration.
    The standalone `cbz_sanitizer.py` cleaner is still deferred; backfill can
    still rename one earlier library archive on arrival, as before.
  - 4: field resolution.
- **Next:** the #119 witness test PR (comic #122), then step 5 (the
  supersession evaluator, read-only).
- **Operator-gated:**
  - watcher deploy (changes arrival names);
  - #117 re-certify plan/apply;
  - index rebuild;
  - re-inventory;
  - #110 refusals deploy.
- **Awaiting David:** the square-bracket word question and the Tower name
  scans.
- Details are in `2026-10-15/PROJECT_CONTEXT.md`, "Current state —
  2026-10-23".

## Earlier checkpoint — 2026-10-22 (night)

Supersedes the evening checkpoint below.
- **Comic master is `3aab686`** (2710 passed / 8 skipped). Tonight's merges
  were #109, #110, #112, #113, #114, #115 and #116. The two Step 8 defects
  (the `series_key` split and page order) are fixed.
- **Relay caps** are 60/hour, 500/day and chain 200 (David approved, user
  env). codex-lead is enabled with no end time.
- **Next:** the re-certify tool for v1 content signatures (it must precede
  any production cutover), then #112 §6 step 3.
- **Awaiting David:** read-only Tower name scans (the key-change report and
  the bracket words), and every operator-gated rebuild, re-certify,
  re-inventory or deploy.
- **When a reply is overdue,** check the relay attempt's exit code and log.
  An ACK can precede a failed turn (model capacity).
- Details are in `2026-10-15/PROJECT_CONTEXT.md`, "Current state —
  2026-10-22 (night)".

## Earlier checkpoint — 2026-10-22 (evening)

Supersedes the codex-lead *disabled* boundary below.
- codex-lead is **enabled, with no end time** (David, terminal, 16:22 UTC-6),
  after the 15:00 UTC-6 expiry disabled it cleanly. The one-shot expiry task
  is deleted.
- Comic #106 and #107 are merged (`90e9ca65`, `f957bded`).
- Next product work is comic **#108**: a read-only cross-copy inventory ahead
  of a Tower → X: merge. Codex implements it; Claude reviews.
- To wake the other lead, a message must start `HANDOFF @name:` or
  `QUESTION @name:`. STATUS posts never wake anyone.
- Details are in `2026-10-15/PROJECT_CONTEXT.md`, "Current state — 2026-10-22
  (evening)".

## Earlier checkpoint — 2026-10-22 (CLOSED proof passed)

The bounded successor proof **`f120c372` passed**, and the app was closed and
reopened by Claude through the reviewed lifecycle helper. This supersedes the
pending-proof and old production/hash statements below.

- **#137:** approved `07e016ffe1c277bd9217cdd92883c5fb42db4e69`, merged and
  deployed as `61286041cbcc5d475f1e470aaba40faa39dc3408` (identical tree).
  Main CI `39798706770` passed. Scripts-only deployment; no service restart.
- **Disabled-only lifecycle trial:** Claude's
  [receipt](https://github.com/Decksx/agent-swarm/pull/137#issuecomment-6344033301)
  records graceful close at 15:04:25–26Z and guarded reopen at 15:04:52–15:05:05Z.
  The separate VS Code app-server was left alone.
- **Proof:** admin source #1917 and Claude source #1919 each had exactly one
  headless launch, exit 0, recorded usage and delivered/ack state. ACKs were
  #1920/#1923; STATUS #1921 named the actual successor thread and workspace.
  Probe 2 was posted while probe 1 ran, then launched **62.5 ms after** probe 1
  exited. Both woken turns are recorded completed on the successor.
- **Cleanup:** result `passed`, no stop reasons, both proof processes confirmed
  exited, usage settled, reservations clear, no new session files, and disable
  confirmed. Claude reopened through the gated `codex app` command at 15:19:52Z.
  Config SHA256 during the proof was unchanged at
  `e6ca4f491a4323b93efe4db9a474a294eb7bb1d1101963b4986c65b41bc46ca4`.
- **Independent audit:** production clean at the exact merge, green main CI,
  relay rows, result, process identities and successor-only turn metadata checked.
  The result file SHA256 is
  `87a6226223ce0f0523867be9576ac0e706d066679f5a4f312613d46b80d7b500`.
  [Claude's proof receipt](https://github.com/Decksx/agent-swarm/issues/113#issuecomment-6344366113);
  [Codex's audit](https://github.com/Decksx/agent-swarm/pull/137#issuecomment-6344548737).
- **Current boundary:** codex-lead remains **disabled**, bound to successor
  `01a1609d-cd64-7bd1-9880-2b5b488509d4` / `C:\git\agent-swarm`; pending deliveries
  and reservations are zero. Original cancelled proof `53e110d6` remains claimed
  with its three original file fingerprints unchanged. No records were reset.
- **Remaining limits/next action:** David's post-reopen `Check` reached the same
  chat. Database completion does not independently prove visual app-UI rendering.
  Unknown-id refusal remains backend-only; no always-on OPEN watcher is claimed.
  Any ongoing-enablement decision is separate from this completed finite proof.
  Comic automation #32/#35 remains the next product workstream.

## Earlier checkpoint — 2026-10-22 (early)

This supersedes the evening statements below that the binding still names the
old thread, that the migration awaits review, and that production is at
`dc565ef`.

- **#135 merged and rolled out** (successor driver migration).
  - It was approved at `847e51b` and merged pinned as `bab1e3a`. Main CI run
    39711151698 passed.
  - Driver-only deploy: production moved from `dc565ef` to `bab1e3a` with no
    restart. Relay 30464 and supervisor 39260 were untouched.
  - **`reconcile-old`** ran at 02:37:20Z, rc 0. The receipt is
    `codex_closed_proof.53e110d6.reconciled.json` (sha256 `a12c420b…`), with
    the verdict `cancelled before enable`, 0 launches and no result. The old
    claim and its three files are byte-identical; the claim is still
    `claimed`.
  - **codex-lead is registered disabled to the successor**:
    - thread `01a1609d-cd64-7bd1-9880-2b5b488509d4`;
    - workspace `C:\git\agent-swarm`;
    - cli `…\OpenAI\Codex\bin\896a0166b774037a\codex.exe`, sha256 `f6dbf48c…0312`.

    The binding equals the driver's constants. Ownership reads OPEN while
    the app is open. There were 0 pending deliveries and 0 reservations.
  - [Receipt](https://github.com/Decksx/agent-swarm/pull/135#issuecomment-6331335254);
    Codex's [independent audit](https://github.com/Decksx/agent-swarm/pull/135#issuecomment-6331912062)
    passed (hive #1885).
- **Settings baseline for the next `prepare`** (read 2026-10-22 by key only, not
  the whole file):
  - `~/.codex/config.toml` sha256 is
    `b6a99abbeafd4c66fa1e551af836ea2e1ecc3071cdc5e8468239ad87b0988166`,
    modified 2026-10-21 22:44:23Z. It was `ef7e7918…1866` on 2026-10-21.
    **The cause of that change is unknown**; it has not been attributed.
  - The current observed proof-relevant values:
    - `sandbox_mode = "danger-full-access"`;
    - `[windows] sandbox = "unelevated"`;
    - model `gpt-6.1-sol` at reasoning effort `high`;
    - no `approval_policy` or `network_access` key.

    Only the two sandbox values have an earlier recorded reading to compare
    against (2026-10-21), and they match it.
    `projects."c:\git\agent-swarm".trust_level = "trusted"` is present, which
    fits the successor's workspace.
  - **Before the next `prepare`,** Claude rechecks these keys and supplies the
    file's then-current sha256 as `--config-sha256`. `prepare` and the
    preflight do not read the keys: they hash the file and compare that hash
    with the supplied value.
- **Next:** a bounded successor proof, when David is available (Codex asked him,
  hive #1887). Before telling him to quit, the target turn must be terminal
  with no `inProgress` turn. Then the comic #32/#35 reconciliation.

## Earlier checkpoint — 2026-10-21 (evening)

This supersedes the afternoon statements below that codex-lead is
unregistered, that the CLOSED proof is pending review, and that no real admin
`@Leads` delivery had been observed.

- **#133 merged and deployed** (`a4e79b7`, driver only, no restart). It adds
  the reviewed one-use CLOSED-proof driver, `codex_closed_proof.py`.
  codex-lead was **registered disabled** to the old thread `01a14068`, with
  workspace `C:\Users\david\Documents\Codex` and the 0.163 cli.
- **Proof `53e110d6` was cancelled before enable,** at David's request.
  - The app was quit while the target turn `01a1607c…` was still active.
    `thread_turns` kept that turn `inProgress`, so ownership read UNKNOWN,
    correctly.
  - Nothing was enabled or launched.
  - The driver was stopped by identity (pid and creation time). Its claim is
    **retained as `claimed`** for explicit reconciliation, alongside
    `codex_closed_proof.53e110d6.cancelled.txt`.
  - Codex state was not edited.
- **Procedure amendment.** Before telling David to quit, verify that the exact
  target turn has completed and that no `inProgress` turn remains. A waiting
  driver is not that evidence.
- **Codex lead migrated** with David's approval. The successor interactive
  lead is thread `01a1609d-cd64-7bd1-9880-2b5b488509d4`, workspace
  `C:\git\agent-swarm` (hive #1851, #1856). The old thread is retired from
  engineering and preserved.
  - The relay binding still names the old thread, disabled.
  - The [migration proposal](https://github.com/Decksx/agent-swarm/pull/133#issuecomment-6328204971)
    is implemented on `feat/codex-proof-successor` and awaits review. It
    retargets the driver and adds a one-time `reconcile-old`. No rebind or new
    proof happens before that PR is merged.
  - Pending notices #1854 and #1860 were reconciled by Codex ACKing their
    current attempts (hive #1868, #1870). Both are delivered, nothing was
    cancelled, and nothing was replayed.
- **`@Leads` is observed end to end.** Admin #1834 created one delivery per
  lead, and both were ACKed. Codex's receipt followed David asking it to
  check; it was not an autonomous pickup.
- **Relay limits are live: 20/hour, 160/day, chain 80** (David, #1834 and
  #1845).
  - #134 was approved at `89b85ff` and merged pinned as `dc565ef`. Main CI
    run 39690905890 passed.
  - Relay-only rollout: the checkout moved at 23:09:44Z, and relay **30464**
    was created at 23:09:47Z. `/relay/status` reports 20/160/80. Deliveries,
    sessions, wakes (25), attempts (50) and reservations (0) are unchanged.
  - [Receipt](https://github.com/Decksx/agent-swarm/pull/134#issuecomment-6328602222).
    Codex verified it independently (hive #1874).
  - Production is detached at `dc565ef`. Hub build `0833f9ad1bd2` and
    supervisor 39260 are unchanged.

## Earlier checkpoint — 2026-10-21 (afternoon)

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
  100/day, with a lead-to-lead chain limit of 12. Live notices are free. These
  were raised to 20/160/80 that evening (#134); see the evening checkpoint.
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
