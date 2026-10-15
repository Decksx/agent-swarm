# Slice #92: engineering decisions and controller/worker contract

Status: Claude accepted the contract with amendments in PR #102's review at
`d9762b7` (comment 6201870664), 2026-10-15. This revision incorporates those
amendments and David's PR-state/scheduling decisions. Claude approved the
repo-slug map with conditions in comment 6202675380 against `0fbdc67`; those
conditions are recorded below. This supplements `74-external-review.md`. It is not
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
engineering policy. Only host capacity is enforced in current code; SERIAL
enforcement is unimplemented. Ingest does not count toward any execution lane.
Host capacity, claim ownership and lease fencing still apply. Do not claim a
test proves an existing serial limiter or add such a limiter in this slice.

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
This approved configuration closes the source-of-slug gap without changing
the admin request or the existing INGRESS_PROJECTS grammar.

A project must be present in both maps. A known ingress project absent from
EXTERNAL_REVIEW_REPOS returns 400 `project not enabled for external review`,
with no task row. Validate every slug with the existing `repo_registry.REPO_SLUG`
owner/name rule, including rejection of option-like strings such as `--help`.
Malformed JSON or any invalid slug disables external review only, with a clear
configuration error on each external-review request; it must never prevent the
controller from starting or serving its other routes.

Record the setting alongside the other controller environment settings on
Tower. The deployment check reports presence/absence without printing values;
source approval is not permission to alter the deployed configuration.

Snapshot project, location and controller-configured `repo_slug` in the
immutable `external:` block. Never accept a client-supplied slug or learn its
authoritative value from an ingest result. The worker resolves its matching
local entry in `repos.json` and checks location and `publish.repo_slug` against
that snapshot. Missing or mismatched local slug is an environment defect;
`comicautomation` currently lacks one. `repo_id` is informational unless also
trusted and snapshotted by the controller. The controller compares `pr_url`
with `https://github.com/<recorded-slug>/pull/<pr_number>`: compare owner/name
case-insensitively and require the exact PR number. Use the same case-insensitive
slug comparison for local registry/snapshot agreement. A genuine slug mismatch,
including a rename/transfer or stale local registry, is a repairable environment
defect (`EXTERNAL_INGEST_BLOCKED`), never a refusal of the PR.

If paths are omitted, accepted `changed_files` become the observed scope in the
registration event and later review activation; do not rewrite the immutable
request to insert them. Explicit paths remain operator constraints.

## 7. PR states and bounded execution

David decided open, draft, closed and merged PRs are accepted. Record observed
state/draft status with provenance. Every review judges only the pinned PR head;
it does not reopen, merge, approve or change the PR. A historical verdict is
dated when performed and cannot imply review or approval preceded an old merge.
Retain the PR's reported base/head metadata, including for merged PRs; do not
substitute today's target-branch HEAD. Fetch the exact reported `baseRefOid` by
SHA alongside the head in the same bounded scratch-fetch phase, keeping both
objects in activation-specific scratch refs until range computation completes.
This is required for merged PRs too; fetching only the head may leave the base
object absent locally. Verify the fetched base object matches its metadata.
Missing or unfetchable objects are environment defects;
an empty/invalid range remains a refusal, not a fabricated historical range.

Derive each `gh`/`git` subprocess timeout from the activation's remaining hard
deadline, measured with a monotonic clock. Heartbeat during long commands as
`claude_integration` does, stop on lost lease, and reserve time to report a
bounded result. No command may start with an exhausted deadline, and retries
must consume the same budget rather than resetting it.

## 8. Wire format: ingest activation and result API

Confirmed by Claude (controller lead) for both halves to build against. Changes
to anything in this section need a doc commit reviewed by both leads first.

### 8.1 The stored request (`task_versions.contract_yaml`)

The external route stores the request as canonical JSON: sorted keys, no extra
whitespace, UTF-8. JSON is valid YAML 1.2, so the column's meaning is
unchanged, and the controller parses it with `json` (no YAML dependency). Its
hash is the version's `contract_hash` as usual.

```json
{"external":{"at_sha":null,"authored_by":[],"paths":null,"pr_number":102,
 "project":"agenthub","repo_location":"C:\\git\\agent-swarm",
 "repo_slug":"Decksx/agent-swarm","schema_version":1},
 "kind":"external_review","schema_version":7}
```

Field rules:
- `at_sha` is lowercase 40-hex or `null`.
- `paths` is a sorted list of unique repository-relative paths, or `null`.
- `authored_by` is a sorted subset of `anthropic`, `openai`, `google` and `human`.

The version row stores `base_sha=""` and `proof_mode="branch_only"`. The task's
`objective` column holds the operator's objective.

