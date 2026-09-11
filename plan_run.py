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
from typing import Optional

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


# How many model calls one planning run may ever make, including the first.
# A hard ceiling rather than a budget somebody tops up: the loop exists so a
# planner can ask for evidence once or twice, and a planner that has asked
# three times is not converging on a plan, it is reading the repository one
# request at a time at a call apiece.
DEFAULT_MAX_CALLS = 3

# Per fulfilled file. Generous compared with a context path, because a planner
# that asked for a specific file by name has already narrowed it.
FULFIL_PER_FILE = 20_000
FULFIL_TOTAL = 80_000



# Search ceilings. Separate from the fulfilment budget because a search is a
# different shape of answer: many small excerpts rather than a few whole files,
# and the failure mode is a query that matches everything rather than one file
# that is enormous.
MAX_RESULTS_PER_QUERY = 30
MAX_RESULTS_TOTAL = 150
SEARCH_LINE_BUDGET = 240
SEARCH_TOTAL_BYTES = 40_000


def search(repo: str, sha: str, request: dict) -> dict:
    """Run the planner's literal queries against the base commit.

    Against the **commit**, never the working tree. `git grep <sha>` searches
    the tree of that commit, so a match is evidence about the same bytes the
    author and the reviewer will see. Searching the checkout would report on
    somebody's uncommitted work in progress, which is the one thing in the
    repository guaranteed not to be what a task will be authored against.

    Nothing is interpolated into a shell. The query travels as one element of
    an argument list, and `-F` tells git the string is fixed rather than a
    pattern -- so a query containing a quote, a semicolon, a backtick or a
    regex metacharacter is a query about those characters and nothing else.

    Zero matches and truncated results are returned as distinct facts, and the
    distinction is the point. "I searched and found nothing" is a strong
    statement a planner should act on; "I searched and stopped counting" is
    not, and a result set that silently conflates them would licence exactly
    the confident wrong conclusion this whole capability exists to prevent.
    """
    import subprocess

    results = []
    spent = 0
    total = 0

    for entry in request["queries"]:
        query = entry["query"]

        argv = [
            "git", "grep",
            "--fixed-strings",      # literal, never a pattern
            "--line-number",
            "--no-color",
            "-I",                   # skip binary files
            "-e", query,
            sha,
        ]

        if entry["path"]:
            argv += ["--", entry["path"]]

        found = subprocess.run(
            argv, cwd=str(repo), capture_output=True,
            encoding="utf-8", errors="replace", check=False,
        )

        # git grep exits 1 for "no matches", which is not an error. Anything
        # else is, and is reported as such rather than as an empty result --
        # a failed search that reads as "nothing found" is the worst possible
        # answer, because absence is what the planner will act on.
        if found.returncode not in (0, 1):
            results.append({
                "query": query,
                "why": entry["why"],
                "path": entry["path"],
                "status": "failed",
                "detail": (found.stderr or "").strip()[:400],
                "matches": [],
                "match_count": 0,
                "truncated": False,
            })
            continue

        lines = [l for l in (found.stdout or "").splitlines() if l.strip()]
        matches = []
        truncated = False

        for line in lines:
            if len(matches) >= MAX_RESULTS_PER_QUERY or total >= MAX_RESULTS_TOTAL:
                truncated = True
                break

            if spent >= SEARCH_TOTAL_BYTES:
                truncated = True
                break

            # "<sha>:<path>:<lineno>:<text>"
            rest = line[len(sha) + 1:] if line.startswith(sha + ":") else line
            path, _, tail = rest.partition(":")
            lineno, _, text = tail.partition(":")
            excerpt = text.strip()[:SEARCH_LINE_BUDGET]

            spent += len(excerpt.encode("utf-8"))
            total += 1
            matches.append({
                "path": path,
                "line": int(lineno) if lineno.isdigit() else 0,
                "text": excerpt,
            })

        results.append({
            "query": query,
            "why": entry["why"],
            "path": entry["path"],
            "status": "ok",
            "matches": matches,
            # The number actually returned by git, which is what makes
            # "truncated" meaningful: 4 of 4 and 30 of 900 are different
            # answers and must not render identically.
            "match_count": len(lines),
            "truncated": truncated or len(matches) < len(lines),
        })

    return {"results": results, "bytes": spent, "returned": total}


