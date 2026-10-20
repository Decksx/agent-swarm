# Claude lead handoff — 2026-10-20

This replaces [HANDOFF_CLAUDE_2026-10-19.md](HANDOFF_CLAUDE_2026-10-19.md) as
the current Claude handoff. That document still holds the reference sections:
how the leads talk (§3), the relay design (§5), the deploy procedure (§6) and
the gotchas (§8). Read this one first, then `AGENTS.md`, `docs/context/README.md`
and the dated sections at the top of `2026-10-15/PROJECT_CONTEXT.md`.

Start the new chat in **`C:\git`**, because Claude's memory is keyed to that folder.

## 0. Do these first, in order

> **Completed 2026-10-20 (~21:20 UTC).** `claude-lead` is bound to
> `b2b425b8-954c-4f9e-bbf0-6f7f6e8acde8`, enabled. Its bounded proof passed:
> #1701 → ACK #1703, interactive confirmation #1708, and the
> [receipt on #113](https://github.com/Decksx/agent-swarm/issues/113#issuecomment-6301684024).
> **Do not repeat the proof for this verified binding.** Any session with a
> different id still needs its own registration and proof. This proof does
> not establish Codex CLOSED delivery or an always-on Codex watcher.

1. **Re-bind the relay if the session is new.**
   - Check the supported status first:
     `C:\Python311\python.exe -X utf8 C:\swarm-prod\agent-swarm\lead_relay.py status`.
   - Find this session's local CLI UUID (`sessionId` in
     `~/.claude/sessions/<pid>.json`; not the remote-control `session_…` id).
   - If `claude-lead`'s `session_id` already equals that UUID, the binding is
     done; skip to item 2. Otherwise, while it points at another session that
     is `enabled=1`, a handoff from Codex or an `@claude-lead` message from
     David wakes that other conversation headlessly (this happened with #1692).
   - Run `register` (it resets `enabled=0`; it is refused while a run is
     reserved), then follow the **bounded bridge
     proof** recipe in the 10-19 handoff §5:
     1. Precheck.
     2. David closes the real terminal.
     3. He enables the relay.
     4. He posts `@claude-lead BRIDGE-PROOF <8> <word>`.
     5. Expect the ACK and a status line.
     6. He resumes with `claude --resume <UUID> --remote-control`.
     7. He **sends a message**.

     Keep the binding disabled at all times except during the agreed bounded
     proof window (step 3 to step 7), and enable it only for that window. It
     stays enabled only if the proof passes. Re-register the new session before
     any test.
   - The 2026-10-20 proof also covered the **post-deploy stdin smoke check**.
     Since #122, prompts reach Claude on stdin; the 10-19 bridge proof ran
     with argv.
2. **Arm the hive watcher.** An open lead only sees messages it reads; the
   relay's live path never injects into an open chat.
   - Run `C:/Python311/python.exe -I C:/git/.claude-tools/hive_watch.py 1686`
     from the Monitor tool (see `C:\git\.claude-tools\README.md`).
   - Re-arm it every 30 min.
   - ACK each `RELAY DELIVER … (live)` that has a token, using that token.
3. **Catch up on the hive:**
   `C:\Python311\python.exe -X utf8 C:\swarm-prod\agent-swarm\lead_chat.py read --as claude-lead --since 1686`.

## 1. State at handoff (checked 2026-10-20, ~21:00 UTC)

This is a dated, historical snapshot. For current state, read the supported
`lead_relay.py status`; don't update the fenced id list below as new messages
arrive.

| Thing | State |
|---|---|
| Production `C:\swarm-prod\agent-swarm` | Detached at `7a29f90` (the #122 deploy, relay only); `origin/main` `0e24561` is docs-only beyond it |
| Supervisor, workers | Running; parity passed in Codex's morning audit (#124) |
| Relay | `AgentSwarmLeadRelay` scheduled task, PID 45684. At 21:03 UTC `claude-lead` → `a750400a…` is **`enabled=0`**: it was disabled after #1692 woke that old session headlessly at 20:59 (re-bind it: §0). `codex-lead` **unregistered**. Chain 1 of 6 |
| **Held Codex queue** | At 21:03 UTC, **22** deliveries for `codex-lead` were `held(unregistered)`: `1519, 1535, 1538, 1550, 1552, 1554, 1557, 1558, 1560, 1562, 1564, 1571, 1583, 1588, 1649, 1663, 1666, 1669, 1673, 1676, 1679, 1687`. Codex has already read all of them. Most are handoffs, but they also include David's authorization #1649 and his praise #1687. **Clear them before Codex is ever registered.** Otherwise Codex would be woken for stale history: per-session reservations and the caps would pace those wakes, but they would still replay. Any cancellation must be a reviewed tool or procedure that names exactly these ids and leaves newer deliveries alone. Don't edit `lead_relay.db` by hand |
| Codex OPEN delivery | The native same-thread scheduled turn is proven **idle** (#1597→#1598), **busy** (#1601→#1603) and **after a desktop app restart** (#1628→#1635; turn `01a15a09…` ran about 78 s after the reopen, before the next slot, and was attributed to the new desktop app-server). Schedules are **paused**. **No always-on watcher yet** |
| Codex CLOSED delivery | Implemented and deployed (#122). Not registered and not proven. Its proof needs the Codex desktop app fully quit |

## 2. Open work, swarm

1. **Always-on Codex watcher.** Codex owns the design; Claude reviews. It's
   the biggest remaining gap. On 10-20 a Claude approval sat unseen until
   David nudged Codex.
2. **Clear the 22 stale held Codex deliveries** (§1) with a reviewed mechanism,
   *before* item 3.
3. **Codex CLOSED path:**
   - register Codex's actual thread and workspace (see #120 / the
     `113-codex-ownership.md` §4 registration);
   - run the bounded proof with the app fully quit;
   - check that a woken `codex exec` can reach the hub under its sandbox, with
     no bypass flags.
4. **Relay caps.** 4 wakes/hour, 20/day and a lead↔lead chain of 6 throttled
   real back-and-forth on 10-19. Propose new values with Codex.
5. **Backlog:** #71 (a stale 2026-09-22 handoff PR; close or refresh it),
   #72 (supervisor heartbeat WinError 5, harmless), #67, #60 (swarm), #62,
   #69, #89. #93–95 stay parked.

## 3. Comic automation (`Decksx/cbz-automation-suite`, default branch `master`)

**Merged 2026-10-20**, all exact-head cross-reviewed, CI green, pinned merges:

| PR | What | Merge |
|---|---|---|
| #93 (Codex; Claude reviewed) | CI `-n 4 --dist loadfile`, pip cache, JUnit artifact. About 3× faster; outcomes identical per test | `b9f02dd` |
| #94 (Claude; Codex reviewed) | Fixes #82. `_replace` retries only WinError 5/32, about 3 s. Copied-source deletes revalidate right before deleting. Operator moves re-run their preconditions after any wait | `fedb7d9` |
| #95 (Claude; Codex reviewed) | The Camelia test fixture uses a fixed zip timestamp (2-second-boundary flake) | `00ee8c8` |

**Open:**
- **#60:** SeriesIndex collisions, non-series dirs, empty keys. **Codex leads**
  (hive #1682, #1686); **Claude reviews exact heads**. Codex's implementation
  is draft **PR #96** at `8ef5ab5d643fd2592cd6121fa5efe39f581867c4`, handed off
  for review in hive #1692: 33 new tests, local 2406 passed and 8 skipped. Codex
  asked for review to challenge gate completeness and path identity as well as
  the three original defects. That review is **done** (old session, hive
  #1699: one P2 test gap, no correctness defect). Codex is adding the tests
  (#1709). Re-review Codex's next exact head; don't restart #60 or that review.
- **#32 and #35:** classify→move→index as one transaction per series, and
  staging operator commands. This is the main correctness project next.

**Permissions:** David's hive #1646 and #1649 give both leads changes to the
library drive, the G: drive and the production DB on G:, plus
pull/commit/merge/push/deploy for the comic project. The rules that still apply:
- back up before applying any change;
- check G:'s free space first (it was nearly full on 10-19);
- cbz_watcher moves files into the library even while the DB is frozen;
- the other lead reviews the exact head, CI is green, and the merge is pinned.

**How to work in the comic repo:**
- Use a fresh clone from `origin/master`; the two dirty local checkouts stay untouched.
- `core.autocrlf=true`: the working tree is CRLF and the index is LF. Preserve
  the original line endings, or the diff shows whole-file churn.
- Tests: `pytest -n 4 --dist loadfile`. The local full suite is 2373 passed
  and 8 skipped at `00ee8c8`. Per JUnit, the skips are 5 Windows
  symlink-privilege tests, 2 deliberately unreadable `corrupt_zip` corpus cases
  and 1 test needing the absent, untracked `routing.json`.

## 4. Lessons from 2026-10-20 (in addition to the 10-19 §8 list)

- **A retry or wait makes earlier checks stale.** Every irreversible step after
  a wait (delete, move under an approval, record a decision) re-runs its own
  precondition. Codex caught two such bugs in #94's first head: one data loss,
  one unverified promote.
- **Check that mutation baselines pass on unmodified code before reading the
  kill count.** One run of 12/12 "killed" was meaningless, because the new
  test was failing anyway.
- **Quoting:** inside `ssh '…'`, a single quote in embedded Python (for
  example `cmd['id']`) silently becomes a bare name. That happened twice, once
  after a POST had already been sent. Use double quotes, or a script file.
- **`gh pr edit`** fails without the `read:project` scope. Use
  `gh api -X PATCH repos/<o>/<r>/pulls/<n> -F body=@file`.
- **An open lead must watch the chat**, and must ACK live deliveries with the
  DELIVER token.
- **Reviews and handoffs to Codex aren't delivered to it** while it's
  unregistered. A nudge from David may still be needed until item 1 of §2 lands.

## 5. Elsewhere

- **Homelab and media work** from this session is in Claude's private memory,
  under `C:\Users\david\.claude\projects\C--git\memory\`, and in a local
  handoff note `C:\git\HANDOFF_PRIVATE_2026-10-20.md`. That covers DNS,
  UniFi, Chaptarr, Audiobookshelf and download cleanup. It's deliberately not
  in this public repo.
- **Session tools** are in `C:\git\.claude-tools\`.
