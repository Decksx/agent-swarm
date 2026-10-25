# Relay successor transition: rebinding a lead past an orphaned run (2026-10-25)

The relay contract is [`113-lead-relay.md`](113-lead-relay.md) (§5 the
reservation, §6 recovery, §12 operation). The Codex ownership rule is
[`113-codex-ownership.md`](113-codex-ownership.md) §2. This note adds one
supported operator command, `successor`, and one guard in `_maybe_release`.

- **Why.** codex-lead's headless attempt `e7c8dfdf2210c057` (message #2646,
  launched 2026-10-24 20:00 UTC-6) was killed by `RUN_TIMEOUT` (45 min) at
  20:46:14 UTC-6. Codex's own `thread_turns` row for that turn stays
  `inProgress`, so `CodexBackend.ownership` reads UNKNOWN and §5 never
  releases the reservation. That is correct: UNKNOWN is not idle. David
  approved moving codex-lead to a fresh thread (hive #2735). But `register`
  refuses while *any* reservation names the recipient, so the successor
  cannot even be registered disabled. The same orphaned-turn shape happened
  on 2026-10-21 ([closed-proof plan](113-codex-closed-proof-plan.md),
  "Successor migration").
- **Rule kept.** Nothing reinterprets the orphaned turn or edits Codex state.
  The old conversation is never declared idle. The command does not release
  the reservation through §5. It *retires* it as evidence, and only for a run
  the relay itself proved terminal and whose process tree is gone.
- **Out of scope.** No automatic retirement, no change to ownership
  probing, no `~/.codex` reads or writes, no enable. Enabling still follows
  the backend's bridge proof (§7).

## 1. The command

```
python lead_relay.py successor --lead codex-lead --session <new-uuid> \
    --workspace C:\git\agent-swarm --retire-attempt e7c8dfdf2210c057 \
    --reason "orphaned inProgress turn after RUN_TIMEOUT; David, hive #2735"
python lead_relay.py successor ... --confirm e7c8dfdf2210c057
```

- Without `--confirm` it is a dry run. It checks every precondition inside
  one transaction, prints the plan or the first `REFUSED:` reason, and rolls
  back. It needs no daemon stop.
- `--confirm <attempt id>` applies the change. The value must equal
  `--retire-attempt`, so the operator names the run being retired twice.
- Applying takes the daemon's own lock, as `cancel --confirm` does (#129), so
  it is refused (exit 3) while `run` is alive. A tick that has already read
  the reservation or the binding cannot interleave with the change.
- `--cli` is optional. Without it the current binding's `cli` is carried over
  (it names the installed CLI, not the thread), and the plan prints it.
- The backend is the current binding's. A successor on a different backend is
  a new registration, which needs no retirement.

## 2. Preconditions

Each failure prints `REFUSED:` with its specific reason and changes nothing.

1. **Inputs.** `--session` is a UUID, `--workspace` is absolute and
   `--reason` is not blank.
2. **The reservation is the blocker named.** A reservation row exists for
   `--retire-attempt`, its recipient is `--lead`, and its `session_key` is the
   lead's current binding. A run already retired is refused, naming when it
   was retired (re-running is a refusal, not a no-op).
3. **It is the only blocker.** No other reservation exists for the lead, and
   none exists on the successor's key.
4. **The attempt is this lead's headless run on that conversation.** Its
   recipient, backend and `session_id` match the reservation, and its path
   is `headless`.
5. **Proven terminal by the relay's own record.** The state is `exited` or
   `done`, `launched_at`, `ended_at`, `pid` and `proc_start` are all
   recorded, and one of these holds:
   - **killed by the run timeout:** `exit_code` is NULL, `ended_at -
     launched_at >= RUN_TIMEOUT`, and the delivery was not marked
     `uncertain` by recovery. `_ended(..., "timeout")` writes exactly this:
     `state = 'exited'`, `exit_code = NULL`, `ended_at` at the kill, with
     usage charged in the same step;
   - **reaped with an exit code:** `exit_code` is not NULL. Only
     `supervise` sets one, from the child's own `Popen` handle.

   A run recovery marked `exited` after a restart, with no exit code and
   less than `RUN_TIMEOUT` of runtime, has `ended_at` but no exit. It is
   refused, as is any `running` or `launching` row. That is the 2026-10-21
   shape: a turn that was quit is not proof of anything.
6. **Usage was recorded.** `usage_recorded = 1`. The command never charges
   usage itself. A retired reservation never reaches `_maybe_release` again,
   so a run retired uncharged would never be charged; refusing keeps
   "exactly once" with the code that already does it (the next tick).
7. **Its delivery is settled.** The attempt's delivery is not `notified`,
   `launching`, `running` or `exited`. An exited run still inside its ACK
   grace (§4) owes a verdict first.
8. **The process tree is gone.** `ProcessApi.is_same(pid, proc_start)` is
   false, and `ProcessApi.descendants(pid, proc_start)` finds no live member.
   - On Windows a child keeps its dead parent's pid. The tree is followed by
     parent pid, counting only processes created after their parent, so a
     reused pid's unrelated children are not mistaken for it.
   - On POSIX the run is its own process group (`separate_process_group`),
     so the tree is the group `pid`.

   A process table that can't be read is a refusal, not an empty tree.
9. **The successor is new.** Its key differs from the reserved key and from
   the current binding. It is not registered to another lead, and it is not
   the key of an earlier retired reservation.
10. **Explicit confirmation**, as in §1.

## 3. What changes, in one transaction

- The reservation row is **moved**, not marked. It is copied into
  `retired_reservations` (its `session_key`, `recipient`, `attempt_id` and
  `acquired_at`, plus `retired_at`, `reason`, the successor key and the
  previous binding as JSON), then deleted from `reservations`.
  - Moving keeps every existing reader of `reservations` unchanged: `register`,
    `_hold_reason`, `_maybe_release`, `_undo` and `status`.
  - A `retired_at` column would have needed a filter in each of those, and
    `session_key` stays the primary key there.
- The lead's `sessions` row is replaced with the successor, **disabled**,
  exactly as `register` writes it.
- Nothing else is written. No `attempts`, `deliveries`, `wakes` or `meta` row
  is inserted, changed or deleted. Codex state is not read or written.
- `status` gains `retired_reservations`, so the evidence stays visible.

## 4. After the rebind

- **The old attempt.** On the next tick `supervise` sees it `exited` with a
  settled delivery and no reservation. It marks it `done`, the normal end of
  every released attempt. It writes no usage, because the flag is already set.
  A late ACK for its token changes nothing, because its delivery is already
  terminal.
- **`_maybe_release` guard (new).** `_maybe_release` used to judge a
  reservation by `self.session(recipient)`. That is the *current* binding,
  which after any rebind is a different conversation, so a CLOSED successor
  would have released the old run's reservation. It now keeps a reservation
  whose key is not the current binding's. A retired reservation never gets
  there. The guard covers a binding changed by any other route (a legacy row
  or a manual edit).
- **Recovery.** `recover` and `_report_uncertain` act only on `launching` or
  `running` attempts. Precondition 5 excludes both, so the successor's
  transcript is never searched for the old token.
- **Held deliveries.** Rows `held(reserved)` for the lead are re-evaluated on
  the next tick against the successor. Nothing reserves the new key, so:
  - CLOSED while disabled gives `held(backend-disabled)`;
  - UNKNOWN gives `held(session-busy-or-unknown)`;
  - OPEN takes the live path (a DELIVER notice and an ACK), even while
    disabled, as today (§12).
- **After `enable`**, they launch headless into the successor one at a time
  (`queued`), oldest first. **Cancel stale history first.** While the lead is
  disabled, `cancel --ids ... --confirm` is the supported way (#125 §1). It is
  otherwise replayed, up to 45 minutes per run.

## 5. Tests and mutants

`tests/test_lead_relay_successor.py` covers each refusal, the success path,
retained evidence, untouched attempt and delivery rows, usage charged once,
the post-enable launch into the successor, re-run refusal, the quit-not-
timed-out case and the `_maybe_release` guard. Each precondition was
mutation-checked; the PR records the table.
