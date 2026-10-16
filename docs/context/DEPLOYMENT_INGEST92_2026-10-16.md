# External ingest deployment and live proof — 2026-10-16

Codex owned this rollout under David's standing project authorization. Claude
reviewed dispatch #108 at `3f36189e51aeaa0349e6c6f7c0e598afd7a40a13` and
merged it as `15c1278a0a342b5888216cb9c639c85eec2218d0`. The merge tree
equals the reviewed candidate. Independent engineering approval is recorded at
https://github.com/Decksx/agent-swarm/pull/108#issuecomment-6219773081.

Both candidate CI 38929581674 and merged-main CI 38930791362 passed all four
checks. Candidate CI ran 2,330 core, 380 hub and eight bypass tests, without
failures/skips. Claude additionally reported 99 focused checks and three caught
mutations. Codex's prior dispatch verification caught nine selected mutations.
These reviews remain engineering evidence rather than controller verdicts.

## Gate, backup and rollout

Initial OfficePC production was clean at d249366, supervisor 9372 with workers
2152/7912/41944. Tower ran the old controller build cc1d4f0214fe, schema 6.
The controller had 120 done and six expired activations, with none live.

Used supported local pause and stop controls, confirmed zero live activations
again while paused, and reached zero workers. Tower backups are under
`/mnt/user/appdata/agent-swarm/data/backups/ingest92-20261016/`: consistent SQLite
backups of controller.db and chat.db (both quick checks passed), app archive,
original environment and container configuration. Credential-bearing backups
remain on Tower with restricted permissions. Local cursor, usage and hold state
was backed up outside Git in the import workspace's ingest92-state-backup.

Ran the full `deploy_controller.sh` gate from clean merged main with real
`C:\Python311\python.exe`, explicit Git Bash and PYTEST_ADDOPTS=-n 4. No test
selection, skip flag or deploy bypass was used:

- Core/worker suite, including bypass tests: 2,328 passed, ten local scheduled-
  task permission skips, zero failures, 226.24 seconds.
- Hub suite: 380 passed, zero failures/skips, 27.22 seconds.
- Total local gate: 2,708 passed, ten skips. CI exercised those ten successfully.

The script copied all 16 controller files, matched every remote digest, restarted
Tower and passed deployment parity. Recreated the container to load the project
maps, with PROGRESSION_INGESTER absent. Kept the immutable existing image,
network, ports, mounts, command, labels, restart policy and existing privilege
configuration. A post-recreate comparison caught the omitted original PID cap;
restored 2048 before enabling ingestion, and retained it on the final recreate.
Final checked options match the original (mount ordering is immaterial).

Production checkout advanced explicitly to detached 15c1278; every tracked file
was compared with its Git object bytes. All three component preflights passed
against Tower. Started the supervisor through pythonw/run_hidden.pyw and the
scheduled-task Git Bash path. Resumed with ingest disabled to verify fresh
workers, paused for the final configuration reload, then resumed again.

Effective Tower settings:

- INGRESS_PROJECTS: `agenthub=C:\git\agent-swarm`
- EXTERNAL_REVIEW_REPOS: `{"agenthub":"Decksx/agent-swarm"}`
- PROGRESSION_INGESTER: `claudecode`
- PROGRESSION_HOST: existing `officepc`

Only agenthub is externally enabled. The named checkout is the registered dev
repository; ingest writes refs, leaving its checked-out files and HEAD intact.
GitHub CLI login and repository read access passed using the worker's filtered
child environment under OFFICEPC\david before enablement. The existing Claude
guard setting still resolves to C:\swarm-prod\agent-swarm; usage/hold state was
preserved. Worker cursors remained 1490 and narrator cursor 525 before the proof.

## Real controller-issued proof

Created the following request through the supported admin CLI; the supervisor
issued it and the production Claude worker claimed it normally. No activation
or result was fabricated through bare ledger events.

| Evidence | Recorded value |
| --- | --- |
| Task | `EXT-92-PROOF-20261016-108` |
| Activation | `cd5243a16bad42b5a6407dbc83888365` |
| Stage / worker / status | ingest / claudecode / DONE |
| Target | merged PR #108, exact head `3f36189e51aeaa0349e6c6f7c0e598afd7a40a13` |
| Base and merge-base | `babea855d22a5dfa725e019091e5076a6fa3150a` |
| Registration event | `2069713513ac489cade44f769d6c9d64`, global seq 529 |
| Event authority | controller; report actor claudecode |
| Final task state | READY_EXTERNAL_REVIEW, state_seq 4 |
| Pin | `refs/swarm/external/EXT-92-PROOF-20261016-108` |
| Repository ID | `0dc8a2e4d227ab03` |

Exactly one registration event exists. Its head/resolved SHA match the request
and local pin; it records 12 changed files, three author signals including the
Codex commit trailer, and a verified full PR-body digest. Scratch refs for this
task are gone. Dev HEAD remains 15c1278 and its worktree is clean. Claude model
usage and hold files are byte-identical to the pre-rollout backup: no model call
was made. approved_candidate_sha remains null; there is no review judgment,
integration activation or PR-state change from this proof. The pin is retained
for later review work.

## Final runtime sample

- Production: clean, detached 15c1278.
- Controller loaded/disk/checkout build:
  `b598aacbbcea86b184fb887c9d5313099ce6ede9515ba0f210136cd689324f51`, schema 6.
- Container final start: 2026-10-16T16:45:11.056750587Z.
- Supervisor 45136, workers ChatGPT 3976, Gemini 46440, Claude 44268, all from
  production. Fresh supervisor heartbeat; one process for each identity.
- Hidden ensure exited 0; local PAUSED and STOPPED flags are absent.
- Anonymous status, external-request and ingest-result routes return 401.
- Activations: 121 done, six expired, zero live. The new task is awaiting review.

Local logs/curated proof receipt are in the original import workspace, and a
proof-receipt.json is stored beside Tower's rollout backup. A documentation
receipt merge does not require another runtime deployment.

## Next engineering handoff

#92 now has a deployed ingest proof. #93/#94 still supply external-review
routing, packets, verdicts and publication. The ready task has not been reviewed.
Issue #109 addresses a separate need: distinct identities and posting receipts
for the interactive leads. David's naming/routing decision is pending. GitHub
PR comments carry engineering reviews/handoffs; hive chat is the intended
project-level view. Session watchers and background workers do not by themselves
connect the interactive Codex and Claude sessions or provide always-on delivery.
