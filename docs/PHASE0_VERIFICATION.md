# Phase 0 — verification evidence record

Produced 2026-09-09 by Claude Code, at the operator's request, relaying a
review from ChatGPT that asked for evidence rather than assertion. Everything
below was re-measured for this document on a clean tree; nothing is carried
over from the earlier session's claims without being run again.

Environment: Python 3.11.3, Windows-10-10.0.26200-SP0, `core.autocrlf=false`,
no `.gitattributes`, 0 of 34 tracked files non-LF.

Phase 0 verification is where this stops. No Phase 1 work was done, and
nothing was deployed.

---

## 0. Two premises in the review that the tree does not support

Both are stated first because the rest of the document is read differently
depending on them.

### The briefing was not truncated. The copy that reached ChatGPT was.

`docs/HANDOFF_SESSION_AGENTS.md` in this repository is **155 lines, 6901
bytes**, ends at section 8 with a complete sentence, and has been that since it
was committed at `8ba7539`. The copy under review stopped mid-sentence at "So
Gemini still decomposes work and says what should happen next. Three things",
which is line 100.

Measured:

```text
copy under review   99 newlines, 4432 bytes, CRLF, no trailing newline
repository file    155 newlines, 6901 bytes, LF,  trailing newline present
diff of repository lines 1-100 against the copy, ignoring CR:
  identical except the copy's missing final newline
```

The same thing happened to the other handoff: the copy of
`docs/HANDOFF_SESSION_CLAUDE.md` was also exactly 99 lines against a
142-line file, cut at "so it exercises no diff gate,". Two documents, both
severed at line 100, both byte-identical prefixes of the tracked file. The
transport between this repository and the reviewer truncates; the documents do
not. `SWARM_PROTOCOL_v7.md` moved through a different path and arrived whole at
1170 lines, so the truncation is not universal and cannot be assumed away.

There is nothing to finish. The remedy is to re-read the tracked files. The
sections the reviewer never saw are section 5 (Constraints that bite),
section 6 (Traps I hit), section 7 (Do not do these), and section 8 (Where to
read more).

### Phase 1 was started. It is not deployed, wired, or merged.

The review asks for "confirmation that Phase 1 was not started". That
confirmation cannot be given. `controller/` exists on `phase1/controller-core`
as 5 modules across 16 commits: `schema.py`, `db.py`, `states.py`, `engine.py`,
`activations.py`, with 69 tests of their own.

What is true, and is the thing the review is protecting:

- nothing in `controller/` is deployed to Tower;
- nothing imports it — the three workers do not reference it at all;
- neither branch is merged to `master`;
- the worker conversion (protocol section 19, Phase 1 item 4), which is the
  step that can strand the operator, has **not** been done.

`docs/PHASE0_CONTAINMENT.md` still says "Phase 1 has not been started". That
sentence was true when written and is now stale. See section 9.

---

## 1. Baseline and candidate

| | |
| --- | --- |
| Baseline (pre-containment) | `dfba2940dec2c00206cad5658b1aa395e69baebb` — `master` |
| Phase 0 candidate | `8bfdb638e56024cd064d6a874ee3947d4dcad494` — `phase0/containment` |
| Deployed to Tower | Phase 0 only |
| Phase 1 branch | `f0b984c3a57e5b4ce3db739d76dbc0be7d432c0c` — `phase1/controller-core`, undeployed |
| Merged to `master` | nothing |

`phase0/containment` is an ancestor of `phase1/controller-core`, so the Phase 0
files are identical on both. Verification below was run in a detached worktree
at the Phase 0 tip, so the numbers are Phase 0's own and not the later branch's.

**The deployed hub is byte-identical to the repository copy.** The deployment
record names SHA-256
`de7d7db2da8a81546f2a1e22cca9172a81c589231c1c7f045408e12432db3a38` for the file
put on Tower; `git show phase0/containment:hub/hub.py | sha256sum` returns the
same digest today. That is a check of the record against the tree, not a
restatement of it.

## 2. Commits and files changed

38 commits, 21 files, +4259 / -964 across `master..phase0/containment`.

