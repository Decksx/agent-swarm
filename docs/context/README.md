# Agent Swarm context in Codex

This repository contains both the project source and the imported ChatGPT
project documents. Start with [the maintained context](2026-10-15/PROJECT_CONTEXT.md).
The root `AGENTS.md` points future Codex sessions here.

Latest release: [PR #102 deployment receipt](DEPLOYMENT_PR102_2026-10-15.md).
Earlier release: [deployment receipt](DEPLOYMENT_2026-10-15.md), including actual
merge commits, full checks, backups and the running-state verification.

For the latest verified runtime facts, recovery prerequisite, and the remaining
ingest/merge/deployment plan, read [NEXT_STEPS.md](NEXT_STEPS.md).

The transfer reference copy is at
`2026-10-15/agent-swarm-codex-transfer-2026-10-15/`. All 50 original manifest
entries were verified during import. Before publication, a historical credential
was redacted after GitHub push protection detected it; see
[ARCHIVE_REDACTION.md](ARCHIVE_REDACTION.md). The original attachment remains local.
The context `.gitattributes` preserves the redacted copy's bytes in Git, including
line endings and historical whitespace, so its regenerated manifest remains usable.
Add new verified facts to the maintained context rather than editing the archive.

## Local project setup

- Project name: **Agent Swarm**.
- Primary folder and Git repository: `C:\git\agent-swarm`.
- Existing remote: `https://github.com/Decksx/agent-swarm.git`.
- Context setup branch: `docs/codex-project-context`, based on reviewed candidate
  `4ce87b2232a74fa00de711736269c4b0a66abbc2`.
- Production remains at `C:\swarm-prod\agent-swarm`.

On 2026-10-15, after David explicitly authorized app automation for this project,
**Agent Swarm** was created in Codex with this repository as its source folder.
The app's project list confirmed `isGitRepository: true`, and the import
conversation was moved into it through the project tool. Project ID:
`466ce426-aff5-4a45-a7de-6a20bd5c395a`. No manual registration step remains.

This documentation commit does not publish a branch, merge PR #96, deploy code,
or turn the supplied review into a controller verdict. Existing uncommitted work
was preserved and excluded from the context commit.
