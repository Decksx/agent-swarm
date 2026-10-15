# Slice #92: engineering decisions and controller/worker contract

Status: Claude accepted the contract with amendments in PR #102's review at
`d9762b7` (comment 6201870664), 2026-10-15. This revision incorporates those
amendments and David's PR-state/scheduling decisions; revised details still
need cross-review. This supplements `74-external-review.md`. It is not
implemented, a deployed schema, a controller verdict, or task-issuance authority.

Claude leads the controller side and end-to-end/mutation checks. Codex owns
the model-free worker and admin CLI. Each independently reviews the other's
candidate. PR #102 fixes and its renewed review come first.

## 1. A refusal terminates in FAILED

Add a controller-authority `external_ingest_refused` transition from active
ingest to terminal `FAILED`, with a typed reason and the relevant observed
facts. Never call a refusal a PR verdict or use author-defect semantics.
Examples: nonexistent PR, moved head, mismatch with an operator-named SHA,
conflicting immutable pin, or an invalid review range.

Transport/authentication failures, unavailable local objects and failed git
operations are environment defects: `EXTERNAL_INGEST_BLOCKED`, repaired back to
`EXTERNAL_PENDING`. Distinguish the cause, rather than classifying every git
exit as an invalid PR. A corrected refused request creates a new task; it does
not reopen FAILED. Reject malformed admin input before creating a task.

## 2. Use explicit assigned and running ingest states

`EXTERNAL_PENDING -> EXTERNAL_INGEST_ASSIGNED -> EXTERNAL_INGESTING` distinguishes
queued work, an issued activation and a claimed activation. Successful
registration moves running ingest to `READY_EXTERNAL_REVIEW`.

Before exposing issuance, implement lease/deadline recovery from both assigned
and running ingest back to pending. A stale result cannot change a moved-on,
cancelled or terminal task. Environment-blocked ingest repairs to pending with
a fresh activation. Add the states to activation exclusion, recovery and
reachability tests together, not in later follow-ups.

Use existing operator authority for the model-free ingest activation; the
controller validates the result and applies controller-authority events. It is
not an author activation and cannot submit an authored candidate. Add `ingest`
to Claude's model-free claim stages so a model-usage hold cannot block it.
Test the actual generic activation-result boundary: from every external state,
OPERATOR authority may apply only `activation_claimed` where defined, and no
other event. In other states even that claim is rejected. Workers report ingest
outcomes through the dedicated validated result path, never by borrowing
controller authority through a generic event submission.

David decided ingest consumes a normal host slot but sits outside the SERIAL
one-task-at-a-time engineering limit. Host capacity, claim ownership and lease
fencing still apply. Ingest cannot consume or release another task's serial slot.

Slice #92 progression issues ingest only. It stops at READY_EXTERNAL_REVIEW;
cross-family review selection, chat confirmation and review progression remain
#93. No external path can reach integration or write approved_candidate_sha.

## 3. Keep an empty base sentinel on the immutable external request version

Use `base_sha: ""` only for a dedicated, explicitly typed external-review
request whose `external:` contract block carries the PR locator and optional
operator-named head SHA. Empty means no swarm authoring baseline; it is not a
commit. Do not put HEAD, a zero hash, a guessed SHA or the requested head there.
Normal authored tasks must still require a valid baseline.
Enforce a full 40-hex `base_sha` on generic `POST /controller/tasks`; empty or
short values are rejected before any row is written. Only dedicated external
ingress may store the empty sentinel. Store `proof_mode: branch_only`, an
existing allowed database value; it does not authorize authoring/integration
or imply a baseline/sabotage proof was performed.

Do not overwrite task_versions.base_sha or rehash its contract after pinning:
that version is immutable. Record the actual PR base SHA and merge base in
`external_candidate_registered`. Later external review activations take their
expected parent from that accepted event's merge base and their expected
candidate from its pinned head, never from the empty sentinel. The offline
review packet receives those explicit SHAs. Generic author/integrator paths
must reject external requests instead of interpreting the sentinel.
In #93, `_review_evidence` must reject a missing explicit external parent
instead of falling back to the request's `base_sha`; test this boundary.

This avoids an unnecessary nullable-column migration while preserving version
and ledger meaning. A SQL NOT NULL constraint by itself is not the guard; the
dedicated ingress and stage checks must enforce the external-only exception.

## 4. Store bounded structured ingest evidence in the accepted event

Use a versioned JSON payload in `external_candidate_registered`; do not add a
blob-upload API in this slice. Reuse the existing authenticated activation-result
envelope and its task-version/state-sequence/lease fencing.

The success payload must contain:

- `schema_version: 1`;
- the registered `repo_id` and canonical repository location;
- `pr_number` and canonical `pr_url`;
- `head_sha`, `resolved_ref_sha`, `base_ref_sha`, and `merge_base`;
- `pin_ref`, `changed_files`, and raw `author_signals` with their provenance.

The immutable request/activation is authoritative for repo identity, PR number,
objective, optional scope and operator-named SHA. The controller compares its
own request fields with reported full SHAs and checks equality of head and
resolved pin. Do not trust a worker-supplied `sha_matches: true` or let a result
replace the operator's objective. PR descriptions and authorship signals remain
claims, not permission or a family verdict.

Controller-owned result checks, before applying the event, include:

- authenticated live activation, matching task/version/state sequence and lease;
- request project/location, PR number and canonical GitHub PR URL match;
- every SHA is exactly 40 hexadecimal characters;
- `pin_ref == refs/swarm/external/<task_id>` exactly;
- `resolved_ref_sha == head_sha`, and equality with any operator `at_sha`;
- `merge_base != head_sha` and non-empty `changed_files`;
- schema/type checks and the controller's own 128-KiB UTF-8 payload limit.

