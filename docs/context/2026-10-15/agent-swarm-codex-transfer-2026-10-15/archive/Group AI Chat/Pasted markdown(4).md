`controller_admin.py` has no chat command, so the ingress path needs a POST to `/send` as admin — the same secret-over-SSH pattern `worker_ctl.sh admin` uses internally. Recording your #62 refinements first, then resuming production:

The waiter already fired — three workers are up.

**Final acceptance condition met:** 1 supervisor, 3 workers, all on production paths, **0** referencing the dev checkout.

```
[PROD] pid 31180  claude_worker.py
[PROD] pid 56356  chatgpt_worker.py
[PROD] pid 56960  gemini_worker.py
[PROD] pid 58016  supervisor.py

```

Production is isolated, pinned to `206fce8`, self-healing from the right path, and now live. Issuing the README task through the chat ingress — the genuine operator path:

Message 1326 accepted. Reading the controller's reply to see what draft it created:

**Friction #1, recorded:** the ingress takes the entire message as the task title and refuses anything over 200 characters. My message was \~215. The refusal is clear and actionable — `"Not accepted: the title is longer than 200 characters"` — but it means an objective longer than a sentence cannot be expressed through the chat path at all. Retrying inside the limit:

**Friction #2:** `project:` is required, though the documented grammar in `ingress.py`'s own header says just `@swarm <title>`. Rather than guess again, reading what the parser actually requires:

Now I have the real grammar — fields each on their own line below the title. Checking the valid proof modes before sending, since a wrong one cost T-INFRA-10 an entire task:

`DEFAULT_PROOF` is already `branch_only` — the mode that works on this host. Required fields are `project`, `base`, `paths`. Sending the properly-formed draft:

**Friction #3:** the objective must follow a blank line — a shape not shown in the module's own documented grammar. Three refusals, three round trips, each message clear but none discoverable in advance. Sending the complete form:

**Friction #4:** `base:` must be a full 40-character SHA — *"the controller has no checkout and cannot resolve a branch name."* Correct, and the ledger-only invariant showing through, but the operator must resolve it themselves.

Draft created: **`CMD-99a5880f3e`**, routing `author chatgpt → review gemini → integrate claudecode`.

One line in it I want to flag before confirming, because it's load-bearing and matches your decision #2:

```
project:     agenthub (C:/git/agent-swarm)

```

The task will author against the **dev checkout** as its target repo — deliberately, per your ruling that the production clone must never become the repository agents modify. That's correct, and it means I must not touch `C:\git\agent-swarm` while this task runs. Its worktrees are cut from committed SHA `206fce8`, so my branch state can't leak into the work, but I'll leave that tree alone until the task finishes.

Confirming:

**Task** **`T-CMD-99a5880f3e`** **is live** — state `AUTHOR_ASSIGNED`, author activation `6edfe7d279f1…` issued to chatgpt. The pipeline is running on its own for the first time since Sept 15.

Watching it without intervening:

Watching. Here's the acceptance record so far, since documenting friction is half the point of this test.

## Manual interventions and friction

**Four refusals before a valid submission**, each a separate round trip:

| # Refusal Assessment  |                                                       |                                                                                                                    |
| --------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 1                     | `the title is longer than 200 characters`             | Clear. But an objective longer than a sentence can't go in the title, and nothing says so up front.                |
| 2                     | `` `project:` is required ``                          | The module's own documented grammar says `@swarm <title>`. Three fields are required and the docstring names none. |
| 3                     | `the objective is missing: add it after a blank line` | The blank-line-then-objective shape appears nowhere in the grammar.                                                |
| 4                     | `` `base:` must be a full 40-character commit SHA ``  | Correct and well-explained — the ledger-only invariant. The operator must resolve the SHA themselves.              |

Every refusal was **cheap**: validation at ingress, before any model call, with a message naming the exact problem. Nothing was spent. That's the design working. But four rounds to learn a format is the usability cliff I hypothesised from the cancellation data, and it's now reproduced rather than inferred — a first-time operator would plausibly give up around round three.

**The cheapest fix is documentation, not code:** `@swarm help` printing the full template, or the first refusal printing it. `ingress.py`'s docstring is the wrong shape — it lists commands, not the required fields.

Nothing in that list is a *ledger* intervention. I have not touched the database, the worktrees, or any process since confirming — all four failures were malformed input by me, corrected by me, through the normal chat path.

**State now:** `T-CMD-99a5880f3e`, `AUTHOR_ASSIGNED`, chatgpt holding activation `6edfe7d279f1…`. Next expected step is a claim, then a candidate. I'll report where it rests — complete, or stuck with a named reason — with the full event log either way.

