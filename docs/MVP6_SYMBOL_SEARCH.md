# Searching the baseline, and what it revealed about the milestone

2026-09-11. `NEEDS_SEARCH` implemented and exercised live. Three planning runs,
no plan produced, and two findings worth more than a plan would have been.

## Why search, specifically

[MVP5](MVP5_SEMANTIC_GROUNDING.md) ended with a proposal that was rejected for a
claim no amount of asking could have checked. The planner read
`provenance_backfill_cli.py` in full, correctly saw that
`tests/test_provenance_backfill_cli.py` did not exist, and proposed writing it —
while `tests/test_provenance_backfill_planner.py` was already calling
`cli.main()` six times and covering both exit-130 paths.

`NEEDS_CONTEXT` answers *"show me this file"*. It cannot answer *"does a test
for this already exist"*, because naming the file that holds the answer requires
already suspecting the answer. That is the whole gap, and it is one query wide:

```
'cli.main(' under tests  ->  19 matches, tests/test_provenance_backfill_planner.py:1889
```

## What was built

**Literal queries, never patterns.** A regular expression written by a model is
one nobody reviewed, and a catastrophically backtracking one hangs the host on
its own repository. `git grep -F` also means a result is evidence about the
exact text asked about rather than about what a pattern happened to mean.

**No shell, ever.** The query is one element of an argument list. Six hostile
queries are in the test suite — shell metacharacters, command substitution, a
`--output=` flag, a bare `-e` — and each is searched *for* rather than executed.

**The immutable base commit, not the working tree.** `git grep <sha>` searches
that commit's tree, so a match is evidence about the same bytes the author and
reviewer will see. The checkout has 14 uncommitted paths and is the one thing
guaranteed not to be what a task is authored against.

**Zero matches and truncation are different answers.** *Nothing found* is a
strong result a planner may act on; *stopped counting* is not. Conflating them
would licence exactly the confident wrong conclusion this exists to prevent, so
the render says `NO MATCHES ... you may rely on it` or
`60 matches, showing the first 30 ... do not reason about what you cannot see`.
A search that *failed* is a third state and never reads as absence.

**Ceilings on everything**: queries per round, results per query, results per
run, excerpt bytes, and the existing total model-call ceiling. Searches
accumulate across rounds alongside context, and the host records every query it
actually ran, so a task claiming it searched for something can be checked
against what happened.

**Symbol requests now route to search.** A `NEEDS_CONTEXT` entry naming a symbol
rather than a path is refused with a pointer to `NEEDS_SEARCH` instead of a flat
"not supported" — the run below spent a call discovering that the hard way.

## Finding 1: Slice 4B1 cannot be planned from the master baseline

Constrained to *completing or unblocking Slice 4B1*, and planning against
`refs/heads/master`, the planner searched, read four source files, and concluded:

> Slice 4B1 is actively being developed on branch
> `slice4b1/artifact-reader-and-applied-projection` (12 commits ahead of the
> baseline snapshot, creating `provenance_backfill_artifact.py`,
> `provenance_applied_projection.py`, and their tests). Because those 12 commits
> are not in the baseline commit, any new task planned against baseline would
> duplicate or collide with active work.

That is correct, and it is the right answer rather than a failure. The
constraint and the objective were in tension: the milestone's code is on a
branch, and the snapshot reads from the baseline by design. The planner found
the contradiction instead of planning around it — which both earlier runs would
not have done.

`applied_projection` returning **no matches** against master is the same fact
stated mechanically, and is exactly the kind of reliable absence the zero-vs-
truncated distinction exists to make trustworthy.

**This is a configuration decision, not a defect.** `planning_ref` is
deliberately configuration — see `repo_registry`'s module docstring — and
planning work that completes a branch means pointing the planner at that branch,
which also makes it the `base_sha` every authored candidate starts from. The
committed `repos.json` was **not** changed; the run below used a temporary
registry.

## Finding 2: investigation is now real, and does not converge in five calls

Planning against the branch head (`0ae92676e265`), the planner used every call
productively and still produced no plan:

| call | what it did |
|---|---|
| 1 | searched for six Slice 4B1 symbols; `read_plan` 61 matches, `AppliedProjection` none |
| 2 | read the projection and artifact implementations and both test suites (80 KB) |
| 3 | searched for `projection_digests`, `reconstruct_gate_failures`, `select_slice4_bindings` |
| 4 | **asked for the second half of a file that had been truncated** |
| 5 | searched for a `verify-plan` CLI entry point — none exists |

Call 4 is the accumulation fix from MVP5 proving itself in the field: the
planner noticed it had been cut off mid-file, asked for the remainder, and got
the *next* chunk rather than the same opening again.

Nothing here is wrong. Slice 4B1 is 4,164 added lines across five files, and
reading it at 80 KB per round takes more rounds than the ceiling allows. This is
a budget parameter, not a capability gap, and the three levers are raising
`--max-calls`, raising the fulfilment budget, or pre-supplying the milestone's
files with `--doc` so the first call starts informed.

## Where this leaves the progression

| run | tasks | fabricated | source read | searches | outcome |
|---|---|---|---|---|---|
| MVP4 | 4 | 4 | 0 files | — | all rejected as duplicates |
| MVP5 | 1 | 0 | 5 files | — | rejected: overstated the gap |
| MVP6 | 0 | 0 | 7 files | 20 queries | no plan; two findings |

Producing nothing is not a regression here. Both earlier runs produced something
precisely because producing nothing reads as failure, and both were wrong. A
planner that investigates for five calls and reports a contradiction it found is
behaving better than one that proposes a plausible task, and the `NEEDS_SEARCH`
and `NEEDS_CONTEXT` outcomes exist so that saying so is an available move.

What remains untested is the thing the whole sequence is for: a grounded task
that advances the active milestone, approved and authored. Getting there needs a
decision about which ref planning targets, and a budget matched to the size of
the milestone being read.
