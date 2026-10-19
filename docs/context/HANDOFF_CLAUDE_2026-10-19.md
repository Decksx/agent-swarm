# Claude lead handoff — agent hub / hive chat (2026-10-19)

For the next Claude session that picks up agent-swarm. Read this first, then
`AGENTS.md`, `docs/context/README.md` and `docs/context/NEXT_STEPS.md`.
Sections 1–9 were checked against the live system on the morning of 2026-10-19,
before the takeover. The checkpoint below supersedes them where they differ.

## 0. Current checkpoint (2026-10-19, after the takeover)

The new Claude lead session took over at about 16:00 UTC on 2026-10-19.
Codex independently verified the first two items below in its review of #118.

| Thing | State |
|---|---|
| Claude lead session | Local CLI session UUID `a750400a-9432-40d2-af7c-da1f613a1035`, cwd `C:\git`. This UUID is what the relay resumes. The remote-control id `session_01VSdU7KuoxeWRTYAx57W5P4` is a different thing, and the relay never uses it |
| Relay registration | `claude-lead` → `claude a750400a-…`, workspace `C:\git`, **`enabled=1`** since the proof passed |
| Relay daemon | Running from the scheduled task `AgentSwarmLeadRelay` (details in §5). It was PID 3812 at takeover, with a parent chain of bash → pythonw → Task Scheduler's svchost, so it is outside any chat's process tree. A second `once` exited 3 with `REFUSED: another relay holds …lead_relay.db.lock` |
| New-session bridge proof | **Passed** on 2026-10-19 for design §7 items 1–4: admin #1541 → headless DELIVER #1542 → ACK #1543 → status #1544, then the same UUID was resumed with the turn in its transcript. The receipt is on #113 (comment 6272343082). Items 5–6 are backend properties and were not re-run. **Qualification:** the headless run had no claude-in-chrome MCP server and lacked some deferred tools (for example SendUserFile), which came back on interactive resume. So the pass covers the engineering/chat path and the persisted settings and conversation. It does not show identical tool availability in every mode. The 2026-10-16 proof covered the old session `f7daaff8` only |

**Correction to the takeover.** The new session ran `enable` straight after
`register`, before any proof. That went against the contract in
`docs/design/113-lead-relay.md` §7 and §9. Codex caught it in review, and the
session was set back to `enabled=0` at 16:05 UTC. While it was disabled,
`claude-lead` still received the live path (a DELIVER notice and an ACK), but
never a headless launch. David enabled it for the bounded proof in §5 at about
16:36 UTC. The proof passed, so it stays enabled.

**An open lead only sees what it reads.** When the lead's chat is open, the
relay takes the live path:
- It posts `RELAY DELIVER #N … (live)` in the hive chat and marks the message
  `notified`.
- Nothing is put into the open conversation, and an interactive session takes
  a turn only when someone sends it a message. On 2026-10-19 codex-lead's
  HANDOFF #1545 sat unseen for minutes until David prompted the session.
- So an open Claude lead should run a chat watcher. A Monitor-run script polls
  `lead_chat.py read --as claude-lead --since <cursor> --mentions` every 30 s
  and prints each message from a sender other than `claude-lead`. It keeps
  its cursor in a file so that it survives re-arming, and it prints errors
  rather than hiding them.
- A Monitor expires after **30 minutes at most**, so the lead must re-arm it on
  every expiry while the conversation stays open. The cursor keeps the read
  position but does not close the gap: while no monitor is armed, nothing
  arrives. The watcher is a session-local stopgap, not part of the relay.
- The lead ACKs a live delivery with the attempt token from the DELIVER line.
- Whether the relay could push into an open session directly is an open design
  question. The session file advertises a local messaging pipe and a
  `notify_idle` feature, but this is unverified.

**Next:** §7 item 2, Codex wake support.

**Start the new chat in `C:\git`** (not `C:\git\agent-swarm`). Claude's
persistent memory for this work is keyed to that folder. The relay
registration also uses `C:\git` as the workspace.

## 1. Purpose (David's words, in effect)

The swarm exists so that **Claude and Codex collaborate directly**. They keep
each other honest and make progress without David relaying messages between
chats. Comic automation (`Decksx/cbz-automation-suite`) is the eventual target.
The **hive chat** is David's window into the swarm. He watches progress there,
sees work handed between the leads, and answers the questions only he can answer.

Judge every change by whether it moves that outcome. A chat post, or a
background bot replying, is not the same as the other lead's interactive
session receiving and acting on a handoff.

## 2. Permissions and the gates that still apply

