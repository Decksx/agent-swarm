# Phase 1 MVP — accepted limitations

Written 2026-09-09, maintained alongside `phase1/mvp-slice`.

These are things the MVP does **not** do, recorded here because a limitation
that lives only in a code comment is invisible to whoever is deciding whether
to rely on the capability. Each entry says what is missing, what it means in
practice, and what would close it.

None of these is a defect. They are deliberate deferrals, and the MVP is
usable with them provided the constraints below are respected.

---

## 1. Model execution is fail-safe, not exactly-once

**What is guaranteed.** A worker writes an in-flight marker before invoking the
model and clears it after reporting. On restart, a leftover marker means the
process died mid-task; the worker refuses to resume it, logs the activation id,
and leaves it to expire so the controller's sweep recovers the task. No result
is ever invented for a run nobody observed, so the *controller's* state stays
consistent with what is known.

**What is not guaranteed.** That the model did nothing before the crash.
`claude -p` runs with Bash authority: it may already have written files, made
commits, or pushed. Once the lease expires, a replacement activation runs the
same task again, on top of whatever the first attempt left behind.

**Why it cannot simply be fixed.** No bookkeeping on the worker side can make
model execution exactly-once across process failure. The crash can land between
any two operations, including between "the model committed" and "the marker was
written to disk". The only sound approach is for recovery to *inspect* the
expected branch and artifacts before reissuing, and decide whether the previous
attempt already did the work. That is not built.

**The constraint this places on the MVP**, and it is not optional:

- tasks routed through this path are **harmless** — no production data, no
  irreversible operations;
- every task gets its **own branch**, named for the task, so a repeated attempt
  collides visibly rather than interleaving with anything else;
- **no production-changing task** goes through this path until recovery checks
  the expected branch and artifacts before reissuing.

## 2. The deterministic completion predicates are not implemented

Protocol section 8 requires the controller to emit
`review_requirements_satisfied` only when the deterministic predicates hold,
computed from evidence rows. Nothing computes them.

For the MVP the gate is the reviewer's authenticated judgment, applied with
controller authority by `submit_review_judgment()` once it has verified the
caller holds that specific live review activation. The controller checks *who
may close the gate*; it does not check *whether the work is any good*.

A test asserts that `satisfied` is accepted with zero evidence rows in the
database, so the limitation is visible in the suite rather than only in prose —
and so that implementing predicates produces a failing test naming the promise
newly being kept.

## 3. There is no integrator

Nothing merges. A task that passes review stops at `READY_INTEGRATION` and
stays there.

**A branch-only demonstration must say so.** Its result reports the candidate
branch and the full SHA, and it must not be described as merged, integrated or
deployed. An ordinary task with no real integrator is left at
`READY_INTEGRATION` rather than being walked to `COMPLETE` by hand — walking it
would make the ledger say a thing happened that did not.

No real ComicAutomation milestone is closed until its accepted commits are
actually integrated and verified.

## 4. There is no general contract linter

Two different things were being described by one sentence here, and the
sentence was the pessimistic one. Stating it that broadly is not a safe
overstatement: a reader who believes a contract's scope is unenforced will
either not trust the harness with a real repository, or will add a second
enforcement layer somewhere else — and a second scope check that can disagree
with the first is worse than either alone.

**What is not validated: the contract as a schema, at the controller.**
`contract_yaml` is stored and hashed and never parsed by the controller. It
does not check that the document is well-formed, that its keys are ones this
protocol defines, that required fields are present, or that a field it does
not recognise is absent. The route that moves a task out of `DRAFT` is called
`/ready` rather than `/validate` for exactly this reason — a route named
`validate` would be claiming a check that does not exist.

**What is enforced: the execution fields, at the worker, before any model
call.** `authored_change.parse_scope` reads `allowed_paths` and
`context_paths` out of the contract, and the task is refused before the model
is invoked if it cannot. This is real enforcement, not a formality:

- an absent, empty, or unparseable `allowed_paths` raises rather than
  defaulting to anything — silence is never read as permission, and the
  earlier behaviour where an unreadable contract meant repository-wide write
  access is the reason this rule is stated in those words;
- `UNRESTRICTED` is the only way to authorise the whole tree, is a literal
  word rather than a glob or an empty list, and a *planner* may not grant it;
- every path an author writes is checked against the parsed scope at commit
  time, by path component rather than string prefix;
- a write to anything in `context_paths` is refused, including under
  `UNRESTRICTED`.

So the gap is a linter, and its consequence is narrower than "nothing is
checked": a contract can carry a misspelt or unknown key, or omit a field the
protocol defines, and nothing will say so until a worker either ignores it or
blocks on it. A contract whose `allowed_paths` is wrong in a way that *widens*
authority is not one of the things that gets through.

## 5. Deferred v7 machinery, present but inert

These exist in the schema or the state table and nothing drives them. They are
kept rather than deleted because removing and re-adding them costs more than
leaving them dormant, but nothing should be built on top of them yet:

| Deferred | State |
| --- | --- |
| Cooperative drain (§6) | `host_capacity.drain_requested` exists; nothing sets it, and no API route exposes it |
| Evidence blobs (§9) | Tables exist; results are accepted with an empty evidence list |
| Worktrees, candidate ancestry, diff gates (§11) | State machine models them; nothing implements them |
| Path reservations, concurrent merge trains (§11) | `CONCURRENT` mode is not entered |
| Budget metering (§14) | `budget_windows` table exists; nothing writes it |
| Protocol migration machinery (§17) | `SCHEMA_VERSION` is 1 and has one deployment |

## 6. Budget is not metered

Nothing counts tokens or dollars. The 5-hour uptime guard in `claude_worker` is
a coarse proxy for the Claude subscription window and bounds nothing for the
per-token providers. A runaway loop would be caught by the containment
structure rather than by a cost ceiling.

This matters more than it looks: the incident that started this work produced
330 agent-to-agent messages, and the two per-token providers bill against a
$10/month plan.

## 7. The single-instance lock trusts a pid alone

`swarm_control.SingleInstance` decides whether a lock is stale by asking
whether the pid in it is still alive. It does not check that the live process
is *the same* process that took the lock.

Pids are reused. A worker that crashes and whose pid is later handed to
something unrelated -- on Windows, plausibly within one uptime -- produces a
lock that looks held by a live process and refuses to let the real worker
start. The failure is a worker that will not run and an operator being told a
pid that belongs to a text editor.

Closing it means recording process identity alongside the pid: creation time is
the usual choice, since it is available on both platforms and is stable for the
life of a process. Until then, an operator who is certain the holder is gone
removes the pid file, which the refusal message names.

Deliberately not fixed before the ChatGPT conversion: the window is narrow, the
symptom is loud rather than silent, and the manual escape is one file deletion.

## 8. One writer, one process

The controller's transactional guarantees assume a single writer to
`/data/controller.db`. That is true because the hub runs as one uvicorn process.
**Never add `--workers N`**: several processes behind one WAL file corrupt it
slowly, and nothing in the code would notice.
