# MVP-1 — the review half

2026-09-09, continuing `docs/MVP1_AUTHOR_RUN.md`. Gemini converted to the
controller queue as a verifier, and MVP-1 reviewed for real.

**Final state `READY_INTEGRATION`. Nothing was merged.** `main` in the scratch
repository is still at the seed commit, `task/MVP-1` is not merged into it, and
the repository has no remote.

---

## The complete ledger

```text
seq=1   contract_validated             DRAFT -> VALIDATED                actor=admin      authority=controller
seq=2   queued                         VALIDATED -> READY_AUTHOR         actor=admin      authority=controller
seq=3   author_activation_issued       READY_AUTHOR -> AUTHOR_ASSIGNED   actor=controller authority=controller
seq=4   activation_claimed             AUTHOR_ASSIGNED -> AUTHORING      actor=claudecode authority=author
seq=5   candidate_submitted            AUTHORING -> READY_REVIEW         actor=claudecode authority=author
seq=6   review_activation_issued       READY_REVIEW -> REVIEW_ASSIGNED   actor=controller authority=controller
seq=7   activation_claimed             REVIEW_ASSIGNED -> REVIEWING      actor=gemini     authority=verifier
seq=8   environment_defect             REVIEWING -> REVIEW_BLOCKED       actor=gemini     authority=controller
seq=9   environment_repaired           REVIEW_BLOCKED -> READY_REVIEW    actor=admin      authority=controller
seq=10  review_activation_issued       READY_REVIEW -> REVIEW_ASSIGNED   actor=controller authority=controller
seq=11  activation_claimed             REVIEW_ASSIGNED -> REVIEWING      actor=gemini     authority=verifier
seq=12  review_requirements_satisfied  REVIEWING -> READY_INTEGRATION    actor=gemini     authority=controller
```

Twelve events. Seq 12 is the one this whole design exists for: **actor
`gemini`, authority `controller`.** The reviewer could not emit that event
itself — the verifier role is not authorized for it — and the controller
emitted it only because gemini held that specific live review activation.

## Seq 8 was my mistake, and it is left in the record

I issued the first review activation without `expected_branch`. The controller
has no working copy, so that activation told the reviewer nothing about what to
look at.

Gemini claimed it, found no branch, and **refused rather than guessing** —
reporting `blocked`, which is a statement about the review rather than about
the change. Zero model calls: the branch check runs before the model is
invoked, so a malformed activation costs nothing.

That is why there are two review activations rather than one. The acceptance
condition of exactly one issued-and-claimed activation holds for the review
proper (seq 10-12); seq 6-8 is an operator error and its recovery, and it is
recorded rather than tidied away because it exercised two paths a clean run
never would: a reviewer refusing to review, and an operator repairing a blocked
task.

It also found a real gap. `environment_repaired` is a controller transition, and
the generic `/transition` route is admin authority, so `AUTHOR_BLOCKED` and
`REVIEW_BLOCKED` were **one-way doors** — a worker could put a task into them
and nobody could take it out. `/tasks/{id}/repair` (seq 9) is the fix.

## The review itself

```text
REVIEWING activation f56e70c5... : task/MVP-1  ee075410ab9d..80cf8c8a9e50, 1 file(s)
VERDICT   satisfied in 3.3s
RATIONALE The diff adds `demo.txt` containing the exact specified text
          `MVP-1 completed`. The change is committed on branch `task/MVP-1`
          with the required commit message `MVP-1 branch-only demonstration`.
```

The rationale cites the diff's actual contents, the branch, and the commit
message — which is the evidence the packet carried, not the author's summary.
That is the difference between a review and a rubber stamp, and it is why the
packet is built from git.

**One model call.** `REVIEWING` and `VERDICT` each appear exactly once in the
whole of today's log.

## Acceptance conditions, measured

| Condition | Evidence |
| --- | --- |
| One review activation issued and claimed | Seq 10-12 for the review proper. Seq 6-8 was my malformed first attempt, recorded above |
| Exactly one Gemini model call | One `REVIEWING` line, one `VERDICT` line, today |
| Review and planning modes distinct | Stage dispatch is explicit; an unrecognised stage is reported blocked, not guessed at |
| Structured verdict plus rationale | `VERDICT:` / `RATIONALE:` required; prose without a `VERDICT` line parses to `blocked` |
| Approval moves to `READY_INTEGRATION` | Seq 12 |
| Rejection moves to `CHANGES_REQUESTED` | Mapped and unit-tested; not exercised live, and not claimed as such |
| No manufactured transition | A verifier calling `/result` with `review_requirements_satisfied` gets 403. Tested locally, and structurally: the judgment route is the only path |
| Repeated polling and restart do not repeat | Polled ~40s after the verdict, then stopped and restarted: `state_seq` stayed 12, model-call count stayed 1 |
| Stops unmerged at `READY_INTEGRATION` | `main` at `ee07541`, `task/MVP-1` at `80cf8c8`, not merged, no remote |

## Two operational findings

**Stopping the background task did not stop the worker.** The launcher `exec`s
python, and killing the task left the python process running. Four workers were
found alive at one point — two of each. They were harmless (a duplicate poll
finds nothing, which is the property the controller already guarantees), but
"exactly one model call" is not measurable while stray workers exist, so they
were killed and the count re-checked before the real review. Any future live
run should verify the process count, not the task list.

**The provider key was read from this machine's own User environment** and the
hub secret from Tower, both passed straight into the worker's environment and
neither displayed. Same arrangement recorded in `docs/MVP1_AUTHOR_RUN.md`, on
the same authorization.

## What is not proven

`CHANGES_REQUESTED` has not been exercised end to end — the demonstration task
was correct, and manufacturing a failing one to watch the rejection path was
not part of this run. The mapping and the state transition are unit-tested; the
live path is not.

Nothing has been integrated. `READY_INTEGRATION` means a reviewer approved a
candidate, and no more than that: there is no integrator, and the task stays
there until one exists. See `docs/PHASE1_MVP_LIMITS.md`.
