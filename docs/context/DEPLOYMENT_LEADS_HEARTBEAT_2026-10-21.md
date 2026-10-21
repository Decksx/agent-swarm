# @Leads, heartbeat retry and held-queue cleanup — 2026-10-21

Claude owned all three operations, and Codex reviewed each exact head and
disposition. Times are UTC. Codex independently audited the runtime of #131 and
#132 at 16:47Z ([audit](https://github.com/Decksx/agent-swarm/pull/132#issuecomment-6321467260)).

## 1. `@Leads` and the #60 boundary (#131): relay only, about 16:02

Codex implemented David's `@Leads` request and recorded the boundary David
approved for #60. Claude reviewed the exact head and owned the rollout.

- **Review.** Claude approved `8818a4a928c3dd92486299449322247623efb4c0`
  ([review](https://github.com/Decksx/agent-swarm/pull/131#issuecomment-6320159980)).
  Claude ran the three changed test files (274 passed) and the view-budget
  tests (12 passed). Eight reviewer mutants of `lead_chat.mentions` were all
  killed.
- **Merge.** `a36b63feb416bba30d7fa8c0e35ef18ccc368446` was merged pinned, and
  its tree equals the approved tree. Main CI run 39629115926 passed all four
  jobs.
- **Scope.** Among runtime files only `lead_chat.py` changed. Only
  `lead_relay.py` and `lead_relay_backends.py` import it, and the hub and
  controller were untouched.
- **Order: move, then stop, then start.** Moving first means any relay created
  afterwards can only load the new code, even if the 5-minute trigger fires in
  between (Codex's #1795).
  1. The checkout moved from `2d1574d` to `a36b63f` at 16:02:34Z.
     `lead_chat.py` sha256 is
     `cc6fe0549bad906e223720d20afa8dfff7d8ab1f73f3ca1ad3848d6c326960cc`.
  2. Relay 49216 was stopped.
- **Deviation.** Claude's `schtasks /Run` did not start a relay: the task read
  `Ready` with last result 127. The most likely cause is that `IgnoreNew`
  dropped the run while the old instance was still exiting. This is not
  verified, because the TaskScheduler Operational log is disabled on this
  host. The task's own trigger started **41788 at 16:04:22.90Z**, so the relay
  was down for about 107 s. The cursor resumes, so no message was lost.
- **After.** Delivery, session, attempt, wake and reservation state was
  unchanged.
- **Alias check, read-only.** Against the production modules: admin `@Leads`
  maps to both leads, admin `@leadership` to none, and a lead's
  `HANDOFF @Leads:` to none.
- **Not yet observed:** a real admin `@Leads` delivery, end to end.
- **Procedure fix.** Before `/Run`, wait until the task is no longer
  `Running`.
- **Receipt:** [#131 comment 6320537340](https://github.com/Decksx/agent-swarm/pull/131#issuecomment-6320537340).

## 2. Heartbeat rename retry (#132, fixes #72): supervisor only, about 16:14

- **Change.** `write_heartbeat` keeps its temp-then-replace write. It now
  retries only `PermissionError` (WinError 5), at 0.05, 0.1 and 0.2 s, and then
  makes one last attempt. A final failure reaches the existing nonfatal
  warning, and the last good heartbeat is kept.
- **Background.** Production had logged 93 such failures since 2026-09-21. The
  gaps between them never approached the 120 s staleness window.
  `swarm_ctl.sh start` and `SingleInstance("supervisor")` already prevent a
  duplicate supervisor.
- **Tests and review.** Claude killed 7 of 7 mutants, and a real Windows
  handle probe reproduced WinError 5 and showed the recovery. Codex approved
  `19c159b55a032e2fefbbeec9092372579273ac07`
  ([review](https://github.com/Decksx/agent-swarm/pull/132#issuecomment-6320388606)).
- **Merge.** `1afa9ccc5809b5cd61647f0f5bec682a0110bb91` was merged pinned on
  top of `a36b63f`, with a patch-id equal to the approved patch. Main CI run
  39631727504 passed.
- **Rollout.** There were no live activations (DONE 121, EXPIRED 6).
  1. `pause`, then `stop`. Supervisor 32136 stopped on request, leaving 0
     workers.
  2. The checkout moved to `1afa9cc` at 16:13:56Z.
  3. With the task reading `Ready`, STOPPED was withdrawn and
     `schtasks /Run AgentSwarmSupervisor` was run.
  4. **Supervisor 39260 was created at 16:14:00Z.** Preflight passed and the
     heartbeat was fresh.
  5. `resume`. Workers 45100, 46776 and 47460 started.
- **After.** The hub build was unchanged (`0833f9ad1bd2`, loaded = disk), and
  relay 41788 was untouched.
- **Deviation.** Claude's rollout script stopped on its own SIGPIPE (`status |
  head` under `pipefail`) right after the stop. Nothing beyond the stop had
  changed, and the remaining steps were run by hand.
- **Receipt:** [#132 comment 6320726466](https://github.com/Decksx/agent-swarm/pull/132#issuecomment-6320726466).

## 3. The last four held codex-lead deliveries: about 16:50

- **Disposition.** Codex chose to cancel, not replay, exactly #1769, #1771,
  #1775 and #1779. Each was an exact-head review handoff that had already been
  completed interactively
  ([disposition](https://github.com/Decksx/agent-swarm/pull/129#issuecomment-6321467832)).
- **Method.** The four rows were rechecked and a dry run matched them. Relay
  41788 was stopped at 16:49:46.38Z, and
  `lead_relay.py cancel … --confirm` returned rc 0 at 16:49:46.57Z. No task
  disable was attempted: if the relay had restarted first, the CLI lock would
  have refused the confirm. Relay **34648** started at 16:49:47.32Z.
- **After.**
  - claude-lead: 33 delivered, which is the earlier 32 plus #1799.
  - codex-lead: 34 cancelled, which is 30 plus 4, and **0 held**.
  - Sessions, wakes (25), attempts (33) and reservations (0) were unchanged.
  - Codex is still unregistered.
- **Receipt:** [#129 comment 6321505602](https://github.com/Decksx/agent-swarm/pull/129#issuecomment-6321505602).

## State at the end

- Production is detached at `1afa9cc`, with hub build `0833f9ad1bd2`.
- Relay 34648 and supervisor 39260 are running.
- claude-lead is bound to `b2b425b8` and enabled.
- codex-lead is unregistered, with nothing held.
- The next step is the [Codex CLOSED-proof plan](../design/113-codex-closed-proof-plan.md).
