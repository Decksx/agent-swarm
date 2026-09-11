# READ-ONLY CENSUS OF UNCOMMITTED WORK IN THE CANONICAL CHECKOUT

Taken 2026-09-11 against C:\git\ComicAutomation without modifying,
cleaning, committing or stashing anything. This is somebody's work in
progress. It is NOT in the baseline you are planning against, and a task
that writes any path listed here would collide with it.

Checkout HEAD: 0ae92676e26501021c4253cb172cdf8485003e94
Checkout branch: slice4b1/artifact-reader-and-applied-projection
Staged entries: 0

## The 14 entries

### Modified, tracked (4) -- 245 insertions, 7 deletions
```
 apps/cbz_gui.py                 |  31 ++++++++-
 docs/cbz_watcher.md             |  37 ++++++++--
 scripts/cbz_watcher.py          | 145 +++++++++++++++++++++++++++++++++++++++-
 tests/test_gui_tool_commands.py |  39 +++++++++++
 4 files changed, 245 insertions(+), 7 deletions(-)
```

### Untracked (10)
```
Logs/batch-2026-08-19-a.out
Logs/batch-2026-08-19-b.out
Logs/batch-2026-08-19-c.out
Logs/drain-78-2026-08-18.out
Logs/relocation-repair-2026-08-18-v2.out
Logs/relocation-repair-2026-08-18.out
Logs/relocation-repair-2026-08-19.out
Logs/relocation-repair-apply-2026-08-18.out
routing.json.bak-2026-08-19
tests/test_watcher_ai_decensor.py
```

Eight are run logs under Logs/ and one is a routing.json backup: output,
not source. The tenth is new source:

  tests/test_watcher_ai_decensor.py -- 115 lines, 3 tests

## What this work is about

The modified hunks in scripts/cbz_watcher.py add AI-decensor invocation
and startup discovery. The untracked test file tests that the watcher
validates both paths returned across the decensor process boundary. This
is the CBZ watcher / GUI subsystem.

## Overlap with the Slice 4B1 milestone: NONE

The five files the milestone branch commits ahead of master:
```
  comic_automation/archive/provenance_applied_projection.py
  comic_automation/archive/provenance_backfill_artifact.py
  docs/engineering_decisions.md
  tests/test_provenance_applied_projection.py
  tests/test_provenance_backfill_artifact.py
```

The intersection of those five with the 14 uncommitted entries is EMPTY.
The uncommitted work is a different subsystem and is not unlanded Slice
4B1 work. Planning against this branch head does not risk duplicating it,
PROVIDED no proposed task writes any of the 14 paths above.
