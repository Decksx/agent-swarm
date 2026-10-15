# PR #96 review

Reviewed on October 15, 2026.
PR: https://github.com/Decksx/agent-swarm/pull/96
Candidate: 4ce87b2232a74fa00de711736269c4b0a66abbc2
Base: 983e32482d2ac5331cf54292341a19659c250da8
Scope: issue #91, external-review design section 4 and slice 1.
Method: fresh review of all six changed files and the surrounding controller, activation, outcome, progression, database and narration code in an isolated detached worktree. No candidate source edits.

## Findings

Verdict: PASS for slice 1 at 4ce87b2232a74fa00de711736269c4b0a66abbc2. No blocking correctness findings in this slice. Validation has the host-dependent skips described below.

The seven external-review states form a separate chain. A graph walk includes every transition, under every authority, and proves that the chain reaches only its own states, CANCELLED and SUPERSEDED. It cannot reach authoring, ordinary review or integration. Verdicts are terminal, replay from the ledger and do not grant integration approval. Each blocked stage repairs to its own starting state.

The earlier automated review's premature-ingress finding is addressed: the generic admin transition route explicitly refuses external_review_requested, with API regressions checking that the task and its event history remain unchanged. Controller-authority transitions cannot be invoked through that admin route. The dedicated ingress remains deferred to slice 2.

Narration now covers the three new events plus the previously omitted integration-blocked and reconciliation-observation events. External verdict lines identify the PR, abbreviated head SHA and judgment. The new event-coverage test prevents silently omitting a future event.

## Validation

Initial full python -m pytest tests/ hub/ -q --tb=short: 2,184 passed, 18 failed, 30 skipped, in 1,035.34 seconds. All 18 failures were in the unchanged tests/test_worker_ctl_root.py, whose shell lookup picked C:\Windows\system32\bash.exe. Its output reports that WSL has no installed distributions. I initially let the tests select the host's default Bash instead of selecting Git Bash explicitly. Raw output: pr96-test-results.txt.

Corrected shell-suite run, with C:\Program Files\Git\bin and C:\Python311 prepended to the process PATH: 22 passed, 30 skipped, in 28.38 seconds. This reran all three suites that resolve Bash from PATH: test_worker_ctl_root.py, test_author_project_environment.py and test_install_registers_the_task.py. Every previously failing test passed; no candidate source changes were needed. Raw output and skip reasons: pr96-shell-test-results.txt.

The 30 skips are 20 supervisor-launcher checks whose SSH stub cannot shadow the real binary on this host, and 10 scheduled-task registration checks requiring permission to register/remove tasks. These remain unverified locally; the full suite was not rerun after correcting PATH.

Focused controller, external-review, narration and API suites: 356 passed in 22.10 seconds. One dependency deprecation warning, no skips or failures. Raw output: pr96-focused-test-results.txt.

Five fresh, independent in-memory guard mutations were all detected: integration leakage, a repair leaking into ordinary review, verifier self-verdict authority, a second entry into external review, and removal of the integration-blocked announcement. No source files were changed for these checks.

Whitespace check passes with core.whitespace=cr-at-eol, respecting the existing CRLF controller API file.

GitHub reports both CI jobs successful at the candidate SHA.

## Scope and limits

This is the state-machine foundation, not the complete external-review feature. Ingest, activation evidence, routing, outcome handling and verdict publication remain later slices. In particular, later activation support must extend lease/deadline recovery to the external assigned/running states before those states are made reachable in production.

Deployment context: the production checkout's recorded commit c93601b is older than this PR's base, but their committed differences are limited to README.md and the external-review design document. That Git-history gap does not itself establish a runtime-code mismatch. This PR changes controller and supervisor-loaded narration code, so deploying it would require a Tower controller build and supervisor restart.

This report is a local review artifact. It is not a controller-ledger verdict or a submitted GitHub approval. No merge, deployment, supervisor restart or production-state mutation was performed for this review.
