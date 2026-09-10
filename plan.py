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

* **context_paths are separate from allowed_paths, and read-only.** Write
  authority and reading list are different questions and were being answered
  by one field. An author given only the files it may write has to infer the
  interfaces it calls, the callers it must not break and the tests that pin
  its behaviour -- and a model that infers them writes something plausible,
  which is the most expensive kind of wrong because a reviewer has to read
  carefully to catch it. Widening allowed_paths to fix that is the wrong
  correction: it buys understanding with authority, and the author only needed
  the first. So the plan states both, and the contract carries both, and the
  author is refused a write to anything in the second.

* **Concurrent tasks do not overlap in what they may write.** Two tasks with
  no dependency between them may be authored at the same time from the same
  base. If their writable paths intersect, one of them is authored against a
  tree that does not contain the other's change, and whichever integrates
  second is either a conflict or a silent revert. A dependency edge is how a
  plan says "these touch the same thing"; without one, saying so here is the
  only chance anybody gets before both branches exist.

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

# Higher than the writable cap on purpose. Reading is cheap and understanding
# is the thing that was missing, so this is generous -- but not unbounded: a
# reading list longer than this is a request for the repository, and the
# budget would then decide which files the author actually saw, silently and
# by file order.
MAX_CONTEXT_PATHS_PER_TASK = 40


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


def _safe_path(raw: str, *, task_id: str, field: str = "allowed_paths") -> str:
    """One path from a plan, or raise. Same rules an author's paths are held to.

    Shared by allowed_paths and context_paths. The containment rules are
    identical -- neither may escape the repository, reach into .git, or arrive
    as a glob -- because both are handed to the harness as repository-relative
    paths and read the same way. What differs is what the path then permits,
    and that is decided by which list it is in, not by this function.

    These become an author's write authority, so they are checked here rather
    than trusted because a model produced them earlier in the pipeline.
    """
    candidate = str(raw or "").strip().replace("\\", "/")

    if not candidate:
        raise PlanError(f"{task_id}: an empty entry in {field}")

    if candidate == UNRESTRICTED:
        if field == "context_paths":
            raise PlanError(
                f"{task_id}: {UNRESTRICTED} in context_paths. A reading list "
                "of everything is not a reading list -- the context budget "
                "would decide which files the author actually saw, in tree "
                "order. Name the files."
            )

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
        raise PlanError(f"{task_id}: {raw!r} in {field} escapes the repository")

    if ".git" in pure.parts:
        raise PlanError(f"{task_id}: {raw!r} in {field} is inside .git")

    if "*" in candidate or "?" in candidate:
        # A glob is not a path. It would be matched by nothing downstream --
        # `matches_allowed` compares path components -- so it would silently
        # authorise less than it appears to.
        raise PlanError(
            f"{task_id}: {raw!r} looks like a glob; {field} are files "
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

    # Read-only, and optional -- a task genuinely may need nothing but its own
    # files. Empty is a statement the planner is allowed to make; the failure
    # this guards against is the opposite one, a planner widening allowed_paths
    # to see a file it only needed to read.
    context_raw = raw.get("context_paths") or []

    if isinstance(context_raw, str):
        raise PlanError(
            f"{task_id}: context_paths is a string. It is a list of paths, and "
            "a string here would be read one character at a time."
        )

    if not isinstance(context_raw, list):
        raise PlanError(f"{task_id}: context_paths is not a list")

    if len(context_raw) > MAX_CONTEXT_PATHS_PER_TASK:
        raise PlanError(
            f"{task_id}: {len(context_raw)} context_paths; more than "
            f"{MAX_CONTEXT_PATHS_PER_TASK} is a request for the repository, "
            "and the context budget would then choose what the author saw"
        )

    context = [
        _safe_path(entry, task_id=task_id, field="context_paths")
        for entry in context_raw
    ]

    # A path that is writable is already shown to the author in full. Naming it
    # again as read-only would put two statements about one file in the same
    # prompt, the second one taking away what the first granted, and the
    # author has no way to tell which was meant. Refused rather than quietly
    # dropped, because at plan time it is more likely a confusion about which
    # list the path belonged in -- and that confusion is worth surfacing while
    # somebody can still say which one was meant.
    overlapping = sorted({
        entry for entry in context if _covered(entry, allowed) or any(
            _covered(path, [entry]) for path in allowed
        )
    })

    if overlapping:
        raise PlanError(
            f"{task_id}: {', '.join(overlapping)} appears in both "
            "allowed_paths and context_paths. A path is writable or it is "
            "reference material; it cannot be both, and the author would be "
            "given both statements at once."
        )

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
        "context_paths": context,
        "dependencies": [str(entry).strip() for entry in depends if str(entry).strip()],
    }


