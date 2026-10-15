Filing the fetch-fallback separately first so it doesn't get absorbed, then implementing precedence.

Implementing. The helper is testable in isolation so "no fetch occurs" can be proven rather than asserted:

Implementation is in — precedence, fail-closed, no fetch. Fixing the startup log line and checking the `candidate` ordering, then writing the six regression tests.

Now the six regression tests, each mapped to a clause of the contract:

Three of my own mistakes — including forgetting that #61 moved `REVIEW_JUDGMENTS` to `outcomes`. Getting the other failures:

Two more, both mine — and the first is a nice one: my assertion matched the substring `fetch` inside the **temp directory path**, which contains the test's own name. Checking the real signature and fixing all three:

One left, and again it's the test not the code: for the `missing` case the path check fails **before any git runs**, so zero commands is correct — and a stronger claim than "no fetch". Making the assertion say that:

11/11. Mutation-testing the two guards that carry the contract:

Both mutants caught. The second is instructive: with the presence check removed, the log shows it falls through to `review_packet` and reproduces the *exact* production error — so the guard's value is converting an obscure packet failure into a precise, recorded refusal. Full suite running; filing the fetch design issue meanwhile:

Filed as **#69**, with your ref-selection point recorded as the subtle one — `git fetch <remote> <sha>` isn't universally supported without `uploadpack.allowReachableSHA1InWant`, and fetching the branch by name would repeat exactly the mistake `review_packet.build` already refuses (a branch names whatever its tip happens to be when read).

Waiting on the suite before committing. Where #64 stands:

**Implementation** — `resolve_review_repo()` in `gemini_worker.py`, with every clause of your contract:

| Clause How                                                                |                                                                                                                         |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Activation `repo_location` authoritative                                  | `if declared: repo, source = declared, "activation"`                                                                    |
| `REVIEW_REPO` only when activation names none                             | `elif configured:` — never reached when `declared` is set                                                               |
| Absent / unreadable / not-a-repo / lacks candidate → `environment_defect` | four distinct refusals, each with its own message                                                                       |
| Never fall back once the activation names one                             | no fallback path exists after `declared` is chosen                                                                      |
| Never fetch                                                               | only `rev-parse --git-dir` and `cat-file -e` run; proven by test 5                                                      |
| Record both paths, no credential leak                                     | `detail` carries `repo_location`, `review_repo`, `repo_used`, `repo_source`; git output is discarded rather than echoed |
| `repo_location` only from the activation                                  | read from the activation record; documented against `engine._approved_candidate`                                        |

**Tests** — 11, covering all six of your shapes. Mutating precedence back to the old behaviour fails 5; removing the presence check fails 2.

**Three test bugs I hit and fixed**, worth naming because two were the tests lying rather than the code:

- My "no fetch" assertion matched the substring `fetch` inside pytest's temp path, which contains the test's own name. It now compares the git subcommand.
- I forgot #61 moved `REVIEW_JUDGMENTS` to `controller.outcomes` — my own refactor, four hours old.
- I asserted "at least one git command" for the missing-path case, where zero is correct and stronger.

Five failures in `tests/` — my change broke existing tests. Getting all of them:

The fixture stubs `review_packet.build` because it *"runs git over a real range"*, then points `REVIEW_REPO` at a bare `tmp_path` — not a git repo. My precondition now runs real git before the stub, so it correctly refuses and the model is never called. The resolution needs stubbing for the same stated reason the packet builder already is:

Re-running the full `tests/` leg to confirm all five are gone and nothing else moved. Meanwhile, the state of #64:

**The five failures were all one fixture** in `test_operator_context_at_the_model_call.py`, and they failed for a legitimate reason: my precondition runs real git *before* the stub those tests rely on. The fixture points `REVIEW_REPO` at a bare `tmp_path` that isn't a git repository, and the activation's `expected_candidate` is `"2" * 40` — a SHA no real repository can contain. So there's no way to satisfy the new check with a real tree; stubbing the resolution is the only honest option, and it's consistent with the fixture already stubbing `review_packet.build` for exactly the same stated reason.

I've noted in the fixture comment that repository selection is covered by `tests/test_review_repo_selection.py`, so the stub can't quietly become the only behaviour anyone tests.

That's worth flagging for the reviewer explicitly: **#64 adds a precondition that any test exercising** **`execute_review`** **with a fake repo must now satisfy or stub.** Five existing tests hit it. A reviewer should check that the stub I added doesn't weaken what those tests were protecting — they assert operator context reaches the prompt, which is untouched by repository selection.

Once the leg is green I'll commit, push, open the PR, and build the packet for the exact SHA.

Confirmed: **all five failures were the one fixture**, no other test touched. Waiting on the re-run to verify the whole leg.

Waiting. While it runs, the summary of what #64 will present for review:

**Changed files:** `gemini_worker.py` (the helper + wiring + the startup log line), `tests/test_review_repo_selection.py` (new, 11 tests), `tests/test_operator_context_at_the_model_call.py` (fixture stub only).

