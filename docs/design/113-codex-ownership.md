# #113 amendment: Codex lead ownership and wake (design draft, 2026-10-19)

This is a proposal for codex-lead to review. No code yet. It fills in the
`CodexBackend` that `docs/design/113-lead-relay.md` §7 leaves provisional:
today its `ownership()` is always UNKNOWN, so the relay never launches Codex.
claude-lead owns the implementation and codex-lead reviews (hive #1549).

**Revision 2** follows codex-lead's review of `c1abcd6` (#120, comment
6273649296) and the three bot findings. All of their factual claims were
re-checked against `lead_relay.py` at `ce5565b` and the installed CLI.

**Direction (codex-lead's decision): staged C.**
1. Prove the supported `codex queue` path into the **open** desktop thread.
2. Keep headless `exec resume` for the **closed** case.
3. Fall back to a watcher (A) only if the queue path cannot reach the actual
   desktop-owned thread. Then the watcher must be specified and demonstrated:
   a poller whose output never enters the conversation does not count.

## 1. What was observed (read-only, OfficePC, 2026-10-19)

None of this was written by us. No credential files were read.

- **CLI.** The desktop app (`OpenAI.Codex_26.1013.4894.0`, `ChatGPT.exe`)
  runs `…\AppData\Local\OpenAI\Codex\bin\<hash>\codex.exe app-server`.
  - The CLI reports `codex-cli 0.163.0-alpha.10.2`.
  - Two hash folders exist, so the path changes on updates.
  - The VS Code extension runs its own `codex.exe app-server` on the same
    `~/.codex`.
  - `codex` is not on PATH.
  - The thread's `session_meta` records an older CLI (`0.162.0-alpha.17.2`,
    source `vscode`). That is history, not the installed version.
- **Resume.** `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]`. `PROMPT`
  may be `-`, meaning stdin, and `--json` exists.
- **Queue.** `codex queue [OPTIONS] --thread <THREAD> --message <TEXT>`
  ("Queue a message for an existing session").
  - It has `--remote <ADDR>` (ws, wss or unix) and
    `--remote-auth-token-env`.
  - It is documented at https://learn.chatgpt.com/docs/cli/reference#codex-queue.
  - Only `--help` has been run.
- **The lead's thread** is `01a14068-d723-76a0-a86d-c7d7b34c1b30`. It is the
  only thread that `thread-project-assignments` maps to project `466ce426-…`.
- **The thread's workspace** is
  `C:\Users\david\Documents\Codex\2026-10-15\i-m-trying-to-merge-a`, according
  to `session_meta.cwd` and the `state_5.sqlite` row. It is **not**
  `C:\git\agent-swarm`. The thread's own instructions direct engineering work
  into the development checkout.
- **Writer lock.** `~/.codex/thread-writer-locks/<threadId>.lock` is held
  exclusively while the thread is loaded, including when no turn is running.
  The binary contains `thread … already has an active writer`.
- **Turn state.** `thread_history_1.sqlite` `thread_turns.status` takes
  `inProgress`, `completed`, `failed` and `interrupted`.
- **No Claude-style presence file.**

## 2. Ownership (`CodexBackend.ownership`)

This is a fail-closed reading of Codex's internal storage. It is not a stable
public API.

| Check, in order | Result |
|---|---|
| Codex data directory, target UUID, rollout or expected schema not found or not as expected; any read or probe error | UNKNOWN (hold) |
| A non-blocking probe of `thread-writer-locks/<id>.lock` fails with a lock violation | **OPEN** |
| The probe succeeds (released before returning) or the lock file is absent, and `thread_turns` has an `inProgress` row for the id (sqlite `mode=ro`) | UNKNOWN (hold) |
| The probe succeeds or the file is absent, and there is no `inProgress` row | **CLOSED** |

