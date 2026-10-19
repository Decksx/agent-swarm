# Codex watcher proof: finite schedule and single processing attempt

Owner: codex-lead. Reviewer: claude-lead. Status: **proposal, not enabled**.
This amends the scheduling mechanism in the
[one-run proposal](113-codex-open-watcher-proof.md), merged through PR #121.
It does not enable a production watcher or the CLOSED relay backend.

## Why the one-run attempt stopped

The supported app tool rejected `COUNT=1` minute rules as having no future
runs. A future `DTSTART` was rejected for immediate creation. The attempts
created no matching automation and no proof message was requested. Receipt:
[#121 comment 6276243272](https://github.com/Decksx/agent-swarm/pull/121#issuecomment-6276243272).
This is a result for those expressions, not proof that all one-shot schedules
or same-thread delivery are unsupported. Do not use a different approval flow,
edit scheduler files or start another server to get around it.

## Changed bounds

After exact-head review, try a native same-thread heartbeat with a **finite
total of at most three scheduled turns**, using
`FREQ=MINUTELY;INTERVAL=2;COUNT=3`, without `DTSTART`. This expression is not yet
tested. If the tool rejects it, stop. If its returned/supported view cannot
confirm the original thread and finite COUNT, stop/disable the schedule before
requesting a probe. Do not retry with COUNT removed or increase it silently.

Record the automation id, confirmed rule, baseline, fresh public probe id and
a UTC expiry at most 15 minutes after creation. Keep default model/permissions.
The creation receipt is not delivery evidence. The app may count an initial
occurrence without executing it; fewer than three actual turns is acceptable.
Never claim exact timing or an actual run count from COUNT alone.

There is **one processing attempt**, not one attempt per scheduled turn. Before
any hub read or post, a scheduled turn must acquire a per-probe file claim
with an exclusive create. Any later turn sees the existing claim and stops
without reading the hive or posting. There are no automatic retries, including
when the first turn found no matching probe, crashed or lost a post response.

## Claim and prompt changes

Use the original prompt's thread-binding, expiry, exact source-message
selection, production helper, own-post `find`, explicit `--to "@claude-lead"`
and CONFIRMED-only ACK rules, with these changes:

1. State the limit explicitly: at most three scheduled turns, but exactly one
   may attempt to read/process the probe. Before scheduling, fill an absolute
   runtime state path under the original import workspace's
   `control/codex_watch_proof/<probe_id>/`. Do not put it in Git, Codex's data
   directory, the production checkout or the scheduler configuration.
2. After verifying actual thread and expiry, use Python `open(claim, 'x')`
   in that existing directory. On FileExistsError stop as **SKIPPED: already
   claimed**. On any other error stop as NOT PROVEN; never fall back to an
   overwrite or another filename. Write the probe id and actual turn id if
   available, flush and `os.fsync`, then close. Do not continue if that fails.
   An empty, malformed or stale existing claim is uncertainty, not permission
   to delete it and retry.
3. Only the successful claimant executes the original bounded read/select/
   find/post sequence, once. Fill the original prompt's command placeholders
   before scheduling; all use `C:\swarm-prod\agent-swarm\lead_chat.py`.
   A separate result JSON records no-match, uncertainty or the confirmed
   source/ACK ids. Write results atomically; missing results never clear the
   claim and never authorize a new attempt.
4. After reporting the result in this conversation, pause the identified
   automation using supported controls if available. If that control is
   unavailable, the remaining finite occurrences only encounter the existing
   claim and stop. Do not create a cleanup automation. Reconcile through the
   supported view and confirm no next run; do not infer this from a prompt's
   successful return.

The concrete helper is [codex_hive_proof.py](../../codex_hive_proof.py). Its
fake-hub tests cover concurrent exclusive-create contention, existing/partial
claims, ambiguous posts, result-write failure and expiry/no-match cases. The
helper creates no schedule, verifies no app-thread identity itself and makes
no claim that a manually run helper proves a scheduled wake. The scheduled
turn must check actual thread identity before invoking it. The claim prevents
repeated local attempts; it does not make hub posting transactionally exactly-once.

After exact-head review, copy the helper's **raw bytes from that reviewed Git
commit** to the runtime proof root, and record its SHA-256. Do not execute it
from a mutable development checkout or deploy the whole branch just for this
proof. Fill the scheduled prompt with the copied helper's absolute path and
hash, exact thread/probe/baseline/expiry and production helper revision. Before
each invocation, check the copied bytes still match the hash; otherwise stop.
The command is `C:\Python311\python.exe <copied-helper> --root <runtime-root>
--probe <id> --baseline <B> --expires <UTC-Z>`, with paths quoted for PowerShell.
All placeholders must be filled before creation. Existing production
`lead_chat.py` supplies read/find/post; do not change its checkout during the
proof. A helper return is still not independent evidence of the scheduled
turn's identity or terminal state.

## Unchanged proof and stop rules

After confirmed schedule creation, Codex posts readiness with the id, baseline
and expiry. Claude supplies exactly one fresh
`PROBE @codex-lead: <probe_id>`. The initiating turn ends. No manual user
message, queue or CLI resume may cause the claimed scheduled turn. If one
intervenes, report inconclusive rather than claiming an autonomous wake.

Observe the actual scheduled turn in the original thread, its terminal state
and at most one targeted, confirmed PROBE-ACK. Record all ids and timestamps,
including extra scheduled turns that skipped. A saved schedule, a file claim
or a manual rehearsal is not delivery proof. Unknown thread, tools/network
failure, no terminal-state evidence or no usable bounded rule means NOT PROVEN.
Keep the proof files for reconciliation; do not remove the claim during the
window or re-arm the same probe after app restart.

This uses up to three model turns even if no message arrives. It does not
assert relay-rate-guard integration or account quota availability. Busy-turn
and restart behavior, durable engineering cursor/actions, cadence/budget,
pause and production enablement still require separate review and proof.
No automation is created by this amendment. Queue remains disabled; Claude's
CLOSED implementation proceeds separately.
