# Deployment receipt — 2026-10-15

David explicitly authorized committing, merging and deploying the project
changes in the Codex conversation. These are operator-directed GitHub and host
operations, not swarm integrations or controller-ledger review verdicts.

## Merged changes

| PR | Candidate | Actual merge commit |
| --- | --- | --- |
| #96: external-review states/events | `4ce87b2232a74fa00de711736269c4b0a66abbc2` | `73ef1b0cb20ae424eb35d1463ede831099b7921e` |
| #97: external-review expiry recovery | `84edbea40e78035ecad56bee3d6c4d931b405031` | `6476b33974cc4d63f7e705ab1855375175e28031` |
| #98: hidden scheduled launcher | `82cf93896023cb85dce96c5216479c5120bf7d5b` | `755aa885b3d4bf8b95cd58e89341c83129eb9b70` |
| #99: redacted project context | `2d105f76d549c2318997f4f6ffa3ca696f12ceac` | `4d2d395746b73fcc724a0d5e69361bb34614ccf0` |

All four candidate heads had successful GitHub unit and bypass checks before
their merges. PR97 was retargeted from its dependency branch to main without
changing its candidate. Its PR was closed/reopened to trigger the existing
workflow. No controller task or ledger verdict was created to justify a merge.

The first PR98 CI run failed eight scheduled-registration tests because their
fixture selected OfficePC's default Python path on the GitHub runner. The fixture
now supplies the test host's interpreter. The corrected CI run exercised and
passed those tests; its unit job reported 1,911 tests plus 318 hub tests, and its
bypass job passed eight tests. Local launcher checks previously passed 26 tests
with ten permission-dependent skips. PR97 CI passed 1,914 unit, 318 hub, and eight
bypass tests. These CI runs are separate from the combined production deploy gate.

## Context and local edits

GitHub push protection rejected the first unpublished context branch because
the raw historical chat included a Google Cloud credential. A clean publication
branch redacts the affected command and has a regenerated 51-entry manifest,
verified against Git's stored bytes. See [ARCHIVE_REDACTION.md](ARCHIVE_REDACTION.md).
The original attachment stays local. The unpublished context branch was repointed
to sanitized main rather than pushed with its original credential-bearing history.

The pre-existing hidden-launcher edits were committed separately in PR98 and
preserved with local stash backups before updating the checkouts:

- Development stash: `2af6ed80e1c0381bfcb0a916e8b87d3fbfcb3569`.
- Production stash: `cdf9186879f3df91c57e2f132e2658b897850a2b`.

Production originally had `core.autocrlf=true`. Advancing its commit rewrote only
changed files, leaving an old mixture of CRLF and LF and thus a different raw
build digest. All 140 tracked differences were verified to be line endings only
before restoring exact Git object bytes. Production now has repository-local
`core.autocrlf=false`, clean Git state, and the expected immutable source bytes.
No deploy bypass or uncommitted-controller override was used.

## Backups and runtime controls

Before deployment, Tower backups were created at:

- `/mnt/user/appdata/agent-swarm/data/backups/controller-predeploy-20261015T171205Z.db`
  (SQLite quick check: `ok`).
- `/mnt/user/appdata/agent-swarm/data/backups/app-predeploy-20261015T171205Z.tar.gz`
  (SHA-256 `b83f362ca74fa21a304a39ff3996b164de4b823bdc428ce0a3513ad6e0041868`).

The runtime was initially unpaused, with one supervisor and one of each worker.
The live controller held 42 terminal tasks and no live activations. Supported
pause and stop reached zero workers, and STOPPED prevented scheduled ensure
from restarting during the gate. Worker cursors were all `1490`; the narrator
cursor was `525`. Control files and cursors were retained through the checkout.

## Deployment validation

Status: deployed and verified. The runtime was resumed to its prior unpaused
state; PAUSED and STOPPED were both absent at the final check.

Runtime source commit: `755aa885b3d4bf8b95cd58e89341c83129eb9b70`.
Expected controller build (14 files):
`cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`.
Controller schema remains 6. External admin ingress is still unavailable;
issue #92 remains implementation work rather than a deployed complete feature.

The existing `deploy_controller.sh` gate passed without bypass flags:

- Controller/workers/planning: **1,917 passed, 10 skipped**, two warnings,
  726.66 seconds.
- Hub/controller API: **318 passed**, one warning, 57.93 seconds.
- Total: **2,235 passed, 10 skipped**, no failures. The ten skips require local
  scheduled-task registration/removal permission. The older report of 30 local
  skips describes a separate earlier run; this full gate skipped only ten.
- The combined release's GitHub CI also passed at the exact source commit:
  1,919 unit, 318 hub, and eight bypass tests (**2,245 passed**, no skips).
  Run: https://github.com/Decksx/agent-swarm/actions/runs/38778302429.
- Full local suite logs and CI logs were preserved in the local import workspace
  as `deploy-suite-0.log`, `deploy-suite-1.log`, and `ci-merged-release.log`.

The script verified all 14 remote file digests, restarted `agent-hub`, observed
the authenticated application come back, and passed deployment parity. Follow-up
preflights for **claudecode, gemini and chatgpt** all reported the same checkout,
running and on-disk build above. Production Git status was clean.

Final runtime sample, 2026-10-15 around 17:54 UTC:

- Supervisor PID **43060**, fresh heartbeat.
- ChatGPT **20468**, Gemini **25392**, Claude **42576**, all children of 43060,
  all executing from `C:\swarm-prod\agent-swarm`; one process per identity.
- Tower `agent-hub`: running, host PID **1752441**, started
  `2026-10-15T17:51:24.573163393Z`.
- Scheduled `AgentSwarmSupervisor`: its manual post-restart invocation and the
  subsequent scheduled run succeeded; latest run `2026-10-15T17:54:22Z`, result
  **0**. Its action still uses production `pythonw.exe` / `run_hidden.pyw` and
  Git Bash `swarm_ctl.sh ensure`. Repeated ensure left one supervisor.
- Worker cursors remain **1490** for all three identities; narrator cursor
  remains **525**, with no history replay.
- Live status remains schema **6**, 42 terminal tasks (28 CANCELLED, 11 COMPLETE,
  3 SUPERSEDED), and no live activations (120 DONE, 6 EXPIRED).

Production stays explicitly pinned at the tested runtime source commit above.
A later merge of this receipt changes documentation only and does not require
another controller build or restart. No real controller task was issued.