- **No probe lock is held across a return.** `ownership()` acquires the lock,
  releases it, and only then returns. It is called from three places in
  `lead_relay.py`:
  - `_hold_reason`, line 557, which runs every tick (20 s) for each eligible
    pending or held delivery;
  - the pre-spawn re-check, line 678;
  - reservation release, line 475.

  So the probe's hold lasts microseconds, and it happens at most about three
  times per tick per Codex delivery. Before Codex is enabled, add rate-limiting
  to `_hold_reason`: re-probe at most once per 60 s per delivery, caching the
  last result for UNKNOWN or OPEN only. A cached CLOSED result is never used to
  spawn.
- **Never manufacture CLOSED.** Never delete lock files, and never clear
  `inProgress` rows.

## 3. The OPEN path: `codex queue`, proof first

This path is not built until the proof in §6.1 passes.

- **What the relay sends.** A minimal pointer, not content:
  `--message "Hive relay: message #<N> for codex-lead. Read it with lead_chat.py read --as codex-lead --since <N-1>, then ACK it."`
  - The quoted hive text and the attempt token are **never** in argv.
  - The woken turn reads the message from the hub, and gets its token from a
    relay-owned file in the Codex data area that only the user can read (or
    from the hub DELIVER line, which already carries the attempt id).
- **What counts as success.** Only the lead's own `ACK #N <token>` in the hub.
  The queue CLI exiting 0 is **not** an ACK and not completed work.
- **Attachment must be real.** If `codex queue` cannot reach the running
  desktop app-server for this thread, the attempt fails. Never start a
  replacement daemon or a second writer to make it look as if it succeeded.
- **State machine.** This is a new `queued` attempt state, separate from a
  headless `running` attempt:
  - It is `queued` when the CLI exits 0.
  - It becomes `delivered(ack)` when the ACK arrives, or `failed(no-ack)`
    after the deadline.
  - It is never re-queued automatically: after a timeout or restart, the turn
    may still run.
  - The reservation is held until ACK, deadline, or recovery finds the deadline
    passed.
  - Wake counters are charged when the attempt is queued.
  - **Usage** is recorded from the ACK time (or deadline) minus the queue time,
    as an upper bound. The queue CLI's exit is not the turn's exit.

## 4. The CLOSED path: headless `exec resume`

- **CLI path.** Resolved at spawn, never cached:
  1. The registered `--cli`, if that file exists.
  2. Otherwise the `ExecutablePath` of a running desktop `codex.exe app-server`.
  3. Otherwise the newest `…\OpenAI\Codex\bin\*\codex.exe`.

  If none exists, the result is `pre-spawn-error` (hold).
- **Prompt transport: a new spawn contract, for both backends.** Today
  `Relay._spawn(command, session, attempt_id)` uses `stdin=subprocess.DEVNULL`.
  It becomes `_spawn(command, session, attempt_id, stdin_bytes)`:
  - `Popen(..., stdin=PIPE)`, then write the UTF-8 prompt in full, then
    `close()`. All of this happens before the attempt is marked `running`.
  - `CodexBackend.command` passes `-` as `PROMPT`. Claude moves to stdin too:
    `claude -p` reads the prompt from stdin when none is given. This must be
    verified on 2.1.303.
  - **Failures once a process exists** (`BrokenPipeError`, a partial write, a
    write timeout of 10 s, or the child dying during the write): kill the
    child, then mark the attempt **`failed(spawn-io)`**. It is **not** undone
    as "never launched", because execution may have begun. It is reported and
    not retried.
  - **Failures before `Popen`** keep today's undo and hold.
  - **Regression tests:**
    - The child receives the exact prompt and token on stdin.
    - Neither appears in `argv` (checked through the spawn fake and a real
      child that echoes its argv).
    - Broken-pipe, timeout and crash cases end in `failed(spawn-io)`.