```text
chatgpt_worker.py                      | 524 ++++++-------------
claude_worker.py                       | 409 ++++++++--------
gemini_worker.py                       | 584 +++++++++--------------
swarm_control.py                       | 518 +++++++++++++++++++ (new)
hub/hub.py                             | 507 +++++++++++++++++++ (new)
hub/main.py                            | 220 +++++++++ (new, the pre-auth hub as found)
hub/test_hub.py                        | 336 +++++++++++ (new)
hub/gemini_lead.py                     |  74 +++ (new, the retired lead, kept as evidence)
hub/PROVENANCE.md                      | 127 +++ (new)
hub/docker-compose.yml                 |  14 + (new)
docs/PHASE0_CONTAINMENT.md             | 231 +++ (new)
docs/DEPLOY_PHASE0_HUB.md              | 238 +++ (new)
tests/bypass_matrix.py                 | 283 +++ (new)
tests/conftest.py                      | 138 +++ (new)
tests/test_chat_cannot_activate.py     | 249 +++ (new)
tests/test_identity_and_credentials.py | 308 +++ (new)
tests/test_model_call_path.py          | 159 +++ (new)
tests/test_pause_and_control.py        | 211 +++ (new)
start_workers.bat                      |  19 +-
pytest.ini                             |   2 + (new)
workspace/throttle_check.py            |  72 --- (deleted)
```

`workspace/guard_check.py` is unchanged since the baseline commit and is not
part of the Phase 0 diff.

## 3. Test commands, exit codes, results

Run at `8bfdb63` in a detached worktree, 2026-09-09.

```text
$ python -m pytest tests/ -q
83 passed in 0.88s
exit 0

$ python tests/bypass_matrix.py
guards proven load-bearing: 10/10
exit 0

$ python workspace/guard_check.py
FAILURES: none
exit 0

$ <venv>/python -m pytest hub/test_hub.py -q
37 passed, 2 warnings in 1.21s
exit 0
```

The hub suite needs FastAPI, which the system interpreter does not carry.
Versions used: fastapi 0.141.1, httpx 0.28.1, pytest 9.1.1.

By file, all exit 0:

```text
tests/test_chat_cannot_activate.py        15 passed
tests/test_pause_and_control.py           21 passed
tests/test_identity_and_credentials.py    35 passed
tests/test_model_call_path.py             12 passed
                                          -----------
                                          83
```

For reference, at the Phase 1 tip `f0b984c` the same commands give 152 passed
(83 Phase 0 + 69 controller), 27/27 guards, `guard_check` exit 0.

## 4. Bypass evidence — the guards are load-bearing

`tests/bypass_matrix.py` removes each guard in turn and asserts which tests
fail. A guard whose removal breaks nothing is unreachable defensive code, not
a boundary. Verbatim at `8bfdb63`:

```text
baseline: suite green (exit 0)

pause_ignored                    LOAD-BEARING      caught=6  expected=6
claim_does_not_consume           LOAD-BEARING      caught=3  expected=3
claim_ignores_agent              LOAD-BEARING      caught=2  expected=2
credentials_unvalidated          LOAD-BEARING      caught=2  expected=2
redaction_disabled               LOAD-BEARING      caught=2  expected=2
identity_accepts_empty           LOAD-BEARING      caught=1  expected=1
chat_activation_reintroduced     LOAD-BEARING      caught=2  expected=2
replies_addressed_to_a_peer      LOAD-BEARING      caught=2  expected=1
                                   also failed: ['test_admin_activation_result_is_posted_to_admin']
system_prompt_dropped            LOAD-BEARING      caught=1  expected=1
startup_invariant_removed        LOAD-BEARING      caught=1  expected=1

guards proven load-bearing: 10/10
```

`replies_addressed_to_a_peer` catches one more test than expected. The matrix
reports the surplus by name rather than swallowing it — a bypass catching more
than predicted is still a caught bypass, but a silent superset would hide the
day it starts catching something unrelated.

## 5. Chat generates zero model calls — two independent methods

### Method 1: dynamic, through the real poll loop

`tests/test_chat_cannot_activate.py` drives each worker's actual `main()`
against a fake hub for a bounded number of polls, with the model boundary
replaced by a recorder — `run_task` for the Claude worker (the function that
invokes `claude -p` with Bash authority) and `generate_reply` for the two API
workers. If the recorder is ever called, containment has failed regardless of
what the intermediate logic did. The hostile batch carries every pre-Phase-0
trigger at once: a direct `target`, `@ClaudeCode` inside content,
`@chatgpt` / `@gemini` mentions, a peer task-result envelope, an unprefixed
lowercase target, and a message whose `sender` claims to be `Admin`.

