# The `evidence/mvp-demo/*` branches

These four refs share **no ancestor** with `main`. They are the complete
history of a separate git repository, pushed into this remote so it survives in
one place rather than on one machine.

Do not merge them. Do not delete them. This file exists because a namespace of
branches that connect to nothing is exactly the thing somebody tidies away
later, correctly reasoning that it looks like a mistake.

## What they are

`greeting` is a throwaway repository created on 2026-09-10 as the target for
the MVP3 rejection cycle — the run that took a task from authored candidate
through review rejection, retry authorisation, correction, and approval. It was
created to be written to badly, by design. Nothing production ever pointed at
it.

The write-up is [`MVP3_REVIEW_CYCLE.md`](MVP3_REVIEW_CYCLE.md), and everything
it cites is in these branches. A write-up whose evidence has been tidied away
is a claim.

| ref | SHA | what it is |
|---|---|---|
| `evidence/mvp-demo/master` | `451d4c43996d429108082af0d2b46f4b96805f1a` | the baseline both tasks branched from |
| `evidence/mvp-demo/task/DEMO-1-a1` | `6cc74999a90d95780c3f662d68c382613a8f1d07` | DEMO-1, approved on the first attempt |
| `evidence/mvp-demo/task/DEMO-2-a1` | `7d4c4f8df1940484bb96c917a6cc667c6a0ebae7` | **DEMO-2, the rejected candidate** |
| `evidence/mvp-demo/task/DEMO-2-a2` | `b0a7360426bf512d7ce00e9acabb259734e50a72` | DEMO-2, the approved correction |

## Why the rejected one matters most

`task/DEMO-2-a1` is the branch most likely to be deleted, because it is the one
that is obviously wrong. That is the reason to keep it.

The task was to reword a single sentence in `README.md` and preserve every
other line. The author replaced the entire file with a plausible README for a
different project — a table of contents, an installation section, directories
that do not exist, a hackathon in 2020, an MIT licence. Gemini rejected it in
one call.

Without that branch, the rejection is a paragraph in a document and the review
that produced it cannot be checked by anyone who was not there. It is the diff
the review was about.

It also explains a decision in the controller: the retry landed on `-a2` rather
than amending `-a1`. A rejected candidate is evidence for the review that
rejected it, so it is never moved or reused.

The run exposed a real harness defect, which is the other reason the branch is
worth keeping — it is the before state. The author had no shell, its prompt
carried only the objective, and the output contract requires the *complete*
contents of every file it writes. With nothing to copy from, inventing the rest
of the file was the only move available to it. The fix was to show the author
the current contents of every in-scope file, and later to add `context_paths`
for the files it must read but may not write.

## What is not here

`PRESERVE.md` and `demo_repos.json` live beside the working copy at
`C:\git\.swarm-demo\` on the operator's machine, not inside the `greeting`
repository. They are reproduced below so the meaning survives independently of
that machine.

The registry entry the run resolved through:

```json
{
  "greeting": {
    "path": "C:\\git\\.swarm-demo\\greeting",
    "repo_id": "4d49a52cb85e99fc",
    "planning_ref": "refs/heads/master",
    "worktree_root": "C:\\git\\.swarm-worktrees\\greeting",
    "plannable": false
  }
}
```

`plannable: false` closes the project to **new planning** while leaving it
resolvable for authoring and review. A planner handed that entry would see a
small, tidy, obviously-improvable repository and plan against it, and the first
new task would start moving the evidence. Deleting the entry would also stop a
planner — and would take the only statement of which checkout the evidence was
produced against with it. See `repo_registry.NotPlannable`.

## When these may be removed

At Phase 1 sign-off, by a person, deliberately. Not before, and not as part of
cleaning up after a later run.
