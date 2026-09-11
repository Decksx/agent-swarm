# The answer that was missing: "nothing needs authoring"

2026-09-11. The planner was given a way to decline, and used it. Three model
calls, no task proposed, and a review proposal instead — which is the first time
in seven runs that the useful output was not a task.

## The cause, not the symptom

Four fabricated tasks in [MVP4](MVP4_PLANNING_RUN.md). One partially-redundant
task in [MVP5](MVP5_SEMANTIC_GROUNDING.md). Both were treated as grounding
failures, and grounding was genuinely part of it — `NEEDS_CONTEXT` and
`NEEDS_SEARCH` both measurably improved the output.

But neither addressed the thing underneath. Every prompt left exactly two ways
to finish: **propose work, or fail.** A model asked what to build next, with no
way to answer *nothing*, is under pressure to invent something — and it did,
twice, in the two shapes available to it: fabricate, then restate.

The tasks were the symptom. The missing third answer was the cause.

## What was added

Five outcomes. Three of them are not a plan:

| outcome | meaning |
|---|---|
| `PLAN` | work genuinely remains and can be named |
| `MILESTONE_READY` | implementation and tests look complete; it needs review |
| `BLOCKED_ACTIVE_WORK` | in-flight work makes reliable planning impossible |
| `NEEDS_SEARCH` | needs to know whether something exists |
| `NEEDS_CONTEXT` | needs to read particular files |

`MILESTONE_READY` and `BLOCKED_ACTIVE_WORK` are deliberately distinct. One says
*the work is done*; the other says *I cannot tell*. Collapsing them would turn
"I could not see enough" into "there is nothing to do", which is the most
expensive misreading available here.

Both are held to a standard, because otherwise they become the easy way out of a
hard question and a pressured planner reaches for them exactly as readily as it
reached for inventing a task. `MILESTONE_READY` must name what it examined and
what a reviewer should check. `BLOCKED_ACTIVE_WORK` must name the specific paths
to reconcile — "something is dirty" sends a person to look at everything.

Both end the run with status 0. A run that reported "no plan produced" as a
failure would teach the next one to invent something.

## The prerequisite: a read-only census

Planning from branch HEAD while ignoring the working tree could still assign
duplicate work, so the 14 uncommitted entries were inspected first. Nothing in
that checkout was modified, cleaned, committed or stashed.

| | |
|---|---|
| staged | 0 |
| modified, tracked | 4 — 245 insertions, 7 deletions |
| untracked | 10 — 8 run logs, 1 `routing.json` backup, 1 new test file |
| **overlap with the 5 milestone files** | **none** |

The uncommitted work is `scripts/cbz_watcher.py`, `apps/cbz_gui.py` and their
tests and docs: the CBZ watcher AI-decensor subsystem. It is not unlanded Slice
4B1 work, which was the risk worth ruling out. The census went into the prompt,
so the planner could see it too.

## The run

Against the branch head, with the two implementation files preloaded, and the
five-call ceiling unchanged so that preloading could be judged on its own.

```
call 1  searched 4 terms   APPLIED_PROJECTION_VERSION -> 12 matches
                           read_plan_artifacts        -> 61, truncated
call 2  read 2 test files  40,000 bytes
call 3  MILESTONE_READY
```

Preloading did what it was supposed to. [MVP6](MVP6_SYMBOL_SEARCH.md) exhausted
five calls on discovery and produced nothing; this reached a conclusion in
three, and the ceiling was never the constraint.

Its five review focus areas are the most useful thing it produced — CRLF
byte-exact digest calculation on Windows, isolation of the version marker from
the planner digest, `_deep_freeze()` immutability on `LoadedPlan`, field-set
enforcement against `None` versus unused columns, and `page_inventory` exclusion
in `select_slice4_bindings()`. These are specific invariants found by reading
the code, not restated headings.

## Honest about what it rests on

The planner flagged its own limitation, and it was right to:

> The test suite was not run in this snapshot environment, and parts of the test
> files were truncated during context retrieval.

Quantified: it saw **29%** of `provenance_backfill_artifact.py`, **57%** of
`provenance_applied_projection.py`, **40%** of the artifact test suite and
**68%** of the projection test suite. The snapshot declared every one of those
truncations, which is why the planner could report it.

So `MILESTONE_READY` here is plausible and partial. Independent corroboration —
109 tests across the two suites, a version marker present and used in 12 places,
commit messages describing review-driven correction — is consistent with a
finished milestone, and none of it is proof. That is precisely why the output is
a review **proposal** and not an opened review.

## What is still not demonstrated

A grounded task, approved, authored and reviewed against real code. The sequence
has produced four fabricated tasks, one redundant task, one refusal to plan from
the wrong ref, and now one declined-with-reason. It has not yet produced a task
somebody wanted.

That is no longer obviously the next thing to chase. If the milestone is
complete, the next real step is the review this proposes — and the integrator,
which does not exist, is what would then be in the way.

| run | outcome | calls | fabricated |
|---|---|---|---|
| MVP4 | 4 tasks | 1 | 4 |
| MVP5 | 1 task | 2 | 0 |
| MVP6 | no plan (ceiling) | 5 | 0 |
| MVP7 | `MILESTONE_READY` | 3 | 0 |
