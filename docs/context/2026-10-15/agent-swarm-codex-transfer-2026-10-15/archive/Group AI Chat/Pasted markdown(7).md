54 branches besides `main`. Before deleting, I'll check whether any code or config refers to these branches by name:

Found that `evidence/mvp-demo/*` branches are intentionally kept per docs and should stay untouched, but `chatgpt_worker.py` defaults to publishing to `refs/heads/master`—I need to verify nothing live depends on that branch before touching it.

`master` is stale and fully merged into `main`, which is the branch actually used in live runs and PR #75, but since `master` still serves as a code fallback target I'll leave it untouched for now. Next, checking the docs for details on the phase branches.

The README says `phase1/mvp-slice`, `phase0/*` and `phase1/controller-core` are **retained as historical** on purpose, so those stay too. One last check on the four no-PR `feature/*` branches:

No lingering references found, so I'll delete the 37 branches fully merged into main—33 with merged PRs plus 4 unreferenced feature branches—each delete pinned to the checked SHA so any moved branch gets refused.

I deleted 36 of the 54 branches. The "can be safely deleted" banner was right for those: each one's tip is already in `main`, so no commits were lost. 32 had merged PRs, and 4 were old `feature/*` branches with no PR and no references anywhere. Each delete was tied to the SHA I checked first, so a branch that had moved since would have been refused. None were.

**17 branches kept (plus `main`):**

| Branches Why they stay                                        |                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `evidence/mvp-demo/*` (4)                                     | `docs/EVIDENCE_BRANCHES.md` says in so many words "do not delete them". They hold the evidence for the MVP3 review-cycle write-up and share no history with `main`.                                                                                                          |
| `phase0/*`, `phase1/*` (4)                                    | The README (line 200) says they're kept on purpose as historical state, and several docs name them.                                                                                                                                                                          |
| `master`                                                      | Fully in `main` and last touched 2026-09-08, but `chatgpt_worker.py:122` still uses `refs/heads/master` as its default publish target. Live runs set `main` explicitly, so deleting it probably breaks nothing, but I didn't want to change a fallback path during a deploy. |
| `docs/handoff-2026-09-22`, `task/T-ACC2-README`               | They belong to open PRs #71 and #75. #75 gets closed in step 3 of your sequence.                                                                                                                                                                                             |
| `task/T-CMD-99a5880f3e-a1…a3`, `task/T-INFRA-03/06/08-a1` (6) | Rejected candidates from closed, unmerged PRs; their commits aren't in `main`. GitHub still keeps each one under `refs/pull/N/head` (I checked #13 and #63). The ledger cites them as rejection evidence, and your #68 work is about those exact attempts.                   |

**Decision for you:** the 6 rejected-candidate branches could go too, since the PR refs would keep the commits. The evidence-branches doc, though, argues that rejected candidates are the ones most worth keeping. I'd keep them unless the clutter bothers you. I'd also delete `master` in the follow-up PR that changes that default publish target.

The acceptance run 2 sequence is still where it was: the deploy's test suite is running, and I'll pick up the restart, cancel and re-create when it finishes.

The first suite passed (1,821 tests). The hub and controller HTTP suite is running now.

Both required suites passed (1,821 + 307), and the files are being copied to Tower.

All 14 digests match on Tower, and `agent-hub` is restarting.

The hub is answering again. Waiting on the preflight parity check.

