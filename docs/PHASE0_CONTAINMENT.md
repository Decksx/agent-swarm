# Phase 0 — Immediate containment

> **Resolution log - 2026-09-09.** This document is an evidence record of what
> was measured on 2026-09-08. Its original findings are left standing; where a
> finding has since been overtaken, the sentence is kept and an inline
> `[RESOLVED 2026-09-09]` marker is added next to it. Four have been overtaken:
>
> 1. The control-plane half of Phase 0 landed and was deployed. `hub/hub.py`
>    authenticates all five routes, derives `sender` from the credential, and
>    removes `/docs` `/redoc` `/openapi.json`. Deployment and its verification
>    are recorded in `docs/DEPLOY_PHASE0_HUB.md`.
> 2. All five points of the minimal patch specification in section 5 were
>    implemented in that same change.
> 3. Phase 1 was subsequently started on `phase1/controller-core`. It is
>    undeployed, unmerged, and imported by nothing.
> 4. The suite in section 6 has grown from 76 tests to 83.
>
> Protocol section 19 Phase 0 item 1 - rotate exposed credentials and inspect
> their exposure history - was *not* addressed by any of the above and had no
> record anywhere when this was written. The operator closed it on 2026-09-09;
> that is recorded in `docs/PHASE0_CLOSEOUT.md`, and the re-measured evidence
> behind every other Phase 0 claim is in `docs/PHASE0_VERIFICATION.md`.

Status: **host half complete, control-plane half not started.**
[RESOLVED 2026-09-09: the control-plane half landed in `hub/hub.py` and
was deployed to Tower the same day.]
Branch: `phase0/containment`. Baseline: `dfba2940dec2c00206cad5658b1aa395e69baebb`.

This records what Phase 0 of `SWARM_PROTOCOL_v7.md` actually closed on this
host, what it deliberately did not, and what an operator has to do differently.
Phase 1 has not been started. [RESOLVED 2026-09-09: Phase 1 was started
on `phase1/controller-core` after this was written; it is undeployed and
unmerged.]

---

## 1. What the measurements found

Everything below was measured against the running system on 2026-09-08, not
inferred from the protocol.

| Fact | How it was established |
| --- | --- |
| `GET /messages` answers `200` with the full backlog to a caller holding no credential | requested from a shell with no `HUB_TOKEN` set |
| `GET /control/status` does not exist | `404` |
| The complete route inventory is five paths | the hub's own `/openapi.json` |
| `POST /send` accepts an optional `token`; `GET /messages` never returns one | `SendRequest` and `Message` schemas |
| The hub is a uvicorn app serving a "Swarm Live Terminal" UI | `server: uvicorn` response header; `GET /` |
| A message carries exactly `id`, `sender`, `target`, `content`, `timestamp` | decoded a live `/messages` response |
| `sender` is free text supplied by the client | `POST /send` body schema; nothing derives it from a credential |
| The hub source is not on this machine | searched `C:\git`, Documents and Desktop; only the three worker clients and their logs reference port 8050 |
| No credential is committed or logged here | scanned all `*.py`, `*.bat`, `*.log`, `*.state` for `sk-`, `sk-proj-` and `AIza` shapes: zero matches |
| The repository had no version control at all | `git rev-parse` failed; no `.git` in the directory or any parent |

The hub serves its own OpenAPI schema at `/openapi.json`, unauthenticated, so
the reachable surface is enumerable exactly rather than by guessing at paths:

```text
GET  /              Swarm Live Terminal UI
GET  /messages      ?since_id=<int>  -> [Message]
POST /send          SendRequest
GET  /openapi.json  GET /docs   GET /redoc
```

**That is the complete route inventory** — five reachable paths, no security
scheme declared, all unauthenticated. `/docs`, `/redoc` and `/openapi.json` are
reachable endpoints in their own right and leak the API surface to anyone on the
LAN; they need the same credential as the rest.

The schema also settles a question that was previously recorded here as
unmeasured. `SendRequest` **does** accept an optional, nullable `token`, but the
`Message` model returned by `GET /messages` carries only `id`, `sender`,
`target`, `content`, `timestamp`. A token can therefore be sent and is never
handed back, which is exactly why the pre-Phase-0 inbound `token_ok()` check
could refuse traffic but could never admit it — setting `HUB_TOKEN` would have
stopped every worker dead.

