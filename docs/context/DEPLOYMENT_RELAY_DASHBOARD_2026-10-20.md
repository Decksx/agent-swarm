# Relay caps and dashboard deployments — 2026-10-20

Claude owned both rollouts; Codex reviewed each exact head. Times are UTC.

## 1. Relay cap accounting, relay only (#126) — ~22:02

David asked in hive #1717 why the caps were hit so fast. Live notices to an
open session were counted as wakes, and the quota was checked before
ownership. PR #126 counts only headless launches, checks the quota only on the
CLOSED path, keeps the lead-to-lead chain as a separate anti-loop rule, and
sets the defaults to 12/hour, **100/day** (David's request) and chain 12.

- **Review and merge.** Codex approved `77048dcad5ba856f7a6cc4ee12746d477b905ee7`
  (comment 6302646612). All four checks passed in run 39502309525. Merged as
  `a07a88fb6ed820f0a3de87312a67eefda5c0a245`, pinned to the approved head;
  the merge tree equals the approved tree.
- **Precheck.** There was no `LEAD_RELAY_*` override in the session, user or
  machine environment, or in the login profiles, so the effective caps are the
  defaults. There were 0 reservations and 0 active deliveries.
- **Checkout.** `C:\swarm-prod\agent-swarm` moved from detached `7a29f90` to
  detached `a07a88f`. It was clean, and the four `lead_relay*.py` files were
  hash-identical to their blobs.
- **Relay-only restart.** Daemon 45684 was stopped and
  `schtasks /Run AgentSwarmLeadRelay` started 20988, and `meta.owner` named
  it. Binding, chain, cursor, open/held set and the 25 `wakes` rows were
  identical before and after.
- **Hub untouched.** `hub/` and `controller/` were unchanged since `7a29f90`;
  build `ab69ad05…` stayed loaded.
- **Live-path confirmation.** This happened naturally, not manufactured:
  admin #1737 was delivered `(live)` (#1738) and ACKed (#1739), and `wakes`
  stayed at 25.
- **Receipt:** #126 comments 6302764973 and 6303026965.

## 2. Dashboard, full procedure (#128) — 00:02 to 00:20 on 2026-10-21

David asked in hive #1737 for relay counters and a project and task view on
the chat page. PR #128 adds `controller/board.py` (its own `BOARD_DB`), the
relay's 30-second snapshot push (`lead_relay_status.py`), a tabbed panel and
`lead_chat.py board`.

### Review history

- Codex requested changes at `a236d22` for two reasons. Concurrent updates
  could strip a done task's evidence. Separately, cached panel data stayed
  "0 s ago / running" through failed refreshes.
- At `4dbe0b4`, Codex's scheduled review (pilot source #1754) found that a
  request that never settles still froze the panel.
- Approved at `d6cb3ec7a699263f47547806de61ba5f33b29968` (comment
  6304041788), with all four checks passing in run 39513733269.
- Merged as `0acbdb75a542847bb0d19fcdb97809f0d24a6b57`, pinned. Main had moved
  to #127, so the merge tree differs from the reviewed tree by exactly #127's
  patch: the patch-id is identical, and the two PRs share no files. Main CI on
  the merge commit passed (run 39514801509).

### Hold

The deploy changes production `lead_chat.py`, which the #127 pilot pinned by
hash. It was held until the pilot was paused and deleted (#1772).

### Steps

1. **Precheck.** No live activations (121 DONE, 6 EXPIRED). Loaded build
   `ab69ad05…`.
2. **Pause, then stop.** Used `swarm_ctl.sh`. This left 0 workers running and
   the supervisor stopped.
3. **Checkout.** Moved from detached `a07a88f` to detached `0acbdb7`. It was
   clean, and 23 hub, controller and relay files were hash-identical to their
   blobs.
4. **`deploy_controller.sh`.**
   - Core suite: 2653 passed, 10 skipped. Hub suite: 412 passed.
   - All 17 digests matched on Tower, and `agent-hub` was restarted.
   - Preflight: checkout, running and disk all at **build `0833f9ad1bd2`**,
     schema 6.
   - A `--tests-only` run from a scratch clone of the same commit reported
     `487a06904a3a`. That clone had `core.autocrlf=true` and checked out LF
     blobs as CRLF. Production has `autocrlf=false` and deploys Git's exact
     bytes.
5. **Supervisor.** `stop` leaves `control/STOPPED`, which makes the task's
   `ensure` hold off. I removed it, which is what `start` does to withdraw a
   stop, and ran `schtasks /Run AgentSwarmSupervisor`. The supervisor came up
   as 32136 with workers 47496, 17004 and 46624. The heartbeat was fresh and
   the swarm unpaused.
6. **Relay-only restart.** Reservations and active deliveries were both 0
   immediately before. Daemon 20988 was replaced by 51160 (`meta.owner` 51160).
7. **Live checks.**
   - `GET /relay/status`: available, about 22 s old, pid 51160, caps 12/100/12.
   - `GET /controller/status`: loaded = disk = `0833f9ad1bd2`.
   - `GET /board`: empty, then seeded with the night's real work using
     `lead_chat.py board` (2 projects, 14 tasks, every done task with its PR
     link).
8. **Backup — taken after the deploy, not before.** The 10-19 §6 checklist
   doesn't list it, but earlier rollouts (for example the 10-16 lead-identities
   receipt) backed up before applying. #128 created only the new `board.db` and
   changed no schema in `chat.db` or `controller.db`. A backup of the deployed
   state is at Tower
   `data/backups/dash128-20261021T002028Z/`: online SQLite backups of
   `chat.db`, `controller.db` and `board.db`, each with `quick_check` = ok, plus
   `app.tar.gz`. Directory 0700, files 0600. **Next hub deploy: back up first.**

**Receipt:** #128 comment 6304814760.

## Not verified here

The rendered page behind David's admin Basic-auth login was not viewed by
Claude. Claude doesn't enter credentials. The page's script was exercised in
Node with fake data and clocks in `hub/test_board.py`, and rendered from the
real template before the review fixes.