def _covered(path: str, entries: Sequence[str]) -> bool:
    """Whether `path` falls under one of `entries`, by path component.

    The same rule `authored_change.matches_allowed` enforces at write time,
    and it must stay the same rule: a plan that this accepts and the harness
    then refuses is a plan that fails halfway through, after branches exist.
    Components rather than string prefixes, so `notes` does not cover
    `notes-secret/x` -- a `startswith` check would say it did.
    """
    target = PurePosixPath((path or "").strip().replace("\\", "/").strip("/"))

    for raw in entries:
        pattern = PurePosixPath((raw or "").strip().replace("\\", "/").strip("/"))

        if not pattern.parts or not target.parts:
            continue

        if target.parts[: len(pattern.parts)] == pattern.parts:
            return True

    return False


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


def _ordering(tasks: List[dict]) -> Dict[str, set]:
    """For each task, every task that must finish before it can start.

    The transitive closure, not just the declared edges. `C depends on B` and
    `B depends on A` orders C after A even though C never mentions A, and a
    collision check working from declared edges alone would call A and C
    concurrent and refuse a plan that is fine.

    Called after the cycle check, so iterating to a fixed point terminates.
    """
    closure = {task["task_id"]: set(task["dependencies"]) for task in tasks}
    changed = True

    while changed:
        changed = False

        for name, deps in closure.items():
            grown = set(deps)

            for dependency in deps:
                grown |= closure.get(dependency, set())

            if grown != deps:
                closure[name] = grown
                changed = True

    return closure