`task_id` must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`. It must not contain
`..` and must not end in `.lock` or `.`. That makes
`refs/swarm/external/<task_id>` a valid ref by construction; the worker still
runs `git check-ref-format`.

### 8.2 Issuance and claim

Progression issues stage `ingest` for an `EXTERNAL_PENDING` task with no live
activation. It needs the routing values `PROGRESSION_INGESTER` (the agent,
normally `claudecode`) and `PROGRESSION_HOST`. The activation carries:

| Column | Value |
| --- | --- |
| `role` | `operator` |
| `stage` | `ingest` |
| `expected_branch` | `refs/swarm/external/<task_id>` (the pin ref) |
| `expected_candidate` | the request's `at_sha`, or `null` |
| `expected_parent` | `null` |
| `repo_location` | the request's `repo_location` |

Issuing applies `ingest_activation_issued` (`EXTERNAL_PENDING` →
`EXTERNAL_INGEST_ASSIGNED`). Claiming applies `activation_claimed`
(→ `EXTERNAL_INGESTING`).

The worker claims with `stages` including `"ingest"`; it is a model-free stage
(`MODEL_FREE_STAGES`). `POST /controller/activations/claim` returns the usual
fields, plus one object that only ingest activations get:

```json
{
  "activation_id": "…", "task_id": "EXT-123", "task_version": 1,
  "role": "operator", "stage": "ingest",
  "expected_branch": "refs/swarm/external/EXT-123",
  "expected_candidate": null, "expected_parent": null,
  "repo_location": "C:\\git\\agent-swarm", "operator_context": null,
  "lease_seconds_remaining": 900.0, "hard_deadline_seconds_remaining": 1800.0,
  "server_seq": 1,
  "external": {
    "schema_version": 1, "project": "agenthub",
    "repo_location": "C:\\git\\agent-swarm", "repo_slug": "Decksx/agent-swarm",
    "pr_number": 102, "at_sha": null, "paths": null,
    "pin_ref": "refs/swarm/external/EXT-123",
    "scratch_ref_prefix": "refs/swarm/ingest-tmp/EXT-123/<activation_id>",
    "reclaimable_scratch_prefixes": [
      "refs/swarm/ingest-tmp/EXT-123/<earlier activation_id>"
    ]
  }
}
```

**Deleting old scratch refs.** The controller decides which scratch refs are
safe to delete, because only it knows which activations are dead.

At claim time it computes `reclaimable_scratch_prefixes`: one prefix for every
other `ingest` activation of the same task whose status is not live (`DONE`,
`EXPIRED`, `ABANDONED`). Only one ingest activation per task can be live, and
the caller holds it, so every listed activation is dead and can no longer have
a result accepted.

The worker may delete only:
- refs under one of those exact prefixes, plus a `/`;
- refs under its own `scratch_ref_prefix`, once it is done with them.

Each delete is `git update-ref -d <ref> <old-sha>`, using the SHA read by
`git for-each-ref` immediately before. If the ref moved in the meantime, the
delete fails and the ref is left alone. The worker never deletes:
- the pin;
- another task's refs;
- any ref under `refs/swarm/ingest-tmp/<task_id>/` that is not under a listed
  prefix.

Cleanup is best effort. A failed scratch delete is logged and never changes the
outcome the worker reports.

- **`external` is the worker's only input.** It is parsed from the stored
  request, never from the PR or from chat. The worker must not parse
  `task_record.contract_yaml` itself.
- **Check the state before any `gh` or `git`.** The worker proceeds only if the
  fetched `task_record.state` is `EXTERNAL_INGESTING`. Otherwise it reports
  `blocked` with `worker_error`, as the integrator does for `INTEGRATING`.
- **Liveness.** Keep the lease alive with the existing
  `POST /controller/activations/{id}/heartbeat`.

### 8.3 Result route

`POST /controller/activations/{activation_id}/ingest`. It is authenticated as
the activation's agent; the body is
`{"outcome": "...", "payload": {...}, "expected_state_seq": <optional int>}`.
It follows the same discipline as `/integration`:
- the caller and the live lease are checked first;
- a submission against a non-ingest activation is refused (403);
- an identical replay returns the cached response; a different second result
  is refused (409).

| `outcome` | Event | From → to |
| --- | --- | --- |
| `registered` | `external_candidate_registered` | `EXTERNAL_INGESTING` → `READY_EXTERNAL_REVIEW` |
| `refused` | `external_ingest_refused` | `EXTERNAL_INGESTING` → `FAILED` |
| `blocked` | `environment_defect` | `EXTERNAL_INGESTING` → `EXTERNAL_INGEST_BLOCKED` |

All three events are applied with controller authority. The generic
`/activations/{id}/result` route cannot produce any of them: with OPERATOR
authority, its only possible effect in an external state is the claim, and
tests pin that.

**A payload that fails validation gets `422 ingest_report_invalid`.** The
activation stays live and nothing is recorded. The worker should fix the report
or report `blocked`/`refused` instead; it must not resend an invalid report
unchanged.

### 8.4 `registered` payload

Every key below is required. Unknown keys are refused.

| Key | Type and rule (checked by the controller) |
| --- | --- |
| `schema_version` | `1` |
| `project`, `repo_location` | exactly equal to the stored request |
| `repo_slug` | equal to the stored slug, case-insensitively |
| `repo_id` | lowercase 16-hex: the matching `repos.json` entry's `repo_id`. Recorded as worker-reported provenance; the controller checks the format only, because it holds no trusted copy |
| `pr_number` | int, equal to the stored request |
| `pr_url` | `https://github.com/<stored slug>/pull/<pr_number>`; slug compared case-insensitively |
| `pr_state` | `open`, `closed` or `merged`, as reported by `gh` |
| `pr_draft` | bool, as reported by `gh` |
| `pr_title` | string, at most 1,024 characters, as reported by `gh` |
| `pr_body` | string, at most 65,536 UTF-8 bytes. If the PR body is longer, cut it at a character boundary and set `pr_body_truncated` |
| `pr_body_truncated` | bool |
| `pr_body_sha256` | lowercase 64-hex: SHA-256 of the **full** UTF-8 body. When `pr_body_truncated` is false, the controller checks it equals the SHA-256 of `pr_body` |
| `head_sha` | lowercase 40-hex: `headRefOid` from `gh` |
| `resolved_ref_sha` | lowercase 40-hex, the fetched scratch object; must equal `head_sha` |
| `base_ref_sha` | lowercase 40-hex: `baseRefOid` from `gh`, fetched by SHA |
| `merge_base` | lowercase 40-hex, must differ from `head_sha` |
| `pin_ref` | exactly `refs/swarm/external/<task_id>` |
| `pin_created` | bool: `true` if this attempt created the pin, `false` if an identical one existed |
| `changed_files` | non-empty, sorted, unique list of repository-relative paths, from `git diff --name-only <merge_base> <head_sha>`; no leading `/`, no `..` segment, each at most 4,096 characters |
| `author_signals` | list of at most 500 items `{"kind","value","source"}` (see below) |