**The one thing I'd want a reviewer to push on:** the fixture stub. Five passing tests now pass because I stubbed the guard away in them. That's defensible — they test prompt assembly, the fixture already stubs `review_packet.build` for the same reason, and their activation names a candidate (`"2" * 40`) no real repository could ever contain, so there is no non-stub option. But it is exactly the shape of change that can quietly hollow out coverage, and the reviewer should confirm the assertions those tests make are untouched by repository selection.

**The startup log line changed meaning**, so I changed its wording: it used to print `review repo: <path>` as though that were the decision. It's now `review repo fallback:` — because an activation naming a repository is reviewed there regardless. A log line that states the old behaviour would be the same class of staleness as the README claim that started the acceptance run.

**What this does not do:** fetch. #69 carries that design, including the `uploadpack.allowReachableSHA1InWant` constraint and the namespaced-ref requirement.

After review and merge, the deployment sequence you specified is: pause and confirm idle → advance the detached production clone explicitly to the new merge SHA → deploy to Tower (required, since #61 changed controller files) → remove the Windows User `REVIEW_REPO` variable → restart via the scheduled `ensure` path rather than by hand → verify parity and process uniqueness → and prove the controller-named repository wins using the *second acceptance task's real review activation*, not a synthetic check.

All three legs green — **1793 + 8 + 307**, up 11 from `main`'s 1782 (the new file). Committing and opening the PR:

**#64 is up for review:** https\://github.com/Decksx/agent-swarm/pull/70

|        |                                                                  |
| ------ | ---------------------------------------------------------------- |
| Head   | `a976602fcc0a79c029897fb3011cd7cdebf1e573`                       |
| Base   | `74dfaef` (current `main`)                                       |
| Packet | `PR_70.md` — 25,539 chars, 3 files, untruncated (attached)       |
| Local  | 1793 + 8 + 307 (main: 1782 + 8 + 307)                            |
| CI     | starting — I'll report the conclusion against the run's head SHA |

Scope is precedence + fail-closed only, exactly as specified. Fetching is #69, with the `uploadpack.allowReachableSHA1InWant` constraint and the namespaced-ref/verify-the-object requirements recorded there rather than half-implemented here.

The PR body flags the one thing I'd want challenged: **five existing tests were changed.** Their fixture can't satisfy the new precondition by any means — it points `REVIEW_REPO` at a bare `tmp_path` and names candidate `"2" * 40`, which no repository can contain — so the resolution is stubbed there, consistently with that fixture already stubbing `review_packet.build`. Those tests assert operator context reaches the prompt, which repository selection doesn't touch, but that's worth confirming rather than accepting.

Board after this: **#70** awaiting verdict, then the deployment sequence to remove the temporary override, then the second acceptance task — which is the one that finally has to prove integration and autonomous merge, the two stages nothing has exercised since Sept 15.

CI is running on `35759883064`; I'll report its conclusion against the head SHA when it lands.

Where the whole effort stands, since this is a natural pause point:

**Merged today:** #26 (`a3e9537`), #57 (`206fce8`), #61 (`74dfaef`) — all CI-green on `main`.

**Awaiting your verdict:** #70 at `a976602`, packet delivered.

**Open, with the work scoped:** #58 (relayed verdicts, Tier 1/2 contract agreed, unblocked now that `activations.py` has headroom), #60 (swarm-development policy, with the measured 5-of-250 baseline), #62 (six-slice cleanup), #67 (ingress usability), #68 (retry model, option A chosen with five test requirements), #69 (fetch design).

**Production:** paused, pinned `206fce8`, idle, carrying one temporary override whose removal is gated on #70.

The thing I'd keep in view: **integration and autonomous merge remain unproven on this deployment.** Everything today exercised authoring, review, retry, repair, escalation and cancellation — genuinely, and they work. The two stages that actually put code on `main` have not run since Sept 15, and the second acceptance task exists specifically to close that gap. Until it does, "operational" is accurate for six stages out of eight.

**CI green on #70**, verified against the run's head rather than the label:

```
head:       a976602fcc0a79c029897fb3011cd7cdebf1e573   ← matches the packet's candidate exactly
conclusion: success
pytest-unit    pass  8m33s
pytest-bypass  pass  44s

```

Run [35759883064](https://github.com/Decksx/agent-swarm/actions/runs/35759883064) · PR https\://github.com/Decksx/agent-swarm/pull/70

\#64 is complete and ready for a verdict at `a976602fcc0a79c029897fb3011cd7cdebf1e573` against base `74dfaef`. Packet delivered, local suite 1793/8/307, CI green, not merged.

Nothing is in flight on my side now. When you have a verdict I'll merge and run the deployment sequence — pause and confirm idle, advance the production clone to the new merge SHA, deploy to Tower, drop the `REVIEW_REPO` variable, restart via the scheduled `ensure` path, verify parity and process uniqueness, then prove the controller-named repository wins using the second acceptance task's real review activation rather than a synthetic check.