```text
test_agent_chat_and_mentions_never_invoke_a_model[claude]     PASSED
test_agent_chat_and_mentions_never_invoke_a_model[chatgpt]    PASSED
test_agent_chat_and_mentions_never_invoke_a_model[gemini]     PASSED
test_repeated_chat_delivery_creates_no_model_calls[claude]    PASSED
test_repeated_chat_delivery_creates_no_model_calls[chatgpt]   PASSED
test_repeated_chat_delivery_creates_no_model_calls[gemini]    PASSED
test_no_hub_message_is_ever_addressed_to_a_peer_worker[x3]    PASSED
test_chat_is_still_recorded_and_readable[x3]                  PASSED
test_narration_survives_a_reread                              PASSED
test_duplicate_polls_cannot_claim_one_activation_twice        PASSED
test_a_worker_cannot_claim_another_workers_activation         PASSED
```

### Method 2: static, from the call graph

A dynamic test proves the loop did not reach the model on the inputs given. It
does not prove no route exists. This check builds a call graph from each
worker's AST and asks who can reach the model boundary at all, so a bug in the
test harness and a bug in the code would have to coincide to hide a failure:

```text
=== claude_worker.py ===
    model boundary        : ['run_task']
    called from           : ['execute_activation']
    fetch_messages() reaches boundary? False
    message_content() reaches boundary? False
    main() calls boundary directly? False
    call order in main()  : ['fetch_messages', 'pause_reason',
                             'claim_activation', 'execute_activation']

=== chatgpt_worker.py ===  boundary ['generate_reply'], called from ['execute_activation']
    fetch_messages() reaches boundary? False
    call order in main()  : ['pause_reason', 'fetch_messages', 'pause_reason',
                             'claim_activation', 'execute_activation']

=== gemini_worker.py ===   boundary ['generate_reply'], called from ['execute_activation']
    fetch_messages() reaches boundary? False
    call order in main()  : ['fetch_messages', 'pause_reason', 'pause_reason',
                             'claim_activation', 'execute_activation']
```

In all three the model boundary has exactly one caller, `execute_activation`,
and the only thing that reaches it is `main()` after `pause_reason()` returned
None and `claim_activation()` returned a record from the local control
directory. No chat-side function reaches it by any path.

Both methods agree: **zero model calls originate from chat.**

## 6. Global pause — demonstrated live; drain is not implemented

Run against a scratch control directory, mirroring `main()`'s ordering exactly.
Verbatim output:

```text
bound identity: 'claudecode'

[1] issue                  rc=0 activation_id=6de36ab7dc734f5b9a5fac419eaad0cf
    pending=1 paused=False
[2] pause                  rc=0 paused=True reason='PAUSED present: demonstration for ChatGPT'
[3] worker poll, paused    -> ('DEFERRED', 'PAUSED present: demonstration for ChatGPT')
    pending after that poll = 1   <- deferred, not consumed
[4] resume (sentinel)      rc=0 paused=False
[5] SWARM_PAUSED=1 set, sentinel clear -> ('DEFERRED', 'SWARM_PAUSED=1 in the worker environment')
[6] worker poll, resumed   -> ('CLAIMED', '6de36ab7dc734f5b9a5fac419eaad0cf')
    pending=0 consumed=1
[7] same worker polls again -> ('NOTHING TO CLAIM', None)   <- consumed exactly once
[8] issue to claudecode, claim as 'gemini' -> None
    pending=1   <- left for its owner, not drained

chat_is_authoritative = False
```

Four properties, each visible above rather than argued:

1. Pause is checked **before** the claim, so queued work is deferred rather
   than consumed (step 3, pending still 1).
2. The file sentinel and `SWARM_PAUSED` are independent stops; clearing one
   does not clear the other (steps 4 and 5).
3. An activation is consumed exactly once — the rename into `consumed/` is the
   idempotency boundary, atomic on NTFS and POSIX (steps 6 and 7).
4. One worker cannot drain another's queue (step 8).

There is a second, control-plane pause on the hub — `POST /control/pause`,
`POST /control/resume`, `GET /control/status`, admin-only, state persisted so
it survives a restart. Its tests are in `hub/test_hub.py` (37 passed). The two
pauses are not yet wired to each other; the host-side pause does not read the
hub's status. That is recorded as intended future work in
`docs/PHASE0_CONTAINMENT.md` section 5 and remains open.

**Cooperative drain (protocol section 6) is not implemented in Phase 0.** The
`drain_requested` column and its check exist only in `controller/schema.py` and
`controller/activations.py` on the undeployed Phase 1 branch. What Phase 0 has
instead is the pause above, which is a drain in the weak sense that matters
today: a task already running continues to completion (bounded by
`TASK_TIMEOUT`, default 900s), and no new work starts. There is no
`DRAIN_REQUESTED` acknowledgement, no `WRITES_STOPPED`, and no worktree
fencing, because there are no worktrees yet. Anyone reading "pause/drain
verified" should read it as "pause verified, drain not built".

