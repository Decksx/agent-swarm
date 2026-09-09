# MVP-1 — the first controller-driven run

2026-09-09. One task, one worker, end to end through the deployed controller.
`claude_worker` on OFFICEPC, `ACTIVATION_SOURCE=controller`, against the hub on
Tower at `b91acfa` plus `9508124`.

**This was a `branch_only` demonstration. Nothing was merged, integrated or
deployed, and the task stopped at `READY_REVIEW`.**

---

## What it proves, and what it does not

It proves the author half of the loop: a task created by the operator, claimed
by a worker over authenticated HTTP, executed by a real model with shell
access, and reported back as a candidate — with the controller's state moving
exactly once at each step.

It does **not** prove the review half. Reaching `READY_INTEGRATION` requires a
legitimate Gemini review activation and judgment, and Gemini is not converted.
Stopping at `READY_REVIEW` is the honest end of an author-only run; walking it
further by hand would have made the ledger claim a review that never happened.

## The task

Deliberately harmless, on an isolated scratch repository created for this run —
no remote, seeded with one commit, nothing else in it. Per
`docs/PHASE1_MVP_LIMITS.md`, the restart guarantee is fail-safe rather than
exactly-once, so this path takes only harmless tasks on unique per-task
branches until recovery inspects artifacts before reissuing.

> Create and check out a branch named `task/MVP-1`; append one line to
> `demo.txt`; commit it; print the branch and the full commit SHA. Do not push.
> Do not touch any other repository.

## The ledger

```text
seq=1  contract_validated        DRAFT -> VALIDATED         actor=admin      authority=controller
seq=2  queued                    VALIDATED -> READY_AUTHOR  actor=admin      authority=controller
seq=3  author_activation_issued  READY_AUTHOR -> AUTHOR_ASSIGNED  actor=controller authority=controller
seq=4  activation_claimed        AUTHOR_ASSIGNED -> AUTHORING     actor=claudecode authority=author
seq=5  candidate_submitted       AUTHORING -> READY_REVIEW        actor=claudecode authority=author
```

Five events, `state_seq=5`, final state `READY_REVIEW`.

Note seq 4 and 5: actor `claudecode`, authority `author`. The worker reported
its own work under its own role, which is what the authority column is for —
a verdict about that work would have read `authority=controller` with
`claudecode` still the actor.

## The candidate

```text
branch : task/MVP-1
sha    : 80cf8c8a9e5089085121e0e3712908162eb4276d
parent : ee07541 (seed)
remote : none configured -- nothing was pushed anywhere
```

`demo.txt` on that branch contains `MVP-1 completed`. The scratch repository's
`main` is untouched.

## Acceptance conditions, measured

| Condition | Evidence |
| --- | --- |
| Exactly one queue source | Startup logged `work from : controller` and `activations: http://192.168.42.50:8050/controller/activations/claim`. The local control directory was never read |
| One claim | One `activation_claimed` event, `seq=4`. `attempt_no=1` |
| One model invocation | One `ACCEPTED activation` and one `COMPLETED activation` line in the worker log, `exit=0 in 17.6s`. Both counts are 1 across the entire log |
| One candidate SHA | `80cf8c8a…`, one commit on `task/MVP-1` beyond the seed |
| Final state `READY_REVIEW` | `state_seq=5`, confirmed twice, before and after the restart |
| Repeated polling does not reclaim | The worker polled every 5s from 17:03:20 to the stop, finding nothing. `ACCEPTED activation` count stayed at 1 |
| Restart does not re-invoke | Stopped and restarted at 17:04:17. It resumed, polled, claimed nothing. The ledger still ends at `seq=5` and the scratch repo still has exactly one task commit |
| Clean run | Zero `WARNING` and zero `ERROR` lines dated 2026-09-09. Zero poll failures. The in-flight marker was cleared after the result was reported and absent at restart |

## Credential handling

The worker's `HUB_SECRET` was read from `hub.env` on Tower and passed directly
into the worker process's environment. It was never echoed, written to a file,
or displayed. This was a deliberate change to the arrangement held until now —
that I hold no component credential — and it was made on the operator's
explicit authorization after being put to them as a question, rather than
assumed because it was convenient.

## Reproducing

```sh
# on Tower
python3 controller_admin.py capacity OFFICEPC 1
python3 controller_admin.py create-task <id> "<title>" "<objective>" --ready
python3 controller_admin.py issue <id> claudecode OFFICEPC author
python3 controller_admin.py events <id>
```

The worker side needs `ACTIVATION_SOURCE=controller`, `HUB_SECRET` set to the
`claudecode` component secret, and `WORKSPACE` pointing at the repository the
task should be performed in.

## What is next

Convert Gemini and issue a review activation against this same task, so
`READY_REVIEW -> READY_INTEGRATION` happens through a real judgment by the
agent holding the review activation rather than by anybody's assertion. MVP-1
is deliberately left at `READY_REVIEW` to be that demonstration's input.
