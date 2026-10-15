All three are right. The 401 correction especially — I built exactly the failure mode I'd flagged in the launcher: a worker that looks alive and cannot work.

Now the worker side: exit on a fatal auth failure, and honour a 429 interval.

Correction 3 — the restart guarantee. My comment claimed more than the mechanism delivers.

Now the bypass rows — proving the new guards are load-bearing before deploying.

The matrix corrected me three times — my expected-failure sets were wrong, not the guards. Those three tests exercise the *worker's* handling, not the client's classification, so they need their own rows.

The bypass hung the run — swallowing a fatal error makes the worker spin forever, which is the failure itself but useless as a test signal. Making it exit with the wrong code instead, and bounding the test's sleep so a regression can never hang the suite.

The 10-minute timeout killed the matrix mid-run — its `finally` restore may not have completed. Checking for a sabotaged file on disk.

The killed matrix left `claude_worker.py` sabotaged — its `finally` never ran, because a hard kill doesn't run `finally`. The docstring's claim that an interrupted run leaves nothing behind is false.

Matrix running in the background. While it does, let me note what it already caught — it's now corrected me five times across this project.

Still running — I'll report where things stand and pick up when it lands.

## The three corrections are in

**Auth failures are now fatal, not slow.** I'd built exactly the failure I flagged in the launcher: a 401 backing off to a cap produces a worker that's alive, logging, and structurally incapable of work. It now raises, and `claude_worker` exits **4** — distinct from 127 (missing binary), 3 (bad source), 2 (chat made authoritative), because only one of those is fixed by editing the launcher's environment.

I split the 403 case rather than treating it as one thing: **403 on the claim route is fatal** (no activation is named — the component may not take work at all), **403 on a result route is not** (it names an activation, means "not yours", and clears on the next claim). Killing a worker over a stale lease would turn a recoverable condition into an outage.

**429 honours** **`Retry-After`**, falling back to 30s when absent. The worker paces its next poll by the longest of the server's interval, the outage backoff, and the ordinary cadence — so a throttle during an outage respects whichever asked for more. Network/5xx keep bounded backoff; an empty queue keeps normal cadence.

**Restart is described as fail-safe, not exactly-once.** You're right and my comment overclaimed. It protects the *controller's* state — no result invented for a run nobody observed. It cannot protect the repository: `claude -p` has Bash, may have committed before the crash, and a replacement activation runs the same task again on top of that. Recorded in `docs/PHASE1_MVP_LIMITS.md` with the constraint it forces — harmless tasks, unique per-task branches, nothing production-changing until recovery inspects artifacts — alongside the six other accepted deferrals.

Live-run target corrected to **`READY_REVIEW`**. Reaching `READY_INTEGRATION` needs a real Gemini review activation, and the state machine enforces that anyway.

**200 tests** in `tests/` (was 192).

## The matrix corrected me three more times

My first three bypass rows reported NOT LOAD-BEARING. The expected-failure sets were wrong, not the guards: those tests drive a stub queue directly, so they guard **`claude_worker`****'s handling**, not `controller_client`'s classification. Split into separate client-side and worker-side rows — better coverage than I'd have written unprompted.

Then a fourth correction, worse. My worker-side bypass swallowed the fatal exception, which makes the worker **poll forever** — the real failure, but it hung the matrix for ten minutes instead of failing a named test. Rewritten to erase the exit code instead.

## A real defect in the matrix itself

The 10-minute timeout **killed the run mid-bypass and left** **`claude_worker.py`** **sabotaged on disk.** `finally` does not run when a process is killed. The docstring's claim — *"Files are restored in a* *`finally`**, so an interrupted run does not leave a sabotaged worker on disk"* — was false, and the next test run failed for a reason unrelated to what I was testing.

Restored from git, then fixed properly: the matrix now writes a sidecar recording the file and its original contents *before* touching it, and clears it only after a verified restore. A later run finds the sidecar, restores from it, and says so loudly. Proven by simulating a killed run — sabotage detected, file restored byte-identical, sidecar cleared.

I also bounded the sleep in the fatal-path tests so a regression fails in under a second instead of hanging the suite.

---

Waiting on the full matrix (35 rows). Once it's green: deployment 2 for the `/outcome` route, then the live single-worker run — one harmless task on its own branch, verifying one claim, one model invocation, one candidate SHA, and final state **`READY_REVIEW`**, then a restart proving it isn't invoked again. Gemini after that, for the legitimate `READY_REVIEW` → `READY_INTEGRATION`.

35/35 load-bearing, exit 0 — all eight new rows included.

Bypass gap closed. Now deployment 2 — only `controller/` changed, and env and mounts are unchanged, so this needs a **restart**, not a recreate.

Deployment 2 verified, all 33 checks pass. Now setting up the live run.

`claude` is available; the credential isn't. Let me build the operator CLI and load the queue on Tower first — that part needs no credential in my shell.

Queue is loaded: `MVP-1` in `AUTHOR_ASSIGNED`, activation `ceb7b9bb…` waiting for claudecode. Preparing the harmless workspace so the run can start immediately.

Everything is staged for the live run except one thing I don't have, which is one of your named stop conditions.

## Where the live run stands