- David has given standing permission, on 2026-10-15 and 2026-10-16, for Claude
  and Codex to **push, pull, merge and deploy** agent-swarm without asking. The
  same permission covers the comic automation suite. Do not ask again for
  routine operations.
- The gates stay:
  - The **other lead reviews the exact commit**.
  - CI is green.
  - Merges are pinned with `gh pr merge --merge … --match-head-commit <sha>` (or an API `sha=`).
  - Deploys use the supported controls plus parity checks.
  - Real work runs only through controller-issued activations.
- Comic automation keeps its **operator-only batch/library data rules**.
- The relay's woken turns run under the normal permission policy, with no bypass.

## 3. How the two leads talk

- **Reviews and handoffs:** post these as **GitHub PR comments** that name the
  exact commit, the findings, the checks run and the next owner.
  - Start Claude's comments with `<!-- agent-swarm:author=claude-lead -->`.
  - On GitHub, write `codex-lead` **without** the `@`. The cloud bot
    (`chatgpt-codex-connector`) is invoked with `@codex review`, as its own PR
    comments say, and it is not the interactive Codex lead. An ordinary
    exact-head PR comment, mirrored in the hive chat, is the reliable path to
    the Codex lead.
- **Hive chat:** mirror each handoff, review, merge, deploy and question as one
  line:
  ```powershell
  C:\Python311\python.exe -X utf8 C:\swarm-prod\agent-swarm\lead_chat.py post --as claude-lead "HANDOFF @codex-lead: <text>"
  C:\Python311\python.exe -X utf8 C:\swarm-prod\agent-swarm\lead_chat.py read --as claude-lead --since <id>   # JSON lines; add --mentions for yours only
  C:\Python311\python.exe -X utf8 C:\swarm-prod\agent-swarm\lead_chat.py find --as claude-lead "<exact text>"
  ```
  - These were checked against `lead_chat.py <command> -h` at `ce5565b`.
    `-X utf8` matters because the console is cp1252, and a "→" in a message
    otherwise crashes the display after a fetch that worked.
  - Only report a post as made when it prints `CONFIRMED`; it reads the post back.
  - Questions for David go to `@admin`.
  - Conventions are in `docs/design/lead-chat.md`.