def _check_concurrent_writes(tasks: List[dict]) -> None:
    """Two tasks that may run at once must not write the same paths.

    "At once" is not a scheduling detail this can look up -- nothing has been
    scheduled yet. It is a property of the plan: two tasks with no dependency
    path between them, in either direction, are two tasks the plan is saying
    may be authored simultaneously, from the same base commit, in separate
    worktrees that cannot see each other.

    What goes wrong is quiet. Both authors are shown the same file at the same
    base and both return its complete contents, because the output contract
    requires the whole file. The second one to integrate does not conflict in
    the interesting case -- it simply carries the base version of the other
    task's edit, and the first task's change disappears with nothing anywhere
    reporting a failure. Both tasks are approved. Both branches exist. One
    change is gone.

    A dependency edge is the plan's way of saying two tasks touch the same
    thing. This is the only moment anybody gets to notice that one is missing
    before the branches exist, so the plan is refused and the planner is told
    which pair and which path.

    Only writable paths. context_paths are read-only and may overlap freely --
    two tasks reading the same interface is what a shared interface is for.
    """
    ordered = _ordering(tasks)

    for i, first in enumerate(tasks):
        for second in tasks[i + 1:]:
            a, b = first["task_id"], second["task_id"]

            if b in ordered.get(a, set()) or a in ordered.get(b, set()):
                continue

            shared = sorted({
                path for path in first["allowed_paths"]
                if _covered(path, second["allowed_paths"])
            } | {
                path for path in second["allowed_paths"]
                if _covered(path, first["allowed_paths"])
            })

            if shared:
                raise PlanError(
                    f"{a} and {b} have no dependency between them, so they may "
                    f"be authored at the same time, but both may write "
                    f"{', '.join(shared)}. Whichever integrates second would "
                    "carry the base version of the other's file and silently "
                    "revert it. Either make one depend on the other, or give "
                    "them separate paths."
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
    _check_concurrent_writes(tasks)

    return {
        "project": snapshot["project"],
        "repo_id": snapshot["repo_id"],
        "planning_ref": snapshot["planning_ref"],
        "base_sha": snapshot["base_sha"],
        "summary": str(parsed.get("summary") or "").strip(),
        "tasks": tasks,
    }


def ground(plan: dict, repo: str, *, ls_tree=None) -> dict:
    """Check the plan's paths against the tree it claims to be planned against.

    `parse` is a parser: it can tell that a path is well formed and that two
    tasks collide, and it cannot tell that `comic_automation/scanner.py` is a
    file that exists. That takes the repository, and it is the check that
    catches the most expensive failure mode -- a confident plan against files
    the model inferred from a directory listing and a README.

    The two lists are held to different standards, and the difference is not
    an inconsistency:

    * **A context_path that does not exist is a defect.** It is reference
      material; the only thing it can be is a file that is already there. A
      missing one means the plan describes a tree that is not this one, and
      the author would silently receive a shorter reading list than the plan
      promised it.

    * **An allowed_path that does not exist may be perfectly correct.** Half
      the tasks worth planning create files. So these are reported, not
      refused -- named as `creates` so a reader can see at a glance whether a
      task claiming to edit a module is in fact about to invent one.

    Returns a report rather than raising. The caller decides: at planning time
    a missing context path should send the plan back to the planner, and a
    person reviewing proposals wants to see the whole picture at once rather
    than the first problem.
    """
    if ls_tree is None:
        def ls_tree(sha):
            import subprocess

            result = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", sha],
                cwd=str(repo), capture_output=True, encoding="utf-8",
                errors="replace", check=False,
            )

            if result.returncode != 0:
                raise PlanError(
                    f"could not read the tree at {str(sha)[:12]} in {repo}: "
                    f"{(result.stderr or '').strip()}"
                )

            return [
                line.strip()
                for line in (result.stdout or "").splitlines() if line.strip()
            ]

    tree = list(ls_tree(plan["base_sha"]))

    if not tree:
        # An empty tree matches nothing, so every path would be reported
        # missing and the report would read as a catastrophically wrong plan
        # rather than as a failed listing.
        raise PlanError(
            f"the tree at {plan['base_sha'][:12]} lists no files. Refusing to "
            "ground a plan against nothing -- every path would report missing."
        )

    tasks = []
    missing_context = 0

    for task in plan["tasks"]:
        def matched(entry):
            return [path for path in tree if _covered(path, [entry])]

        absent = [entry for entry in task["context_paths"] if not matched(entry)]
        creates = [entry for entry in task["allowed_paths"] if not matched(entry)]
        missing_context += len(absent)

        tasks.append({
            "task_id": task["task_id"],
            "missing_context": absent,
            "creates": creates,
            "edits": [
                entry for entry in task["allowed_paths"] if matched(entry)
            ],
            "context_files": sum(len(matched(e)) for e in task["context_paths"]),
        })

    return {
        "base_sha": plan["base_sha"],
        "tree_size": len(tree),
        "grounded": missing_context == 0,
        "missing_context_total": missing_context,
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
                "context_paths": ["path/that/must/be/read/to/do/it/right.py"],
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
        "- context_paths are files the author will be shown READ-ONLY, at this "
        "same commit, so it can see what its change has to fit: the module it "
        "imports from, the interface it implements, the caller it must not "
        "break, the test that pins the behaviour. The author has no shell and "
        "cannot open anything you do not list here. It sees the full current "
        "contents of its allowed_paths already, so do not repeat those.",
        "- Do NOT widen allowed_paths to let an author read something. That "
        "buys understanding with write authority, and a file listed as "
        "writable is a file that can come back rewritten. If it only needs "
        "reading, it is a context_path.",
        "- Every context_path must already exist at this commit. One that does "
        "not is refused: it means the plan was written against a different "
        "tree. allowed_paths may name files that do not exist yet, which is "
        "how a task creates one.",
        "- Two tasks with no dependency between them may run at the same time, "
        "so they must not list overlapping allowed_paths. If two tasks must "
        "touch the same file, make one depend on the other. Overlapping "
        "context_paths are fine -- reading is not writing.",
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
