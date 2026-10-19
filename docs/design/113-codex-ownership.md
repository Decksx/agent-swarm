# #113 amendment: Codex lead ownership and wake (design draft, 2026-10-19)

This is a proposal for codex-lead to review. No code yet. It fills in the
`CodexBackend` that `docs/design/113-lead-relay.md` §7 leaves provisional:
today its `ownership()` is always UNKNOWN, so the relay never launches Codex.
claude-lead owns the implementation and codex-lead reviews (hive #1549).

## 1. What was observed (read-only, OfficePC, 2026-10-19 ~17:19 UTC)

None of this was written by us. No credential files were read.

- **CLI.** The desktop app (`OpenAI.Codex_26.1013.4894.0`, `ChatGPT.exe`)
  runs `…\AppData\Local\OpenAI\Codex\bin\<hash>\codex.exe app-server`.
  - The CLI reports `codex-cli 0.163.0-alpha.10.2`.
  - Two hash folders exist (`896a0166b774037a`, `ce4759538b7f2f1a`), so the
    path changes on app updates.
  - The VS Code extension runs its own `codex.exe app-server` on the same
    `~/.codex`.
  - `codex` is not on PATH.
- **Resume CLI.** `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]`:
  - `SESSION_ID` is a UUID or a thread name.
  - `PROMPT` may be `-`, meaning stdin.
  - `--json` exists.
  - The current `CodexBackend.command` form is valid.
- **The lead's thread.** In `.codex-global-state.json`,
  `thread-project-assignments` maps exactly one thread to the Agent Swarm
  project `466ce426-…`: **`01a14068-d723-76a0-a86d-c7d7b34c1b30`**.
  - Its rollout is `~/.codex/sessions/2026/10/15/rollout-…-01a14068-….jsonl`.
  - `state_5.sqlite` `threads.rollout_path` names the same file.
  - The thread id is the `session_id` that `codex exec resume` takes.
- **Writer lock.** `~/.codex/thread-writer-locks/<threadId>.lock` exists for
  this thread only.
  - A non-blocking shared lock probe failed with `ERROR_LOCK_VIOLATION`, so a
    process holds it exclusively. No turn was running at the time: the
    rollout ended in `task_complete`.
  - The binary contains `thread … already has an active writer` and
    `failed to acquire thread writer lock`.
  - Reading of this evidence: the app holds the lock while the thread is
    loaded, and a second writer is refused.
- **Turn state.** `thread_history_1.sqlite` `thread_turns.status` has the
  values `completed`, `failed`, `interrupted` and `inProgress`.
- **No Claude-style presence file exists.** Process command lines carry no
  thread id.

## 2. Proposed `CodexBackend.ownership(session)`

| Check, in order | Result |
|---|---|
| Any read or probe error, unexpected schema, or no rollout found for the id | UNKNOWN (hold) |
| A non-blocking probe of `thread-writer-locks/<id>.lock` fails with a lock violation | **OPEN**: a writer, normally the app, has the thread loaded |
| The probe succeeds (released immediately), or the lock file is absent, **and** `thread_turns` has an `inProgress` row for the id (read with sqlite `mode=ro`) | UNKNOWN: a stale `inProgress` row after a crash, or something odd. Hold |
| The probe succeeds or the file is absent, and there is no `inProgress` row | **CLOSED** |

- **Use a lock probe, not a file-existence check.** A crashed writer leaves the
  file behind, but the OS releases its lock. This matches the "stale is not
  proof of idle" rule. The other way around, a stale `inProgress` row without a
  held lock is never treated as idle.
- **The probe holds the lock briefly.** If Codex tries to load the thread in
  that instant, it could see `failed to acquire thread writer lock`. The probe
  releases straight away. It runs only in the pre-spawn checks, not every
  tick.
- **Backstop.** Between the probe and the spawn, Codex's own writer guard
  refuses a second writer. The relay must classify that refusal (exit code and
  output still to be measured) as `held(session-opened)` and retry. It must
  not count it as a failed attempt.

## 3. Launch details

- **CLI path.** Resolve it at spawn, never cache it:
  1. The registered `--cli`, if that file exists.
  2. Otherwise the `ExecutablePath` of a running desktop `codex.exe app-server`.
  3. Otherwise the newest `…\OpenAI\Codex\bin\*\codex.exe`.

  If none exists, the result is `pre-spawn-error`, which holds the message.
- **Prompt on stdin (`-`)**, not in argv. The quoted message and the token
  stay out of command lines.
- **Registration:**
  `lead_relay.py register --lead codex-lead --backend codex --session 01a14068-d723-76a0-a86d-c7d7b34c1b30 --workspace C:\git\agent-swarm`.
  This leaves it disabled until the bridge proof. The workspace is to be
  confirmed against the rollout's `session_meta.cwd`.
- **`transcript_mentions`.** Scan the thread's rollout for the token. Return
  `None` if the rollout is unreadable or compressed (`.jsonl.zst`).
- **Spend (design §9).** Codex usage recording must be pinned before
  `enable`. Proposal: record the duration of each run, as for Claude, in a
  `codex` guard file. Caps apply as they do today.

## 4. The open-app problem (the main question for review)

If the app holds the writer lock whenever the thread is loaded, then **Codex
is OPEN almost all the time the app runs**.
- An OPEN Codex lead gets only the live path: a `DELIVER … (live)` line, and
  the message is `notified`.
- Nothing enters the Codex conversation. That is the same gap claude-lead hit
  today (handoff §0, #1545), but for Codex it would be the normal case rather
  than the exception.
- So headless `exec resume` alone would wake Codex only when the app is closed.

Options, for codex-lead to choose or reject:

- **A. Accept it.** Headless wake works only while the app is closed. The open
  app gets a Codex-side watcher, like claude-lead's Monitor stopgap.
  - This needs Codex's equivalent of Monitor. Does the Codex app have
    something like `~/.codex/automations`?
- **B. Deliver into the open thread through the app-server.** The running
  `codex.exe app-server` presumably accepts new turns from the app UI. If it
  exposes a supported local interface, the relay could submit the turn there
  instead of spawning `exec resume`.
  - This is unverified and may not be a supported surface. It would need its
    own contract.
- **C. Do both.** Use B when OPEN and `exec resume` when CLOSED.

We recommend A now, with B investigated separately. A uses only documented
CLI behaviour plus a read-only probe.

## 5. Other open questions

- **Network from a woken turn.** Does a woken `codex exec` turn get network
  access under the configured sandbox policy? The ACK needs `lead_chat.py` to
  reach the hub at `192.168.42.50:8050`. If network is denied, even
  `BLOCKED @admin` cannot be posted. That has to be shown in the bridge proof,
  not assumed.
- **Lock behaviour.** Does the app release the lock when it quits, when the
  user switches threads, or when it is minimised? Does the VS Code app-server
  ever take this thread's lock?
- **Visibility.** Does an `exec resume` turn made while the app was closed
  appear in the app's thread view when it reopens? (§7 item 3)

## 6. Bridge proof for Codex (after review and implementation)

This is the Claude recipe from handoff §5, with the Codex specifics:
1. Precheck: codex-lead registered to the thread and disabled.
2. **Quit the Codex desktop app completely.** The probe must then show CLOSED.
   Record what the lock does when the app quits.
3. David enables codex-lead.
4. David posts an `@codex-lead BRIDGE-PROOF 01a14068 <nonce>` test message.
5. Expect the ACK and a status line. If neither comes within 10 minutes, or
   anything else goes wrong, disable codex-lead.
6. Reopen the app on the thread, check the woken turn is visible, then send
   it a message.

Also measure, once, with Codex's agreement: the `exec resume` exit code and
output against a held lock, which the backstop in §2 depends on.

All six design §7 items are needed before `enable` stays on.
