# MVP-2 — ChatGPT authored, Gemini reviewed

2026-09-09. The second agent pair, and the first change authored by a model
with no shell.

**Final state `READY_INTEGRATION`. Nothing merged.** `main` in the ChatGPT
scratch repository is still at the seed commit, `task/MVP-2` is not merged into
it, and the repository has no remote.

---

## The ledger

```text
seq=15  author_activation_issued       READY_AUTHOR -> AUTHOR_ASSIGNED   actor=controller authority=controller
seq=16  activation_claimed             AUTHOR_ASSIGNED -> AUTHORING      actor=chatgpt    authority=author
seq=17  candidate_submitted            AUTHORING -> READY_REVIEW         actor=chatgpt    authority=author
seq=18  review_activation_issued       READY_REVIEW -> REVIEW_ASSIGNED   actor=controller authority=controller
seq=19  activation_claimed             REVIEW_ASSIGNED -> REVIEWING      actor=gemini     authority=verifier
seq=20  environment_defect             REVIEWING -> REVIEW_BLOCKED       actor=gemini     authority=controller
seq=21  environment_repaired           REVIEW_BLOCKED -> READY_REVIEW    actor=admin      authority=controller
seq=22  review_activation_issued       READY_REVIEW -> REVIEW_ASSIGNED   actor=controller authority=controller
seq=23  activation_claimed             REVIEW_ASSIGNED -> REVIEWING      actor=gemini     authority=verifier
seq=24  review_requirements_satisfied  REVIEWING -> READY_INTEGRATION    actor=gemini     authority=controller
```

Two different agents, neither of which chose its own work or its own verdict.

## Authoring without a shell

ChatGPT has no shell, so authoring splits: the model supplies file contents and
the worker applies them. `authored_change` parses a fixed block format,
validates every path against the repository root, writes, and commits on a new
task branch.

The split is the security property. There is no path by which the model runs
anything; what it returns is text, and the only thing done with that text is
writing files whose paths were checked first — refused rather than sanitised,
and checked by resolving against the root rather than by scanning for `..`.

```text
AUTHORING activation 8b2f02e0... for task MVP-2
COMPLETED activation 8b2f02e0...: task/MVP-2 at 29b05f28d19d (1 file(s)) in 3.1s
```

The file it produced, exactly as specified:

```markdown
# MVP-2

This file was authored by ChatGPT through the controller.
```

## The review

```text
REVIEWING activation 90bb905f...: task/MVP-2  521ab9ae65b7..29b05f28d19d, 1 file(s)
VERDICT   satisfied in 3.0s
RATIONALE The diff creates `notes/chatgpt-mvp2.md` containing exactly the
          requested three lines: a level-1 heading reading `# MVP-2`, a blank
          line, and the sentence "This file was authored by ChatGPT through
          the controller".
```

Bounded by the immutable range `521ab9ae65b7..29b05f28d19d`, not by the branch.

## Acceptance conditions, measured

| Condition | Evidence |
| --- | --- |
| One activation, one claim | `attempt_no=1`; one `activation_claimed` per stage |
| One ChatGPT model call | One `AUTHORING` line all day |
| One Gemini model call | One `REVIEWING` line for this activation |
| One candidate commit | One commit beyond the seed on `task/MVP-2` |
| Structured branch/SHA fields | Reported as named fields by `apply_and_commit`, not parsed from prose |
| Restart does not duplicate | Stopped and restarted mid-run: `AUTHORING` count stayed 1, commit count stayed 1, `state_seq` unchanged |
| Exactly one worker | Process count checked at every step: 0 → 1 → 1 after a second start attempt → 0 |
| Unmerged at `READY_INTEGRATION` | `main` at `521ab9a`, `task/MVP-2` at `29b05f2`, not merged, no remote |

## Seq 20 was a stale deployment, and it is left in the record

The first review activation was issued against a controller that did not yet
have the issuance guard. The API silently dropped the `repo_location` field it
did not know about, `_review_evidence` was not deployed to reject the result,
and the activation went out carrying no base and no candidate.

**The worker caught it anyway.** Gemini claimed it, found no range, and blocked
without calling the model — the same refusal that caught my hand-issued mistake
on MVP-1, from a different cause. The guard chain held at the layer that was
current even though the layer that should have caught it first was not.

The lesson is about deployment discipline rather than design: I ran a live test
against a controller several commits behind the code I had just written and
tested. The fix was to deploy the whole controller, which also exercised the
v1→v2 migration on live data — schema stamped 2, MVP-1 still at
`READY_INTEGRATION`, MVP-2 still at `REVIEW_BLOCKED`, nothing lost. A backup of
`controller.db` was taken first.

After deploying, the guard was confirmed working against the live hub:

```text
$ controller_admin.py issue MVP-2 gemini OFFICEPC review --expected-branch task/MVP-2
HTTP 400
  "detail": "a review activation needs repo_location; refusing to issue one a
             reviewer could not act on"
```

Refused before anything was claimed, which is the whole point of moving the
check to issue time.

## What is still not proven

`CHANGES_REQUESTED` has still not been exercised end to end. Both demonstration
tasks were correct and both were approved. It remains unit-tested only, and
should be demonstrated before the swarm is pointed at a real ComicAutomation
milestone.
