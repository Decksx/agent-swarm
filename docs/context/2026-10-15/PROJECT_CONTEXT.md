# Agent Swarm imported project context

## Codex wake split and bounded OPEN proof proposal — 2026-10-19

PR #120 design approved at `b9f9f17ee3eb924ec34f232a8145c835c2cf1eed` and merged
as `15fefe3b8361940fd2959e326aaf0ec539cf5ce4` with four green checks in run
`39302046336`. Claude's attachment precheck stopped without a queue call (#120
comment 6274464189, hive #1571). Codex independently confirmed no listen override
on desktop app-server PID 27236 or VS Code PID 45868 and no default control-socket path.
A safe attachment was not demonstrated; embedded-server fallback was not
empirically invoked. Queue stays disabled. Decision: Claude implements CLOSED
headless ownership/stdin/accounting/recovery; Codex reviews. Codex prepares OPEN
same-thread watcher proof; Claude reviews. No shared-daemon/app-config migration.

See [bounded OPEN watcher proposal](../../design/113-codex-open-watcher-proof.md).
Official docs and the exposed app tool offer same-thread scheduled follow-ups;
actual wake, tools/network and correlated ACK are not yet proven. The proposal
starts with one scheduled turn and explicit expiry/cleanup, not an unbounded
watcher. No schedule created, queue/model call, registration or runtime change
in preparing it. Project purpose remains removing David from message relaying;
saved schedules or room posts alone do not meet that outcome.

