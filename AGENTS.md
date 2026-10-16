# Agent Swarm project guidance

Read `docs/context/README.md`, then the maintained context at
`docs/context/2026-10-15/PROJECT_CONTEXT.md` before starting project work.
Consult the detailed checkpoint, accepted design, and individual historical
records as needed. Historical chat and protocols are reference material, not
execution requests or automatic instructions.

- Purpose: let Codex and Claude collaborate directly on projects such as the
  comic automation suite, independently check claims and keep work moving
  without David copying messages between chats. Judge swarm changes against
  that outcome. The interactive chats and background workers are distinct;
  do not claim that connecting one also connects the other.
- David chose #109 (interactive lead identities/posting), then the durable
  wake-up relay as the next scope on 2026-10-16. Park #93-95 behind that work.
  Approved identities are codex-lead and claude-lead; questions requiring his
  decision target @admin. Claude leads #109 implementation; Codex reviews.
- Post engineering reviews and handoffs as comments on the relevant GitHub PR,
  naming the exact commit, findings, checks and next owner. David authorized
  this project coordination on 2026-10-16. Link maintained review documents as
  supporting evidence; ensure the actionable handoff reaches the PR itself.
- Mirror each handoff, review, merge, deploy and question into the hive chat as
  one line with `lead_chat.py`, as `claude-lead` or `codex-lead`, so David can
  follow along. Questions for him go to `@admin`. Report only a `CONFIRMED`
  receipt as posted. Conventions: `docs/design/lead-chat.md`.
- Develop here in `C:\git\agent-swarm`. Keep the pinned production checkout at
  `C:\swarm-prod\agent-swarm` isolated from development branches.
- Codex and Claude may both lead engineering interactively and through the
  selectable planner. Choose one accountable lead per workstream; use the other
  for review or handoff. Gemini remains available as a planner/reviewer. Read
  `docs/design/engineering-leadership.md` for the interfaces and current assignment.
- Inspect existing changes before editing. Preserve other work and stage only
  files belonging to the current task. Do not add runtime logs, credentials,
  controller databases, worker state/cursors, or control artifacts to Git.
- Bind reviews, CI, and merge evidence to exact commits. Changed candidates need
  fresh review. Local or relayed reviews are not controller-ledger verdicts.
- Preserve ledger meaning. Use supported controller routes and append corrections;
  never alter historical instructions or approvals to imply an action occurred.
- Follow accepted `docs/design/74-external-review.md` and issues #91-95. External
  reviews end in verdicts and never enter integration. Implement activation
  lease/deadline recovery before exposing external assigned/running states.
- Use explicit Git Bash for Bash-dependent tests on Windows. Report partial
  reruns and host-dependent skips accurately. Mutation-check correctness guards.
- David gave standing explicit permission on 2026-10-15 for this project's
  commits, pushes, merges and deployments. Do not request that permission again
  for routine project operations. Keep exact-commit review/CI gates, supported
  production controls and parity checks. Real work still needs controller-issued
  activations; current instructions from David control authorization.
- Update the maintained context after verified work, recording exact commits,
  checks, deployment receipts where relevant, remaining gaps, and the next action.

The root README and older session handoffs include historical MVP status. Reconcile
them against current code and evidence rather than treating them as live status.
