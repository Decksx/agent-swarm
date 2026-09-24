# Design: reviewing a change the swarm did not author (#74)

**Status:** proposed. Review this document the way code is reviewed: a verdict names the exact commit, and a new commit voids it.

**Decided by the operator before drafting (2026-09-24):** verdict-only first; a parallel state chain rather than a route into integration; the objective is stated by the operator; the candidate is fetched once, at submission; review routing must not let a model grade its own work. Each is written up below with its reasoning, so that a reviewer can disagree with the reasoning and not only with the conclusion.

---

## 1. The problem

The pipeline can review only what it authored. A review activation needs a task in `READY_REVIEW`, and the only ways in are `candidate_submitted` (AUTHOR authority) and `return_to_review` (an operator's answer to an existing escalation). A commit a person wrote, or one Claude Code wrote out-of-band, has no route to a reviewer. The only way to force one would be to emit `candidate_submitted` claiming a worker authored it, which writes a false statement into the ledger.

The consequence is #58. Every merge to `main` since 2026-09-15 that did not come through `@swarm` was approved by a **relayed** verdict: a person read a review packet and pasted "PASS at `<sha>`" into a PR comment. At the time of writing that is `a3e9537`, `206fce8`, `74dfaef`, `40291d8`, `1352362`, `27b49ab` and `c93601b`. None of them has a review activation or a recorded judgment. The ledger cannot answer "who reviewed this, at which SHA, and what did they say" for the changes that built the system itself.

## 2. Goal and non-goals

**Goal.** An operator can say, in the hub chat, "review PR #N against this objective". The swarm then pins the exact head SHA, has a reviewer of a different model family from the PR's authors judge it, and records the verdict in the ledger against that SHA. The verdict is posted to the room and to the PR.

**Non-goals, for this design:**

- **Merging.** Nothing in this design merges an external PR. See §3.
- **Third-party or untrusted code.** The PRs in scope are this project's own: written by the operator or by an agent the operator directed. This is not a defence against a hostile contributor.
- **Replacing CI.** The verdict is a review judgment, not a test result. CI still runs on the PR as it does today.
- **Reviewing arbitrary commits that have no PR.** A pull request is the unit here, because it is what a person merges and where the verdict is read.

## 3. Decision 1: verdict-only (DECIDED)

**The swarm judges; a person merges.**

External review ends in a verdict and never reaches `READY_INTEGRATION`.

- **Trust has to be earned on this input.** The integrator was built for candidates the swarm produced: one commit on a controller-named branch, from a controller-pinned base, inside a contract's allowed paths. Human PRs break every one of those assumptions: many commits, merge commits inside the branch, a base that has moved, work-in-progress CI, files outside any contract. Letting the integrator loose on them would be the first time it saw such input, and the first time would be live.
- **It solves #58 on its own.** The provenance gap is about the *verdict*, not the merge. A ledger-native verdict at an exact SHA is exactly what the relayed comments lack.
- **The decision is reversible.** Opening a door into integration later is additive: one transition, gated by its own review. Closing a door that was opened too early means unpicking merges.

What the person does with a PASS is unchanged from today: merge with `gh pr merge <n> --merge --match-head-commit <sha>`. The difference is that the PR comment they cite is the swarm's, and it names a ledger event rather than a pasted packet.

## 4. Decision 2: a parallel state chain (DECIDED; shape proposed)

The state table maps `(state, event)` to a next state. It does not know what kind of task it is looking at. So "external tasks never reach integration" cannot be a condition attached to the shared review states. It has to be structural: external tasks live in states from which integration is **unreachable**, and a test proves that.

### Proposed states

| State | Meaning |
| --- | --- |
| `EXTERNAL_PENDING` | Submitted; the head is being fetched and pinned by an ingest activation. |
| `READY_EXTERNAL_REVIEW` | Pinned; waiting for progression to issue a review. |
| `EXTERNAL_REVIEW_ASSIGNED` | A review activation is issued. |
| `EXTERNAL_REVIEWING` | The reviewer has claimed it. |
| `EXTERNAL_REVIEWED` | **Terminal.** A verdict is recorded. |
| `EXTERNAL_INGEST_BLOCKED` | The ingest could not be performed (environment). `repair` returns it to `EXTERNAL_PENDING`. |
| `EXTERNAL_REVIEW_BLOCKED` | The review could not be performed (environment). `repair` returns it to `READY_EXTERNAL_REVIEW`. |

### Proposed events

| From | Event | To | Authority |
| --- | --- | --- | --- |
| DRAFT | `external_review_requested` | `EXTERNAL_PENDING` | ADMIN (operator, via chat) |
| `EXTERNAL_PENDING` | `external_candidate_registered` | `READY_EXTERNAL_REVIEW` | CONTROLLER, on the ingest worker's report |
| `EXTERNAL_PENDING` | `environment_defect` | `EXTERNAL_INGEST_BLOCKED` | CONTROLLER |
| `READY_EXTERNAL_REVIEW` | `review_activation_issued` | `EXTERNAL_REVIEW_ASSIGNED` | CONTROLLER |
| `EXTERNAL_REVIEW_ASSIGNED` | `activation_claimed` | `EXTERNAL_REVIEWING` | VERIFIER |
| `EXTERNAL_REVIEWING` | `external_review_judged` | `EXTERNAL_REVIEWED` | CONTROLLER, on the reviewer's judgment |
| `EXTERNAL_REVIEWING` | `environment_defect` | `EXTERNAL_REVIEW_BLOCKED` | CONTROLLER |
| `EXTERNAL_INGEST_BLOCKED` | `environment_repaired` | `EXTERNAL_PENDING` | CONTROLLER |
| `EXTERNAL_REVIEW_BLOCKED` | `environment_repaired` | `READY_EXTERNAL_REVIEW` | CONTROLLER |
| any non-terminal | `admin_cancelled` | `CANCELLED` | ADMIN (existing, generic) |
| lease and deadline events | (as the author and review stages have them) | | |

**Two blocked states, not one.** The table maps a `(state, event)` pair to a single destination, so one blocked state could not return to two different places. Each blocked state belongs to the stage that blocked, as `AUTHOR_BLOCKED` and `REVIEW_BLOCKED` do.

**`environment_defect` clears no approval here.** It is in `engine.APPROVAL_CLEARING`, which is harmless on this path because external tasks never have an approval (below).

**One event for the verdict, not three.** `external_review_judged` carries `judgment` (`satisfied`, `changes_requested` or `decision_required`) and the rationale in its payload, and always lands in `EXTERNAL_REVIEWED`. There is no author to send back to, so `changes_requested` does not need a state of its own. It is a fact about the PR at that SHA, which the person reads and acts on.

**Why `external_candidate_registered` and not `candidate_submitted`.** The two must never be confusable in the ledger. `candidate_submitted` means "an author the controller activated produced this". The new event means "the operator asked for this commit to be reviewed, and a worker verified it exists at this SHA". A reader must be able to tell those apart for as long as the ledger exists. That is the reason #74 was refused a shortcut.

**Invariant, enforced by a test over the transition table:** from any `EXTERNAL_*` state, no sequence of transitions reaches `READY_INTEGRATION`, `INTEGRATING`, `INTEGRATION_*` or `COMPLETE`. The test walks the graph rather than listing edges, so a future transition that opens a path is caught even if nobody thought to mention it.

**Approval columns.** `approved_candidate_sha` is not written for external tasks. The verdict lives in the event, which is where a relayed verdict never lived. Leaving the column empty is itself a guard, because progression will not issue an integrate stage without it.

## 5. Decision 3: the objective is stated by the operator (DECIDED)

The reviewer judges a diff against an objective and acceptance criteria (`review_packet.build`). A human PR has neither in the ledger.

| Option | Weakness |
| --- | --- |
| Use the PR description | Written by the PR's author: the reviewer would be told what to look for by the party being reviewed. |
| Contractless review | The verdict becomes "looks reasonable", which is weaker than what the pipeline gives its own candidates. |
| **Operator states it** | Costs the operator one line; the question stays theirs. **Chosen.** |

The PR title and description are still **shown** to the reviewer, labelled as the author's claims, because they are useful context. They are never presented as the objective.

**Paths.** `paths:` is optional. When given, a change outside it is grounds for `changes_requested`, as it is for swarm tasks. When omitted, the contract records the PR's changed files at pin time as the scope. That describes the PR rather than constraining it, and the verdict payload says so.

## 6. Decision 4: fetch once, at submission (DECIDED; answers #69 for this path)

The reviewer stays exactly as #70 left it: it runs offline under `GIT_NO_LAZY_FETCH`, reads only the repository the activation names, and refuses if the pinned commit is absent. It never fetches.

The fetch happens earlier, in a separate **ingest** activation, and follows #69's own conditions:

1. Ask GitHub for the PR's `headRefOid` and `baseRefOid` (`gh pr view <n> --json`).
2. `git fetch origin refs/pull/<n>/head:refs/swarm/external/<task_id>` into the named repository, which is a namespaced ref rather than a branch.
3. **Verify the fetched object equals `headRefOid`.** If it does not, the PR moved during the fetch: refuse and record both SHAs.
4. If the operator named a SHA in the command, **verify it equals `headRefOid`**. This protects "review what I looked at" from a push landing between reading and submitting.
5. Compute the review range: `expected_parent = merge-base(baseRefOid, head)`, i.e. GitHub's three-dot diff, so a base branch that moved on does not put other people's commits into the reviewed diff.
6. Report `{head_sha, base_ref_sha, merge_base, changed_files, pr_number, pr_url, author_signals}`. The controller applies `external_candidate_registered` with that as evidence.

`refs/swarm/external/<task_id>` is kept until the task is terminal and then deleted by the ingest worker on its next pass. It exists so the object cannot be garbage-collected between pinning and review.

Failures follow #78's rule. "The PR does not exist" and "the PR moved" are **refusals**. "GitHub could not be reached" and "git fetch failed" are **environment defects** (`EXTERNAL_INGEST_BLOCKED`, repairable). They are never recorded as a judgment on the PR.

**Which worker ingests.** `claudecode`: it already has `gh`, a checkout, and the integrator's network access. Ingest is a new stage (`ingest`) with a new role, which the `claudecode` worker learns to claim. It is not an integrate activation in disguise.

## 7. Decision 5: a model does not grade its own work (PROPOSED)

Most out-of-band PRs so far were written by Claude Code. The configured verifier today is Gemini, which is a different family, but that is an accident of configuration and not a rule. This design makes it a rule.

**Author signals, gathered at ingest and recorded in the evidence:**

- `Co-Authored-By:` trailers on every commit in the range (for example `Claude … <noreply@anthropic.com>`);
- known agent footers in the PR body (for example `Generated with [Claude Code]`);
- commit author emails.

These map to families by a table: `anthropic`, `openai`, `google`, `human`. An unknown signal is recorded verbatim and maps to nothing. The operator may also state `authored-by:` in the command, and the stated and detected families are **unioned**, never replaced. A human saying "I wrote this" does not erase a trailer that says otherwise.

**Routing rule, at issue time (progression):** the verifier's family must not be in the PR's author families. If the configured verifier conflicts, try the next eligible verifier in a configured order. If none is eligible, **do not issue**: the task is a persistent decline under #77 (`reason_code: no_eligible_verifier`), announced once in the room. The operator can then cancel it, or add a verifier.

Today that means a Claude-written PR is reviewed by Gemini, and a Gemini-written PR has no eligible verifier until a second reviewing worker exists. That is deliberate: better an announced "nobody can review this fairly" than a quiet self-review.

**What this does not catch.** A person pasting model output without a trailer is invisible to it. The rule is about honest provenance on the project's own PRs, not adversarial detection (§2).

## 8. The operator's command

```
@swarm review #<pr> [at <sha>]
authored-by: <family>[, <family>]     (optional)
paths: <paths>                         (optional)

<objective, after a blank line>
```

It goes through the same draft → `@swarm confirm CMD-<id>` step as a task, so nothing is fetched or issued until the operator confirms. The draft shows the PR's current head, its title, and which verifier the routing rule would pick.

## 9. Where the verdict appears

- **Ledger:** `external_review_judged`, with `{judgment, rationale, head_sha, merge_base, pr_number, verifier, verifier_family, author_families}`.
- **Room:** the narrator's existing line for the event.
- **The PR:** a comment posted by the ingest worker once the task is `EXTERNAL_REVIEWED`. It names the SHA, the judgment, the rationale, the verifier and the ledger event id, with a marker so it is posted once. The integrator does not post it: nothing on the integrate path is involved at all.

A verdict is void if the PR's head moves. The PR comment says so, and a new `@swarm review` of the same PR at a new SHA creates a **new task**. The old task keeps its verdict for its SHA; it is not rewritten.

## 10. Slices

Each slice is its own issue and PR, with an exact-SHA verdict, mutation-tested guards, and a gated deploy.

1. **State machine and ledger events.** Add the new states, events and authorities, plus the unreachability test (§4). Controller only; nothing can enter the new states yet.
2. **Ingest.** The `ingest` stage and the `claudecode` claim, the fetch-and-pin procedure (§6), `external_candidate_registered`, `EXTERNAL_INGEST_BLOCKED` and its repair. Driven by the admin API, with no chat command yet.
3. **Chat command and routing.** `@swarm review` with draft and confirm (§8), progression issuing external reviews, author signals and the routing rule (§7), and the `no_eligible_verifier` decline.
4. **Verdict publication.** The reviewer's judgment mapped to `external_review_judged`, the PR comment, and the ref cleanup.
5. **First use.** Review an open out-of-band PR with it, and merge only on its verdict. From that PR on, "relayed verdict" stops appearing in merge records.

The first two slices are the largest.

## 11. Open questions for the reviewer

1. **Re-review:** a new task per SHA (proposed), or a new version of the same task? A new task keeps each verdict tied to exactly one SHA. A new version keeps a PR's history in one place.
2. **`decision_required`:** land in `EXTERNAL_REVIEWED` like the other judgments (proposed), or in `NEEDS_HUMAN` as it does for swarm tasks? There is no author to unblock, so `NEEDS_HUMAN` would add a state with no exit that means anything.
3. **Budget:** should repeated external reviews of the same PR be counted against a limit, as author attempts are? This design proposes none, because each review is operator-initiated.
4. **Should Claude Code's out-of-band PRs be allowed to skip the swarm review once this exists?** This design assumes not: from slice 5 on, every merge to `main` either came through `@swarm` or carries an `external_review_judged` event. That is a policy the operator states, and the design only makes it possible.

## 12. Related

#58 (the gap this closes), #60 (swarm development bypasses the swarm), #64 and #70 (the offline reviewer this preserves), #69 (fetching, answered here for the ingest path only), #77 (how an unroutable review is surfaced), #78 (refusals versus environment defects).
