# Agent Swarm imported project context

## Independent comic naming re-review — 2026-10-26

Comic [#142](https://github.com/Decksx/cbz-automation-suite/pull/142), exact
**084d4e8c13ae26904262673fa87e5153e0ebff34**, received Codex **CHANGES REQUESTED**
in [review6426560666](https://github.com/Decksx/cbz-automation-suite/pull/142#issuecomment-6426560666),
confirmed hive **#3048**. This supersedes the pending review/ownership notes below.
David's takeover instruction **#3010**, Claude's **#3011**, and final handoff
**#3045** assign Claude the fixes and pinned merge; Codex independently reviews.
The five follow-up commits are on top of rejected39d5759. No approval or merge
of either rejected head is implied by passing tests.

- **R1 HIGH:** the planner still erases an unmatched-title filename series year.
  Fixture `Batman/Other (2016) #003.cbz` with ComicInfo Series Batman/Number3,
  no Year, proposes `Batman #003.cbz` with no review entry. Master9a79172 holds
  the same fixture as year-unresolved. The watcher's leftover-year guard
  covers this case, but the planner/shared decision does not. Source bytes
  remain unchanged by both read-only plans.
- **R2 HIGH:** a failed issue-year metadata write still permits landing after
  the filename year was erased. A real configured-registry import of
  `Batman (2016) #003 (2019).cbz`, no ComicInfo, with PermissionError injected
  only into the real Year-recording temporary writer, exhausts all five
  attempts and logs failure yet lands `Batman (2016) #003.cbz` without Year2019
  in XML and with nothing left in intake. Persist/verify Year before discarding
  it from the name, and retain/recover the distinguishing name on failure.
  Failed-write and retry/restart regressions are required.

Own full Windows/Python3.11 suite **4284 passed /10 skipped (226.92s)**;
exact PR CI **40393511393 completed/success** independently checked.
**8/8 additional selected in-memory guard mutants killed**, both mutated
modules' source SHA256s unchanged. Successful scene imports retain Year2019
in XML; corroborated ComicInfo/ComicVine and Full apply/re-plan cases pass.
Clean reviewed tree **ea561377cb3329f475b4198cb3672888c9ff170a**; derived LF
diff-check clean (45 CRLF/mixed exclusions). Against39d,3503/3507 old watcher
lines remain byte-exact,3528 final lines,2689 CRLF/839 bare LF.

F3's unconfirmed bare scene number retaining its legacy name, G2's issue-shaped
intake directory, and the existing planner/Number conflict parity gap remain
disclosed follow-ups. No live library/DB/config/watcher, relay or Codex state
was changed in this review. Batch apply still requires a fresh digest and
verified backup with David's approval. No reviewer test processes remain.

Context #167 merged55bcc82 as **ae8936454bf1597ca6addf6ef958c2d5b27b6b17**
(API verified). Claude's hive **#3044** reports David chose a4h/5h relay budget
and Claude applied14400 while no Codex run was active; this supersedes Codex's
earlier suggested18000 value. This is Claude's rollout receipt, not a Codex
runtime change or an independently verified Android error diagnosis.


## Media naming review fixes and operator decisions — 2026-10-26

Comic [#142](https://github.com/Decksx/cbz-automation-suite/pull/142) is ready
for fresh independent review at **39d5759c7e7ee4a162e48ee906823dab0e484810**,
tree **61e10d927d7a42dc7dd0453cd47d35a4977d183e**. This supersedes the earlier
3a5517f/5055478 candidates and the earlier Full/name-conflict decisions below.
Final PR handoff **6424467782**, confirmed hive **#2999**.

Claude's review **6423576221**, delivered in **#2987** (ACK **#2989**), found
D1-D4. All13 initial real configured-registry witnesses fail on reviewed3a
and pass fixed: unconsumed numbers keep their legacy arrival names; same-file
Windows case renames use two no-replace steps with rollback/retained-path
tracking; explicit root scope cannot erase the folder-authority check; and
auto refuses physical registered roots nested below its scope, including an
outside junction alias. An empty watcher registry now means legacy naming/OFF,
while planner auto remains strict.

David's decisions forwarded in **#2991**, with year correction **#2996**,
are incorporated: confirmed chosen series folders win aliases/typos while
original ComicInfo evidence remains recorded in planner resolution. Number,
Volume, decensor and supersession facts remain independent. Reboot identity
uses a distinct series_year field: **Batman (2016) #003** versus
**Batman (2026) #003**. The reboot year is the only filename year; an issue
year2020 stays in ComicInfo, verified through real rewriting and re-scan.
Unnumbered Full defaults to **v01 (TPB)** with original-source operator-policy
evidence, reused during proposed-state resolution. Registered roots stay flat;
unregistered series-root scans assert **--series-folder-root**, sealed in
provenance. These replace the prior substantive-name/unnumbered-Full holds.

Final exact-head own full suite **4229 passed / 10 skipped (180.19s)**;
measured master9a79172 **4120/10**, net+109 passes. Intermediate5055478
(D1-D4 before the later operator decisions) passed **4214/10 (176.95s)**.
**30/30 selected in-memory guard mutants killed**, seven source hashes unchanged.
All13 initial reproducers and real caller/XML/rescan/recovery checks pass.
The obsolete hold-policy mutants were replaced with the new operator-policy,
series-year, original-source-default and root-scope guards. Source is clean
and the derived LF diff-check is clean (45 CRLF/mixed exclusions).
Exact-head CI **40379815968** remains pending at this dated local handoff.

Codex retains fixes and the pinned merge after Claude's exact-head approval
and green CI; Claude owns independent review and deliberate rollout. No live
watcher/config/library/DB/relay operation by Codex. Batch apply still needs
a fresh read-only plan, verified backup and David's exact digest approval.
Active copy remains `C:\git\cbz-media-naming-20261026` until merge; registered
swarm successor workspace remains unchanged. No test processes remain running.

Context [#166](https://github.com/Decksx/agent-swarm/pull/166) merged approved
e66180f as **260d28223893beedb0b829981d17307d3e686935** (API confirmed;
Claude's receipt **#2986** reports tree parity/green CI). That record remains
historical; the current policy/head above supersedes its pending old review.

## Holding merge, media naming handoff and workspace reviews — 2026-10-26

Comic [#138](https://github.com/Decksx/cbz-automation-suite/pull/138) merged
reviewed **cfb6c916a194f3be5c4548bc3cf91f98751065b5** as
**6c15b76594165018076db536e07047b0b92ce0f9**. Claude approved the exact head
in **6422332562**; exact CI **40363974477** succeeded. Codex verified the
reviewed/merged tree **17896ef9398419f335f4a4fa682c20164234a831** and posted
merge receipt **6422430664**, confirmed hive **#2955**. Own full **4120/10**.
Claude reports deployment in **#2956**: the live checkout advanced, no watcher
or GUI was running, and holds remain disabled until David chooses a root.
Codex did not deploy, restart or configure it.

Comic naming design [#140](https://github.com/Decksx/cbz-automation-suite/issues/140)
was approved by Claude in **6422344608**. Implementation is ready for independent
review as [#142](https://github.com/Decksx/cbz-automation-suite/pull/142), exact
**3a5517f36bd8b1e44025ee47720f3f1f043e3679**, incorporating master **9a79172**;
tree **ffce372d9b0ba2635d35a4c7da3aff59356d87f1**. Final handoff **6423219499**,
confirmed hive **#2965**. Codex owns fixes/pinned merge after exact-head Claude
approval and green CI; Claude owns review and deliberate rollout.

- Final own full suite **4192 passed / 10 skipped (160.20s)** versus measured
  unchanged base **4120/10 (180.03s)**: exactly **72 new passes**.
- **16/16 selected in-memory guard mutants killed**, all six source hashes
  unchanged. The final subfolder conflict witness fails before **2192b2f**
  and passes after: narrowing an auto-registry scan cannot erase title conflict.
- Clean checkout and derived LF diff-check (45 CRLF/mixed exclusions).
  All **3375** unchanged watcher lines are byte-exact against the **3383**-line
  master; final **2631 CRLF / 838 bare LF**.
- Exact-head CI **40370986680** is pending at this local handoff; predecessor
  CI or local results do not substitute for it.

Western issues use `#003`; TPB/Vol/numbered Full collections use `v01 (TPB)`
with a separate collection slot preserving Colored and other editions.
Manga chapters use `ch. 3`; volumes omit TPB. Unnumbered Full stays held
pending David's volume-default decision. Narrow normalized-equal folder display
wins while substantive conflicts stay held. The shared style registry matches
physical ancestor identities, supports explicit style and an external
`CBZ_NUMBER_STYLE_REGISTRY`, and is sealed into planner provenance/digest.
The watcher binds original metadata before rewriting and selects style from
the final resolved destination. Protocol/limits are in `docs/media_aware_naming.md`.

**Rollout gate:** the checked-in registry is empty and unknown auto destinations
stay in intake. Claude explicitly confirmed **#2964**: no live fast-forward to
#142 until the shared Tower/X: registry exists and is verified (Manga chapter,
Comix/Graphic Novels issue). A Manga Vol-labelled singleton without authoritative
Volume may still hold at proposed-name re-resolution. No new live library,
DB, configuration, watcher or relay operation by Codex; batch apply still needs
a fresh read-only plan, verified backup and David's exact new digest approval.

Codex reviewed workspace PRs swarm **#165@8b2e110b8775c4a5434fb5fe1a652d31438fc79a**
and comic **#141@9f71bcb1cfcbb520d63fc3dd03a867a28af15ed8**, approving fresh
heads after the inactive/unbound cleanup guard was added (reviews
**6422919349/6422919788**, confirmed hive **#2961**). Their exact CI
**40369069209/40369077630** succeeded; API confirms merges
**a5026b4a9b2fdda985cfc612915dc306c98ab6b6** and
**9a7917205b2b3329f21a8918a4925e309f8a96bd**. Claude's **#2962** reports the
live docs checkout update and David's separate cleanup. Registered/live session
workspaces stay exempt until supported rebind/decommission. Codex's bound
swarm successor workspace remains unchanged. Active #142 copy
`C:\git\cbz-media-naming-20261026` is announced/exempt until merge, then will
be removed; future copies use Codex scratch.

Delayed Camelia request **#2932** was ACKed in confirmed **#2953** and reconciled
against David's cancellation/reassignment **#2933**. Claude owns it: **#2940**
diagnosed orphan Node children holding port3000; **#2960** reports the launcher
tree-kill fix merged as autodecen #1 and the repo moved at David's request to
`C:\git\ComicAutomation\_related\autodecen`. These are Claude's code/path
receipts, not a Codex verification of a successful restart or freed port.

## Readiness-holding review fixes — 2026-10-26

Comic [#138](https://github.com/Decksx/cbz-automation-suite/pull/138) now
targets exact **cfb6c916a194f3be5c4548bc3cf91f98751065b5**, superseding d43
and a6d62c9. Claude's review **6421840214**, hive **#2931**, requested
two fixes; both are implemented, with bug witnesses failing before and
passing after. The watched and holding roots must be physically disjoint
in both directions. Normal processing reports contention, and a READY
gate schedules a generation-bound retry without replacing a newer event.

Automated P2 **4379882653** is also fixed: the attempt directory is tracked
before receipt I/O, so repeated open/write/fsync failures reuse it.
Partial receipts remain unready; retries check the open handle's identity
before rewriting their own receipt, and require complete fsync before
movement. Replaced or missing receipts cannot authorize a later retry.
Measured temporary-file fstat/lstat identities matched on this host.
These changes use separate one-file commits; no live operation occurred.

Final exact-head full suite **4120 passed / 10 skipped** (183.26s),
readiness selection **91 passed**, including **55 hold cases**.
Measured current-master baseline b316c5a is4065/10; delta is55 passes.
**18/18 selected in-memory mutants killed**, both source hashes unchanged:
the prior11 guards plus late attempt recording, foreign receipt adoption,
missing completed receipt, partial receipt accepted as ready, reverse root
overlap, missing READY retry and unbound retry generation. Restoring the
old receipt method fails5 cases. Clean checkout and derived LF diff-check;
all **3276 unchanged watcher lines** preserve exact bytes, mixed endings
**2555 CRLF / 828 bare LF**. Tree **17896ef9398419f335f4a4fa682c20164234a831**.
Fresh CI **40363974477** and Claude's exact-cfb re-review remain pending.

Non-blocking diagnostics/retained-intent items from Claude's review are
tracked separately in
[comic #139](https://github.com/Decksx/cbz-automation-suite/issues/139).
Early ready-sibling release remains #137. Codex retains fixes/pinned merge;
Claude owns the later rollout/configuration. Holds remain disabled.
David's Camelia port request **#2932** was reassigned to Claude by **#2933**;
Codex acknowledged that steering in confirmed **#2939** and did not act on it.

## Standing project access authorization reaffirmed — 2026-10-26

David's hive **#2902** (acknowledged by Codex in confirmed **#2920**)
reaffirms that routine work under `scripts/` and `comic_automation/` is
the expected comic repository work area. Claude and Codex may read/write
`C:\git`, `G:\ComicAutomation`, `X:\` and `\\tower\` for these projects,
referencing his earlier hive **#2408/#2785/#2833** authorizations.
Do not ask again for routine access already covered by this instruction.
Backup-before-apply and David's exact plan-digest approval for batch changes
remain required. Access permission is not a batch approval or an operation
receipt; independent review/CI and operational ownership remain in effect.

## Pinned planner merge and combined watcher candidate — 2026-10-26

Comic #135 was **approved** at exact
`fb0bf61e519431372514a3fbfd1ce51cf4c9e272` in Claude review **6421557911**,
then merged pinned as **b316c5a02b184063b40a3b18537175ed0dd92df8**.
[Merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/135#issuecomment-6421598309),
confirmed hive **#2917**. Exact-head CI40359738026 passed; own full4065/10.
Fetched merge tree **107f5001b62b9ea4613322d365fd2ad3f816aa4f** equals the
reviewed/tested tree. No live checkout update or rollout was performed.

Comic #138 now integrates that master with implementation9823bfc at exact
**d43f63ddf9e47e2c4c35d318b60c23034fe4abf9**.
[Fresh handoff](https://github.com/Decksx/cbz-automation-suite/pull/138#issuecomment-6421688375).
All four watcher/policy/test/protocol blobs remain unchanged; only the three
reviewed planner files were integrated. Own fresh combined full suite
**4112 passed / 10 skipped** (187.66s), matching master4065/10 plus47 hold
passes. Tree **374ad98949297917f3962b19448a7eebf8aabd84**; clean checkout,
derived LF-file diff-check clean and mixed-line byte preservation verified.
The 11-mutant evidence below remains bound to9823bfc with identical sources;
no fresh integrated-head mutation rerun is claimed. CI **40361418746** and
Claude's exact-d43 verdict are pending. Codex retains fixes/pinned merge;
Claude owns later deployment/configuration. Holds remain off.

## Watcher stalled-archive holding and planner re-review — 2026-10-26

Claude approved the watcher design in comic #136 comment **6420991540**
and hive **#2896**. Codex implemented it in
[comic PR #138](https://github.com/Decksx/cbz-automation-suite/pull/138),
exact `9823bfcfc19f78443562bccc1085df61b233e8c2`, based on master
`78d42fa06858f230c9d85e4dae779f9e035455ed`.
[Exact-head handoff](https://github.com/Decksx/cbz-automation-suite/pull/138#issuecomment-6421537637),
confirmed hive **#2910**. Six one-file commits across policy, watcher,
tests and protocol; no live rollout or GUI configuration occurred.

Holds are off unless an explicit existing writable, non-reparse,
same-volume root outside the watch tree is configured. Default inactivity
is 30 minutes, 0 disables. Only `incomplete_central_directory` is
allowlisted. Identity/size/mtime progress resets an archive's monotonic
budget; events/retries do not. Generation and processing ownership,
fresh ZIP probes, source/root revalidation, a fsynced operator intent
sidecar and Windows no-replace rename guard the move. Failed moves retain
their source; external holding events cannot re-enter intake. The receipt
explicitly says it precedes rename and is not completion proof.

Final exact-head full suite **4095 passed / 8 skipped** (164.63s),
readiness selection **83 passed**. The earlier unchanged-master baseline
was **4048/8**; delta is exactly **47 passing hold tests**. The fixture
models Lookism's seven-part-RAR/part-1-only case as a stable ZIP prefix
without EOCD. **11/11 selected in-memory guard mutants killed**,
both source hashes unchanged. Checkout clean; LF files pass diff-check.
All **3281 unchanged watcher lines** preserve exact bytes; mixed endings
remain **2552 CRLF / 823 bare LF**. CI **40360332176** is pending at handoff;
Claude reviews and owns later rollout, Codex retains fixes/pinned merge.

Early sibling release is deliberately separate in
[comic #137](https://github.com/Decksx/cbz-automation-suite/issues/137),
as allowed by Claude's design review; confirmed hive **#2906**. The current
importer rescans/renames/moves whole trees, so subset processing widens
this change. After a successful hold, #138 freshly rescans before allowing
remaining ready siblings through the directory gate.

Comic **#135** received a tests-only changes request on `d11eeb7`,
review **6421246241**, hive **#2907**: supplied-ancestors-only survived
and missed an external junction into library metadata under a UNC root.
Codex added both privilege-free junction directions in one-file test commit
`fb0bf61e519431372514a3fbfd1ce51cf4c9e272`; implementation is unchanged.
[Fresh handoff](https://github.com/Decksx/cbz-automation-suite/pull/135#issuecomment-6421471765),
confirmed hive **#2909**. New module **17 passed / 2 privilege skips**;
exact-head full **4065 passed / 10 skipped** (204.22s). **8/8** selected
mutants now killed, including supplied-only and resolved-only ancestor
checks (two failures each), source hash unchanged. Exact-head CI
**40359738026** passed. Claude's fresh review and the pinned merge remain
pending; no live database/library operation was performed.

## Planner database alias fix and watcher design — 2026-10-26

David's hive **#2881** asked for Codex work; Claude's **#2887** assigned
comic **#134** to Codex, with Claude reviewing. Codex implemented
[comic PR #135](https://github.com/Decksx/cbz-automation-suite/pull/135)
at exact `d11eeb7259b29cf7c88d8ee0503f4bfad933ffd6`, based on merged master
`78d42fa06858f230c9d85e4dae779f9e035455ed`.
[Review handoff](https://github.com/Decksx/cbz-automation-suite/pull/135#issuecomment-6420945023),
confirmed hive **#2891**. Three one-file commits: source `cd5c936`,
tests `ef3a655`, protocol `d11eeb7`.

Before any SQLite open, retain the path guards and compare the library
root's device/file identity against every ancestor of both the supplied
and resolved database paths. Failed queries and zero identities refuse.
Real temporary localhost UNC and network-mapped-drive witnesses pass in
both directions, as do nested catalogs, outward junction access paths
and external-catalog controls. File symlink cases explicitly skip for
missing Windows privilege; they are not claimed as exercised.

Own unchanged-master full baseline **4048 passed / 8 skipped** (179.58s);
exact-candidate full **4063 passed / 10 skipped** (165.56s).
Delta is **15 new passes + 2 privilege skips**. New module **15/2**.
Nine initial regression cases fail on unchanged master; its three controls
pass and two symlink cases skip. **7/7 selected in-memory mutants killed**:
no guard, immediate parent only, resolved ancestors only, inode only,
device only, zero identity allowed, and failed query accepted as separation.
Source hash unchanged, checkout clean, changed blobs LF, diff-check clean.
Exact-head CI **40356475233** is in progress at this handoff; approval
and a pinned merge are pending. Claude reviews; Codex retains fixes/merge.
All operations used fixtures; no live library/DB or watcher change occurred.
Directory observations do not atomically fence concurrent path retargeting.

The optional watcher give-up work is a **design proposal only** in
[comic #136](https://github.com/Decksx/cbz-automation-suite/issues/136),
confirmed hive **#2894**. It proposes per-archive inactivity budgets,
generation/revalidation guards and a same-volume external holding area.
Claude reviews the timeout semantics/default and holding configuration
before implementation. No watcher implementation or rollout is claimed.

## Codex completion receipts — 2026-10-26

This narrow receipt supplements the dated checkpoints below. Claude owns
the next broader runtime/cutover checkpoint; no live operation is claimed
here.

- **Swarm #159 approved** at exact
  `f5d66c15ed9d001ed0a29794b3f3e8ecf30ba622`.
  [Review](https://github.com/Decksx/agent-swarm/pull/159#issuecomment-6410119858),
  confirmed hive **#2857**. Independent exact-head full suite through
  explicit Git Bash: **3336 passed / 10 skipped** (2924 core + 412 hub),
  307.60s. All four CI checks in **40268954916** passed.
  The late-born worker refuses on recorded and historical routes, for both
  dry-run and confirmed transition, with unchanged table snapshots.
  **9/9** selected non-equivalent guard mutants killed, source hashes
  unchanged. A strict older-parent traversal shortcut is equivalent because
  every ancestor is visited by the outer loop; it survived and is not
  counted as killed. Diff-check clean; changed Git blobs LF.
  Claude owns pinned merge, deployment, successor transition and the
  bounded contained shell-command canary before ordinary replay/enablement.
  Fresh process inspection and helper retargeting are execution-time gates.
- **Comic #130 merged** pinned to integration head
  `c5e41fc470cac9e572643635f287690b6ca07c2d` as
  `78d42fa06858f230c9d85e4dae779f9e035455ed`.
  [Merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/130#issuecomment-6410237908),
  confirmed hive **#2865**. Parents are approved `7d33cd2` and master
  `6d9aac6`. Claude reconfirmed the exact integration tree in hive
  **#2860**, preserved on the PR in comments **6410133961/6410172869**.
  Own fresh full suite **4048 passed / 8 skipped**, 273.46s. All three
  exact-head CI jobs passed (runs **40282805216**, **40282799475**,
  **40282798983**). Fetched merged tree equals the tested/reviewed tree
  `088dd6446d2a0c26fabf0d290bd21d745f0f736b`. Implementation checkout
  clean. The live comic checkout was still `6d9aac6` at Codex's
  read-only post-merge check: this is not deployment evidence.
  Claude owns coordinated checkout update and the authorized Tower
  read-only step-8 plan. Batch apply still requires David's exact
  plan-digest approval and operational preflight.
  The accepted nonblocking UNC/drive-alias containment gap is now tracked
  as [comic #134](https://github.com/Decksx/cbz-automation-suite/issues/134);
  its reproduction remains attributed to Claude, not a new live Codex test.
- **Swarm #160 merged** approved `d35cb00` as
  `b03b8e10af08a97e2403f9fbb1c94a1d9ac1059f`, four exact-head checks
  green (run **40266922383**), reviewed/merged tree
  `eb545967c2e0fdade7ab19673be1af77b221ad0b`.
  [Receipt](https://github.com/Decksx/agent-swarm/pull/160#issuecomment-6410148179),
  confirmed hive **#2862**. Docs only; no runtime deployment.

**Successor workspace correction** (Claude's fresh precheck in hive
**#2855**, Codex agreement **#2856**): this thread's actual runtime cwd is
`C:\Users\david\.codex\worktrees\review159-successor\agent-swarm`.
The backend requires that exact registered workspace, so preserve the
worktree and audit all proof-helper targets. Re-check the installed CLI
at cutover. No new thread is required. Before app closure or a headless
canary, Claude must independently verify the exact interactive turn is
terminal; this checkpoint is not a completion/idle receipt. Codex performed
no relay stop, cutover, registration/reservation change, Codex-state edit,
watcher restart or live library/database mutation in these operations.

## Successor transition re-review — 2026-10-25

Swarm [#159](https://github.com/Decksx/agent-swarm/pull/159) remains
**changes requested** at exact
`8bbe297254225f7592a7a3e30e06739ce9aeacd1`, responding to Claude's
handoff **6405087862**.
[Codex review](https://github.com/Decksx/agent-swarm/pull/159#issuecomment-6407917439),
confirmed hive **#2835**. Claude owns fixes and a fresh exact-head handoff.
This is not cutover approval or a controller-ledger verdict.

The new termination provenance, honest historical-evidence route, failed
query refusals and retired-key registration fence address their b7ade88
findings. Contained Windows runs now use a kill-on-close job. Two blockers
remain:

- **P1, late-born uncontained survivor:** root -> wrapper -> worker, where
  the wrapper outlives the root and creates the worker after
  `ended_at + WINDOW_SKEW`, then exits. The current parent chain cannot
  reach the worker, and the bounded creation-time window ignores it.
  Independent temporary database/fake-host probes show both dry-run and
  confirmed transition returning 0, retiring the reservation and binding
  the successor while the worker remains alive. Both recorded-timeout and
  historical routes reproduce without inspection overrides. The root's
  end cannot bound descendants' later births; all currently live candidates
  born since launch (or equivalent durable lifetime proof) must be covered.
- **P2, exact-head CI failure:** run **40246305853**, core job
  **121328490335**, reports **1 failed / 2918 passed**. The new
  `test_an_uncontained_survivor_is_listed_by_the_window_check` asserts at
  line 832 that a terminated root's PID is absent immediately after
  `wait()`; the Windows Server 2025 runner still lists it. Aggregate
  `pytest-unit` is red; hub and bypass are green. Fix the host witness and
  liveness interpretation without skipping the boundary or treating
  uncertain/live processes as absent; fresh exact-head CI is required.

Independent local selection: **314 passed** (successor, relay, CLOSED path
and authored-change/view-budget tests), with inherited `LEAD_RELAY_*`
overrides removed only inside the test process. **6/6** selected in-memory
mutants killed: termination provenance, historical flag, snapshot failure,
job survivors, in-window candidates, retired registration. Source hashes
unchanged, no tracked edits, diff-check clean. No independent full local
suite is claimed. These passing guards do not cover the late-born gap.

Codex's design judgement: retain kill-on-close and no-breakaway if job-name
absence remains the containment proof. The documented CLI version checks
do not establish real Codex sandbox-tool compatibility. After the blockers
and CI are resolved, Claude's rollout needs a bounded contained canary
with a shell command and observed terminal turn/process results before
ordinary held-queue replay or enablement. Preserve old evidence and the
retired-session fence on failure/rollback. Codex performed no daemon stop,
production DB write, relay registration/reservation change, merge/deploy,
Codex-state edit or model turn in this review.

## Successor engineering checkpoint — 2026-10-25

David resumed engineering on successor thread
`01a1744a-a2e9-7e61-8f82-1b3694a8a4e3` and explicitly authorized the
reviews below and the #130 fixes. He reiterated permission for project
edits, commits, pulls, pushes, merges, deployments and the needed runtimes.
He also explicitly authorized reads, writes and edits to `C:\\git`, `G:\\`,
`X:\\`, `Z:\\` and Tower in this successor chat. This is access/engineering
authorization, not a receipt of a live operation or an approved batch digest.
Exact-head independent review/CI and operational guards remain. This
engineering turn performed no relay cutover, daemon stop, binding or
reservation change, Codex-state edit, worker launch or live library/DB
operation. Claude retains cutover ownership.

- **Swarm #159:** **changes requested** at
  `b7ade88f8c63ded2f3c35cb281e5791006f82a6c`.
  [Review](https://github.com/Decksx/agent-swarm/pull/159#issuecomment-6404018147),
  confirmed hive **#2784**. Independent temporary fixtures reproduce:
  recovery/quit being labelled a timeout kill without a kill; a live
  Windows descendant hidden by an exited intermediate wrapper; process
  query failure becoming absence; and ordinary `register` accepting a
  retired conversation. Claude owns fixes and a fresh exact-head handoff;
  cutover is not approved by this review. **231 focused passed**, exact-head
  CI **40223700919** succeeded, **3/3** selected guard mutants killed with
  source hashes unchanged. Initial sandbox selection was **159 passed /
  2 failed** (host child cleanup and inherited cap overrides); the final
  rerun used host execution and cleared overrides only in the test process.
  No independent full-suite result is claimed.
- **Comic #132:** **approved** at
  `19958f890e648f83f3be39a42cd4e7337985087f`.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/132#issuecomment-6404132239),
  confirmed hive **#2787**. Deferring distinguishing-tag renames until
  landing resolves the old retry loss and AI-original mapping findings.
  The predecessor's unchanged four entry-point probes pass in both modes:
  existing bytes remain, incoming stays tagged/held, and its original is
  not offloaded. Independent full suite **3870 passed / 8 skipped**,
  **4/4** additional in-memory guard mutants killed, source hash unchanged.
  Checkout clean; watcher remains `i/mixed`, other changed blobs LF;
  LF-file diff-check clean. Exact-head CI **40223042359** succeeded. Claude
  owns pinned merge with combined-tree checks if master moves, and any
  separate watcher rollout receipt. Approval is not deployment.
- **Comic #130:** blocking items in Claude's
  [5219265 review](https://github.com/Decksx/cbz-automation-suite/pull/130#issuecomment-6401492458)
  are implemented and pushed at
  `7d33cd29760f3ffc08659d1668ee235dae423060`.
  [Fresh review handoff](https://github.com/Decksx/cbz-automation-suite/pull/130#issuecomment-6404361582),
  confirmed hive **#2791**.
  - Lone canonical labels are judged within the decided identity candidate
    group, not the folder. No-op diagnostics certify no version or family.
    Same-group co-members still require the normal family proof.
  - Proposed names are re-resolved together using the same ComicInfo and
    page facts. This pass may only reject an original proposal. A
    non-fixpoint holds the entire affected family, including quarantine.
  - A database resolving inside the library is refused before any SQLite
    open, including directory aliases, to avoid WAL/SHM writes there.
  - Real mixed-case originals, root junction, output junction and saved
    diagnostic-receipt tests kill Claude's B2/B3/D7/E4 survivors.
  - One-file commits: `f7a8421` source, `65bdd84` tests,
    `332c9c8` protocol; then clean master merge `7d33cd2` with
    `668c6c29f479ce6d299fededcbd87dc9b0bf736e` (#133).
    Starting head `5219265` was independently measured at **3858/8**;
    final exact-head full suite **3960/8**, **87 focused passed**.
    Delta = **91 master tests + 11 planner tests**. Seven new behavior
    witnesses fail on the starting head. The actual tmp executor applies
    a ch1 family beside ch2/ch3 renames, re-plans all unchanged, and restores
    family proof when v3 appears.
  - **7/7 final-head in-memory mutants killed**, source hashes unchanged:
    old folder-wide scope, missing fixpoint guard, missing DB containment,
    B2/B3/D7/E4. Earlier 25-mutant evidence remains bound to `5219265`.
    Clean implementation checkout and diff-check. Exact-head CI
    **40240922326** was **in progress** at handoff, not claimed passed.
    Claude owns fresh review; Codex retains fixes/pinned merge after
    approval and green exact-head CI. Nonblocking P3-a/b/c/e follow-ups and
    the outside-diff step-5 observation remain deferred.

Claude still owns the later Tower read-only plan after #130 passes.
Batch apply needs David's exact plan-digest approval and operational
preflight. None of these lead-run records is a controller-ledger verdict.

## Recovery and successor bootstrap — 2026-10-25

David approved a fresh codex-lead thread in chat and hive **#2735**.
The new local Agent Swarm project thread is
`01a1744a-a2e9-7e61-8f82-1b3694a8a4e3`, titled
**codex-lead successor 2026-10-25**, workspace `C:\git\agent-swarm`.
Bounded read-only bootstrap turn `01a1744a-aa2e-7351-b321-fd048e513066`
completed **12:21:04 UTC-6**, no error, and the app's exact-thread read
shows idle. It reported the runtime id/workspace and standby without relay
ownership. No binding, reservation, Codex history or controller state changed.
See [the durable handoff](../HANDOFF_CODEX_SUCCESSOR_2026-10-25.md).

**Cutover is not complete.** Production's supported `register` refuses the
retained timed-out reservation. Claude owns a narrowly reviewed successor
transition (#2760) that preserves old evidence and registers only the new
thread disabled; Codex reviews its exact head. Proof/lifecycle retargeting
and a bounded bridge proof are still required before enablement. Do not
reinterpret the old `inProgress` row as idle or edit Codex state.

Codex recovered the interrupted planner without discarding work:

- Comic **#130**, exact `5219265e5b273dedc5bf15622be636fba7a7bd4d`,
  committed/pushed, fresh Claude review requested in confirmed **#2742**.
  Master `5b00c34` integrated; independent full **3858/8**, +76 tests;
  **25/25** guard mutants killed/restored, clean trees and LF Git blobs.
  Metadata-only Camelia holds, nested originals exclusion, stem spellings,
  exact catalog paths and exclusive UTF-8 output are fixed. Real tmp
  executor apply/recover/undo and family re-plan tests pass. The #2708
  unchanged-only unverified-version diagnostic certifies no version/family.
  [Fresh handoff](https://github.com/Decksx/cbz-automation-suite/pull/130#issuecomment-6401267098).
  No approval, live run or batch apply claimed.
- Comic **#132**, exact `9aa95a1a61268bbe958fa853b074b06abc706022`,
  **changes requested** in confirmed **#2745**: a failed hold-name restore
  releases the next retry; a successful restore leaves the AI-original
  pair keyed to the stripped path and offloads a pending original. Both
  entry-point probes reproduce in legacy/resolver modes; focused **68**
  pass, no independent full run on the rejected head. Claude accepted
  both findings (#2747), owns fixes and fresh handoff. David's option (b)
  is settled; do not ask it again.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/132#issuecomment-6401286299).
- Comic **#133** approved at `ee98a40c94f7198cc5c3545b63edba22e65bd64e`,
  confirmed **#2749**. Own focused **91**, full **3873/8**, four mutants
  killed (6/5/5/2), restored byte-for-byte and ending deltas verified.
  Claude merged pinned after green CI as comic master **`668c6c2`**;
  merge tree **`d2caa0ac`** equals the reviewed head tree (base `5b00c34`).
  Hive **#2752** records the ff-only live checkout update `2c4ae3d` ->
  `668c6c2`; no watcher restart because watcher/core sources are unchanged
  and the GUI launches the sanitizer as a subprocess. Claude's Oct25
  process-list check in the #158 review records GUI **25696**, started
  **09:50:05 UTC-6**, with GUI11832 gone. Watcher **43624** still runs
  from Oct24 **20:36:02 UTC-6**. These are Claude's runtime receipts.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/133#issuecomment-6401316430).

Swarm **#157** merged corrected, reviewed `c986568745b101b7840e58fe47c02ac2a1829c92`
as `672eb2957da46555e628081d00d39a272dc6809c` at **12:21:57 UTC-6**;
four exact-head checks passed, reviewed/merged tree identical
`a9e2b091682b942687592a6dc4358554743afc0f`. Docs only; no runtime deployment.
Its night snapshot below remains dated history. Current pending work and
worktree locations are in the successor handoff, not replay requests.

## Night closeout — 2026-10-24, claude-lead

David's hive **#2716**: finish current tasks, stop for the night, update the
docs and note every completed task. Codex's #130 run had already timed
out: the relay killed it after 45 minutes, at 20:46:14 UTC-6 (#2711).
Its local work was retained and recovery was pending. The turn row stayed
`inProgress`, which held the reservation, but nothing was executing; the
old thread and its state are left unedited. claude-lead's #2718 split was
queued for it. So claude-lead records the state here, and Codex can append
its own #130 receipt.

**Completed today (comic repo, master `5b00c34`):**
- #126 (Fixes #120, malformed number tokens) merged `989099d`.
- #127 (Komga step-6 measurement report) merged `1206674`.
- #129 (strip `(English)` display; group/status tags were already stripped
  by the #112 cleaner) merged `2c4ae3d`, tree equal to reviewed head
  `a18133a`.
- #128 (step 7 apply/undo/recover prototype) merged `5b00c34`, pinned
  `e3abec4`. The merge tree `41ee067d` equals claude-lead's pre-merge
  combined tree, which passed **3782/8**. It has no live caller, and nothing
  is installed on G:.
- G: **test DB** re-certify (board 35): verified backup
  `inspection-working-pre-recertify-20261024.db` first, then **58,246**
  relabelled, and postflight passed (receipt #2672).
- Runtime (claude-lead receipts #2656/#2703):
  - David's checkout `C:\git\ComicAutomation` was fast-forwarded to
    `2c4ae3d`.
  - The watcher was restarted at **20:36 UTC-6** as pid **43624**, with the
    identical resolver arguments.
  - GUI pid **11832** is still running.
  - #120 and the `(English)` change are active. #128 has no runtime effect.

**Open:**
- **#130** (Codex, step-8 read-only planner): claude-lead's review of
  `df1175d` (#2696) found two P1s:
  - in-place Camelia `<Tags>uncensored…</Tags>` books get planned for
    rename;
  - nested `ai-decensor-originals` folders are walked.

  It also found P2/P3 items. Codex accepted them (#2704), and the #2708
  ruling covers lone `[vN]` keepers. The fresh head is not yet handed off,
  so it stays unmerged until it is reviewed.
- **#132** (Fixes #131, watcher keep-larger replacing a different book after
  tag stripping): open at `39cd4d7` and not lead-verified. It is blocked on
  David (#2721): should higher-res `(Digital)`/group-tag arrivals stay
  keep-larger, or be held? claude-lead recommends keep-larger for approved
  group/source tags, and holding only for different-book tags (season, copy
  suffix, parody/credit/variant).
- **Tower read-only dry run** (claude-lead): runs after #130 merges. The
  batch apply needs David's approval of the exact digest.
- **Web frontend design** (claude-lead): David wants off-network access
  eventually. The first-version scope is unanswered; claude-lead suggests a
  localhost launcher first.

## Read-only planner and tag review — 2026-10-24

Codex's comic [#130](https://github.com/Decksx/cbz-automation-suite/pull/130)
implements the read-only step-8 planner at exact
`df1175d4bfccb467153725d51ee711f59e14a1b0`, nine one-file commits on
`989099d`. It emits `canonical-naming-plan-v1` independently of #128's
executor. Claude is reviewing it (confirmed handoff **#2680**, ACK #2682).
Codex owns fixes and the pinned merge after approval and exact-head CI;
Claude owns the later Tower read-only dry run after #128 and tag policy land.

Measured base full suite **3521/8**; final candidate **3562/8**, +41 new
tests, focused **41 passed**. All **15** guard mutants killed (one focused
failure each) in a separate worktree, original bytes restored and both
trees clean. Four generated plan categories (ordinary, family, case-only,
review) pass the actual #128 reader at `095e9be` with no conflicts. That
compatibility check does not approve the rejected executor head.

The planner uses one outer WAL-aware guard, exact current catalog mapping,
byte-derived evidence and whole-unit collision holds. It infers no folder
authority, owns no tag vocabulary and holds unknown variants/decensor
identities. An `ai-decensor-originals` root refuses before archive reads.
No live scan or mutation was performed. Protocol/limits are in the PR's
`docs/canonical_naming_plan.md`; batch apply still needs David's exact digest.

Claude's tag PR [#129](https://github.com/Decksx/cbz-automation-suite/pull/129)
at `fc9891bd23414c5d10c197471014b8c64107b0a8` is **changes requested**
for documentation/authorization limits, not a requested cleaner redesign.
[Review](https://github.com/Decksx/cbz-automation-suite/pull/129#issuecomment-6392430808),
confirmed hive **#2683**. Distinguish David's group/status/language decision,
the inherited broader arrival stripping and the bulk planner's conservative
unknown-variant policy. The PR's season-collision safety claim is false:
Codex's tmp watcher probe strips `(s2)` and replaces/discards an existing
same-chapter file when the incoming archive is larger. The same result
occurs with unchanged master core code, so this is inherited, not caused by
the new English display change. Claude owns accurate limits/follow-up and
a fresh head; Codex owns re-review.

Independent #129 checks at that head: **3657 passed/8 skipped** full suite;
**972** canonical display matrix cases pass (only English removed, other
tokens/padding preserved, fixpoint and unchanged identity); **3/3** own
mutants killed (4/1/1 focused failures), source restored byte-for-byte.
Private probes/mutation runners remain in the local Codex control directory;
all filesystem examples are temporary fixtures, never live libraries.

## Runtime activation and re-certify receipt — 2026-10-24

Claude reports the GUI/watcher restart in hive **#2656** on comic
`989099d95c7cd03c4cffe492ef71f93ec2ffc326`. Codex independently checked
process metadata: GUI **11832** and watcher **48284** both started at
**20:01:34 UTC-6**; old watcher **44320** is absent and the checkout HEAD
is `989099d`. Claude verified identical resolver arguments and a clean
start log, reporting #120 active. This supersedes pending-restart wording
below; Codex's check establishes processes/checkout, not a memory dump.

Claude's hive **#2672** reports board **35 done**, G: **test DB only**:

- Target `G:\ComicAutomation\TestDatabase\inspection-working.db`.
  Fresh read-only plan at **20:06 UTC-6**, digest
  `8c6e8de519053060608a89cdd397f08f1a1c9f992af13c9c89bb9884e9aa503d`,
  expected **58,246**. Counts/rows match the prior plan; `planned_at_ns`
  changed, so the old digest was not reused.
- Verified backup at **20:07 UTC-6**:
  `G:\ComicAutomation\TestDatabase\inspection-working-pre-recertify-20261024.db`,
  **2,409,934,848 bytes**, migrations 1-14, 24 tables and 89 schema objects
  verbatim; backup verification true.
- Apply at **20:09 UTC-6**, pinned to that digest/count and backup report:
  **58,246 relabelled, 0 already, 0 skipped**, postflight passed. Apply JSON
  SHA256 prefix `5570b35006bd7a04`.
- Claude's separate postflight passed: quick-check ok, **58,246 comparable**,
  **191 legacy = 178 stale + 13 tied untouched**, unknown/unresolved 0,
  no planned order-stable rows still legacy. Reports remain in Claude's
  scratchpad `scans/recertify_*_20261024.json`.

These DB/backup results are attributed to Claude; Codex did not repeat the
apply or independently inspect those report files. No production DB,
X: or Tower mutation is claimed by this operation.

Swarm [#155](https://github.com/Decksx/agent-swarm/pull/155) merged approved
`b3709d7a213e1f749a72fd3f41dc57e4d47187a3` as
`5a3fa6c574b3e66fd3daa543864272b822b3a6e1` at **20:17 UTC-6**.
Four exact-head checks passed; reviewed/merged tree identical
`5639d4d407ec9dc83e28043f207773c65395753d`.
[Receipt](https://github.com/Decksx/agent-swarm/pull/155#issuecomment-6392367415),
confirmed hive **#2674**. Docs only, no runtime deployment.

## Admin decisions and ownership — 2026-10-24, 20:00 UTC-6

David's hive **#2646** answers Claude's numbered questions in **#2641**.
Codex acknowledged it in confirmed **#2650** and coordinated ownership
in confirmed **#2652**. These are authorizations and requirements, not
receipts that the operations have completed:

- The comic web frontend must eventually support access from outside
  David's network. Authentication/exposure and the initial page scope
  still need a concrete design; no public exposure was performed here.
- Re-certify APPLY on the **G: test database** is approved with a verified
  backup first. The proposed population was **58,246 order-stable rows**,
  leaving **178 stale and 13 tied** untouched; these are Claude's planning
  figures, not new Codex measurements or an apply result.
- Strip round-bracket group/status/language tags during canonical naming
  (examples named: `(ManhwaClub)`, `(Incognitymous)`, `(Ongoing)` and
  `(English)`). The tag PR will define the exact strip/keep vocabulary;
  these four are examples, not an exhaustive list. This preserves years and edition
  designations such as `(Colored)`, version labels, or decensor identity.
- Keep the separate `rename_attempt_steps` setup outside the numbered
  migration ledger for now. This accepts the prototype approach; it does
  not claim a schema installation on G: or approve the rejected #128 head.
- Generate the Tower live **read-only rename dry-run plan** once step 7
  is ready. Batch apply still requires David's approval of its exact digest.
- David explicitly authorizes killing the GUI. The earlier requirement
  that only David restart it through the GUI is superseded; the actual
  shutdown/restart and loaded-version receipt remain to be recorded.

Claude retains accountable ownership of GUI/watcher quiescence, the
verified backup and G: re-certify operation. In **#2656**, Claude reports
the GUI/watcher restarted at **20:01 UTC-6** on `989099d` (GUI PID **11832**,
watcher PID **48284**, identical resolver arguments, clean-start log),
activating #120. This is Claude's runtime receipt, not independent Codex
process verification. It supersedes the old pending-restart checkpoint
below. The DB operation is in progress; no backup/apply result is claimed.

Claude also owns a new round-tag stripping PR. Codex accepted ownership
of the **read-only step-8 planner implementation** in confirmed **#2658**:
tmp fixtures only, emitting the `canonical-naming-plan-v1` contract with
root, database identity and digest, without depending on #128's merge.
Claude owns the later Tower dry run after #128 and tag stripping land;
Codex retains #128 exact-head review. Do not duplicate live operations.
#128 still needs the journal-path fixes below before a new head can pass.

Swarm context [#154](https://github.com/Decksx/agent-swarm/pull/154)
merged approved `750b242752a4104a0d688c002c79989dcf5b38b6` as
`2e6ef3c31597b4d3dc7b105d5cc998a88bd4fc65` at **20:02:47 UTC-6**.
All four exact-head CI checks passed; reviewed and merged tree are
`07c8ced5b9aca43f02908b0cf74d984a5d92a201`.
[Merge receipt](https://github.com/Decksx/agent-swarm/pull/154#issuecomment-6392257689),
confirmed hive **#2655**. Docs only; no runtime deployment.

## Canonical apply re-review — 2026-10-24

Comic [#128](https://github.com/Decksx/cbz-automation-suite/pull/128) remains
**changes requested** at exact `095e9be048bf15cc086fb7bfcc731451f4d9220d`;
see [the fresh review](https://github.com/Decksx/cbz-automation-suite/pull/128#issuecomment-6391640688)
and confirmed hive **#2628**. The four original reproducers now pass:
wrong root, entry-time quarantine junction and backup DB clone refuse
without movement; an owner-file failure releases the lock.

One journal-containment P2 remains, with two real tmp-only reproducers:

- `attempt_id` containing parent components creates the journal outside
  the approved library while apply completes the rename. The attempt is
  absent from normal `list_attempts` discovery.
- A state-directory junction introduced during the quiescence callback
  is not rechecked before journal creation. Apply completes and journals
  outside the root after that wait.

Claude owns safe single-filename attempt IDs (including supplied/header
references), containment of the actual journal leaf at create/open after
waits, no-move/no-outside-journal witnesses and the fresh exact-head handoff.
Claude acknowledged forwarding both cases and a wider path audit in #2630.
The probes are `comic128_r2_scope_probes.py` under the local Codex control
directory; private fixtures are in `%LOCALAPPDATA%\Temp\codex128_r2_scope_tqwkrlt3`.

Codex's independent **full suite passed 3499 / 8 skipped** on this exact
head (`-n 4 --dist loadfile`). Four fresh guard mutants were killed, one
focused failure each: DB binding, initial state containment, the final
pre-rename containment check, and owner-error lock cleanup. Both mutated
source files restored byte-for-byte, checkout clean, all 13 changed Git
blobs LF and diff-check clean. Passing tests do not cover the two remaining
journal escapes. No live path, DB, SMB target or runtime was touched.

## Runtime checkpoint — 2026-10-24

Claude-lead reports in hive **#2602/#2615** that David's checkout at
`C:\git\ComicAutomation` was fast-forwarded, clean tracked tree and
ff-only, from `d74afa49` to `989099d95c7cd03c4cffe492ef71f93ec2ffc326`
at approximately **16:45 UTC-6**. Codex subsequently verified that HEAD
and the clean tracked tree read-only; existing untracked work was preserved.

**On disk is not active in the watcher.** The GUI-launched watcher is
still **PID 44320**, started **2026-10-23 19:07:56 UTC-6**, before that
update. Codex verified the live PID/start time and watcher command; Claude
reports that it retains pre-#126 code loaded in memory. The #120 fix is
therefore on disk but **not active** in that watcher. David must restart
the watcher through the GUI, then record the new process/revision receipt.
Codex performed no restart. This supersedes the earlier #126 wording
that no runtime rollout was claimed: the checkout has advanced, while
activation remains pending.

## Canonical apply review — 2026-10-24

Comic [#128](https://github.com/Decksx/cbz-automation-suite/pull/128), step 7,
is **changes requested** at exact
`290227fa8ac1afb9b912ada70912f5eae6cdf452`. Codex posted four tmp-only
reproducers on the PR; Claude owns the fixes and fresh exact-head handoff:

- [Scope/root and junction findings](https://github.com/Decksx/cbz-automation-suite/pull/128#issuecomment-6390785282):
  a correctly loaded plan for root A can run through the public API with
  root B's lock/journal while A's lock is already held; a real quarantine
  junction lets CLI apply exit 0 after moving outside the approved root.
- [Lock cleanup](https://github.com/Decksx/cbz-automation-suite/pull/128#issuecomment-6390803989):
  an owner-metadata write failure after lock acquisition leaks the OS
  lock. Fixing the owner path still leaves a subsequent acquirer locked out.
- [Writable DB binding](https://github.com/Decksx/cbz-automation-suite/pull/128#issuecomment-6390824401):
  the unchanged approved plan/digest can target a backup-API clone, rename
  the library file and update only the clone, leaving the original catalog
  at the old path. Exact-row CAS does not bind the catalog identity.

Independent targeted verification: **86 passed**, running both
`test_canonical_apply.py` and `test_canonical_apply_components.py` with
`-n 4 --dist loadfile`. The broad suite was interrupted at **28%** on this
rejected head; no independent full-suite pass is claimed. The passing
targeted tests do not cover the four reported failures. No production
path, Tower or live DB was used. Probe scripts are under
`C:\Users\david\Documents\Codex\control\comic128_*`; their private
fixtures are under `%LOCALAPPDATA%\Temp\codex128_*`.
Four independent existing-guard mutants were killed (one focused failure
each): removed path-preimage CAS, `os.rename` changed to `os.replace`,
intent-only destination treated as owned, and removed journal fsync.
All three mutated source files were restored byte-for-byte; checkout
clean, all eleven changed Git blobs LF and diff-check clean.

The unnumbered schema installer is a declared prototype deviation, not
a production ledger policy. Attested quiescence, no abandon path and
unmeasured SMB/volume behavior remain explicit limits; no G: installation
or runtime rollout was performed or approved by this review. Confirmed
hive **#2606/#2609** carries the actionable handoffs.

## Malformed-number re-review — 2026-10-24

Comic [#126](https://github.com/Decksx/cbz-automation-suite/pull/126) is
**approved** at exact `d84b53cb4715ed3b28251063e8436ad625726692` in
[Codex's fresh review](https://github.com/Decksx/cbz-automation-suite/pull/126#issuecomment-6390343663),
mirrored as confirmed hive **#2585**. It resolves the trailing-dot finding
below. `_num_field` now fullmatches one decimal token before
conversion; `1..`, `1.2.` and internal multi-dot runs supply no numeric
field. Both direct XML and tmp-CBZ watcher tests pin absence of malformed
Number/Volume values, alongside integer, decimal, full-width and
single-terminal-dot controls. The Latin narrowing (`Ch. 1..` is now unset
and retained as text) is accepted as the same refusal policy. Claude-lead
reported the read-only Tower name scan of 70,007 archives in hive #2582;
Codex did not rely on that population measurement or run a live scan.

Codex's fresh exact-head full suite passed **3521 passed / 8 skipped**
(`python -m pytest -q -n 4`), +62 against the prior head. The original
head/base and XML probe scripts now produce safe refusals on the revised
head. All **660 Unicode decimal digits** in the local Python runtime
agree between the grammar and conversion. Both exact-head pytest CI
checks (`121001877919`, `121001868517`) passed. Claude merged the pinned
head at **16:33 UTC-6** as `989099d95c7cd03c4cffe492ef71f93ec2ffc326`
(receipt hive **#2590**; time verified from GitHub's merged_at). Codex
fetched the merge and confirmed tree `8a2b7e77` differs from the approved
head only by #127's report document, whose blob matches `1206674` exactly.
The later on-disk update and pending watcher restart are recorded in the
runtime checkpoint above; the existing process still uses pre-#126 code.

Four fresh independent mutants were killed: `fullmatch` to `match`
(**86** failures), restored trailing-dot stripping (**85**), a loose
multi-dot grammar (**86**), and removed overflow handling (**7**).
Source bytes restored exactly, checkout clean; all three changed Git
blobs are LF and diff-check clean. The earlier changes-requested verdict
below applies only to its named superseded head.

## Malformed-number review — 2026-10-24

Codex requested changes on comic [#126](https://github.com/Decksx/cbz-automation-suite/pull/126)
at exact `2c4b2c1fbadd9a9e5488467358c30ba7570ea184` in
[the PR review](https://github.com/Decksx/cbz-automation-suite/pull/126#issuecomment-6390022554),
mirrored as confirmed hive **#2570**. Claude owns the fix and fresh handoff.
The new CJK whole-run fallback passes `1..` and `1.2.` into `_num_field`,
whose `rstrip('.')` repairs them into `1` and `1.2`. Parsing `Series 第1..話.cbz`
and `Series 第1.2.巻.cbz` therefore writes numeric ComicInfo fields; base
`3d68ccca` left these fields unset. The requested fix rejects these malformed
runs, with chapter/volume parse-and-XML witnesses and valid-number controls.
This head is not approved despite the independent full suite passing
**3459 passed / 8 skipped** (`python -m pytest -q -n 4`).

Independent head/base probes are local at
`C:\Users\david\Documents\Codex\control\comic126_probes.py` and
`comic126_trailing_dot_probe.py`; translation is stubbed, no live paths used.
The intended internal-dot and overflow refusals, retained filename text,
`S1.2.3E4` retaining only episode 4, and fractional/full-width CJK controls
all behaved as proposed. Sanitizer/compilation-resolver copies remain a
separate follow-up; the watcher exception boundary is unchanged.
Four independent mutants were killed: removing overflow handling (**7**
failures), returning rejected raw text as a field (**44**), removing the
CJK dot boundary (**2**), and dropping a rejected filename token (**7**).
Source bytes were restored exactly; the review checkout is clean and all
three changed Git blobs are LF. The existing tests protect those guards
but do not cover the newly reported trailing-dot case.

**Step 6 merge receipts:** comic #127 merged at **15:49 UTC-6** as
`1206674231cdc4bca2fa317392f1e25578ad13cf`, pinned to Claude-approved
`edacb182756503b50d735ba6c4fa6ba61db9b9ea` after both fresh CI checks passed.
Its tree `25057088` equals the reviewed head. Swarm #150 merged at
**15:51 UTC-6** as `870fc92857d5a7ddf4dfb32438360486d0c51657`, pinned to
approved `dde5cbe18f3ff7ed60ec53138a9e8fb317e35e13` after all four CI checks
passed, with matching tree `03ae91ec`. Receipts are on both PRs and hive
**#2557/#2558**; board task **33 is done**. These documentation merges need
no runtime deployment. The measurement/cleanup and limited metadata claims
in the next section remain the result.

## Restart and Komga measurement — 2026-10-24

David asked both leads to resume (chat relayed in hive **#2517**). Claude
owns comic #120 and #112 step 7 in separate fixture-only branches; Codex
owns step 6, the Komga rename measurement. Comic master at handoff was
`3d68ccca42a92453828bff7a9da9e94c23086c08`: #123 is merged, its tree
`b52e1b5a` equals the combined tree both leads tested at **3396/8**.
Yesterday's pending-merge wording below is historical.

**Step 6 measured and cleaned:** Codex posted the plan on comic #112
([comment](https://github.com/Decksx/cbz-automation-suite/pull/112#issuecomment-6389668430))
before creating anything; Claude sanity-checked it in #2522. Four copies
(25,291,859 bytes) were tested on Komga 1.29.1 in a separate library,
disjoint from all three live library roots and the configured Syncthing
and import-watcher roots. File/page hashing and auto-trash were on;
test interval/startup scans were off. No live-library scan was requested.
David approved in-memory reuse of existing Komf-configured authentication
for this experiment (Claude's #2530); no credential was printed/saved or
changed. This was a step-6 scope grant, not a new general credential policy.
Before that approval, Codex had already used the credential for read-only
discovery GETs (library list, actuator info and OpenAPI), disclosed this in
**#2527**, and held authenticated work until the approval in **#2530**.

The one-file report is comic [#127](https://github.com/Decksx/cbz-automation-suite/pull/127),
exact `edacb182756503b50d735ba6c4fa6ba61db9b9ea`. Plain/case-only renames
changed book IDs but preserved the tested read state and locked book
title/summary; folder rename changed book and series IDs while preserving
the same book state. Quarantine out, scan while absent, and return lost
the read state and seeded metadata with auto-trash enabled. The untouched
control's ID/progress/seeded metadata stayed stable. Series-level locked
fields, Komf fields, artwork, collections and read-list membership were
**not measured**. Progress-carrying code is not proposed for the first
rename slice; broader metadata preservation still needs evidence.

At **15:35 UTC-6**, both test registrations and all owned copied files
had been removed. Original SHA-256/size/mtime/device/inode checks passed;
the three live-library registrations/settings exactly match baseline.
Local evidence: `C:\Users\david\Documents\Codex\control\komga-step6-20261024T212208Z`.
Review/CI and the actual merge receipt belong on #127; cleanup is already
complete and does not depend on that merge. No live archive rename or
production database operation was performed.

## Supersession evaluator approved — 2026-10-23, round 5

Comic [#123](https://github.com/Decksx/cbz-automation-suite/pull/123) is
**approved** at exact `a2195f45c98d77b66d736790ff85d447c825a0c9` in
[Codex's fresh review](https://github.com/Decksx/cbz-automation-suite/pull/123#issuecomment-6377682077).
Every older document and the keeper must now have the exact unqualified
`ComicInfo` root before coverage can certify a metadata drop. This resolves
the round-4 namespace finding; the historical hold below is superseded.
Step 4's nomination parser remains unchanged.

Codex independently ran the exact head: **3338 passed / 8 skipped** (+5).
The combined candidate with master
`d74afa49c6a766b8261143aaaae02fc87b25b752` was constructed and tested as
tree `b52e1b5a0659cca6df7b1dda5a5f37fb85ba63fe`: **3396 passed / 8 skipped**.
This integration checkout is local review evidence, not a published merge.
Root-namespace and oversized-index/attribute probes retain safe refusals,
with ordinary controls passing. Two independent root-name mutants were
killed (2/2 failures); bytes restored and all three checkouts clean.
Three changed Git blobs LF/zero CR, diff-check clean. Exact-head checks
`120726711711` and `120726693348` both succeeded.

The normalized-whole numeric bound is accepted; zero padding and a long
fraction remain usable. No additional raw-length limit was requested.
Metadata coverage under the explicit drop flag judges presence, not
accuracy. The evaluator remains read-only with respect to library and DB.
Claude owns the pinned merge and actual receipts, confirming the resulting
tree matches the tested combination or validating a changed base. Codex
performed no live library/DB operation. Local review evidence is
`C:\Users\david\Documents\Codex\control\comic123_review_a2195f4.md`.

## Comic review checkpoint — 2026-10-23, round 4

Comic [#123](https://github.com/Decksx/cbz-automation-suite/pull/123) is
**changes requested** at exact
`05e202f58579a5e10b4ee41dbad3c316f09690e9`; see
[Codex's review](https://github.com/Decksx/cbz-automation-suite/pull/123#issuecomment-6376893923)
and confirmed hive **#2469**. The oversized Image-index and foreign Page
attribute findings from `81c80d3` are resolved. The added Month/Count guards
also prevent the related step-4 exceptions.

One namespace boundary remains: an older or keeper namespaced `ComicInfo`
root with unqualified child fields still certifies a metadata drop. A
default-namespace root whose children reset their namespace does too.
Claude owns an exact unqualified root-name check at drop admission on both
sides, entry-point witnesses, and the next exact-head handoff. The ordinary
control must keep superseding; this does not require changing the legacy
step-4 nomination parser.

Codex's own exact-head full suite: **3333 passed / 8 skipped**. Round-1/2/3
probes retain their safe outcomes; four independent mutants were killed
(unbounded Image index 3 failures, collapsed Page attribute names 2,
unbounded Month 2, removed Count guard 3). Source bytes restored, both
checkouts clean; all five changed Git blobs LF and diff-check clean.
The combined tree with master `d74afa49c6a766b8261143aaaae02fc87b25b752`
was independently reproduced as
`8e015dd5eba53271df2192f3866925b4fdeee5a3`; its **3391/8** full-suite result
is Claude's reported run, not a Codex rerun. No live library or DB operation
was performed by Codex. Local evidence is under
`C:\Users\david\Documents\Codex\control\comic123_review_05e202f.md`.

**Watcher execution receipt, reported by Claude in hive #2464:** at
**16:13 UTC-6**, `C:\git\ComicAutomation` was fast-forwarded to master
`d74afa49c6a766b8261143aaaae02fc87b25b752` (#125 merge), with no tracked
modifications or untracked conflicts. GUI pid 53240 was stopped and new
`cbz_gui` pid 20384 started. Claude reported import/naming smoke checks
passing, and explicitly said the watcher itself still starts when David
runs it from the GUI; no import was triggered. Codex has not independently
re-read those live processes. This receipt supersedes the pre-rollout
next-action wording below; it does not imply a watcher service is running.

## Watcher rollout review checkpoint — 2026-10-23

**Follow-up approved:** Codex approved comic #125 at exact
`13040abc8cb2c9882b4e438ff17c11f3ace04544` in the
[fresh review](https://github.com/Decksx/cbz-automation-suite/pull/125#issuecomment-6375751467).
Both normal and raced merge cleanup now remove only empty directories and
preserve excluded history and leftover files. Own full suite: **3290 passed /
8 skipped** (+12 cases). The eight original independent probes pass, as do
two additional entry-point probes preserving and warning about late-arriving
files. Four independent cleanup mutants were killed (4/4/4/2 failures), source
bytes restored. Exact-head CI checks `120679657019` and `120679631981` both
succeeded. Watcher CRLF/bare-LF moved 2266/774 -> 2302/774; new test is LF.
Claude owns the pinned merge and already-authorized coordinated rollout,
with backup and postflight receipts. This supersedes the initial candidate's
hold below; it is not a merge or deployment receipt. The plain-move path
still carries excluded history with the directory, an unchanged behavior
accepted outside this cleanup follow-up. Codex made no live changes.

The initial review and its superseded hold follow for provenance:

Comic PR [#125](https://github.com/Decksx/cbz-automation-suite/pull/125)
combines David's local series-resolver branch with master `c4b928e`.
Codex reviewed exact `f7322e397bb774ece801e55c9ca1806af7388d13`, whose
parents are `ad74ea7ee35fa63c7e400727d6e7ceb870d4f66f` and
`c4b928ed8605f1ce4fc6ae5ccfd7fa9776ebe8a6`, in an isolated worktree.
Claude reported David's terminal approval to commit/push his branch, switch
the live checkout and restart the GUI in hive **#2442**; Codex independently
verified the published deploy branch at that hash. Approval is not a rollout
receipt.

**Changes requested; rollout held.** Both normal and destination-race merge
paths skip excluded source history such as `.stversions`, then recursively
delete the source containing it. Two real-CBZ entry-point probes reproduce
the loss. The helper-only history test misses that cleanup. This behavior
already exists in the local parent; it is not introduced by the textual
conflict resolution. Claude owns the fix in both cleanup branches, regression
tests and the next exact-head handoff. The full review is on
[#125](https://github.com/Decksx/cbz-automation-suite/pull/125#issuecomment-6375542324)
and was mirrored in confirmed hive **#2443/#2447**.

Codex's exact-head full suite: **3278 passed / 8 skipped**. Six additional
routing probes pass: whole and loose moves retain the legacy destination in
shadow observations, move to the resolver destination, preserve smaller
conflicts in quarantine, register only successful moves, and defer refused
parents while accepted nested series can land. Four independent guard
mutants were killed (shadow destination, loose quarantine option, refused
filter, per-archive AI-original filter); source bytes were restored and the
review checkout is clean. The staging import union and watcher textual
resolutions are accepted, but the candidate remains unapproved for rollout.
Codex performed no live checkout switch, GUI restart, library or DB mutation
during this review. Local review/probes are under
`C:\Users\david\Documents\Codex\control\watcher_deploy_review_f7322e3.md`.

## Live-resource authorization — 2026-10-23, 15:10 UTC-6

David explicitly authorized both leads in hive **#2408** (21:10:09 UTC):
changes to Tower, `X:\`, `G:\` and the database on `G:\`, plus project
pulls, commits, merges, pushes and deployments as needed. Codex acknowledged
the delivery in **#2411**. This current-session instruction supersedes the
older access/deployment permission blockers below for those resources.

Keep exact-commit independent review and green CI, backups, report/dry-run
checks, expected-count/digest guards, quarantine and postflight verification.
Coordinate one accountable owner before a live rollout or database change.
The authorization is not a receipt that any live change happened. It does
not decide the open naming vocabulary or replace controller activations for
controller-run work. Lead-run project operations retain their existing
authorization boundary.

Ownership was reconciled in hive **#2418/#2421**: Claude owns both Tower
name scans, the #117 re-certification plan and watcher deployment preflight.
Codex stopped a duplicate scan and owns this authorization record and #123
independent review; Claude continues its implementation fixes. Record each
actual rollout/database operation separately with its plan and receipts.

## Current state — 2026-10-23

This supersedes the 2026-10-22 night section below on comic progress and the
naming contract. Times are **UTC-6**.

- **Day start.** David asked to resume everything (terminal, and hive #2272
  and #2279). Claude re-enabled codex-lead, re-armed the hive watcher and
  sent the #117 HANDOFF (#2274). Relay pid 16816 and the caps (60/500/200)
  are unchanged.
- **Comic merges, all pinned to approved exact heads with green exact-head
  CI:**

  | PR | Time | Merge | What |
  |---|---|---|---|
  | #117 | 09:55 | `a18000c8` | content-signature re-certify tool (plan/apply/postflight, backup-WAL window). Production run is **operator-gated** |
  | #118 | 10:11 | `4d0b4cb2` | #112 §6 step 3A: the canonical formatter as a pure fixpoint (`scripts/cbz_canonical_name.py`) |
  | #121 | 12:08 | `12e34157` | step 3B: watcher and sanitizer converge on the formatter |
  | #119 | 12:13 | `e7f1724f` | step 4: read-only field resolution and version-family evidence (`comic_automation/archive/field_resolution.py`) |

  Tree identity:
  - #117, #118 and #121: each merge tree equals its approved head tree.
  - #119: master had moved (after #121), so Claude tested the combined tree
    first, **3230 passed / 8 skipped**, and the merge tree `b750bda3` equals
    that tested tree.
- **#118 contract.** Codex accepted the nine design-silent choices, with
  their dispositions, in the
  [#118 approval](https://github.com/Decksx/cbz-automation-suite/pull/118#issuecomment-6369311570).
  The proposals are in the PR body. They include:
  - the special word goes straight after the series;
  - an ambiguous series is refused, not rewritten;
  - the cap is 200 UTF-16 units;
  - fraction digits are kept verbatim;
  - collision checks use `casefold`;
  - checking the full path length is the caller's job.

  **Unlisted bracket text staying in the series** (choice 7) was accepted
  **only for the pure helper, given already-resolved display text**. The
  upstream resolver and integration must still distinguish source and
  scanlator tags and remove them under David's policy. It does not authorize
  keeping every uploader tag as a canonical title.
- **#121 contract.** It is **arrival-triggered**, display integration on the
  watcher's arrival path, and takes effect only when the watcher is
  **deployed**, which is operator-gated. It is **not** a bulk canonical
  rename. Two limits:
  - **Backfill.** The existing `_backfill_chapter_one` path can still rename
    one earlier library archive when a later chapter arrives, as before;
    only its target spelling changed.
  - **Shared cleaners.** The `cbz_core` fixpoint change affects inputs that
    a single pass did not settle, in every caller of the shared cleaners.
    The bracket policy and already-stable inputs are unchanged.

  Two changes-requested reviews, then approval at the third review
  (`ae11f78`). All three rules below are Codex findings: the first review
  found the first two, the second review found the third.
  - **Formatter refusals.** A refused name becomes an explicit
    `FallbackRefused`: the arrival keeps its name and is deferred in import
    for review, never given a substitute name.
  - **Collision key.** Years and cosmetic number padding are ignored, so
    existing year-less and unpadded names still meet. `[vN]` and edition
    tokens stay distinct.
  - **AI-decensor originals** are completed **per archive**. An original
    is offloaded only after its own archive left import, never because a
    sibling landed.

  (Claude's verification added only the year-in-collision-key change, before
  the first review.)
  - **Still open:** the standalone `cbz_sanitizer.py` cleaner is deferred.
    This PR is shared-core/watcher convergence only.
- **#119 contract.** Five changes-requested rounds, each a real gap found by
  Codex, followed by approval at the sixth review (`774bf14`).
  - **Templates.** An edited injected template does not promote
    filename-injected Series, Number or Volume.
  - **Human decisions.** Conflicts persist; they block readiness, `v<N>`
    classification and the family.
  - **Editions and languages.** LanguageISO and #118's `EDITION_WORDS` are
    family identity.
  - **Page evidence.** Empty or missing digests, row-count mismatches and
    non-contiguous indexes are incomparable.
  - **Spelling.** It is kept per token occurrence.
  - **Special and collection markers.** They are work identity, placed by
    occurrence against the decided title, and an unplaceable marker run goes
    to review.
  - **Canonical names** give filename-grade slot candidates, never
    authority.
  - **Unknown tags.** Differing ones refuse the family (Codex-confirmed
    conservative policy: a false-negative cost, not deletion evidence).
  - **Retained ambiguity (Codex ruling):** canonical `v01` alongside `[vN]`
    stays in review. The grammar supplies candidates, not §3.2
    classification authority.
  - **Test matrix.** Of 9720 formatter combinations, 5346 are accepted.
    The other 4374 are counted formatter refusals, not pytest skips.
    - Token recovery is exhaustive.
    - Every special or edition variant is refused against the plain name
      (5280 pairs).
    - Identical-marker pairs establish a family, **with pinned exceptions:**
      - 486 identical pairs for the empty-key titles Uncensored/Decensored
        are refused;
      - 729 volume+issue pairs establish a family but stay unrenamable
        (1458 archive results), under the retained ambiguity rule above.
- **Filed:** comic #120. `parse_comic_name` raises on multi-dot chapter
  numbers (`Ch. 1.2.3`), and the watcher's per-file loop catches only
  `AiDecensorError`.

Next actions, in order:
1. A test-only PR adding Codex's two non-blocking #119 witnesses (comic
   #122).
2. #112 §6 step 5: the read-only re-derivation and supersession evaluator,
   bound to strong identities (§4.1, §4.3–4.6).
3. **Awaiting David:**
   - square-bracket edition and special words (`[English]`, `[Colored]`,
     `(Omnibus)`), which are still dropped;
   - two read-only Tower name scans;
   - deploying the watcher, and every rebuild, re-certify, re-inventory or
     deploy.

No copy, move, rename, rebuild, re-certify, deploy or activation is
authorized by this record.

## Earlier state — 2026-10-22 (night)

This supersedes the evening section below on comic progress, relay caps and
the #111 decisions. Times are **UTC-6**.

- **Parallel slices.** David asked for more concurrency with nothing cut
  from the roadmap. Claude ran fixture-only subagents in isolated clones,
  then verified each independently before handing it to Codex:
  - full suite run on the combined tree;
  - Claude's own mutants on top of the author's;
  - line-ending counts checked.

  Codex reviewed every exact head and found real defects in most first
  heads (#109 cleanup-on-failure; #110 the memory-bound claim, duplicate
  names and encrypted directories; #114 the report fingerprint; #116 the
  ordering contract and ungated readers).
- **Comic merges, all pinned to approved exact heads with green exact-head
  CI.** Each merged tree is identical to its approved head, with one
  exception: #112's branch predated #113. Its design doc is byte-identical
  to the approved head, and its merged tree additionally contains #113's
  four files.

  | PR | Time | Merge | What |
  |---|---|---|---|
  | #109 | 17:40 | `580b7772` | Step 5: `read_guards` opens through the DAL; DAL closes on policy failure |
  | #110 | 18:02 | `657e1293` | Step 7: archive caps (50k entries, 16 GiB declared; **approved by David**), unsafe paths, encrypted members. These are **refusals**, a behaviour change on deploy |
  | #113 | 18:16 | `4ab8041d` | Step 8: `high_entry_count` corpus case, seeded invariant properties, fault injection |
  | #112 | 18:26 | `7e5714cd` | design for #111, canonical naming and WIP-version supersession (three review rounds) |
  | #114 | 19:45 | `6410880f` | `series_key` fixpoint, plus the read-only key-change report |
  | #115 | 20:08 | `a8d81cc2` | Step 5: `perceptual_reuse_analysis` through the DAL (allowlist now 5 files / 7 calls) |
  | #116 | 20:55 | `3aab6865` | page order: raw-name tie-break; duplicate names unresolved; `CONTENT_SIGNATURE_VERSION` 2 with one gate for every ordered reader |

  Master is `3aab686`, full suite **2710 passed / 8 skipped**.
- **The two Step 8 defects are fixed on master.**
  - **`series_key` split:** `Berserk_Uncensored` used to key apart from
    `Berserk Uncensored`.
  - **Page order:** it depended on physical member order on natural-key
    ties.
- **Operator-gated consequences, none run:**
  - an index rebuild under the new key, after David reviews
    `scripts/cbz_series_key_change_report.py --root …`;
  - re-certifying v1 content signatures. Until then, every existing row is
    *legacy* and the duplicate audit and near-duplicate generation return
    nothing. The re-certify tool is in progress as its own PR and must land,
    with operator approval, before any production cutover;
  - re-inventory of tied and unresolved archives;
  - deploying #110's refusals.
- **Relay caps raised** at David's explicit approval (terminal), as user
  environment variables (previously 20/160/80):
  - `LEAD_RELAY_MAX_WAKES_PER_HOUR=60`
  - `LEAD_RELAY_MAX_WAKES_PER_DAY=500`
  - `LEAD_RELAY_MAX_CHAIN=200`
  - **The restart** happened while idle. The old relay pid 30464 was
    terminated because `schtasks /End` stopped only its launcher; the new
    pid 16816 started at 17:19.
  - **David confirmed** the new caps on the chat dashboard.
- **Codex capacity failure.** Codex's headless run for #2235 ACKed but ended
  `turn.failed: Selected model is at capacity`, and no review was posted.
  Claude re-woke it with a new HANDOFF (#2238), and the review then
  completed (#2241). **An ACK is not a finished turn.** Check the attempt's
  exit code and log when a reply does not arrive.
- **David's #111 decisions (recorded on the issue):**
  - **Format:** `Series v01 #003 (2019)` or `Series ch. 1 (2019)`.
  - **Version marker:** `[vN]`.
  - **Brackets:** stripped for identity matching; the display name keeps
    `(YYYY)`, `[vN]` and edition words.
  - **Retention:** quarantined superseded versions are kept **2 days**,
    purged by a separate guarded slice.
  - **Komga:** read-progress resets are acceptable.
  - **Inserted pages:** always review, never automatic.
  - **Metadata:** David decided that more accurate or more comprehensive
    metadata may replace old. *Claude's proposed mechanical rule*, not yet a
    reviewed design change: drop the superseded ComicInfo only when the
    keeper's non-empty fields cover all of the old one's; otherwise send the
    pair to review.
  - **Word lists:** David proposed starter lists, and Claude grouped them as
    edition, collection, special and dropped tags. The final lists await a
    read-only bracket-token scan of the Tower names, which needs David's
    go-ahead.

- **The #108 scope is superseded.** The evening section above and the
  earlier contract describe superseded-duplicate and chapter-coverage
  analysis. That is replaced by the current #108 contract: a **read-only
  Syncthing preview and post-sync verifier**. It maps exact X/Tower byte
  matches into keep/write/remove sets, plus an unresolved set when evidence
  is missing. It does no copying, no Syncthing control or config writes, and
  no deep supersession analysis. It cannot measure block reuse or
  disk-write volume.

Next action, in order:
1. The re-certify tool PR (Claude subagent; Codex reviews).
2. The canonical formatter as a fixpoint function, with the watcher and
   sanitizer converging on it (#112 §6 step 3).
3. Two read-only Tower name scans, awaiting David: the key-change report
   and the bracket-word scan.

No copy, move, rename, rebuild, re-certify, deploy or activation is
authorized by this record.

## Earlier state — 2026-10-22 (evening)

This supersedes the day section below on the comic review queue, the trial
deadline and codex-lead's state. Times are **UTC-6**.

- **Comic merges, all pinned to approved exact heads with matching CI:**
  #100 roadmap (12:27, `76da5212`), #99 decision-manifest design (12:43,
  `cd2b774e`), #104 slice-4 ledger guard (13:31, `f77e518d`), #103 staging
  integration/rollback design (13:39, `fee1dc25`), #106 next-applicable-015
  predicate (16:48, `90e9ca65`, Codex lead, Claude review with 8/8 independent
  mutants) and #107 inert staging shadow-plan A3.1 (16:54, `f957bded`, Claude
  lead, Codex review with 8/8 independent mutants). Before the #107 merge, the
  combined #106+#107 master ran **2491 passed / 8 skipped** (`-n 4`), and the
  merged tree is identical to that tested merge. #107 only observes: the
  watcher's moves are unchanged, and the review root is
  `CBZ_CLASSIFICATION_REVIEW_ROOT`, with no default. The A3.2 configuration
  gate and policy question D.1 stay open.
- **Ambiguity measurement (#101 tool, hive #2079):** a read-only run over the
  configured X: index scope found 18,366 directories and 26 collision keys, all
  cross-library (0 same-root). Output is under
  `G:\ComicAutomation\cache\ambiguity_2026-10-22\`, report SHA256
  `1af6a916db55b7b4cd9187480bf8baf958b67fa56b6c9e33119600374a97de2f`.
- **Trial expiry and re-enable:** David extended the trial to 15:00 (hive
  #2018). `AgentSwarmCodexEnableExpiry` ran at 15:00 with result 0. Claude read
  `enabled=0` with zero reservations and zero headless attempts at 15:01, then
  deleted the one-shot task. At 16:22 David asked in the terminal for
  codex-lead to be re-enabled, **with no end time**. The caps of 20/hour,
  160/day and chain 80 still apply.
- **Relay envelope lesson:** only a lead message starting
  `HANDOFF @name:` or `QUESTION @name:` (colon immediately after the name)
  wakes the other lead. Claude's STATUS posts #2088 and #2090–#2093, and #2089
  (`HANDOFF @codex-lead per #2085:`), were skipped silently. There was no
  delivery row, and the cursor advanced past them. Re-sent as #2094 (16:47);
  Codex woke and ACKed as #2096 (its plan followed as #2097). A malformed
  envelope is indistinguishable
  from an idle lead unless the deliveries table is checked.
- **Operator goal for the comic work (terminal, hive #2091–#2105 and #2111):** collapse
  the three copies of the collection (F: backup, Tower `Z:` = `\\TOWER\media`,
  X:) into **one primary on X:** (faster, so decensoring runs quicker there)
  plus one backup.
  - Tower receives new books (phone → MEGA → `C:\Temp` → watcher →
    `Z:\comics\Manga|Comix`).
  - Tower holds the decensored files. Censored originals go to
    `F:\ai-decensor-originals`, a separately preserved set that is never a
    duplicate of its decensored file.
  - Tower was copied from X: and then **consolidated**: series split or
    duplicated across scanlation groups were merged. X: still holds those
    duplicates.
  - **X: is frozen** (David, hive #2111): nothing has been added to X: since
    it was copied to Z: and Z: became the primary. By David's account,
    everything only on X: is a duplicate or a pre-consolidation copy.
  - David backs up to F: (beside the existing sets) before any move.
  - The contract is comic **issue #108**: a read-only cross-copy inventory.
    Its **headline output** is the X/F → Tower moved-path mapping and the
    evidence for probable superseded duplicates. The truly-X-only loss list
    is a confirmation check **expected to be empty**. Items that cannot be
    decided are reported as unresolved, never as a loss. Codex implements it
    on fixtures; Claude reviews the exact head.

Next action: Codex's fixture-only #108 implementation and Claude's exact-head
review. A live inventory run needs separate authorization. No copy, move,
overwrite or activation is authorized by this record.

## Earlier state — 2026-10-22 (day)

This supersedes the disabled-only and comic-next-work statements in the earlier
finite-proof checkpoint below. New operator-facing timestamps use **UTC-6**, as
David requested in hive #1950; existing historical timestamps retain their units.

- **Swarm #139 / #67:** Codex approved exact head
  `528f512633e715e3e28db769ed5d501900543efe`, with 117 focused tests and five
  independently rejected mutations. It merged as
  `0a8c46956ab693e6745366b1ec52a5ed8945495e`; main CI `39813660608` passed.
  [Claude's full hub rollout receipt](https://github.com/Decksx/agent-swarm/pull/139#issuecomment-6346264362)
  records a backup before change, pause/stop, deployment/parity checks, restart
  and resume; build `b5cc792cd29f`, supervisor 20008 and unchanged relay 30464.
  Codex independently read production at that exact merge. The receipt's first
  precheck aborted without changes because it counted a live notice as a
  headless attempt. The revised precheck distinguishes those cases. No new
  runtime gate implementation is claimed. The live task-help template is the
  small discoverability slice of #67, not inferred task fields.
- **Comic #97:** merged at **11:31:58 UTC-6** as
  `f88d1da68a4213b1f3eb0030d5a851d3940e511e`, identical tree to approved head
  `a7c0151753e5acfd1975996e553600dbbd033a84`. Exact-head CI runs `39814410236`
  and `39817020082` passed; local full suite was 2412 passed / 8 skipped.
  Codex and Claude each rejected four selected mutants independently.
  [Independent review](https://github.com/Decksx/cbz-automation-suite/pull/97#issuecomment-6345899007);
  [merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/97#issuecomment-6347087023).
  #32 and #35 are now **closed completed**, with evidence pointers. Their
  implementation had already landed in August; this slice adds real two-ingest
  serialization/index-handoff, unrelated-series and failed-move witnesses.
  Tests and log only: no production rollout, live library/database access,
  staging wiring or routing activation. Remaining authority gates and verified
  cross-volume rollback are separate. The comic log is
  `docs/development_log_2026-10-22.md` in that repository.
- **Comic #101 / #98:** David authorized the combined next-work plan in hive
  #1972. The explicit-scope, read-only ambiguity-report command merged at
  **12:22:00 UTC-6** as `16f4cdab05d6db0309e6c6e4088c2bc71080e10d`, identical
  tree to approved head `a79837dbdea2f9152f1d3af0180d0f89d37c2f84`. Exact-head
  CI `39829808800` passed; local full suite was 2438 passed / 8 skipped.
  Codex rejected 9 selected mutants; Claude independently rejected 10.
  [Review](https://github.com/Decksx/cbz-automation-suite/pull/101#issuecomment-6347988091);
  [merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/101#issuecomment-6348088158).
  #98 is closed. The command requires a routing file and confirmation of the
  complete configured index scope, emits JSON on stdout and binds the config
  bytes, absolute config path and observed directory inputs in its fingerprint.
  Failed/disabled scans cannot pass. This is directory-level tooling, not a
  completed target-library remeasurement or archive-revision inventory. No
  production census, database access, rollout or activation occurred.
- **Parallel comic reviews:** roadmap #100's corrected exact head
  `ab69eed5eaa5aa951e1137316a7b0b7a99d93033` is approved; merge still requires
  that advertised PR head and matching CI, not the original `15aa829` checks.
  Decision-manifest design #99 at `60a4b74927cf1e88df2584998d94058419b3605a`
  has [changes requested](https://github.com/Decksx/cbz-automation-suite/pull/99#issuecomment-6347990837):
  revision-aware observation enrichment, trusted human-approval provenance,
  conflict-safe supersession and compatible/reconciled routing dispositions.
  Claude owns the revision; Codex re-reviews each changed exact head.
- **Finite workflow trial:** Claude reported David's separate terminal
  authorization for the four-hour trial, enabled at **09:36 UTC-6**, ending
  **13:36 UTC-6** on 2026-10-22. Codex independently read the binding enabled
  and the one-shot `AgentSwarmCodexEnableExpiry` task scheduled to call the
  supported disable route at that deadline. Expiry has not yet been observed;
  this does not claim an always-on OPEN watcher. App OPEN still uses notices.
- **CLI/app change during that trial:** hive #1954 records Claude's
  operator-requested re-registration after an app update removed the former
  CLI, then graceful app closure at **11:25:35 UTC-6**. Codex independently read
  the enabled binding to successor `01a1609d-cd64-7bd1-9880-2b5b488509d4` /
  `C:\git\agent-swarm`, registered CLI `bin\a96ca4c1eee0cf35\codex.exe`, and
  SHA256 `e757246b4de87359e660647fa9514955a0971ff6a30affdd8c145d1d5ece7b84`.
  Claude reports version `0.163.0-alpha.11.1`; proof `f120c372` covered
  `alpha.10.2`, so its result is not a fresh proof of this version. Source #1943
  subsequently arrived headlessly as #1955 and was ACKed as #1956; this turn
  merged comic #97. Do not describe the current reservation/queued timestamp
  notice as the zero-queue state of the earlier proof.

Next action: complete the parallel comic reviews and separately authorize any
target-library measurement; preserve the existing trial deadline and observe
its disable receipt after expiry.
Claude reviews this documentation checkpoint. No new activation or deployment
is authorized by this record.

### Earlier finite-proof checkpoint

The bounded CLOSED proof `f120c372` **passed** on deployed #137 merge
`61286041cbcc5d475f1e470aaba40faa39dc3408`, with green exact-merge main CI
`39798706770`. Claude closed and reopened the app through the reviewed helper;
David sent the one admin probe. Both probes had one headless launch, ACK and
exit 0; the second launch waited for the first process to exit. Codex independently
verified the retained result, relay rows, process identities and completed
successor turns. See [the checkpoint](../NEXT_STEPS.md#current-checkpoint--2026-10-22-closed-proof-passed)
and [audit](https://github.com/Decksx/agent-swarm/pull/137#issuecomment-6344548737).

At proof completion Codex was **disabled**, with no pending deliveries or reservations. The old
cancelled proof/claim is unchanged. This finite proof does not enable an ongoing
watcher or establish visual UI rendering from metadata alone. Any ongoing
enablement was a separate decision; the trial and completed comic work above
supersede that next-action statement.

## Earlier state — 2026-10-21 (supersedes the 2026-10-20 evening section below)

David approved the [#60 engineering boundary](../../design/engineering-leadership.md)
on 2026-10-21: interactive lead-run PRs retain independent exact-head review,
CI and rollout records; controller-run tasks retain activation and ledger gates.
Lead work is recorded honestly without inventing controller approvals. He also
requested `@Leads` as shorthand for alerting both interactive leads. Codex owns
the alias implementation and policy documentation; Claude reviews before rollout.

**Evening, 2026-10-21:** see
[NEXT_STEPS](../NEXT_STEPS.md#current-checkpoint--2026-10-21-evening). It
covers:

- #133 deployed;
- codex-lead registered disabled to the old thread;
- proof `53e110d6` cancelled before enable, with its claim retained;
- the Codex lead migrated to thread `01a1609d`. The driver migration (#135)
  rolled out on 2026-10-22: `reconcile-old` ran and codex-lead is registered
  disabled to the successor (see the 2026-10-22 checkpoint);
- `@Leads` observed end to end;
- relay limits of 20/hour, 160/day and chain 80, **live** since #134's
  relay-only rollout (relay 30464, production `dc565ef`).

**Afternoon, 2026-10-21:**

- #131 and #132 are merged and rolled out, and #72 is fixed.
- The last four held codex-lead deliveries were cancelled at Codex's
  direction, leaving 0 held.
- Production is at `1afa9cc`, with build `0833f9ad1bd2`, relay 34648 and
  supervisor 39260.
- See the [receipt](../DEPLOYMENT_LEADS_HEARTBEAT_2026-10-21.md). The next step
  is the [Codex CLOSED-proof plan](../../design/113-codex-closed-proof-plan.md),
  pending Codex's review.

Read [NEXT_STEPS.md](../NEXT_STEPS.md) and the
[deployment receipt](../DEPLOYMENT_RELAY_DASHBOARD_2026-10-20.md). The sections
below remain evidence of their own times, not current setup instructions.

- **The OPEN watcher is no longer pending re-review or uninitialized.** #127
  merged (`118e97d`), its filled prompt was reviewed, and its finite pilot ran
  from 23:00 to 23:58Z and was deleted at expiry.
  - It completed three native reviews (#1754 backlog, #1767 with an
    intervening manual status-only Check, #1769 unprompted in 108 s).
  - It **missed #1771**, posted after the last poll and before the cutoff.
    That is not a complete pass
    ([closure](https://github.com/Decksx/agent-swarm/pull/127#issuecomment-6304562027),
    [miss](https://github.com/Decksx/agent-swarm/pull/127#issuecomment-6305029614)).
  - No ongoing Codex watcher runs.
- **Deployed:** relay caps #126 (relay only, `a07a88f`) and dashboard #128
  (full procedure, `0acbdb7`, build `0833f9ad1bd2`). claude-lead is bound to
  `b2b425b8`, enabled and proven.
- **#129 applied:** production is clean at `2d1574d`, hub build unchanged.
  Codex independently verified all 30 named deliveries cancelled with zero
  attempts at 15:23Z; #1769/#1771/#1775/#1779 remain held/unregistered.
  Relay PID 49216 had a fresh snapshot, Claude's b2b425b8 binding was enabled,
  and reservations were zero. The scheduled-task disable failed during the
  rollout; the successful lock-protected cancellation does not erase that
  procedure deviation. Future task-disable failures must stop the procedure.
  [Audit](https://github.com/Decksx/agent-swarm/pull/129#issuecomment-6319668272).
  Codex remains unregistered, and the four newer deliveries need disposition
  before registration and a bounded CLOSED proof.

## OPEN watcher implementation and relay quota rollout — 2026-10-20 evening

This checkpoint supersedes the pending restart/old binding/old runtime statements
in the morning audit below. The historical records remain evidence of their
observation times, not current setup instructions.

- The bounded native desktop restart test passed; see
  [#123 receipt 6295301987](https://github.com/Decksx/agent-swarm/pull/123#issuecomment-6295301987).
  The old idle/busy/restart proof automations are PAUSED. No ongoing Codex
  watcher is enabled, and Codex remains unregistered in the production relay.
- Claude's current binding is `b2b425b8-954c-4f9e-bbf0-6f7f6e8acde8`, enabled
  after the separately verified new-session stdin bridge proof
  ([#113 receipt](https://github.com/Decksx/agent-swarm/issues/113#issuecomment-6301684024)).
  Do not repeat an already verified binding proof or wake an old session.
- #126 merged as `a07a88fb6ed820f0a3de87312a67eefda5c0a245`, pinned to
  Claude-authored/Codex-approved `77048dcad5ba856f7a6cc4ee12746d477b905ee7`,
  four green checks in run 39502309525. OPEN notices no longer consume the
  headless launch quotas; chain protection remains distinct. Defaults are
  12 launches/hour, 100/day and chain 12, configurable policy limits rather
  than measured capacity. No historical counter rows were edited.
  Codex independently ran 169 focused tests and caught five selected mutations.
- Claude owns and reports the relay-only rollout in
  [#126 receipt](https://github.com/Decksx/agent-swarm/pull/126#issuecomment-6302764973)
  and hive #1734. Codex independently verified the production checkout is clean
  at `a07a88f` and relay PID 20988 exists. The receipt reports Tower build,
  supervisor and workers unchanged; those were not re-audited by Codex in this
  check. Live-path confirmation remains distinct from process/checkout parity.
- Codex is implementing the finite OPEN watcher in an isolated worktree,
  `C:\git\agent-swarm-codex-watch`, branch `feat/113-codex-open-watch`, based on
  the merged cap fix. The [helper/pilot prompt](../../design/113-codex-open-watch-pilot.md)
  requires Claude's exact-head review before initialization or scheduling.
  Durable head-bound claims, pause/expiry/budget gates, retained uncertain ACKs
  and owner-bound completion are implemented. No pilot database, new schedule,
  production changes or relay registration were created by this implementation.
  Native turns expose duration but no token counts in the reviewed metadata
  schema; the pilot explicitly reports that limit and cannot establish an
  ongoing polling cost budget. Claude accepted that finite limitation in
  [#127 review 6303250712](https://github.com/Decksx/agent-swarm/pull/127#issuecomment-6303250712),
  and requested viability fixes. Routine operator/unsupported messages now
  surface alongside work without stopping the pilot; ACK pre-send checks
  precede the posting marker. The reviewed chat-helper hash is a required
  initialization pin, so #128 can deploy before pilot activation without
  automatic trust of changed bytes. The revised helper/prompt need re-review.
- Comic #96 (issue #60 diagnostics) merged as
  `a5dc3bc20a4fba052918cf4f2a86d1dc1180192d`, pinned to reviewed `9d34051`;
  master CI run 39500697135 passed. The #32/#35 reconciliation is parked behind
  the remaining interactive-delivery gap. Swarm #93–95 remain parked as well.
- David requested a relay counter and project/task dashboard in hive #1737.
  Claude accepted design/build lead in #1741; Codex will review. Codex's #1740
  coordination post is confirmed. This is a separate workstream from the finite
  watcher; do not stop the watcher implementation to duplicate Claude's UI work.

## Morning recovery and current delivery checkpoint — 2026-10-20

This checkpoint supersedes the earlier pending-proof statements below. The
project still aims to let the interactive leads collaborate without David
relaying their messages; background worker health alone does not prove that.

- Production is clean at `7a29f90aec800e8364c1425b6f20a212e83074ae` (merged
  #122). On 2026-10-20 around 15:32–15:37 UTC, authenticated controller status
  reported schema 6 and matching checkout/loaded/on-disk build
  `ab69ad056404c0b7c6c8827e355be770b7073a99d7968c6774d69bcff72f7314`.
  There were no live activations: 121 DONE, 6 EXPIRED; the external proof task
  remains READY_EXTERNAL_REVIEW, without a controller review verdict.
- Supervisor PID 25056 and workers 32468/32544/32628 are running, unpaused,
  with a fresh supervisor heartbeat. Their creation times are from October 19,
  before the reported overnight Internet outage. Relay daemon PID 45684 is
  running under its scheduled hidden launcher; its launcher is a separate
  process, not a second relay daemon. GitHub API and authenticated hive access
  both work. No restart or deployment was needed for this audit.
- The supervisor still logs intermittent Windows heartbeat-replace WinError 5
  (latest observed at 09:00 MDT); the current heartbeat is fresh. Relay #1610
  reports a 0.3-minute detected hub outage, not the length of David's reported
  five-hour Internet outage. Do not conflate LAN hub reachability with Internet
  availability or infer that no outbound requests failed overnight.
- During the audit, David's hive admin message #1611 reset the earlier chain
  cap. Held handoffs #1589/#1593 and #1611 were delivered and ACKed as
  #1613/#1615/#1617. Relay status then showed chain=2 and no reservations.
  No agent edited the cap or its records. Claude's registered interactive
  session `a750400a-9432-40d2-af7c-da1f613a1035` has a matching live process.
  Claude independently replied in #1619 that its watcher received Codex #1618;
  this confirms current direct coordination, beyond process health.

The finite native proof helper was approved in #123 at
`234473cf8e769d4bf461c6487ada998caa19ee66`, merged as
`d144408eb85e54cf1c4078b2920244250efdd27f`. Subsequent runtime receipts on
[#123](https://github.com/Decksx/agent-swarm/pull/123) establish:

- Idle scheduled turn `01a155f2-7a61-70c3-b2af-f246cf9211ef` completed on
  October 19, 20:55:16–20:56:43 UTC; source #1597 produced targeted ACK #1598.
- Busy scheduled turn `01a1561e-6df5-7851-af9e-ad4f246014fe` completed
  21:43:17–21:44:12 UTC, after parent `01a15618-8bd8-73b3-a909-63951cdc01e9`
  completed at 21:42:51 UTC; source #1601 produced targeted ACK #1603.
  This establishes no overlap, not how an earlier due occurrence was handled.
  Claude reviewed the exact busy prompt after execution, not beforehand.
- Both finite test automations remain PAUSED, confirmed again this morning.
  Codex is still unregistered in the production relay. These results do not
  establish app-restart delivery or an always-on Codex watcher.

Next: the bounded app-restart plan revision 2 is approved by Claude in
[#123 comment 6278759156](https://github.com/Decksx/agent-swarm/pull/123#issuecomment-6278759156).
It still needs David's availability, a filled prompt/timing window and Claude's
independent observer. No restart schedule, PROBE or observer is armed. Keep
Claude's separate post-deploy stdin wake smoke check distinct. #93–95 and the
comic CI-efficiency follow-up remain queued behind interactive delivery.

## One-run scheduling stopped; finite alternative proposed — 2026-10-19

PR #121 merged as `83666c04464301801975531fd0f764dd0f2c0019`, pinned to
Claude-approved `e5dd3d4d5b977abb88eda99a5373c6bf7279ca77`, all four checks
green in run `39313027019`. Immediate COUNT=1 scheduling attempts were rejected;
DTSTART was disallowed for immediate creation. No matching automation, fresh
probe or scheduled model turn was created. Receipt: #121 comment 6276243272.

The [finite proof amendment](../../design/113-codex-finite-watch-proof.md)
proposes at most three native scheduled turns with one exclusive file claim
for any hub-processing attempt. The concrete `codex_hive_proof.py` helper has
17 passing temporary-state/fake-hub tests, including concurrent claims and
ambiguous posts. It must be copied from the approved Git bytes and hash-checked
before scheduling. The native finite schedule itself is not yet tested or
enabled; no unbounded scheduler or modified automation files were used.

Claude's CLOSED PR #122 was re-reviewed and approved at
`dc87321230d6e0027efdd927aa9c98eacb20cdda` (#122 comment 6276538020): 161
focused tests independently passed, all four checks green in run `39317634880`.
All five earlier findings are fixed. Claude owns pinned merge/rollout
preparation; approval is not deployment or a real Codex bridge proof. Codex
registration/enablement remains gated; no runtime change by this checkpoint.
Subsequently verified PR #122 merged as
`7a29f90aec800e8364c1425b6f20a212e83074ae`, pinned to that approved head.
The new proof helper's six selected guard mutations were all caught: claim
overwrite, ignored expiry, wrong ACK target, unconfirmed receipt accepted,
wrong source sender and ignored existing ACK. These used isolated source
copies/fake hubs; no production state or unreviewed automation was executed.

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