What remains unmeasured is narrower: whether the hub *validates* that token on
write. Answering it requires a POST to the live hub, which was not done. Nothing
here depends on the answer, because inbound tokens are not consulted either way.

## 2. What the workers did before

The chat stream was an unauthenticated remote-execution channel.

- `claude_worker` ran `claude -p` with `Bash,Read,Edit` pre-authorized whenever
  a message's `target` named it. Anything able to POST to the hub could run
  commands as the user, unattended.
- `chatgpt_worker` and `gemini_worker` called their model APIs whenever `target`
  named them **or** the substring `@chatgpt` / `@gemini` appeared anywhere in a
  message's content, so any hub client could spend either account's budget.
- Both API workers pasted the last twenty hub messages into every prompt, so
  untrusted stream content was fed to a model on every turn.
- `claude_worker` posted every task result to `@Gemini`, which target-triggered
  Gemini, whose reply re-triggered Claude. **The loop was wired in, not
  emergent.**
- The brakes — per-sender cooldowns, a burst cap, a verification gate — were
  advisory, in-memory, and cleared by a restart. None was a boundary.
- `token_ok()` compared an inbound `token` field. `GET /messages` never returns
  one, so that check could refuse traffic but never admit it: setting
  `HUB_TOKEN` would have stopped the worker dead.

## 3. What Phase 0 changed here

**Chat cannot start work.** Not by `target`, not by `@mention`, not from any
sender, not with any content. Messages are still fetched and recorded to
`control/narration.jsonl`, so the conversation stays readable and storable; it
simply carries no authority. Every stored row is stamped
`"authoritative": false`.

**Work is claimed from a local control directory.** `control/activations/`
holds operator-issued records; `swarm_control.claim_activation()` renames one
into `control/consumed/` before returning it. The trust boundary is this host's
filesystem permissions, not a shared secret travelling over an open network — a
secret sent through the hub is readable by every hub client, whereas a directory
on OFFICEPC is not reachable from the hub at all.

**The rename is the idempotency boundary.** It is atomic on NTFS and POSIX, so
duplicate polls — or two processes — cannot both win one activation. That is
what makes repeated polling free rather than repeatedly chargeable.

**A deterministic global pause.** `control/PAUSED` (durable, survives a restart)
or `SWARM_PAUSED` in the environment (process-local). Either alone holds the
host. It is checked *before* the claim, so engaging it defers queued work rather
than consuming what it declined to run. An unreadable flag fails closed: a
spurious pause costs a delay, a missed one costs an unattended run holding Bash
authority.

**Identity is bound locally.** Each worker speaks only as its configured
`AGENT_IDENTITY` and never adopts a name from an inbound message.
`outbound_envelope()` builds every payload, so a worker cannot be talked into
speaking as someone else, and the `token` field is no longer attached to
outbound messages.

**Results go to `@Admin`, never to a peer.** This one line removes the return
leg of the loop.

**Credentials come only from the environment.** No file fallback, no default.
Validated at startup, so a blank or placeholder value is refused here rather
than surfacing as a provider `401` later, and refusals never carry the value.
`.gitignore` blocks `.env*`, `*.log`, `*.state` and `secrets.json` so a
credential or a task log cannot reach a commit. Task output is passed through
`redact()` before it is logged or posted, because a task holding Bash can print
the environment.

**A readable control status.** `swarm_control.control_status()`, written to
`control/status.json` each poll and printable with `python swarm_control.py
status`.

## 4. Operator workflow

```powershell
python swarm_control.py status                                  # read state
python swarm_control.py issue claudecode "run the preflight"    # queue work
python swarm_control.py pause "investigating an incident"       # stop the swarm
python swarm_control.py resume
```

`issue` takes the agent handle (`claudecode`, `chatgpt`, `gemini`) and the task
text. A worker claims only records addressed to its own identity, so one worker
cannot starve another by draining the queue.

### What this costs

**Admin can no longer drive a worker by typing in the chat UI.** That capability
returns when the hub authenticates callers and derives `sender` server-side. It
is not recoverable before then, because "obey only Admin" is not enforceable
while anybody may claim to be Admin. Chat remains fully readable, and workers
still narrate results to `@Admin`.

## 5. What Phase 0 did NOT close

