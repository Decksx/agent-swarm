# Proposals: ComicAutomation, 2026-09-10

Four tasks, all `DRAFT`. **None has been activated, and no model call was
made to produce this file** — every field below is read back from the
controller and cross-checked against the plan that created it.

This exists because the planning write-up established that these proposals are
*structurally* sound — the paths resolve, the tasks do not collide — and
explicitly did not establish that any of them is worth doing. That judgment
needs the complete objectives and acceptance criteria, which lived only in the
controller database until now.

The machine-readable record is
[`PLAN_2026-09-10_comicautomation.json`](PLAN_2026-09-10_comicautomation.json),
including each stored `contract_yaml` and its hash.

## Provenance

| | |
|---|---|
| project | `comicautomation` |
| repo_id | `fdc614a6f9af1a5f` |
| planning ref | `refs/heads/master` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| planner | `gemini-3.6-flash` |
| exported | 2026-09-10T23:30:01Z |

**The planner's own summary**, verbatim, including what it said it could not see:

> This plan adds documentation, configuration validation tooling, and test coverage for database read guards and watcher routing rules. Because Python source file contents were omitted from the snapshot, tasks are structured around new, self-contained files and test modules that rely on provided documentation and configuration examples as context.

**Consistency.** The contract stored in the controller and the plan it was
created from were compared field by field — `title`, `objective`, `acceptance_criteria`, `mode`, `allowed_paths`, `context_paths`, `base_sha`. 
They agree on every field for all four tasks.

## What is being asked

Not whether these are grounded. That is settled and shown below. The open
question is whether any of them **advances ComicAutomation** — whether the
work is worth doing at all, which is the one judgment the planner has not
demonstrated it can make and which this repository deliberately does not let
it make.

Two things worth weighing per task:

- Every one of these creates a *new* file. None edits existing code. That is
  what makes them safe to author and also what limits what they can be worth.
- `ROUTING-2` writes tests for a file `ROUTING-1` creates, so it cannot read
  that file: context is read from the immutable base SHA, where it does not
  exist. It would be authored knowing what the tests should cover but not
  what they are testing against. It should not be the first task.

---

## `DOC-1` — Document WAL-aware read guard design and protocol

| | |
|---|---|
| state | `DRAFT` |
| mode | `document` |
| proposed owner | `chatgpt` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| dependencies | none |
| contract hash | `ef2275b32e4f4c04…` |

**Objective**

Create a dedicated documentation file in docs/wal_aware_read_guards.md detailing the PRAGMA data_version read-guard protocol for SQLite WAL mode, outlining transaction semantics, pre/post data_version validation, and report rejection rules.

**Acceptance criteria** — what the reviewer would judge against:

- docs/wal_aware_read_guards.md exists and explains the single deferred transaction requirement and PRAGMA data_version check protocol.
- The document details error handling and diagnostic signals when data_version changes during execution.

**Writable** (`allowed_paths`)

- `docs/wal_aware_read_guards.md` — creates

**Read-only** (`context_paths`) — 3 file(s) resolved, 0 missing

- `CLAUDE.md` — exists at base
- `docs/database_architecture.md` — exists at base
- `comic_automation/database/read_guards.py` — exists at base

---

## `ROUTING-1` — Create routing JSON configuration validation script

| | |
|---|---|
| state | `DRAFT` |
| mode | `implement` |
| proposed owner | `chatgpt` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| dependencies | none |
| contract hash | `c9007a01ac478688…` |

**Objective**

Implement a standalone script scripts/validate_routing_config.py that validates JSON routing files against expected schema constraints (destinations dictionary, default destination, and ordered rules array).

**Acceptance criteria** — what the reviewer would judge against:

- scripts/validate_routing_config.py accepts a path to a routing JSON file via CLI arguments.
- The script reports validation errors for missing default destinations, invalid JSON syntax, or malformed rule objects, and exits non-zero on error.

**Writable** (`allowed_paths`)

- `scripts/validate_routing_config.py` — creates

**Read-only** (`context_paths`) — 3 file(s) resolved, 0 missing

- `docs/cbz_watcher.md` — exists at base
- `config/routing.example.json` — exists at base
- `config/routing.v2.json` — exists at base

---

## `ROUTING-2` — Add unit tests for routing configuration validator

| | |
|---|---|
| state | `DRAFT` |
| mode | `test` |
| proposed owner | `chatgpt` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| dependencies | `ROUTING-1` |
| contract hash | `8578f87bd368c511…` |

**Objective**

Create unit tests in tests/test_routing_config_validation.py verifying scripts/validate_routing_config.py against valid sample configs and various malformed JSON structures.

**Acceptance criteria** — what the reviewer would judge against:

- tests/test_routing_config_validation.py contains unit tests passing valid routing configs (e.g. config/routing.example.json).
- Tests verify detection of invalid routing files missing mandatory keys or containing invalid rule patterns.

**Writable** (`allowed_paths`)

- `tests/test_routing_config_validation.py` — creates

**Read-only** (`context_paths`) — 3 file(s) resolved, 0 missing

- `docs/cbz_watcher.md` — exists at base
- `config/routing.example.json` — exists at base
- `config/routing.v2.json` — exists at base

---

## `TEST-1` — Add test suite for WAL-aware read guard checks

| | |
|---|---|
| state | `DRAFT` |
| mode | `test` |
| proposed owner | `chatgpt` |
| base SHA | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| dependencies | none |
| contract hash | `8fdb63f8160798a0…` |

**Objective**

Create tests/test_wal_read_guard_protocol.py to test read guard wrappers against SQLite databases in WAL mode, asserting behavior when PRAGMA data_version remains unchanged versus when a concurrent write alters data_version.

**Acceptance criteria** — what the reviewer would judge against:

- tests/test_wal_read_guard_protocol.py defines pytest test cases for read guard success on unchanged data_version.
- Test cases verify that data_version mismatches trigger report rejection or guard exceptions.

**Writable** (`allowed_paths`)

- `tests/test_wal_read_guard_protocol.py` — creates

**Read-only** (`context_paths`) — 3 file(s) resolved, 0 missing

- `CLAUDE.md` — exists at base
- `comic_automation/database/read_guards.py` — exists at base
- `tests/test_read_guards.py` — exists at base

---

## Selecting one

Approving a task means moving it `DRAFT -> READY_AUTHOR`, which is what makes
it activatable:

```bash
./worker_ctl.sh admin ready <TASK-ID>
```

Rejecting one needs no command. A `DRAFT` task is inert; nothing polls for it
and nothing will pick it up.