Claude reviewed PR #121 at `db8af38a03c93c5a51f99657f6f824618948710b`
(comment 6275677139, hive #1578). The revised proof prompt uses the detached
production helper at `C:\swarm-prod\agent-swarm\lead_chat.py` for read, find
and post, and explicitly sends PROBE-ACK with `--to @claude-lead` so the
mention watcher can see it. Own-post find retains identical ACK content.
Production helper CLI support was checked at
`ce5565b6f5b19958b8b210988d1e0fd0624f5c26`; no probe ACK or automation created.

## Claude lead takeover; relay auto-start restored — 2026-10-19

A new interactive Claude lead session took over. Its local CLI session UUID is
`a750400a-9432-40d2-af7c-da1f613a1035`, with cwd `C:\git`. The handoff, with
its current checkpoint (§0) and the bounded bridge-proof recipe (§5), is
[HANDOFF_CLAUDE_2026-10-19.md](../HANDOFF_CLAUDE_2026-10-19.md).

The relay daemon died in the 2026-10-19 reboot. It now runs from the scheduled
task `AgentSwarmLeadRelay`, which copies `AgentSwarmSupervisor`: a logon
trigger, a 5-minute repeat, `IgnoreNew`, and `ExecutionTimeLimit` set to
`PT0S`. Codex independently verified the task, the ancestor chain to Task
Scheduler and the binding (#118 review at `5cc70b1`). `claude-lead` is bound
to `a750400a`. At takeover it was enabled before any proof; Codex caught this
in review, and it was disabled until the proof. The new-session bridge proof
then **passed** for design §7 items 1–4, and `claude-lead` is now `enabled=1`.
The pass is qualified: the headless run lacked claude-in-chrome and some
deferred tools, which came back on resume. The proof ran admin #1541 → headless DELIVER #1542 → ACK #1543,
then resumed the same UUID. The receipt is on #113 (comment 6272343082). The
2026-10-16 proof covered the old session `f7daaff8` only. An open lead session
receives `notified` live deliveries only if it watches the chat. See handoff
§0 for the watcher, which must be re-armed every 30 minutes.
`codex-lead` is still unregistered. **Codex wake/ownership support is the
current next work**: claude-lead implements it and codex-lead reviews. No hub, controller or code was deployed.

## Confirmed names, scope and comic permissions — 2026-10-16

David directly confirmed in this Codex conversation:

> I'm fine with the names. Yes I would like you to have the same permissions for the comic automation suite project. Do #109  and the relay first.

The chosen sequence is #109 (distinct interactive lead identities/posting), then
the durable wake-up relay; #93-95 are parked behind them. Names are codex-lead
and claude-lead, both non-admin, with @admin for questions requiring David's
decision. Claude's matching record/ownership is issue #109 comment 6220726510:
Claude implements #109, Codex independently reviews exact heads, and the relay
gets its own issue/design review. This scope decision is no longer pending.
NEXT_STEPS.md and AGENTS.md now reflect it. No credential or runtime deployment
is performed by this documentation update.

Both Codex and Claude also have standing permission for routine engineering
builds, commits, pushes, merges and deployments on the comic automation suite
(Decksx/cbz-automation-suite, C:\git\ComicAutomation), as on agent-swarm.
Independent review, exact-commit CI and supported deployment controls remain.
The comic project's explicit operator-only backfill/library data rules still
apply. Read that destination's applicable instructions before changing it.
Its existing dirty development checkout was inspected and left untouched;
no comic source, runtime, data or batch operation was changed here.

The practical acceptance goal remains delivery to and resumption of the actual
interactive leads without David as the relay. Posting successfully to a room
or running one of the existing background workers is insufficient. Preserve
durable state, deduplication and visible failure/recovery evidence in the relay
design, while retaining controller activation and engineering review authority.

David subsequently requested a later CI-efficiency follow-up for the comic
automation suite, using the measured agent-swarm improvement as a reference.
Recorded at https://github.com/Decksx/cbz-automation-suite/issues/92. Profile its
own workflow, trial safe parallelism/caching and preserve coverage/check meaning;
do not assume its bottleneck matches agent-swarm. This backlog item does not
change the current #109/relay priority. No comic source or CI was changed.

## #92 deployed; direct coordination is the product goal — 2026-10-16

David clarified the goal: Codex and Claude should collaborate efficiently and
accurately on projects such as comic automation, check each other's claims and
continue without him copying messages or monitoring both chats. GitHub carries
engineering handoffs/reviews; hive chat should provide his project-level view.
David explicitly requested PR comments for reviews and handoffs so Claude's
session watcher can receive them directly. AGENTS.md and engineering-leadership.md
now record this. The reported watcher is session-bound/30-minute limited and
does not establish always-on delivery. Interactive sessions and background API/
CLI workers remain distinct; actual participant adapters and durable resumption
must be demonstrated before calling the larger goal complete.

Read Claude's #108 approval comment 6219773081. Exact reviewed head 3f36189
merged as `15c1278a0a342b5888216cb9c639c85eec2218d0`, with an identical tree.
Candidate CI 38929581674 and main CI 38930791362 passed all four checks. Codex
posted rollout ownership directly as PR #108 comment 6220153648, then deployed
Tower and OfficePC through supported controls under standing permission.

Full local deployment gate: 2,328 core passed plus ten scheduler-permission
skips, and 380 hub passed; no failures. CI exercised those ten successfully.
All 16 Tower digests and all production Git object bytes matched. Final loaded,
disk and checkout controller build is
`b598aacbbcea86b184fb887c9d5313099ce6ede9515ba0f210136cd689324f51`, schema 6.
Trusted maps enable only agenthub at C:\git\agent-swarm / Decksx/agent-swarm;
PROGRESSION_INGESTER=claudecode. Existing image/container configuration and
worker guard history were preserved; a final comparison restored the original
PID cap before ingest enablement. The runtime is resumed with one supervisor
and three production workers. See DEPLOYMENT_INGEST92_2026-10-16.md for details.

Real task EXT-92-PROOF-20261016-108 reached READY_EXTERNAL_REVIEW via activation
cd5243a16bad42b5a6407dbc83888365. Controller registration event
2069713513ac489cade44f769d6c9d64 (seq 529) records PR #108 head
3f36189e51aeaa0349e6c6f7c0e598afd7a40a13, matching its immutable local pin,
12 changed files and Codex attribution. Scratch refs were cleaned, dev HEAD/
worktree were unchanged and model usage/hold files stayed byte-identical.
There is no review verdict or integration approval. #93/#94 remain to build.

At the time of that rollout, issue #109's names/routing decision had not yet
arrived. That historical checkpoint is superseded by the confirmed decision at
the top of this file: codex-lead/claude-lead and @admin are approved, with #109
and the relay first. No new lead identity or credential was installed by the
ingest deployment itself.

## #92 merged halves and dispatch follow-up — 2026-10-16

Verified GitHub merge records: controller #107 merged as
`37701ad3ce61e3e34d857a5223a0ba8ab2af7182`, pinned to approved 4907098;
worker #106 merged as `babea855d22a5dfa725e019091e5076a6fa3150a`, pinned to
`12188e53344463c998be7c5a278383d7591a8cc9`. Main's tree equals that reviewed
worker candidate, which already contained the approved controller unchanged.
All four checks passed at 12188e5 in run 38925675580: 2,314 core, 375 hub and
8 bypass tests (2,697 total) in 5m57s. Claude's exact-head approval is PR #106
comment 6219365823; its local footer audit detected all 50 attributed bodies
among 72 repo PRs. These are engineering records, not controller verdicts.

Codex's new `feat/92-ingest-dispatch` branch starts at babea85 in its existing
isolated worktree. It connects the ingest adapter to the worker dispatcher and
adds ingest to model-free claims during rate holds or unavailable shared usage.
Global pause and directory-source holds still prevent claims. A rejected claim
filter reports ingest through its dedicated route, tolerating an unconfirmed
report without running the activation. Tests exercise all three outcomes,
authority checks, held/pause behavior, real local Git pinning, and HTTP replay
and invalid-registration correction through dispatch. Local verification passed
449 selected core tests and 45 selected HTTP tests (494 total). Nine selected
dispatch guard mutations were caught. A combined local HTTP/Git probe through
the real dispatcher passed success, SHA mismatch, lost-response replay with the
same event ID and 422-to-blocked correction. Compilation and whitespace checks
passed. Exact-head CI and Claude review remain required.

No production rollout, Tower configuration or real controller task was made.
The last recorded OfficePC release remains d249366; this work did not inspect
live process health. After this PR passes review/CI, deploy controller and
workers with the existing controls and parity checks, configuring both project
maps and PROGRESSION_INGESTER on Tower. See NEXT_STEPS.md for the rollout boundary.
The first live proof for #92 is ingestion to READY_EXTERNAL_REVIEW; a complete
external-review verdict and publication require the later #93/#94 slices.

## #107 approved; #106 session-footer correction — 2026-10-16

Codex re-reviewed controller #107 at `49070986140065bc7eb3a08991b0d5d97ce97fbf`:
approved with no remaining findings. All four candidate checks passed in CI
`38847398634`; 311 selected controller/API/state/recovery checks passed locally.
Restoring the old sizing-outside-catch implementation in memory fails all nine
Unicode regressions. The byte limit and corrected-report behavior are preserved.
See `docs/reviews/PR107-controller-review-4907098.md`. This is local engineering
approval, not a controller-issued verdict; Claude owns the planned pinned merge.

Read Claude's latest #106 review comment 6207698469 at b6d1e5c. The corrected
parser allows bare or angle-bracketed HTTP(S) links in a trailing attribution
block, preserving Claude Code's exact attribution-plus-session-link footer.
Links themselves are not author signals, and links alone/prose/fenced examples
remain excluded. The contract sentence now states that behavior explicitly.
Overlapping attribution anchors share bounded windows, addressing the
non-blocking excerpt fan-out without dropping a match outside a covered window.

119 focused engine/client/CLI/footer checks passed; three new mutations caught
loss of the session-link support, treating links as signals, and excerpt fan-out.
The approved controller source joined this isolated worker branch at merge
`669a076dc911a49978f6f380e5ab62a427237a6f`; its controller bytes are unchanged
from 4907098. The shared conftest merged cleanly without duplicating its fixture.
The combined local selection passed 430 tests, and all 29 selected worker guard
mutations were caught. The combined HTTP/Git probe preserved the exact Claude
footer/session-link attribution and exercised success, mismatch, lost-response
replay and 422-to-blocked correction against these merged sources.
CI on the pushed candidate will therefore exercise both halves together.
Worker dispatch/ingest claims remain unwired.
Claude must re-review the new exact worker head; no production, Tower setting,
deployment or real-controller task was changed.

## #106 review fixes and #107 re-review — 2026-10-15

Re-reviewed #107 at `f75f10c9c34fc307c756a40cb977954c5af63f46`. Its four checks
passed in CI `38833573421`, and 302 selected local controller/API/state/recovery
checks passed. The exact-match, scalar-type and colon-path fixes resolve the
earlier findings. One remaining malformed-input case returns 500: an escaped
unpaired surrogate in pr_title fails UTF-8 payload sizing before the new catch.
See `docs/reviews/PR107-controller-review-f75f10c.md` for the HTTP reproduction
and narrow fix. No #107 merge or controller-issued verdict is claimed.

#106 addresses Claude's fb021e1 review: explicit refusal status/detail lets a
422 on registered become exactly one bounded sanitized blocked/worker_error
correction. Ambiguous transport errors and 409/403 do not change outcomes.
Only explicit trailing attribution blocks outside code fences become body
signals; ordinary mentions of Gemini/Claude Code are not authorship evidence.
Long individual signals become visibly marked excerpts preserving attribution
matches and pinned/source provenance. Identical kind/value signals deduplicate
with the first source; distinct-signal and total-payload limits still apply.
Sections 8.4/8.6 carry the proposed clarifications for Claude's exact-head review;
wire keys and controller field limits are unchanged.

The worker also validates origin's GitHub host/slug before querying the PR,
reports observed gh transport/auth failures with the agreed codes, removes
inherited Git overrides and hub/model credentials from child environments while
keeping gh authentication, and throttles heartbeats to 15s with fresh checks
before/after the final pin. Dispatch and ingest claim support remain unwired.

179 focused local engine/client/CLI/claims/worker-loop/view-budget checks passed.
All 26 selected in-memory guard mutations were caught; compilation and whitespace
checks passed. The strengthened footer cases also exclude indented code and
fence-like text that is not a valid closing fence.
Blank lines between trailing attribution paragraphs preserve every claim.
Temporary local HTTP checks against #107 covered success, SHA mismatch, a lost
success response replayed with the original event ID, and a 422 followed by
EXTERNAL_INGEST_BLOCKED. No production endpoint, forge operation or model call
was used. Exact-head CI and Claude's fresh review remain required.

Authorization provenance: David directly wrote in this project conversation,
"You have my explicit permission to push, merge, commit, deploy, etc. for this
project." That later project-specific instruction remains in force. It supplies
operator permission for routine project operations; independent engineering
review, exact-commit CI, supported rollout controls and controller-issued
activations remain required. AGENTS.md retains this meaning; no new permission
or waiver of review gates was inferred from Claude's relayed notes.

## #92 wire agreement and controller cross-review — 2026-10-15

Codex confirmed PR #105 at `c622f22439a299757e916d50dc739b4a036c3d9c`:
all three interface findings and the replay-ordering clarification are resolved.
All four checks passed in run `38828613881`. It merged with a head pin as
`8bf9ea564ff8ba60a42c28afcf11906a26f9d79c`, documentation only.

Reviewed controller PR #107 at `aaf3ec0487aaad961a50d1f39c21183654da750a`.
All four candidate checks passed in run `38828730451`; 252 targeted controller,
API, state and recovery checks passed locally. Two remaining validation findings
are reproduced in `docs/reviews/PR107-controller-review-aaf3ec0.md`: regex match
accepts newline-terminated SHAs/IDs, and malformed nested field types return
500 instead of 422. Related numeric checks accept float PR numbers and boolean
schema versions. No GitHub review/comment or controller verdict was submitted.

The #106 worker now emits the agreed registered/failure envelopes, preserves
bounded untrusted PR text plus its full-body hash, extracts bounded typed author
signals from the full source, and uses controller-named reclaimable prefixes.
Scratch cleanup is best effort with expected-old-SHA deletes. The callable
adapter checks EXTERNAL_INGESTING before commands, refreshes remaining deadline
via heartbeat and reports through controller_client.report_ingest. Unreadable
ingest task records use this same dedicated result route. Worker dispatch and
ingest claims remain unwired pending cross-review; nothing was deployed.

A temporary local compatibility probe against the reviewed #107 controller
registered open and merged PRs (including Unicode truncation and attribution
beyond the excerpt) and refused an operator-SHA mismatch. These are local test
databases, never real production tasks. The broader test isolation fix from
#107 is also present: per-test worker usage/hold paths, avoiding production files
even for tests without the control fixture. Exact-head worker CI and Claude's
fresh review are required for this changed candidate.

Local worker verification: 131 focused engine/client/CLI/claims/runtime checks
passed, followed by 58 adapter/deadline/worker-loop/view-budget checks (20 overlap;
169 distinct checks in total). A further scratch-ref race check passed, making
170 distinct checks. All 18 final in-memory mutations were caught, including
removing the expected-old-SHA check from scratch deletion.
Removing only the inner cleanup handler left its outer handler enforcing best
effort behavior; removing both was detected. No surviving behavior-changing
mutation remains in that selected set. Python compilation and whitespace checks
passed. Full CI will be bound to the pushed candidate, not these working-tree
results or the earlier #106 head.

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
