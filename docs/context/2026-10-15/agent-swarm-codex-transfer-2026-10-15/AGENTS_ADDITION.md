# Suggested addition to existing project instructions

Reconcile this text with existing OfficePC global/repository/nested instructions. It is not a replacement AGENTS.md and has not been installed.

- Read the maintained project checkpoint before continuing Agent Swarm work; the initial transfer checkpoint is `CURRENT_STATE.md` in the October 15 context package. Keep long history in reference documents, outside automatic instructions.
- Develop in the development checkout. Keep the pinned production checkout and scheduled supervisor isolated from feature branches.
- Bind reviews, CI evidence and merges to exact commits. A changed candidate invalidates the old verdict. Distinguish local or relayed review evidence from a controller-issued verdict.
- Preserve the ledger's meaning. Use supported controller routes and append corrections; never patch historical instructions or approvals to make an outcome appear valid.
- Follow accepted `docs/design/74-external-review.md` and issues #91–95. External reviews end in a verdict and never enter integration. Implement activation lease/deadline recovery before exposing assigned/running external states.
- Use the supported controls and parity checks for production. Follow the existing operator merge/deploy/real-task gate and already-granted access permissions.
- On Windows select Git Bash explicitly for Bash-dependent tests. Report host skips and partial reruns accurately. Mutation-test correctness guards as required by the project design.
- Update the checkpoint after verified work: exact SHA, checks, actual deployment evidence, remaining risks and next action. Historical records do not establish current runtime state.
