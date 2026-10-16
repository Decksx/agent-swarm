# Controller approval at 4907098

Reviewed candidate: `49070986140065bc7eb3a08991b0d5d97ce97fbf` (PR #107).
Codex engineering review: **approved, no remaining findings** at this commit.
This is not a controller-issued verdict. No GitHub review/comment was posted.
Claude owns the planned GitHub merge pinned to this head.

The delta from f75f10c moves canonical serialization/UTF-8 byte sizing into the
existing malformed-report catch without changing the independent 128-KiB limit.
Invalid surrogate strings now produce a static, encodable 422 diagnostic before
any event/result is recorded. A corrected submission is still accepted.

Evidence:

- All four checks are successful at this exact head in CI run `38847398634`.
- Independent local controller/API/state/recovery selection: 311 passed,
  no failures/skips.
- All nine new Unicode regressions detect the previous sizing-outside-catch
  implementation when restored in memory; no source file in Claude's worktree
  was modified. The real candidate passes those cases within the selection.
- The delta adds five controller and four real-HTTP regressions spanning title,
  body, author signal and failure detail, with corrected reports afterward.

Earlier exact-match/type/path/replay findings remain resolved. The worker's
contract amendments retain the same report fields and limits; standalone
trailing link lines accompany attribution but do not become signals.

The approved controller candidate is being combined with the corrected #106
worker in the isolated development branch for CI before dispatch is wired.
No production, deployment, Tower setting or real-controller task was changed.
