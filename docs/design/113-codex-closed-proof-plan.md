# Codex CLOSED-path bridge proof: bounded plan (2026-10-21)

The procedure is [`113-codex-ownership.md` §6.2](113-codex-ownership.md) together
with [`113-lead-relay.md` §7](113-lead-relay.md). This plan fills in the exact
commands, observations and abort rules for the current runtime. Claude drafts
it; **Codex reviews this exact head before anything is registered or enabled.**
Nothing here creates a schedule, re-arms the expired OPEN pilot, passes a
bypass flag, or turns on the OPEN queue path, which stays disabled (§3).

## 0. Facts at drafting time (read-only, about 16:55Z)

- **Relay.** Production is at `1afa9cc`, relay pid 34648. codex-lead is
  **unregistered, with nothing held** (34 cancelled). Reservations are 0.
- **Thread.** `01a14068-d723-76a0-a86d-c7d7b34c1b30`. Its `threads.cwd` is
  `C:\Users\david\Documents\Codex`, and its rollout is
  `…\.codex\sessions\2026\10\15\rollout-2026-10-15T10-32-55-01a14068-….jsonl`.
- **With the app open.** The writer-lock probe answers `held`. The backend's
  `ownership()` for that registration answers **OPEN**. The desktop app-server
  is `…\OpenAI\Codex\bin\896a0166b774037a\codex.exe`, which reports
  `codex-cli 0.163.0-alpha.10.2`. That is newer than the `0.162.0-alpha.17.2`
  in §7's table, so this proof is evidence for 0.163 only.
- **Two bin folders exist:** `896a0166b774037a` and `ce4759538b7f2f1a`. With the
  app closed, `CodexBackend.cli()` falls back to the newest folder by mtime.
- **Launch command.** No bypass flag is passed:
  `codex.exe exec resume --json --skip-git-repo-check 01a14068-… -`, with the
  prompt on stdin.
- **Settings the woken run inherits.** `~/.codex/config.toml` sets
  `sandbox_mode = "danger-full-access"` (and `[windows] sandbox = "unelevated"`).
  These are David's settings, and the relay does not widen them. The network
  gate in §6.2 is therefore tested under the configured settings, not under
  the read-only default. The receipt must say so.
- **Codex time budget.** `LEAD_RELAY_CODEX_BUDGET_SECONDS` defaults to 7200 s
  of headless Codex time per 5 h. The relay caps are 12/hour and 100/day.

## 1. Preparation (Claude, after Codex approves this plan; no David needed)

1. **Pin the CLI.** Register with `--cli` set to the app-server path observed
   at that moment, so the woken run doesn't depend on mtime order.
   - If Codex prefers no pin (always the newest install), drop `--cli`. The
     receipt then records which folder was chosen. **Codex decides.**
2. **Register, disabled.** The relay stays running. `register` refuses while a
   reservation exists, and it always writes `enabled=0`.
   ```
   python lead_relay.py register --lead codex-lead --backend codex \
     --session 01a14068-d723-76a0-a86d-c7d7b34c1b30 \
     --workspace "C:\Users\david\Documents\Codex" --cli "<pinned path>"
   ```
   Then confirm with `status` that codex-lead is registered and
   `enabled = 0`. The app is still open, so ownership is OPEN and nothing can
   launch.
3. **Item 5 (an unknown id fails without a new session), read-only.**
   `ownership()` for a random UUID with the same workspace must answer
   UNKNOWN, because it has no `threads` row. An UNKNOWN answer holds the
   delivery and never launches.
   - A direct `codex exec resume <random uuid> -` would also show what the CLI
     itself does, by comparing `~/.codex/sessions` before and after. It is
     **optional, and done only if Codex asks for it**, since it starts a CLI
     process outside the relay.
4. **Baselines.** Record the sha256 of `config.toml`, the newest rollout size
   and mtime for the thread, the `thread_turns` statuses, and the lock file's
   existence and mtime.
5. **Desktop scripts.** Write two scripts to David's desktop.
   - **`Codex Bridge Proof - ENABLE.bat`** refuses unless all of these hold:
     - codex-lead is bound to `01a14068`, with that workspace;
     - there are no reservations;
     - `ownership()` answers **CLOSED**;
     - no desktop `codex.exe app-server` is running.

     Only then does it run `lead_relay.py enable --lead codex-lead`.
   - **`Codex Bridge Proof - DISABLE.bat`** runs `disable` unconditionally.
6. **Observer.** Claude starts a read-only observer. It logs the following
   every 10 s for a fixed 20-minute window:
   - ownership;
   - codex processes;
   - the delivery, attempt and reservation rows for codex-lead;
   - hive messages after the proof message.

   It runs `disable` itself when any abort rule in §3 fires.

## 2. The proof (David, at a time he chooses)

1. **Quit the Codex app completely**, including the tray icon. Claude confirms
   all of the following and records the lock file's state:
   - no app-server process;
   - the lock probe answers `free`;
   - no `inProgress` turn;
   - `ownership()` answers **CLOSED**.
2. **David runs the ENABLE script.**
3. **David posts from the chat page:** `@codex-lead BRIDGE-PROOF 01a14068 <any word>`.
4. **Expected:**
   - the relay sees CLOSED and makes exactly **one** headless launch;
   - the woken run posts `ACK #<id> <token>` and then a status line;
   - the run exits;
   - the delivery ends `delivered`, with one attempt and one `wakes` row.
5. **Item 6 (a second handoff waits).** While the run is still running, Claude
   posts:
   `HANDOFF @codex-lead: BRIDGE-PROOF-2 01a14068: reply with ACK only.`
   - **Pass:** no second launch until the first run has exited and ownership
     reads idle again. Then exactly one more launch, which ACKs.
   - If the first run ends before this can be posted, item 6 is recorded as
     **not exercised**, not as passed.
6. **Reopen the Codex app on the thread.** Check items 3 and 4:
   - both woken turns are visible in the desktop UI;
   - the workspace is unchanged;
   - the `config.toml` hash is unchanged;
   - David sends one message and it is answered normally.

## 3. Abort rules (any one fires: disable codex-lead; nothing is retried)

- No ACK within 10 minutes of the proof message.
- More than one launch for one delivery, or any launch while ownership was not
  CLOSED.
- Any new session or rollout file other than the thread's own rollout.
- A codex process still running 15 minutes after its launch: disable
  codex-lead and report.
  - The relay's own kill comes later, at `LEAD_RELAY_RUN_TIMEOUT` (default 45
    minutes), and it posts `RELAY TIMEOUT`.
  - Claude stops that one process earlier only if David agrees.
- A woken run that wants approval it can't get. It must post its BLOCKED or
  QUESTION status; nothing is approved on its behalf.
- Any failed precondition or supported control during the run: stop and
  report, the same rule as the rollouts.

## 4. After the proof

- **Pass.** The receipt goes on #113, covering all six §7 items, each marked
  passed or not exercised, with the exact evidence. **Codex decides** whether
  codex-lead stays enabled, as claude-lead did after its proof.
- **Fail.** codex-lead stays registered and disabled. The attempt log and the
  observer log are kept.
- **Either way:**
  - update `NEXT_STEPS.md` and the board;
  - no schedule or OPEN watcher is created;
  - the comic #32/#35 reconciliation comes next.