def render_search(request: dict, result: dict) -> str:
    """The search results, appended to the next prompt.

    A query that found nothing gets a line saying so in as many words. It is
    the most useful result a search can return -- it is the one that licenses
    writing the task -- and an empty section under a heading would be read as
    "the search did not run".
    """
    parts = [
        "",
        "=" * 70,
        "SEARCH RESULTS",
        "",
        "You asked to search because: " + request["reason"],
        "",
        f"Searched the tree of the baseline commit. These are literal matches, "
        f"not patterns. Line numbers are that commit's.",
    ]

    for item in result["results"]:
        scope = f" under {item['path']}" if item["path"] else ""
        parts += ["", "-" * 60, f"QUERY: {item['query']}{scope}"]

        if item["why"]:
            parts.append(f"(you asked because: {item['why']})")

        if item["status"] == "failed":
            parts += [
                "",
                f"THE SEARCH FAILED: {item['detail']}",
                "This is not the same as finding nothing. Do not conclude that "
                "the text is absent.",
            ]
            continue

        if item["match_count"] == 0:
            parts += [
                "",
                "NO MATCHES. This text does not appear anywhere in the "
                "baseline commit. This is a real result and you may rely on "
                "it.",
            ]
            continue

        shown = len(item["matches"])
        parts.append("")

        if item["truncated"]:
            parts.append(
                f"{item['match_count']} matches, showing the first {shown}. "
                "THE LIST IS CUT SHORT -- do not conclude anything from the "
                "matches you cannot see, and do not assume the remainder "
                "resemble these."
            )
        else:
            parts.append(f"{item['match_count']} match(es), all shown:")

        parts.append("")
        parts += [
            f"  {m['path']}:{m['line']}: {m['text']}" for m in item["matches"]
        ]

    parts += [
        "",
        "=" * 70,
        "",
        "Now answer again. A plan, or a needs_context request for whole files "
        "these results point at, or another search -- but the call limit is "
        "strict and may already be reached.",
    ]

    return "\n".join(parts)


def fulfil(repo: str, sha: str, request: dict, already: Optional[dict] = None) -> dict:
    """Read what the planner asked for, at the base commit. Never more.

    Only paths. A request naming a symbol rather than a file is reported back
    unfulfilled with the reason -- this does not index the repository, and
    guessing which file a name lives in would answer a question the planner did
    not ask. Saying so lets it ask again with a path, which costs one call and
    is honest; a wrong guess costs a plan.
    """
    import subprocess

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", sha],
        cwd=str(repo), capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    tree = [line.strip() for line in (listing.stdout or "").splitlines() if line.strip()]

    # What earlier rounds already handed over: path -> bytes shown. A planner
    # re-asking for a file it was given in full is told so rather than being
    # sent it twice; one that was truncated gets the *next* part rather than
    # the same opening again, which is the only way a second request for a
    # large file can be worth the call it costs.
    already = dict(already or {})

    supplied, refused = [], []
    spent = 0

    for entry in request["requests"]:
        path, symbol, why = entry["path"], entry["symbol"], entry["why"]

        if not path:
            refused.append({
                "asked": symbol,
                "reason": "named a symbol, not a path. needs_context reads "
                          "files by path. To find out WHERE a symbol is, "
                          "answer with needs_search and the literal text "
                          "instead -- that is exactly what it is for, and it "
                          "will give you the paths to ask for here.",
            })
            continue

        matched = [
            candidate for candidate in tree
            if candidate == path or candidate.startswith(path.rstrip("/") + "/")
        ]

        if not matched:
            refused.append({
                "asked": path,
                "reason": f"nothing at that path in {sha[:12]}",
            })
            continue

        for candidate in matched:
            if spent >= FULFIL_TOTAL:
                refused.append({
                    "asked": candidate,
                    "reason": "the fulfilment budget was already spent",
                })
                continue

            shown = subprocess.run(
                ["git", "show", f"{sha}:{candidate}"],
                cwd=str(repo), capture_output=True, encoding="utf-8",
                errors="replace", check=False,
            )

            if shown.returncode != 0:
                refused.append({"asked": candidate, "reason": "could not be read"})
                continue

            raw = (shown.stdout or "").encode("utf-8")
            offset = already.get(candidate, 0)

            if offset >= len(raw):
                refused.append({
                    "asked": candidate,
                    "reason": "already supplied in full in an earlier round; "
                              "it is still above in this prompt",
                })
                continue

            room = min(FULFIL_PER_FILE, max(0, FULFIL_TOTAL - spent))
            chunk = raw[offset:offset + room]
            truncated = offset + len(chunk) < len(raw)
            text = chunk.decode("utf-8", "ignore")

            spent += len(chunk)
            already[candidate] = offset + len(chunk)
            supplied.append({
                "path": candidate, "text": text,
                "truncated": truncated, "why": why,
                "continued": offset > 0,
                "shown_bytes": already[candidate],
                "total_bytes": len(raw),
            })

    return {
        "supplied": supplied, "refused": refused, "bytes": spent,
        "already": already,
    }


