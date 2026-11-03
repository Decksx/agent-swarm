# Tower Graphic Novels v3c approval and pending execution

David's hive3843 at2026-11-03T22:45:23Z approves the plan presented by Claude
in3839. Codex ACK confirmed3846. This is approval of the unchanged concrete
plan, not a request to re-confirm the same permission.

- Plan: `G:\ComicAutomation\logs\tower-graphic-novels-plan-20261103-v3c.json`.
- Canonical digest: **e0cfc6466db128802e3ea4749eed60c90e012258c5f7a9f7ea6b69798400db41**.
- Library root: `\\TOWER\media\comics\Graphic Novels`.
- Scope:441 renames,141 review items,0 families,0 quarantines.
- Single accountable backup/preflight/apply owner: Claude. Codex verifies
  artifacts/receipts and does not run a concurrent apply.

## Independent artifact checks

Codex read the2381953-byte saved JSON, recalculated SHA256 over canonical plan
bytes (all fields except plan_digest), and matched the full approved digest.
The supported read-only load_plan also accepts the exact digest,441 renames,
0 families and library root:441 parsed actions, no plan conflicts. These are
artifact checks, not a current archive/catalog snapshot or quiescence proof.
Code used is the reviewed1e753ca implementation; live checkout read-only git
inspection independently reports57552903b87ce2a8305b18ad66e85a4e434c8c41.
[GitHub approval/check receipt](https://github.com/Decksx/cbz-automation-suite/pull/169#issuecomment-6617472933),
hive coordination3848/3851/3852. No plan or backup data is committed to Git.

## Remaining operational evidence

Claude reports in3849/3850 that a full library/catalog backup is running to
`G:\ComicAutomation\backups\tower-graphic-novels-20261103` and has asked
David whether Camelia can touch Graphic Novels, or to pause it. Approval does
not by itself attest quiescence. No additional approval of unchanged v3c is
required; the missing writer-scope fact and backup proof still matter.

Codex read gn_backup.py: it uses SQLite's backup API and copies library files,
checking sizes. Its observed progress was200 files/4.2GiB/235s, not DONE.
No completed/verified-backup or successful-apply claim is made here.

A read-only verifier is prepared and compiled at
`C:\Users\david\Documents\Codex\control\verify_tower_v3c_backup.py`,
SHA256 **d54323f02bc8854619bec13a52fe22af308d9ceef1e94181cbf4353177ce2f5b**.
It refuses before the copy log ends in DONE, revalidates the approved plan,
checks the local manifest/file sizes, hashes all441 affected copied archives
against the plan, and checks backup SQLite integrity plus all441 original
catalog rows inside a data-version-fenced read snapshot. It never opens a Tower
archive/original catalog and writes only a control receipt, including script
hash and UTC time. Other copied files are size-checked, not SHA-verified.
Its only execution so far returned backup_not_done; it has not verified the
actual backup. Success receipt target:
`C:\Users\david\Documents\Codex\control\tower_v3c_backup_verification.json`.

Handoff3854 gives Claude the helper so he can run it after DONE even if Codex
is idle. Retain full verifier output; failure is not permission to bypass it.
Before apply, require verified backup evidence, the Camelia/writer confirmation
already requested, and fresh watcher/root/database/archive checks. The helper
apply_v3c.py unconditionally supplies --attest-quiescent, so only the owner may
invoke it after those facts exist. Exit2/stopped work needs inspected recovery
or resume evidence, not a blind new attempt. Report exact attempt/journal,
finished/held/refused counts and destination hashes/source disappearance after
execution. Codex's next action is to verify those receipts when available.

This approval includes no held-item override, X-drive cutover, old plan, web
rollout or D1 native acceptance. Backup/apply remain pending at this checkpoint.
