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
        "dependencies": [],
    }
    base.update(over)
    return base


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
