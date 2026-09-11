# Review proposal: Slice 4B1

**No authoring task was created and nothing was activated.** The planner
returned `MILESTONE_READY`: its judgment is that the milestone's
implementation and tests are complete and what it needs is a review.

This document is that proposal. It is not a decision — a planner judging its
own subject complete is evidence, and opening a review on it automatically
would make the judgment self-executing.

## The milestone

| | |
|---|---|
| branch | `refs/heads/slice4b1/artifact-reader-and-applied-projection` |
| head | `0ae92676e26501021c4253cb172cdf8485003e94` |
| ahead of master | 12 commits |
| diff | 5 files changed, 4164 insertions(+) |

Files the branch adds or changes:

- `comic_automation/archive/provenance_applied_projection.py`
- `comic_automation/archive/provenance_backfill_artifact.py`
- `docs/engineering_decisions.md`
- `tests/test_provenance_applied_projection.py`
- `tests/test_provenance_backfill_artifact.py`

## How the judgment was reached

| | |
|---|---|
| planner | `gemini-3.6-flash` |
| model calls | 3 of 5 |
| searches run | 4 |
| files requested and read | 2 |

Searches the host actually ran, with what they returned:

- `provenance_applied_projection` — 3 match(es)
- `provenance_backfill_artifact` — 2 match(es)
- `APPLIED_PROJECTION_VERSION` — 12 match(es)
- `read_plan_artifacts` — 61 match(es), truncated

**Its stated reason:**

> The core modules for Slice 4B1 (`provenance_applied_projection.py` and `provenance_backfill_artifact.py`) are fully implemented, and their companion test suites (`test_provenance_applied_projection.py` and `test_provenance_backfill_artifact.py`) comprehensively cover expected behaviors, design spec alignment, byte-level document framing, and independent shape refusals.

## What a reviewer should look hardest at

These are the planner's own words, and they are the most useful part of this
document: five specific invariants it identified while reading the code.

1. Isolation of `APPLIED_PROJECTION_VERSION` from planner digest and version markers to prevent false positive comparisons.
2. Binary CRLF byte-exact digest calculation in `read_plan_artifacts()` to ensure text-mode newline normalization on Windows does not alter verification outcomes.
3. Strict field-set enforcement and table-based disambiguation for `None` values (such as `inspector_version` in `archive_inspections`) versus unused columns in `provenance_backfill_artifact.py`.
4. Exclusion and counting of `page_inventory` bindings by `select_slice4_bindings()` without discarding them from plan digest verification.
5. Immutability enforcement via `_deep_freeze()` and read-only mapping proxies on `LoadedPlan` and `AppliedBinding` to prevent post-verification state mutation.

## The caveat, quantified

The planner flagged this itself:

> The test suite was not run in this snapshot environment, and parts of the test files were truncated during context retrieval, though the examined code and test assertions cover all major invariants specified in the milestone design.

It is right, and the magnitude is worth stating precisely. The snapshot
declared every truncation honestly, and the planner reached its conclusion
having seen this much of each file:

| file | seen | total | |
|---|---|---|---|
| `comic_automation/archive/provenance_applied_projection.py` | 12,000 | 21,237 | 57% |
| `comic_automation/archive/provenance_backfill_artifact.py` | 12,000 | 42,036 | 29% |
| `tests/test_provenance_applied_projection.py` | 20,000 | 29,337 | 68% |
| `tests/test_provenance_backfill_artifact.py` | 20,000 | 50,609 | 40% |

So `MILESTONE_READY` rests on 29% of the artifact implementation and 40% of
its test suite. That is not a refutation — but it is the reason this is a
proposal for a human review rather than a conclusion.

## What corroborates it independently

Checked by the host against the repository, not by re-reading the planner:

- The two test suites contain **109 tests** between them (51 + 58). A
  milestone with no tests would be the obvious counter-evidence; this is the
  opposite.
- The branch's own commit messages describe review-driven correction —
  *"Record what review found, not the version that passed my own tests"*,
  *"Correct two docstring claims that did not survive the implementation"* —
  which is the shape of work approaching completion rather than beginning.
- A search for `APPLIED_PROJECTION_VERSION` returns 12 matches; the version
  marker the design calls for is present and used.
- **Zero overlap** between the milestone's five files and the 14 uncommitted
  entries in the working tree. The dirty work is the CBZ watcher AI-decensor
  subsystem and is unrelated. See the census below.

## The uncommitted work, and why it does not block this

A read-only census was taken before this run; nothing in that checkout was
modified, cleaned, committed or stashed.

- 4 modified tracked files, 245 insertions, 7 deletions
- 10 untracked: 8 run logs, 1 `routing.json` backup, and one new source file
  `tests/test_watcher_ai_decensor.py` (115 lines, 3 tests)
- 0 staged

All of it is `scripts/cbz_watcher.py`, `apps/cbz_gui.py` and their tests and
docs. None of it is unlanded Slice 4B1 work, which was the risk worth ruling
out before planning from branch HEAD.

## What this proposal asks for

A decision on whether to open a review of Slice 4B1, with the five focus
areas above as its agenda, and with the coverage caveat understood.

It does not ask for a task, because the planner's finding is that there is no
task to author — and being able to say that is the capability this run was
testing.
