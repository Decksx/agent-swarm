# Structural grounding is not semantic grounding

2026-09-10. The planning canary did its job: it produced four proposals that
passed every mechanical check and were worthless, and the gap between those two
facts is the whole finding.

## What happened

[MVP4](MVP4_PLANNING_RUN.md) produced four tasks against ComicAutomation. Every
path resolved. No two concurrent tasks collided. The base SHA was pinned, the
contracts were stored, the grounding report was green. All four were rejected
by a reviewer who could read the source:

| task | why it was rejected |
|---|---|
| `DOC-1` | `comic_automation/database/read_guards.py` is 553 lines and already documents the transaction sequence, `data_version`, WAL behaviour, error handling and diagnostic limits |
| `TEST-1` | `tests/test_read_guards.py` already has 21 focused tests over exactly that ground |
| `ROUTING-1` | `scripts/cbz_routing.py` already has `parse()`, `load()` and `RoutingConfigError` with extensive structural validation. The proposal never looked at it |
| `ROUTING-2` | tests the redundant validator, and duplicates `test_routing_engine.py` and `test_watcher_router.py` |

All four are `CANCELLED` in the controller with those reasons in the ledger.

## The failure, stated precisely

The planner was told, accurately, that no source file contents were in the
snapshot. It read that and said so in its own summary — and then planned
anyway, proposing four brand-new standalone files.

That was not carelessness. It was the only move available to it. Its options
were to plan against code it could not see, or to produce nothing, and
producing nothing reads as failure. So it produced work that was **safe to
author** rather than work that was **worth doing**, and new files are what safe
to author looks like when you cannot read the repository.

Nothing in the loop could tell those two apart. Every check in place was
structural: does this path exist, do these tasks collide, is the base fresh.
A duplicate of an existing module passes all of them, because the duplicate's
path is by definition free.

## What was added

**A third option: `NEEDS_CONTEXT`.** The planner may answer with a bounded
request for specific files instead of a plan. The host fulfils it from the base
commit and asks again. The prompt says plainly that this is the preferred
answer, and tells it what happened last time.

**A strict ceiling.** `--max-calls`, counting the first call. Reaching it
without a plan is a refusal, never a fallback to whatever the planner last
said — a fallback would restore exactly the behaviour this removes. The refusal
names what was still being asked for, because the cheap fix is usually to widen
the snapshot with `--doc` rather than raise the ceiling.

**`existing_work_checked`, required per task.** Each task must name the
implementation, tests and documentation it examined, and say why what it found
does not already cover the work. A non-answer is refused. This cannot verify
that the conclusion is *right* — that is the judgment the planner failed at,
and a parser claiming to make it would be trusted for it — but it refuses a
proposal that never looked, and it puts what was looked at in front of the
person deciding.

**Two new grounding refusals.** A task whose writable paths overlap the
**uncommitted working tree** is refused: somebody is editing those files now.
A task creating a file in a **directory whose existing contents were never
read** is refused — this is `ROUTING-1` exactly, and one examined sibling is
enough, because requiring all of them would refuse every task touching a large
directory and a check that always fires gets switched off.

**Work in progress, in the snapshot.** The active branch, its commits and its
diffstat, under a heading saying not to duplicate it. ComicAutomation's
baseline is `master`; its work is twelve commits along on
`slice4b1/artifact-reader-and-applied-projection`, and a planner shown only the
baseline plans as though nothing were in flight.

## The second run

Same repository, same base commit, same model. Given the handoff, the
development log, the architecture and engineering-decisions documents, the
active branch, the 14 uncommitted paths, and the ability to ask.

It asked. Three times, and it hit the ceiling:

```
call 1  five source files       -- provenance planner, CLI, protected
                                   migrations, job queue, job worker
call 2  two existing test files -- "to confirm whether ... already tested"
call 3  the CLI again, and the Slice 4 design document
        REFUSED: the call limit of 3 is reached
```

That refusal was correct behaviour and it also found a defect in the loop.

### The defect the run exposed

Each round's prompt was rebuilt as `prompt + latest_fulfilment`. So round three
discarded what round one had supplied, and the planner asked again for
`provenance_backfill_cli.py` — a file it had already been given **in full**. It
was not being redundant; it had genuinely lost the file, and it spent one call
of a three-call budget rediscovering that.

Fixed: evidence accumulates across rounds, a file already supplied in full is
not sent twice, and re-asking for a truncated file returns the **next** part
rather than the same opening again. Four tests pin it.

### After the fix

One task, on the second call, having read five source files:
`TEST-PROVENANCE-CLI` — add `tests/test_provenance_backfill_cli.py`.

Its `existing_work_checked` names the CLI, an existing test file and the design
document, and argues from what it found rather than from a path being free.
That is the behaviour the requirement was added to produce.

## It is still not sufficient, and that matters

Verified independently against the repository, not by re-reading the planner:

- `tests/test_provenance_backfill_cli.py` does not exist. **True.**
- The CLI defines exit codes 0–7 and 130. **True.**
- Nothing overlaps active work. **True.**
- "CLI exit codes, preflight checks, signal handling and argument parsing are
  not currently exercised." **Materially overstated.**
  `tests/test_provenance_backfill_planner.py` imports the CLI, calls
  `cli.main()` six times, and asserts exit codes including `7` and `130` —
  and one of the proposal's five acceptance criteria, covering both
  KeyboardInterrupt cases, describes tests that already exist.

So the second run is much better and is not correct. The improvement is real
and measurable — from four worthless tasks to one partially-redundant task, and
from zero source files read to five. The residue is a judgment no mechanical
check can make: nothing can tell a harness that the CLI's tests live in a file
named after the planner.

That judgment stays with a person. The proposal is exported with the
verification attached, in `DRAFT`, unactivated.

## What this changes about the roadmap

The controller was never the problem. Authority, isolation, the review cycle
and the ledger all did what they were built to do, twice.

The planner needs a repository-investigation phase before it is trusted to
decide what should be built. `NEEDS_CONTEXT` is the first piece of that and it
demonstrably works — it turned a planner that guessed into one that asked. It
is not the whole of it. What would close the remaining gap is the ability to
search the repository by symbol rather than by path, so a question like "is
there already a test that calls `cli.main()`" can be answered before a proposal
is written rather than after it is rejected.

Until then, every plan is a proposal and a person decides.
