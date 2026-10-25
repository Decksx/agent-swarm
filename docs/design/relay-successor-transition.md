# Relay successor transition: rebinding a lead past an orphaned run (2026-10-25)

The relay contract is [`113-lead-relay.md`](113-lead-relay.md) (§5 the
reservation, §6 recovery, §12 operation). The Codex ownership rule is
[`113-codex-ownership.md`](113-codex-ownership.md) §2. This note adds one
supported operator command, `successor`, and one guard in `_maybe_release`.

- **Why.** codex-lead's headless attempt `e7c8dfdf2210c057` (message #2646,
  launched 2026-10-24 20:00 UTC-6) ended at 20:46:14 UTC-6, 45.2 min in, with
  no exit code. The relay's own hive line #2711 says `RELAY TIMEOUT #2646 →
  codex-lead: run killed after 45 min`. Only the timeout path posts that line,
  but the database row does not record it (§2.5). Codex's own `thread_turns`
  row for that turn stays
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

- `--historical-evidence` accepts a run that predates termination provenance
  on exactly what its row proves (§2.5). A run that ended after this change
  never needs it.
- `--inspected-pids 1,2,...` names the live processes, created during an
  uncontained run's window, that the operator inspected and found unrelated
  (§2.8). It never overrides a process the parent chain ties to the run.

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
   - **Reaped with an exit code:** `exit_code` is not NULL. Only
     `supervise` sets one, from the child's own `Popen` handle.
   - **Killed by the run timeout:** `ended_by = 'timeout'` (provenance, §3),
     `exit_code` is NULL, `ended_at - launched_at >= RUN_TIMEOUT`, and the
     delivery is not `uncertain`. Only the timeout path writes `timeout`. It
     writes it right after its tree kill, in the same `UPDATE` that marks the
     run `exited`. A NULL exit code and a long runtime are *not* enough. After
     a restart the `Popen` handle is gone. A child that then quits on its own
     past `RUN_TIMEOUT` is recorded with exactly those, plus `ended_by =
     'exit'`. b7ade88 called that a kill; it is now refused.
   - **Historical evidence, only with `--historical-evidence`:** all of
     these hold:
     - `ended_by` is NULL;
     - the run ended before `meta.provenance_since`, so it predates
       provenance rather than lacking it;
     - `exit_code` is NULL;
     - it ran at least `RUN_TIMEOUT`;
     - the delivery is not `uncertain`.

     The plan says what that proves and no more: "ended, no exit code, ran
     >= RUN_TIMEOUT, no termination provenance recorded; not proven a timeout
     kill". It relies on the uncontained process checks of §2.8.

     The relay's database holds no other record of the kill. The timeout
     path's only other trace is its hive post, `RELAY TIMEOUT #<message>`.
     For e7c8dfdf that is #2711, mirrored in `control/narration.jsonl`. The
     post is made after the row is written, outside its transaction. So the
     refusal names it for the operator to check, and the command does not
     read it. The run's own log (`control/lead_relay_logs/<attempt>.log`) is
     the child's output; the relay never writes to it.

   Anything else is refused:
   - a run recovery marked `exited` after a restart (`ended_by = 'recovery'`);
   - a run reaped with no code (`ended_by = 'exit'`);
   - any `running` or `launching` row;
   - a NULL `ended_by` on a run that ended after `provenance_since`.

   That is the 2026-10-21 shape: a turn that was quit is not proof of
   anything.
6. **Usage was recorded.** `usage_recorded = 1`. The command never charges
   usage itself. A retired reservation never reaches `_maybe_release` again,
   so a run retired uncharged would never be charged; refusing keeps
   "exactly once" with the code that already does it (the next tick).
7. **Its delivery is settled.** The attempt's delivery is not `notified`,
   `launching`, `running` or `exited`. An exited run still inside its ACK
   grace (§4) owes a verdict first.