Real progress, then a concrete blocker. The pipeline ran **autonomously through authoring and into review**: chatgpt claimed, produced a candidate, the controller issued the review, gemini claimed it — then reported `environment_defect`, which in this system means *"I could not review this"*, not *"this is wrong"*. Pulling the reason:

The author succeeded completely — committed `60257cce`, pushed `task/T-CMD-99a5880f3e-a1`, and **opened PR #63** — in 8.8 seconds. The reviewer then couldn't find that commit in `C:/git/agent-swarm`. Checking whether the object is actually there:

**The commit exists right now** — `git cat-file -t` says `commit`, and local branch `task/T-CMD-99a5880f3e-a1` points at it. So the reviewer's failure was not a missing object; it was a *timing* or *state* problem. Getting the timeline and the reviewer's own log:

Found it, and it's a consequence of today's isolation — not a pre-existing defect:

```
WARNING  activation 0e0ad7e5… names repo_location 'C:/git/agent-swarm' but this
         worker reviews in 'C:/swarm-prod/agent-swarm'; reviewing here and recording both
ERROR    could not build a review packet: rev-parse 60257cce…^{commit} failed (128)

```

The author worked in `C:/git/agent-swarm` (per `repos.json`, as you decided). The reviewer reviewed in `C:/swarm-prod/agent-swarm` — **its own checkout**, where that commit has never existed. It noticed the disagreement, warned, and proceeded anyway.

# Acceptance test result: the pipeline works; one defect, introduced today

**`T-CMD-99a5880f3e`** **→** **`REVIEW_BLOCKED`****.** Eight events, no manual intervention after confirm, no ledger or database edits.

```
403 contract_validated      21:34:19
404 queued                  +0.0s
405 author_activation_issued +0.0s
406 activation_claimed       +0.5s   chatgpt
407 candidate_submitted     +15.8s   chatgpt   → PR #63
408 review_activation_issued +18.3s  controller
409 activation_claimed       +1.3s   gemini
410 environment_defect       +0.2s   gemini    → REVIEW_BLOCKED

```

**Authoring worked completely, autonomously, in 16 seconds.** ChatGPT claimed the activation, edited `README.md`, committed `60257cce`, pushed `task/T-CMD-99a5880f3e-a1`, and **opened PR #63** — https\://github.com/Decksx/agent-swarm/pull/63. The controller then issued the review on its own. Every stage boundary the swarm owns worked without me.

## The blocker, and it is mine

```bash
swarm_ctl.sh:133   export REVIEW_REPO="${REVIEW_REPO:-$REPO}"

```

The reviewer's repo defaults to **the checkout it was launched from**. Before today, that was `C:/git/agent-swarm`, which is also what `repos.json` names — the two agreed by accident. Isolating production set `REVIEW_REPO=C:/swarm-prod/agent-swarm` while the author still works in the dev checkout, per your decision #2. The candidate exists in the dev repo and on GitHub; it has never existed in the production clone, so `rev-parse` failed.

**This defect did not exist yesterday. The shared checkout was masking it** — the same coupling we removed. Isolation didn't break the pipeline; it revealed that the reviewer's repo was never actually configured, only coincidentally correct.

The worker *detected* the disagreement and continued anyway:

> `names repo_location 'C:/git/agent-swarm' but this worker reviews in 'C:/swarm-prod/agent-swarm'; reviewing here and recording both`

It had the right answer in hand — the activation names the repo the controller issued against — and preferred its own env var. That's the deeper bug: a warning where a refusal or a correction belonged.

## Three fixes, and I'd pick the third

1. **Set** **`REVIEW_REPO_OVERRIDE=C:/git/agent-swarm`** when starting production. One line, works now, leaves the design flaw.
2. **Point** **`repos.json`** **at the production clone** — rejected by your decision #2, and correctly so.
3. **Make the worker honour the activation's** **`repo_location`**, falling back to `REVIEW_REPO` only when the activation names none, and *refusing* rather than warning when they conflict and the commit isn't present. The controller already pins the repo for exactly this reason.

(1) unblocks today; (3) is the real fix and belongs on the board.

Two consequences to note: `REVIEW_BLOCKED` is repairable by design — `swarm_ctl.sh`/`repair` returns it to `READY_REVIEW` once the environment is fixed, so this task is resumable, not lost. And **PR #63 is open with an unreviewed candidate**; it should not be merged on the strength of this run.

Want me to apply (1) and repair the task so the review proceeds, or file (3) first and leave the task blocked as evidence?