- **Probe-to-spawn race.** If the app loads the thread between the probe and
  the spawn, Codex's writer guard should refuse. In v1 there is no exception:
  the attempt is `running`, an exit without an ACK is `failed(no-ack)`, and it
  is reported and never replayed.
  - An error substring, a nonzero exit or a missing token does not prove that
    no work was done.
  - A retryable `refused-writer` outcome would need three things. First, an
    unambiguous **pre-execution** refusal signature, measured once on a
    **disposable test thread**, never the lead's conversation. Second, rollout
    evidence that no turn started. Third, specified transitions: the attempt
    goes to a terminal `refused`, the reservation is released, the wake and
    chain counters and usage are not charged, the delivery returns to
    `held(session-opened)`, and the same holds after crash recovery.

    It is out of scope for v1.
- **Registration** binds the actual thread and workspace:
  `register --lead codex-lead --backend codex --session 01a14068-d723-76a0-a86d-c7d7b34c1b30 --workspace "C:\Users\david\Documents\Codex\2026-10-15\i-m-trying-to-merge-a"`.
  This leaves it disabled. Moving the thread to another workspace is a separate
  explicit migration, and must not quietly satisfy the "workspace unchanged"
  item.
- **`transcript_mentions`.** Scan the rollout for the token. Return `None` if
  it is unreadable or `.zst`.

## 5. Usage, by backend (design §9)

Today `Relay.usage` is one pair. `_headless_blocker` checks it only for
`claude` (line 569), and `_record_usage` records every attempt through it
(line 457).

- **`usage: dict[backend, (check, record)]`.**
  - `_headless_blocker` checks `usage[session.backend]`.
  - Exit, recovery and the queue completion of §3 record against the
    **attempt's** backend.
- **Persist the binding.** Migrate `attempts` to add `backend` (it has
  `session_id` already), set at attempt creation. Recording and reservation
  release use the attempt's stored backend and session, never the current
  registration. So a re-registration can't charge or release the wrong
  conversation.
- **Keep the existing Claude guard** and its behaviour of retrying when
  recording fails (`usage_recorded` stays 0 until recorded).
- **No guard means a hold.** A backend with no guard configured is
  `held(rate-unconfigured)`.
- **Codex gets a local duration guard.** It is a local budget only and does
  not show that the Codex account has quota.
- **Tests:** there is no cross-charging in either direction, including
  recovery of exited and queued attempts after a registration change.

## 6. Proofs (after review and implementation)

### 6.1 The queue path (the OPEN path), first

This uses the real lead thread while idle, done with codex-lead's agreement.
1. While the app is open and idle: `codex queue --thread 01a14068… --message <pointer>`.
   Check that the turn starts in the **desktop** conversation, with exactly
   one ACK.
2. While a turn is running: queue a second pointer. It must run after the
   current turn, with one ACK and no interleaving.
3. After a deadline timeout, and after a relay restart, there is no duplicate
   turn.
4. Record what happens if the app is closed. Does `queue` fail, start a
   server, or write offline? Starting a server or a second writer is a failure
   of this path.

If item 1 fails, the fallback is A, with a watcher that is specified and
demonstrated. A Codex automation is a candidate, but not assumed to be
equivalent to Claude's Monitor.

### 6.2 Headless `exec resume` (the CLOSED path)

All six items of design §7 apply, including an unknown id failing and a queued
second handoff. The procedure:
1. Precheck: codex-lead is registered to the thread and its workspace, and is
   disabled.
2. Quit the app completely. The probe must show CLOSED, and you record what the
   lock did.
3. David enables codex-lead.
4. David posts `@codex-lead BRIDGE-PROOF 01a14068 <nonce>`.
5. Expect the ACK and a status line. If neither comes within 10 minutes, or
   anything goes wrong, disable codex-lead.
6. Reopen the app on the thread, check the woken turn is visible, then send it
   a message.

**The gate: network, tools and settings.** A woken `codex exec` runs under
Codex's non-interactive sandbox, which is read-only by default
(https://learn.chatgpt.com/docs/non-interactive-mode). The proof must show the
ACK reaching the hub **without** bypass flags or wider permissions. If it can't,
the run must leave an offline local receipt (the attempt log) and stay held or
fail visibly. Successful CLI parsing does not show tool parity.

No manual test is needed from David until the implementation and its
exact-head review are ready.
