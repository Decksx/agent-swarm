# The first plan, and the six ways one gets refused

2026-09-10. Planner `gemini` (gemini-3.6-flash), one model call. Target:
`comicautomation`, the authoritative checkout at `C:\git\ComicAutomation`,
resolved through the committed `repos.json` — the real project, not a
demonstration repository.

Nothing was executed. Four tasks exist in the controller in `DRAFT` and
nothing will pick them up.

## What was being demonstrated

That a planner's output stops being prose before it becomes state. Every field
is checked against something outside the plan, the checks are mechanical, and
the plan is refused whole when any of them fails.

One model call was spent on the plan. The six refusals below were demonstrated
with `--from-reply` against hand-written replies, which costs nothing and is
the only way to exercise a rejection path deliberately rather than waiting for
a model to produce one.

## The snapshot

| | |
|---|---|
| ref | `refs/heads/master` |
| base | `032b9857a50e` |
| tree | 275 files |
| documents shown | 14 |
| omissions declared | 42 |
| prompt | 90,146 characters |

The planner is told what it was not shown. It used that: its summary opens
with *"Because Python source file contents were omitted from the snapshot,
tasks are structured around new, self-contained files and test modules that
rely on provided documentation and configuration examples as context."*

That is the OMITTED section doing its job. A planner that had not been told
would have planned against source it could not see, and the first sign of
trouble would have been an author failing to find a function.

## The plan

Four tasks, all grounded.

| task | mode | writes | reads | after |
|---|---|---|---|---|
| `DOC-1` | document | `docs/wal_aware_read_guards.md` *(new)* | 3 files | — |
| `TEST-1` | test | `tests/test_wal_read_guard_protocol.py` *(new)* | 3 files | — |
| `ROUTING-1` | implement | `scripts/validate_routing_config.py` *(new)* | 3 files | — |
| `ROUTING-2` | test | `tests/test_routing_config_validation.py` *(new)* | 3 files | `ROUTING-1` |

Twelve context paths across four tasks. Every one of them exists at
`032b9857a50e`, verified independently with `git cat-file -e` rather than only
by the grounding step that was under test. All four written paths are new
files, also verified — no task is about to rewrite something.

Three tasks have no dependencies and could be authored simultaneously. No two
of them write the same path; the plan would have been refused if they did.

## `context_paths`, used as intended

This is the first plan that could separate reading from writing, and the point
of the exercise was partly to see whether a planner would use it. It did:

```
DOC-1     writes docs/wal_aware_read_guards.md
          reads  CLAUDE.md
                 docs/database_architecture.md
                 comic_automation/database/read_guards.py
```

`read_guards.py` is the module the document describes. Before this field
existed, the only way to let the author read it was to put it in
`allowed_paths` — which would have made a documentation task capable of
rewriting the module it was documenting. That is not a hypothetical: the
rejected DEMO-2 candidate replaced a file it was asked to reword one sentence
in.

## The six refusals

Each was run against the same real snapshot. Each exits non-zero.

| case | refused with |
|---|---|
| two independent tasks writing one path | *"A-1 and B-1 have no dependency between them, so they may be authored at the same time, but both may write docs/shared.md. Whichever integrates second would carry the base version of the other's file and silently revert it."* |
| a planner granting `UNRESTRICTED` | *"a plan may not grant UNRESTRICTED. Repository-wide authority is an operator's decision, not a planner's."* |
| `UNRESTRICTED` in `context_paths` | *"A reading list of everything is not a reading list — the context budget would decide which files the author actually saw, in tree order."* |
| a path in both lists | *"A path is writable or it is reference material; it cannot be both, and the author would be given both statements at once."* |
| a dependency cycle | *"the dependencies contain a cycle among: A-1, B-1"* |
| a context path that is not there | parses; reports `NOT GROUNDED`, and `--create` is refused |

The last one is the one that matters most, and it is the only one the parser
cannot catch. `comic_automation/scanner.py` is a perfectly well-formed path in
a project that has a `comic_automation/` package. Nothing about it is
malformed. It simply is not there, and only the tree can say so.

The write collision is the one whose consequence is quietest. It is not a merge
conflict, which is loud. Both authors are shown the same file at the same base,
and the output contract requires each to return that file's *complete* new
contents — so the second candidate to integrate carries the base version of the
first one's edit. The first task's change disappears. Nothing fails. Both
tasks are approved, both branches exist, and one change is gone.

## What the controller holds now

```text
DOC-1      DRAFT  base 032b9857a50e  writes 1, reads 3
TEST-1     DRAFT  base 032b9857a50e  writes 1, reads 3
ROUTING-1  DRAFT  base 032b9857a50e  writes 1, reads 3
ROUTING-2  DRAFT  base 032b9857a50e  writes 1, reads 3
```

Each contract carries both lists:

```yaml
schema_version: 7
task_id: DOC-1
mode: document
allowed_paths:
  - docs/wal_aware_read_guards.md
context_paths:
  - CLAUDE.md
  - docs/database_architecture.md
  - comic_automation/database/read_guards.py
```

`DRAFT` is not executable. Something has to move a task to `READY_AUTHOR`, and
`plan_run.py` deliberately does not do that unless asked with `--ready`.

## A limit this run exposed

`ROUTING-2` writes tests for `scripts/validate_routing_config.py`, which
`ROUTING-1` creates. Its `context_paths` cannot name that file: it does not
exist at the base commit, so grounding would refuse the plan.

This is not a planner mistake. It is a structural consequence of context being
read from the immutable base SHA, which is the property that makes the author
and the reviewer look at the same bytes. A dependent task cannot read its
predecessor's output, so `ROUTING-2` would be authored knowing only what the
tests should cover and not what it is testing against.

Nothing here fixes that, and it is worth being explicit about rather than
discovering it as a puzzling review rejection. It also decides something: when
one small task is picked to run for real, it must not be `ROUTING-2`.

## What this did not demonstrate

- Authoring. No task left `DRAFT`, and no author has seen a `context_paths`
  contract from a real plan.
- A plan going stale. `is_stale` is tested, not run live; the planning ref has
  not moved since the snapshot.
- Any judgment about whether this work is worth doing. The plan is grounded,
  its tasks are independent, and its paths are real. Whether the repository
  wants a routing-config validator is a question for a person, and the
  validator is deliberately not equipped to answer it.
