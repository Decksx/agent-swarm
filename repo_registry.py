"""Which checkout is authoritative, and which commit is the baseline.

Why this exists
---------------

A snapshot was generated against `D:\\Documents\\ComicAutomation` because that
path was passed to a command. It is a real checkout of the real project, on a
feature branch, at a commit six weeks behind, with fourteen uncommitted files.
Nothing about it was malformed. A planner handed it would have produced a
confident plan against code that has since been rewritten, and the first sign
of trouble would have been an author failing to find a file.

`repo_id` cannot prevent that. It identifies a *lineage* -- both checkouts have
the same root commits, the same origin, and therefore the same id, which is
correct and is exactly why identity is not the answer. Nor can "the checkout
looks right": `C:\\git\\ComicAutomation` is the authoritative one and its
working tree currently sits on `slice4b1/artifact-reader-and-applied-projection`
with nine uncommitted files.

So which checkout, and which commit, are configuration. Not a default, not an
inference, not an argument somebody types each time. A project is named; the
name resolves through this registry or it does not resolve.

What each entry states
----------------------

* `path`          -- the canonical checkout. The only one that counts.
* `repo_id`       -- what that path must contain. A path repointed at another
                     project, or replaced by a fresh clone of something else,
                     stops resolving instead of being planned against.
* `planning_ref`  -- the ref the baseline comes from, in full: `refs/heads/
                     master`, never `master`. A bare name can match a branch
                     and a tag at once, and git resolves that ambiguity with a
                     warning nobody reads. A full refname cannot be ambiguous.
* `worktree_root` -- where task execution happens. Never inside the canonical
                     checkout, which is dirty and stays that way.

The ref is resolved once
------------------------

`resolve()` turns the planning ref into one full SHA, and everything downstream
takes the SHA. A ref is a moving target: resolving it again at review time, or
in the author's worktree, would mean the plan, the snapshot and the candidate
each described whatever `master` pointed at when they happened to look.

The commit is not the working tree
----------------------------------

The baseline is read from the resolved commit. The canonical checkout's own
HEAD, its branch, and its uncommitted files have nothing to do with it -- they
are reported separately, as operational context, so a planner can see that work
is in flight without any of it entering the baseline it plans against.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Dict, Optional

# The committed registry is the default; SWARM_REPOS overrides it. The paths
# in an entry are host-specific, so a host with a different layout -- or a
# throwaway registry for a demonstration -- points at its own file rather than
# editing the one under version control.
DEFAULT_REGISTRY = Path(
    os.environ.get("SWARM_REPOS") or Path(__file__).resolve().parent / "repos.json"
)


class RegistryError(Exception):
    """The registry itself is wrong."""


class ResolutionError(RegistryError):
    """A registered project cannot be planned against as it stands."""


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    repo_id: str
    planning_ref: str
    worktree_root: Path

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "repo_id": self.repo_id,
            "planning_ref": self.planning_ref,
            "worktree_root": str(self.worktree_root),
        }


@dataclass(frozen=True)
class Resolved:
    """One project, one commit. What the rest of the system is handed."""

    project: Project
    sha: str
    ref: str

    @property
    def name(self) -> str:
        return self.project.name

    @property
    def path(self) -> Path:
        return self.project.path


REQUIRED = ("path", "repo_id", "planning_ref", "worktree_root")


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False

    return True


def parse(name: str, entry: dict) -> Project:
    """One registry entry, validated as configuration rather than as input.

    Everything checkable without touching a disk is checked here, so a
    malformed registry fails when it is read rather than in the middle of a
    run against whichever field was wrong.
    """
    if not isinstance(entry, dict):
        raise RegistryError(f"{name}: entry is not an object")

    missing = [key for key in REQUIRED if not str(entry.get(key, "")).strip()]

    if missing:
        raise RegistryError(f"{name}: missing {', '.join(missing)}")

    ref = str(entry["planning_ref"]).strip()

    if not ref.startswith("refs/"):
        # The ambiguity this whole module exists to remove. `master` can name a
        # branch and a tag simultaneously, and git picks one with a warning on
        # stderr that no automated caller will ever read.
        raise RegistryError(
            f"{name}: planning_ref must be a full refname such as "
            f"refs/heads/master, not {ref!r}"
        )

    path = Path(str(entry["path"]).strip())
    worktree_root = Path(str(entry["worktree_root"]).strip())

    if _is_inside(worktree_root, path):
        raise RegistryError(
            f"{name}: worktree_root {worktree_root} is inside the canonical "
            f"checkout. Task worktrees would appear in its status and could be "
            f"committed into it by accident."
        )

    return Project(
        name=name,
        path=path,
        repo_id=str(entry["repo_id"]).strip(),
        planning_ref=ref,
        worktree_root=worktree_root,
    )


def load(path: Optional[Path] = None) -> Dict[str, Project]:
    """Every registered project, or raise.

    A registry that will not parse is not partially usable: the entry that
    happens to be readable might be the wrong one.
    """
    path = Path(path or DEFAULT_REGISTRY)

    if not path.exists():
        raise RegistryError(f"no registry at {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{path} is not valid JSON: {exc}")

    if not isinstance(raw, dict) or not raw:
        raise RegistryError(f"{path} does not define any projects")

    return {name: parse(name, entry) for name, entry in raw.items()}


def get(name: str, registry: Optional[Path] = None) -> Project:
    """One project by name, or raise naming what is registered.

    There is no path argument anywhere in this module's public surface. That
    is the correction: the way to reach a repository is to name a project, and
    a name either resolves to the configured checkout or does not resolve.
    """
    projects = load(registry)

    if name not in projects:
        raise RegistryError(
            f"{name!r} is not a registered project. Registered: "
            f"{', '.join(sorted(projects)) or '(none)'}"
        )

    return projects[name]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def resolve(project: Project, *, repo_id_of=None) -> Resolved:
    """Verify the checkout is the registered one and pin the planning ref.

    Three refusals, and each one is a state in which planning would otherwise
    proceed and produce something that looks like a plan:

    * the checkout is not there, or is not a repository -- typically a drive
      that did not mount, which otherwise reads as an empty project;
    * it is a repository, but not the registered one. A path repointed at
      another clone keeps working for every command except the one that
      matters;
    * the planning ref does not exist. A renamed default branch would
      otherwise fall back to whatever the checkout happened to be on, which is
      the original mistake with an extra step.

    `repo_id_of` is injectable so this module does not have to import the
    snapshot generator, which imports nothing from here in turn.
    """
    if repo_id_of is None:
        from repo_snapshot import repo_id as repo_id_of

    path = project.path

    if not path.exists():
        raise ResolutionError(
            f"{project.name}: {path} does not exist. It is unavailable, which "
            "is not the same as empty -- nothing may be planned against it."
        )

    if not (path / ".git").exists():
        raise ResolutionError(f"{project.name}: {path} is not a git repository")

    try:
        actual = repo_id_of(str(path))
    except Exception as exc:
        raise ResolutionError(f"{project.name}: cannot identify {path}: {exc}")

    if actual != project.repo_id:
        raise ResolutionError(
            f"{project.name}: {path} contains repository {actual}, but the "
            f"registry expects {project.repo_id}. Either the path now points "
            "at a different project, or the registry is stale. Both are "
            "reasons to stop."
        )

    result = _git(path, "rev-parse", "--verify", f"{project.planning_ref}^{{commit}}")

    if result.returncode != 0:
        raise ResolutionError(
            f"{project.name}: {project.planning_ref} does not exist in {path}. "
            "Refusing to fall back to whatever this checkout is currently on."
        )

    sha = (result.stdout or "").strip()

    if len(sha) != 40:
        raise ResolutionError(
            f"{project.name}: {project.planning_ref} did not resolve to a "
            f"commit sha (got {sha!r})"
        )

    return Resolved(project=project, sha=sha, ref=project.planning_ref)


def resolve_name(name: str, registry: Optional[Path] = None) -> Resolved:
    """`get` then `resolve`, which is how every caller uses this."""
    return resolve(get(name, registry))
