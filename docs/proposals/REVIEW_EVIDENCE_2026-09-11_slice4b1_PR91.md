## Review evidence — Slice 4B1

Performed from a **clean isolated worktree** detached at the candidate SHA, never the canonical checkout (which carries 14 uncommitted entries belonging to unrelated watcher work). **No corrective edits were made.**

| | |
|---|---|
| candidate SHA | `0ae92676e26501021c4253cb172cdf8485003e94` |
| base | `032b9857a50e1d1e6c18cb9cb55c615d69a637e3` |
| worktree status | 0 entries, detached |
| ancestry | base is an ancestor; 12 ahead, **0 behind** |

### Tests — exact counts

| suite | result |
|---|---|
| `tests/test_provenance_applied_projection.py` | **53 passed** in 0.48s |
| `tests/test_provenance_backfill_artifact.py` | **116 passed** in 2.03s |
| full suite | **2287 passed, 3 skipped** in 146.90s |

169 tests across the two milestone files.

### Line endings and whitespace

`git diff --check master...HEAD` — clean, no whitespace errors.

All five changed files are LF-only on both sides; `docs/engineering_decisions.md` was LF on master and stayed LF. No normalisation churn.

### The five invariants

Each was raised as a review focus. All five hold.

1. **Version marker isolation** — `APPLIED_PROJECTION_VERSION = "provenance-backfill-applied/1"`, explicitly not `PLAN_DIGEST_VERSION`, with the reason documented: a borrowed marker would compare equal across a change to either definition.

2. **CRLF byte-exact digests** — `projection_document()` returns and builds `bytes`, joining with `b"\n"`. The reader takes `path.read_bytes()` and digests **before** decoding; CSV parses through `io.StringIO(text, newline="")`. The Windows text-mode translation hazard is handled and documented at both ends, plus a canonical re-render check that rejects a lone-LF terminator.

3. **Field-set enforcement and `None`** — `AppliedBinding.__post_init__` requires exact set equality against `PROJECTION_VALUE_FIELDS`, so a present-but-`None` `inspector_version` is distinguished from an absent column. The empty-string → `None` decode in `_binding_from_row` is a real acknowledged ambiguity, and the safety argument holds: a genuine empty-string value would reconstruct to `None`, produce a different plan digest, and be refused rather than silently misread.

4. **`page_inventory` exclusion is counted** — `select_slice4_bindings()` returns `(projected, excluded)`; `project_planned_binding()` raises rather than returning `None` for one arriving individually, so the deliberately-unapplied count cannot quietly disagree with reality.

5. **Immutability** — `_deep_freeze` builds a **fresh** dict before wrapping in `MappingProxyType`, so the proxy is over state nothing else holds a reference to. `AppliedBinding.__post_init__` copies and freezes **before** validating, so what is checked is what is rendered. Both carry the prior defect they fix in their docstrings.

### Notes, not blockers

- `reconstruct_gate_failures` deliberately reimplements the planner's property rather than calling it, and pins the duplication with `test_the_gate_failure_reconstruction_matches_the_planner`. The reasoning is sound; it remains a duplication to keep in step.
- `provenance_applied_projection` imports the planner's private `_canonical_json` on purpose, documented as the correctness property rather than an accident.

### Provenance of this review

The planning system returned `MILESTONE_READY` rather than inventing a task, having seen only 29–68% of the major files. This review read all five changed files and ran the suites in full, so it supersedes that partial basis.

Nothing failed. This is evidence for a review decision, not an approval.
