# Proposals (revised): ComicAutomation, 2026-09-10

One task, `DRAFT`, **not activated**. This supersedes the four proposals in
[`PLAN_2026-09-10_comicautomation.md`](PLAN_2026-09-10_comicautomation.md),
all of which are now `CANCELLED` in the controller with their rejection
reasons recorded in the ledger.

What changed between the two runs is not the planner. It is that the planner
could ask for source instead of guessing, and did.

| | first run | this run |
|---|---|---|
| model calls | 1 | 2 |
| source files read | 0 | 5 |
| tasks proposed | 4 | 1 |
| rejected as duplicate | 4 | — see below |

## Provenance

| | |
|---|---|
| project | `comicautomation` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| planner | `gemini-3.6-flash` |
| calls used | 2 of 4 |
| active branch shown | `refs/heads/slice4b1/artifact-reader-and-applied-projection` |
| exported | 2026-09-11T00:06:21Z |

Source the planner asked for and was given, read from the base commit:

- `docs/slice4_migration_design.md`
- `comic_automation/archive/provenance_backfill_planner.py`
- `comic_automation/archive/provenance_backfill_cli.py`
- `comic_automation/archive/revision_retention.py`
- `comic_automation/database/protected_migrations.py`

**The planner's summary**, verbatim:

> This plan adds a dedicated test suite for the provenance backfill CLI (comic_automation/archive/provenance_backfill_cli.py), covering CLI argument parsing, exit codes (0-7 and 130), output preflight checks, and error handling. I verified from the snapshot tree and source files that tests/test_provenance_backfill_cli.py does not yet exist, while the CLI logic is implemented in full.

**Consistency.** Controller contract and originating plan compared field by
field. They agree on all seven for this task.

## Independent verification — read this before deciding

Checked against the repository at the base sha by the host, not by the planner and not by re-reading the planner's own claims.

**TRUE** — tests/test_provenance_backfill_cli.py does not exist

> git cat-file -e at 032b9857a50e returns absent

**TRUE** — the CLI defines exit codes 0-7 and 130

> provenance_backfill_cli.py returns 1,2,3,4,5,6,7,130 and 0 in main()

**TRUE** — the task does not overlap active work

> neither path appears among the 14 uncommitted paths or the 5 files on slice4b1

**MATERIALLY OVERSTATED** — CLI exit codes, preflight checks, signal handling and argument parsing are not currently exercised

> tests/test_provenance_backfill_planner.py imports provenance_backfill_cli as cli, calls cli.main() six times, and asserts exit codes including 7 and 130. Six named CLI tests exist, among them test_the_cli_reports_an_interrupt_before_the_envelope_as_uncommitted and a committed-envelope interrupt case asserting code == 130.

**ALREADY SATISFIED BY EXISTING TESTS** — acceptance criterion: KeyboardInterrupt handling tests both the envelope-committed and no-envelope cases for exit code 130

> both cases are already present in tests/test_provenance_backfill_planner.py

**The open question:** Whether the exit codes not reached through cli.main() in the existing six tests (2, 3, 4, 5, 6 appear as assertions in that file but may be planner-level rather than CLI-level) and argument parsing are worth a dedicated CLI suite, given that a new file would overlap six tests that already exist.

The short version: the proposal is far better grounded than anything in the
first run — it read the CLI, it read a test file, it named real evidence, and
its central factual claim is true. But its stated justification overstates the
gap. `tests/test_provenance_backfill_cli.py` genuinely does not exist, and the
CLI genuinely is already tested, in a file named after the planner rather than
the CLI. One of its five acceptance criteria describes tests that already
exist verbatim.

That is a judgment about whether partial duplication is worth it, which is
yours. The harness cannot make it: no mechanical check can tell that
`test_provenance_backfill_planner.py` is where the CLI tests live.

---

## `TEST-PROVENANCE-CLI` — Add test suite for provenance backfill CLI entry point and exit codes

| | |
|---|---|
| state | `DRAFT` |
| mode | `test` |
| proposed owner | `chatgpt` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| dependencies | none |
| contract hash | `16b8ee13f8f568bb…` |

**Objective**

Create tests/test_provenance_backfill_cli.py to thoroughly exercise comic_automation/archive/provenance_backfill_cli.py. The tests must verify command-line argument handling, summary formatting, output preflight enforcement, and all documented exit codes: 0 (success/passing gates), 1 (plan written with gate failures), 2 (usage/missing database error), 3 (database integrity error), 4 (database changed during read), 5 (planning error), 6 (output path refusal or write failure), 7 (staging residue left behind), and 130 (keyboard interrupt handling).

**Acceptance criteria**

- tests/test_provenance_backfill_cli.py is created and passes under pytest.
- CLI exit codes 0, 1, 2, 3, 4, 5, 6, 7, and 130 are explicitly exercised against mock or temp-database scenarios.
- Preflight output path refusal (e.g. database file collision or existing output) returns exit code 6 without attempting database reads.
- KeyboardInterrupt handling tests both the envelope-committed and no-envelope cases for exit code 130.
- Summary rendering output in stdout matches expected plan and gate statistics formatting.

**Writable**

- `tests/test_provenance_backfill_cli.py` — creates

**Read-only**

- `comic_automation/archive/provenance_backfill_cli.py` — exists at base
- `comic_automation/archive/provenance_backfill_planner.py` — exists at base
- `docs/slice4_migration_design.md` — exists at base

**Existing work checked** — the new requirement, in the planner's words

- `comic_automation/archive/provenance_backfill_cli.py`
- `tests/test_provenance_backfill_planner.py`
- `docs/slice4_migration_design.md`

Why it says the behaviour is still missing:

> comic_automation/archive/provenance_backfill_cli.py implements the CLI entry point and explicit exit code contract (0-7, 130). While tests/test_provenance_backfill_planner.py tests core planner algorithms, tests/test_provenance_backfill_cli.py is absent from the repository tree and CLI exit codes, preflight checks, signal handling, and argument parsing are not currently exercised.

**Mechanical checks**

- context resolved: 3 file(s), 0 missing
- collides with uncommitted work: no
- creates a file in an unread directory: no

---

## Deciding

```bash
./worker_ctl.sh admin ready  TEST-PROVENANCE-CLI              # approve
./worker_ctl.sh admin cancel TEST-PROVENANCE-CLI --reason ... # reject
```

A `DRAFT` task is inert; nothing polls for it. Rejecting it with a reason
records the judgment in the ledger, which is what the four before it got.
