# The rejection cycle, run end to end

2026-09-10. Controller build `33b5006c9707` on Tower, verified by preflight
before each worker started. Author `chatgpt` (gpt-4o), verifier `gemini`
(gemini-3.6-flash). Six model calls in total, itemised below.

Target: `greeting`, a throwaway repository registered in a demonstration
registry (`SWARM_REPOS`), never the committed `repos.json`. Nothing production
was touched.

## What was being demonstrated

That a rejected candidate can be sent back, retried under the controller's
authority, and approved on a second, separate range -- with the rejected
candidate preserved rather than moved.

## DEMO-1: the approval path

Objective: create `notes/greeting.md` with three exact lines.

| | |
|---|---|
| base | `451d4c43…`'s parent, `0abc407f63c9` |
| candidate | `6cc74999a90d` on `task/DEMO-1-a1` |
| author calls | 1 |
| review calls | 1 |
| verdict | `satisfied` in 2.1s |
| final state | `READY_INTEGRATION` |

The author produced exactly the three lines requested. The worktree was created
detached at the baseline, the commit landed on its own branch, and the worktree
was removed once the commit existed.

## DEMO-2: the rejection cycle

Objective: reword one sentence in the existing `README.md`, preserving every
other line.

### Attempt 1 — rejected

`task/DEMO-2-a1` at `7d4c4f8df194`, one author call.

The author replaced the entire README with a plausible one for a different
project: a table of contents, an installation section, `src/` and `tests/`
directories that do not exist, a hackathon in 2020, an MIT licence. Every line
it had been told to preserve was gone.

Gemini, one call, 2.6s:

> The diff completely replaces the original README content with new boilerplate
> text, violating all acceptance criteria. The original lines and section
> contents under "## Layout" and "## Provenance" were destroyed.

`REVIEWING -> CHANGES_REQUESTED`, authority `controller`, actor `gemini`.

**This was not a bad model. It was a harness defect the run exposed.** The
author has no shell, its prompt carried only the objective, and the output
format requires the *complete* contents of every file it writes. With nothing
to copy from, inventing the rest of the file was the only move available to it.

Fixed before the retry: the prompt now carries the current content of every
in-scope file, read from the base commit. See `authored_change.existing_in_scope`.
A file too large to show in full is flagged, and the author is told to answer
`CANNOT_AUTHOR` rather than rewrite it -- half a file reads as a whole file.

### Retry authorisation

`worker_ctl.sh admin retry DEMO-2` -> `CHANGES_REQUESTED -> READY_AUTHOR`,
authority `controller`, one author attempt spent of three.

The operator asks; the controller decides. `retry_authorized` is a
controller-authority transition and cannot be applied through the admin
transition route, so an operator cannot keep buying attempts past the point
where the loop itself is the problem.

### Attempt 2 — approved

`task/DEMO-2-a2` at `b0a7360426bf`, one author call, from the same base
`451d4c43996d`. The prompt carried the reviewer's rationale verbatim and the
README's actual contents. The diff:

```diff
-A throwaway repository for exercising the review loop.
+A throwaway repository for exercising the review loop end to end.
```

Gemini, one call, 3.7s: `satisfied`. `REVIEWING -> READY_INTEGRATION`.

## The ledger

```text
seq=33  contract_validated             DRAFT             -> VALIDATED         admin      controller
seq=34  queued                         VALIDATED         -> READY_AUTHOR      admin      controller
seq=35  author_activation_issued       READY_AUTHOR      -> AUTHOR_ASSIGNED   controller controller
seq=36  activation_claimed             AUTHOR_ASSIGNED   -> AUTHORING         chatgpt    author
seq=37  candidate_submitted            AUTHORING         -> READY_REVIEW      chatgpt    author
seq=38  review_activation_issued       READY_REVIEW      -> REVIEW_ASSIGNED   controller controller
seq=39  activation_claimed             REVIEW_ASSIGNED   -> REVIEWING         gemini     verifier
seq=40  author_defect                  REVIEWING         -> CHANGES_REQUESTED gemini     controller
seq=41  retry_authorized               CHANGES_REQUESTED -> READY_AUTHOR      admin      controller
seq=42  author_activation_issued       READY_AUTHOR      -> AUTHOR_ASSIGNED   controller controller
seq=43  activation_claimed             AUTHOR_ASSIGNED   -> AUTHORING         chatgpt    author
seq=44  candidate_submitted            AUTHORING         -> READY_REVIEW      chatgpt    author
seq=45  review_activation_issued       READY_REVIEW      -> REVIEW_ASSIGNED   controller controller
seq=46  activation_claimed             REVIEW_ASSIGNED   -> REVIEWING         gemini     verifier
seq=47  review_requirements_satisfied  REVIEWING         -> READY_INTEGRATION gemini     controller
```

`authority` is not decoration. A review judgment is applied with controller
authority on behalf of the verifier holding the activation, so the log shows
both who judged and what permitted the move.

## Model calls

| stage | activation | calls |
|---|---|---|
| DEMO-1 author | `7be3513a` | 1 |
| DEMO-1 review | `1a442601` | 1 |
| DEMO-2 author, attempt 1 | `2d252b6d` | 1 |
| DEMO-2 review, attempt 1 | `992c4f1a` | 1 |
| DEMO-2 author, attempt 2 | `252221e5` | 1 |
| DEMO-2 review, attempt 2 | `7e539435` | 1 |

Six calls, six activations, one call each. No activation made two.

## What the run leaves behind

Three candidate branches, including the rejected `task/DEMO-2-a1`. It is the
evidence for the review that rejected it and is never moved or reused -- which
is why the retry landed on `-a2` rather than amending.

No worktrees: each was removed once its commit existed. The canonical checkout
was never written to at any point; it was read for the review and nothing else.

## What this did not demonstrate

- Integration. `READY_INTEGRATION` is where both tasks stopped; nothing was
  merged.
- The attempt budget reaching `NEEDS_HUMAN`. It is tested, not run live.
- A task against a repository anyone depends on. `greeting` was created for
  this and can be deleted.
