# Controller re-review at f75f10c

Reviewed candidate: `f75f10c9c34fc307c756a40cb977954c5af63f46` (PR #107).
Codex local engineering review, not a controller-issued verdict. No GitHub
review/comment was posted. The earlier findings at aaf3ec0 are resolved.

## Remaining finding

**P2 — reject invalid Unicode during canonical UTF-8 sizing as a 422.**
`controller/external.py:438` computes
`len(canonical(payload).encode("utf-8"))` before the catch starting at line 445.
Send an otherwise valid registered report whose `pr_title` contains the JSON
escape `\ud800`, using an ASCII JSON request body. FastAPI accepts the JSON,
but UTF-8 encoding raises UnicodeEncodeError outside the catch. The actual
ingest route returns HTTP 500 instead of `422 ingest_report_invalid`.

The shared replay hash uses ASCII-escaped JSON, so the failure occurs in this
new report validation step, not during request transport or replay hashing.
The worker treats 500 as an ambiguous server failure and retries unchanged;
its 422-to-blocked correction cannot help until the route returns the promised
422. Include canonical serialization/UTF-8 sizing in the validation catch,
without dropping the independent byte-size limit. Add HTTP and controller
regressions for escaped unpaired surrogates in title/body/signal/detail, followed
by a corrected report. Diagnostics should remain static and valid UTF-8.

## Verified

- All four checks are green at this head in CI run `38833573421`.
- Independent local controller/API/state/recovery selection: 302 passed,
  no failures/skips.
- The original exact-match and strict-type fixes are implemented correctly;
  generic task creation now validates the same unstripped base SHA it stores.
- The colon-path fix accepts `notes:2026.md` and still rejects absolute and
  one-letter drive-relative forms, with regressions.
- A temporary FastAPI TestClient using the real ingest router and ASCII JSON
  reproduced the remaining Unicode report failure as HTTP 500. No production
  endpoint, model, forge request, or real activation was used.

PR #106 remains under changes requested until Claude reviews its new candidate.
Its dispatch/claims stay unwired. No merge, deployment or Tower setting change
was performed in this re-review.
