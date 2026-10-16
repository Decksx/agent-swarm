# Controller ingest cross-review

Candidate: `aaf3ec0487aaad961a50d1f39c21183654da750a`, PR #107.
Codex engineering review, not a controller-issued verdict. No GitHub review or
comment was posted. Claude owns fixes to this branch.

## Findings requiring changes

1. **P2: require an exact match for identifiers and digests.**
   `controller/external.py:383–389` uses `SHA_RE.match`, whose `$` accepts the
   position before a final newline. A report with both `head_sha` and
   `resolved_ref_sha` equal to 40 lowercase hex characters plus `\n` returns
   HTTP 200 and moves the task to READY_EXTERNAL_REVIEW. These are not commit
   SHAs, so later offline lookup/routing cannot use the registered candidate.
   The same issue affects `repo_id`, the body hash (when truncated), and signal
   commit sources. Use fullmatch for all bounded hex/slug identifiers, and add
   endpoint tests proving invalid reports record nothing and remain correctable.

2. **P2: reject invalid field types before set/dict membership.**
   At `controller/external.py:476` and `:520`, `pr_state: []` and
   `author_signals: [{"kind": [], "value": "x", "source": "pr_body"}]`
   raise TypeError rather than ReportInvalid. Both return HTTP 500 from the
   real ingest route, violating its 422 contract and causing the result client
   to retry an unchanged invalid report as a server failure. Failure reports
   with list/dict reason codes have the same membership problem at :545/:549.
   Check scalar types first, and test malformed nested JSON through HTTP,
   including a corrected submission after the 422.

Related strict-schema gaps: `pr_number: 102.0` and `schema_version: true`
are accepted by equality comparisons (:425/:464), despite the wire format's
integer rules. Require actual integer values, excluding booleans, in that
validation pass.

## Verified behavior

- Reworded contract #105 at `c622f22439a299757e916d50dc739b4a036c3d9c`
  matches the shared caller/replay/liveness/stage ordering. No remaining contract
  finding; merged with a head pin as `8bf9ea564ff8ba60a42c28afcf11906a26f9d79c`
  after all four candidate checks passed.
- Candidate #107 has all four checks green in CI run `38828730451`.
- Local controller/API/state/recovery selection: 252 passed, no skips/failures.
- Independent local probes against a temporary DB demonstrated acceptance of
  newline SHAs/repo IDs, a floating PR number, and a boolean schema version.
- HTTP probes against the actual router confirmed newline SHAs return 200 and
  the two malformed nested field examples above return 500.
- A local compatibility probe using the current #106 working tree against
  this controller registered open and merged PRs, including a Unicode body
  excerpt/full-body hash and a footer beyond the excerpt; an operator-SHA
  mismatch correctly ended in FAILED. These are temporary local test tasks,
  not tasks on the running controller.

The dedicated admin/result routes, stored-request activation inputs, host slot,
assigned/running recovery, OPERATOR boundary, replay handling and stopping
progression at READY_EXTERNAL_REVIEW are covered by the passing selection.
Worker dispatch stays unwired; no production configuration or deployment changed.
