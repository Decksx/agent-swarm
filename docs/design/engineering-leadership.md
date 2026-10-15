# Selectable engineering leadership

Status: David confirmed both interactive leadership and selectable automated
planning on 2026-10-15. The first implementation is under development; it does
not change controller stage routing or enable chat-triggered execution.

## Requested behavior

Codex and Claude must both be able to guide engineering: investigate the
repository, propose architecture, decompose work, and assess implementation
progress. Gemini must not be the exclusive engineering lead. Keep Gemini as an
available contributor and independent reviewer, with its Argon model selection
handled separately in PR #101.

Choose one accountable lead for a workstream, with the other available to
challenge the design or take over. Leadership is a role, not a permanent
property of a model vendor. Allow David to change the lead without rewriting
task history or changing existing activations.

## Current code and gaps

- `plan_run.py` calls `ask_gemini` directly. `GEMINI_PLANNER_MODEL` and `--model`
  select a Gemini model, not another provider. Its saved-reply path can validate
  a supplied plan without calling a model.
- `controller/activations.py` assigns author, verifier and operator authority
  to stages. `controller/progression.py` advances tasks according to state and
  configured agents. These mechanisms are separate from planning a workstream.
- `supervisor.py` is a deterministic process supervisor. Replacing an
  engineering lead does not require giving a model its process-control role.
- `chatgpt_worker.py` is an API-backed worker. It is not this interactive Codex
  task, and it must not be relabelled as Codex CLI without an actual adapter.
- Hive messages are narration. Only authenticated operator commands and
  controller-issued activations authorize work; peer mentions cannot do so.

Codex and Claude executables are present on this Windows host. Their presence
alone does not establish unattended authentication, command compatibility or
successful planner calls. Verify those separately before enabling automation.

## Proposed first implementation

Introduce explicit planner-provider selection with adapters for Codex, Claude
and Gemini. Codex is the default; `--planner` or `SWARM_PLANNER` chooses the lead.
Keep repository snapshots,
context-request limits, plan validation and DRAFT-task creation in the common
pipeline. Provider adapters should return text or a clear failure; they should
not create tasks, grant permissions or bypass validation.

Resolve the model default for the selected provider. Preserve explicit model
selection and the saved-reply workflow. Record the actual provider, model,
source base and call count in plan evidence. The legacy `planner` field remains
the requested model selector, with `cli-default` when no selector is supplied.
`planner_provider` and `planner_source` distinguish live calls and saved replies.
`planner_reported_models` records the models a CLI reported using, including
auxiliary models, without designating one as the primary model;
an empty list means no concrete version was reported, not an inferred default.
For a saved reply, `planner` and `planner_provider` are null.

CLI children receive no inherited provider API keys or authentication-token
overrides; they use cached login credentials. `CODEX_CLI` and `CLAUDE_CLI` support
an explicit absolute executable path outside the app's inherited PATH. Windows
also reads these non-secret settings from the current user's Environment key.
Hosts authenticated only through `CLAUDE_CODE_OAUTH_TOKEN` or
`CODEX_ACCESS_TOKEN` must establish a stored CLI login before using planning;
these token overrides are intentionally excluded as well as API keys.

Claude planning requires an explicit `CLAUDE_RATE_GUARD_DIR` shared with the live
worker. Both read the same hold and usage files; planner duration is charged even
on failures/timeouts. The worker refreshes disk usage before checking its window,
and reads and completed-call merges take the same OS lock, including the open
read handle's lifetime, before atomic replacement. This preserves
the existing elapsed-model-time proxy, including its limits: it is not a provider
quota API or an in-flight token reservation. A worker upgrade/restart is required
before relying on shared accounting.

## Deployment note

This PR changes the Gemini worker system prompt from lead architect to engineering
reviewer as well as the operator planner default. Deploy notes must identify both.
It also updates Claude's shared-usage read/write path. On OfficePC the configured
guard directory points at the existing production state files; do not reset or
remove them or point a restarted worker at a fresh directory. Before restart,
check the effective setting against the existing usage and hold locations; moving
them would hide an active hold. The old worker does not refresh planner records
and can overwrite them on its next completed call. Do not run `--planner claude`
until the updated worker has been deployed/restarted through supported controls,
and its running source and effective state directory are verified. Only then
enable shared planning. No runtime deployment is implied by a source review.

For interactive leadership, record the chosen lead and workstream objective in
the maintained project context and handoffs. A lead proposes work for the same
controller path used today. The existing author/reviewer separation, exact
candidate evidence and operator merge/deployment gates still apply.

The first patch should cover selection, provider invocation, accurate evidence,
failure behavior and tests. It should not restore chat-triggered execution or
implement a new multi-agent debate loop. Controller role-policy changes should
be a separate, explicit design if they turn out to be needed.

## Immediate Claude assignment

Act as engineering co-lead. Review this design and its first implementation
against `AGENTS.md`, current source and `docs/design/74-external-review.md`.
Inspect `planner_cli.py`, `plan_run.py` and their tests for correct provider
selection, CLI authentication, disabled execution/integrations, call budgets,
validation and accurate provider/model evidence. Codex handles implementation
and rollout of this slice; Claude owns its independent engineering review.

Return findings with file/line references, missing acceptance tests and any
compatibility concerns. Then propose the next #92 ingress slice and a task split
between Claude and Codex, with Claude able to lead that slice. Identify any
conflicts with the accepted external-review design. Do not duplicate the Argon
rollout or start #92 implementation during this review assignment.

Do not merge, deploy, issue real controller tasks or alter live role routing as
part of this design assignment. Findings are an engineering review, not a
controller-ledger verdict.
