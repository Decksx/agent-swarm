# Reviewer dispositions

What a person decided about each proposal, and when.

Kept apart from the proposal exports on purpose. Those files are generated
records of what the planner produced and what the controller stored at a moment
in time; editing one to say "rejected" would make it a record of two different
things at two different times, and the state it captured would no longer be
recoverable from it. A proposal's history is not improved by being tidied after
the fact.

The controller's ledger is authoritative for state. This is the reasoning, which
the ledger has room for only one line of.

---

## 2026-09-10 — `DOC-1`, `TEST-1`, `ROUTING-1`, `ROUTING-2`

**Rejected, all four.** Export:
[`PLAN_2026-09-10_comicautomation.md`](PLAN_2026-09-10_comicautomation.md).
Controller state: `CANCELLED`.

Every path resolved, nothing collided, the grounding report was green — and
every one of them duplicated code or tests that already existed.

| task | finding |
|---|---|
| `DOC-1` | `comic_automation/database/read_guards.py` is 553 lines and already documents the transaction sequence, `data_version`, WAL behaviour, error handling and diagnostic limitations |
| `TEST-1` | `tests/test_read_guards.py` already has 21 focused tests over that ground, including unchanged snapshots, concurrent WAL commits, transaction boundaries, integrity failures, read-only enforcement and deterministic reports |
| `ROUTING-1` | `scripts/cbz_routing.py` already provides `parse()` and `load()` with extensive structural validation and `RoutingConfigError`. The proposal omitted that module from its context and would have created a competing validator beside it |
| `ROUTING-2` | tests the redundant validator, cannot inspect its dependency's output, and overlaps `tests/test_routing_engine.py` and `tests/test_watcher_router.py` |

Written up in [`../MVP5_SEMANTIC_GROUNDING.md`](../MVP5_SEMANTIC_GROUNDING.md).
This is the run that established the distinction the whole exercise turns on:
structural grounding is not semantic grounding.

---

## 2026-09-11 — `TEST-PROVENANCE-CLI`

**Rejected.** Export:
[`PLAN_2026-09-10b_comicautomation.md`](PLAN_2026-09-10b_comicautomation.md).
Controller state: `CANCELLED`.

Three reasons, and the first is the disqualifying one.

**The justification is false where it matters.** The contract rests on CLI exit
codes, preflight checks, signal handling and argument parsing "not currently
being exercised". `tests/test_provenance_backfill_planner.py` imports
`provenance_backfill_cli as cli`, calls `cli.main()` six times, and asserts on
its exit codes — including exit 7 and both exit-130 paths: the interrupt before
the envelope is written, and the interrupt after it is committed. One of the
proposal's five acceptance criteria asks for tests that already exist verbatim.

**It asks for substantial duplicated work.** Some CLI coverage may genuinely be
missing — the exit codes not reached through those six `cli.main()` calls, and
argument parsing. That is not nothing, and it is not what this contract
describes. A new `tests/test_provenance_backfill_cli.py` written to this
specification would restate six existing tests before reaching anything new.

**It is not tied to the active milestone.** The repository's work is Slice 4B1,
twelve commits along on
`slice4b1/artifact-reader-and-applied-projection`. A CLI test suite is a
defensible thing to want and does not complete or unblock that slice. **A
technically valid task unrelated to the active milestone is not acceptable
work**, and this is the clearest statement of that rule so far: the proposal is
not fabricated, not ungrounded, and still not worth doing now.

### What this run did establish

It is markedly better than the four before it, and the improvement is the
finding rather than the rejection:

| | first run | second run |
|---|---|---|
| source files read | 0 | 5 |
| model calls | 1 | 2 |
| tasks proposed | 4 | 1 |
| fabricated | 4 | 0 |

Its central factual claim — that `tests/test_provenance_backfill_cli.py` does
not exist — is true, and it was reached by reading the CLI rather than by
observing that a path was free. `NEEDS_CONTEXT` turned a planner that guessed
into one that asked. What it did not do is let the planner find out that the
CLI's tests live in a file named after the planner, because no amount of asking
for files by path will surface that.

That is the gap `NEEDS_SEARCH` is for, and the reason the next planning run is
constrained to the active milestone rather than to general improvement.