## 7. Secret-exposure findings

Four scans. Pattern set: `sk-proj-`, `sk-` (16+ chars), `AIza` (16+), `ghp_`,
`xox[baprs]-`, PEM private-key headers, and literal `Authorization: Basic`
values.

**Tracked files, all three branch heads.** Matches occur in exactly one file,
`tests/test_identity_and_credentials.py`.

**Entire history, all 54 reachable commits.** 387 matches, every one of them in
that same file. The complete set of distinct credential-shaped literals ever
committed to this repository is six, and all six are self-evidently synthetic
fixtures whose whole purpose is to be asserted absent from output:

```text
AIzaSyAbCdEf0123456789xyz
AIzaSyExampleNotARealKey
sk-AbCdEf0123456789xyz
sk-proj-AbCdEf0123456789xyz
sk-proj-MustNotBeLogged0123456789
sk-proj-ThisMustNeverAppearInAnyMessage
```

**Runtime logs and state on disk.** 171,908 bytes of pre-containment worker
logs from 2026-09-03 plus the three `.state` files: **zero matches**, including
zero for `HUB_SECRET=`, `api_key=`, `password`, and `Basic <base64>`. All are
gitignored (`*.log`, `*.state`) with the reason recorded in `.gitignore`
itself.

**Browser JavaScript.** The live terminal served by `GET /` contains no
credential, no `btoa`, no `Authorization` header construction and no token
literal. Its three `fetch()` calls are relative — `/messages`, `/send`,
`/control/status` — and rely on the browser's own HTTP Basic prompt and cache.
The page itself sits behind `Depends(authenticate)`, so an unauthenticated
browser never receives the HTML at all.

Supporting guarantees, each with a test: `hub.py` reads `HUB_CREDENTIALS` from
the environment only and never from a literal; every credential-parsing failure
path raises with a message that does not contain the value; workers read
`HUB_SECRET` from the environment with no file fallback; nothing containing a
credential is logged at startup (`test_no_credential_is_logged_at_startup`);
the `token` field the pre-containment workers attached to every outbound
message is gone (`test_outbound_envelope_carries_no_token_field`).

### Two limits of that finding, stated rather than left implied

1. **Redaction is shape-based and does not cover the hub secret.**
   `_SECRET_RE` in `swarm_control.py` matches `sk-proj-`, `sk-` and `AIza`
   prefixes. The hub credentials are `openssl rand -hex 24` output, which has
   no distinguishing prefix, so `redact()` would not catch one if it ever
   reached a log line or a message body. Nothing in the repository constructs
   such a string, and the tests assert the outbound envelope carries no token —
   but the backstop does not extend to it, and should not be described as if it
   does.
2. **Absence of a secret in this repository is not absence of exposure.** These
   scans cover the repository, its history, and the local logs. They say
   nothing about the hub's own message database on Tower, which accumulated 378
   messages under an unauthenticated hub that any LAN caller could read.

## 8. The open Phase 0 item: credential rotation

[RESOLVED 2026-09-09, both halves. The operator rotated the OpenAI and
Gemini keys the same day; the rotation is recorded in
`docs/PHASE0_CLOSEOUT.md` section 1. The exposure history was then scanned
on Tower with `hub/scan_hub_db.py`: 0 matches across all 1134 text-bearing
cells of the 378-row message table, section 3 of the same document. The
finding below is kept as written, because what it establishes is that no
record existed before that rotation, and that remains true of the day it
describes.]

Protocol section 19 lists four Phase 0 requirements. Three are done and
evidenced above: authenticate every endpoint and bind identity server-side;
make workers ignore chat for activation; add a visible global pause and verify
it. The first is not.

> 1. Rotate exposed credentials and inspect their exposure history.

**No record of this exists anywhere in the repository.** Neither
`docs/PHASE0_CONTAINMENT.md`, `docs/DEPLOY_PHASE0_HUB.md`, nor
`hub/PROVENANCE.md` mentions rotation, revocation, or an exposure review of
`OPENAI_API_KEY` or `GEMINI_API_KEY`. Searched for: rotat, exposed, leak,
revoke, previous key, old key.

