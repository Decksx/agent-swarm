# Finite operational Codex OPEN watcher pilot (#113)

Status: implementation candidate for Claude's exact-head review. No runtime
database, new automation, relay registration or production deployment is created
by this change. Codex owns implementation; Claude reviews the helper, this prompt
and the filled activation receipt before scheduling. The earlier idle, busy and
desktop-restart proofs remain paused; their retained claims are unrelated.

The purpose is a real unattended handoff to this interactive Codex lead, without
David prompting it to check the hive. Background workers are separate agents.
This pilot uses the supported native follow-up in this existing chat, preserving
its configured model and permissions. It creates no other writer, CLI daemon,
app-server or CLOSED fallback. Local work requires the machine/app available;
the bounded restart proof does not establish processing while the app is quit.

## Input and durable processing

`codex_hive_watch.py` is a script-first inbox, not an engineering executor. It
reads the hive through the existing non-admin `codex-lead` helper. Its bytes at
`C:\swarm-prod\agent-swarm\lead_chat.py` must match SHA-256
`2f06a40af74ad7bd4a1ef23b11f235cbce44773334d2a43f5e84902fd21ba035`;
the adapter executes those verified bytes without a second file read. Secrets
are used by the existing helper and never included in a packet or diagnostic.

Pilot work envelopes must come from authenticated `claude-lead`, begin with
`HANDOFF @codex-lead:`, `REVIEW @codex-lead:` or `QUESTION @codex-lead:`, and name
exactly one allowed PR plus exactly one full 40-character head SHA. Use an
explicit GitHub PR URL, `swarm #N` or `comic #N`. Allowed repositories are
`Decksx/agent-swarm` and `Decksx/cbz-automation-suite`. Bare `#N`, short SHAs,
multiple heads, ambiguous projects and a moved GitHub head produce attention,
not inferred work. In the pilot a `QUESTION` is a head-bound PR discussion;
general questions need direct lead attention. Admin messages addressed to Codex
are surfaced as attention without being executed by this narrow parser. Other
prose, worker messages and our own echoes do not create tasks.

A fresh SQLite database outside Git and `~/.codex` stores configuration, cursor,
admitted poll turns, classifications, work and relay ACK intents. Classification,
source message id, head-bound work and cursor advancement commit together. The
work key includes repository, PR, full head and envelope kind; repeated messages
for that same item alias the original source claim. A new head is a new item.
At most one work item is active; a run returns at most one packet. GitHub's head
is checked on classification and again before activation. Exact-head review and
CI remain necessary; neither a packet nor a chat post is their evidence.

`CODEX_THREAD_ID` comes from the actual execution environment. A read-only query
of this thread's `thread_turns` metadata in `thread_history_1.sqlite` must find
exactly one current `inProgress` turn. No bodies, credentials, rollout files or
Codex state edits are used. This local schema is version-sensitive: a missing
database, changed schema, ambiguous current turn or wrong thread stops the run.
It is not a public app API or independent evidence of a scheduled invocation.

A committed polling marker prevents a competing process from reading the hub.
A crash leaves that marker or the active work claim intact and blocks takeover.
An interrupted claim must be reconciled through a separately reviewed recovery
procedure against its GitHub/hive evidence. Do not delete/reset the database,
claims, reservations or cursor to force progress. A report is recorded with
`finish` only in the owning actual turn, using the actual exact-PR GitHub comment
URL. The helper validates that URL's shape, not the remote comment's contents;
the assistant must verify the post and reviewed head. Local completion is not a
controller-ledger verdict. Local completion bookkeeping remains possible after
pause/expiry, without loading the hub adapter.

Future `relay` live notices with `RELAY DELIVER #N → @codex-lead attempt=TOKEN
(live)` map to the already classified source. They never create another task.
One durable ACK intent is stored per source/token. An existing own exact ACK is
found before posting; otherwise the posting state commits before the one POST.
Only a confirmed receipt completes it. A lost response/uncertain receipt remains
visible and is never retried automatically. Unknown sources require attention.
This support does not register Codex in the relay or prove that CLOSED works.

## Bounds and stop controls

The first pilot is every five minutes, at most twelve native scheduled turns,
with an absolute expiry no more than one hour after initialization. The native
schedule must itself be finite; the helper's durable budget is a second bound.
The last admitted poll returns `stop_after_turn=true` so cleanup can occur in
that turn, even if it is otherwise idle. Runs refused before admission (expired,
duplicate turn, unfinished claim or uncertain ACK) are not additional ledger
rows: count actual scheduled invocations from the app's run evidence as well.
The helper cannot by itself count model turns that never invoked it.

Both `C:\swarm-prod\agent-swarm\control\PAUSED` and the hub `/control/status`
switch stop work, along with a pilot-local `PAUSED` file. A malformed/unavailable
hub pause response fails closed. Pause and expiry are checked before reading,
before posting an ACK and before handing work to the assistant. Recheck before
engineering side effects as directed in the native prompt. The helper cannot
cancel work the assistant has already started.

Use supported app controls to pause/delete only this pilot automation on expiry,
budget exhaustion, pause, uncertainty or any failed identity/hash gate. Preserve
other automations and all runtime evidence. If cleanup controls are unavailable,
report that failure visibly; the finite occurrence count and retained claims
remain the bounds. Do not create a cleanup automation, silently re-arm, change
permissions, migrate the app, or convert this into unlimited recurrence.

## Activation preparation (after independent approval)

1. Record the reviewed Git head, copied helper raw-byte SHA-256, actual thread,
   fresh baseline, UTC creation/expiry and supported automation receipt. Use a
   fresh runtime folder under the original workspace's `control`, outside Git
   and Codex state; never reuse a previous proof folder. Copy only approved bytes.