def render_fulfilment(request: dict, result: dict) -> str:
    """The evidence, appended to the next prompt, with the refusals named.

    A request that could not be met is stated rather than omitted. Silence
    would read as "this file is empty" or "you did not ask", and the planner
    would draw a conclusion from an absence that means neither.
    """
    parts = [
        "",
        "=" * 70,
        "THE FILES YOU ASKED FOR",
        "",
        "You asked for these because: " + request["reason"],
        "",
        "They are read from the same commit the snapshot describes. This is "
        "the evidence you said you were missing; plan against what is actually "
        "in it, including deciding that something you were going to propose is "
        "already done.",
    ]

    for entry in result["supplied"]:
        header = f"--- {entry['path']}"

        if entry.get("continued"):
            header += (
                f" (CONTINUED from byte {entry['shown_bytes'] - len(entry['text'].encode('utf-8')):,})"
            )

        parts += [
            "",
            "-" * 60,
            header,
            f"(you asked for this because: {entry['why']})",
            "",
            entry["text"].rstrip(),
        ]

        if entry["truncated"]:
            parts.append(
                f"[{entry['path']} IS CUT SHORT HERE -- you have "
                f"{entry.get('shown_bytes', 0):,} of "
                f"{entry.get('total_bytes', 0):,} bytes. Do not conclude "
                "anything about the part you cannot see. Asking for it again "
                "returns the NEXT part, not this one over again.]"
            )

    if result["refused"]:
        parts += ["", "-" * 60, "NOT SUPPLIED:"]
        parts += [
            f"  {item['asked']} -- {item['reason']}" for item in result["refused"]
        ]
        parts.append(
            ""
            "An unfulfilled request is not evidence that the thing does not "
            "exist. If you still need it, say so rather than planning around it."
        )

    parts += [
        "",
        "=" * 70,
        "",
        "Now answer again. A plan if you can now write one, or another "
        "needs_context request if the evidence changed what you need -- but "
        "the call limit is strict and may already be reached.",
    ]

    return "\n".join(parts)