The hub credentials are new — generated on Tower on 2026-09-09 with
`openssl rand -hex 24`, mode 600, never echoed to a terminal — so for the hub
there was nothing to rotate. The provider API keys are a different matter, and
they are the ones that cost money. They lived in the environment of workers
that, before containment, ran models with shell authority and posted output
into an unauthenticated hub readable by anyone on the LAN.

I cannot close this. I hold no credential and should not; rotation and the
provider-side exposure review are operator actions on the provider consoles.
**Phase 0 should not be signed off as complete while requirement 1 has no
record**, and the correct resolution is either the operator rotating and
recording it, or an explicit, recorded decision not to, with the reason.

## 9. Documentation drift found while verifying

`docs/PHASE0_CONTAINMENT.md` was written before the hub half of Phase 0 landed
and now contradicts the deployed state in two places:

- line 8: "Phase 1 has not been started." It has — see section 0.
- section 5, "What Phase 0 did NOT close", opens "**The hub is still
  unauthenticated**" and lists a five-point minimal patch specification for
  Tower. All five points were subsequently implemented in `hub/hub.py` and
  deployed on 2026-09-09, which `docs/DEPLOY_PHASE0_HUB.md` records with
  measurements.

Both sentences were true when written. Neither has been marked resolved, so a
reader arriving at the primary containment record today is told the control
plane is open when it is not. That document is an evidence record, so the fix
is an inline `[RESOLVED 2026-09-09]` marker plus a resolution log at the top —
not a rewrite of the original finding. **Not done here**, because this
session's scope ends at verification; it is left as a named, deliberate
omission rather than silently carried.

The docstring of `swarm_control.py` has the same drift in miniature: it
describes the server-side half of Phase 0 as "the half of Phase 0 that lives on
Tower and is not in this repository". `hub/hub.py` has been in this repository
since `e87176b`.

## 10. Two defects found while verifying

Neither affects containment. Both are recorded rather than fixed, for the same
scope reason.

1. **`gemini_worker.py` logs three startup lines twice** (lines 491-496:
   identity, activations, chat). A copy-paste artifact; the other two workers
   log them once.
2. **`start_workers.bat` does not warn about a missing `HUB_SECRET`.** It warns
   about `GEMINI_API_KEY` and `OPENAI_API_KEY`, but all three workers now exit
   1 without `HUB_SECRET`, and the launcher does not mention it. The operator's
   first symptom would be three windows that open and close.

## 11. The `/messages` polling question

The review asks whether the workers should keep polling chat at all, and is
right that they have no functional need for it. Measured rather than argued:

- `POLL_SECONDS` defaults to **3** in all three workers, and
  `start_workers.bat` does not override it. Three workers at 3s is
  **86,400 `GET /messages` per day**, all authenticated, all costing nothing
  but request volume.
- What the poll produces: messages are appended to a local JSONL narration log,
  each row stamped `"authoritative": false` and passed through `redact()`, and
  a per-worker high-water mark is advanced.
- What consumes it: `read_narration()` has exactly **one** production caller,
  `control_status()`, and it uses it only to report `narration_rows` as a
  count. Nothing reads narration content, and no control decision anywhere
  depends on it.

So the poll is already UI-and-record-only, and section 5 above proves it can
never invoke a model. The reviewer's requested end state is the current design;
what remains open is only the cadence, and **the cadence is already operator
policy, not code**: `POLL_SECONDS` is read from the environment, so setting
`POLL_SECONDS=60` (1,440 requests/day/worker, a 20x reduction) or `300` in
`start_workers.bat` needs no code change and no review of a safety boundary.

Recommended, and not done here: set it in the launcher rather than lowering the
default, so the value is visible at the place the operator starts the swarm.
Removing the poll entirely would end the narration log, which is the only
durable local record that the hub conversation happened — worth keeping until
the controller's event ledger (protocol section 4) replaces it.

## 12. Reproducing all of this

```powershell
git worktree add <scratch>\phase0 phase0/containment
cd <scratch>\phase0
python -m pytest tests/ -q            # 83 passed, exit 0
python tests/bypass_matrix.py         # 10/10 load-bearing, exit 0
python workspace/guard_check.py       # FAILURES: none, exit 0

python -m venv <scratch>\hubvenv
<scratch>\hubvenv\Scripts\python -m pip install fastapi httpx pytest
<scratch>\hubvenv\Scripts\python -m pytest hub/test_hub.py -q   # 37 passed

git show phase0/containment:hub/hub.py | sha256sum   # must equal de7d7db2...
```

If any of these disagrees with this document, the tree is right and this
document is stale. Say so rather than working around it.
