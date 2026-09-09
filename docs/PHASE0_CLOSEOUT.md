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
test output in section 5.

The hub credentials are a separate matter and needed no rotation: they were
generated on Tower on 2026-09-09 with `openssl rand -hex 24`, mode 600, and had
no predecessor. That is recorded in `docs/DEPLOY_PHASE0_HUB.md`.

### The exposure-history half

The requirement has two halves. Rotation is done, and so is the other half:
the hub's message history was scanned on Tower the same day and is clean, 0
matches across all 1134 text-bearing cells. See section 3, which also says what
a clean scan does and does not establish.

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

## 3. Hub database scan — run 2026-09-09, clean

`hub/scan_hub_db.py` (`d53272c`) scans the hub's SQLite database for
credential-shaped strings and reports **table, column, pattern name and row
primary key — never the matched value, never an excerpt, never message
content.** A scan that prints what it finds moves the secret into a terminal, a
transcript and often a bug report, which is how a scan becomes a leak.

The database is at `/mnt/user/appdata/agent-swarm/data/chat.db` on Tower
(`/data/chat.db` inside the container). This is the exposure-history half of
section 1: those messages accumulated while the hub answered `200` to any LAN
caller, so if a model ever printed its environment into chat, that is where it
would be.

### Result

Run on Tower on 2026-09-09, on the operator's explicit authorization, over the
existing `tower.local` SSH route. The database was never copied anywhere; the
scanner was staged on the media share and read `appdata` in place.

```text
database : /mnt/user/appdata/agent-swarm/data/chat.db
columns  : 3 text-capable columns across 1 tables

cells scanned : 1134
matches       : 0
RESULT: clean
exit 0
```

**Zero matches across every text-bearing cell in the database.** The population
reconciles exactly, which is the part worth checking rather than trusting:

- `messages` holds **378 rows**, ids 1 to 378 with no gaps, so nothing has been
  deleted and the whole pre-containment history is present.
- Three TEXT columns are scanned — `sender`, `target`, `content`. 378 x 3 =
  **1134**, the number the scanner reports.
- The two columns it skipped are `id` (INTEGER PRIMARY KEY) and `timestamp`
  (REAL). SQLite is dynamically typed, so "declared REAL" is not the same as
  "contains no text": checked separately, all 378 `timestamp` values have
  storage class `real` and all 378 `id` values `integer`. Nothing textual went
  unscanned.
- `sqlite_sequence` is excluded as an internal table. Its entire contents are
  the single row `('messages', 378)`.
- Longest `content` value is 4,428 characters, so the scan covered real message
  bodies rather than a table of stubs.

The sender distribution is an independent confirmation of the measurement this
whole effort started from: Gemini 182, ChatGPT 148, ClaudeCode 28, Admin 20,
summing to 378. Those are the figures quoted in
`docs/HANDOFF_SESSION_AGENTS.md` section 1, arrived at again from the database
rather than carried forward from the earlier count.

`chat.db` was last written 2026-09-03 14:20 — before containment. The
authenticated hub has written no messages since it was deployed on 2026-09-09,
which is consistent with the workers having been stopped.

### What this does and does not establish

It establishes that no credential-shaped string is stored in the hub's message
history, for the eight shapes the scanner knows. It does not establish that
nothing was ever exposed: a key posted and later deleted would leave no row, and
the contiguous id range only shows no row was removed from *this* table, not
that nothing was read by a LAN caller while the hub was open. Rotation is what
covers that, and it is done.

To re-run it, on Tower:

```sh
# copy hub/scan_hub_db.py from this repository to Tower first -- it is not
# deployed there, and nothing in the container needs it
python3 /mnt/user/appdata/agent-swarm/scan_hub_db.py \
        /mnt/user/appdata/agent-swarm/data/chat.db
```

It uses only the standard library, so the system `python3` on Tower is
enough; it does not need the container or its FastAPI environment.

Exit status 0 means clean, 1 means matches were found. **Report the printed
summary — the counts and row ids — not the rows themselves.** If it ever reports
matches, the rows it names are the exposure history, and what to do about them is
an operator decision made with the database open, not one made from a transcript.

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

## 4. Credential isolation — verified against the live hub

Deriving `sender` server-side was recorded as closing impersonation. On its own
it does not, and the gap is worth stating precisely because everything else in
Phase 0 rests on it.