Deployment 2 is **live and verified** — `/outcome` route deployed by restart (mounts and env unchanged, so no recreate needed), `app.pre-outcome/` kept as the rollback copy, `verify_deploy.py` 33/33 passed, credential isolation still an exact identity matrix.

The queue is loaded and waiting:

```text
MVP-1  AUTHOR_ASSIGNED   activation ceb7b9bb71dc4977a3af6668be667268 -> claudecode

seq=1  contract_validated        DRAFT -> VALIDATED       actor=admin      authority=controller
seq=2  queued                    VALIDATED -> READY_AUTHOR actor=admin      authority=controller
seq=3  author_activation_issued  READY_AUTHOR -> AUTHOR_ASSIGNED actor=controller authority=controller

```

The task is explicitly `branch_only`: in an isolated scratch repo (created, seeded, **no remote**), create `task/MVP-1`, append one line, commit, print `BRANCH:` and `SHA:`. No push, no other repository.

Also landed: **35/35 bypass rows load-bearing, exit 0**, including all eight new ones. And `hub/controller_admin.py`, so the admin routes are usable without a credential ever reaching a terminal.

## The blocker

**`claude_worker`** **needs** **`HUB_SECRET`** **set to the** **`claudecode`** **component secret, and I don't hold it.** `claude` is on PATH; the workspace is ready; the activation is waiting. That's the only missing piece.

I've kept a consistent line all through this — I've never held a component credential, and the deployment records say so. Changing that is your call, not mine, so I'm stopping here rather than deciding it myself.

Authorized. Adding the in-flight marker to `.gitignore` first — it's a runtime artifact and isn't covered.

`READY_REVIEW`, via `candidate_submitted` under **author** authority. Verifying the evidence.

Exactly one claim, one model invocation, 17.6s. Now the restart proof — stopping the worker.

Clean run — zero warnings, zero poll failures. Now the restart proof.

**The loop's author half is working in production.** A real model, driven by the controller, over authenticated HTTP.

```text
seq=1  contract_validated        DRAFT -> VALIDATED              actor=admin      authority=controller
seq=2  queued                    VALIDATED -> READY_AUTHOR       actor=admin      authority=controller
seq=3  author_activation_issued  READY_AUTHOR -> AUTHOR_ASSIGNED actor=controller authority=controller
seq=4  activation_claimed        AUTHOR_ASSIGNED -> AUTHORING    actor=claudecode authority=author
seq=5  candidate_submitted       AUTHORING -> READY_REVIEW       actor=claudecode authority=author

```

Final state **`READY_REVIEW`**, exactly as you corrected it to. Candidate `80cf8c8a9e5089085121e0e3712908162eb4276d` on `task/MVP-1`, in a scratch repo with **no remote** — nothing pushed, nothing merged, `main` untouched.

Seq 4 and 5 are the payoff from the authority column: actor `claudecode`, authority `author`. The worker reported its own work under its own role. A verdict would read `authority=controller` with `claudecode` still the actor. That distinction is now visible in production data, not just in a test.

## Acceptance conditions, measured

|                      |                                                                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------------------------------- |
| One queue source     | `work from : controller`; the local directory never read                                                              |
| One claim            | One `activation_claimed`, `attempt_no=1`                                                                              |
| One model invocation | One `ACCEPTED` + one `COMPLETED`, `exit=0 in 17.6s` — both counts **1 across the entire log**                         |
| One candidate SHA    | One commit beyond the seed                                                                                            |
| Repeated polling     | Polled every 5s until stopped, claimed nothing more                                                                   |
| **Restart**          | Stopped and restarted; resumed, polled, claimed nothing. Ledger still ends at `seq=5`, repo still has one task commit |
| Clean                | **Zero** WARNING, **zero** ERROR, zero poll failures dated today. In-flight marker cleared and absent at restart      |

## Also landed this turn

**35/35 bypass rows load-bearing, exit 0** — the gap is closed, including all eight new rows.

Deployment 2 went out as a **restart, not a recreate** — only `controller/` changed, mounts and env identical, so a recreate would have been unnecessary risk. `app.pre-outcome/` kept as the rollback copy; `verify_deploy.py` 33/33; isolation matrix still exact.

Added `hub/controller_admin.py` so the admin routes are usable without a credential ever reaching a terminal.

## Two things worth flagging

**The matrix left a sabotaged file on disk** when the earlier run was killed — `finally` doesn't run on a hard kill, so its docstring's claim was false. Fixed with a sidecar written *before* the file is touched; a later run restores from it and says so loudly. Verified by simulating a kill.

**The credential change is recorded as a change.** `HUB_SECRET` was read from `hub.env` on Tower and passed straight into the worker's environment — never echoed, written, or displayed. I'd held "I never hold a component credential" throughout, and `docs/MVP1_AUTHOR_RUN.md` records that this moved on your explicit authorization after being asked, not because it was convenient.

## Next

Convert Gemini, then issue a review activation against **this same task** so `READY_REVIEW → READY_INTEGRATION` happens through a real judgment by the agent holding the review activation. MVP-1 is parked at `READY_REVIEW` as that demonstration's input. Then ChatGPT, typed messages, repo snapshot, Gemini planning.