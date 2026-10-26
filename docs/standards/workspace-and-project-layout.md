# Workspace and project layout standard

Status: adopted 2026-10-26 at David's request. It applies to every agent
(Claude, Codex, Gemini, subagents and workers) working in `C:\git` or in a
project repository. When this document and a habit disagree, this document wins.
Propose changes to it by PR, like any other code.

The aim is simple. `C:\git` holds projects, not leftovers. A repository's root
says what the project is, not what happened in it last week.

## 1. The `C:\git` workspace

```
C:\git\
├── .claude\                 # Claude Code project settings (not a project)
├── .claude-tools\           # claude-lead's helper scripts (hive watcher)
├── ComicAutomation\         # comic suite: primary checkout (GUI shortcut points here)
│   └── _related\            # git-ignored: satellite repos and assets for the comic suite
│       ├── autodecen\       # Camelia decensor app (its own repo)
│       ├── resolver\        # series import resolver (its own repo)
│       └── komga\           # Komga fork .jar builds
├── agent-swarm\             # swarm: development checkout (Codex's relay worktree links here)
│   └── _archive\            # git-ignored: retired swarm material kept for reference
├── anime-dub-auditor\       # other projects: one folder each, at the top level
├── dsjinfra\
├── SyncSettings\
├── Ubers-SD-Files\
├── HANDOFF_PRIVATE_2026-10-20.md
└── homelab-infrastructure.md
```

Production deployments live outside `C:\git` (for example
`C:\swarm-prod\agent-swarm`) and are only changed through their supported
deploy controls.

### Rules

1. **One top-level folder per primary project.** It is that project's main
   checkout. Do not add a second clone or worktree of a project at the top
   level.
2. **Satellites nest under their primary project.** A repository, tool or
   asset that exists to serve one project goes in that project's `_related\`
   folder, which is listed in the project's `.git\info\exclude`. Example:
   `autodecen` serves the comic suite, so it lives at
   `C:\git\ComicAutomation\_related\autodecen`.
3. **Review, test and mutation copies never go in `C:\git`.** Use your own
   scratch area:
   - Claude: the session scratchpad
     (`%LOCALAPPDATA%\Temp\claude\...\scratchpad`);
   - Codex: `%USERPROFILE%\.codex\worktrees\...` or its app's own
     worktree location;
   - other agents: a temp folder of their own.

   Name a copy after its purpose and the exact head it reviews, for example
   `review-138-cfb6c91`.
4. **Feature work for a PR** goes in a git worktree in the same scratch area,
   created from the primary checkout (`git worktree add <scratch>\<repo>-<topic> -b <branch>`).
   If David needs to open it himself, use `C:\git\_worktrees\<repo>\<topic>`
   instead; that folder is the only other place worktrees may live.
5. **Clean up after yourself.** When the PR merges or closes, or the review
   ends, remove the copy:
   - a worktree: `git worktree remove <path>`, then
     `git -C <primary> worktree prune`;
   - a clone: delete it only after checking that it has no modified or
     untracked files and that its HEAD is on a remote branch.

   Never use `--force` on anything you did not create. A copy you cannot prove
   clean and pushed is moved to the project's `_archive\`, not deleted.
6. **Retired material goes to `<project>\_archive\`** (git-ignored), never to a
   new dot-folder at the top level.
7. **No loose files at the top level** except the two notes shown above.
   Patches, PR bodies, downloads and build outputs belong in a scratch area or
   in the project that produced them.
8. **Do not move these** without David's say-so and a plan for each dependency:
   - `C:\git\ComicAutomation` (desktop shortcut "CBZ Automation");
   - `C:\git\agent-swarm` (Codex's relay workspace is a linked worktree of it);
   - `C:\git\.claude-tools` (claude-lead's hive watcher).

   Check scheduled tasks, shortcuts, relay registrations and other linked
   worktrees before moving anything else.
9. **Data never lives in a checkout.** Libraries, catalogs, databases, run logs
   and reports stay in their operational homes (`G:\ComicAutomation`, `X:\`,
   Tower). A repository holds only code, docs, configs and small test fixtures.

## 2. Repository layout

Every project uses this layout. Folders marked *when needed* are created only
once the project actually has that concern; empty placeholders are clutter.

```
<project>/
├── .github/                  # CI workflows, issue and PR templates
│   └── workflows/            #   ci.yml: lint and tests on every PR
├── .gitignore                # ignores logs/, results/, reports/, _related/, _archive/, caches
├── AGENTS.md                 # agent working rules (Codex reads this; points to CLAUDE.md and here)
├── CLAUDE.md                 # Claude working rules for this repository
├── README.md                 # what it is, quickstart, where the docs are
├── CHANGELOG.md              # when needed: releases and breaking changes
├── pyproject.toml            # metadata, dependencies, tool config (ruff, pytest)
├── <package>/                # core source package (e.g. comic_automation/), or src/<package>/
│   ├── core/ ...             #   domain logic
│   ├── database/             #   data access and migrations/
│   └── ...
├── apps/ or gui/             # when needed: GUI or frontend clients
├── scripts/                  # operator command-line entry points, thin wrappers over the package
├── tools/                    # developer-only diagnostics and maintenance utilities
├── config/                   # checked-in default configuration and schemas
├── migrations/ or db/        # when needed: versioned schema migrations and seeds
├── api/                      # when needed: interface contracts (OpenAPI and similar)
├── deploy/ and infra/        # when needed: deployment manifests, proxy and service configs
├── benchmarks/               # when needed: load and performance harnesses
├── docs/
│   ├── architecture.md       #   how the system fits together
│   ├── adr/ or engineering_decisions.md   # decision records
│   ├── design/               #   accepted designs, one file per feature
│   ├── context/              #   maintained agent context and handoffs
│   └── standards/            #   standards like this one
├── tests/
│   ├── conftest.py
│   ├── fixtures/             #   small static inputs only
│   ├── unit/, integration/   #   when the suite is large enough to split
│   └── e2e/                  #   when needed
├── logs/, results/, reports/ # git-ignored runtime output, if a tool must write inside the repo
├── _related/                 # git-ignored (local only): satellites, see section 1
└── _archive/                 # git-ignored (local only): retired material
```

### Rules

1. **New files go where this layout says.** Do not create new top-level
   folders or loose top-level files without a reason recorded in the PR.
2. **Existing deviations are fixed only by a dedicated PR.** That PR moves
   files, updates imports, docs and shortcuts, and runs the full suite. Never
   restructure as a side effect of feature work. Known deviations:
   - comic suite: `Logs/`, `progress_tracking/`, `archive/`,
     `cbz_sqlite_schema_phase1/`, `README_SQLITE_SCHEMA_PHASE1.md`,
     `pytest-of-david/`;
   - agent-swarm: `SWARM_PROTOCOL_v7.md` at the root.
3. **Line endings and encodings are preserved byte for byte** when moving or
   editing files.
4. **Generated output is never committed.** That covers logs, caches,
   databases, coverage, plans, reports and test temp folders. Add the pattern
   to `.gitignore` the first time a tool produces one.
5. **One concern per PR**, as today, with a single-file commit per file where
   the project's process asks for it.

## 3. Applying this standard

- **At the start of a task,** check `git worktree list` for the projects you
  touch. Remove your own stale copies (rule 1.5) before creating new ones.
- **When you hand work off,** say where your working copy is, and say when you
  have removed it.
- **Maintained context** records cleanups that change paths other agents or
  David depend on.
- **If you find clutter you did not create,** report it in the hive with the
  evidence (clean? pushed? in use?) instead of deleting it.
