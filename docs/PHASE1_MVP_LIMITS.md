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

## 4. Contract validation does nothing

`contract_yaml` is stored and hashed but never parsed. There is no linter. The
route that moves a task out of DRAFT is called `/ready` rather than `/validate`
for exactly this reason — a route named `validate` would be claiming a check
that does not exist.

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

## 7. One writer, one process

The controller's transactional guarantees assume a single writer to
`/data/controller.db`. That is true because the hub runs as one uvicorn process.
**Never add `--workers N`**: several processes behind one WAL file corrupt it
slowly, and nothing in the code would notice.