`hub.authenticate()` reads the component name from the Basic **username**, looks
that name up in `CREDENTIALS`, and compares only the secret. The name is
therefore chosen by the caller; the secret is the entire binding. If two
components share a secret, either name authenticates, and the impersonation is
total: the hub stores whichever `sender` was typed, and a worker sharing a
secret with `admin` can pause and resume the swarm. Every individual request is
perfectly valid, so nothing in the hub can detect it at runtime. It is a
property of the deployed configuration, not of the code, and can only be checked
from outside.

### The matrix

`hub/auth_matrix.py` tries every configured credential under every configured
username against `GET /control/status` on the live hub, and prints component
names and status codes only — never a secret, never a hash, never a length. Run
on Tower on 2026-09-09 against the running container (up 5 hours), reading
`hub.env` in place:

```text
hub        : http://127.0.0.1:8050/control/status
components : 4 (admin, chatgpt, claudecode, gemini)

rows = credential owner, columns = username presented

                 admin     chatgpt  claudecode      gemini
admin              200         401         401         401
chatgpt            401         200         401         401
claudecode         401         401         200         401
gemini             401         401         401         200

RESULT: isolated - each credential authenticates exactly one identity
exit 0
```

**The deployed hub is already isolated.** Four components, four distinct
secrets, an exact identity matrix: 4 diagonal 200s, all 12 off-diagonal cells
401. The `chatgpt` row answers the case the review asked for by name — that
credential authenticates as `gemini`, `claudecode` and `admin` exactly never —
and the other three rows answer the equivalent cases. No credentials needed to
be replaced; they were already distinct.

The checker was proven to fail before it was trusted to pass. Against a hub
started with `admin` and `gemini` deliberately sharing a secret it reports both
off-diagonal 200s by name and exits 1; against the same hub with four distinct
secrets it prints the identity matrix and exits 0. Both runs were then searched
for the fixture secret values and neither printed one.

### The launcher was the real exposure

The configuration was sound; the way credentials reached the workers was not.
`start_workers.bat` passed **one** `HUB_SECRET` to all three workers by
environment inheritance. With four distinct component secrets that is also
operationally broken — at most one worker could authenticate, and the other two
would 401 on every poll while looking healthy, because `fetch_messages` logs a
warning and returns an empty list. The tempting way to make it "work" is to give
every component the same secret, which is exactly the collapse the matrix exists
to catch.

Each worker now takes its credential from its own `HUB_SECRET_<COMPONENT>`
variable and the child clears all three, so a worker process holds exactly one
credential and cannot read its peers'. Verified with stub workers: each reported
`HUB_SECRET` set to its own value with no other `HUB_SECRET_*` variable present.

Two details are load-bearing and both were measured rather than assumed:

- The doubled percent signs pass the variable **name** to the child, which
  expands it itself, so no secret value appears on a command line — where any
  process on the machine could read it. Confirmed by having the child print its
  own `CMDCMDLINE`, which came back containing `%HUB_SECRET_CLAUDECODE%` rather
  than the value.
- Each launch is guarded on its variable being present, because the obvious
  version was wrong. When a variable is unset, `cmd` does not expand `%%NAME%%`
  to nothing — it leaves the literal text. The first draft started
  `chatgpt_worker` with `HUB_SECRET` set to the string `%HUB_SECRET_CHATGPT%`,
  which is not empty, passes the worker's placeholder check, and 401s forever
  while the window looks fine: the silent-degradation mode Phase 0 exists to
  remove, reintroduced by the fix for it. A missing credential now prints
  `[error]`, that worker is not started, and the others still are. Both paths
  were run.

### Tests

Six tests added to `hub/test_hub.py` (37 to 43), asserting all twelve ordered
cross pairs, the three `chatgpt`-as-someone-else cases by name, and that a
worker secret cannot reach admin authority on `/control/pause` or
`/control/resume` by renaming.

The sixth asserts the hazard rather than a defence: two components sharing a
secret **do** authenticate as each other and the stored sender is whichever name
was typed. It is a characterization test, and it is the reason `auth_matrix.py`
has to exist.

Five of the six are load-bearing, verified by bypass rather than by assertion.
Rewriting `authenticate()` to compare the secret against every configured
component and then trust the supplied name — the realistic regression, since
every request still looks valid — fails 7 tests: five of the six added, plus the
two existing unknown-name cases. The characterization test passes under that
bypass, correctly.

