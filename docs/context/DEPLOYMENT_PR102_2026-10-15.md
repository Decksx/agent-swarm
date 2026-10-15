# PR #102 deployment receipt — 2026-10-15

David explicitly granted standing permission for this project's commits,
pushes, merges and deployments in the Codex conversation. Routine operations
within that scope do not require another permission question. Review, CI,
controller authority and supported runtime controls remain required.

## Exact source and engineering evidence

- PR: https://github.com/Decksx/agent-swarm/pull/102
- Approved candidate: `9b7282a39fc3ed0b5698d4f07d905f90d1be8e73`.
- Claude's no-findings engineering approval:
  https://github.com/Decksx/agent-swarm/pull/102#issuecomment-6203010215.
- Merge: `d2493667391244ca10226894b171a7590d5e1708`, 2026-10-15 22:01:25 UTC,
  performed with `--match-head-commit` pinned to the approved candidate.
- Merge tree equals the approved candidate's tree; no extra implementation
  commit was added to the reviewed PR.
- Candidate CI `38811541122`: all four checks succeeded; 2,317 tests passed.
- Merged-main CI `38814198397`: all four checks succeeded; 1,991 core,
  318 hub and eight bypass tests passed, with no failures/skips, in 6m20s.
- Prior focused Windows checks: 159 passed; all 18 in-memory mutations caught.

The approval is independent engineering evidence, not a controller-ledger
verdict. No task or historical approval was fabricated to justify the merge.

## Local deployment gate

Ran the existing `deploy_controller.sh --tests-only` on merged source, without
test-selection or failing-test bypasses. The gate ran all `tests/` and `hub/`
tests with real `C:\Python311\python.exe`, explicit Git Bash on PATH and four
parallel test interpreters. Installed pytest-xdist 3.8.0 and execnet 2.1.2
locally to run the same parallel machinery as CI.

The first local run had one failure: the bounded worker-loop test's mocked
`time.sleep` raised its loop-ending exception during contention on a shared
usage mutex, before startup reached orphan cleanup. A separate probe reproduced
that exact failure with the mutex held, and the same unchanged test passed
after release. This was not ignored or counted as a passing gate.

The full gate was rerun with an independent CLAUDE_RATE_GUARD_DIR for each
execnet test interpreter. Source, suites, assertions and test selection were
unchanged. This also keeps tests away from production usage/hold files.

- Core/all worker tests: 1,989 passed, ten scheduler-permission skips, 202.09s.
- Hub tests: 318 passed, 21.07s.
- Total: **2,307 passed, ten skipped, zero failures**; gate exit 0.

CI exercised those ten scheduled-task tests successfully. A later test-only
follow-up should isolate the Claude usage paths in the shared control fixture
so this harness does not depend on process-wide state or fake polling sleeps.

## Production operations and preserved state

Production checkout: `C:\swarm-prod\agent-swarm`.
Initial inspection found `db0bd5b64af89bef2ad2d86b53950d96527b1c96` running
under supervisor 38900, with ChatGPT 6664, Gemini 35732 and Claude 35744.
The source subsequently advanced to the approved merge during validation;
the production reflog records checkout at 22:08:52 UTC. That checkout was
already present before this turn's controlled stop/restart and is not
attributed to a checkout command from this deployment sequence.

Before restarting, verified the target source was clean, both process and
Windows user CLAUDE_RATE_GUARD_DIR settings named the existing production
directory, and the controller had no live activations. Backed up existing
usage/hold/cursor files locally and recorded their presence/hashes. Used
supported pause/stop controls; stop verified zero workers.

Started the supervisor through `pythonw.exe` / `run_hidden.pyw` with hidden
Git Bash. The initial PowerShell Start-Process wait followed the long-lived
process tree; the supervisor itself had started correctly while paused. Ended
only that waiting shell, resumed through supported controls, and used the
launcher's own process handle for the subsequent bounded ensure check.

The prior unpaused state was restored. All prior usage/hold files (including
absence where applicable) and worker/narrator cursors matched the backup
before the intentional planner smoke call.

## Final verification

- Runtime source: `d2493667391244ca10226894b171a7590d5e1708`, clean checkout.
- Supervisor PID 9372, ChatGPT 2152, Gemini 7912, Claude 41944; exactly one each.
- Fresh supervisor heartbeat, PAUSED/STOPPED absent.
- Hidden `ensure` exited 0 and reported an existing healthy supervisor.
- Worker cursors: 1490 each; narrator cursor: 525.
- All three worker identities passed authenticated preflight. Checkout,
  controller-loaded and controller-disk builds agree at
  `cc1d4f0214fe903a64a4a9edf491ef8cc00cc014d04ab9e69f7e4b6fdc2cde97`, schema 6.
- Controller files were unchanged, so no Tower copy/restart was performed.

After confirming the updated worker was running, a small real
`planner_cli.generate('claude', ...)` call returned exactly
`CLAUDE_SHARED_GUARD_OK`, reported `claude-opus-5-5`, and persisted one call
of 6.219 seconds in the production usage file. The updated refresh loaded
that record from the same configured directory. This was one paid CLI smoke
call; it did not create or issue a controller task.

Claude shared planning can now be used. Gemini's prompt is the engineering
reviewer prompt from this release, retaining its separately deployed Argon
model selection. No external-ingest runtime or new controller configuration
was enabled. The next work is #92 under `92-ingest-contract.md`; worker/CLI
preparation is isolated in the separate external-ingest-worker worktree.