Deploy passed every gate. Next, the workers need a restart, because they still hold the old code (#73 only changed worker files). Checking what `stop` does before using it:

The restart flow is `stop` (sets a `STOPPED` marker) then `start` (clears it after a parity check), keeping `PAUSED` intact throughout. Next I'll trigger the scheduled `ensure` once to confirm it only sees one live supervisor and doesn't spawn a second.

Supervisor is up and paused, with no workers yet. Now triggering the scheduled `ensure` to confirm it doesn't start a duplicate:

Exactly one supervisor (pid 31476), and `ensure` exited 0 without starting another. Releasing the pause so the workers start on the new code:

Confirmed one supervisor and three workers are all running from C:\swarm-prod at 1352362, started post-deploy. Next, I'll cancel T-ACC2-README via the admin workflow with the reason documented.

Step 3 done. Step 4: posting the `@swarm` task as the operator. First, how an admin/operator message reaches the hub:

Ingress runs for admin senders on `POST /send`. I'll post through the same credential path `worker_ctl.sh admin` uses, so the secret never lands in a file or the transcript:

I'll write a small posting helper that reads the credential from the environment only:

Now the task message, in the §4 template, on the new `main` SHA:

The draft was accepted on the first attempt, with the right base, paths and routing (ChatGPT authors, Gemini reviews, Claude Code integrates). Confirming through chat:

This run's author activation (branch task/T-CMD-056dcdec11-a1, repo C:/git/agent-swarm) completed fully within 30 seconds—authored, submitted, auto-handed to review (seq 442, previously the stall point), and claimed by Gemini. Now opening the focused issue with the cancel seq filled in.

Issue **#77** is open. All five steps are done. Acceptance run 2 is in review now, and I'll watch it through to a final state.

I did all five steps and checked each against the live system. Acceptance run 2 got past the point where it stalled last time and is now in review.

1. **#73 merged** as `1352362`. Right before merging I rechecked it: head still `31c4cbe`, both CI checks green on that exact commit, base `40291d8` equal to current `main`. The PR comment says the approval was relayed, not recorded in the ledger (the #58 gap again), and that you changed the merge order.
2. **Deployed.** 
   - **Tests:** 1,821 + 307 passed.
   - **Tower:** all 14 file digests match.
   - **Parity:** preflight OK at build `dadbdb3a55f7`. That build id didn't change because #73 only touched worker files.
   - **Restart:** `stop` → `start` → one scheduled `ensure` run, which left exactly one supervisor running.
   - **Processes:** one supervisor and three workers, all from `C:\swarm-prod` at `1352362` and all started after the deploy. The workers were restarted because they still held the old retry code.
3. **T-ACC2-README cancelled** with `admin cancel` (seq 436). The reason names the missing `expected_branch` and `repo_location`, and neither field was patched. PR #75 is closed without merging, and its branch is kept because the ledger's seq 435 points to that commit.
4. **Run re-created through `@swarm`** on `1352362` and confirmed in chat. The controller accepted it first time as **`T-CMD-056dcdec11`**, and its author activation has `task/T-CMD-056dcdec11-a1` and `C:/git/agent-swarm`. Within 30 seconds ChatGPT had authored it, the controller sent it to review on its own (seq 442), and Gemini claimed the review.
5. **#74 doesn't cover this.** It's about reviewing changes a person wrote, not a malformed activation the controller issued. So I opened **#77**, which covers refusing author activations that have no branch or repository, and surfacing repeated skips as warnings and in the hub chat. It also asks whether ChatGPT should keep defaulting to `task/{id}` when an activation names no branch.

Nothing needed a manual repair or a direct database change.

Review is the first of the three stages this run has to get through; CI and autonomous integration by Claude Code come after it. A monitor will tell me when the task reaches `COMPLETE` or stops somewhere, and I'll report back then.

Gemini approved the change, and Claude Code has claimed the integration (seq 446). This is the first time on this deployment that a task has reached integration. Waiting for the result.

The integrator rejected the candidate. Finding out why:

The integrator says the candidate doesn't descend from `1352362`, but the candidate says its base is `1352362`. Checking the commit graph directly:

The refusal is **wrong**: `b3d7b5b`'s parent *is* `1352362`, and the diff is just the 2 README lines. So the integrator's ancestry check gave a false answer. Finding where it checks:

The integrator's ancestor check treats any non-zero git exit as "not an ancestor," but exit 128 can also mean the commit object is missing—likely why it failed here. I'll check which repo it used and whether it ever fetched the candidate commit.

Since INTEGRATION_REPO defaults to the production checkout while the author committed elsewhere, and the integrator only fetches after merging, I'll check whether that production clone actually has the candidate commit.

Confirmed: the candidate is fine — the integrator checked the wrong repo clone (the prod `$REPO` split from dev), so it never fetched the commit and a missing-object error (exit 128) got misread as a failed ancestry check. Now I need to check whether anything will automatically act on this false refusal before I stop.

The task is parked in CHANGES_REQUESTED with no active retries, and per the directive to stop and report at this point, I'm stopping the watcher.

Acceptance run 2 got through authoring, review and CI on its own, but the automatic merge wrongly rejected the change. I've stopped there as your directive says; the task is parked and nothing is running.

## What happened to T-CMD-056dcdec11

| seq Stage Result  |                           |                                                                                                                                         |
| ----------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 441               | Author (ChatGPT)          | Commit `b3d7b5b` in 5 s, PR #76                                                                                                         |
| 442–444           | Review (Gemini)           | Handed to review automatically, approved in 7 s: "adds the requested blockquote verbatim… without modifying any other existing content" |
| 445–446           | Integration (Claude Code) | Handed off automatically and claimed                                                                                                    |
| 447               | Integration               | **Rejected, 9 minutes later:** "The pinned target 1352362fe59e is not an ancestor of the candidate b3d7b5b95b1f."                       |

## The rejection is false

In git, `b3d7b5b`'s parent is `1352362`, and the diff is just the 2 README lines. The cause is yesterday's split between the production and development checkouts:

1. The integrator works in `INTEGRATION_REPO`, which defaults to the directory the supervisor runs from. That is now the production checkout, `C:\swarm-prod\agent-swarm` (`swarm_ctl.sh:144`).
2. ChatGPT committed the change in `C:\git\agent-swarm`, the repository the task names. Nothing ever fetched that commit into the production checkout, where `git cat-file` returns **exit 128, object missing**.
3. `integrator.py:962` treats any non-zero exit from `merge-base --is-ancestor` as "not an ancestor". So "I don't have this commit" was recorded as "this commit is based on the wrong thing".

This is the #64 bug again, in the integration step instead of review. Review follows the repository the controller names; the integrator ignores it and uses its own setting. The split turned that from harmless to fatal: when production and development were one directory, the integrator happened to be looking in the right place.

**The ledger now holds a false entry.** seq 447 says the candidate failed an ancestry check it would have passed. I haven't touched it, and I'll record the correction in the fix PR and on the task.

## Options

- **A. Fix, then retry (recommended).** A PR that:
  - makes the integrator use the activation's `repo_location`, as #70 did for review;
  - fails closed on exit 128 with "the candidate is not present", separate from a real ancestry failure;
  - adds tests for both, mutation-tested.
  Then your merge verdict, a gated deploy, and `@swarm retry T-CMD-056dcdec11`. The retry authors a new candidate, which also exercises #73. The rejection reason ChatGPT will see is the false one, though, so it may try to "fix" a candidate that was never wrong. I'd note that in the retry.
- **B. Temporary setting, then retry.** Set `INTEGRATION_REPO=C:/git/agent-swarm`, the same kind of stopgap as the old `REVIEW_REPO`, restart, then retry. It's faster, but it's another stopgap to remember to remove, and the misread-exit-code bug stays.

Neither option edits the database. Should I go with A, starting with the PR?

The old deploy watcher has expired, which is expected: that deploy finished and was verified earlier. Nothing new has changed. I'm waiting for you to choose option A or B for the integrator fix.