The controller cannot independently inspect Git objects on the worker's host.
Fetch/object/range assertions are worker evidence, while the above comparisons
are performed by the controller itself. No worker-provided boolean replaces them.

Use at most 128 KiB of canonical UTF-8 JSON evidence. If the complete required
evidence will not fit, refuse with `evidence_too_large`; do not silently truncate
signals that later routing depends on. Refusal/environment events carry typed
reason codes and bounded sanitized diagnostics, never raw credential-bearing
git stderr. Refusals record expected/observed SHAs when available.

No durable registration, verdict eligibility or READY_EXTERNAL_REVIEW state may
exist if committing the accepted event fails. Report replay must be idempotent
under the existing activation-result rules.

## 5. Protect the final ref with create-only compare-and-swap

Use `refs/swarm/external/<task_id>`, after validating its complete Git ref name.
Fetch into an activation-specific scratch ref first; do not fetch directly over
the final pin or depend on shared FETCH_HEAD. Validate that scratch object's SHA
against the metadata and any operator-named SHA, compute the three-dot merge
base, and then create the final ref with `git update-ref` expecting an absent
old value. Never force-update a final pin.

An existing pin is idempotent only when it equals the same immutable head.
Any conflicting object is a refusal, not an overwrite or a retargeted review.
A retry must not silently follow a newly pushed PR head. The task ID and its
accepted candidate are never reused for another SHA.

This provides immutable pin protection, not general resource-fence epochs:
the controller must still reject expired or superseded ingest reports. A stale
attempt can at most leave the same pinned object as an orphan; it cannot replace
a candidate or authorize review. Do not claim that Git ref CAS proves the
worker's lease is current.

Keep the final ref through review. Terminal cleanup belongs to the publication
slice and deletes only the recorded ref/object with an expected-old-SHA check,
after ensuring no live ingest uses it. Cleanup must tolerate an orphan from a
stale attempt; it must never delete a different candidate. Scratch-ref cleanup
uses `refs/swarm/ingest-tmp/<task_id>/<activation_id>` so a new ingest can find
that task's expired attempts. The next ingest clears only refs for this same
task's expired/superseded activations, with an expected-old-SHA delete and a
fresh live-activation check; never delete a live sibling or another task's ref.

## 6. Admin request and repository identity

Admin-only `POST /controller/external-reviews` accepts:

```json
{
  "task_id": "EXT-123",
  "project": "agenthub",
  "pr_number": 102,
  "objective": "Review the change against the stated acceptance criteria",
  "at_sha": "<optional full 40-hex SHA>",
  "paths": ["<optional scope>"],
  "authored_by": ["anthropic", "openai", "google", "human"]
}
```

The last three fields are optional; `authored_by` records claims only. Create
the task and `external_review_requested` atomically. Unknown project, invalid
SHA, invalid PR number, or empty objective returns 400 without a task row;
duplicate task ID returns 409. The CLI targets this exact request shape.

`INGRESS_PROJECTS` remains the project-to-location allowlist. The controller
also needs a trusted project-to-`owner/repo` map; it cannot validate a URL from
location alone. Proposed configuration: `EXTERNAL_REVIEW_REPOS`, a JSON object
such as `{"agenthub":"Decksx/agent-swarm"}`, keyed by the same project names.
This closes the source-of-slug gap in the review proposal without changing
the admin request or the existing INGRESS_PROJECTS grammar. Claude should check
this configuration detail before implementing it.

Snapshot project, location and controller-configured `repo_slug` in the
immutable `external:` block. Never accept a client-supplied slug or learn its
authoritative value from an ingest result. The worker resolves its matching
local entry in `repos.json` and checks location and `publish.repo_slug` against
that snapshot. Missing or mismatched local slug is an environment defect;
`comicautomation` currently lacks one. `repo_id` is informational unless also
trusted and snapshotted by the controller. The controller compares `pr_url`
with `https://github.com/<recorded-slug>/pull/<pr_number>`.

If paths are omitted, accepted `changed_files` become the observed scope in the
registration event and later review activation; do not rewrite the immutable
request to insert them. Explicit paths remain operator constraints.

## 7. PR states and bounded execution

David decided open, draft, closed and merged PRs are accepted. Record observed
state/draft status with provenance. Every review judges only the pinned PR head;
it does not reopen, merge, approve or change the PR. A historical verdict is
dated when performed and cannot imply review or approval preceded an old merge.
Retain the PR's reported base/head metadata, including for merged PRs; do not
substitute today's target-branch HEAD. Missing objects are environment defects;
an empty/invalid range remains a refusal, not a fabricated historical range.

Derive each `gh`/`git` subprocess timeout from the activation's remaining hard
deadline, measured with a monotonic clock. Heartbeat during long commands as
`claude_integration` does, stop on lost lease, and reserve time to report a
bounded result. No command may start with an exhausted deadline, and retries
must consume the same budget rather than resetting it.

## Shared acceptance cases

Cover operator-SHA mismatch, moved/missing PR, network/git environment defects,
duplicate reports, conflicting or identical existing pins, no common ancestor,
evidence overflow, task cancellation, expiry before claim/during fetch/after pin,
repair and reissue, stale result rejection, and preservation of normal authored
tasks. Mutation checks must detect removed SHA comparisons, lost create-only
semantics, acceptance without a live activation, missing assigned/running
recovery, and any external route into integration. Also cover all PR states,
the OPERATOR event boundary, generic empty-base rejection, explicit external
review parents, repo identity mismatch, controller-side evidence validation,
deadline exhaustion, task-scoped scratch cleanup, host-slot accounting and
preservation of the serial engineering limit.