### What this does not make permanent

Isolation is a property of the credential set, so it is true until somebody
edits `hub.env`. `hub/auth_matrix.py` should be re-run after any credential
change, and its exit status is 0 only for an exact identity matrix.

## 5. Re-measured after the closeout edits

Run on `phase0/closeout` at `39f39a8`, after the credential-isolation work,
Python 3.11.3, Windows-10-10.0.26200-SP0.

```text
$ python -m pytest tests/ -q
83 passed in 0.71s
exit 0

$ python tests/bypass_matrix.py
guards proven load-bearing: 10/10
exit 0

$ python workspace/guard_check.py
FAILURES: none
exit 0

$ <venv>/python -m pytest hub/test_hub.py -q
43 passed, 2 warnings in 1.33s
exit 0
```

The worker figures are unchanged from the Phase 0 tip, which is the expected
result: nothing on this branch changes worker behaviour. The bypass matrix
reports the same ten guards load-bearing with the same expected failure counts,
including the surplus on `replies_addressed_to_a_peer` (caught 2, expected 1)
that it names rather than swallows.

The hub suite moved from 37 to 43, and the delta reconciles exactly against the
six cross-identity tests described in section 4 — one exhaustive over all twelve
ordered pairs, three named `chatgpt` cases, one admin-authority case, one
characterization of the shared-secret hazard.

Two changes are not covered by a test and are not claimed to be.
`POLL_SECONDS=60` is a launcher default whose effect is a request rate rather
than a behaviour. The per-worker credential handoff is batch-file behaviour that
pytest cannot reach; it was verified by running the launcher itself against stub
workers, in both the all-present and missing-credential cases, with the results
in section 4.

## 6. Where Phase 0 stands

| Protocol section 19, Phase 0 | State |
| --- | --- |
| 1. Rotate exposed credentials | **Done.** Rotation 2026-09-09, operator-attested (section 1). Exposure history scanned the same day: 1134 of 1134 text cells, 0 matches (section 3). |
| 2. Authenticate every endpoint, bind identity server-side | **Done.** `hub/hub.py`, byte-matched to the deployed SHA-256. Identity separation verified against the live hub: exact identity matrix, 0 of 12 cross pairs authenticated (section 4). |
| 3. Workers ignore agent chat for activation | Done. Proven dynamically and by call graph. |
| 4. Visible global pause, verified | Done. Demonstrated live. |

Evidence for 2, 3 and 4 is in `docs/PHASE0_VERIFICATION.md`, re-measured rather
than carried forward.

**Nothing in Phase 0 remains open.** All four requirements are closed and
recorded, and every claim above is either a measurement reproducible from the
commands in this document and in `docs/PHASE0_VERIFICATION.md`, or is labelled
as an operator attestation where it is one.

One standing obligation outlives the sign-off, and it is a re-check rather than
an open item: identity separation is a property of the credential set rather
than of the code, so `hub/auth_matrix.py` needs re-running after any change to
`hub.env`. Nothing in the hub will notice if that property stops holding.

## 7. Positions accepted from the review

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

## 8. Branch and scope

`phase0/closeout` branches from `phase0/containment` and contains no controller
code, so it can be reviewed and merged without carrying Phase 1 with it. The
branch as it stood when this document was written, newest first — this
document's own commit is necessarily not in its own list:

```text
e443ac3 Correct the worker credential procedure this document got wrong
39f39a8 Hand each worker only its own hub credential
f01702e Assert a valid secret cannot borrow another component's name
84123ec Check that a credential authenticates one identity, not several
56036c3 Close the marker now that both halves of the item are answered
fd72c3e Record the hub database scan, which came back clean
688e6dc Point the open item at the record that closed half of it
92cada3 Close Phase 0 with the rotation recorded and the last gap named
d53272c Scan the hub database without being able to read what it finds
3d8567d Slow the chat poll from three seconds to sixty
10d7599 Warn about the credential that now stops every worker
f6bda95 Stop the docstring describing a hub that no longer exists
cd73898 Mark what this record got right on the day and wrong since
c0d5c98 Answer the Phase 0 review with measurements instead of claims
d14ed37 Commit the protocol the code already claims to enforce
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
