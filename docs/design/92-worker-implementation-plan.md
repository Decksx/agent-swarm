# #92 worker and operator CLI implementation plan

Prepared from the agreed `92-ingest-contract.md` at merged PR #102, source
`d2493667391244ca10226894b171a7590d5e1708`. This is implementation preparation;
it does not enable external ingress, issue activations or claim #92 is complete.

Claude leads controller ingress, configuration validation, state transitions,
activation issuance/recovery, evidence validation and end-to-end/mutation checks.
Codex implements the model-free worker and operator CLI in the separate
`feat/92-external-ingest-worker` worktree. Both sides require independent review
at their final commit before merging. Controller and worker must agree on the
actual activation/result envelope before the glue is enabled.

## Worker changes

1. Add `claude_ingest.py`, independent of model adapters. Resolve only the
   activation-named registered checkout. Validate the immutable external block,
   full task/ref names and registry location/slug agreement before commands.
2. Use the remaining activation deadline with a monotonic clock for all `gh`
   and `git` calls, heartbeat long commands and stop on lease loss. Commands
   use argv without a shell and bounded, sanitized diagnostics.
3. Read PR head/base/URL/state and authorship claims; allow open, draft, closed
   and merged PRs. Fetch head and the exact base SHA into activation-specific
   scratch refs. Verify metadata/operator SHA equality, range and changed files.
4. Create the final pin with expected-absent CAS; identical existing SHA is
   idempotent, conflicts refuse. Never retarget a pin or follow a pushed head.
   Delete only this task's expired scratch refs with expected-old-SHA checks,
   preserving live attempts and every other task's refs.
5. Produce bounded versioned evidence and dedicated success/refusal/environment
   outcomes. No author result, integration, merge, publication or model call.
   Network/auth/config/missing-object failures are repairable environment defects.
6. Add the explicit ingest branch in `claude_worker.execute_activation` and
   model-free claim filtering. Integrate with the controller's dedicated result
   method only once its exact request envelope is available; do not invent a
   generic event route or let the worker submit controller-authority events.

## CLI changes

Add an admin subcommand in `hub/controller_admin.py`, reachable through the
existing authenticated `worker_ctl.sh admin` path. Target only
`POST /controller/external-reviews` with task_id, project, pr_number, objective
and optional at_sha/paths/authored_by. Preserve optional-field omission and
operator text; validate locally without replacing the controller's validation.
Do not silently use ordinary create-task or issue routes if ingress is absent.

## Verification and rollout

Use temporary local Git remotes and stub GitHub metadata to exercise real fetch,
base-object retrieval, CAS and moved-head races without network/model calls.
Cover no-common-ancestor, empty range, bad/missing slugs, full evidence/overflow,
all PR states, deadline exhaustion, lease loss and safe scratch cleanup. Check
CLI payloads and verify a usage hold still allows model-free ingest claims.

Mutation checks must catch either removed SHA comparison, lost create-only CAS,
an unbounded command, unsafe ref cleanup, invalid evidence and any model call.
Claude's controller suite must additionally prove authority boundaries,
assigned/running expiry recovery, stale-result rejection and no integration
reachability. Issue #92 stops at READY_EXTERNAL_REVIEW; #93/#94 handle routing,
review and publication. Keep production ingress disabled until the combined
candidate is reviewed, tested, deployed and verified.