def render_terminal(outcome: dict, resolved, calls: int,
                    searches, supplied) -> str:
    """A terminal answer that is not a plan, rendered for a person.

    Given the same weight as a plan report deliberately. These outcomes exist
    because a planner with no way to say "nothing to do" invents something, and
    an outcome rendered as a two-line apology would read as a failed run --
    which teaches exactly the behaviour the outcome was added to remove.
    """
    lines = [
        "=" * 70,
        f"OUTCOME: {outcome['outcome'].upper()}",
        "=" * 70,
        "",
        f"  project   {resolved.name}",
        f"  ref       {resolved.ref}",
        f"  base      {resolved.sha[:12]}",
        f"  calls     {calls}",
        f"  searches  {len(searches)}",
        f"  files read {len(supplied)}",
        "",
    ]

    if outcome["outcome"] == "milestone_ready":
        lines += [
            "The planner's judgment is that nothing further needs authoring.",
            "",
            "WHY",
            *(f"  {line}" for line in outcome["reason"].splitlines()),
            "",
            "WHAT IT EXAMINED TO CONCLUDE THAT",
            *(f"  {entry}" for entry in outcome["examined"]),
        ]

        if outcome["review_focus"]:
            lines += [
                "",
                "WHAT A REVIEWER SHOULD LOOK HARDEST AT",
                *(f"  {entry}" for entry in outcome["review_focus"]),
            ]

        if outcome["residual_risk"]:
            lines += [
                "",
                "WHAT IT IS UNSURE OF",
                *(f"  {line}" for line in outcome["residual_risk"].splitlines()),
            ]

        lines += [
            "",
            "-" * 70,
            "This is a success, not an empty result. A finished milestone "
            "needs a review, not another task.",
            "",
            "The next step is a person deciding whether to open that review. "
            "This program does not create one: a planner judging its own "
            "subject complete is evidence, and acting on it automatically "
            "would make the judgment self-executing.",
        ]

    else:
        lines += [
            "Planning stopped. In-flight work makes it unreliable.",
            "",
            "WHY",
            *(f"  {line}" for line in outcome["reason"].splitlines()),
            "",
            "WHAT MUST BE RECONCILED FIRST",
            *(f"  {entry}" for entry in outcome["blocking_paths"]),
        ]

        if outcome["what_would_unblock"]:
            lines += [
                "",
                "WHAT WOULD UNBLOCK IT",
                *(f"  {line}"
                  for line in outcome["what_would_unblock"].splitlines()),
            ]

        lines += [
            "",
            "-" * 70,
            "This is not the same as the milestone being complete. It says "
            "the planner could not tell, which is the more honest answer when "
            "somebody else's changes are outstanding.",
        ]

    return "\n".join(lines)


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

        lines.append("  existing work checked:")

        for entry in task["existing_work_checked"]["searched"]:
            lines.append(f"    {entry}")

        lines += [
            "    why it is still missing:",
            *(f"      {line}" for line in
              task["existing_work_checked"]["why_missing"].splitlines()),
        ]

        if report["active_work_collisions"]:
            lines.append("  COLLIDES WITH UNCOMMITTED WORK:")
            lines += [f"    {entry}" for entry in report["active_work_collisions"]]

        for blind in report["unexamined_directories"]:
            lines += [
                f"  UNEXAMINED DIRECTORY: {blind['creates']} would be created "
                f"in {blind['directory']}, which already holds "
                f"{blind['existing_siblings']} file(s) that were never read:",
                *(f"    {name}" for name in blind["examples"]),
            ]

        if task["dependencies"]:
            lines.append(f"  after: {', '.join(task['dependencies'])}")

        lines.append("")

    lines += ["-" * 70, ""]

    if grounding["grounded"]:
        lines.append(
            "GROUNDED. Every context path names a file that exists at this "
            "commit, nothing overlaps work in progress, and every new file "
            "goes into a directory whose existing contents were examined."
        )
    else:
        lines.append("NOT GROUNDED.")

        if grounding["missing_context_total"]:
            lines.append(
                f"  {grounding['missing_context_total']} context path(s) name "
                "files that do not exist at this commit. The plan was written "
                "against a tree that is not this one."
            )

        if grounding.get("active_work_collisions_total"):
            lines.append(
                f"  {grounding['active_work_collisions_total']} writable "
                "path(s) have uncommitted changes in the canonical checkout. "
                "Somebody is editing them now; a candidate written against "
                "the baseline would conflict with or discard that work."
            )

        if grounding.get("unexamined_directories_total"):
            lines.append(
                f"  {grounding['unexamined_directories_total']} new file(s) "
                "would be created in directories whose existing contents were "
                "never read. This is how four proposals duplicating existing "
                "implementations and tests were produced: the path was free, "
                "and the job was already done next to it."
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
    parser.add_argument(
        "--max-calls", type=int, default=DEFAULT_MAX_CALLS,
        help="the hard ceiling on model calls for this run, counting the "
             "first. Reaching it without a plan is a refusal, not a fallback "
             "to whatever the planner last said.",
    )
    parser.add_argument(
        "--doc", action="append", default=[],
        help="include this path in the snapshot's documents, ahead of the "
             "pattern matches. Repeatable. This is the cheaper answer to a "
             "planner that keeps asking for the same file.",
    )
    parser.add_argument(
        "--active-ref", default=None,
        help="a branch whose in-flight work the planner should be shown and "
             "told not to duplicate. Defaults to the canonical checkout's "
             "current branch, which is where work in progress actually is.",
    )
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
        # The checkout's own branch by default. The baseline is master and
        # the work is not on master -- that is the normal state of this
        # repository, and a planner shown only the baseline plans as though
        # nothing were in flight.
        active_ref = args.active_ref

        if active_ref is None:
            current = repo_snapshot._git(
                str(resolved.path), "rev-parse", "--abbrev-ref", "HEAD",
                check=False,
            ).strip()
            active_ref = (
                f"refs/heads/{current}"
                if current and current != "HEAD" and
                f"refs/heads/{current}" != resolved.ref
                else ""
            )

        snapshot = repo_snapshot.build(
            resolved, tests=tests, documents=args.doc, active_ref=active_ref
        )
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

    # --- The bounded loop ----------------------------------------------------
    #
    # A planner that cannot see the source has three options, and before this
    # loop existed it had two. It could plan against files it could not read,
    # or produce nothing -- and producing nothing reads as failure, so it
    # produced work that was safe to author instead of work that was worth
    # doing. Four proposals, every path valid, all four duplicating code and
    # tests already in the repository.
    #
    # The third option is to ask. Each round costs one call, the ceiling counts
    # every call including the first, and reaching it without a plan is a
    # refusal rather than a fallback to whatever the planner said last. A
    # fallback would restore exactly the behaviour this exists to remove.
    transcript = []
    context_supplied = []
    # Every round's evidence, kept. Rebuilding the prompt from the latest
    # fulfilment alone made each round discard the last one's files -- so the
    # planner correctly re-asked for something it had already been given, and
    # spent a call of a strictly limited budget doing it. A live run hit this
    # on its third call. Evidence accumulates or the loop cannot converge.
    evidence = []
    already_supplied = {}
    # Every search run this session, kept as the host's own record. The
    # planner is asked to list its queries in existing_work_checked, and this
    # is what that claim is checked against -- a proposal saying it searched
    # for something nobody ran is a proposal resting on a search that did not
    # happen.
    searches_run = []
    parsed = None
    outcome = None
    calls = 0
    attempt_prompt = prompt

    while True:
        if args.from_reply:
            reply = Path(args.from_reply).read_text(encoding="utf-8")
            print("plan: parsing a saved reply; no model was called", file=sys.stderr)
        else:
            if calls >= args.max_calls:
                # The planner asked again and there is no call left to answer
                # it with. What it last asked for is printed, because the
                # useful next move is usually to widen the snapshot's document
                # set and start over rather than to raise the ceiling.
                print(
                    f"\nplan: REFUSED -- the call limit of {args.max_calls} is "
                    "reached and the planner still has not produced a plan."
                )

                if outcome and outcome.get("outcome") == "needs_context":
                    print("      It was still asking for:")

                    for entry in outcome["requests"]:
                        print(f"        {entry['path'] or entry['symbol']}")

                    print(
                        "      Consider adding these to the snapshot's "
                        "documents with --doc and running again, rather than "
                        "raising --max-calls."
                    )

                return 1

            try:
                reply = ask_gemini(attempt_prompt, model=args.model)
                calls += 1
            except PlanRunError as exc:
                print(f"plan: {exc}")
                return 1

        transcript.append({"call": calls, "prompt": attempt_prompt, "reply": reply})

        if args.reply_out:
            # Every round, not just the last. A run that ended in a refusal is
            # only diagnosable from what was actually said, and the request
            # that preceded a bad plan is usually where the answer is.
            suffix = "" if calls <= 1 else f".{calls}"
            Path(args.reply_out + suffix).write_text(reply, encoding="utf-8")

        try:
            outcome = plan.parse_reply(reply, snapshot=snapshot, owners=OWNERS)
        except plan.PlanError as exc:
            # The whole plan, never part of it. The tasks refer to each other,
            # and a plan minus its third task is a plan nobody wrote.
            print(f"plan: REFUSED -- {exc}")

            if not args.reply_out:
                print(
                    "      Re-run with --reply-out to keep the reply; a "
                    "refused plan is only diagnosable from what was said."
                )

            return 1

        if outcome["outcome"] == "plan":
            parsed = outcome["plan"]
            break

        # The two terminal answers that are not a plan. Both end the run
        # successfully: a planner that says "this needs review, not another
        # task" has done the most useful thing available to it, and a run that
        # reported that as a failure would teach the next one to invent
        # something instead.
        if outcome["outcome"] in ("milestone_ready", "blocked_active_work"):
            report = render_terminal(outcome, resolved, calls, searches_run,
                                     context_supplied)
            print()
            print(report)

            if args.out:
                Path(args.out).write_text(
                    json.dumps({
                        "outcome": outcome, "planner": args.model,
                        "guidance": guidance, "model_calls": calls,
                        "max_calls": args.max_calls,
                        "base_sha": resolved.sha,
                        "planning_ref": resolved.ref,
                        "searches_run": searches_run,
                        "context_supplied": context_supplied,
                    }, indent=2),
                    encoding="utf-8",
                )
                print(f"\nplan: written to {args.out}")

            if args.create:
                print(
                    "\nplan: --create has nothing to create. This run "
                    "concluded that no task should be authored, which is an "
                    "answer, not an empty plan."
                )

            return 0

        if outcome["outcome"] == "needs_search":
            print(f"\nplan: the planner asked to search (call {calls})")
            print(f"      {outcome['reason']}")

            for entry in outcome["queries"]:
                scope = f" under {entry['path']}" if entry["path"] else ""
                print(f"        {entry['query']!r}{scope}")

            if args.from_reply:
                print(
                    "\nplan: --from-reply cannot be answered; there is no "
                    "second saved reply to read. The queries are above."
                )
                return 0

            found = search(str(resolved.path), resolved.sha, outcome)

            for item in found["results"]:
                if item["status"] == "failed":
                    state = "FAILED"
                elif item["match_count"] == 0:
                    state = "no matches"
                elif item["truncated"]:
                    state = f"{item['match_count']} matches, {len(item['matches'])} shown"
                else:
                    state = f"{item['match_count']} match(es)"

                print(f"        {item['query']!r}: {state}")

            searches_run.extend({
                "query": item["query"],
                "path": item["path"],
                "status": item["status"],
                "match_count": item["match_count"],
                "truncated": item["truncated"],
                "paths": sorted({m["path"] for m in item["matches"]}),
            } for item in found["results"])

            evidence.append(render_search(outcome, found))
            attempt_prompt = prompt + "".join(evidence)
            continue

        # NEEDS_CONTEXT. Not a failure -- this is the answer the loop was
        # built to make available, and it is the one the planner is told to
        # prefer over a plan it is not confident in.
        print(f"\nplan: the planner asked for context (call {calls})")
        print(f"      {outcome['reason']}")

        for entry in outcome["requests"]:
            print(f"        {entry['path'] or entry['symbol']} -- {entry['why']}")

        if args.from_reply:
            print(
                "\nplan: --from-reply cannot be answered; there is no second "
                "saved reply to read. The request is above."
            )
            return 0

        result = fulfil(
            str(resolved.path), resolved.sha, outcome, already_supplied
        )
        already_supplied = result["already"]

        print(
            f"plan: supplying {len(result['supplied'])} file(s), "
            f"{result['bytes']:,} bytes"
            + (f", refusing {len(result['refused'])}" if result["refused"] else "")
        )

        for item in result["refused"]:
            print(f"        not supplied: {item['asked']} -- {item['reason']}")

        if not result["supplied"]:
            # Answering with nothing would spend the next call to be told the
            # same thing again, and the round after that would be identical.
            print(
                "\nplan: REFUSED -- nothing the planner asked for could be "
                "supplied, so another call would ask the same question of the "
                "same evidence."
            )
            return 1

        evidence.append(render_fulfilment(outcome, result))
        attempt_prompt = prompt + "".join(evidence)
        context_supplied.extend(entry["path"] for entry in result["supplied"])

    # The uncommitted paths, as active-work warnings. A task authorised to
    # write a file somebody is mid-edit on is a task whose candidate was
    # written against a base that person has already moved past.
    dirty_paths = [
        entry[3:].split(" -> ")[-1].strip().strip('"')
        for entry in snapshot["operational"]["uncommitted"]["entries"]
    ]

    try:
        grounding = plan.ground(parsed, str(resolved.path), dirty=dirty_paths)
    except plan.PlanError as exc:
        print(f"plan: could not be grounded -- {exc}")
        return 1

    print()
    print(render_report(parsed, grounding, snapshot))

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"plan": parsed, "grounding": grounding,
                 "planner": args.model, "guidance": guidance,
                 "model_calls": calls, "max_calls": args.max_calls,
                 "context_supplied": context_supplied,
                 "searches_run": searches_run,
                 "active_ref": snapshot.get("active_work", {}).get("ref", "")},
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
