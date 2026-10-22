# Codex CLOSED-path bridge proof: bounded plan (2026-10-21)

The procedure is [`113-codex-ownership.md` §6.2](113-codex-ownership.md) together
with [`113-lead-relay.md` §7](113-lead-relay.md).
- **Driver.** The plan is carried out by one reviewed, single-use driver,
  `codex_closed_proof.py`, with tests in `tests/test_codex_closed_proof.py`.
- **Who.** Claude runs it in a supervised terminal. There are no desktop
  launchers.
- **Review first.** **Codex reviews this exact head (plan and driver) before
  anything is registered or enabled.**
- **Out of scope.** Nothing here creates a schedule, re-arms the expired OPEN
  pilot, passes a bypass flag, or turns on the OPEN queue path, which stays
  disabled (§3).

Revised after Codex's review of `27e8ad6`
([comment 6322250083](https://github.com/Decksx/agent-swarm/pull/133#issuecomment-6322250083)).

## Successor migration (2026-10-21 evening; supersedes the thread facts below)

Proof `53e110d6` was cancelled before enable. Its target thread `01a14068`
had an orphaned `inProgress` turn, so ownership read UNKNOWN. With David's
approval, the Codex lead then moved to a fresh thread. This follows Codex's
[migration proposal](https://github.com/Decksx/agent-swarm/pull/133#issuecomment-6328204971).

- **Target.** The driver targets thread `01a1609d-cd64-7bd1-9880-2b5b488509d4`
  with workspace `C:\git\agent-swarm`. Its state file is
  `codex_closed_proof.01a1609d.json`. The retired thread and binding are
  refused by the preflight. The ownership rule is unchanged: nothing
  reinterprets the orphaned turn or edits Codex state.
- **The old proof is reconciled once, append-only.**
  `python codex_closed_proof.py reconcile-old` runs under the old driver's own
  lock. It refuses if any of these holds:
  - the old driver (pid 47792, creation `134370937802738350`) is alive;
  - any of the three retained files differs from its recorded sha256;
  - the old state is not `53e110d6` with status `claimed`;
  - a result file exists;
  - any codex-lead attempt launched after the old run began;
  - codex-lead is not registered disabled;
  - a reservation exists.

  Otherwise it creates `codex_closed_proof.53e110d6.reconciled.json`
  exclusively (it never overwrites), with the verdict `cancelled before
  enable`. The old state, cancellation text and log are left byte for byte.
- **`prepare` refuses** if any of these holds:
  - the reconciliation receipt is missing or doesn't match the retained
    fingerprints;
  - any old file has changed since;
  - the old driver is alive.
- **Rollout order:**
  1. Deploy the merged driver.
  2. Run `reconcile-old`.
  3. Use the supported `register` to bind codex-lead to the successor thread
     and workspace, disabled.
  4. Reconcile the then-current codex-lead notices explicitly; ACKing their
     current attempts is receipt only.
  5. Only when David is available: `prepare`, then `run`.
- **Before telling David to quit,** Claude verifies independently that the
  exact target turn has **completed** and that no `inProgress` turn remains
  on the successor thread. A waiting driver is not that evidence.

## App lifecycle: Claude closes and reopens the app (2026-10-22)

David agreed in hive #1893 and #1906 that Claude closes the desktop app,
instead of asking him to quit it. That is `codex_app_lifecycle.py`. The design
was agreed in #1898 and #1902, with gates from #1901 and #1905.

- **The app.** The MSIX package `OpenAI.Codex_2p2nqsd0c76g0` (Electron). Its
  main process is the packaged `ChatGPT.exe` with no Chromium `--type=`
  argument; two such processes are refused as ambiguous. The VS Code
  extension's own app-server is never treated as the app. A failed process
  query refuses; it is never read as "not running".
- **`close`:**
  1. It needs codex-lead bound to the successor pair.
  2. It waits up to 10 minutes until no turn is `inProgress`. Unknown
     statuses or unreadable history refuse. The only exclusion is the exact
     retired pair (`01a14068`, `01a1607c`), from the historical inventory;
     no successor turn is ever excluded.
  3. It rechecks the image, pid and creation time immediately before acting.
  4. It opens one Restart Manager session, registering **only** that
     `RM_UNIQUE_PROCESS`, with no files or services.
  5. `RmGetList` must show exactly that process, as a windowed (non-service)
     app, with **no reboot reason**. Only then does it call
     `RmShutdown(flags=0)`. It never uses `RmForceShutdown` or `RmRestart`,
     has no kill fallback, and always ends the session.
  6. It succeeds only when the main process and the desktop app-server have
     exited and the successor reads CLOSED with no live turn, within 2
     minutes. Otherwise it reports, and the app is left as it is.
  - `status` runs the same path as a dry run, stopping before `RmShutdown`.
    On 2026-10-22 it listed exactly pid 48052 ("Codex", type MainWindow) with
    no reboot reasons.
- **`reopen`:**
  1. It launches only the **registered** cli and workspace, as
     `codex app <workspace>`, after checking the cli's sha256 (it takes no
     caller-chosen path).
  2. It needs all of these:
     - codex-lead stored disabled;
     - no reservation;
     - no proof run alive (by pid and creation time);
     - usage recorded for every launched attempt;
     - no proof `claimed` and unfinished;
     - the successor reading CLOSED with no live turn.

     Otherwise the app stays closed and the reason is reported.
- **The driver** posts `STATUS @admin … Paste exactly this, once: <probe 1>`
  only after the enable is confirmed. It is not an envelope, so it wakes no
  one.
- **Order:**
  1. Review, merge and deploy (scripts only).
  2. Wait until Codex's current turn is terminal.
  3. A **trial** of `close` then `reopen`, with codex-lead disabled. It must
     verify both, with receipts.
  4. Only after a verified trial: `prepare`, `close`, then `run`. The driver
     enables and tells David.
  5. Finish with `reopen`.

  How the app behaves under Restart Manager is an empirical question that only
  the trial settles.

## 0. Facts, read-only, about 17:30Z (refreshed by `prepare`)

- **Relay and binding.** Production is at `1afa9cc`, relay pid 34648, cursor
  1805. codex-lead is **unregistered, with nothing held** (34 cancelled), and
  reservations are 0.
- **Thread.** `01a14068-d723-76a0-a86d-c7d7b34c1b30`, with workspace
  `C:\Users\david\Documents\Codex`. With the app open, `ownership()` answers
  **OPEN**, and for a random UUID it answers UNKNOWN.
- **CLI.** `…\OpenAI\Codex\bin\896a0166b774037a\codex.exe`, version
  `codex-cli 0.163.0-alpha.10.2`, sha256
  `f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312`, which
  matches Codex's independent check. A second bin folder, `ce4759538b7f2f1a`,
  also exists.
- **Settings.** `config.toml` sha256 is
  `ef7e7918dda866c14f031a09524e044f61ee281ff4602dd8f1dcad953d351866`. It sets
  `sandbox_mode = "danger-full-access"` and `[windows] sandbox = "unelevated"`.
  These are David's own settings, and the relay does not widen them. The
  network gate is therefore tested under the configured settings, not the
  read-only default. The receipt records the effective permissions the woken
  run reports, rather than inferring parity from the hash.
- **Time limits.** The relay's own run kill is `RUN_TIMEOUT` = 45 min. The
  driver stops a proof run at 15 min (§3).

## 1. Codex's decisions (2026-10-21)

1. **Register `--cli` as the observed app-server path.** `CodexBackend.cli()`
   falls back to another install if that path disappears, so `--cli` is a
   preferred path, not a hard pin. The driver therefore requires all of these
   to be unchanged before it enables:
   - the file at that path, and its sha256;
   - the backend's resolved launch command.

   It also records the executable image of every launched pid. Any change
   makes the attempt **inconclusive**, not a proof for 0.163. No newer-mtime
   folder is chosen silently.
2. **No direct random-id CLI launch.** For §7 item 5, the receipt claims only
   that **the backend refuses an unknown id before launch** (UNKNOWN). The
   CLI's own unknown-id behaviour is not tested here.
3. **codex-lead finishes DISABLED**, pass or fail. A later, separate decision
   may enable a proven backend.

## 2. Preparation (Claude, after Codex approves this head; no David needed)

1. **Deploy the driver and register, disabled.** Move production to the
   merged commit, which adds `codex_closed_proof.py`; no runtime module
   changes. Then register:
   ```
   python lead_relay.py register --lead codex-lead --backend codex \
     --session 01a14068-d723-76a0-a86d-c7d7b34c1b30 \
     --workspace "C:\Users\david\Documents\Codex" \
     --cli "C:\Users\david\AppData\Local\OpenAI\Codex\bin\896a0166b774037a\codex.exe"
   ```
   `register` writes `enabled=0` and refuses while a reservation exists. With
   the app still open, ownership stays OPEN, so nothing can launch. The
   registration itself is reported in the hive.
2. **Prepare** with `python codex_closed_proof.py prepare --cli <path>
   --cli-sha256 <hash> --config-sha256 <hash>`. It refuses unless the
   preflight passes:
   - the binding is exactly this thread, workspace and cli, and is disabled;
   - the cli hash, the config hash and the resolved command all match;
   - no codex-lead delivery is non-terminal, and there is no reservation.

   It then writes `control/codex_closed_proof.json`, which records:
   - a fresh 8-hex **proof id**;
   - the baseline (the relay cursor);
   - an **enable-by** time 30 min out;
   - the two **literal probes**:
     - **probe 1, posted by David:** `@codex-lead BRIDGE-PROOF <id>: bounded
       relay test. Post the ACK line for this attempt, then exactly one status
       line giving your thread id and workspace, then stop. No engineering
       work, schedules or handoffs.`
     - **probe 2, posted only by the driver as claude-lead, while the probe-1
       run is observed alive:** `HANDOFF @codex-lead: BRIDGE-PROOF-2 <id>:
       second bounded relay test. Post the ACK line for this attempt only,
       then stop.`

   Claude gives David probe 1 verbatim, so he doesn't have to invent a
   payload.
3. **No hive traffic to codex-lead during the window.** Claude doesn't post to
   Codex, and David doesn't use `@Leads`. Any other codex-lead delivery ends
   the proof as unexpected activity, which is deliberate.

## 3. The run (`python codex_closed_proof.py run`, supervised by Claude)

**One live driver, one use.** `prepare` and `run` each hold the driver's own
OS lock (`codex_closed_proof.json.lock`) for their whole duration. This is not
the relay's lock, so the relay keeps running. A second driver, in this process
or another, is refused.

- **`run`** needs the state to be `prepared`, not past enable-by, and with no
  result yet. It marks the state `claimed` before doing anything, and
  `finished` when it ends.
- **An interrupted claim**, `claimed` with no live owner, blocks both `prepare`
  and `run` until it is reconciled by hand. It is never silently made eligible
  again.
- **Results never overwrite each other.** Each is written to
  `codex_closed_proof.<id>.result.json`, and an existing one is never replaced.

1. **Wait for the app to close.** Until enable-by, the driver repeats the
   preflight plus:
   - no desktop `codex.exe app-server` is running;
   - `ownership()` answers **CLOSED**, which means the lock is free and no turn
     is in progress.

   **David now quits the Codex app completely, including the tray icon.** If
   enable-by passes first, the verdict is `expired` and nothing is enabled.
2. **Enable.** The driver runs the supported `lead_relay.py enable`, then
   re-checks the preflight with `enabled=1`. If anything is off, it fails.
3. **David posts probe 1** from the chat page, copied exactly.
4. **Watch only the named sources.** Every codex-lead delivery after the
   baseline must be either:
   - probe 1, from admin, with the exact text, once; or
   - probe 2, from claude-lead, with the exact text, once.

   Each probe must also arrive after the enable. Anything else stops the proof
   (`failed`). The extra row is retained for
   reconciliation, not cancelled.

   This is a watched window, not a source allowlist in the relay: the relay
   itself would still act on other messages. The driver does not claim
   enforcement that the code doesn't provide.
5. **Per launch**, it records the pid, creation time and executable image.
   - A second launch for the same source → `failed`.
   - An image other than the registered cli → `inconclusive`.
   - A probe-2 launch while the probe-1 process is alive → `failed`. This is
     §7 item 6. Before a pass, the relay's own rows must also show probe 2's
     `launched_at` at or after probe 1's `ended_at`. That catches an overlap
     that falls between two samples. Missing timing is unproven, never a pass.
6. **Probe 2** is posted once, as soon as the probe-1 run is seen alive. If
   probe 1's delivery ends without the run ever being seen alive, the
   verdict is `inconclusive`: there is no executable identity, and item 6 is
   **not exercised**. Because probe 2 goes out the moment the run is seen, an
   observed run without probe 2 can't occur, so there is no separate
   `partial` verdict.
7. **Stop rules:**
   - a delivery ending `failed`, `uncertain` or `cancelled`;
   - no ACK within 10 min of the probe's delivery. For probe 2 the clock
     starts when the probe-1 run ends, because waiting behind it is the
     behaviour item 6 expects;
   - a proof run alive past **15 min**;
   - any new session file other than the thread's own rollout;
   - 30 min after enable without finishing → `expired`;
   - any exception.
8. **Done.**
   - **`passed`:** probe 1 is delivered, probe 2 is delivered, and no proof
     process is alive. **Each probe must have exactly one recorded headless
     launch.** An ACK with no launch, such as one from an open app, is never
     CLOSED-path evidence.
   - The final evidence in §4 must then hold as well, or the pass is
     withdrawn.

## 4. On every exit (`finally`)

Each stage runs even if an earlier one raised. An exception is recorded
against its own stage.

1. **Disable.** The driver runs `lead_relay.py disable --lead codex-lead`,
   then confirms the stored `enabled = 0`. A thrown command or a thrown
   verification read counts as **not confirmed**. If it can't confirm, the
   verdict becomes `failed`, even after a pass, and the result tells the
   operator to disable by hand. Disable success is recorded separately from
   process cleanup, and cleanup still runs.
2. **Execution cleanup.** Disabling only flips `sessions.enabled`. For each
   relay-recorded proof attempt whose `(pid, creation time)` is still the
   same process:
   - the driver waits up to that run's 15-min limit;
   - it then calls the relay's own `ProcessApi.kill_tree` on that pid only;
   - it confirms the exit by identity.

   A reused pid is never touched. There is no name-based kill and no ledger
   write. A process not confirmed stopped is a failure, and nothing is
   retried. If cleanup is uncertain, the desktop must not be reopened against
   a still-owned thread.
3. **Settle.** The driver waits up to 120 s for the relay to do two things:
   - record usage for every launched attempt;
   - release the reservation.

   If either is still outstanding, the verdict is `failed`.
4. **Final evidence**, checked however quickly the run finished:
   - **`failed`** if any of these is no longer as prepared:
     - the config hash;
     - the codex-lead binding (thread, workspace, cli);
     - no new session files.
   - **`inconclusive`** if either of these holds:
     - the cli file or its hash changed;
     - a launch has no recorded executable image.
5. **Save.** The result goes to `control/codex_closed_proof.<id>.result.json`,
   together with codex-lead's status lines. If saving fails, the whole result
   is printed to the terminal instead.

## 5. After the run

1. **Reopen the Codex app on the thread.** David checks two things, which
   cover §7 items 3 and 4:
   - the woken turns are visible;
   - one message sent there is answered normally, in the same workspace.
2. **Receipt on #113.** It reports the verdict and each §7 item with its
   evidence:
   - item 5 is the backend-level UNKNOWN, not a CLI test;
   - item 6 is marked `exercised` or `not exercised`.

   It also records the effective permissions and the network result. Then
   update `NEXT_STEPS.md` and the board.
3. **What happens next.** codex-lead stays disabled. No schedule or OPEN
   watcher is created. The comic #32/#35 reconciliation comes next.
