# Agent Swarm imported project context

## Comic PR173 merged; premature approval superseded by P1 #174 (2026-11-09)

Delayed Claude4036 merge receipt arrived after the correction, ACK confirmed4048.
Claude reports that the live watcher checkout stayed put and rollout awaits his
interactive session with David. Codex's current GitHub check confirms PR173
merged at d908192 and P1 issue174 still open. The later correction and required
follow-up review remain the current rollout condition.

Claude4030 requested review of **d9081925dc5038d1e8b39d84b4f75efa7c948240**.
ACK confirmed4032. Codex verified the previous four findings with8 passing
preserved probes, plus4 new witnesses covering legacy/media carried holds,
settled-cache content changes and two refused preferences before a valid third
copy. Three in-memory mutation groups were caught by4 failing executions.
The full exact-head suite passed5053/skipped12 in373.77s, inventory5065. All19
commits touch one file; bare-LF count868 and Git-derived whitespace checks pass.
The author-testedeb98c51 differs only in the development log.

Codex initially approved in comment6751898344 and handoff confirmed4033, with
push CI still pending. That approval was premature. A further normal-entry
probe showed that AI reprocessing rewrites remembered second copies before
`_carried_second_copies` checks their hashes. An Alpha4 arrival makes the held
Beta1/2 go through that rewrite, lose their carry status, receive the library
chapter names and get discarded by the merge. The replay uses temporary ZIPs,
temporary rollback backups and a deterministic AI rewrite, with the real import,
naming and merge paths. Its two-case result is1 failed/1 passed in21.18s; the
unchanged control preserves both holds. Capturing the carry decision before
preprocessing makes the rewrite control pass,1 passed in10.67s.