8. **Nothing of the run is alive.** The command reads one
   `ProcessApi.snapshot()` of the whole host. On Windows that is one
   `NtQuerySystemInformation` call. It gives every process's pid, parent,
   image name and creation time without opening the process. (`OpenProcess`
   fails for 205 of 484 processes on the lead host.) The checks run in this
   order:
   - **The root.** A live entry with the run's pid and `proc_start` is a
     refusal. So is a live entry with its pid whose creation time can't be
     read, because it can't be told apart from the run.
   - **The parent chain.** It is followed from the root, counting only
     processes created after their parent, so a reused pid's unrelated
     children are not mistaken for it. Any member is a refusal. So is any
     candidate whose creation time can't be read (b7ade88 silently skipped
     it).
   - **The container**, `attempts.container`, recorded with the pid at
     launch (`popen_contained`). The chain alone is not proof. Take root ->
     wrapper -> worker with the wrapper gone: the worker's parent pid points
     nowhere, and b7ade88 called the tree gone while the worker lived.
     - *Windows, `job:Global\lead-relay-<attempt>`.* The run is created
       suspended, assigned to a new job, then resumed, so everything it ever
       starts is in the job. The job is `KILL_ON_JOB_CLOSE`. Only the child
       inherits its one inheritable handle; the relay closes its own at
       once.
       - While some member holds the handle, the job exists and lists
         exactly its live members. Any member is a refusal.
       - When the last holder exits, the kernel ends every other member and
         destroys the job. So "no such job" proves nothing is alive.
       - Any other query failure (access denied, a truncated list) is a
         refusal.
       - The name is in `Global\`, so a query from another logon session
         can't wrongly read "not found".
     - *POSIX, `session:<pid>`.* This is the run's own session
       (`separate_process_group`). Any live process in that session or
       process group is a refusal. A process that calls `setsid` itself
       leaves it; POSIX has no stronger container without cgroups.
   - **No container.** This covers every run from before this change, and
     any run whose job could not be made (that is logged, and the run goes
     uncontained). The command refuses when *any* live process on the host
     was created during `[launched_at - 10 s, ended_at + 10 s]`. It lists
     each one's pid, image name and creation time. A broken chain hides a
     surviving child, so this is the only check that can't miss it. An
     unreadable creation time is a refusal.

     `--inspected-pids` exists because the window is host-wide. Without it,
     a browser tab or terminal opened during a 45-minute run would block the
     route for as long as it lives. The operator must name every listed pid.
     The set can only shrink: a process that appears later can't have been
     created in a past window. Parent-chain members are never overridable.

   A process table that can't be read is a refusal, not an empty one.
9. **The successor is new.** Its key differs from the reserved key and from
   the current binding. It is not registered to another lead, and it is not
   the key of an earlier retired reservation. `register` also refuses a
   retired conversation, for either lead and in any letter case. So no
   supported route binds it again.
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

### Schema: termination provenance and containment

`lead_relay.migrate` calls `migrate_provenance` (in `lead_relay_backends.py`).
It follows the existing pattern: read `PRAGMA table_info(attempts)`, then
`ALTER TABLE ... ADD COLUMN` only what is missing. It is idempotent and runs on
every start.

- `attempts.ended_by TEXT` is how the relay saw the run end. `_ended` writes
  its `how` (`timeout`, `exit` or `spawn-io`) in the same `UPDATE` that sets
  `state = 'exited'`. Recovery writes `recovery` if nothing was recorded.
- `attempts.container TEXT` is `job:<name>` or `session:<pid>`. It is written
  with the pid, before the stdin write.
- `meta.provenance_since` is when this database first ran the migration. It
  is `INSERT OR IGNORE`, so it is set once. Existing rows keep NULL in both
  columns. A NULL `ended_by` on a run that ended before it means "predates
  provenance". On a later run it can't be relabelled as anything.

The new columns are not in `SCHEMA`, which keeps `lead_relay.py` inside the
50,000-character view budget. Every opener of the relay database (`Relay`,
the CLI and `transition`) runs `migrate`.

### A behaviour change at launch

The job is kill-on-close, so a process a woken run starts does not outlive
the run's last job-handle holder (normally the root). Before, a leftover
child of `claude -p` or `codex exec` survived the run. A woken lead that
needs a lasting process must start it outside the run (a scheduled task or a
service), not as its child.

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
timed-out case and the `_maybe_release` guard.

Its `Host` fake models the process table: parents, creation times,
unreadable entries and jobs. It sits behind both the real `ProcessApi` hooks
that b7ade88 used and `snapshot`. These witnesses for codex-lead's four
findings fail at b7ade88 and pass here:

- A restart, then a child quitting past `RUN_TIMEOUT`, is refused (`ended_by
  exit`). The historical route, its flag and its limits are covered too.
- Root -> exited wrapper -> worker is refused, and the worker is listed.
- An unreadable child refuses, and so does an unreadable root identity. An
  exited child does not.
- `register` of a retired conversation is refused, for the same lead and for
  the other one.

On Windows, three host tests use real processes:

- the snapshot's creation times match `GetProcessTimes`;
- a contained run's job lists a worker the parent chain can't reach. The job
  survives the launcher closing its handle, and ends the worker when the
  root exits;
- an uncontained survivor is listed by the window check.

The tests pin the relay's policy constants, so inherited `LEAD_RELAY_*`
overrides do not decide them. Each new guard was mutation-checked; the PR
records the table.
