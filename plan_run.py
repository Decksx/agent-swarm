"""Ask the planner for a plan, and refuse it before anybody acts on it.

What this is for
----------------

`plan.py` is a parser and `repo_snapshot.py` is a document generator, and
neither of them calls a model. This is the piece between them: resolve a
project, snapshot it, ask Gemini, and then put the answer through every check
there is before a single task exists in the controller.

The order matters. Every refusal below happens before the plan becomes state:

1. **Resolve for planning.** The name goes through the registry, and the
   registry may say the project is closed to new work. A demonstration
   repository whose branches are evidence is a repository a planner will
   happily plan against, because from the outside it looks small and
   improvable.
2. **Snapshot at one commit.** The ref is pinned once, here, and the SHA is
   what everything downstream uses. Resolving the ref again later would mean
   the plan, the tasks and the candidates each described whatever `master`
   pointed at when they happened to look.
3. **Parse.** Shape, owners, modes, paths, dependencies, acceptance criteria,
   write collisions between concurrent tasks. All of it against the snapshot
   rather than against the plan's own claims about itself.
4. **Ground.** The check the parser cannot do, because it needs the tree: does
   `comic_automation/scanner.py` exist. This is the one that catches a
   confident plan written against files inferred from a directory listing.
5. **Report.** Nothing is created. The plan is written out as JSON and as a
   readable summary, and a person decides.

Creating tasks is a separate command, and by default it creates them in DRAFT.
Nothing is queued, nothing is activated, and no author is given a contract
until somebody says so.

Why proposals rather than tasks
-------------------------------

A plan reads as a decision. Five confident paragraphs about work that sounds
plausible, a nod, and the first thing anybody verifies is an author failing to
find a file. The whole point of parsing it into a fixed shape is that the shape
can be checked -- and a check nobody looks at before the work starts is a check
that runs after the branches exist.

So the default is to produce proposals and stop. `--create` writes them to the
controller as DRAFT tasks, which is still short of executable: something has to
move each one to READY_AUTHOR, and that is deliberately not this program.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import plan
import repo_registry
import repo_snapshot

HERE = Path(__file__).resolve().parent

# The model that plans. Named here rather than taken from the environment: the
# planner's identity belongs in the evidence for a plan, and a variable
# somebody exported last week is not evidence.
GEMINI_MODEL = os.environ.get("GEMINI_PLANNER_MODEL", "gemini-3.6-flash")

# Who a plan may assign work to. The controller checks this again; it is here
# so the planner is told, rather than guessing and having the whole plan
# refused for a name it could not have known.
OWNERS = ("chatgpt", "claudecode", "gemini")


class PlanRunError(Exception):
    """The run could not produce a plan worth looking at."""


def ask_gemini(prompt: str, *, model: str = GEMINI_MODEL) -> str:
    """One planning call. Returns the reply text, or raises.

    Deliberately not resilient. A worker swallows a failed generation because
    one bad call must not kill a daemon that has to keep polling; this is a
    single operator-initiated run, and a run that quietly produced no plan
    would be indistinguishable from a run that produced an empty one.
    """
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()

    if not key:
        raise PlanRunError(
            "GEMINI_API_KEY is not set. It is read from the environment only, "
            "never from a file beside this one."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise PlanRunError(
            f"the Gemini SDK is not installed ({exc}). Install google-genai."
        )

    client = genai.Client(api_key=key)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # The planner is told what it is doing here, and everything
                # else it knows comes from the snapshot in the prompt. It has
                # no shell, no repository access, and no memory of the last
                # run: whatever is not in that document, it does not have.
                system_instruction=(
                    "You are planning work on a software repository you cannot "
                    "browse. Everything you know about it is in the snapshot "
                    "you are given. Plan only what that snapshot supports, and "
                    "say plainly in the summary where it does not support you."
                ),
            ),
        )
    except Exception as exc:
        raise PlanRunError(f"the planning call failed: {exc}")

    reply = (getattr(response, "text", None) or "").strip()

    if not reply:
        raise PlanRunError(
            "the planner returned no text. A safety block and an empty answer "
            "look the same from here, and neither is a plan."
        )

    return reply


def render_report(parsed: dict, grounding: dict, snapshot: dict) -> str:
    """The plan as something a person can decide about in one screen.

    Grounding is interleaved with each task rather than appended as a section.
    A reader deciding whether a task is sensible needs to know that its context
    file does not exist at the same moment they read the objective, not four
    tasks later.
    """
    ordered = {entry["task_id"]: entry for entry in grounding["tasks"]}
    lines = [
        f"PLAN for {parsed['project']} at {parsed['base_sha'][:12]}",
        f"  ref      {parsed['planning_ref']}",
        f"  repo_id  {parsed['repo_id']}",
        f"  tree     {grounding['tree_size']:,} files",
        f"  tasks    {len(parsed['tasks'])}",
        "",
        "SUMMARY (the planner's own words, including what it was unsure of)",
        parsed["summary"] or "(the planner wrote none)",
        "",
    ]

    for task in parsed["tasks"]:
        report = ordered[task["task_id"]]
        lines += [
            "-" * 70,
            f"{task['task_id']}  [{task['mode']}]  -> {task['owner']}",
            f"  {task['title']}",
            "",
            "  objective:",
            *(f"    {line}" for line in task["objective"].splitlines()),
            "",
            "  acceptance criteria:",
            *(f"    - {entry}" for entry in task["acceptance_criteria"]),
            "",
            f"  writes  ({len(task['allowed_paths'])}):",
        ]

        for entry in task["allowed_paths"]:
            mark = "creates" if entry in report["creates"] else "edits  "
            lines.append(f"    {mark}  {entry}")

        lines.append(
            f"  reads   ({len(task['context_paths'])} entries, "
            f"{report['context_files']} files):"
        )

        for entry in task["context_paths"]:
            mark = "MISSING" if entry in report["missing_context"] else "ok     "
            lines.append(f"    {mark}  {entry}")

        if not task["context_paths"]:
            lines.append("    (none -- this task was planned with no reading list)")

        if task["dependencies"]:
            lines.append(f"  after: {', '.join(task['dependencies'])}")

        lines.append("")

    lines += ["-" * 70, ""]

    if grounding["grounded"]:
        lines.append(
            "GROUNDED. Every context path names a file that exists at this "
            "commit."
        )
    else:
        lines.append(
            f"NOT GROUNDED. {grounding['missing_context_total']} context "
            "path(s) name files that do not exist at this commit. The plan was "
            "written against a tree that is not this one; an author would be "
            "sent to work with a shorter reading list than it was promised."
        )

    # Concurrency is proved by parse() -- a plan with a collision does not get
    # here -- so this states what was checked rather than checking it again.
    # A reader wanting to know whether parallel execution is safe should be
    # able to see the answer without inferring it from the absence of an error.
    concurrent = [
        task["task_id"] for task in parsed["tasks"] if not task["dependencies"]
    ]
    lines += [
        "",
        f"{len(concurrent)} task(s) have no dependencies and could start at "
        f"once: {', '.join(concurrent) or '(none)'}.",
        "No two tasks that may run concurrently write the same path; the plan "
        "would have been refused if any did.",
        "",
        f"The planner was shown {len(snapshot['documents'])} document(s) and "
        f"told about {len(snapshot['omissions'])} omission(s).",
    ]

    return "\n".join(lines)


def create_tasks(parsed: dict, *, url: str, ready: bool = False) -> int:
    """Write the plan's tasks to the controller as DRAFT. Returns how many.

    Every task carries the plan's base_sha, not the registry's current one.
    They are the same at this instant, and they are not the same after the
    planning ref moves -- and a task created against "whatever master is now"
    is a task whose review has nothing fixed to judge against.
    """
    sys.path.insert(0, str(HERE / "hub"))
    import controller_admin

    secret = os.environ.get("HUB_SECRET", "").strip()

    if not secret:
        raise PlanRunError("HUB_SECRET is not set; cannot reach the controller")

    created = 0

    for task in parsed["tasks"]:
        contract = "".join([
            "schema_version: 7\n",
            f"task_id: {task['task_id']}\n",
            f"mode: {task['mode']}\n",
            "allowed_paths:\n",
            *(f"  - {entry}\n" for entry in task["allowed_paths"]),
        ])

        if task["context_paths"]:
            contract += "context_paths:\n" + "".join(
                f"  - {entry}\n" for entry in task["context_paths"]
            )

        # The acceptance criteria travel in the objective because that is what
        # the reviewer is handed. A criterion the reviewer never sees is a
        # criterion nobody judges against, and the controller has no column
        # for them.
        objective = "\n".join([
            task["objective"],
            "",
            "ACCEPTANCE CRITERIA:",
            *(f"- {entry}" for entry in task["acceptance_criteria"]),
        ])

        status, body = controller_admin.call(
            url.rstrip("/"), secret, "POST", "/controller/tasks",
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "objective": objective,
                "base_sha": parsed["base_sha"],
                "contract_yaml": contract,
            },
        )

        if status >= 400:
            print(f"  {task['task_id']}: REFUSED {status} {body}")
            continue

        created += 1
        print(f"  {task['task_id']}: created in DRAFT")

        if ready:
            status, body = controller_admin.call(
                url.rstrip("/"), secret, "POST",
                f"/controller/tasks/{task['task_id']}/ready",
            )
            print(f"  {task['task_id']}: ready -> {status}")

    return created


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project", required=True,
        help="a name registered in repos.json. There is no --repo: a path is "
             "how the wrong checkout got snapshotted.",
    )
    parser.add_argument("--registry", default=None)
    parser.add_argument(
        "--guidance", default="",
        help="what is being asked for, in your words. Without it the planner "
             "is choosing what matters as well as how to do it.",
    )
    parser.add_argument(
        "--guidance-file", default=None,
        help="read the guidance from a file instead, for anything longer than "
             "a shell argument should be.",
    )
    parser.add_argument("--model", default=GEMINI_MODEL)
    parser.add_argument(
        "--out", default=None,
        help="write the accepted plan here as JSON, for the ledger",
    )
    parser.add_argument(
        "--prompt-out", default=None,
        help="write the exact prompt the planner was given. A plan is "
             "evidence about a prompt as much as about a repository.",
    )
    parser.add_argument(
        "--reply-out", default=None,
        help="write the planner's raw reply, including anything outside the "
             "block. A refused plan is only diagnosable from what was said.",
    )
    parser.add_argument(
        "--from-reply", default=None,
        help="parse a saved reply instead of calling the model. For checking "
             "the validation without spending a call.",
    )
    parser.add_argument(
        "--create", action="store_true",
        help="write the accepted tasks to the controller as DRAFT. Without "
             "this, nothing is created and the run is a proposal.",
    )
    parser.add_argument(
        "--ready", action="store_true",
        help="with --create, also move each task to READY_AUTHOR. This is the "
             "point work becomes activatable; it is separate on purpose.",
    )
    parser.add_argument("--url", default="http://192.168.42.50:8050")
    parser.add_argument("--run-tests", default=None, metavar="COMMAND")
    args = parser.parse_args(argv[1:])

    # The snapshot quotes documents, and documents contain arrows and accented
    # names. A Windows console is cp1252, so printing one unprepared raises
    # UnicodeEncodeError -- the plan would be produced correctly and then die
    # on its way to the screen.
    reconfigure = getattr(sys.stdout, "reconfigure", None)

    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

    guidance = args.guidance

    if args.guidance_file:
        guidance = Path(args.guidance_file).read_text(encoding="utf-8")

    try:
        resolved = repo_registry.resolve_name(
            args.project, args.registry, for_planning=True
        )
    except repo_registry.NotPlannable as exc:
        print(f"plan: {exc}")
        return 3
    except repo_registry.RegistryError as exc:
        print(f"plan: {exc}")
        return 2

    print(
        f"plan: {resolved.name} -> {resolved.ref} -> {resolved.sha}",
        file=sys.stderr,
    )

    try:
        tests = (
            repo_snapshot.run_tests(str(resolved.path), args.run_tests)
            if args.run_tests else None
        )
        snapshot = repo_snapshot.build(resolved, tests=tests)
    except repo_snapshot.SnapshotError as exc:
        print(f"plan: {exc}")
        return 1

    prompt = plan.render_prompt(repo_snapshot.render(snapshot), guidance)

    if args.prompt_out:
        Path(args.prompt_out).write_text(prompt, encoding="utf-8")

    print(
        f"plan: prompt is {len(prompt):,} characters over "
        f"{snapshot['tree']['file_count']:,} files",
        file=sys.stderr,
    )

    if args.from_reply:
        reply = Path(args.from_reply).read_text(encoding="utf-8")
        print("plan: parsing a saved reply; no model was called", file=sys.stderr)
    else:
        try:
            reply = ask_gemini(prompt, model=args.model)
        except PlanRunError as exc:
            print(f"plan: {exc}")
            return 1

    if args.reply_out:
        Path(args.reply_out).write_text(reply, encoding="utf-8")

    try:
        parsed = plan.parse(reply, snapshot=snapshot, owners=OWNERS)
    except plan.PlanError as exc:
        # The whole plan, never part of it. The tasks refer to each other, and
        # a plan minus its third task is a plan nobody wrote.
        print(f"plan: REFUSED -- {exc}")

        if not args.reply_out:
            print(
                "      Re-run with --reply-out to keep the reply; a refused "
                "plan is only diagnosable from what was actually said."
            )

        return 1

    try:
        grounding = plan.ground(parsed, str(resolved.path))
    except plan.PlanError as exc:
        print(f"plan: could not be grounded -- {exc}")
        return 1

    print()
    print(render_report(parsed, grounding, snapshot))

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"plan": parsed, "grounding": grounding,
                 "planner": args.model, "guidance": guidance},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nplan: written to {args.out}")

    if not args.create:
        print(
            "\nplan: nothing was created. This is a proposal. Re-run with "
            "--create to write these to the controller as DRAFT."
        )
        return 0

    if not grounding["grounded"]:
        # The one refusal that happens between an accepted plan and created
        # tasks. Every task here would be authorable, and the ones with missing
        # context would block at authoring having already consumed an
        # activation -- which is a worse place to discover this than here.
        print(
            "\nplan: refusing --create. The plan is not grounded, so at least "
            "one task would be created only to block when its author found the "
            "reading list it was promised is not there."
        )
        return 1

    print("\nplan: creating tasks in DRAFT")

    try:
        created = create_tasks(parsed, url=args.url, ready=args.ready)
    except PlanRunError as exc:
        print(f"plan: {exc}")
        return 1

    print(f"plan: {created} of {len(parsed['tasks'])} task(s) created")

    if not args.ready:
        print(
            "plan: they are in DRAFT and nothing will pick them up. Moving one "
            "to READY_AUTHOR is a separate decision."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
