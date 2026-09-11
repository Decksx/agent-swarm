"""The planning run, up to but not including the model call.

`plan.py` decides whether a plan is acceptable and `plan_run.py` decides what
happens next. The interesting behaviour here is all refusal: a closed project,
an ungrounded plan, and the difference between producing a proposal and
creating state. `--from-reply` exists so all of it can be exercised without
spending a call, which is also how the refusal cases were demonstrated live.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import plan
import plan_run
import repo_registry
import repo_snapshot


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered, plannable project with a few real files in it."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "plan@test")
    git(root, "config", "user.name", "Plan Test")

    (root / "docs").mkdir()
    (root / "src").mkdir()
    (root / "README.md").write_text("# project\n\nA thing.\n", encoding="utf-8")
    (root / "docs" / "design.md").write_text("# design\n\nHow it works.\n", encoding="utf-8")
    (root / "src" / "api.py").write_text("class Reader:\n    pass\n", encoding="utf-8")

    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")

    registry = tmp_path / "repos.json"
    registry.write_text(json.dumps({
        "demo": {
            "path": str(root),
            "repo_id": repo_snapshot.repo_id(str(root)),
            "planning_ref": "refs/heads/master",
            "worktree_root": str(tmp_path / "worktrees"),
        }
    }), encoding="utf-8")

    monkeypatch.setattr(repo_registry, "DEFAULT_REGISTRY", registry)
    return root


def reply_file(tmp_path, tasks, name="reply.txt"):
    body = {"summary": "a plan", "tasks": tasks}
    path = tmp_path / name
    path.write_text(
        f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}\n", encoding="utf-8"
    )
    return path


def task(**over):
    base = {
        "task_id": "T-1", "title": "add a document",
        "objective": "Write docs/new.md describing the thing in three sections.",
        "acceptance_criteria": ["docs/new.md exists"],
        "owner": "chatgpt", "mode": "document",
        "allowed_paths": ["docs/new.md"],
        "context_paths": ["docs/design.md"],
        "existing_work_checked": {
            "searched": ["docs/design.md", "src/api.py"],
            "why_missing": "design.md describes the mechanism but no document "
                           "states the protocol, and src/ has no equivalent.",
        },
        "dependencies": [],
    }
    base.update(over)
    return base


def reply_text(*tasks, **top):
    body = {"summary": "a plan", "tasks": [dict(t) for t in tasks]}
    body.update(top)
    return f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}\n"


def run(*args):
    return plan_run.main(["plan_run.py", *args])


# --- A proposal is not state -------------------------------------------------


def test_a_good_plan_is_reported_and_nothing_is_created(project, tmp_path, capsys):
    """The default is a proposal. A plan reads as a decision, and the whole
    point of checking it is that somebody looks before the branches exist."""
    saved = tmp_path / "plan.json"

    code = run(
        "--project", "demo",
        "--from-reply", str(reply_file(tmp_path, [task()])),
        "--out", str(saved),
    )

    assert code == 0
    assert "nothing was created" in capsys.readouterr().out
    assert json.loads(saved.read_text(encoding="utf-8"))["plan"]["tasks"]


def test_the_saved_plan_carries_the_resolved_base_not_a_ref(project, tmp_path):
    """A ref is a moving target. Everything downstream takes the SHA."""
    saved = tmp_path / "plan.json"
    run("--project", "demo",
        "--from-reply", str(reply_file(tmp_path, [task()])),
        "--out", str(saved))

    stored = json.loads(saved.read_text(encoding="utf-8"))["plan"]

    assert stored["base_sha"] == git(project, "rev-parse", "HEAD").strip()


def test_no_model_is_called_when_a_reply_is_supplied(project, tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the model was called for a saved reply")

    monkeypatch.setattr(plan_run, "ask_gemini", explode)

    assert run("--project", "demo",
               "--from-reply", str(reply_file(tmp_path, [task()]))) == 0


# --- Refusals, each before anything exists -----------------------------------


def test_a_project_closed_to_planning_is_refused(project, tmp_path, capsys):
    """And distinguishably: exit 3, not the generic registry failure.

    An operator whose plan was refused because the project is closed is in a
    different situation from one whose drive did not mount.
    """
    registry = repo_registry.DEFAULT_REGISTRY
    raw = json.loads(registry.read_text(encoding="utf-8"))
    raw["demo"]["plannable"] = False
    registry.write_text(json.dumps(raw), encoding="utf-8")

    code = run("--project", "demo",
               "--from-reply", str(reply_file(tmp_path, [task()])))

    assert code == 3
    assert "plannable" in capsys.readouterr().out


def test_an_unregistered_project_is_refused(project, tmp_path, capsys):
    code = run("--project", "nothing-by-that-name",
               "--from-reply", str(reply_file(tmp_path, [task()])))

    assert code == 2
    assert "not a registered project" in capsys.readouterr().out


def test_a_colliding_plan_is_refused_whole(project, tmp_path, capsys):
    code = run("--project", "demo", "--from-reply", str(reply_file(tmp_path, [
        task(task_id="A-1", allowed_paths=["docs/shared.md"]),
        task(task_id="B-1", allowed_paths=["docs/shared.md"]),
    ])))

    assert code == 1
    assert "no dependency between them" in capsys.readouterr().out


def test_an_ungrounded_plan_is_reported_rather_than_hidden(
    project, tmp_path, capsys
):
    """It still parses. Only the tree can say the path is not there."""
    code = run("--project", "demo", "--from-reply", str(reply_file(
        tmp_path, [task(context_paths=["src/absent.py"])]
    )))

    out = capsys.readouterr().out

    assert code == 0
    assert "NOT GROUNDED" in out
    assert "src/absent.py" in out


def test_create_is_refused_for_an_ungrounded_plan(project, tmp_path, capsys):
    """The last refusal between an accepted plan and created tasks.

    Every task would be creatable, and the ones with missing context would
    block at authoring having already consumed an activation -- a worse place
    to discover this than here.
    """
    code = run("--project", "demo", "--create", "--from-reply", str(reply_file(
        tmp_path, [task(context_paths=["src/absent.py"])]
    )))

    assert code == 1
    assert "refusing --create" in capsys.readouterr().out


def test_nothing_is_created_without_a_credential(project, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HUB_SECRET", raising=False)

    code = run("--project", "demo", "--create",
               "--from-reply", str(reply_file(tmp_path, [task()])))

    assert code == 1
    assert "HUB_SECRET" in capsys.readouterr().out


# --- The report a person actually decides from -------------------------------


def test_the_report_marks_a_created_file_apart_from_an_edited_one(
    project, tmp_path, capsys
):
    """A task claiming to edit a module that it is in fact about to invent is
    the thing a reader most needs to see at a glance."""
    run("--project", "demo", "--from-reply", str(reply_file(tmp_path, [
        task(
            allowed_paths=["docs/new.md", "docs/design.md"],
            context_paths=["README.md"],
        ),
    ])))

    out = capsys.readouterr().out

    assert "creates  docs/new.md" in out
    assert "edits    docs/design.md" in out


def test_the_report_names_missing_context_beside_its_task(project, tmp_path, capsys):
    """Interleaved rather than appended. A reader deciding whether a task is
    sensible needs this at the moment they read the objective."""
    run("--project", "demo", "--from-reply", str(reply_file(
        tmp_path, [task(context_paths=["docs/design.md", "src/absent.py"])]
    )))

    out = capsys.readouterr().out
    body = out[out.index("T-1"):]

    assert "MISSING  src/absent.py" in body
    assert "ok       docs/design.md" in body


def test_the_report_says_which_tasks_could_start_at_once(project, tmp_path, capsys):
    """Stated rather than left to be inferred from the absence of an error."""
    run("--project", "demo", "--from-reply", str(reply_file(tmp_path, [
        task(task_id="A-1", allowed_paths=["docs/a.md"]),
        task(task_id="B-1", allowed_paths=["docs/b.md"], dependencies=["A-1"]),
    ])))

    out = capsys.readouterr().out

    assert "1 task(s) have no dependencies" in out
    assert "A-1" in out


def test_the_report_carries_the_planners_own_summary(project, tmp_path, capsys):
    """Including what it said it was unsure of, which is the part a reader
    most needs and the part a tidier report would drop."""
    path = tmp_path / "reply.txt"
    body = {
        "summary": "I could not see any Python source, so this is documentation only.",
        "tasks": [task()],
    }
    path.write_text(
        f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}\n", encoding="utf-8"
    )

    run("--project", "demo", "--from-reply", str(path))

    assert "I could not see any Python source" in capsys.readouterr().out


def test_a_task_planned_with_no_reading_list_says_so(project, tmp_path, capsys):
    """An empty section would read as a rendering bug rather than a choice."""
    run("--project", "demo", "--from-reply", str(reply_file(
        tmp_path, [task(context_paths=[])]
    )))

    assert "planned with no reading list" in capsys.readouterr().out


# --- The prompt is evidence too ----------------------------------------------


def test_the_prompt_can_be_kept(project, tmp_path):
    """A plan is evidence about a prompt as much as about a repository."""
    prompt = tmp_path / "prompt.txt"

    run("--project", "demo", "--prompt-out", str(prompt),
        "--from-reply", str(reply_file(tmp_path, [task()])))

    text = prompt.read_text(encoding="utf-8")

    assert "OMITTED OR TRUNCATED" in text
    assert "context_paths" in text


def test_the_prompt_tells_the_planner_not_to_widen_write_authority(
    project, tmp_path
):
    """The correction a planner reaches for when an author needs to read
    something is to make it writable. It is told not to, in the prompt, at the
    point it is deciding."""
    prompt = tmp_path / "prompt.txt"

    run("--project", "demo", "--prompt-out", str(prompt),
        "--from-reply", str(reply_file(tmp_path, [task()])))

    assert "Do NOT widen allowed_paths" in prompt.read_text(encoding="utf-8")


# --- The bounded NEEDS_CONTEXT loop -----------------------------------------
#
# The ceiling is the safety property. Without one, a planner that keeps asking
# turns a planning run into an unbounded sequence of paid calls that reads the
# repository one file at a time -- and the run still might not end in a plan.


def context_request(*paths, reason=None):
    body = {
        "outcome": "needs_context",
        "reason": reason or "I cannot tell whether this already exists without "
                            "reading the implementation.",
        "requests": [
            {"path": p, "why": "to see whether it already does this"}
            for p in paths
        ],
    }
    return f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}"


def scripted(monkeypatch, *replies):
    """Answer each call with the next scripted reply, counting the calls."""
    state = {"calls": 0, "prompts": []}

    def fake(prompt, *, model=None):
        state["prompts"].append(prompt)
        index = state["calls"]
        state["calls"] += 1

        if index >= len(replies):
            raise AssertionError(
                f"the loop made call {index + 1}; only {len(replies)} scripted"
            )

        return replies[index]

    monkeypatch.setattr(plan_run, "ask_gemini", fake)
    return state


def test_a_context_request_is_fulfilled_and_planning_retried(
    project, tmp_path, monkeypatch, capsys
):
    state = scripted(
        monkeypatch,
        context_request("src/api.py"),
        reply_text(task()),
    )

    code = run("--project", "demo")
    out = capsys.readouterr().out

    assert code == 0
    assert state["calls"] == 2
    assert "asked for context" in out
    # The second prompt carries the file, read from the base commit.
    assert "class Reader" in state["prompts"][1]
    assert "THE FILES YOU ASKED FOR" in state["prompts"][1]


def test_the_first_prompt_does_not_contain_the_answer(
    project, tmp_path, monkeypatch
):
    """Otherwise the request would have been unnecessary and the test would
    prove nothing about fulfilment."""
    state = scripted(
        monkeypatch, context_request("src/api.py"), reply_text(task())
    )
    run("--project", "demo")

    assert "class Reader" not in state["prompts"][0]


def test_the_call_ceiling_is_a_refusal_not_a_fallback(
    project, tmp_path, monkeypatch, capsys
):
    """A fallback to the planner's last answer would restore exactly the
    behaviour the loop exists to remove: a plan produced without the evidence
    the planner said it needed."""
    state = scripted(
        monkeypatch,
        context_request("src/api.py"),
        context_request("docs/design.md"),
        context_request("README.md"),
    )

    code = run("--project", "demo", "--max-calls", "3")
    out = capsys.readouterr().out

    assert code == 1
    assert state["calls"] == 3
    assert "call limit of 3 is reached" in out


def test_the_ceiling_counts_the_first_call(project, tmp_path, monkeypatch, capsys):
    state = scripted(monkeypatch, context_request("src/api.py"))

    code = run("--project", "demo", "--max-calls", "1")

    assert code == 1
    assert state["calls"] == 1
    assert "call limit of 1" in capsys.readouterr().out


def test_the_refusal_names_what_was_still_being_asked_for(
    project, tmp_path, monkeypatch, capsys
):
    """The useful next move is usually to widen the snapshot rather than raise
    the ceiling, and that needs to know which files."""
    scripted(monkeypatch, context_request("src/api.py"))
    run("--project", "demo", "--max-calls", "1")

    out = capsys.readouterr().out

    assert "src/api.py" in out
    assert "--doc" in out


def test_a_request_for_nothing_that_exists_ends_the_run(
    project, tmp_path, monkeypatch, capsys
):
    """Answering with nothing would spend the next call to be told the same
    thing again, and the round after that would be identical."""
    state = scripted(monkeypatch, context_request("src/does_not_exist.py"))

    code = run("--project", "demo", "--max-calls", "5")
    out = capsys.readouterr().out

    assert code == 1
    assert state["calls"] == 1
    assert "nothing the planner asked for could be supplied" in out


def test_a_symbol_request_is_refused_with_a_reason_not_guessed_at(
    project, tmp_path, monkeypatch, capsys
):
    """Guessing which file a name lives in answers a question nobody asked.
    A wrong guess costs a plan; saying so costs one call."""
    body = {
        "outcome": "needs_context",
        "reason": "I need to know whether this symbol already exists anywhere.",
        "requests": [
            {"symbol": "Reader", "why": "to see whether it already does this"},
            {"path": "src/api.py", "why": "to read the interface"},
        ],
    }
    scripted(
        monkeypatch,
        f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}",
        reply_text(task()),
    )

    run("--project", "demo")
    out = capsys.readouterr().out

    assert "not supplied: Reader" in out
    assert "does not index symbols" in out


def test_context_is_read_from_the_baseline_not_the_working_tree(
    project, tmp_path, monkeypatch
):
    state = scripted(
        monkeypatch, context_request("src/api.py"), reply_text(task())
    )
    (project / "src" / "api.py").write_text("SABOTAGE\n", encoding="utf-8")

    run("--project", "demo")

    assert "class Reader" in state["prompts"][1]
    assert "SABOTAGE" not in state["prompts"][1]


def test_the_saved_plan_records_how_many_calls_it_took(
    project, tmp_path, monkeypatch
):
    """A plan that needed two rounds of evidence is a different piece of
    evidence from one produced cold, and the file should say which it is."""
    scripted(monkeypatch, context_request("src/api.py"), reply_text(task()))
    saved = tmp_path / "plan.json"

    run("--project", "demo", "--out", str(saved))
    stored = json.loads(saved.read_text(encoding="utf-8"))

    assert stored["model_calls"] == 2
    assert stored["context_supplied"] == ["src/api.py"]


def test_each_round_of_replies_is_kept(project, tmp_path, monkeypatch):
    """A run that ended in a refusal is only diagnosable from what was said,
    and the request preceding a bad plan is usually where the answer is."""
    scripted(monkeypatch, context_request("src/api.py"), reply_text(task()))
    out = tmp_path / "reply.txt"

    run("--project", "demo", "--reply-out", str(out))

    assert out.exists()
    assert (tmp_path / "reply.txt.2").exists()


def test_a_saved_reply_asking_for_context_stops_and_says_so(
    project, tmp_path, capsys
):
    """--from-reply has no second reply to read, so it reports the request
    rather than pretending it was answered."""
    path = tmp_path / "reply.txt"
    path.write_text(context_request("src/api.py"), encoding="utf-8")

    code = run("--project", "demo", "--from-reply", str(path))
    out = capsys.readouterr().out

    assert code == 0
    assert "cannot be answered" in out


# --- Active work reaches the planner and the grounding ----------------------


def test_a_task_writing_an_uncommitted_file_blocks_creation(
    project, tmp_path, monkeypatch, capsys
):
    (project / "docs" / "design.md").write_text("edited\n", encoding="utf-8")
    scripted(monkeypatch, reply_text(task(
        allowed_paths=["docs/design.md"], context_paths=["README.md"],
    )))

    code = run("--project", "demo", "--create")
    out = capsys.readouterr().out

    assert code == 1
    assert "COLLIDES WITH UNCOMMITTED WORK" in out
    assert "refusing --create" in out


def test_the_prompt_shows_work_in_progress_on_another_branch(
    project, tmp_path, monkeypatch
):
    """A planner shown only the baseline plans as though nothing is in flight,
    and work in progress is the likeliest thing to duplicate."""
    git(project, "checkout", "-q", "-b", "slice/in-flight")
    (project / "src" / "new_feature.py").write_text("x = 1\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "in flight work")

    state = scripted(monkeypatch, reply_text(task()))
    run("--project", "demo")

    assert "WORK IN PROGRESS ON ANOTHER BRANCH" in state["prompts"][0]
    assert "src/new_feature.py" in state["prompts"][0]


def test_the_prompt_tells_the_planner_it_may_ask(project, tmp_path, monkeypatch):
    state = scripted(monkeypatch, reply_text(task()))
    run("--project", "demo")

    prompt = state["prompts"][0]

    assert "needs_context" in prompt
    assert "existing_work_checked" in prompt
    assert "All four were rejected" in prompt


# --- Evidence accumulates, or the loop cannot converge ----------------------
#
# A live run found this. The prompt for each round was rebuilt as
# `prompt + latest_fulfilment`, so round three discarded what round one had
# supplied -- and the planner, correctly, asked again for a file it had
# already been given in full. It spent one call of a three-call budget doing
# it, and the run ended at the ceiling with no plan.


def test_every_earlier_round_is_still_in_the_prompt(
    project, tmp_path, monkeypatch
):
    state = scripted(
        monkeypatch,
        context_request("src/api.py"),
        context_request("docs/design.md"),
        reply_text(task()),
    )

    assert run("--project", "demo", "--max-calls", "3") == 0

    third = state["prompts"][2]

    assert "class Reader" in third          # supplied in round one
    assert "How it works" in third          # supplied in round two


def test_a_file_supplied_in_full_is_not_sent_twice(
    project, tmp_path, monkeypatch, capsys
):
    """It is still in the prompt. Sending it again would spend budget to tell
    the planner something it can already read."""
    scripted(
        monkeypatch,
        context_request("src/api.py"),
        context_request("src/api.py"),
        reply_text(task()),
    )

    run("--project", "demo", "--max-calls", "3")
    out = capsys.readouterr().out

    assert "already supplied in full" in out


def test_re_asking_for_a_truncated_file_returns_the_next_part(
    project, tmp_path, monkeypatch
):
    """Otherwise a second request for a large file returns the same opening
    again, and costs a call to do it."""
    big = "\n".join(f"line {n} of the long module" for n in range(4000))
    (project / "src" / "big.py").write_text(big, encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "a file larger than the per-file budget")

    monkeypatch.setattr(plan_run, "FULFIL_PER_FILE", 2_000)
    monkeypatch.setattr(plan_run, "FULFIL_TOTAL", 8_000)

    state = scripted(
        monkeypatch,
        context_request("src/big.py"),
        context_request("src/big.py"),
        reply_text(task()),
    )

    assert run("--project", "demo", "--max-calls", "3") == 0

    third = state["prompts"][2]

    assert "CONTINUED from byte" in third
    # The second chunk starts where the first stopped, so content from beyond
    # the first budget is now present.
    assert "line 0 of the long module" in third
    assert third.count("line 0 of the long module") == 1


def test_a_cut_short_file_says_how_much_is_left(project, tmp_path, monkeypatch):
    big = "\n".join(f"line {n}" for n in range(4000))
    (project / "src" / "big.py").write_text(big, encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "big")

    monkeypatch.setattr(plan_run, "FULFIL_PER_FILE", 2_000)
    state = scripted(
        monkeypatch, context_request("src/big.py"), reply_text(task())
    )

    run("--project", "demo")
    second = state["prompts"][1]

    assert "IS CUT SHORT HERE" in second
    assert "returns the NEXT part" in second