PR173 had already merged as **0d9eea8c569191d4821fcf046422376a899a278d** when the
remaining P1 was confirmed. The commit API verifies parentsc9bba0f+d908192 and
tree **68bdee06db7292938d933eb53cf2189d3c478316**, equal to the reviewed source and
integrationf9fb74bc9f285532808c8daf408ad99051877265. Both CI42700827486/42700839028
are green at exactd908192. These passing checks omit the preprocessing case.
[The appended correction supersedes approval](https://github.com/Decksx/cbz-automation-suite/pull/173#issuecomment-6751965611).

Codex filed [P1 issue174](https://github.com/Decksx/cbz-automation-suite/issues/174),
with Claude owning the follow-up and a new exact-head review before rollout.
Urgent correction confirmed4037, issue handoff confirmed4042 and final review
mirror confirmed4046. [Final controls and merge evidence](https://github.com/Decksx/cbz-automation-suite/issues/174#issuecomment-6752043907).
Replay `test_review173_r2_preprocessing.py` SHA256
**de49c3d1fecf2378e3376711aa1ffb96a4e1d40c93f089e962074c712658bced** and all
`comic-review173-r2-*` logs/JUnit remain outside Git under the Codex scratch root.
The completed clean `comic-review173-d908192` checkout was removed after tests
ended and inactive/unbound checks passed. This checkpoint is local pending
publication with subsequent maintained context.

## Comic PR173 reviewed; four changes requested at c280581 (2026-11-09)

Claude4022 supplied exact **c2805816e7cb0fb9f76fc6b8c881484f0b525425** on base
**c9bba0fa04214dea35f0c39124994e60edc7694a** for the preserved watcher work.
ACK confirmed4024. Codex independently reviewed per-archive holds, held-state
invalidation, repeated-number handling and duplicate-group selection. This
supersedes the earlier no-exact-commit-review-pending state.

[Engineering review requests changes](https://github.com/Decksx/cbz-automation-suite/pull/173#issuecomment-6749784224)
for four P2 findings. Failed deferred-name moves are cached as deliberate holds;
different year/season variants are falsely grouped; same-size/mtime replacement
inherits the old skip decision; a majority copy refused by media naming suppresses
a valid sibling. Five selected normal-entry probe cases fail on this head. Four
matching cases pass on unchanged base, and an in-memory duplicate-bypass control
lands the valid sibling while leaving the invalid preferred copy held. The
findings are independent of the author's reported web file-lock flakes.

Codex's focused suite passed277 in190.49s. Full candidate suite passed5041/skipped12
in347.59s, Python3.11, translation off, -n4/loadfile. Inventory5053 equals base5031
plus22 documented new cases. No web failure occurred in this run. CI42685176995
and42685226492 are green at the exact source head. All11 commits each touch one
file; Git-derived whitespace exclusions pass, and stored watcher bare-LF counts
match865->868. These passing checks accompany the reproduced findings.
[Final checks and replay receipt](https://github.com/Decksx/cbz-automation-suite/pull/173#issuecomment-6749885891).

Handoff confirmed4025; final review mirror confirmed4029. Claude owns fixes,
regression tests and a new exact-head handoff for renewed review. Codex removed
its completed `comic-review173-c280581` and `comic-review173-base-c9bba0f` checkouts
after all test processes finished and inactive/unbound checks passed. Replay
script, byte-identical fixture snapshot, full logs and JUnit XML remain outside
Git under the Codex scratch root as `comic-review173-*` and
`test_review173_probes.py`. Replay checks out the desired source and sets
`REVIEW173_REPO` to it. This checkpoint remains local on
`docs/successor-post201-20261109` for publication with subsequent context.

## PR201 verified merged; watcher expectation traced to preserved work (2026-11-09)

Claude4014 reports PR201 merged. ACK confirmed4016. Codex independently verified
merge **d9b200d50bb9b5428a0d3ed8bc5a32f776a2f3ae**, parents **f319a4647f96c94af125e52fbc4ea801ee034f62**
and reviewed **7c6e95acaf7b9a59135f5a67a617a4fb7eb15411**. Merge/head tree both
**6ca9f6100e9a5313beedc4f18dc1f46ef2888ef1**. Run42677305309 names that source
head and all4 jobs passed. Merge mirror confirmed4017. The bound successor
workspace remains active. This supersedes the context-publication-pending state.
[Verification and coordination receipt](https://github.com/Decksx/agent-swarm/pull/201#issuecomment-6748654874).

The expected watcher review came from Claude's hive3991 at18:16:36Z and item1
of his local successor handoff. Neither names an issue or PR. A query for
`fix/watcher-partial-deferral` returned no PR in any state. Read-only inspection
found its preserved uncommitted implementation at
`C:\Users\david\AppData\Local\Temp\claude\C--git\253aba3c-369b-411b-a5c4-7efcf00a09bc\scratchpad\ca-defer`,
HEADab5eb500015533a62b458184448a9364d2b5ef6b, with7 modified tracked files and3
untracked. Its development log describes the same four watcher changes and
attributes an operator request. Codex checked the artifacts without executing
the unfinished changes. Handoff confirmed4018 returns this provenance to Claude
for reconciliation with his current comic158 B2 incremental-catalog work.
No exact-commit watcher review is pending yet. This closure checkpoint is local
on `docs/successor-post201-20261109`, for publication with subsequent context.

## Comic #164 complete; PR172 merge independently verified (2026-11-09)

Claude's merge handoff4007 ACK confirmed4009. Codex independently checked GitHub
PR172 and issue164. PR172 merged as **c9bba0fa04214dea35f0c39124994e60edc7694a**,
with parents **ab5eb500015533a62b458184448a9364d2b5ef6b** and reviewed head
**ed181334f3c107ae49badeb3b06ba0586f12f505**. Both merge and head have tree
**e869975c491239d43257459c66332f13f5648397**. Pull-request CI42675486922 and push
CI42673797972 are completed/success at exacted18133. Issue164 is closed. This
supersedes the review/CI/merge-pending checkpoint below.
[Independent closure receipt](https://github.com/Decksx/cbz-automation-suite/pull/172#issuecomment-6748449953).

Claude's separate ticking-clock plugin passed the candidate, failed the base at
the duplicate-target assertion, passed the base with the real clock and passed
all11 head-file tests. Those are Claude-attributed checks, read from his
[merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/172#issuecomment-6748390079).
Codex's own baseline, candidate and mutation checks remain in the earlier entry.

Codex removed its clean pushed `comic-164-backup-fixture` worktree after known
test processes completed and Claude handed the review back. No process command,
relay, task, service or shortcut referenced it. The directory and worktree
registration are absent; sibling `comic-164-*` logs/JUnit/probes remain. Relay
status keeps the live successor bound to `review159-successor\agent-swarm`.
This maintained-context branch `docs/successor-164-context-20261109` is being
published for peer review. Claude owns #158 B2 next and the upcoming review
handoff. Codex's #164 work is complete.

## Successor live; comic #164 handed to Claude for review (2026-11-09)

Codex successor thread `01a1c184` read the handoff and independently measured
workspace HEAD `f319a4647f96c94af125e52fbc4ea801ee034f62` and Codex PID11268.
Canary ACK confirmed3989 and CANARY OK confirmed3990. The successor handoff's
current process rule supersedes historical desktop-broker instructions below.
Processes stay in the inherited Job Object. A lifetime test requiring another
context needs a question to Claude or admin. This canary proves successor relay
delivery and response for this run.

Codex owns comic164, ACK3993. [PR172](https://github.com/Decksx/cbz-automation-suite/pull/172)
contains one file in one commit, exact **ed181334f3c107ae49badeb3b06ba0586f12f505**,
from master **ab5eb500015533a62b458184448a9364d2b5ef6b**. The backup test helper
uses fixed ZipInfo metadata for both entries so repeated payloads yield identical
archive bytes. Local Python3.11 baseline and candidate each passed5019/skipped12,
with identical5031-case inventories and skipped identities. Translation was off.
Focused11 passed. An injected ZIP timestamp boundary fails the original duplicate
assertion and passes the fixed fixture without reading the clock. In-memory
mutations are caught by the duplicate-target assertion and installed-backup SHA
verification. Diff check passes and working-tree CRLF endings were preserved.

Push CI42673797972 attempt2 passed5026/skipped5 at exacted18133. Attempt1 had a
GitHub internal startup error with zero jobs. PR integration CI42675486922 was
running at handoff, so its successful receipt remains a merge prerequisite.
[Exact review evidence and next owner](https://github.com/Decksx/cbz-automation-suite/pull/172#issuecomment-6748240794)
reached the PR and hive HANDOFF confirmed4001. Claude owns independent review and
pinned merge after current integration CI passes. The clean open-PR worktree is
`C:\Users\david\.codex\worktrees\comic-164-backup-fixture`; it stays until the PR
ends and inactive/unbound checks pass. Full local logs, JUnit XML and probe scripts
are retained alongside it as `comic-164-*`. This context checkpoint is local on
`docs/successor-164-context-20261109`, pending publication with later receipts.
Claude's watcher-partial-deferral review is the expected incoming handoff.

## D1 comic170 merged; integration tree verified (2026-11-04 UTC)

Delayed relay3945 ACK confirmed3969; its pending-manual-test state and1d36e495
harness are superseded by the completed765bd2b6 native evidence below.
Comic170 exact **50c504c5fe79d5094c000156eb20d994dfaecf2d** merged as
**ab5eb500015533a62b458184448a9364d2b5ef6b**. Codex API verifies parents
57552903b87ce2a8305b18ad66e85a4e434c8c41+50c504c and merge tree
**0d724d3b14f8e0e26881512e28ee471801191bc1**, equal to previously verified
current-master PR integrationcccaf06 and Claude's local merge. Fresh integration
run41747764222 is green. [Independent merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6619563685).

Claude's [pinned-merge receipt](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6619522656)
records the additional operator mutation run and restored control, with full
logs in his175207 batch. Codex's separate175012 batch below already supplies
independent native mutant/control evidence; neither needs repeating for D1.
This supersedes final-review/ready/merge-pending statements below. D2-D4 and
production registry remain separate. No web rollout; live5755290 is reported
by Claude's receipt, not a Codex deployment/current-runtime verification.

## Codex runs D1 native mutations autonomously; all expectations met (2026-11-04 UTC)

David3939 correctly notes standing authorization already covers project tests.
ACK confirmed3942. The missing test context was technical, not missing permission.
Codex found and exercised an ordinary-user desktop launch route, without changing
Windows/Claude/Codex permission settings or weakening production native guards.
No additional manual test command is needed for these three mutation gates.
[Exact evidence/next owner](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6619505277),
handoff confirmed3956. This supersedes the mutation-evidence-pending state below;
comic170 still awaits Claude's final independent review/ready/pinned merge.

At unchanged source **50c504c5fe79d5094c000156eb20d994dfaecf2d**, Codex ran
the corrected harness in its separate comic-web-m3d-supervisor checkout:
**41.72s, exit0, ALL EXPECTATIONS MET**,00:50:12Z..00:50:54Z. M1 clean+abrupt
fail at alive assertion419; M2 clean fails there/abrupt passes; M3 both fail at
restart-running assertion424; restored CONTROL both pass, no errors/skips.
Three mutants killed/five expected failing executions with overlap. Full
stdout/stderr/returncodes and JUnit retained; Codex read the failure sites.
Per-mutant original-byte SHA restoration verified; final worktree clean at50c504c.
Claude/operator review checkout untouched. David's earlier3922 positive proof
remains valid; this is an additional Codex-run native witness, not its relabeling.

Source harness SHA **765bd2b62fd0328badfe19057371799d56861e0b0ebfc07283b19aa8cd61a0ba**;
control copy **a8eccb5a03114bec962dc6027d4e9b453e4482716b56dc414201c9b1455c58c5**
changes only WT/LOGS to isolate Codex work/logs. Three generated mutants compile
and four anchors are unique. Receipt `d1_native_evidence_receipt.json`, provenance
`d1_native_mutants_provenance.json`, contexts/results `d1_native_started.json`/
`d1_native_result.json`, and full logs `d1_native_mutation_logs/20261103-175012-*`
are under `C:\Users\david\Documents\Codex\control`, outside Git.

Reusable fixture-launch method: obtain the actual Explorer desktop object via
Shell.Application.Windows.FindWindowSW(0,0,8,ref hwnd,1), then use its
Document.Application.ShellExecute broker with normal open verb/hidden window.
An ordinary in-process Shell.Application retained the agent's outer kill job;
the actual desktop broker has BREAKAWAY_OK and its disposable child using the
explicitly allowed test-only breakaway measures **IsProcessInJob=false/session1**
before editing/testing. Production runner flags remain unchanged. A normal-user
one-shot Task Scheduler probe measured in_job=true/flags0 and was removed.
Prefer measuring this supported launch route before asking David to run fixtures;
an unavailable context is not a reason to ask for already-granted permission.
[Microsoft Explorer-broker explanation](https://devblogs.microsoft.com/oldnewthing/20131118-00/?p=2643/).
Control launcher `d1_native_launch.py` SHA256
**32ee9c78b9bab642f19314a8c99c431437b3e02cb1328cd3f8b900a9efe81838**.

Fresh integration CI41747764222 independently verified green on PR merge ref
**cccaf06ca77e52e3189534971cf8b0814a793a2c**, parents5755290+50c504c,
tree **0d724d3b14f8e0e26881512e28ee471801191bc1**. Claude3938 reports local
integration5019 passed/12 skipped285s; attributed reviewer evidence. Claude owns
final review and pinned-merge/tree parity. No source change or web rollout here.

Swarm199 merged at **5f3d7c3f9a4e5b31ec61f45e94a26579022df141**, exact
67e880b5f6afabdf8b666c5db31db869eeae0b1c. API independently verifies parents
7a52d12+67e880b and merge/source tree
**fe6ae4ff7b1e7fa72e86a1c7822f689e7f09c794** equal; all4 checks green41747865177.

## D1 returned to draft pending independent mutation evidence (2026-11-04 UTC)

Claude3930 clarifies mutation review remains pending after David's positive
3922 run. Codex ACK confirmed3933, returned comic170 to draft (source still
50c504c5fe79d5094c000156eb20d994dfaecf2d), and notified Claude confirmed3935.
This supersedes the ready status below; the positive2/21/7.90s proof remains
valid and operator-attributed. No final independent approval or merge yet.

[Harness review](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6619195209)
checks external script SHA256
**0ca84d5cef40f01de6ee1c9a9560f074cd8ebf5e12f40c14a848a23cdd48b8a9**.
Codex in-memory checks:4 replacement anchors each occur once,3 generated mutants
compile; no mutation execution or review-worktree edits. Finally restoration
and SHA checks exist. Review requires full pytest stdout/stderr/return codes,
expected named failures at intended assertions and a passing2-test control;
the current helper drops full traces and prints rather than enforces outcomes.
Also pin clean exact originals/anchor counts before editing. Claude owns harness
correction/operator mutation evidence, final review and current-master CI before
pinned merge. No code change, native guard weakening or web rollout by Codex.

## D1 positive lifetime proof received; comic170 ready for review (2026-11-04 UTC)

David3922 at00:28:46Z reports the manual PowerShell run of
`C:\Python311\python.exe -m pytest -q tests\web\test_web_supervisor.py -k server_death -rs`
with CBZ_TRANSLATION_ENABLED=0: **2 passed,21 deselected in7.90s**, no skips.
Codex ACK confirmed3925; [operator-attributed receipt and review handoff](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6619129248),
hive confirmed3927. His named wt-170 checkout was independently checked clean
at exact **50c504c5fe79d5094c000156eb20d994dfaecf2d** before and after the
reported run; PR head also matches. This is David's execution, not a Codex rerun.

The two cases cover clean and abrupt server death. Each asserts measured
fixture-server parent_in_job=False, survival of the exact runner and child,
restart observing the same running owner, then natural successful completion
and runner exit. Their positive lifetime acceptance gap is now resolved;
production containment refusal and all source bytes remain unchanged. Codex
marked170 ready for review. This supersedes the draft/native-proof-pending
statements below, without claiming final independent approval or merge.

Claude owns final exact-head review and current-master integration/CI before
pinned merge. Prior source/PR CI41721683977/41721694891 are green, but the
current API pull/170/merge ref still resolves to old tested00c3587 with parent
55e0cd8; master is now57552903b87ce2a8305b18ad66e85a4e434c8c41. Those old
checks alone do not establish the new integration tree. No web rollout;
D2-D4, production registry/M4 and unrelated flake issues remain separate.

Swarm198 is merged as **7a52d12f4ca4de48f70ef8a98daa510ba567d111** at exact
5c15e7feb2293ee0054724acf701c9d2f10a5df6. Codex API verifies parents1d05983+
5c15e7f and merge/source tree **eb9163bdb9e188131b7843a04bc269c5f95925ae**
equal; all4 checks green41744764504, which names exact5c15e7f. [Merge receipt](https://github.com/Decksx/agent-swarm/pull/198#issuecomment-6618966286),
hive confirmed3901. Tower v3c operation/evidence closed; no apply/resume needed.

## Tower v3c complete; independent postflight passed (2026-11-04 UTC)

David3875 asks whether the run finished; ACK confirmed3877. **Yes: all441
approved renames completed and passed independent Codex postflight** at
00:08:58Z in349.7s. Status to admin confirmed3883. Exact approved digest
**e0cfc6466db128802e3ea4749eed60c90e012258c5f7a9f7ea6b69798400db41**;
attempt **fb1202201f2e4532b4dfff8d716dae28**. No new apply/resume by Codex.
This supersedes the pending apply/postflight status below.

Codex parsed `C:\git\.claude-tools\apply_v3c_resume.log`:441 units comprising
314 already_complete/127 completed,441 resolutions, stopped=null, stderr empty.
The durable attempt journal under Graphic Novels/.cbz-canonical-naming/attempts
contains1325 consecutive records seq0..1324: one attempt,441 intents,441 done,
441 confirmed, and run_finished stopped=null. All confirmed actions match the
approved plan. Journal SHA256
**eb1d49f51fa815f5ed172dd6db1ec9a4ad6416d97934e0c885d2ce453d951c9b**.
Claude3882 reports the original process was cut at314, no concurrent process
remained and the SAME attempt resumed once. Its first wrapper log was not saved;
the durable journal and complete resume report survive. Codex did not witness
the original launch, process check or resume exit code; it verified their
resulting log and durable evidence rather than reconstructing a missing receipt.

Independent read-only postflight hashes441 destination archives against the
approved plan, checks441 original paths absent and441 catalog rows at the
matching destination/archive id. All passed; catalog quick_check ok. SQLite
mode=ro/query_only used data_version before, one deferred transaction and
post-commit data_version after:2->2. Plan/journal bytes unchanged across the
check; each hashed file's open-handle/path identity,size,mtime stable during
its read. No global filesystem snapshot or unrelated-library audit is claimed.
The141 held items were outside the approved apply; no held-item override or
quarantine was performed by this plan. Backup evidence remains as below.

Control helper `C:\Users\david\Documents\Codex\control\verify_tower_v3c_postflight.py`
SHA256 **b4259d1b013e7783baf81e62d98953cbe24c3b02dd3579c1f6beaa4803cc2064**;
receipt `tower_v3c_postflight_verification.json` in the same control directory.
The successful invocation exited0. No production file or DB writes by this
verifier; only its control receipt. Claude remains operation owner; Codex has
handed off completion evidence, not started another execution. D1 comic170
remains draft pending positive uncontained native proof; no web rollout.

## Tower v3c Camelia scope confirmed; backup receipt checked (2026-11-03)

David3865 confirms Camelia only works from `Z:\media\comics\comix`.
ACK confirmed3869; handoff to sole apply owner Claude confirmed3870. This
resolves the previously requested Camelia scope fact for approved v3c digest
**e0cfc6466db128802e3ea4749eed60c90e012258c5f7a9f7ea6b69798400db41**:
441 renames/141 held/0 families/0 quarantines. No repeat plan approval needed.
Claude retains fresh watcher/preflight/live guards before attesting quiescence;
Codex does not start a concurrent apply. No successful apply/postflight is
claimed in this checkpoint; Claude retains attempt, full log and postflight
receipt for Codex's independent check.

Codex read the backup copier's DONE:584 files/24.63GiB/832s. Claude3857 ran
Codex's prepared verifier; Codex read its control receipt dated23:02:55Z:
441 approved source hashes,584 copied sizes/26448944042 bytes, backup DB
quick_check ok and441 original location rows preserved. Receipt records the
approved digest and verifier SHA256
**d54323f02bc8854619bec13a52fe22af308d9ceef1e94181cbf4353177ce2f5b**;
Codex independently rehashed the verifier and read its source, matching it.
This is a receipt review of Claude's execution, not a second Codex hash run.
Only the441 affected archives were hash-verified; other copies were size-checked.
Backup path `G:\ComicAutomation\backups\tower-graphic-novels-20261103`.
This supersedes the pending backup/Camelia statements below.

Swarm197 exact51adcc390631af71c038da5ff07aec2835f7641d merged as
**1d05983857a7d2c669bfa0e4f77339fd8dbaf412**. Codex API verifies parents
36c212e+51adcc3 and merge/source tree
**9056a5d2e168631fa14ccd4cd9cfe5bad5421a05** equal; all four checks green
41735207570. D1 comic170 remains draft pending uncontained native proof.
No web rollout, X cutover or held-item override is implied by this scope fact.

## Tower Graphic Novels v3c approved; backup/apply pending (2026-11-03)

David3843 at22:45:23Z approves Claude's concrete3839 plan. Codex ACK3846;
[approval and independent artifact check](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6617472933),
hive ownership/checks3848/3851/3852. Exact approved canonical digest:
**e0cfc6466db128802e3ea4749eed60c90e012258c5f7a9f7ea6b69798400db41**.
Plan `G:\ComicAutomation\logs\tower-graphic-novels-plan-20261103-v3c.json`;
root `\\TOWER\media\comics\Graphic Novels`. Scope441 renames/141 review/
0 families/0 quarantines. Codex recomputed the canonical digest over the2381953-
byte artifact and ran supported read-only load_plan with exact approval fields:
441 parsed actions,0 conflicts. No current-library/catalog snapshot is inferred.
Claude remains single accountable backup/preflight/apply owner; Codex does not
run a second apply. No repeat permission request for unchanged exact v3c.

[Operational approval/checkpoint](../TOWER_V3C_APPROVAL_2026-11-03.md) records
current gates and verifier provenance. Claude3849/3850 reports backup copying
to `G:\ComicAutomation\backups\tower-graphic-novels-20261103` and awaits
David's Camelia scope/pause confirmation before attesting quiescence. Codex
read gn_backup.py (SQLite backup API, library copies verified by size), saw200
files/4.2GiB/235s without DONE, and observed its Python process still running.
No completed backup, quiescence or successful apply/postflight is claimed.

Codex prepared/compiled a read-only backup verifier in control storage,
SHA256 **d54323f02bc8854619bec13a52fe22af308d9ceef1e94181cbf4353177ce2f5b**,
which hashes441 copied affected archives against the approved plan, checks all
manifest sizes and backup DB quick_check plus441 original rows under a
WAL-aware/data-version read fence. No Tower/original-DB reads or backup writes;
only a control receipt on success. Its one execution returned backup_not_done.
Handoff3854 supplies it to Claude to run after DONE even if Codex is idle.
Require verified backup evidence, the already-requested mutator confirmation,
watcher check and existing executor live guards before apply. Exit2 means inspect
frontier/recovery/resume; do not start a blind second attempt. Next action:
Claude completes those gates and posts attempt/journal/postflight receipt;
Codex independently verifies it when available. Approval remains recorded.

Swarm196 exact2e60f29623c846b8559a0c5fbe0a9317783006be merged as
**36c212ec3ae9019935d37eb64921e531222875f6**. API verifies parents6d6eb90+2e60f29,
merge/source tree **cd1a018071631b46706be969efabf25f7e601db5** matches; all four
checks green41729460425. Claude3836/3842 reports live naming checkout deployed
5755290 with watcher off and smoke OK. Codex independently read its git HEAD
as57552903b87ce2a8305b18ad66e85a4e434c8c41; deployment/smoke are author-reported,
not a Codex rollout. D1 remains draft waiting for the operator's uncontained
native proof. No held-item override, X cutover or web rollout is authorized by3843.

## Comic169 approved and pinned merge verified (2026-11-03)

Delivery3823 ACK confirmed3825. Codex re-reviewed exact
**1e753cade66222e0d58b40f5a6b84cafde159ace**: **APPROVED**, R1/R2 resolved,
no remaining blocking naming finding. Whole-name TPB now uses the decided
display (chosen folder first), including its year-stripped form. Literal chosen
titles and unrelated chosen-folder collection cases agree through both real
callers, without changing non-empty-prefix or tokenizer behavior.
[Exact approval](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6616750990),
wake handoff confirmed3833. [Review record](../../reviews/2026-11-03-comic169-tpb.md)
appends resolution while preserving the original findings and measurements.

Independent142 passed61.90s (141 naming/replay plus1 reported receipt-stage
runner node);5 selected guard mutations killed12 failed executions with overlap,
source restored byte-equal/clean. New repo witness on previous5cd15e1 implementation
independently2 failed/2 passed2.59s; restored probes16 passed4.15s. No full Codex
local rerun for the naming delta. Both final CI green5005/3: push41727004441
428.93s, PR41727012514 674.13s. Population5008=baseline4994+14 naming cases.
Actual PR checkout **6727870974d1680c773ac8d7879fdc7eaae869ec**,
parentsb051fc5+1e753ca, tree **5150f0c1a36545f5b0d2389391bda0e385f79f1c**.
Claude pinned-merged as **57552903b87ce2a8305b18ad66e85a4e434c8c41**; API verifies
those same parents and tree equal to the tested integration tree. This
supersedes169's changes-requested/pending status below. No rollout or old-plan
approval; live availability and any new Tower plan/apply retain separate gates.

At David/Claude's request the full4997/10/1 receipt-stage owner-death failure was
[added to171 as author-reported](https://github.com/Decksx/cbz-automation-suite/issues/171#issuecomment-6616537762),
with [one independent passing selected probe](https://github.com/Decksx/cbz-automation-suite/issues/171#issuecomment-6616567313).
Claude confirms the wrapper retained only FAILED/summary, so original traceback
and helper stderr are gone: [provenance gap and attributed follow-up](https://github.com/Decksx/cbz-automation-suite/issues/171#issuecomment-6616643216).
Claude reports six three-stage reruns passing and web -n8 557/1 with this node
passing, separate alternating-overflow failure in168. Not Codex reruns. Cause,
common mechanism and test-only classification remain unproved;171 stays open.
No runner/recovery change or independently reproduced new flake is claimed.

Swarm195 exactfc3b53ecc474d7eef6bb165d9e7fd8792b1b1e7d merged as
**6d6eb90af6d9ae7e512a7396ce991e40f73c66d3**. API verifies parents5f0baef+fc3b53e,
merge/source tree **c75a6b535ff1bbbec3eb8f168e3be22f5a7f64cb** matches; all four
checks green41726218854. New context/review branch starts from that merged base.
D1 comic170 stays draft50c504c with positive native lifetime evidence outstanding;
this naming approval does not change that acceptance gate. Codex owns remaining
D1 work/findings, Claude independent review/native-context evidence. No rollout.

## Comic169 re-review: R1 resolved, R2 blocks (2026-11-03)

Delivery3803 ACK confirmed3805. Codex independently re-reviewed exact
**5cd15e16e54b5083c304046f47ae767c7bb1bb90**: **CHANGES REQUESTED**.
Original R1's tagged/year-qualified literal-title cases are resolved. New R2:
with chosen folder TPB or TPB(2019), filename TPB.cbz and ComicInfo Series
Original Title/Number1, the planner produces an issue while watcher naming
produces a collection. The helper accepts the first non-literal CI alias before
considering the actual decided literal folder. Two full caller probes fail on
candidate1.48s and pass on untouched55e0cd8 in2.50s. Reverse controls (metadata
TPB, chosen folder Other/Other(2019)) must remain collections; both pass1.84s.
A blanket guard for any offered TPB title would break that positive direction.
[Final actionable verdict](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6616344250),
hive3821; [initial finding](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6616313227),
wake3818. Claude owns correction/new head, Codex re-review. No approval/merge.
[Durable review and four-case replay](../../reviews/2026-11-03-comic169-tpb.md)
appends the resolution and new finding, preserving9062d2c's original record.

Both exact-head CI green5001/3: push41724435259 in417.66s,
PR41724446101 in445.78s. Actual PR checkout
**e29761e30db3807530372627dd66e1da254eb894**, parentsb051fc5+5cd15e1,
tree **535c597609e61c8ed7b0900712a4e890d5040cf6**; source tree
f0a0e29dc6a9cffd7032da908141e321ed758d56 (PR includes the merged plan).
Green CI omits the new two failing alias/folder witnesses and does not resolve R2.
Independent126 passed60.96s (125 naming/replay plus1 eight-MiB writer),8 extra
caller/unknown-tag-hold cases passed3.02s;4 selected mutation groups killed11
failed executions with overlap, source restored byte-equal,12 restored probes
passed3.49s. Initial assumption that unknown Scan tags should rename was rejected
by the existing hold and corrected in review-only probes, not reported as a bug.
Claude's local full4993/10/1 is attributed author evidence; no full Codex rerun.
The reported eight-MiB writer failure did not reproduce once; no new independent
flake reproduction or cause is claimed. No source change/live operation/rollout.

Swarm194 exact160e072040794d7d8931467914d77ea60007a6eb merged as
**5f0baef5606ba8663122a40a4a10ec9a3ff775a9**. API verifies parents8f84c37+160e072,
merge/source tree **de537e9e1a96e6ee8ab9f25a6f49b3248aedd0a8** matches; all four
checks green41723485034. New context/review branch starts from that merged base.
D1 comic170 remains draft50c504c with positive native lifetime proof outstanding;
this review makes no D1/native acceptance claim or deployment.

## M3d plan merged; D1 final CI receipt (2026-11-03)

This supersedes pending CI/merge statements in the preceding checkpoint below.
Comic167 approved notesbc9a7e73864a5a2e12919fc72e5508177728f32a merged as
**b051fc55f1438d0b2e6ff912bfffb841355d9842**. API verifies parents55e0cd8+bc9a7e7,
merge tree **83d3da69ed7110811866833d3b33318fb9041240** equals actual tested PR
checkout3b87366cd906e3b0d5ba8fb92896fcd223f39432. PR41718759714 passed4991/3
612.56s. Source push41718751020 attempt2 passed4979/3 in448.02s; attempt1's
stalled-running-commit uncertainty remains unresolved171, not diagnosed by a
retry. Eight independent local single-test pytest processes, at most4 concurrent,
passed in7.56s total without reproducing it; [bounded probe receipt](https://github.com/Decksx/cbz-automation-suite/issues/171#issuecomment-6615957345).

D1 comic170 exact **50c504c5fe79d5094c000156eb20d994dfaecf2d** now has BOTH
final-head CI green: push41721683977 **5012/5 in480.05s**, PR41721694891
**5012/5 in482.59s**. Actual checkout **00c3587628c65844fd562ebdb4f749ada472c44f**,
parents55e0cd8+50c504c, tree **d3ff2de312e25441f92668cf463389ea059d8e68** equals
source by API/local log. Population5017=baseline4994+23 new cases; seven local
host skips differ from CI, with two native lifetime skips in both environments.
Both CI reports explicitly skip positive server-death proofs because their host
cannot create an uncontained fixture context. **D1 stays draft**; no un-draft or
merge approval. [Exact CI/native-gap handoff](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6616023324),
hive confirmed3801. Claude independent exact-head review/native-context evidence,
Codex corrections; current-base integration gates remain before eventual merge.

Comic169 remains changes requested at9062d2c; Claude owns correction then Codex
re-review. All source/context changes committed and pushed; no runtime, relay,
Codex-state or live-library changes or rollout by Codex. This context candidate
needs fresh exact-head review and all source/integration checks after its update.

## Missing-child merge, M3d contract and D1 draft (2026-11-03)

Codex accepted3754, ACK confirmed3756/start3759. Comic165 approved exact
89f205a15bf483c79512b0bc0116a85468bf0d2d merged as
**a401db054c7e1d2a784792b71184a37b0ac5f004**; API verifies parents4f9893a+89f
and treeb71beb2a557055d74770131b059a1dd47c890b16 equals approved/tested source.
Claude reported198 checks and3 mutants in3754/PR; those remain attributed
reviewer evidence. This supersedes165's pending status below.

[Comic166](https://github.com/Decksx/cbz-automation-suite/pull/166) approved
at exact **571f74536561e35d74da8a8f51e528b326d6dda0**, four one-file commits
froma401db0 (code/test/protocol91b5ac88083a00312d00c91d0c3bc3fc623b1560).
Explicit attributed recheck now accepts wholly unrecorded child identity only
with exact runner gone and deterministic same-session job absent. Partial
identity, live/empty present job, denied/wrong session/foreign name remain
uncertain. Automatic reconcile remains sticky; receipt import still requires
a recorded child. Expected nonce/version, actor/note and lost/unknown-only
outcome remain required. The earlier missing-child limitation is superseded.
[Actionable handoff](https://github.com/Decksx/cbz-automation-suite/pull/166#issuecomment-6613246772),
wake confirmed3761. Merged as **55e0cd8bffb8b854d50bf712f997d32e88911e43**;
API verifies parentsa401db0+571f745 and merge/source treee777d772. This
supersedes166's pending status below.

Recovery81 passed40.13s (+12 new cases); new cases on unchangeda401db0
implementation10 failed/2 passed6.66s. Nine selected mutation groups killed /
13 failing executions with overlap, restored bytes. Real present live/empty
jobs, wrong-session native query and owner death before child persistence are
witnessed. Full clean571f745 **4983 passed/10 skipped/1 failed346.07s**;
sole failure zero-write log-index replace WinError5. Exact test on untouched
mastera401db0 reproduced same error on bounded third attempt (pass2.08s,
pass1.44s, fail1.60s); candidate targeted rerun passed28.14s. These are partial
reruns, not replacement full results or proof of OS cause. Tracked separately
as [168](https://github.com/Decksx/cbz-automation-suite/issues/168); no retry or
log-core fix bundled. Final166 CI BOTH GREEN **4991/3**: push41700387140
448.87s, PR41700398567 479.83s. Actual checkout
96204853fdfa5d0e0528b0fe173a970372d2637b parentsa401db0+571f745, tree
**e777d772ec84924a7a0c8f93273fbf405848951e** equals source by API/log.

[M3d plan167](https://github.com/Decksx/cbz-automation-suite/pull/167) had all
four decisions AGREED by Claude at5517c7913fa8ab6597cbe9591fb454e2addddea9
(PR comment6613486413, hive3766/3784). Codex resumed after usage reset3784,
ACK confirmed3786, admin operational status3788. Notes folded at exact
**bc9a7e73864a5a2e12919fc72e5508177728f32a**: one shared reader per job, bounded
subscriber queues/resume, admission-lock acquisition witness and ~1s idle/cold
cadence; request headroom beyond8streams with ninth JSON-client witness; shared
startup/30s reconciliation pass guard; measured parent/launcher kill-on-close
containment. Additive schema-v1 progress table compatibility must be witnessed
in D3. [Exact notes handoff](https://github.com/Decksx/cbz-automation-suite/pull/167#issuecomment-6615445413),
hive confirmed3789. Relative links/whitespace pass. PR41718759714 green4991/3 in612.56s. Source push41718751020 attempt1
failed4978/3/1 in1055.98s: stalled-running-commit witness expected succeeded,
got uncertain with runner.reason hidden; cause unproved. PR integration includes
166's12 tests while source basea401db0 does not. Attempt2 already in progress
at21:28Z. [CI qualification](https://github.com/Decksx/cbz-automation-suite/pull/167#issuecomment-6615839072),
hive3795; [separate follow-up171](https://github.com/Decksx/cbz-automation-suite/issues/171)
records missing diagnostics/load reproduction, distinct from164/168. No passing
companion or rerun is treated as diagnosis or replacement for failed evidence.
Claude verifies/pinned-merges on green exact-head CI. D1 authorized by agreement
and3784; M4/M6 production submission/interruption gates remain closed.

[D1 draft170](https://github.com/Decksx/cbz-automation-suite/pull/170) exact
**50c504c5fe79d5094c000156eb20d994dfaecf2d**, eight one-file commits from55e0cd8,
branch feat/web-m3d-supervisor in own comic-web-m3d-supervisor worktree. Service
reconciles before new session publication, sequences bounded snapshot pages
without outer admission/native transaction, shares startup/scheduler pass guard,
retains uncertain and never adopts/stops/relaunches. Missing verifier refuses;
internal submit commits once then attempts one fixed runner command using parent
pinned home identity, allowlisted environment and trusted interpreter/repo cwd.
Unconfirmed spawn retains admission/deadline; admitted version stays1. Shutdown
closes admission, bounded-waits actual work and retains server/console guard
until actual worker settlement. Protocol/audit on the comic branch explain limits.

Full clean99e89532c679c6779740820dae7ccfe67004b608: **5004 passed/12 skipped315.36s**,
-n4 --dist loadfile, translation off; baseline4994 cases plus22=5016. Follow-up
41213248c2fefe17dd1e7404befe68141cc61c23 adds one server-close witness only;
latest broader focused **164 passed/2 skipped88.24s**, same code/tests as final
head (final commit appends audit). Local full not repeated after that test-only
addition; final-head CI runs complete candidate. Eleven selected mutation groups
killed/12 failed executions with overlap, source restored byte-equal; includes
readiness, expiry, sequence/cutoff, parent native query, pinned context, pass guard,
unsettled service/server ownership and publication ordering. Final push41721683977
and PR41721694891 pending at this checkpoint; earlier99e8953 checks are historical.

Native host measured in_job=true/current flags0x2800 (kill-on-close/BREAKAWAY_OK).
A real contained-parent fixture refuses before admission and passes. Even a
test-only permitted breakaway leaves a measured outer job; the two positive
clean/abrupt server-death lifetime witnesses therefore skip. Production never
breaks away and refuses any parent job/unknown. Positive proof in a genuinely
uncontained supported fixture context remains required before D1 completion;
no skipped witness is counted as that proof.
[Actionable draft review/native evidence handoff](https://github.com/Decksx/cbz-automation-suite/pull/170#issuecomment-6615852598),
hive confirmed3796; first pushed checkpoint/admin status3793 before40min. Claude
owns independent exact-head review/native-context evidence, Codex findings and
remaining D1 work. D2-D4, M4 registry/admission and M6 controls remain separate.

Independent comic169 review: CHANGES REQUESTED at9062d2c61040d8a9f79fc2a9a31c303538920bae,
R1 tagged literal TPB/year-qualified TPB series become collections. Candidate
104 passed/3 failed54.71s; untouched55e0cd8 all4probes passed0.73s. Submitted
CI41710167235/41710211461 green but missing those boundaries.
[Actionable finding](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6615495187),
hive3792; [durable replay](../../reviews/2026-11-03-comic169-tpb.md). Claude owns
correction/new exact head, Codex re-review; no merge/deployment approval.

Swarm193 exact595a85c38b6325976c37febbd485d2b7fdf353ef merged as
**8f84c3795d4e174c3d32b110deb53ac8ecd5f017**, parents5b961c2+595a85c;
merge/source tree3190d9f6a0d3831d035fe730e5bad5723d13d7bf matches, API verified.
Exact run41698397725 green. Neither follow-up nor plan performs a rollout,
live-library operation or production process restart. D1 remains draft pending native acceptance;
backup164 and suite-wide Translate stubbing remain separate unstarted extras.

## M3c slice 3 recovery candidate (2026-11-03)

Codex accepted delivery3742, ACK confirmed3746/start status3747. Comic
[#165](https://github.com/Decksx/cbz-automation-suite/pull/165), branch
feat/web-m3c-recovery in an isolated own worktree, starts from master
4f9893acae3a0fbb8bc7f40a0ac8c207cac2d240. Candidate 89f205a15bf483c79512b0bc0116a85468bf0d2d;
code/test/protocol ec24e64b918969634fa21cc918eae7b52c2d34a6. Codex owns
implementation/findings; Claude exact-head independent review/pinned merge.

Recovery observes exact runner/child and same-session deterministic job under
admission exclusion; reports cannot be reused as commit authority. Receipt
import rechecks all immutable command/seal/identity fields, canonical shape,
complete index/hash and bounded existing segments, then repeats native absence
and refences the full row/nonce/version in a short transaction. Idempotent
imports never auto-clear durable uncertain. Explicit attributed operator recheck
changes uncertain only to lost/unknown after fresh recorded-owner/child gone and
named-job absent proof. Missing recorded child in an uncertain row remains
blocked; no override. Orphan exit.json.tmp stays preserved and specifically
classified. Pump startup failure records a post-birth reason and still attempts
to persist child identity. Native polling250ms and ledger refresh1s are separate;
main requires the parent admission identity context. M3d authentication/routes/
scheduling/context propagation and M4 production registry/stop gates stay separate.

Verification: focused164 passed, then2 hardened identity/refresh and6 strengthened
native crash/index witnesses passed. New69 tests, existing tests retained.
22 selected mutations killed/30 failed executions with overlap, restored bytes;
two mutation groups bypass redundant boundary checks together. Full results
at clean2436c09:4971 passed/10 skipped/1 failed519.65s, the same untouched
alternating-overflow WinError5 as baseline. All69 added tests passed; count
delta exactly69. One bounded partial rerun passed each tree (3.79s/3.80s),
not replacement full runs or proof of the OS cause. Untouched4f9893a baseline4902 passed/10 skipped/1 failed349.30s,
independently reproducing alternating-overflow WinError5; OS cause unproved.
No source change for that flake and no rollout/live-library/process operation.
[Protocol](https://github.com/Decksx/cbz-automation-suite/blob/89f205a15bf483c79512b0bc0116a85468bf0d2d/docs/web_console_m3c_recovery.md)
and dated development log record API boundaries and replay evidence. Current
status ready/un-drafted: BOTH final-head CI green4979 passed/3 skipped,
push41696715358 in364.06s and PR41696727103 in495.48s. Actual PR checkout
308e6c2edc5c56deea74f0320de3e3e750b7ff2a, parents4f9893a+89f205a,
treeb71beb2a557055d74770131b059a1dd47c890b16 equals source by API/log.
Current master4f9893a; prior2436c09 checks also green.
[Ready exact-head handoff](https://github.com/Decksx/cbz-automation-suite/pull/165#issuecomment-6612735928),
wake confirmed3750 before40min. Fresh Claude review/pinned merge required;
Codex owns findings, no source approval/merge or rollout claimed. Checkpoint pushed as draft at2436c09, hive3748.

Earlier context receipts independently verified:191 exactaa65bc0 merged
95558eb56b21f692bdc10ed72c0bfd51d3d49309, tree
2fdbb669be1e9813a9822184ae39db49ccd3848e equals source;192 exact9ce5d60 merged
5b961c2f9d1e9a016d39d6f952833f3fe9e746ca, tree
4c3663290841d7efae1337ffb339fe2513ac4817 equals source. Comic157 approvedc1d0f5e
is merged4f9893a (API verified), superseding its open status below. Claude's
live deployment4f9893a and David's subsequent GUI/Camelia restart are reported
in hive3718/3719/3722; Codex did not independently deploy or verify live processes.

## M3c slice 2B merged receipt (2026-11-03)

Claude independently approved comic #163 exact
**7919b3a393218d81a766e90d2700bf8756048abd** and pinned-merged it as
**91cae2c26f0e42d574c4dd49caaf1f14397c83fc** at17:25:29Z. Verified via
GitHub API: parents36a1b82+7919b3a; merge tree
**0fc73063ba40d6a73e6cd1d0380161187e56a343** equals approved source and
tested synthetic557a5c5. Both final CI runs green as recorded below. Claude
reports independent -n8 checks129 passed and both revised persistence guards
mutation-killed (hive3686); these are reviewer-reported, not Codex reruns.
Original CI cause remains unproved. This supersedes pending163 status below.

Slice3 recovery/import/orphan-temp handling is Codex's next workstream after
this bounded run; production reconstruction/orchestration remains M3d/M4.
No rollout. #157 exactc1d0f5e is Codex-approved and still open at this snapshot;
Claude owns its pinned merge. Context191 remains the preceding dependency.

## TPB correction approved; M3c follow-up CI green (2026-11-03)

Codex re-reviewed comic #157 at new exact
**c1d0f5e21441eb105fdf5895d35bc39c710c1228**: **APPROVED**, R1 resolved,
no remaining blocking finding. [Actionable verdict](https://github.com/Decksx/cbz-automation-suite/pull/157#issuecomment-6610832373),
hive handoff confirmed3684. Tokenizer equals base20ebcc2; decided-title-aware
Unicode label checks preserve literal titles and retain bare-label guards.
Independent111 passed in57.67s, including all original regression probes;
eight selected mutants killed/12 failing executions with overlap, source
restored and clean. Full local not rerun for this delta. Verified pushCI
41682454572 passed4667/3 and PR41682466262 passed4867/3. Actual integration
**a241d3d8cb2631e749a126a2f9645e65898c4451**, parents36a1b82+c1d0f5e,
tree23229b89dd21b5ecb50362f4608ebbc63ad0878c. Claude owns pinned merge/current
base gates; live availability/Tower rerun separate. [Review record](../../reviews/2026-11-03-comic157-tpb.md)
appends this superseding verdict while preserving the original finding.

Comic #163 exact **7919b3a393218d81a766e90d2700bf8756048abd** now has both
final-head checks green: push41682825046 **4882/3 in375.60s**;
PR41682837268 **4882/3 in386.44s**. Actual PR checkout
**557a5c5ed1967e4f63bd054d7f6c5105d871a530**, parents36a1b82+7919b3a,
tree **0fc73063ba40d6a73e6cd1d0380161187e56a343** equals source by API/log.
[CI receipt](https://github.com/Decksx/cbz-automation-suite/pull/163#issuecomment-6610854434),
hive wake handoff confirmed3685. Fresh Claude review/pinned merge remains
required; Codex owns findings. Original CI failures absent on these runs,
original causes still unproved. This supersedes pending CI below. Context191
exactaa65bc0 remains a separate preceding review candidate at this snapshot.
No merge/deployment/live-library change by Codex; checkpoint before40min.

## M3c slice 2B persistence follow-up (2026-11-03)

Comic [#163](https://github.com/Decksx/cbz-automation-suite/pull/163) now has
exact pushed head **7919b3a393218d81a766e90d2700bf8756048abd**, clean in
comic-web-m3c-supervision, branch feat/web-m3c-supervision. Five one-file
follow-up commits supersede head250f135; code/test/protocol checkpoint
**01f522db2583ca817e4ed95cec2ab9b67ca03f97** differs afterward only by an
evidence append. [Fresh exact-head handoff](https://github.com/Decksx/cbz-automation-suite/pull/163#issuecomment-6610682191)
assigns Claude fresh review/pinned merge after green final-head CI, Codex findings.
No rollout or production tool reconstruction is enabled.

Age alone while persistence is pending now produces diagnostic waiting and
retains ownership/native supervision. Actual persistence errors or unknown
native/log proof remain sticky uncertainty. Production descendant, drain and
cleanup deadlines are unchanged. Normal-success fixtures now use production
cleanup budgets and include reason, phase, budgets and events on failure;
short deadlines remain explicit only in deadline witnesses. A deterministic
slow-publisher witness failed old code with PERSISTENCE_TIMEOUT:publish and
passes this head. A separate witness proves native uncertainty during that
wait cannot be cleared by a late receipt. This proves the policy correction,
not the unexplained uncertainty in original CI41674738395.

At checkpoint01f522d: **43 focused passed in37.32s**; concurrent runner plus
50MiB/eightMiB log load **45 passed in35.32s** (-n8 --dist loadfile);
**20 selected mutants killed /23 failing executions** with overlap, source
restored byte-equal; full clean suite **4,875 passed /10 skipped in359.14s**
(-n4 --dist loadfile). Diff whitespace check is clean. Neither original CI
failure reproduced locally. Final-head push41682825046 and PR41682837268
were still running at this checkpoint; no final CI success is claimed here.

The unrelated backup collision fixture is tracked separately as
[comic issue164](https://github.com/Decksx/cbz-automation-suite/issues/164).
A two-case control on unchanged20ebcc2 passes with fixed identical ZIP dates
and deterministically reaches the old assertion failure when only the third
ZIP timestamp differs. Production dedup is byte-based; do not weaken it.
Original failed CI ZIP bytes were not retained, so this plausible fixture
mechanism is not claimed as that run's proven cause. No backup change bundled.

Swarm [#190](https://github.com/Decksx/agent-swarm/pull/190) approved exact
35018be09f57547d8832452efadce467f811373f merged as
**95b9715d41c8684ce93279488f3cb2ade48f0c9a**; all four checks passed and
merge/source tree **29f3c5f8640c7ca237b101b7a8df0d160af34f9e** matches by API.
Its #157 verdict below remains correct for6fbf30f. Claude supplied new head
**c1d0f5e21441eb105fdf5895d35bc39c710c1228** in hive3676/3679, reporting a
title-aware Unicode label check and tokenizer revert. Codex re-review is next
once its CI is green; this entry does not approve the new candidate. Tower
plan rerun remains blocked on review/merge/live availability. M3c slice3
recovery/import/orphan-temp handling follows2B; M3d/M4 remain separate.

## Comic #157 bare-TPB review (2026-11-03)

Codex completed delivery #3640 (ACK confirmed #3667): **CHANGES REQUESTED**
at exact **6fbf30fd93bdb0fb1bc3132c93c7bae1805d4cc7**.
[Actionable R1](https://github.com/Decksx/cbz-automation-suite/pull/157#issuecomment-6610146450),
mirrored #3669, wake handoff #3670. Claude owns correction/new exact head,
Codex re-review. No merge/deployment or Tower-plan rerun by this review.

P2 R1: TPB inside a confirmed series title becomes collection evidence.
TPB Tales.cbz with matching folder/ComicInfo title and Number3 is renamed by
the real planner and watcher to v03 (TPB), instead of issue #003. Already
canonical TPB Tales #003 is held/refused. Series TPB reproduces in the planner;
ASCII lookarounds also match inside éTPB / TPBé. Six planner and two watcher
regressions fail this head and pass unchanged base20ebcc2. Preserve TPB consumed
by the decided title and recognize actual labels outside it; keep the new
Number/Volume/no-default/conflict guards.

Existing media/caller82 passed; seven selected guard bypasses all killed,
14 failing executions with overlap, source restored byte-equal. Independent
full clean-head suite **4,644 passed /10 skipped in300.74s**. These passing
repository tests omit the eight external R1 witnesses. Old CI4651/3 at head
and synthetic29cb27d9 (base20ebcc2) is green; current synthetic aa8df451
integrates36a1b82 and has a different tree, not covered by those old checks.
[Maintained review](../../reviews/2026-11-03-comic157-tpb.md) records exact
commits, current CI qualification and external fixture/mutation replay.

Context #189 head d1752a00a548aaf1dc5c83177a30a25886fea217 merged as
**f4cd4e75926cb4c73aa029850c8fd61cce9c4b20**, all four checks green;
tree **d8ce54ac651eefde041d760242b796238e2b949f** equals source, verified by API.
This supersedes its pending status below. Comic #163 head250f135 remains
unmerged: PR integration4881/3 passed, but push41674738395 failed2/4879/3
(normal runner success ended uncertain; backup collision fixture also failed).
Current assertion does not reveal the uncertainty reason; Codex owns
diagnosis/new head. No claim of a proven Windows/timing cause or rollout.

## M3c slice 2B supervision candidate (2026-11-03)

David restarted work through delivery #3636, ACK confirmed **#3639**;
Codex plan confirmed #3641. Slice 2A [comic #162](https://github.com/Decksx/cbz-automation-suite/pull/162)
approved head **e07b94dd60eb5ebecb03826e62eb8e215a2ce869** is merged as
**36a1b82cb9dbdd3d890e55b95fec6d1159592de7**, tree
**93d066975832d0ed27d474db4b2177a6db6f5e30** equal the approved source.
Context [#188](https://github.com/Decksx/agent-swarm/pull/188) head
00e0a41512d05c301466d7e8d74fff00a4d526a0 is merged as
**5e6c14a8c17d9020e7059ec0bd6e6049635c21e8**, previously verified tree parity
and all four checks green. These receipts supersede pending wording below.

[Comic #163](https://github.com/Decksx/cbz-automation-suite/pull/163) is ready
for Claude's independent review at exact
**250f135f19a7bb17955a617d9011635c82f62ff9**, nine one-file commits from36a1b82.
Implementation/test/protocol checkpoint **a18ae548266259e02918658c31364385bd10490b**
is unchanged afterward; only its dated evidence record was added. Codex owns
findings, Claude owns exact-head review/pinned merge after final-head CI.
[Actionable handoff](https://github.com/Decksx/cbz-automation-suite/pull/163#issuecomment-6609604873)
names the exact head and checks. Branch feat/web-m3c-supervision, isolated
worktree comic-web-m3c-supervision; checkpoint pushed and confirmed hive
#3654 before the relay deadline.

The runner claims/launches once from trusted reconstructed and freshly hashed
interpreter/source/registry seals; no production registry exists. Post-birth
ledger/receipt I/O runs off the native poller. Root exit starts descendant
10-second grace independently of EOF, followed by a 30-second zero-proof bound;
reader drain and cleanup have separate 5-second budgets. Unsettled I/O retains
claim/handles. Failed writers keep the reader draining/discarding; recovered
writes cannot clear uncertainty or restore EOF. Stop policy is wait-only;
requests/log errors cannot force-kill a live writing root. Native job names
use the shared helper. The CLI takes only job ID/nonce, no argv/registry option.

Focused **42 passed in26.64s**. Full local on clean a18ae54:
**4,874 passed /10 skipped in376.92s**, +42 cases over prior product/test baseline.
Nineteen selected mutants killed, **22 failing executions with overlap**;
source restored byte-equal. Real disposable Windows witnesses include 4MiB
written after writer failure and owner death after claim, after birth/before
running commit and after receipt/before terminal commit. Push CI41673108329
at exact a18ae54 is SUCCESS: **4,881 passed /3 skipped in417.04s**. Final-head
push/PR CI remains separate; the PR comment will carry completion receipts.

An earlier related focused run hit log-index replace WinError5. Unchanged base
reproduced it on bounded rerun4 (same tree e07b94d/36a1b82); cause remains
unknown. It did not occur in the final local full run; no diagnosis/fix claimed.
[Protocol](https://github.com/Decksx/cbz-automation-suite/blob/250f135f19a7bb17955a617d9011635c82f62ff9/docs/web_console_m3c_runner.md)
and [evidence](https://github.com/Decksx/cbz-automation-suite/blob/250f135f19a7bb17955a617d9011635c82f62ff9/docs/development_log_2026-11-03_m3c_supervision.md)
record limits and external replay paths. Slice3 recovery/import/orphan temp
handling, M3d server/recheck/routes and M4 production adapters/stop gates remain
separate. Board98 stays in progress. No live library action, deployment,
production tool launch or relay/Codex-state change; no operator input needed.

## M3c slice2A live-owner receipt candidate (2026-11-02)

Delivery #3495 acknowledged as confirmed hive **#3497**. Comic #159 approved
head55260768ab428c5fba095de9a01534a85ad3bffa merged as
**080e39d5a644b67c9df1b2d55d8e222b21995935**, tree
**ba9d1a2394231ffc25682e580fccb840dc5675bd** equal the previously tested
synthetic integration. Swarm #187 head5263bfa9833fa956af00bb7edfaa0ce5ca1946b2
merged as **289c334b0f708f520775c06c26837cd43c7d0753**, all four CI checks
SUCCESS; merge/head tree **772b5b2d357e025cff6660bb69000727d56f1dca** equal.
These receipts supersede the pending merge language below.

Codex started slice2 from080e39d. [Comic #162](https://github.com/Decksx/cbz-automation-suite/pull/162)
is the first review checkpoint at exact **e07b94dd60eb5ebecb03826e62eb8e215a2ce869**,
eight one-file commits. Code/test/protocol checkpoint
**7c853b713aa4e42ecea9dcb475450c719ad155d1** is unchanged afterward; only the
dated evidence record was added/updated. [Actionable review handoff](https://github.com/Decksx/cbz-automation-suite/pull/162#issuecomment-6589939943)
names Claude next owner for exact-head review/pinned merge after green CI.

Store APIs authenticate the live exact claim/nonce/runner/state/version and
physical lock, validate the immutable command, and atomically record running,
pre-birth refusal or terminal state/event. Receipt publication is checked
write/fsync/atomic replace/readback; finalization repeats actual owned root
exit/empty-job and settled LogPump/complete pinned-index proof. Both require
fresh trusted outcome mapping; JSON cannot choose success. Late receipts
cannot auto-clear uncertain. Stop intent/outcomes currently refuse. Native
environment sorting is corrected to uppercase order with a direct witness.

Focused store/receipt/native **136 passed in40.75s**. Full local suite at7c853b7:
**4,832 passed /10 skipped in375.81s**, including54 added cases (53 receipt,
1 native environment). The prior alternating-overflow WinError5 did not
reproduce; cause remains undiagnosed. Nineteen selected mutants killed,
31 failing executions with overlap, source restored byte-equal; diff-check
clean. No production native launch, library operation or rollout.

This is **slice2 checkpoint A, not completed runner supervision**. Native
fixtures exercise the store/receipt boundary; no runner entry point, LaunchSpec
builder or production adapter/route is enabled. Synchronous publication may
stall. Checkpoint B still owes responsive native supervision, post-birth commit
failure, descendant/drain deadlines, stop gates, bounded cleanup and the
failed-writer child writing beyond the pipe buffer while its reader drains
and discards. Slice3 recovery evidence and M3d/M4 remain separate. Final-head
CI and independent review are pending at this checkpoint; final receipts go
on #162 and this context PR. Codex owns findings and then checkpoint B.
[Protocol](https://github.com/Decksx/cbz-automation-suite/blob/e07b94dd60eb5ebecb03826e62eb8e215a2ce869/docs/web_console_m3c_receipts.md);
[dated evidence](https://github.com/Decksx/cbz-automation-suite/blob/e07b94dd60eb5ebecb03826e62eb8e215a2ce869/docs/development_log_2026-11-02_m3c_receipts.md).

## Comic #159 approved after root-guard repair (2026-11-02)

Delivery #3484 acknowledged as confirmed hive **#3488**. Codex independently
APPROVED exact **55260768ab428c5fba095de9a01534a85ad3bffa**; all prior R1/R2
findings are resolved, superseding the changes-requested status below.
[Actionable review](https://github.com/Decksx/cbz-automation-suite/pull/159#issuecomment-6588699716),
[CI tree qualification](https://github.com/Decksx/cbz-automation-suite/pull/159#issuecomment-6588718672),
confirmed hive **#3490**, board97 updated. Claude owns the exact-head pinned
merge and merge/tree receipts. Approval is for this source head only.

Scandir listed evidence permits a vanished root child to be attributed only
when it was a plain, plannable directory. Files, internal/protected folders,
reparses and unavailable evidence refuse; unrequested confirmed series folders
stay outside named scope. Fresh lstat still supplies inventory identities.
Planner/executor194 repository cases plus six external root-refusal cases:
**200 passed in139.56s**. Eight additional real-junction/unavailable-evidence
cases passed in3.17s. Six individual mutants killed (6/2/2/2/2/4 failures,
overlapping test populations), restored byte-equal; clean review worktree.
Strict JSON matches base b127b4f on one 9,403-byte fixture, not universal proof.
[Maintained review](../../reviews/2026-11-02-comic159-scoped.md) records replay paths,
qualifications and two nonblocking comment nits. No independent full local
repository rerun; author4,746passed/10skipped remains attributed.

Push CI41525851832 tested exact55260768ab428c5fba095de9a01534a85ad3bffa:
**4,753 passed /3 skipped in402.08s**. PR CI41525860866 tested synthetic merge
**e4c82d9520dd0d69b413a9b9bbfece98a1a60d60**, parents4dbb7d3 +5526076,
tree **ba9d1a2394231ffc25682e580fccb840dc5675bd**:
**4,785 passed /3 skipped in355.54s**. Both SUCCESS, but different tested
trees; checkout logs/commit API verified. This covers integration with native
slice1 as well as the branch head. Global DB snapshot guard remains for B2.

Swarm #186 exact605ce081d37009e15ca52b7e2ffefd44b5d24333 merged as
**70a22c5c7a7e2c2b49b68be5010da7015be7e8f7**, all four checks green;
merge/head tree **5be10c1947f18225f7ba791d0e3dc6bfd56fbe53** verified equal.
No production library operation, sync/cutover, rollout, relay or Codex-state
change. Codex's web work remains M3c slice2 next.

## Comic #159 re-review and native-slice merge receipts (2026-11-02)

Codex acknowledged delivery #3462 as hive **#3477**, then independently
re-reviewed exact **21fb800343f5915c9e64de5900f97b02d0201b36**:
**CHANGES REQUESTED**, one P2 root-observation regression. Ordinary series
races now pass and R2's family/quarantine and unchanged filters each fail
their new named witness when bypassed. A first-walk vanished root loose
file/history/protected-originals directory instead becomes a guessed series,
or disappears entirely from observation with named scopes. Six deterministic
refusal witnesses fail at this head, and all six pass against e7f3cc9 source.
Claude owns the root guard/test/protocol follow-up; no merge agreement.
[Actionable re-review](https://github.com/Decksx/cbz-automation-suite/pull/159#issuecomment-6588332364),
confirmed hive **#3480**, board97 updated; [maintained detail](../../reviews/2026-11-02-comic159-scoped.md).

Planner/executor181 repository cases plus six original external probes:
**187 passed in120.44s**. Both full CI41516549172/41516537699 are SUCCESS
at21fb800. Strict full JSON matches base b127b4f on one three-book fixture
(9,403bytes this run), not universal parity. Four individual guard bypasses
cause1/1/6/2 named failures; the vanished-selection bypass's six failures
are on exact-reason assertions. Prior source fails all six new series-race
cases. All product mutations restored byte-equal; review tree clean/pinned.
No independent full repository run; author4,733passed/10skipped attributed.
No live-library action or rollout.

Separately, delivery #3459 was acknowledged as **#3473** and superseded by
completed slice1: Comic #161 approved head **3c938f4b2833e4d3f94a4f8f211d398cbeb4c4ce**
merged as **4dbb7d3c466b80bb2a5c46540d992ec5532bb384**. Merge tree
**3ea689a7fe74229de49175bb5fe4891d3a371b5c** equals approved head; both
exact-head CI41521824594/41521814876 SUCCESS (4,746passed/3skipped each).
Context #185 head **50b85253128fae4558af26777f7d20330beffaae** has all four
checks green and merged as **1c6d6a6ec4efa5f8106216b12cea327e6d1ff06e**;
merge/head tree **78bcea3da508986c40894b9dba4b3e024cc2ded9** verified equal.
This supersedes the candidate/pending language below. Claude owns those
merges; Codex verified receipts. Slice2 remains next, with review notes:
use upper() for Windows environment sorting; prevent concurrent unrelated
launches while the write handle is inheritable; closing a collided job
handle can affect kill-on-last-close lifetime. No rollout.

## M3c slice1 native candidate (2026-11-02)

Codex acknowledged relay #3454 as confirmed hive #3463 and implemented from
the agreed contract merge **f09fcfcb9bfa276ecc99416aa796a743c7dbfc02**.
[Comic #161](https://github.com/Decksx/cbz-automation-suite/pull/161) is at
exact **3c938f4b2833e4d3f94a4f8f211d398cbeb4c4ce**, ten single-file commits.
Four initial code/helper/test/protocol commits reached
**d257487836a442eb39e001612973650942ed50d8**; later follow-ups refine tests/
helpers and evidence, with product source unchanged.

The internal win32 adapter owns a private noninheritable kill-on-close job,
uses JOB_LIST/HANDLE_LIST at birth, and transfers/closes process, thread,
pipe, CRT, attribute-list and security-descriptor resources. No uncontained/
suspended fallback. Named/denied/wrong-type collisions stay uncertain.
Exceptional native return recovers raw PROCESS_INFORMATION handles and
marks possible child birth. FILETIME/session observations distinguish alive/
gone/unknown, immediately close query handles and never adopt/kill a PID.
A retained owner can request job termination, but policy/finality remain
later runner responsibilities. No ledger or HTTP wiring is enabled.

OfficePC probe: Python3.11.3 AMD64, Windows build26200, session1,
TokenIsElevated=0 and TokenElevationType=3 (non-elevated filtered token).
The witnessed tree held two Python and two conhost processes; tests verify
actual identities plus whole-job zero/absence instead of a guessed count.
Owner death is measured after factory return and after CreateProcessW before
identity returns, with explicit atomic ready/release handshakes. No in-kernel
API interruption is claimed. Wrong-session/denial queries cannot prove absence.

Final native file: **32 passed in2.58s**. Thirteen failure boundaries include
CRT transfers and post-birth exceptions; raw returned handles are checked
independently of Python wrappers. Eleven selected mutants caused twelve
named failures, restored: omitted job/list inheritance/kill-on-close,
collision bypasses, birth classification/raw-handle cleanup, noninheritance,
denial/namespace handling. Refined helper/mutation checks were replayed.
Negative probes terminate only their own random fixture job after their own
identity handshakes; recent fixture identities are gone.

The local full -n4/--dist loadfile run started at d257487 and completed
**4,737 passed /10 skipped /1 failed in495.81s**, including all31 then-current
native cases. Sole failure is the already recorded OfficePC alternating-
overflow WinError5 at index replace, candidate offset442. Log source and that
test are unchanged from M3b; cause remains undiagnosed. No clean local full
pass is claimed. Test-only follow-ups add physical alias-safe sentinel
identity, process-count/expiry/owner-alive refinements, create-call counts,
bounded negative cleanup and one real missing-executable case (32native now).
Product code remains unchanged. Final exact-head full CI is pending at this
checkpoint; readiness and final receipts go on #161 and this context PR.

[Native API/probe protocol](https://github.com/Decksx/cbz-automation-suite/blob/3c938f4b2833e4d3f94a4f8f211d398cbeb4c4ce/docs/web_console_m3c_native.md);
[daily evidence and qualifications](https://github.com/Decksx/cbz-automation-suite/blob/3c938f4b2833e4d3f94a4f8f211d398cbeb4c4ce/docs/development_log_2026-11-02_m3c_native.md).
Claude owns independent exact-head implementation review; Codex owns findings.
Slice2 still owes trusted launch reconstruction, claims/store/receipt
finalization, descendant/drain timing, failed-writer beyond-pipe-buffer
witness and recovery integration. M3d scheduling/routes and M4 production
adapters remain separate. No merge, rollout, production library operation,
relay or Codex-state change by Codex. Slice1 uses disposable native fixtures.

## M3b merged, M3c agreement and scoped-plan review (2026-11-02)

GitHub independently confirms Comic #156 reviewed head
**19324e9c3de6030a346c7d064fa48c584fc40eca** merged as
**b127b4f166b558ab275abd2b20e4759950c67257**, and context #183 head
**7d11b758718364f11971a0b5c229863d31e0fd37** merged as
**29f22f0e1de973092f6fa277cf5ed9f000a72a68**. This supersedes the pending
review wording below. Claude's #3439 reports tree parity, R1 closed and
348 web tests passed; those reviewer-local measurements remain attributed.
No M3 rollout is claimed.

David's #3440 assigns Claude the X-primary migration blockers, while Codex
keeps the web console. Claude opened #158 and owns scoped planning then the
incremental catalog. Writer coordination across watcher/decensor/apply needs a
shared contract before enabling writing tools. #108 remains the separate
read-only transfer preview/post-sync verifier and later cutover track.
[Coordination and fixture requirements](https://github.com/Decksx/cbz-automation-suite/issues/158#issuecomment-6586314379);
confirmed hive #3447. No live library or sync control was changed.

M3c plan-first draft [Comic #160](https://github.com/Decksx/cbz-automation-suite/pull/160)
is at **7536e031529c01bb0ad2ba5aeb44826b3fa7587e**, two single-file doc
commits from b127b4f. Claude agreed all four decisions at original
**3d9b5cc1b809aca8b7ffa69b867ecb454f0073fc** (#3454 and PR comment).
The follow-up folds in its required invariants: a failed writer cannot stop
pipe draining/discarding while a writing tool continues, with a slice-2
more-than-pipe-buffer witness; read-only log/drain uncertainty still blocks
admission until M3d's explicit acknowledgement/recheck with fresh proof.
M3c supplies native ownership/evidence and conditional store APIs; M3d owns
orchestration/routes, M4 production adapters. Named collisions remain uncertain
and log failures cannot bypass writing-tool interruption gates. Completion
ports are optional; bounded polling remains v1. No native code/probe acceptance
or production route is claimed. Diff-check passes; latest doc-head CI is
pending at this checkpoint, with final receipts on #160. Codex's next work is
slice1 native adapter/fixture probes; Claude reviews each exact code head.

Codex reviewed draft [Comic #159](https://github.com/Decksx/cbz-automation-suite/pull/159)
at exact **e7f3cc934c9eb254c4d672bce5654ba4d7ebc8f3** (base b127b4f):
**CHANGES REQUESTED**, R1 enumeration races still abort unrelated scopes, R2
family-drop/unchanged-drop correctness filters lack direct scoped witnesses.
Actionable [review](https://github.com/Decksx/cbz-automation-suite/pull/159#issuecomment-6587074606)
and confirmed hive **#3455** name Claude as next owner. No merge until agreement.

Independent evidence: planner/executor172 passed in126.41s. Strict-mode complete
JSON matches the base byte-for-byte on one three-book fixture (9,411bytes,
ordinary rename plus a family); not a universal equivalence claim. Both
pinned-head CI runs41512146589/41512137498 were green. No independent full
repository rerun: author4724passed/10skipped remains attributed. Six new
fixture probes give4passed/2failed in4.61s: actual file/folder moves between
the final enumeration and lstat produce WinError2 rather than only skipping
Beta. Family/unchanged filters each survive all18 existing scope-selected
cases; each new direct witness fails under its corresponding mutation.
Root-refusal and named-walk bypasses are independently killed (3 and1 failures).
Sources restored clean. Conservative root refusal and collision-before-drop
are accepted; explicit-root and retained collision-hold probes pass. Global
WAL commit refusal remains an explicit B2 limitation, not relaxed here.

[Maintained review detail](../../reviews/2026-11-02-comic159-scoped.md).
The review scratch is pinned under Codex worktrees; it can be removed once
the review is complete and the copy is clean, inactive and unbound. No merge,
rollout, production data operation, relay or Codex-state change by Codex.

## M3b R1 writer-validation follow-up (2026-11-02)

This supersedes the pending review at 9b8a938 below. Claude requested changes
for measured per-chunk full inspections in Comic #156 (review comment
6584982033, relay #3421; confirmed Codex ACK #3423 and progress #3427).

New Comic candidate **19324e9c3de6030a346c7d064fa48c584fc40eca** is six
single-file follow-ups. Source/tests/protocol were verified at
**cc90ef094d15f5f31a76a486b0b306096db1f60e**; the final commit only adds the
daily evidence record. The full state/config/containment/ledger-pin check
remains under admission at writer creation. Streaming validates the physical
home identity, home/selected-path/parent privacy, reparse components and open
claim without full scans or ledger/config reads. Watcher AST parsing caches
the most recent source bytes, so edits invalidate it even with unchanged
size/timestamps.

The real create_writer witness persists 8 MiB in 128 x 64 KiB chunks with exact hash,
no gaps and exactly one full inspection. Adapter/config 45 passed in 27.50 s
(nine added cases). Five selected mutations caused nine named failures and
were restored: repeated full inspection, identity, selected privacy/reparse,
closed claim and parse-cache guards. An additional mid-job StateDirRefused
witness leaves 6 durable bytes from 11 read, incomplete and unknown_tail after
uncertainty is recorded. M3c must classify boundary refusals as uncertain,
stop/cancel as needed and retain the claim until both threads settle.

Append-only private-home measurements: 20 x 1,024 bytes in 0.8697 s and 20 x 65,536 bytes
in 1.1649 s; creation/finish excluded. These are host measurements, not guaranteed
throughput or a controlled before/after benchmark. The count is the contract.

At final Comic head 19324e9, both Windows full CI runs passed
**4,714 tests /3 skipped**:
[41502080927](https://github.com/Decksx/cbz-automation-suite/actions/runs/41502080927)
in 427.65 s and
[41502093875](https://github.com/Decksx/cbz-automation-suite/actions/runs/41502093875)
in 294.75 s. Counts reconcile to nine added cases.

The local full run began at cc90ef0 and source/tests remained byte-identical
through 19324e9. It completed **4,706 passed /10 skipped /1 failed in 1,167.62 s**.
The only failure is the exact alternating-overflow test reported by Claude:
WinError 5 at os.replace(index.tmp,index.json), candidate offset 742.
The bare LogDisk implementation and that test are unchanged by R1. This is a
current Codex reproduction of the reported host exception; its underlying
cause remains undiagnosed. No clean local full pass is claimed. All new
adapter/config cases and the existing 50 MiB/cancellation cases passed in that
full run.

Claude's OfficePC alternating-overflow WinError 5 at 9b8a938 is explicitly
recorded as an environment exception (his 338 passed / 1 failed review result).
The earlier f0b709f zero-write failure was independently reproduced by Codex.
The cause remains undiagnosed; no Defender/ACL/indexer explanation or new retry
is claimed. The reviewer offered either a bounded test retry or recording the
exception; this follow-up deliberately chooses the latter.

[Protocol and refusal semantics](https://github.com/Decksx/cbz-automation-suite/blob/19324e9c3de6030a346c7d064fa48c584fc40eca/docs/web_console_m3b_logs.md);
[R1 evidence and host exception](https://github.com/Decksx/cbz-automation-suite/blob/19324e9c3de6030a346c7d064fa48c584fc40eca/docs/development_log_2026-11-02_m3b_r1.md).
Exact-head CI/readiness receipts and actionable handoffs go on #156/#183 and
in hive. Claude owns fresh review of #156, then pinned merge of #183 after it;
Codex owns findings and later M3c. No merge, rollout, production data access,
relay or Codex-state change occurred in this correction.

## M3b restart and test-only CI correction (2026-11-02)

David restarted the project via relay #3394; Codex acknowledged as confirmed
hive **#3396**, started in **#3397**, and checkpointed in **#3406**. This
supersedes the October 27 night stop. Comic #156 and context #183 were both
drafts at restart; Claude owns fresh exact-head review of #156, then pinned
merge of #183 after #156. Codex owns findings and later M3c.

Comic candidate **9b8a93873dd77392928912196ecae98f241f56d7** appends two
one-file commits to f0b709f: test correction
**3fa4c7aab2e71540522b831c151aca939f0b1fbc**, then its evidence document.
All production source is byte-identical to f0b709f. Failed original exact-head
CI40616463908 was **4,703 passed /3 skipped /1 failed**, not green: the50MiB
test called cancellation-capable join(30) immediately, imposing a throughput
deadline before EOF. At failure it had read37,879,808 and persisted37,355,520
of52,428,800 bytes with error=None. Its companion40616450549 passed.

Controlled healthy per-chunk delay reproduces the original failure
(one failed in50.51s) and the corrected witness passes with exact-byte/restart
checks (one passed in102.09s). The fixture now waits for finite capture under
an independent180s test watchdog before the bounded5s cleanup join. Production
join/cancellation limits are unchanged. Bypassing that wait kills the new
deterministic ordering test (one failure); restored clean scratch copies were
removed. Focused three critical cases pass; all50 log tests pass in31.49s.

At3fa4c7a both Windows full CI runs **41491498875/41491510758** pass
**4,705 tests /3 skips** (348.01/358.69s), exactly one new regression case.
The local full completed **4,697 passed /10 skipped /1 failed in425.51s**:
the50MiB witness passes, but the zero-write test encountered WinError5 replacing
its index. The unmodified f0b709f checkout independently reproduces the same
index-replace access denial without injection; focused current rerun passes.
Its underlying host cause remains undiagnosed. No clean local full pass or
antivirus/ACL fix is claimed. The document records both outcomes explicitly.

The final comic commit changes only documentation after the measured test
head; latest-head CI is running. Both PRs stay draft until their updated heads
are green; readiness and final exact-head receipts go on their PRs and in hive.
[Diagnosis, reproduction and qualifications](https://github.com/Decksx/cbz-automation-suite/blob/9b8a93873dd77392928912196ecae98f241f56d7/docs/development_log_2026-11-02_m3b_ci.md).
The earlier full implementation/21-guard measurements below retain their own
candidate binding; they are not relabelled as new campaigns. No merge, live
archive/database/watcher change, deployment, relay configuration or Codex-state
edit occurred. This is lead-run engineering, not a controller verdict.

## M3b implemented and handed to Claude for review (2026-10-27)

Codex resumed on relay #3379 (confirmed ACK **#3381**) from comic master
**20ebcc26989ebabd8f65b6fe6363edabeec64470**. This is the verified #155 merge;
its tree **d8b2fd4693cfa48653d8b24228a98cf7a9dff25a** equals reviewed eeaeacf,
and exact-head CI **40607740992/40607744931** both succeeded. #153 is CLOSED;
Codex agrees both halves are complete. Board 94/95 are done. The earlier
pending #155/#153 wording below is historical and superseded.

New comic [#156](https://github.com/Decksx/cbz-automation-suite/pull/156)
implements M3b at exact **f0b709f53bc3598d50e12381e45a6ead551b1446**, sixteen
one-file commits from that master. [Handoff 6458372734](https://github.com/Decksx/cbz-automation-suite/pull/156#issuecomment-6458372734)
and confirmed hive **#3384** give Claude independent exact-head review and
pinned merge ownership on green CI. Board **96 is review**, parent36 updated.
Codex owns findings and then M3c after this dependency lands. Exact-head CI
**40616450549/40616463908** is running; no approval/merge is claimed.

M3b supplies a nonblocking bounded queue, independent pipe reader/disk writer,
contiguous retained segments, compact gaps and durable coverage/EOF metadata,
raw-byte cursor codec, bounded UTF-8/JSON paging, advisory progress parsing,
native READ/WRITE/DELETE-shared readers and best-effort I/O cancellation.
JobLogs binds writers to matching live claims and validates selected private
hot/cold paths. Archive member size/digest pins commit with pointers/events
and are immutable. Two adjacent cached members avoid rotation rehash thrashing;
byte/member batch packing makes progress with many small retained log files.

Two format refinements need Claude's explicit review: compact atomic index.json
replaces the design sketch's gaps.jsonl, and cold log pages authenticate selected
members against independent ledger pins instead of hashing unrelated batch
bytes. Original command/cleanup APIs retain whole-seal verification. Legacy
batches without member pins refuse the fast path; no evidence is backfilled.
[Protocol](https://github.com/Decksx/cbz-automation-suite/blob/f0b709f53bc3598d50e12381e45a6ead551b1446/docs/web_console_m3b_logs.md).

Final full at **bfa57ef428740c3e2a5acd9610f6ebf531c73bc3**:
**4,697 passed /10 skipped in282.62s**, exactly65 added cases versus the
retained4,632 baseline. Both real-browser tests pass. Skips remain one absent
routing config, two deliberately unreadable corpus cases and seven Windows
symlink-privilege cases. Windows/Python3.11.3, four workers/loadfile; translation
unset. Earlier focused b51d552: **64 passed in29.08s**; after packing fix,
its regression plus all15 service cases **16 passed in24.70s** (overlap).
The final commit adds only the daily verification log; source/tests are
byte-identical to the measured full candidate. No redundant rerun of unchanged
code is attributed to the documentation head.

All **21/21 selected mutations** failed named witnesses at bfa57ef (23 failing
cases total); sources restored and clean inactive scratch removed. A8/A15 from
#155 are directly covered and killed: codec ledger/manifest command mismatch,
and a deterministic real admission-lock interleaving before runner-lock open.
Other witnesses include a paced50MiB producer without a server, exact persisted
bytes/restart paging, a1MiB line, invalid UTF-8, partial/zero writes, stalled
storage, safe replay, bounded alternating gaps, retention-before-unlink, native
sharing, corruption without fallback and cache/member-budget bounds.
[Daily log and named guards](https://github.com/Decksx/cbz-automation-suite/blob/f0b709f53bc3598d50e12381e45a6ead551b1446/docs/development_log_2026-10-27_m3b.md).

M3c owns native tool containment/finalization and must retain claims until logs
settle; unproved cleanup stays uncertain. M3d owns protected polling/SSE,
durable progress cursor/events, lifecycle hooks and idle archive byte/time
budgets. M5 renders continuation markers. M4 production submission stays
unwired. All operations used disposable fixtures; no live archive/data change,
watcher/GUI rollout, production run route, relay configuration or Codex-state
change occurred. This is lead-run engineering, with no controller verdict.

## Successor resumes comic history #153 and hands off #155 (2026-10-27)

Codex acknowledged relay delivery3360 as confirmed hive **#3362** and resumed
the clean comic worktree `comic-web-history-153` at
**873dc8cd8eb8d0f59dc9140effe57a0c029678ab**. The five interrupted-run commits
were inspected, each one file: scoped privacy/runner locks5130a03,
missing-source verification b6f2367, ledger-first history d53ce93,
history tests c12a115, protocol873dc8c. They are now pushed with one
documentation-only verification commit as exact comic
[#155](https://github.com/Decksx/cbz-automation-suite/pull/155) head
**eeaeacf937e1f140df58455ffdb42b0e025001ad**, ready for review.
[Actionable handoff6457138545](https://github.com/Decksx/cbz-automation-suite/pull/155#issuecomment-6457138545)
and confirmed hive **#3363** give Claude exact-head review and pinned merge
ownership on green CI. Codex owns findings and then M3b after this dependency.

Fresh verification at873dc8c: **137 focused passed in100.71s**;
**4,632 full passed /10 skipped in305.83s**, Windows/Python3.11.3,
four workers/loadfile, both real-browser tests passed. Skips: one absent
routing configuration, two deliberate unreadable corpus cases, seven Windows
symlink-privilege cases. CBZ_TRANSLATION_ENABLED was unset for these runs.
The default Miniconda interpreter lacked pytest; all actual verification used
C:\Python311. The final head changes only the daily verification document;
executable source/tests are byte-identical to the measured head. CI on the
new exact head is pending, and no independent approval is claimed.

All **15/15 selected guard mutations** failed named witnesses, with17 failing
cases total; source bytes restored and the clean inactive scratch worktree
removed. A fresh1,001-job/>2,000-entry test restarts, creates five batches,
leaves200 hot jobs and reads a cold command. Privacy checks stay **19/19**;
sampled get70.338/130.070ms under concurrent suite load. The stable claim is
bounded filesystem-check count, not constant SQL cost or total-history size.
The committed [daily log](https://github.com/Decksx/cbz-automation-suite/blob/eeaeacf937e1f140df58455ffdb42b0e025001ad/docs/development_log_2026-10-27_history153.md)
names every selected witness and measurement qualification.

History seals private immutable ZIP batches, verifies them against hot and
ledger evidence, commits immutable pointers/archive events, then removes hot
copies. Cleanup re-verifies committed batches and remaining sources; corrupt
hot/cold evidence refuses without fallback. No audit row/event is deleted.
The #154 helper is incorporated unchanged. M3b cold log paging, M3c native
terminal proof and M3d idle maintenance scheduling remain. M4 production
submission is still unwired. No live archive/data operation, watcher/GUI
rollout, relay rebind or Codex-state change occurred in this resume turn.

## M3a implemented and handed to Claude for review (2026-10-27)

Codex delivered comic [#152](https://github.com/Decksx/cbz-automation-suite/pull/152)
at exact **d6f3eaf00801e8b3bf45bfd869b17ed72d95d91e**, tree
**4952db77b8f3dcb58603e2b690ba9f19bcf562ac**, twelve single-file commits
from M2 merge **8f1f0ffe3443e38e4224964b2a1c5e8564e08973**.
[Handoff 6455357243](https://github.com/Decksx/cbz-automation-suite/pull/152#issuecomment-6455357243)
and confirmed hive **#3313** request Claude's independent exact-head review.
Board93 is review; parent36 lists the completed milestones and next slices.

M3a adds lock-free inspection of an existing pinned state home and a separate
console job store: console_meta schema version, immutable command artifacts,
serialized compatibility checks, runner-lock leases, conditional nonce/deadline
claims, clock rollback refusal, expiry, uncertain holds and append-only events.
All connections use the shared database layer. Production submission stays
unwired without M4's trusted verifier. No runner/tool is created by this slice;
native process evidence and terminal proof remain M3c responsibilities.

One ordering refinement needs review: command preparation holds the admission
OS lock before BEGIN IMMEDIATE to avoid racing the privacy scan with temporary
files. Artifact-before-row and fsync-before-commit remain enforced. The protocol
is docs/web_console_m3a.md; M2's2,000-entry privacy ceiling and growing artifact
retention need integration attention before production submissions are enabled.

Own base **4,519 passed /10 skipped in228.13s** at8f1f0ff. Full at
**9bd3e7ff2959649548310d78cfe01f1e45b207eb**:
**4,576 passed /10 skipped in220.04s**, exactly57 added cases.
Focused store/inspection **57 passed**. Windows/Python3.11.3, translation
disabled, four workers/loadfile for full runs. Real20-process contention admits
one and refuses19; two runner processes produce one post-claim marker; a
claim/expiry process race has one winner. Event-write failure rolls back claims.

All **19/19 selected guard mutations** were caught by named witnesses; the
committed daily log lists them. Each witness passes on the unmutated candidate;
mutated bytes restored. Final changes after the measured full run are
documentation only, including a validation docstring and a stale containment
comment. Executable parsed code and tests were checked equal. Diff-check and
single-file commit checks pass; feature worktree is clean.
Exact-head CI **40596492085** is running at handoff.

M2's merge/parents/tree and green exact-head run40592597629 were independently
verified: **4,526 passed /3 skipped in327.21s**. Context #180 is verified merged
as **ed26b68a21dcd08a5372e5e10a2f99f1cad612d2**.
Claude owns M3a review and pinned merge on green; Codex owns findings and then
M3b after this dependency lands. Keep the active feature copy under own scratch
until review/merge. No rollout, running-watcher, operational database, live
intake/library, relay or Codex runtime change occurred.

## M2 test isolation approved after failed CI (2026-10-27)

Codex freshly approved comic #151 at exact
**bdef88ec018c15c8ca297e5bf3136d9ac03ddfdf** in
[review 6454880669](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6454880669);
confirmed hive **#3296** and board74 record the handoff.
R1-R4 remain closed. Claude owns pinned merge on green exact-head CI;
Codex starts M3 after M2 lands. No M2 merge is claimed here.

The earlier approved546aa4b did not merge: exact-head CI40591517612 failed
with **2 failed / 4,524 passed / 3 skipped**. Codex independently read its
log. The example's Tower hostname does not resolve on the runner, and the
product correctly refuses an undeterminable server. Two unrelated state-dir
tests inadvertently depended on OfficePC's name resolution.

Fresh diff review: one test file, +9/-2; product code/config unchanged.
The privacy test now uses an empty config. The example-copy test stubs only
Tower's host classification, delegating other hosts to the real guard.
The unknown-server-refusal test is unchanged.

Independent reproduction forced Tower getaddrinfo failure in the pytest
process. The old two tests fail (2 failures in 0.91 s); restoring the current
test file, **all 160 web tests pass in 29.81 s** under that fault, including
unknown-server refusal and both Edge tests. Temporary test bytes restored,
clean source/diff-check verified. No host DNS configuration changed.

Full product evidence remains the measured4,519/10 at48a5aa8, followed by
verified comment-only changes at546aa4b and the current test-only review.
No full repository rerun or repeat of the unchanged guard campaign is claimed.
New exact-head CI **40592597629** was running at handoff. The old CI failure
supersedes the earlier pending-run checkpoint, without changing its history.
No rollout or live state/watcher, relay or Codex runtime changes.

## M2 approved at fresh exact head; pinned merge awaits CI (2026-10-27)

Codex independently approved comic #151 at exact
**546aa4b48c464049fe5589fef1499a973944ad9c**.
[Review 6454719189](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6454719189)
and confirmed hive **#3283** bind the verdict and next owner.
**R1-R4 are closed**. Board74 is review, awaiting Claude's pinned merge
after the same head's continuous integration (CI) succeeds.

Own full suite at preceding candidate
**48a5aa8c1c04dfede1489f62d1237d926c4c9278**:
**4,519 passed / 10 skipped in 221.39 s**, Windows/Python 3.11.3,
translation disabled, four workers/loadfile distribution. Both real-Edge
tests pass, including an old worker still controlling the reused port's
literal origin while sign-in on the random hostname is untouched.
Fresh review of546aa4b confirms exactly two comment-block changes:
Python parsed code and example-TOML values are identical, with all other
source/tests unchanged. Comments reviewed and diff-check passes; no full
suite rerun is claimed for the final comment-only commits.

R3 uses a per-run 128-bit random localhost hostname, required for browser
pages/login/session even on a reused port. Only enumerated launcher routes
also accept the literal loopback spellings, retaining authentication checks.
The launcher validates the server-supplied login URL. R4 uses daemon threads
and bounds the own-address lookup, propagating its TimeoutError. Both original
independent subprocess probes now time out and exit within two seconds
with a 0.1 s test deadline. Original native R1/R2 fixtures still refuse.

All **6/6 selected reviewer guard mutations** were caught: browser host,
random label, launcher URL validation, daemon status, own-address bound and
timeout propagation. Unmutated witnesses pass; fixture children were reaped,
source bytes restored and copies clean. This is a selected independent
campaign, separate from the author's measurements.
Exact-head CI **40591517612** was running at approval, not claimed green.
Manual keyboard/zoom/screen-reader acceptance remains deferred to M5.

Claude owns pinned merge on green exact-head CI; Codex starts M3 after M2
lands. Preserve guarded routing, fetch-stream browser-key headers, lock-free
runner state inspection, dal-only connections and lifecycle hooks.
Context #179 is verified merged as
**0b46a86eaf1b9fd9fd3788d3bb57c7160b607219**.
No rollout or running-watcher, production-data, relay or Codex runtime change.

## M2 re-review closes R1/R2; R3/R4 still block approval (2026-10-27)

Codex completed comic #151 re-review at exact
**d0b8b37173b37b57a7247ec4b6416547c7402d85**:
**CHANGES REQUESTED for R3/R4**. The original native UNC/local containment
and explicitly broad-granted ledger fixtures now refuse: **R1/R2 closed**.
[Final review 6454237208](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6454237208)
and confirmed hive **#3270** record checks and next ownership. Board74
remains in_progress for Claude's fixes.

R3: port zero selects an available port, not a never-used browser origin.
A native bind-to-zero/close loop reused a port after 7,849 allocations.
The author's Edge control proves prior-worker interception on a reused
fixed origin; choosing a different port once does not establish isolation.
These are separate observations, not a claim that the allocator loop
automatically reused that particular worker fixture's port. The contract
must cover an allocator choosing an earlier origin and preserve two tabs.

R4: the ThreadPoolExecutor timeout returns but its running worker prevents
interpreter exit. A disposable subprocess reached TimeoutError with a0.1s
deadline and remained alive after2s. Separately, _local_addresses calls
gethostbyname_ex directly before _bounded; blocking that call in a fixture
produced neither timeout nor exit within2s. Both fixtures were reaped.
All name-resolution/stat stages and refused-process exit need bounded proof.

Own full: **4,499 passed / 10 skipped in218.06s**, Windows/Python3.11.3,
translation disabled, four workers/loadfile distribution, including both
Edge tests. Four selected guard mutations caught (physical containment,
local-host classification, unknown-server refusal, child permissions);
a fifth fixed-default mutation fails the config assertion only, which is
not an origin-isolation proof. Every selected witness passed unmutated and
source bytes were restored. Diff-check and source cleanliness pass.
Exact-head CI **40587707023** was running at handoff; no green claim.

Claude acknowledged the earlier findings in hive3269 and owns fixes/new
exact head. Codex re-reviews before pinned merge; M3 code follows corrected
M2 integration. Context #178 is merged as
**5ff6040be7ef42deea113a0c97ec9c6bc29daac9** (independently checked main).
No rollout, running-watcher, production-data, relay or Codex runtime changes.

## M2 exact-head review requests fixes; M3 plan merged (2026-10-27)

Codex completed the independent review of comic
[#151](https://github.com/Decksx/cbz-automation-suite/pull/151) at exact
**35ceb027e3f9a842a0b5115b33768c0b2ad5241d**: **CHANGES REQUESTED**.
This supersedes the 22ab870 and 427b41b review candidates.
[Final review 6453824281](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6453824281)
binds checks, findings and next ownership to that head. Confirmed hive
**#3258** mirrors the verdict; board74 is in_progress for Claude's fixes.

Three blocking findings have disposable native witnesses:
- R1: a local state directory inside a library exposed through a UNC alias
  is accepted and creates the ledger. The library spellings have matching
  physical identity. Refusing network state locations covers the opposite
  direction and leaves this case open.
- R2: an existing ledger explicitly granting Authenticated Users Full access
  is accepted beneath a private root. Existing trusted state artifacts need
  their own privacy validation before they are trusted.
- R3: a prior same-origin service worker controls the login navigation even
  after the exact ConsoleApp takes over the listener. A fresh Edge fixture
  returns a harmless marker; no credentials are exchanged or captured.
  Launcher hello authenticates its HTTP endpoint, not the browser's prior
  origin state. The bootstrap/origin-lifecycle contract needs correction.

Details and requested witnesses are on
[R1](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6453752130)
and [R2/R3](https://github.com/Decksx/cbz-automation-suite/pull/151#issuecomment-6453775017).
Own full suite: **4,491 passed / 10 skipped in 216.69 s**, Windows/Python
3.11.3, translation disabled, four workers/loadfile distribution. All
**6/6 selected reviewer guard mutations** were caught: Host, Origin, CSRF
(cross-site request forgery), browser key, root permissions and local volume.
Each named witness passed unmutated; source bytes were restored. This is
not a rerun of the author's entire mutation campaign. Exact-head continuous
integration **40584551177 SUCCESS: 4,498/3 in 313.85 s**, independently read
from its log. Candidate source remains unchanged; diff-check passes.
Manual keyboard/zoom/screen-reader acceptance remains deferred to M5.

Claude's approved M3 plan #150 is independently verified merged at
**a448609b9e07a0c1831b0cb0a78b5c07ddf57ddd**, candidate
**053a0cb6f4ff9324a49aaf92c7803c0756775941**; merge/candidate tree
**7d0e7e26fd4508ca8f3f2b2133a6a5e38e858628** matches.
Exact-head CI **40564608293** is green. Board92 is now done.
Context #177 is verified merged as
**a911a309d5bb8ea4264f45cabb9801b2d087b14b**.
Hive3244's M2 seams are received: lock-free state inspection for runners,
dal-only connections/schema version, guarded pattern routes, fetch-based
event streaming with the browser-key header, lifecycle hooks and lock reuse.

Claude owns M2 fixes and hands back a new exact head for Codex review.
M3 implementation follows the corrected M2 merge. No rollout or running
watcher, live state, library/intake, relay or Codex runtime change occurred.

## M3 implementation plan ready for contract review (2026-10-27)

Claude's hive **#3227** requests an M3 plan while M2 remains their workstream.
Codex acknowledged the relayed handoff in confirmed **#3237** and delivered
comic [#150](https://github.com/Decksx/cbz-automation-suite/pull/150), exact
**053a0cb6f4ff9324a49aaf92c7803c0756775941**, tree
**7d0e7e26fd4508ca8f3f2b2133a6a5e38e858628**. It adds only
docs/web_console_m3_implementation_plan.md in two one-file commits from
master **2a95b25080da2bd743acd1a902646c2132e8eef6**. Design blob
**df98a7eeb3bbdbc07f9852cb89f67a84fcf9e92a** and merged M1b govern the plan.

The proposed sequence is M3a store/admission, M3b bounded logs, M3c contained
runner, M3d reconciliation/stop/API. It defines M2 config/state/DB/security/
lifecycle seams and M4 trusted command/seal validation. Production submission
stays disabled until the latter exists. State transitions, crash-boundary
witnesses, strict uncertain recheck, atomic JOB_LIST/explicit inheritance,
logical log offsets/gaps, bounded streaming and stop acceptance gates are
spelled out. The existing comic operational job queue is a separate system.

Section9 asks Claude to review proposed refinements rather than treating them
as accepted: honest unknown-log-tail reporting after combined storage/runner
loss; bounded cleanup without false success; exact process/session evidence,
in-claim deadline, page bounds and truthful stop-delivery status. M2 symbol
names remain provisional until its exact-head review. M3 implementation is scheduled after contract approval and M2's merge. M4/M6 retain production tool wiring and writing-tool interruption gates.

Checks completed: relative links/reference definitions, headings/fences,
documentation-only diff, diff-check and one-file commit shape. Full-file GitHub
readback blob **0185f2283293957c949ef28b8aba45f466343502** matches local Git.
Primary Windows references were checked and linked in the document. No
implementation suite or mutation pass is claimed for a documentation plan.
Exact-head CI **40564608293** is running at handoff.

[PR handoff 6450913057](https://github.com/Decksx/cbz-automation-suite/pull/150#issuecomment-6450913057)
and confirmed hive **#3239** reach Claude. Board **92 in_progress** means
draft complete, awaiting contract review; it does not mean M3 coding has begun.
Parent36 shows M2 active and M3 planning in review. Claude reviews/pinned-merges
the plan on green; Codex handles changes and later implementation. Retain the
own plan worktree until review/merge, then apply the inactive/unbound rule.

Context #176 is independently verified merged as
**e4d2e9ac755da1c48dcdf108a59c2e55d09d25f4**, including M1b's final merge
receipt. No M2 files, watcher, launcher, live library/intake, database, relay or
Codex runtime state changed for this planning work.

## M1b pinned merge and green checks verified (2026-10-27)

Claude freshly approved exact **5152cf042af08a31006dc4d21077b764b32fb6ca**
in [review 6450519407](https://github.com/Decksx/cbz-automation-suite/pull/149#issuecomment-6450519407),
then merged comic #149 as **2a95b25080da2bd743acd1a902646c2132e8eef6**.
GitHub and fetched Git independently confirm it. Merged and candidate trees
are identical: **7851f76de82d5d03eefe4fc0d68e39ea84088e04**.

Exact-head CI **40560885148 SUCCESS: 4,366 passed / 3 skipped in 274.09 s**,
independently read from the completed workflow log. Own full **4,359/10**,
19 stop-file cases and 17/17 guard checks are detailed below. The earlier
pending-CI/review/merge wording is superseded; no old-head approval was reused.
[Merge receipt 6450546906](https://github.com/Decksx/cbz-automation-suite/pull/149#issuecomment-6450546906)
and confirmed hive **#3228** record the result. Board73 is done.

The merged own M1b feature copy was verified clean, inactive and unbound, then
removed without force or pruning others. The bound successor workspace remains
untouched. No rollout, production-checkout update or running-watcher change by
Codex. Claude continues M2; Codex reviews its exact head when handed over.
Context #175 is verified merged as **df8cc78e61410700a5112a9a2fb1c609cb6d0878**.
Delayed #3207 was acknowledged in confirmed hive **#3225** and reconciled:
M1b already descended from #148 merge740a732. Both engineering-decision append
sections must be retained when M2 integrates.

## M1b independent review test gaps closed (2026-10-27)

The delayed #3204 contract delivery was acknowledged in confirmed hive **#3218**.
It was already implemented. Current chat revealed Claude's newer **#3216** and
[review 6450347316](https://github.com/Decksx/cbz-automation-suite/pull/149#issuecomment-6450347316):
code at 807a69e approved, with two test gaps to close before merge. This
supersedes the earlier waiting-for-first-review checkpoint below.

Comic #149 now has exact **5152cf042af08a31006dc4d21077b764b32fb6ca**, tree
**7851f76de82d5d03eefe4fc0d68e39ea84088e04**, eight one-file commits.
The two follow-up commits change tests and the daily log only; watcher source
and its mixed bytes are identical to 807a69e. A direct-entry witness observes a
new request before any earlier timer/explicit poll. A real expired holding
rename and receipt then latches stop before ready siblings are processed,
proving the already-admitted unit finishes without re-admission.

Both exact reviewer mutations now fail their named new test, **one failure
each**: admission changed to admitted = not self._closed, and the hold path
re-enters _process_directory_when_ready. All previous 15 selected guards were
rerun: **17/17 caught**, sources restored, guard/candidate source and test
parity checked, clean inactive/unbound scratch copy removed. Logs and receipt
are outside Git under Documents/Codex/control/m1b-review-guard-results.

Final full at 5152cf0: **4,359 passed / 10 skipped in 212.46 s**, +2 over the
807a69e measurement, +19 over base 4,340/10. The stop-file file passed
**19/19 in 3.85 s**. Windows/Python 3.11.3, translation disabled, four workers
and loadfile distribution. LF-only diff-check passes; feature copy clean.
[Fresh handoff 6450478687](https://github.com/Decksx/cbz-automation-suite/pull/149#issuecomment-6450478687)
and confirmed hive **#3222** reach Claude. Exact-head CI **40560885148** is
running at handoff. Claude owns fresh exact-head review and pinned merge on
green; no old-head approval is transferred. Board73 records that next step.

David's delayed dashboard request #3196 was acknowledged in confirmed
**#3214**, status reply **#3215**. Parent36 now has the current localhost
design link, completed milestones, active M2 ownership and M3-M12 next steps.
Mockup card71 includes the verified merge receipt; completed card72 stays done.
No watcher rollout, live intake/library, database, relay or Codex state change.

## Web console resumed: cleanup fix merged; M1b implemented (2026-10-27)

Claude's hive **#3194** and approved interface **#3204** assign Codex
**#147 then M1b**, with Claude reviewing each exact head and owning pinned
merges on green continuous integration (CI). Claude owns the separate M2 web
package; its implementation has not been independently reviewed by Codex.
Board **72** is done; **73** records M1b progress and next ownership. David's
dashboard request **#3196** was addressed through supported board updates;
Claude's **#3202/#3203** also list completed work and the remaining milestones.

### M1 and cleanup follow-up reconciled

GitHub independently confirms M1 #146 merged approved **6e4600f** as
**fb6ef7dbc8a45d16b15103bff5f5dae8e11f32b6**, mockup #145 as
**5889beb7e97d46f2a74d09b1d10b73d3731331f1**, and context #174 as
**eade953e9358c7bc8460c471f5c56ed0cb25d822**. These supersede the pending
review/merge wording below. Claude's **#3192** reports the M1 live checkout
fast-forward, no watcher running at that deployment, and physical-root mutex
smoke; Codex did not repeat that live operation or restart the watcher.

Codex implemented #147 in comic [#148](https://github.com/Decksx/cbz-automation-suite/pull/148)
at exact **f50df64c3eff008a84622bef492557cefc81e50a**, six one-file commits.
It preserves an original session/acquisition error with cleanup logged/noted;
cleanup-only failure is exit 4. Handle close is attempted after release errors,
and uncertain cleanup retains process-local root exclusion. Startup refusal
remains exit 3. Protocol and daily provenance are committed in that PR.

Own measured base **4,328 passed / 10 skipped in 232.40 s**; final full
**4,340 / 10 in 242.91 s**, +12 cases, focused **45**. All **8/8** targeted
guard mutations were caught with named failures; restored scratch copy removed.
Windows/Python 3.11.3, translation disabled, four workers/loadfile distribution.
Exact-head CI **40557029434 SUCCESS: 4,347 / 3 in 291.84 s**.
[Handoff 6449953668](https://github.com/Decksx/cbz-automation-suite/pull/148#issuecomment-6449953668)
and confirmed hive **#3206** reached Claude; **#3207** reports independent
approval, five reviewer mutations caught and pinned merge. GitHub and Git
independently confirm merge **740a7324f40bfc4201ad9e5aff513c29a317c5a3**,
tree equal to candidate **c2d2e3ff14300c15ffc453066d82736dc14ba920**.
[Receipt 6450126101](https://github.com/Decksx/cbz-automation-suite/pull/148#issuecomment-6450126101)
records the green CI and parity. No #147 rollout by Codex.

### M1b graceful stop handed to Claude

Comic [#149](https://github.com/Decksx/cbz-automation-suite/pull/149) is ready at
exact **807a69ef9fa625b2ede79938ecdae4cbfc28722a**, tree
**42b14321556f8810c49bfab1a739f6f14b1447fe**, six one-file commits from
master **740a732**. [Handoff 6450301141](https://github.com/Decksx/cbz-automation-suite/pull/149#issuecomment-6450301141) and confirmed hive **3211**
record the actionable handoff. Claude owns independent review and the pinned
merge on green exact-head CI. No approval, merge or activation is inferred.

The optional absolute --stop-file requires an existing parent. Presence latches
stop; content is ignored and the watcher never deletes the request. It stops
admitting directory units, cancels pending timers, joins the observer and drains
callbacks/direct units while M1 still owns the root. Admitted units finish.
Startup requests exit successfully before routing/recovery/imports. Poll errors
warn once and keep running, as Claude requested for transient state-drive
failures. No forced termination is added; M6 retains its interruption/recovery
gate. Active operations and startup work can make graceful latency unbounded.

Final own full suite at 807a69e: **4,357 passed / 10 skipped in 227.15 s**; broad focused **130
passed in 23.64 s**, including **17 new cases**. Base tree parity with the just
tested #148 candidate establishes **4,340/10**, without a redundant baseline
run. Initial M1b 4ffc50a also passed **4,357/10 in 245.38 s**. The final commit
only scopes a stat-fault test so failed guards produce ordinary named failures
instead of interfering with pytest reporting; watcher source is unchanged.

All **15/15 selected guards** were caught at the final tree: absolute path
(1 failure), existing parent (2), latch (1), poll-error continuation (2),
warn-once (2), directory admission (1), pending cancellation (1), direct-unit
draining (1), startup stop (1), idle stop (1), exit log (1), and each of four
timer-entry polls (1 each). Logs/receipt remain outside Git under
Documents/Codex/control/m1b-guard-results. Every source byte was restored;
the clean, inactive, unbound mutation copy was removed.

Native fixture witnesses include atomic-request shutdown of a real observer
process, stopping between startup directories, and a contender refused until an
admitted directory finishes. Mixed watcher endings remain **2,767 CRLF / 842
bare LF -> 2,842 / 865**; the actual edits explain both deltas. LF-only diff
check and one-file commit checks pass. Final CI **40559498616** is pending
at handoff; green checks remain a merge gate. Protocol and daily evidence are
docs/watcher_graceful_stop.md and docs/development_log_2026-10-27_m1b.md.

Own merged M1 and #147 feature copies were verified clean, inactive and unbound,
then removed without force or pruning others. Keep the active M1b feature copy
at C:/Users/david/.codex/worktrees/comic-web-m1b until review/merge. The bound
successor session/relay workspace was not moved or changed. No running watcher,
launcher, live intake/library, database, relay or Codex state was changed.

## Delayed M1 approval reconciled; cleanup diagnostic follow-up (2026-10-26)

The delayed hive **#3160** is Claude's code approval of M1 **ffd4f1f**, recorded
in comic #146 [review 6429304973](https://github.com/Decksx/cbz-automation-suite/pull/146#issuecomment-6429304973).
It does not approve the later configuration-corrected head
**6e4600fe7fffe677fe517a9872cc029729c8c0bb**. Claude's newer **#3165** says that
head is under independent review. Its local 4,328/10 and green CI 4,335/3
receipts are already recorded; no merge has been performed from the old approval.

Codex chose the permitted separate follow-up for the non-blocking ReleaseMutex
diagnostic issue: comic [#147](https://github.com/Decksx/cbz-automation-suite/issues/147),
board child **72 todo** under M1 task **70**. An offline FakeKernel probe at
6e4600f confirms that a protected body ValueError followed by release failure
is handled as a startup refusal/exit 3, suppressing the primary diagnostic.
The primary exception remains in Python's context chain. No native/live mutex
or runtime state was changed by that probe.

The follow-up must preserve the primary error when cleanup also fails, classify
a cleanup-only failure separately from startup refusal, always attempt handle
close and retain fail-closed ownership. Deterministic failure-injection tests
are specified on the issue. Codex owns that separate work after M1 integration;
the M1 candidate remains unchanged and clean.

[PR note 6429564463](https://github.com/Decksx/cbz-automation-suite/pull/146#issuecomment-6429564463)
and confirmed hive **#3173** record this decision. Claude offered the pinned
merge in #3160; Codex accepted that offer in #3173 after a fresh current-head
approval and green checks, with **no rollout**. This updates the merge-owner
wording in the earlier implementation handoff below. Claude reviews 6e4600f
and owns the offered pinned merge; Codex owns findings and #147.

The #145 light review and M1's pinned repository-mockup citation are already
complete. The running watcher, libraries, database, relay and Codex state remain
untouched.

## Web-console mockup light review approved (2026-10-26)

Codex approved comic [#145](https://github.com/Decksx/cbz-automation-suite/pull/145)
at exact **296f53588305331a5bda7a5bf2fc8e08ef6890f4** in
[review 6429508134](https://github.com/Decksx/cbz-automation-suite/pull/145#issuecomment-6429508134).
Hive handoff **#3169** is confirmed; board child **71** is done.
Claude owns the pinned merge. This delayed #3157 handoff was handled after
M1's implementation/review handoff, respecting its priority.

All **6/6 payload SHA-256 values** match the committed provenance README.
The canvas parses, its five boards/order match the artboards, the relative
design-document link resolves, and page links resolve except the explicitly
documented missing support.js. The change is seven regular documentation
files only; diff-check passes. Reviewed tree
**c215bdcaffa16af835df6a21738466ab44fcc67d**; exact-head continuous integration
(CI) **40414424474** is green. No local suite or mutation rerun was needed.

The written design stays authoritative, data is sample data, and Series Review
remains v1.1. This was static markup/provenance review: Codex didn't download the
private canvas version independently or render the pages. The original download
receipt remains Claude's evidence. Mockup Google Fonts references do not change
the approved production font/content-security-policy requirements.

M1 [#146](https://github.com/Decksx/cbz-automation-suite/pull/146) now cites the
[pinned repository copy](https://github.com/Decksx/cbz-automation-suite/blob/296f53588305331a5bda7a5bf2fc8e08ef6890f4/docs/design/web-console-mockup/README.md)
in its PR description and [reference comment 6429515540](https://github.com/Decksx/cbz-automation-suite/pull/146#issuecomment-6429515540).
This changes metadata only. Its candidate under independent review remains
**6e4600fe7fffe677fe517a9872cc029729c8c0bb**, with the same green CI.
No feature source, runtime or live watcher state changed.

## Web console M1 implemented and handed to Claude (2026-10-26)

Codex's comic [#146](https://github.com/Decksx/cbz-automation-suite/pull/146)
is ready for independent review at exact
**6e4600fe7fffe677fe517a9872cc029729c8c0bb**, tree
**dcd3fff89dc4f9b803ba9b9cc9928a4cea8faf70**.
[Handoff 6429440452](https://github.com/Decksx/cbz-automation-suite/pull/146#issuecomment-6429440452)
and hive **#3162** are confirmed. Ten one-file commits branch from master
**4cf01a81526a06ddc24c95aa6cf6a411a254a0a9**. Claude owns independent review;
Codex owns findings and the pinned merge after approval and green exact-head
continuous integration (CI). No merge or deployment of M1 is claimed.

The watcher acquires a Windows Global mutex keyed by physical watch-root
device/inode identity before integration settings, routing, startup recovery,
discovery or observer startup. Unknown/zero identity, held ownership or
uncertain kernel results refuse with exit code 3. There is no alternate
backend. Abandoned ownership is acquired without claiming the old import
finished. Ownership includes observer shutdown, cancellation of pending timers
and draining callbacks that already entered; late callbacks are fenced.
A refused embedded call cannot reconfigure the active session.

Final exact-head checks:
- Windows/Python 3.11.3 full suite, translation disabled, four workers:
  **4,328 passed / 10 skipped in 211.03 s**, +33 passes over the independently
  measured identical executable/test baseline at #144.
- Focused **34/34**, including 33 new cases and existing policy cleanup.
- **21/21 selected guard mutations rejected** by named tests, with every
  source byte restored. The configuration-order regression first failed
  against the earlier candidate (1 failed / 33 passed), then passes fixed.
- Real local/localhost UNC, mapped-drive, junction, distinct-root and
  abandoned-holder witnesses pass. Two actual Git worktrees at the final head
  produce contender exit 3 while held and 0 after release. The abandoned test
  preserves a non-owning handle to prove WAIT_ABANDONED rather than recreation.
- OfficePC token: medium integrity, Administrators deny-only, no
  SeCreateGlobalPrivilege. Native tests pass under that token; cross-account
  behaviour is unmeasured.
- Mixed watcher endings retained: 2,699 CRLF / 839 bare LF to 2,764 / 842.
  The LF diff check and one-file commit check pass; feature worktree clean.
- CI **40416860492** was still running at initial handoff. It was then
  independently verified **SUCCESS at the same head: 4,335 passed / 3 skipped
  in 261.01 s**. [Receipt 6429464896](https://github.com/Decksx/cbz-automation-suite/pull/146#issuecomment-6429464896)
  supersedes that pending status. Claude acknowledged the handoff in **#3164**;
  independent review is still pending.

The protocol and stable-root/rollout limits are in
docs/watcher_single_instance.md; daily evidence and the initial 4,327/10
candidate measurement remain in docs/development_log_2026-10-26.md.
The final callback/configuration change was retested as above; the earlier
candidate is not the current review head.

Feature worktree: C:\\Users\\david\\.codex\\worktrees\\comic-web-m1. Both disposable
guard worktrees were verified restored, clean and inactive before removal.
Retain the feature copy until review/merge, then apply the inactive/unbound
cleanup rule. The session/relay-bound successor workspace remains untouched.

The running watcher, its configuration, live libraries, database, relay and
Codex state were untouched. Pre-M1 processes hold no mutex and must be stopped
deliberately before eventual first-live rollout. M1b's stop file, interruption
safety and destination-wide writer exclusion remain separate. Root/ancestor
retargeting during a session is outside this contract.

The GitHub API independently confirms #143 merged as **4cf01a8** and context
#173 as **777067c4ccc6da35039de68d25df1ca5ec5e179d**. Claude's #3154 reports the
live checkout fast-forward; Codex didn't restart or reconfigure that watcher.

## Integrated web-console design exact-head approval (2026-10-26)

Codex re-approved comic [#143](https://github.com/Decksx/cbz-automation-suite/pull/143)
at **890a1cbd31a0c3a34c2b3288f7b47ade18f5089b** in
[review 6428957865](https://github.com/Decksx/cbz-automation-suite/pull/143#issuecomment-6428957865).
Hive handoff **#3146** is confirmed. This supersedes the candidate hash in the
earlier design approval while retaining its accepted contracts and limits.

Independent Git checks verified both merge parents: approved design **58120ea**
and master **1dde8a5b168c3bd4d8db4b6aedd6c1e9dde3f1e2**. The latter is the
API-verified #144 merge at 22:33:49 UTC, and its tree equals reviewed #144 head
**79257a513bc23f1c2e594e58874b7c5eb0976a67**. Every non-design tracked blob
and file mode in the new #143 head equals that reviewed #144 tree. The design
is byte-identical to 58120ea, blob **df98a7eeb3bbdbc07f9852cb89f67a84fcf9e92a**,
SHA-256 **3f6d2a98cd5c4a81e90327a20178dbc019a16ae42596aaa55b2e52c120a7d02b**.

Integrated tree: **a53322ba76be9cfd68a7a695b6a903d66b17c6d5**. Diff-check
passes; the diff from master is only the design. The existing independent
#144 suite and guard evidence apply by complete source/test parity. No local
suite rerun at 890a1cb is claimed. Continuous integration (CI) **40413471162**
was still running at handoff. Claude owns the pinned merge on green CI;
the PR description still needs its old runtime/logging summary refreshed.
Board child **68** now links the integration verdict. No runtime change or
M1 implementation occurred in this re-review.

## Wrong-language translation regression independently approved (2026-10-26)

Codex approved comic [#144](https://github.com/Decksx/cbz-automation-suite/pull/144)
at exact **79257a513bc23f1c2e594e58874b7c5eb0976a67** in
[review 6428914410](https://github.com/Decksx/cbz-automation-suite/pull/144#issuecomment-6428914410).
Hive handoff **#3136** is confirmed; board task **69** is done.
Claude owns the pinned merge and any rollout receipt. No merge or deployment
of #144 is claimed by this review.

The guard now requires an allowed detected Japanese/Korean/Chinese language
before accepting Latin-script translation. Native-script behaviour and existing
allowed-language acceptance remain. The PR description was corrected: those
allowed detections don't also require a romaji marker.

Independent checks at this exact head:
- Full Windows/Python 3.11.3 suite with C:\\Python311 and
  `CBZ_TRANSLATION_ENABLED=0`: **4,295 passed / 10 skipped in 717.47 s**.
- **30 offline language/script cases** pass, including markerless accepted
  detections, wrong-language rejections and native-script preservation.
- Replacing the guard with its exact old expression in memory gives **6 failed /
  60 passed** across the two focused files. It reproduces the original Kaguya
  Series becoming Together and the legacy filename becoming Partnership #3 Ch. 3.
  The source file's SHA-256 remains unchanged after the probe.
- Continuous integration (CI) **40411561277** is green: **4,302 passed /
  3 skipped in 299.04 s**. Reviewed tree
  **5588ae3cd7747f340132673dea733e42df699ac9**.
- Three one-file commits, preserved line endings and clean review worktree.
  Diff-check passes for LF files, excluding the existing CRLF test by policy.

Codex independently confirmed that C:\\Python311 lacks googletrans. No live
Google call was made in this review; the response drift and its onset remain
attributed to Claude's recorded evidence. Offline replay establishes the
regression mechanism. Suite-wide network isolation and translation of an
authoritative folder-selected series remain follow-ups for Claude to track.
If #143 is integrated onto the repaired master, its final checks and unchanged
design evidence must name the resulting commit.

The own scratch review copy was clean, inactive and never registered as a
session or relay workspace; it was removed after the review ended, without
force or pruning other copies. No watcher, live library, database, relay or
Codex state changed. Context #172 is independently verified merged as
**15532675e5768211f5c3de3d94a33bd6abc949b5**.

## Web console design approved at the third reviewed head (2026-10-26)

Codex approved comic [#143](https://github.com/Decksx/cbz-automation-suite/pull/143)
at exact **58120eabcba45f1248e8b4fa1b61eaa9dd03493f** in
[review 6428608741](https://github.com/Decksx/cbz-automation-suite/pull/143#issuecomment-6428608741).
Hive handoff **#3123** is confirmed. This supersedes the changes-requested
verdict at 45c04eed recorded below; the earlier evidence stays historical.

The four remaining design findings are addressed: atomic Job Object launch
only, descendant deadlines alongside pipe draining, fresh identity and
containment proof before releasing uncertain admission, and separate bounded
reader/writer logging with explicit gap-aware segments. Source contents are
sealed and checked again by the runner. The watcher uses a fixed Global mutex
backend keyed by physical directory identity, resolving junction-root aliases.
Claude's OfficePC non-elevated mutex measurement is attributed to Claude.
Cross-account behaviour is unmeasured; uncertainty must refuse startup.

The diff remains one 1,219-line design document, SHA-256
**3f6d2a98cd5c4a81e90327a20178dbc019a16ae42596aaa55b2e52c120a7d02b**.
Diff-check passes. This is design approval; no implementation suite or
mutation pass is claimed. Continuous integration (CI) run **40410496583**
was still running at review. Claude owns the pinned merge after exact-head
checks and accounting for the separate Kaguya test investigation. The PR
description still needs to match the revised document.

Implementation review must verify the promised acceptance witnesses, prompt
closing of temporary Job Object query handles, bounded writer shutdown and
honest gap reporting when G: is unavailable, and bounded retention metadata
for long-lived services. The check-to-import source-change window is accepted
explicitly in the design.

Board child **68** records this completed approval review under parent **36**.
Codex owns M1 implementation with Claude reviewing; no M1 code or rollout is
included in this receipt. No watcher, library, G: state, relay or Codex state
changed. Admin style request #3111 was acknowledged in confirmed **#3118**,
with reply **#3119**.

## Web console design second review, still awaiting revision (2026-10-26)

Codex re-reviewed comic [#143](https://github.com/Decksx/cbz-automation-suite/pull/143)
at **45c04eed84d25c978d766ece2b41fc75ffc77ac5** and requested changes in
[review6428493377](https://github.com/Decksx/cbz-automation-suite/pull/143#issuecomment-6428493377).
The hive confirmed the handoff as **#3115**. Claude owns the next revision.

The revision addresses most first-round findings: physical-root watcher mutex,
cross-account scope, atomic Job Object launch as the preferred path, transactional
nonce claim, admission table, stop acceptance gates, expanded preview seal,
three-secret bootstrap exchange and a real-browser smoke test. David's choices
are now recorded: runtime state on G:, OfficePC hosting, mid-run stops enabled
per tool after their recovery tests, and a cancellable planner with progress.
Those directions are accepted. M1's implementation remains pending; its physical
identity direction is accepted with lock-backend and alias clarifications.

Four details still need changes:
1. The suspended fallback can crash after process creation but before its child
   identity is durable. Removing that fallback from v1 would close the gap.
2. Waiting for output-pipe end-of-file before starting the descendant timeout can
   wait forever on an inherited writer. Poll and enforce the deadline while the
   pipe is drained concurrently, then verify the empty Job Object.
3. Resolving an uncertain job must freshly prove termination under admission
   exclusion. A desired terminal state and an evidence note cannot release an
   inaccessible or still-live owner.
4. A blocked G: write must not block the pipe reader. Use a bounded reader/writer
   handoff, count overflow, and define segment offsets across dropped-byte gaps.

The review also asks for executable-source content sealing or refusal of source
dirtiness (a dirty boolean is not a fingerprint), one fixed lock backend per
deployment, and a clear junction-root policy.

A bounded temporary-process probe measured root exit at0.093s and pipe closure
at2.109s, after its grandchild exited. Both fixture processes ended. Microsoft's
process/pipe contracts support the lifecycle findings. The diff is still one
design document,1111 lines, SHA256
**dc197b13556de72049e9b85c0f140a10a581c3c4a5032abe69173c5e052703f3**,
and diff-check is clean. No implementation suite or mutation pass is claimed.
Continuous integration (CI) run **40409592051** was still running at handoff.
The earlier Kaguya failure remains Claude's separate investigation.

Board child67 records this completed review while parent36 stays open. Context
#171 merged as **9a49d81** according to Claude's **#3110** receipt. No M1 or web
implementation, G: state write, watcher start, library operation or relay/Codex
state change occurred in this review.

David's hive **#3111** asks for natural, direct writing with contractions,
bullets where helpful, no em dashes or canned reframing, and explanations of
initialisms and acronyms at first use. Follow that preference in handoffs too.


## Web console design review and merged feature cleanup — 2026-10-26

Codex reviewed comic [#143](https://github.com/Decksx/cbz-automation-suite/pull/143)
at **11ebf94637e474b849890fe0236ce2f8d3d820ca** and requested changes in
[review6428308440](https://github.com/Decksx/cbz-automation-suite/pull/143#issuecomment-6428308440),
confirmed hive **#3103**. One860-line design document is the entire diff
fromf43174e, SHA256 **796687c4be54c295894ed2a42d681438b206d06669538bc0ed4afcfca7d1ff33**,
diff-check clean. Stdlib WSGI/service modules, localhost scope, read-only plan
review and CLI-only canonical apply are accepted directions, not implementation
approval. Claude owns revisions and the next exact-head handoff.

Five contracts need revision: **D1** physical-identity watcher exclusion
instead of path-hash/per-user ambiguity; **D2** containment before tool execution,
verified descendant cleanup and safe stop identities; **D3** durable runner
claim/adoption and crash-safe admission; **D4** runner-owned bounded logging,
rotation and generation-aware cursors; **D5** proven tool-specific cancellation
and watcher/maintenance concurrency contracts rather than Tk-parity claims.
Implementation acceptance tests are specified in the PR review. Preview sealing,
bootstrap-token redaction and real-browser security/SSE smoke coverage also need
clarification. Operator-facing Q1-Q13 decisions stay with David/Claude.

A temporary host probe demonstrated D1: the same directory via local C: and
localhost UNC had equal st_dev/st_ino but different normalized-realpath hash
keys. A second probe demonstrated WinError32 when rotating a log with an open
writer handle. Microsoft process-creation documentation supports the containment
finding. This is a design review: no implementation suite/mutation pass is claimed.
The mockup URL was inaccessible, so visual fidelity remains unverified.

Exact-head CI **40407785338 failed:4296 passed/3 skipped/1 failed**.
The Kaguya selected-folder fixture wrote ComicInfo Series Together instead of
Kaguya-sama (test_media_naming_callers.py:373). Only the design doc changed;
the failure's cause is not diagnosed or dismissed. Claude must compare/reproduce
against the unchanged base before assigning a cause.

Claude's handoff **#3097** released the merged old feature copy
`C:\\git\\cbz-media-naming-20261026`. Codex removed it through git worktree
remove after checking clean state,39d ancestry in mergedf431, no matching
process/service/scheduled-task/shortcut, and no binding in a fresh non-stale relay
snapshot. Cleanup receipt confirmed hive **#3101**. Other unverified/prunable
copies were not globally pruned. Primary ComicAutomation and the bound swarm
successor workspace remain. No live library/config/runtime/relay state changed.


## Naming merge, rollout receipt and current library scopes — 2026-10-26

David clarified in hive **#3087** (Codex ACK **#3091**) that **Horrorsplat is
not a current library**: its contents were merged into Manga and Graphic
Novels. Do not register or plan it as a separate library. Claude's **#3088**
confirms exclusion from the style registry and describes the X: copy as a
leftover for later sync reconciliation; that leftover/sync description is
Claude's receipt, not a Codex filesystem migration or deletion authority.

GitHub independently confirms comic [#142](https://github.com/Decksx/cbz-automation-suite/pull/142)
merged reviewed **8797a5657c424e584884f5c057bde5f103e9b133** as
**f43174e65a2cc4c13d0c0e68224ffe0eccae995c** at2026-10-26T21:17:20Z.
Codex read-only checkout check finds `C:\\git\\ComicAutomation` at that merge,
with tree **0ea99a96f966680493031724db289524f71dff3f**, equal to the reviewed head.
This supersedes the pending merge note below; Claude performed the merge/rollout.

Claude's hive **#3085** reports David approved the registry, no watcher/GUI
was running at fast-forward, User environment selects the shared registry,
real UNC/Z: scope selection was verified, and media naming activates on the
next GUI launch. Codex did not launch/restart a watcher or independently
verify a post-launch import. Codex read-only inspection verifies the shared
file `C:\\Users\\david\\.cbz-automation\\number-styles.json` has SHA256
**0d810778b89007f2f25de4faadbf4e86120604ec9784ea4f138204c4380a8e72**,
six roots: Tower UNC and X: Manga=chapter, Comix/Graphic Novels=issue, with
no Horrorsplat entry. The registry was not edited by Codex.

GitHub also confirms context [#169](https://github.com/Decksx/agent-swarm/pull/169)
merged3084061 as **339ac49748ce6521e232aa4e98691996100fe979**; Claude's **#3086**
reports green CI/tree parity. No library move, deletion, sync, batch apply,
configuration edit or relay/Codex-state operation followed David's FYI.
Fresh Tower batch plans still require verified backup and exact-digest approval.


## Comic media naming exact-head approval — 2026-10-26

Codex approved comic [#142](https://github.com/Decksx/cbz-automation-suite/pull/142)
at **8797a5657c424e584884f5c057bde5f103e9b133**, reviewed tree
**0ea99a96f966680493031724db289524f71dff3f**.
[Review6427524333](https://github.com/Decksx/cbz-automation-suite/pull/142#issuecomment-6427524333),
confirmed hive **#3082**, supersedes the blocking verdict on084d4e8 below.
Claude owns the expected-head pinned merge and separate deliberate rollout;
neither is claimed complete by this dated review receipt.

R1 is fixed by a shared occurrence-counting unconsumed-year guard. The real
unmatched-title planner fixture now holds without altering its archive bytes.
R2 persists and reads back the issue year before removing it from the filename:
both original spellings retain2019 in intake after all five real temporary
writes fail; a fresh pass after the fault clears lands exactly one archive
with XML Year2019. An independent interruption after successful persistence
but before rename also preserves the year and recovers on a fresh pass.
The changed existing Full test passes its issue-year argument explicitly
and requires omission to refuse; it kills removal of the shared guard.
A supplementary resolver/human-year fixture proves the rename-only boundary
when the trusted year is absent from XML; no human-manifest CLI is implied.

Own exact-head Windows/Python3.11 suite **4290 passed /10 skipped (241.87s)**,
one supplementary fixture passed, and **8/8 independent in-memory mutants
killed**, all three source SHA256s unchanged. Exact-head PR CI
**40400646356 completed/success** independently verified; advertised head
unchanged. Derived LF diff-check clean (45 mixed/CRLF exclusions), clean tree.
Against084d,3515/3528 old watcher lines are byte-identical; final3538 lines,
2699 CRLF/839 bare LF. Disclosed F3/G2 policy follow-ups remain nonblocking.
No live library/DB/config/watcher, merge/deploy or relay/Codex-state operation
by Codex. Tower batch apply still requires a fresh digest, verified backup
and David's approval.

David's board request **#3068** was reconciled through supported /board
routes with read-back, coordinated with Claude. Codex corrected7/8/15/41
and added linked completed work57-64; Claude updated their own work and
active142 card56. Confirmed hive **#3076/#3077** distinguishes historical
backfills from new work. The final positive review is a completed child of
active card56, while card63 retains the earlier negative review. Task36 is
the dashboard work item, not GitHub issue36: localhost-only v1 is recorded,
Claude owns it, and the roadmap's pre-mutation security requirements remain.


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
