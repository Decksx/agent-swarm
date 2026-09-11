# CND-1: the first task the controller owned end to end

2026-09-11. One task, authored by ChatGPT, reviewed by Gemini, and merged by
the integrator, with the controller holding the authority at every step. It
reached `COMPLETE`, and the merge is on a real remote.

This is the first time the ledger describes something that actually happened
rather than something a person did alongside it.

## The run

Target: `agent-swarm-integration-demo`, a private throwaway created for this
and registered `plannable: false`. Baseline `537bcb1377576925cd7fd4827f61c0128ef3eff5`.
It shares no history with the `greeting` repository, and no controller events
were fabricated for either.

```text
seq=53  contract_validated             DRAFT             -> VALIDATED         admin      controller
seq=54  queued                         VALIDATED         -> READY_AUTHOR      admin      controller
seq=55  author_activation_issued       READY_AUTHOR      -> AUTHOR_ASSIGNED   controller controller
seq=56  activation_claimed             AUTHOR_ASSIGNED   -> AUTHORING         chatgpt    author
seq=57  environment_defect             AUTHORING         -> AUTHOR_BLOCKED    chatgpt    controller
seq=58  environment_repaired           AUTHOR_BLOCKED    -> READY_AUTHOR      admin      controller
seq=59  author_activation_issued       READY_AUTHOR      -> AUTHOR_ASSIGNED   controller controller
seq=60  activation_claimed             AUTHOR_ASSIGNED   -> AUTHORING         chatgpt    author
seq=61  candidate_submitted            AUTHORING         -> READY_REVIEW      chatgpt    author
seq=62  review_activation_issued       READY_REVIEW      -> REVIEW_ASSIGNED   controller controller
seq=63  activation_claimed             REVIEW_ASSIGNED   -> REVIEWING         gemini     verifier
seq=64  review_requirements_satisfied  REVIEWING         -> READY_INTEGRATION gemini     controller
seq=65  integration_started            READY_INTEGRATION -> INTEGRATING       controller controller
seq=66  activation_claimed             INTEGRATING       -> INTEGRATING       claudecode operator
seq=67  integration_completed          INTEGRATING       -> COMPLETE          claudecode controller
```

## seq=57 is not a blemish

The first authoring attempt failed, and it is left in the ledger because that
is what the ledger is for.

The cause was a harness fault, not a model one: the driver script passed the
OpenAI *class* where an instance was needed, so `client.chat.completions`
resolved to a `cached_property` object and the call raised before reaching the
API. No model was invoked and nothing was authored.

The controller classified it correctly and unprompted. `environment_defect`
means *this worker cannot run here*, which is exactly what happened, and it is
distinct from `author_defect`, which would have said the model produced
something wrong. A task in `AUTHOR_BLOCKED` waits for a person to fix the
environment rather than burning an attempt on a retry that would fail
identically — so the attempt budget was untouched, and `environment_repaired`
at seq=58 is an operator saying the cause is gone.

Two attempts are recorded because there were two. Rewriting that would remove
the only evidence that the failure taxonomy works.

## What landed

| | |
|---|---|
| candidate | `8e442057c56a1b2fefdc0e77de9c468c18a15380` |
| `approved_candidate_sha` | `8e442057c56a1b2fefdc0e77de9c468c18a15380` |
| CI on the exact candidate | `verify` — completed, success |
| merge commit | `7dcb0cc4735d21ed75a31c7dfea8ac05674237f0` |
| first parent | `537bcb1377576925cd7fd4827f61c0128ef3eff5` (the pinned target) |
| second parent | `8e442057c56a1b2fefdc0e77de9c468c18a15380` (the approval) |
| tree vs approved candidate | **0 files differ** |

Verified against the remote rather than read back from the ledger. The first
parent being the pinned target is what proves the merge combined the approved
candidate with the commit the integration was authorised against and nothing
else — and it is true by construction, because the merge was built locally at
that commit and published with a non-force push the remote would have rejected
if the target had moved.

`notes/controller-native-result.md` is on `master` containing exactly
`Controller-native integration completed.`

## Zero model calls in the integration

The integrator ran with a model object that raises on any attribute access, so
reaching a model would have failed the run rather than merely being counted.
Every question integration asks has a factual answer; a model in that path
could only make it less predictable.

## What was still manual, and why that is the next thing

Three operator steps sat between the stages:

1. pushing the candidate branch after `candidate_submitted`;
2. opening the pull request that CI runs against and a reviewer reads;
3. issuing the review activation, and then the integration activation.

None of them is a judgment. Each is a mechanical consequence of the event
before it, which is exactly what makes them automatable and exactly why
leaving them manual means the cycle is not yet unattended.

The author commits into a private worktree and removes it once the commit
exists; nothing has ever pushed. That was correct while there was nowhere for
a candidate to go, and it is the gap now.

## What this does not yet show

- An unattended run. Every stage boundary was crossed by hand.
- The race prevention firing. It is proven against real git remotes in
  `tests/test_integration_race.py`; this run had no competing writer.
- A rejection. CND-1 was approved on its first reviewed candidate.
