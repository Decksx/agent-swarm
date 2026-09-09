# Phase 0 — closeout

Written 2026-09-09 by Claude Code. Branch `phase0/closeout`, based on
`8bfdb638e56024cd064d6a874ee3947d4dcad494` (`phase0/containment`, the tip that
was deployed and verified on Tower).

This closes the one Phase 0 requirement that had no record behind it, corrects
the documents and comments that had gone stale under the work, and re-measures
the suite afterwards. It is documentation, two comment corrections, two
launcher lines and one read-only diagnostic. **No worker or hub behaviour
changes**, and nothing here was deployed.

---

## 1. Credential rotation — closed by the operator

Protocol section 19, Phase 0 item 1: *rotate exposed credentials and inspect
their exposure history.* Before today this had no record in any document, which
`docs/PHASE0_VERIFICATION.md` section 8 reported as the open item that should
block sign-off.

| | |
| --- | --- |
| Date | 2026-09-09 |
| Providers | OpenAI, Google (Gemini) |
| Action | Old API keys revoked and replaced in the provider consoles |
| Worker configuration | Updated with the new keys in the protected environment |
| Restart | Each worker restarted and confirmed authenticated startup with no credential displayed |
| Current state | Workers stopped |
| Reported by | The operator |

**No key value was given to me, and none is recorded here or anywhere in this
repository.** That is the point of the entry: the record needs the date, the
providers and who confirmed it, and needs none of the material it is about.

### What this entry is, precisely

**This is an operator attestation, not a measurement I made.** I cannot see the
provider consoles, I hold no credential, and I should hold none. I did not
verify that the old keys are revoked, that the new ones differ, or that the
workers authenticated — I was told, and I am recording what I was told, with
the fact that it is a report rather than an observation stated plainly so that
a later reader does not mistake this table for evidence of the same kind as the
test output in section 4.

The hub credentials are a separate matter and needed no rotation: they were
generated on Tower on 2026-09-09 with `openssl rand -hex 24`, mode 600, and had
no predecessor. That is recorded in `docs/DEPLOY_PHASE0_HUB.md`.

### The exposure-history half

The requirement has two halves. Rotation is done. **Inspecting the exposure
history is not, and cannot be finished from this host** — see section 3.

## 2. Documents and comments corrected

Each of these was found while verifying, and each was left in place at the time
because verification is not the moment to start editing. They are fixed here.

**`docs/PHASE0_CONTAINMENT.md` (`cd73898`).** Four statements were true when
measured on 2026-09-08 and false afterwards: that the control-plane half was
unbuilt, that the section 5 patch specification was still a proposal, that
Phase 1 had not started, and that the suite was 76 tests. The document is an
evidence record, so nothing was rewritten: each sentence is kept verbatim with
an inline `[RESOLVED 2026-09-09]` marker beside it, and a resolution log at the
top lists all four together. A reader arriving at the primary containment record
was previously told the hub is unauthenticated, which is the single claim about
this system most worth being right about.

**`swarm_control.py` docstring (`f6bda95`).** It described the hub in the
present tense — `GET /messages` answers 200 without a credential, `sender` is
free text nobody derives from an identity — and called the server-side half of
Phase 0 "the half that lives on Tower and is not in this repository". Both
stopped being true on 2026-09-09; `hub/hub.py` has been tracked since `e87176b`.
Rewritten in the past tense with the measurement date kept, because those
measurements are the justification for the module's design and deleting them
would remove the reason along with the staleness.

That correction carries a decision worth reading, now stated where the decision
would be made: the authenticated hub makes "only obey Admin" enforceable for the
first time, so restoring Admin-over-chat became *possible* — and it stays
deliberately unrestored, because activation is moving to the controller and a
second chat-shaped path into it would hand back exactly what Phase 0 removed.

**`start_workers.bat` (`10d7599`).** The launcher warned about `GEMINI_API_KEY`
and `OPENAI_API_KEY`, which stop one worker each, and said nothing about
`HUB_SECRET`, which stops all three. Since Phase 0 a worker without it returns 1
at startup, so the symptom is three windows that open and close faster than they
can be read.

The same commit records a mistake in `docs/DEPLOY_PHASE0_HUB.md` section 5, at
the place an operator would be misled by it. That section says the simplest
arrangement is one shell per worker, "which `start_workers.bat` already gives
you (each opens its own window)". Each worker does get a window, but `start`
hands every child the launching shell's environment, so all three inherit **one**
`HUB_SECRET`. The hub keys credentials per component and the Basic username is
each worker's bound identity, so one shared value authenticates all three only
if all three components were issued the same secret; with distinct secrets, two
of the three get 401 on every call. Left as a warning rather than a fix:
per-worker secret plumbing is a behaviour change and does not belong in a
closeout.

## 3. Hub database scan — tool delivered, scan not run

`hub/scan_hub_db.py` (`d53272c`) scans the hub's SQLite database for
credential-shaped strings and reports **table, column, pattern name and row
primary key — never the matched value, never an excerpt, never message
content.** A scan that prints what it finds moves the secret into a terminal, a
transcript and often a bug report, which is how a scan becomes a leak.

**It has not been run against the real database, and I cannot run it.** The
database is at `/mnt/user/appdata/agent-swarm/data/chat.db` on Tower
(`/data/chat.db` inside the container). It is not reachable from OFFICEPC, and
reaching it would require a credential I do not hold. This is the exposure-history
half of section 1: those messages accumulated while the hub answered `200` to any
LAN caller, so if a model ever printed its environment into chat, that is where
it is.

To run it, on Tower:

```sh
# copy hub/scan_hub_db.py from this repository to Tower first -- it is not
# deployed there, and nothing in the container needs it
python3 /mnt/user/appdata/agent-swarm/scan_hub_db.py \
        /mnt/user/appdata/agent-swarm/data/chat.db
```

It uses only the standard library, so the system `python3` on Tower is
enough; it does not need the container or its FastAPI environment.

Exit status 0 means clean, 1 means matches were found. **Report the printed
summary — the counts and row ids — not the rows themselves.** If it reports
matches, the rows it names are the exposure history, and what to do about them
(and whether the just-rotated keys were among them) is an operator decision made
with the database open, not one made from a transcript.

Verified before delivery, against fixtures rather than assumed:

- a clean database containing a 64-character sha256 digest stays clean and exits
  0 — the `hex48` pattern is bounded on both sides so it does not match a window
  inside a longer hex string;
- a database with a planted OpenAI key, Google key and 48-hex string reports
  three matches by row id, prints no value, and exits 1;
- a `DELETE` attempted through the same `file:...?mode=ro` URI the scanner uses
  fails with "attempt to write a readonly database", so it cannot alter the
  hub's data even if run while the hub is live.

The `hex48` pattern exists because the hub credentials are `openssl rand -hex 24`
output. That shape has no prefix, so `swarm_control.redact()` — which keys off
`sk-` and `AIza` — cannot see one. It is the pattern most likely to produce a
false positive and the only one that can find the credential this system
actually issues.

## 4. Re-measured after the closeout edits

Run on `phase0/closeout` at `d53272c`, Python 3.11.3, Windows-10-10.0.26200-SP0.

```text
$ python -m pytest tests/ -q
83 passed in 0.73s
exit 0

$ python tests/bypass_matrix.py
guards proven load-bearing: 10/10
exit 0

$ python workspace/guard_check.py
FAILURES: none
exit 0

$ <venv>/python -m pytest hub/test_hub.py -q
37 passed, 2 warnings in 1.34s
exit 0
```

Unchanged from the Phase 0 tip, which is the expected result: nothing in this
branch changes behaviour. The bypass matrix reports the same ten guards
load-bearing with the same expected failure counts, including the surplus on
`replies_addressed_to_a_peer` (caught 2, expected 1) that it names rather than
swallows.

`POLL_SECONDS=60` is not covered by a test and is not claimed to be. It is a
launcher default, applied only when the variable is unset, and its effect is a
request rate rather than a behaviour.

## 5. Where Phase 0 stands

| Protocol section 19, Phase 0 | State |
| --- | --- |
| 1. Rotate exposed credentials | **Rotation done** 2026-09-09, operator-attested (section 1). Exposure-history inspection **open** — scan delivered, not run (section 3). |
| 2. Authenticate every endpoint, bind identity server-side | Done, deployed, verified. `hub/hub.py`, byte-matched to the deployed SHA-256. |
| 3. Workers ignore agent chat for activation | Done. Proven dynamically and by call graph. |
| 4. Visible global pause, verified | Done. Demonstrated live. |

Evidence for 2, 3 and 4 is in `docs/PHASE0_VERIFICATION.md`, re-measured rather
than carried forward.

**One item remains open**: running the scan in section 3. Everything else that
Phase 0 asked for is closed and recorded.

## 6. Positions accepted from the review

Recorded because they are decisions, and a decision that lives only in a message
is not recorded. These came from ChatGPT's review, relayed by the operator, and
are adopted:

- **The attachment truncation was outside this repository.** The tracked
  briefing is complete and needs no repair. `docs/PHASE0_VERIFICATION.md`
  section 0 keeps the measurement that established it.
- **The existing Phase 1 code does not invalidate Phase 0.** It predates the
  review assignment and remains undeployed.
- **The live pause satisfies Phase 0.** Cooperative drain (protocol section 6)
  belongs to later controller and integration work and is not a Phase 0 gap.
- **Sixty-second polling is transitional.** Phase 1 should remove worker chat
  polling entirely once a narration count can be obtained on demand rather than
  accumulated independently by every worker.
- **"Nothing deployed" scopes to the verification turn.** The authenticated
  Phase 0 hub was deployed earlier, on 2026-09-09, and is byte-matched to the
  tracked commit.

## 7. Branch and scope

`phase0/closeout` branches from `phase0/containment` and contains no controller
code, so it can be reviewed and merged without carrying Phase 1 with it. The
branch as it stood when this document was written, newest first — this
document's own commit is necessarily not in its own list:

```text
d53272c  Scan the hub database without being able to read what it finds
3d8567d  Slow the chat poll from three seconds to sixty
10d7599  Warn about the credential that now stops every worker
f6bda95  Stop the docstring describing a hub that no longer exists
cd73898  Mark what this record got right on the day and wrong since
c0d5c98  Answer the Phase 0 review with measurements instead of claims
d14ed37  Commit the protocol the code already claims to enforce
8bfdb63  (phase0/containment) Close the deployment record with the operator's 200
```

The bottom two are cherry-picks of commits made earlier today on
`phase1/controller-core`, where they landed before this branch existed. They are
Phase 0 documents — the protocol and the verification record — and they belong
on a branch a reviewer can take without the controller. **The originals are
still on `phase1/controller-core`**, so `SWARM_PROTOCOL_v7.md` and
`docs/PHASE0_VERIFICATION.md` each exist under two commit ids until one of the
branches is merged or rebased. Git will reconcile them by content; it is noted
here so nobody mistakes it for a divergence.

Phase 1 is **not** deployed and **not** merged. Nothing in this closeout touches
`controller/`.
