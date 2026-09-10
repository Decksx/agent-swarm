"""A plan is a proposal, and the controller decides what it is worth.

Why this is not just a prompt
-----------------------------

A planner asked for "the next slice of work" returns prose, and prose is
persuasive in a way that has nothing to do with whether it is right. The
failure is not that a model plans badly -- it is that a plan reads as a
decision. Somebody skims five confident paragraphs, agrees, and the first
thing anybody checks is an author failing to find a file.

So the planner's output is parsed into a fixed shape and every field is
checked against something outside the plan: the snapshot it was made from, the
registry, the repository's own tree. What survives is a set of task
definitions. What does not survive is refused as a whole -- a plan is accepted
or it is not, never partially, because the parts refer to each other and a
plan minus its third task is a plan nobody wrote.

What the controller checks, and why each one
--------------------------------------------

* **base_sha matches the snapshot.** The planner does not choose what its work
  branches from. If it states one at all it must be the one it was given.

* **The plan is not stale.** A plan made against a baseline the planning ref
  has since moved off describes a repository that no longer exists. It is
  refused rather than rebased: the file it wanted changed may have been
  deleted in the meantime, and nothing in the plan would say so.

* **allowed_paths are real, safe, and narrow.** Same containment rules as an
  author's output, because they become an author's authority. The
  `UNRESTRICTED` marker is refused outright here -- a planner that could grant
  its own author the whole repository is the fail-open contract hole with an
  extra step, and this is the layer that was named as the place to stop it.

* **Dependencies form a DAG within the plan.** A cycle is not a scheduling
  problem to resolve later; it is a plan that cannot be executed, and saying
  so now costs nothing.

* **owner is an agent that exists.** A task assigned to nobody sits in
  READY_AUTHOR until a person notices.

* **Acceptance criteria are present and separate from the objective.** The
  reviewer judges against them. A plan that states only an objective produces
  a review with nothing to check against, which is how a review becomes a
  reaction to a diff.

Not validated
-------------

Whether the work is worth doing, whether the decomposition is sensible,
whether the estimate is realistic. Those are judgments, this is a parser, and
a parser that claimed to make them would be trusted for them.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence

# The same shape as the author's output contract, for the same reason: a model
# that explains itself before or after the block still produces a usable
# answer, and one that forgets the terminator produces an error rather than a
# truncated plan that happens to parse.
BEGIN = "<<<PLAN>>>"
END = "<<<END>>>"

# Deliberately small. Each is a decision about how a task is executed, and a
# planner inventing a new one is a planner deciding something nobody defined.
MODES = frozenset({"implement", "investigate", "document", "test"})

# A plan may not grant this. See parse_scope in authored_change: the marker is
# the one way to authorise a repository-wide change, and a model authoring the
# contract is exactly the case it must not cover.
UNRESTRICTED = "UNRESTRICTED"

MAX_TASKS = 12
MAX_PATHS_PER_TASK = 20


class PlanError(Exception):
    """The plan could not be accepted."""


def _block(text: str) -> str:
    """The content between the markers, or raise."""
    if not isinstance(text, str) or not text.strip():
        raise PlanError("the planner returned nothing")

    start = text.find(BEGIN)

    if start < 0:
        raise PlanError(
            f"no {BEGIN} block in the reply; refusing to read the prose around "
            "it as a plan"
        )

    end = text.find(END, start)

    if end < 0:
        raise PlanError(
            f"the {BEGIN} block is not terminated by {END}; the plan may be "
            "truncated and a truncated plan can still parse"
        )

    return text[start + len(BEGIN):end].strip()


def _safe_path(raw: str, *, task_id: str) -> str:
    """One allowed path, or raise. Same rules an author's paths are held to.

    These become an author's write authority, so they are checked here rather
    than trusted because a model produced them earlier in the pipeline.
    """
    candidate = str(raw or "").strip().replace("\\", "/")

    if not candidate:
        raise PlanError(f"{task_id}: an empty allowed_path")

    if candidate == UNRESTRICTED:
        raise PlanError(
            f"{task_id}: a plan may not grant {UNRESTRICTED}. Repository-wide "
            "authority is an operator's decision, not a planner's."
        )

    pure = PurePosixPath(candidate)

    if pure.is_absolute() or candidate.startswith("/"):
        raise PlanError(f"{task_id}: absolute path {raw!r}")

    if re.match(r"^[A-Za-z]:", candidate):
        raise PlanError(f"{task_id}: drive-qualified path {raw!r}")

    if ".." in pure.parts:
        raise PlanError(f"{task_id}: {raw!r} escapes the repository")

    if ".git" in pure.parts:
        raise PlanError(f"{task_id}: {raw!r} is inside .git")

    if "*" in candidate or "?" in candidate:
        # A glob is not a path. It would be matched by nothing downstream --
        # `matches_allowed` compares path components -- so it would silently
        # authorise less than it appears to.
        raise PlanError(
            f"{task_id}: {raw!r} looks like a glob; allowed_paths are files "
            "and directories, matched by path component"
        )

    return candidate


def _one_task(raw: dict, *, index: int, owners: Sequence[str]) -> dict:
    if not isinstance(raw, dict):
        raise PlanError(f"task {index}: not an object")

    task_id = str(raw.get("task_id") or "").strip()

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", task_id):
        raise PlanError(
            f"task {index}: task_id {task_id!r} is not a short identifier"
        )

    objective = str(raw.get("objective") or "").strip()

    if len(objective) < 20:
        raise PlanError(
            f"{task_id}: the objective is {len(objective)} characters. An "
            "objective an author cannot act on is not an objective."
        )

    criteria = raw.get("acceptance_criteria")

    if not isinstance(criteria, list) or not criteria:
        raise PlanError(
            f"{task_id}: no acceptance_criteria. The reviewer judges against "
            "these; without them a review is a reaction to a diff."
        )

    criteria = [str(entry).strip() for entry in criteria if str(entry).strip()]

    if not criteria:
        raise PlanError(f"{task_id}: acceptance_criteria are all empty")

    owner = str(raw.get("owner") or "").strip().lower()

    if owner not in owners:
        raise PlanError(
            f"{task_id}: owner {owner!r} is not one of {', '.join(sorted(owners))}"
        )

    mode = str(raw.get("mode") or "").strip().lower()

    if mode not in MODES:
        raise PlanError(
            f"{task_id}: mode {mode!r} is not one of {', '.join(sorted(MODES))}"
        )

    paths = raw.get("allowed_paths")

    if not isinstance(paths, list) or not paths:
        raise PlanError(
            f"{task_id}: no allowed_paths. A task that may touch nothing "
            "cannot be authored, and one that says nothing is refused."
        )

    if len(paths) > MAX_PATHS_PER_TASK:
        raise PlanError(
            f"{task_id}: {len(paths)} allowed_paths; more than "
            f"{MAX_PATHS_PER_TASK} is a task that has not been decomposed"
        )

    allowed = [_safe_path(entry, task_id=task_id) for entry in paths]

    depends = raw.get("dependencies") or []

    if not isinstance(depends, list):
        raise PlanError(f"{task_id}: dependencies is not a list")

    return {
        "task_id": task_id,
        "title": str(raw.get("title") or objective[:60]).strip(),
        "objective": objective,
        "acceptance_criteria": criteria,
        "owner": owner,
        "mode": mode,
        "allowed_paths": allowed,
        "dependencies": [str(entry).strip() for entry in depends if str(entry).strip()],
    }


def _check_dependencies(tasks: List[dict]) -> None:
    """Every dependency names a task in this plan, and there are no cycles."""
    ids = [task["task_id"] for task in tasks]

    if len(set(ids)) != len(ids):
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        raise PlanError(f"duplicate task_id: {', '.join(duplicated)}")

    known = set(ids)

    for task in tasks:
        for dependency in task["dependencies"]:
            if dependency == task["task_id"]:
                raise PlanError(f"{task['task_id']} depends on itself")

            if dependency not in known:
                raise PlanError(
                    f"{task['task_id']} depends on {dependency!r}, which is "
                    "not in this plan"
                )

    # Kahn's algorithm; what is left over when nothing else can be removed is
    # exactly the cycle, and naming it beats reporting that one exists.
    remaining = {task["task_id"]: set(task["dependencies"]) for task in tasks}

    while True:
        ready = [name for name, deps in remaining.items() if not deps]

        if not ready:
            break

        for name in ready:
            del remaining[name]

        for deps in remaining.values():
            deps.difference_update(ready)

    if remaining:
        raise PlanError(
            "the dependencies contain a cycle among: "
            + ", ".join(sorted(remaining))
        )


def parse(
    text: str,
    *,
    snapshot: dict,
    owners: Sequence[str] = ("chatgpt", "claudecode", "gemini"),
) -> dict:
    """Turn a planner's reply into task definitions, or refuse the whole plan.

    `snapshot` is what the planner was shown. Its `base_sha` and `repo_id` are
    copied onto the plan here rather than read from the reply: the planner does
    not get to say what its work branches from, and a plan that names a
    different base is not corrected, it is refused.
    """
    body = _block(text)

    try:
        parsed = json.loads(body)
    except ValueError as exc:
        raise PlanError(f"the plan block is not valid JSON: {exc}")

    if isinstance(parsed, list):
        parsed = {"tasks": parsed}

    if not isinstance(parsed, dict):
        raise PlanError("the plan block is not an object")

    declared_base = str(parsed.get("base_sha") or "").strip()

    if declared_base and declared_base != snapshot["base_sha"]:
        raise PlanError(
            f"the plan names base {declared_base[:12]}, but it was made from "
            f"{snapshot['base_sha'][:12]}. Refusing a plan that disagrees "
            "with its own evidence about what it was planned against."
        )

    raw_tasks = parsed.get("tasks")

    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise PlanError("the plan contains no tasks")

    if len(raw_tasks) > MAX_TASKS:
        raise PlanError(
            f"{len(raw_tasks)} tasks; more than {MAX_TASKS} in one plan is a "
            "plan that should be several"
        )

    tasks = [
        _one_task(entry, index=index, owners=[o.lower() for o in owners])
        for index, entry in enumerate(raw_tasks)
    ]

    _check_dependencies(tasks)

    return {
        "project": snapshot["project"],
        "repo_id": snapshot["repo_id"],
        "planning_ref": snapshot["planning_ref"],
        "base_sha": snapshot["base_sha"],
        "summary": str(parsed.get("summary") or "").strip(),
        "tasks": tasks,
    }


def is_stale(plan: dict, resolved) -> Optional[str]:
    """Why this plan can no longer be executed, or None.

    A plan is evidence about one commit. When the planning ref moves, the plan
    still reads as current -- every path in it still looks plausible -- and
    that is exactly why this is checked mechanically rather than noticed.

    Refused rather than rebased. The intervening commits may have deleted the
    file a task was written to change, and nothing in the plan would say so.
    """
    if plan.get("repo_id") != resolved.project.repo_id:
        return (
            f"the plan was made against repository {plan.get('repo_id')}, and "
            f"{resolved.name} is {resolved.project.repo_id}"
        )

    if plan.get("planning_ref") != resolved.ref:
        return (
            f"the plan was made against {plan.get('planning_ref')}, and the "
            f"registry now says {resolved.ref}"
        )

    if plan.get("base_sha") != resolved.sha:
        return (
            f"the plan was made against {str(plan.get('base_sha'))[:12]}, and "
            f"{resolved.ref} is now at {resolved.sha[:12]}"
        )

    return None


def render_prompt(snapshot_text: str, guidance: str = "") -> str:
    """The planner's prompt: the snapshot, then the question, then the form.

    The snapshot is evidence and carries no instructions of its own -- that is
    why `repo_snapshot.render` produces a document rather than a prompt. This
    is where the asking happens.
    """
    parts = [
        "You are planning work on a repository. Below is a snapshot of it, "
        "taken from the repository itself.",
        "",
        "Read the OMITTED OR TRUNCATED section. It says what you were not "
        "shown. If the plan you would write depends on something that is not "
        "here, say so in the summary rather than assuming it.",
        "",
        "=" * 70,
        snapshot_text,
        "=" * 70,
        "",
    ]

    if guidance.strip():
        parts += ["WHAT IS BEING ASKED FOR", guidance.strip(), ""]

    parts += [
        "-" * 60,
        f"Answer with one {BEGIN} block containing JSON, terminated by {END}, "
        "and nothing else that matters. This shape exactly:",
        "",
        BEGIN,
        json.dumps({
            "summary": "one or two sentences on what this plan does and what "
                       "you were unsure of",
            "tasks": [{
                "task_id": "SHORT-1",
                "title": "a few words",
                "objective": "what this task must achieve, in enough detail "
                             "that somebody who cannot see this plan could do it",
                "acceptance_criteria": [
                    "a checkable statement that must be true when it is done",
                    "another one",
                ],
                "owner": "chatgpt",
                "mode": "implement",
                "allowed_paths": ["path/that/may/be/written"],
                "dependencies": [],
            }],
        }, indent=2),
        END,
        "",
        "Rules, each of which is checked and will reject the whole plan:",
        f"- mode is one of: {', '.join(sorted(MODES))}.",
        "- allowed_paths are real repository-relative paths, not globs. They "
        "become the author's write authority, so name the narrowest set that "
        "can do the work.",
        f"- {UNRESTRICTED} is not available to you. If a task genuinely needs "
        "repository-wide access, say so in the summary and let a person decide.",
        "- dependencies name task_ids in this same plan and must not form a "
        "cycle.",
        "- acceptance_criteria are what a reviewer will judge the work "
        "against. They must be checkable by reading a diff.",
        "- Do not state a base_sha. The controller supplies it; it is the "
        "commit the snapshot describes.",
        "",
        "If the snapshot does not give you enough to plan against, answer with "
        "a plan containing one task in mode 'investigate' that would get it.",
    ]

    return "\n".join(parts)