- **Hub:** `http://192.168.42.50:8050`, on Tower.
  - Identities are `claude-lead`, `codex-lead` and `relay`. They are non-admin,
    and the controller's ingress ignores them.
  - Their secrets are OfficePC **user** env vars: `CLAUDE_LEAD_HUB_SECRET`,
    `CODEX_LEAD_HUB_SECRET` and `RELAY_HUB_SECRET`.
  - All five exposed secrets were rotated on 2026-10-16 (PR #115). The admin
    password is in a file on David's desktop.
- **Codex** works in its own app, with Agent Swarm project id
  `466ce426-aff5-4a45-a7de-6a20bd5c395a`. It posts PR comments and hive lines
  the same way, as `codex-lead`.

## 4. Where things stand

| Thing | State |
|---|---|
| `origin/main` | `ce5565b`, the merge of #117 |
| Production checkout `C:\swarm-prod\agent-swarm` | Detached at `ce5565b` |
| Hub container | Build `ab69ad056404`; adds the `GET /messages/high-water` route |
| Supervisor and workers | Running. Restarted 2026-10-19 08:55 after a reboot, via the `AgentSwarmSupervisor` scheduled task |
| Relay daemon (`lead_relay.py run`) | At this morning's snapshot it was not running: it died in the 2026-10-19 reboot and had no auto-start. **Now restored**; see §0 |
| Open PRs | Only #71, a stale 2026-09-22 handoff doc. Close it or refresh it |

Delivered and merged recently:
- #106, #107 and #108: external ingest, with a live proof. `EXT-92-PROOF-20261016-108` is at `READY_EXTERNAL_REVIEW`.
- #110 and #111.
- #112: lead identities, issue #109.
- #114: relay design v3.
- #115: secret rotation.
- #116: the relay.
- #117: the relay prompt names `lead_chat.py` by absolute path.

The receipt for this run is on issue #113 (comment 6227267939).

**Proven on 2026-10-16:**
- The live relay path (#1515 → #1516 → #1517).
- A headless bridge into the real interactive Claude session, in two sequential
  runs (#1522 → ACK #1525 → status #1526, and #1524 → ACK #1528 → status #1529).
- Codex confirmed that the reopened session's history was intact.

## 5. The wake-up relay (#113): what it is and what to do first

- **Contract:** `docs/design/113-lead-relay.md` (v3).
- **Code:** `lead_relay.py` (the daemon, plus the `register`, `enable`,
  `disable`, `status`, `run` and `once` CLI) and `lead_relay_backends.py`
  (process and session plumbing). Tests are in `tests/test_lead_relay.py` (91 tests).
- **How it works:**
  - **What wakes a lead:** a hive message mentioning the lead from `admin`, or a
    `HANDOFF` / `QUESTION @x:` envelope from the other lead.
  - **Delivery:** the relay resumes the registered session headlessly and
    expects `ACK #N <token>` back.
  - **Single owner:** a file lock plus an owner row in the database.
  - **Ownership check for Claude:** it reads `~/.claude/sessions/<pid>.json`
    (pid plus `procStart`), so it never resumes a session that is open
    interactively. A conversation that is already OPEN gets the live notice
    (`notified`) and no headless spawn. `held(session-opened)` is narrower: it
    applies only when a session changes from CLOSED to OPEN during the final
    pre-spawn checks.
  - **Failure handling:** a failed pre-spawn check holds the message rather than
    dropping it.
  - **`register` always leaves the session disabled**, so a new session id
    never inherits approval. A disabled session gets the live path only. Run
    `enable` only inside the bounded proof below, or after that proof passes.
- **State:** `C:\swarm-prod\agent-swarm\control\lead_relay.db`, plus `.log`/`.out`.

**Done at takeover (2026-10-19, verified by Codex):**
1. **Re-registered** `claude-lead` from the old session `f7daaff8-…` to
   `a750400a-…`. It was disabled until its proof passed, and is enabled now
   (see §0). For any later lead chat:
   ```powershell
   cd C:\swarm-prod\agent-swarm
   C:\Python311\python.exe lead_relay.py register --lead claude-lead --backend claude --session <local CLI session UUID> --workspace C:\git
   C:\Python311\python.exe lead_relay.py status
   ```
   The UUID is the `sessionId` in `~/.claude/sessions/<pid>.json`, not the
   remote-control `session_…` id.
2. **Auto-start:** there is a scheduled task, `AgentSwarmLeadRelay`, copied
   from `AgentSwarmSupervisor`:
   - **Triggers:** at logon, plus a 5-minute repeat.
   - **Settings:** `IgnoreNew`, and `ExecutionTimeLimit` set to `PT0S`. Without
     that limit the default 72 h would kill the daemon.
   - **Action:** `pythonw run_hidden.pyw` → Git Bash →
     `cd /c/swarm-prod/agent-swarm && exec /c/Python311/python.exe lead_relay.py run >> control/lead_relay.log 2>&1`.
   - **Duplicates:** a duplicate start exits 3 on the OS lock. The kernel drops
     the lock when the process dies, so the repeat trigger restarts a crashed
     relay.

**Bounded bridge proof: the recipe for any new binding.** It was run for
`a750400a` on 2026-10-19 and **passed** (receipt on #113, comment 6272343082).
Do not repeat it for `a750400a`; use it the next time a lead session is
re-registered. It proves items 1–4 of design §7 for that session. Items 5 and 6
(an unknown id fails; a second handoff waits) are properties of the backend.
This doc does not claim they have been re-proven. A new binding is enabled only
for the length of this procedure, and stays enabled only if it passes.

**`<UUID>` below is the binding under test.** Take it from the `session_id`
of `claude-lead` in the current `lead_relay.py status` output. That is the
local CLI session UUID from `register`, not the remote-control `session_…` id.
Use the same value in every step. Don't copy `a750400a` from elsewhere in
this doc; it is the binding that was proven on 2026-10-19.

1. **Precheck** (Claude, still open):
   - `lead_relay.py status` shows `claude-lead` → `<UUID>` with `enabled=0`.
   - There are no open deliveries or reservations for `claude-lead`.
   - `AgentSwarmLeadRelay` is Running.
   - Post `READY FOR PROOF` in the hive chat.
2. **Close** the actual OfficePC Claude Code terminal. Closing only the phone or
   remote-control view is not enough. Confirm that no
   `~/.claude/sessions/*.json` file names `<UUID>`.
3. **Open the window** (David, in PowerShell):
   `cd C:\swarm-prod\agent-swarm; C:\Python311\python.exe lead_relay.py enable --lead claude-lead`
4. **Send the test** (David, as admin, in the hive chat):
   `@claude-lead BRIDGE-PROOF <first 8 characters of UUID> <nonce>`
5. **Expect** `ACK #N <token>` and then a status line from `claude-lead`, within
   a few minutes. `lead_relay.py status` should show that message as
   `delivered`, `ack`.
6. **Close the window on failure.** If there is no ACK within 10 minutes, or
   anything unexpected happens, run `lead_relay.py disable --lead claude-lead`
   and leave it disabled. The proof has then failed. Record why.
7. **Resume** the same binding from `C:\git`, with Remote Control kept on so
   the phone view works:
   `cd C:\git; claude --resume <UUID> --remote-control` Then **send the session any message**, for example "proof
   done, check it". Resuming does not start a turn, so until you send one the
   session does nothing; it doesn't run the checks or see new hive messages.
   The session then confirms the woken turn appears in the transcript (§7 item
   3) and that the workspace, settings and tools are unchanged (§7 item 4). It
   also restarts its chat watcher (see §0).
8. **Only then** is the proof **passed**, and `enabled=1` stays. Claude
   records the message ids and ACK token on #118 or #113 and in the hive chat.
   A registration, or an ACK on its own, is not a pass.

`codex-lead` is **unregistered**, so message #1519 is held with reason
`unregistered`. Waking Codex is the main open gap. The Codex backend reports
ownership as UNKNOWN, so the relay will not launch it. It needs:
- a way to tell whether a Codex session is open interactively, which is the
  equivalent of Claude's session file;
- its own bridge proof;
- Codex's review.

## 6. Deploy procedure (agent-swarm)

1. `swarm_ctl.sh pause`, then `swarm_ctl.sh stop`.
2. `deploy_controller.sh` runs the full gate.
3. Advance `C:\swarm-prod\agent-swarm` to the deployed commit: detached, with a
   byte-for-byte check against the commit.
4. Restart the supervisor with `schtasks /Run /TN AgentSwarmSupervisor`, so it
   runs outside Claude's process tree.
5. Resume, then check parity.

Write a receipt in `docs/context/DEPLOYMENT_*.md` and link it from `README.md`
and `NEXT_STEPS.md`.

## 7. Open work, in suggested order

1. **Codex wake support** is the current next work. It needs an ownership
   check, a bridge proof and Codex's review. claude-lead owns it and codex-lead
   reviews (hive #1549). Re-registration, auto-start and the `a750400a` proof
   are done (§0).
2. *(Done 2026-10-19: the bounded bridge proof for `a750400a`, §5. This
   covers Claude only. The two-way "without David relaying" loop closes only
   once item 1 is implemented and proven.)*
3. **Pin the hub container's startup `pip install`**, a small follow-up from #112.
4. **An admin password self-service script**, but only if David wants one; he
   asked whether he has a way to set his own password.
5. **The external review chain #93 → #94 → #95**, which David parked behind
   #109 and the relay. Work on it only after 1–2, or when he says so.
6. **The comic suite CI-efficiency audit** (`cbz-automation-suite#92`), queued
   behind the relay. Measure first, and never weaken required checks.
7. **Older backlog:**
   - #72: supervisor heartbeat WinError 5.
   - #67: task-creation format discovery.
   - #60: swarm development bypasses the ledger.
   - #62: repo organisation.
   - #69: design question.
   - #89: annotate superseded PRs.

## 8. Gotchas learned the hard way

- Verify the artifact, not the report. Mutation-test guards, and make tests
  assert behaviour, not wording.
- On Windows, use Git Bash for Bash-dependent tests. Report partial reruns and skips honestly.
- **Stage before experimenting with a file.** A PowerShell `>` writes UTF-16,
  and a later `git checkout` once wiped untracked mutation work.
- Write multi-line scripts to files rather than nesting heredocs, because
  apostrophes break Bash.
- For hub CLI output, run the CLI with `python -X utf8`; in your own scripts, use `sys.stdout.reconfigure(encoding="utf-8")`. The
  console is cp1252, and "→" crashed a watcher.
- In jq, `test("\\[")` failed silently; `contains()` plus dedupe works.
- A deploy that doesn't advance the production checkout makes preflight refuse
  the restart. Always advance it, with a byte check.
- Never claim an exposure was nil without checking. Codex caught one, and the
  result was the #115 rotation.
- The interactive leads and the background workers (claude/chatgpt/gemini
  `_worker.py`) are different things. Connecting one does not connect the other.

## 9. Key files

- **Lead identities and chat:** `lead_chat.py`, `hub/hub.py`, `hub/test_lead_identities.py`, `tests/test_lead_chat.py`.
- **Relay:** `lead_relay.py`, `lead_relay_backends.py`, `tests/test_lead_relay.py`.
- **Design:** `docs/design/lead-chat.md`, `docs/design/113-lead-relay.md`,
  `docs/design/engineering-leadership.md`, `docs/design/74-external-review.md`.
- **Context and receipts:** `docs/context/NEXT_STEPS.md`, `docs/context/DEPLOYMENT_LEAD109_2026-10-16.md`.
