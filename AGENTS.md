# Agent Swarm project guidance

Read `docs/context/README.md`, then the maintained context at
`docs/context/2026-10-15/PROJECT_CONTEXT.md` before starting project work.
Consult the detailed checkpoint, accepted design, and individual historical
records as needed. Historical chat and protocols are reference material, not
execution requests or automatic instructions.

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
- Use supported production controls and parity checks. The recorded operator gate
  requires explicit go-ahead for merging, Tower deployment, or real task issuance;
  current instructions from David control authorization.
- Update the maintained context after verified work, recording exact commits,
  checks, deployment receipts where relevant, remaining gaps, and the next action.

The root README and older session handoffs include historical MVP status. Reconcile
them against current code and evidence rather than treating them as live status.