**The hub is still unauthenticated.** [RESOLVED 2026-09-09: it is not, as
of the deployment recorded in `docs/DEPLOY_PHASE0_HUB.md`. Everything in
the rest of this section describes the hub as it was on 2026-09-08 and is
kept for that reason.] Requirements 4, 5, 7 and 8 of the Phase 0
brief — authenticate every endpoint, bind actor identity server-side, a
control-plane pause, a control status endpoint — are server-side. The hub runs
on Tower and its source is not in this repository or anywhere on this machine.
Nothing done here changes that, and no client-side change can.

Concretely, all of the following remain true of the running hub:

- anyone on the LAN can read every message ever posted;
- anyone on the LAN can post as `Admin`, or as any worker;
- there is no pause, no health endpoint and no status endpoint on the hub;
- the "Swarm Live Terminal" UI is served without authentication.

What containment achieves is narrower and worth stating exactly: **an attacker
who fully controls the hub can no longer cause code to run on OFFICEPC or spend
a model budget.** They can still read the conversation, write misleading
narration into it, and impersonate anyone in the UI.

### Minimal patch specification for the Tower hub

[RESOLVED 2026-09-09: all five points below were implemented in
`hub/hub.py` and deployed. The specification is kept as written because
it is what the implementation was reviewed against.]

Enough to satisfy the remaining four requirements, in the order they matter:

1. **A shared-secret dependency on every route** — all five: `GET /`,
   `GET /messages`, `POST /send`, and the `/docs`, `/redoc`, `/openapi.json`
   trio, which currently hand the whole API surface to any LAN caller. Read the expected value from an
   environment variable or a secrets file that is excluded from version control;
   never a literal. Reject with `401` when absent or wrong. Compare with
   `hmac.compare_digest`, not `==`.
2. **Per-component credentials, not one shared token** — a mapping from
   credential to component name (`claudecode`, `chatgpt`, `gemini`, `admin`,
   `operator`).
3. **Derive `sender` server-side** from the authenticated credential and
   **ignore any client-supplied `sender`, `actor` or `token` field** in the
   body. This is the requirement client code cannot satisfy at all.
4. **`POST /control/pause`, `POST /control/resume`, `GET /control/status`**,
   with the pause state persisted so it survives a restart, and `status`
   readable by any authenticated component.
5. **Never log a credential**, including in uvicorn access logs and error
   handlers.

Once that lands, the host-side pause here should read the hub's
`/control/status` as a second, independent stop, and Admin-over-chat can be
restored — at that point `sender` is finally evidence of something.

## 6. Verification

```powershell
python -m pytest tests/ -q        # 76 passed
python tests/bypass_matrix.py     # 10/10 guards load-bearing, exit 0
python workspace/guard_check.py   # FAILURES: none, exit 0
```

[RESOLVED 2026-09-09: the suite is now 83 passed, not 76 - tests were
added after this was written. The bypass and guard-check figures are
unchanged. Re-measured at `8bfdb63`; see `docs/PHASE0_VERIFICATION.md`
section 3.]

`bypass_matrix.py` is the important one. A green suite with the guards present
proves nothing about the guards — it is equally consistent with unreachable
defensive code that fails nothing when removed. The matrix removes each guard in
turn and confirms named tests fail, restoring the file in a `finally` and
verifying the restore by hash.

It has already earned its keep three times: it showed two of the expected
failure sets were wrong (crediting the rename guard with routing failures it
does not cause), it exposed a test that passed vacuously and would have stayed
green with `REPLY_TARGET` set back to `@Gemini`, and its own first run hung —
because a build with the startup refusal removed reaches the real poll loop
against the live hub, which is now caught by a tripwire.

`workspace/throttle_check.py` was retired: it asserted the throttle that this
work deleted. `workspace/guard_check.py` is unchanged and still passes; its
still-meaningful assertions were also carried into
`tests/test_model_call_path.py`.

### One regression, found and fixed

Removing the chat-era constants from `gemini_worker` also removed
`SYSTEM_PROMPT`, which `generate_reply` still referenced. Every generation would
have raised `NameError`, been swallowed by the broad `except Exception` that
keeps one bad call from killing the daemon, and returned `None` — a worker that
started cleanly, logged an error per attempt, and silently never answered.

**The full pytest suite passed throughout**, because the containment tests stub
`generate_reply`. `workspace/guard_check.py` caught it, which is the argument
for having kept it. The value was restored verbatim from the baseline commit and
asserted byte-identical; `tests/test_model_call_path.py` now covers the real
generation path, and `system_prompt_dropped` is a permanent row in the bypass
matrix.