2. In the actual target chat, initialize once using `C:\Python311\python.exe
   -X utf8 <COPIED_HELPER> --root <PILOT_ROOT> init --thread <ACTUAL_THREAD>
   --baseline <BASELINE> --expires <UTC_Z_EXPIRY> --control
   C:\swarm-prod\agent-swarm\control`. This verifies current turn identity but
   performs no hub access and creates no schedule. Retain any partial failure.
3. Have Claude confirm the filled prompt/constants and nominate a real future
   PR handoff within the hour. #126 has already merged/deployed; use the next
   genuine handoff, not a stale cap-fix replay or another synthetic probe.
   Agree to the full-SHA/project envelope above. David needs no app-close ritual.
4. Use the supported same-chat automation tool with the prompt below, every
   five minutes for twelve occurrences, no more than one hour. Record its actual
   persisted creation anchor and ID; do not infer nominal slot behavior from a
   late/coalesced run. Do not edit scheduler files. If that finite definition is
   rejected, stop visibly rather than substituting an unlimited schedule.

## Native prompt template (all placeholders must be filled and reviewed)

> This is the reviewed finite Agent Swarm OPEN-chat operational pilot, source
> commit `<APPROVED_HEAD>`. Actual target thread `<THREAD>`, runtime root
> `<ROOT>`, copied helper `<HELPER>`, raw-byte SHA-256 `<HASH>`, baseline
> `<BASELINE>`, absolute UTC expiry `<EXPIRY>`. At most twelve native turns at
> five-minute cadence; this pilot never grants extra permissions or schedules.
>
> Verify this is a native scheduled heartbeat in this exact chat. Verify actual
> environment CODEX_THREAD_ID, current UTC before expiry, and helper raw-byte
> hash before invoking it. If any fact is missing/wrong, do not invoke it; report
> visibly and pause only this automation using its scheduled-context ID.
>
> Run once, as the first task action: `C:\Python311\python.exe -X utf8 <HELPER>
> --root <ROOT> poll`. The helper independently verifies the actual current
> turn through read-only own-thread metadata. Never pass a fabricated turn ID.
> No repeated poll, daemon, model launch or alternate delivery path is permitted.
>
> For `idle` or `already-polled`, do no engineering and post nothing in the
> hive. End with the required quiet DONT_NOTIFY heartbeat block. If
> `stop_after_turn=true`, first pause this automation and record the receipt.
>
> For `paused`, `expired`, `budget-exhausted`, `paused-or-expired`, `attention`,
> malformed output or a command failure, do no engineering. Preserve evidence,
> pause only this automation through supported controls, report the actual
> reason/source IDs once, and end with NOTIFY for a material failure or action
> needed. A routine pause may remain quiet. Do not reset a claim or retry an
> ambiguous POST. Never treat an unknown ACK as authorization for another task.
>
> For `work`, handle only that one claimed source/PR/head within existing project
> authorization. Fetch the PR and prior comments directly from GitHub; a hive
> claim, author's text or prior local report is not independent review evidence.
> Recheck the hub and shared/pilot PAUSED switches, UTC expiry and exact GitHub
> head before engineering side effects using `<HELPER> --root <ROOT> guard
> --claim <PACKET_CLAIM>`; proceed only on `ready`. This point-in-time check
> does not replace atomic GitHub merge pins. Do not claim another work item or create
> schedules. If remaining time cannot support a correct bounded response, post
> one accurate blocked handoff on that PR and record it; do not claim completion.
> Any merge/deploy retains independent exact-head review, CI and project controls.
>
> Post the actual review/handoff on the exact PR, verify its confirmed URL, and
> mirror one meaningful result in the hive via the pinned helper, using find
> before any uncertain resend. Record with `<HELPER> --root <ROOT> finish
> --claim <PACKET_CLAIM> --report <ACTUAL_PR_COMMENT_URL>` (add `--blocked` for
> a blocked result), in this owning actual turn. A crash/uncertain result stops
> for reconciliation; never erase state or take over a prior turn's active claim.
> Delivery receipts never count as controller review verdicts.
>
> If the packet had `stop_after_turn=true` or expiry is reached, pause only this
> pilot using supported app controls after recording the result. Preserve all
> other automation fields. If controls/ID are unavailable, report cleanup not
> confirmed; do not create another schedule. Final output must be exactly one
> nonempty heartbeat response with this automation ID, NOTIFY for meaningful
> completion/failure/user action, otherwise DONT_NOTIFY. No idle hive chatter.

## Measurement and pass/fail

For each pilot-window handoff record source ID/time, requested and actual head,
helper claim time, actual thread/turn, confirmed PR/hive result and app terminal
metadata. Pass requires every eligible handoff picked up within one cadence plus
run duration, no duplicate engineering action, no idle hive spam, and confirmed
supported pause/delete at the end. Record misses by source ID and reasons;
unsupported envelopes count as visible attention, not successful delivery.
The test is inconclusive if there is no genuine future handoff. A manual check
does not prove unattended pickup. The helper does not attest native scheduling.

`metrics` reads only recorded own-thread turn IDs and terminal status,
started/completed times and `duration_ms`, plus helper duration/result. Compare
idle and actionable whole-turn durations separately from helper/network time.
The reviewed metadata schema exposes **no token counts**. Metrics therefore
report token usage as unavailable; duration is not tokens or cost. No credential,
message-body or arbitrary-history scraping is a substitute. The implementation
review must accept this finite visibility limit or require a supported usage
source before activation. This pilot alone cannot establish an affordable
unlimited cadence. Any ongoing cadence/budget is a separate explicit decision.

The dashboard requested in hive #1737 and the separate CLOSED queue cleanup/
registration/proof are other workstreams. Do not fold them into this pilot or
claim that this makes either lead continuously available.