`author_signals` items:
- `kind` is one of `co_authored_by`, `commit_author_email` or `pr_body_footer`.
- `value` is raw text of at most 512 characters.
- `source` is `commit:<40-hex>` or `pr_body`.

These are claims recorded verbatim. #93 maps them to model families.

**The PR title and body are untrusted.** They are written by the party being
reviewed, and they are kept so the offline reviewer can read them; #70 makes
the reviewer unable to call `gh`. The review packet (#93/#94) must show them
fenced and labelled as the author's claims, never as the objective or as
instructions (design §5). A truncated body must say that it is truncated.

Further checks:
- If the stored `at_sha` is set, `head_sha` must equal it.
- The whole payload, as canonical JSON, must be at most 131,072 bytes.
  Otherwise the worker reports `refused` with `evidence_too_large`.

### 8.5 `refused` and `blocked` payloads

```json
{"schema_version": 1, "reason_code": "head_moved",
 "detail": "<sanitized, at most 2,000 characters>",
 "observed": {"head_sha": "…", "resolved_ref_sha": "…"}}
```

`observed` only ever holds lowercase 40-hex values under these keys: `head_sha`,
`resolved_ref_sha`, `base_ref_sha`, `existing_pin_sha` and `at_sha`. `detail`
never contains raw `gh` or `git` stderr.

`refused` reason codes and what each must carry in `observed`:

| `reason_code` | Required in `observed` | Controller check |
| --- | --- | --- |
| `pr_not_found` | none | none |
| `head_moved` | `head_sha`, `resolved_ref_sha` | the two must differ |
| `at_sha_mismatch` | `head_sha` | the stored `at_sha` must be set and differ |
| `pin_conflict` | `head_sha`, `existing_pin_sha` | the two must differ |
| `no_merge_base` | `head_sha`, `base_ref_sha` | none |
| `empty_range` | `head_sha` | none |
| `evidence_too_large` | `head_sha` | none |

`blocked` reason codes, with `observed` optional:
- `github_unreachable`
- `gh_auth`
- `gh_error`
- `git_fetch_failed`
- `object_missing`
- `repo_unusable`
- `repo_slug_mismatch`
- `slug_not_configured`
- `deadline_exhausted`
- `worker_error`

An unknown reason code under either outcome gets 422. A failure the worker
cannot classify is `blocked` with `worker_error`, never `refused`.

### 8.6 Client

The worker side adds `controller_client.report_ingest(activation_id, *, outcome,
payload)`. It posts to the route above, using the same `_submit` retry and
idempotency discipline as `report_integration`.

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
ingest exclusion from any execution lane. Cover disabled/malformed repo-slug
configuration without controller startup failure, projects missing from either
map, case-insensitive slug matching, repairable slug mismatches, configuration
presence reporting, and merged PRs whose base object must first be fetched.
