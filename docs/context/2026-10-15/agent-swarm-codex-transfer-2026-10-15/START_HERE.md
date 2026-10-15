# Agent Swarm: OfficePC Codex handoff

Prepared 2026-10-15 for David Johnson. Repository: https://github.com/Decksx/agent-swarm

This package carries the available Group AI Chat project documents, a current checkpoint, and the remote Codex review supplied by David. It is a document handoff, not a restored ChatGPT conversation or a Codex session database. It has not been installed on OfficePC. The raw test logs named in the remote review remain on OfficePC and are not included.

## Import into the existing OfficePC project

1. Extract this package into a new local folder, for example `C:\git\agent-swarm-context\2026-10-15`. This is a suggested destination, not a discovered existing folder. Keep the original documents available.
2. In the existing OfficePC Codex session, ask it to read this file and `CURRENT_STATE.md`, then `reviews/PR96-remote-review-2026-10-15.md`. Its existing session and local files remain useful; there is no need to clear them.
3. Have Codex inspect the development checkout's existing instructions and documentation. Merge useful context into its existing handoff/operations documents, preserving newer local information. `AGENTS_ADDITION.md` is a small suggested addition to the repo's instructions, not a replacement file. The GitHub root `AGENTS.md` lookup returned 404; OfficePC may still have untracked, global or nested instructions.
4. Keep the archive outside automatic agent instructions. Read particular historical records when a question requires them. If useful, maintain a concise project pointer in the existing `AGENTS.md` directing Codex to the current handoff. Codex reads AGENTS.md instructions before working: https://learn.chatgpt.com/docs/agent-configuration/agents-md
5. Reconcile live GitHub and host state before a merge or deployment. Follow the project's existing operator gate; this package records context and does not independently authorize a merge, deployment or real controller task.

Suggested prompt for the OfficePC session:

> Read START_HERE.md, CURRENT_STATE.md and the PR96 remote review in this transfer package. Import the relevant project knowledge into the existing development checkout's handoff/operations docs and add a short pointer in its existing agent instructions without replacing them. Preserve newer local evidence and classify archived records as historical. Recheck PR #96 head/base/CI and the current production build, pause state and processes. Prepare the exact-head merge/deploy plan for #96 and an implementation plan for #92, including activation recovery before external states become reachable. Continue reversible preparation within our existing permissions; retain the operator's existing merge/deploy/task gate. Do not manufacture a ledger-native verdict from this local review. Report what context you imported and the next concrete action.

## Contents and evidence

- `CURRENT_STATE.md`: current checkpoint, decisions, runtime layout, scope limits and next steps.
- `reviews/PR96-remote-review-2026-10-15.md`: the review supplied by David, transcribed without substantive changes.
- `sources/`: GitHub PR, CI, issue and accepted-design snapshots fetched during this handoff, plus the archive source inventory.
- `archive/Group AI Chat/`: all 33 non-image project records available in that folder: protocols, handoffs, pasted project history and review packets, including two existing review ZIPs. Duplicate filenames/copies are retained. Nine writing blocks are reconstructed as complete UTF-8 text and checked against their reported byte lengths.
- `AGENTS_ADDITION.md`: suggested concise project instructions to reconcile with existing instructions.
- `SHA256SUMS.txt`: integrity hashes for the other files in the package.

Nineteen image attachments were not copied. Full conversation transcripts beyond the available project documents, OfficePC working files, credentials, controller database, worker state/cursors, raw PR96 test logs and live host evidence are not part of this transfer. The snapshots do not replace the GitHub repository or the running controller ledger.

## Source priority

Current code, accepted design, live controller evidence and exact-head checks determine current behavior. Historical records explain decisions; they do not establish today's production state. Explicit current instructions from David control authorization. When sources disagree, retain the discrepancy and inspect it rather than silently rewriting history.

In particular, the archived `74-external-review.md` is an earlier draft. The accepted version is `sources/design-at-983e324.md`, corresponding to the merged PR #90 base of PR #96. The September 22 handoff lists PR #70 as open and production at `206fce8`; those are historical values, superseded by later records. A closed GitHub issue alone is not evidence its runtime feature is implemented.
