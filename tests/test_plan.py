"""A plan is a proposal, and every field of it is checked against something.

The failure this guards against is not a model planning badly. It is a plan
reading as a decision: five confident paragraphs, a nod, and the first thing
anybody verifies is an author failing to find a file. So each test below takes
one field and asks what outside the plan could contradict it.
"""

from __future__ import annotations

import json

import pytest

import plan
import repo_registry
from plan import PlanError


SNAPSHOT = {
    "project": "demo",
    "repo_id": "4d49a52cb85e99fc",
    "planning_ref": "refs/heads/master",
    "base_sha": "a" * 40,
}


def task(**overrides) -> dict:
    base = {
        "task_id": "T-1",
        "title": "add a note",
        "objective": "Create notes/greeting.md with the agreed three lines.",
        "acceptance_criteria": ["notes/greeting.md exists", "line 1 is '# Greeting'"],
        "owner": "chatgpt",
        "mode": "implement",
        "allowed_paths": ["notes"],
        "dependencies": [],
    }
    base.update(overrides)
    return base


def reply(*tasks, **top) -> str:
    body = {"summary": "a plan", "tasks": [dict(t) for t in tasks] or [task()]}
    body.update(top)
    return f"prose before\n{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}\nprose after"


def parse(*tasks, snapshot=None, **top):
    return plan.parse(reply(*tasks, **top), snapshot=snapshot or SNAPSHOT)


# --- The shape ---------------------------------------------------------------


def test_a_well_formed_plan_becomes_task_definitions():
    result = parse(task())

    assert result["tasks"][0]["task_id"] == "T-1"
    assert result["tasks"][0]["owner"] == "chatgpt"
    assert result["summary"] == "a plan"


def test_prose_around_the_block_is_ignored():
    """A model that explains itself first still produces a usable answer."""
    assert parse(task())["tasks"][0]["task_id"] == "T-1"


def test_a_reply_with_no_block_is_refused():
    with pytest.raises(PlanError, match="no <<<PLAN>>>"):
        plan.parse("Here is my plan: do the thing.", snapshot=SNAPSHOT)


def test_an_unterminated_block_is_refused():
    """A truncated plan can still parse as JSON, which is the danger."""
    with pytest.raises(PlanError, match="not terminated"):
        plan.parse(plan.BEGIN + '{"tasks": []', snapshot=SNAPSHOT)


def test_an_empty_plan_is_refused():
    with pytest.raises(PlanError, match="no tasks"):
        plan.parse(f"{plan.BEGIN}\n{{\"tasks\": []}}\n{plan.END}", snapshot=SNAPSHOT)


# --- The base is not the planner's to choose --------------------------------


def test_the_base_sha_comes_from_the_snapshot():
    result = parse(task())

    assert result["base_sha"] == SNAPSHOT["base_sha"]
    assert result["repo_id"] == SNAPSHOT["repo_id"]


def test_a_plan_naming_a_different_base_is_refused_not_corrected():
    """It disagrees with its own evidence about what it was planned against."""
    with pytest.raises(PlanError, match="disagrees with its own evidence"):
        parse(task(), base_sha="b" * 40)


def test_a_plan_restating_the_correct_base_is_accepted():
    assert parse(task(), base_sha=SNAPSHOT["base_sha"])["tasks"]


# --- allowed_paths become an author's authority ------------------------------


def test_a_plan_may_not_grant_unrestricted():
    """The hole parse_scope closes, reopened one layer up.

    A planner that could hand its own author the whole repository is the
    fail-open contract with an extra step, and this is the layer that was
    named as the place to stop it.
    """
    with pytest.raises(PlanError, match="may not grant UNRESTRICTED"):
        parse(task(allowed_paths=["UNRESTRICTED"]))


@pytest.mark.parametrize("path", [
    "/etc/passwd", "../outside", "C:\\windows", ".git/config", "notes/../../x",
])
def test_unsafe_paths_are_refused(path):
    with pytest.raises(PlanError):
        parse(task(allowed_paths=[path]))


def test_a_glob_is_refused_because_nothing_downstream_matches_one():
    """`matches_allowed` compares path components; a glob would authorise less
    than it appears to, silently."""
    with pytest.raises(PlanError, match="looks like a glob"):
        parse(task(allowed_paths=["src/**/*.py"]))


def test_a_task_with_no_allowed_paths_is_refused():
    with pytest.raises(PlanError, match="no allowed_paths"):
        parse(task(allowed_paths=[]))


def test_too_many_paths_is_a_task_that_was_not_decomposed():
    with pytest.raises(PlanError, match="not been decomposed"):
        parse(task(allowed_paths=[f"dir{n}" for n in range(25)]))


# --- Fields a reviewer and an author depend on -------------------------------


def test_acceptance_criteria_are_required():
    """Without them a review is a reaction to a diff."""
    with pytest.raises(PlanError, match="no acceptance_criteria"):
        parse(task(acceptance_criteria=[]))


def test_an_objective_too_short_to_act_on_is_refused():
    with pytest.raises(PlanError, match="objective"):
        parse(task(objective="fix it"))


def test_an_owner_that_is_not_an_agent_is_refused():
    """A task assigned to nobody sits in READY_AUTHOR until someone notices."""
    with pytest.raises(PlanError, match="owner"):
        parse(task(owner="nobody"))


def test_an_invented_mode_is_refused():
    with pytest.raises(PlanError, match="mode"):
        parse(task(mode="refactor-everything"))


# --- Dependencies ------------------------------------------------------------


def test_dependencies_may_name_other_tasks_in_the_plan():
    result = parse(task(task_id="A"), task(task_id="B", dependencies=["A"]))

    assert result["tasks"][1]["dependencies"] == ["A"]


def test_a_dependency_outside_the_plan_is_refused():
    with pytest.raises(PlanError, match="not in this plan"):
        parse(task(task_id="A", dependencies=["Z"]))


def test_a_self_dependency_is_refused():
    with pytest.raises(PlanError, match="depends on itself"):
        parse(task(task_id="A", dependencies=["A"]))


def test_a_cycle_is_named_rather_than_merely_reported():
    with pytest.raises(PlanError, match="cycle among: A, B"):
        parse(
            task(task_id="A", dependencies=["B"]),
            task(task_id="B", dependencies=["A"]),
        )


def test_duplicate_task_ids_are_refused():
    with pytest.raises(PlanError, match="duplicate task_id: A"):
        parse(task(task_id="A"), task(task_id="A"))


def test_the_whole_plan_is_refused_when_one_task_is_bad():
    """Never partially. The parts refer to each other."""
    with pytest.raises(PlanError):
        parse(task(task_id="A"), task(task_id="B", owner="nobody"))


# --- Staleness ---------------------------------------------------------------


class FakeResolved:
    def __init__(self, sha, ref="refs/heads/master", repo_id="4d49a52cb85e99fc"):
        self.sha = sha
        self.ref = ref
        self.name = "demo"
        self.project = repo_registry.Project(
            name="demo", path=".", repo_id=repo_id,
            planning_ref=ref, worktree_root="w",
        )


def test_a_plan_on_the_current_baseline_is_not_stale():
    result = parse(task())

    assert plan.is_stale(result, FakeResolved(SNAPSHOT["base_sha"])) is None


def test_a_plan_whose_baseline_has_moved_is_stale():
    """Refused rather than rebased: the intervening commits may have deleted
    the file a task was written to change, and nothing in the plan says so."""
    result = parse(task())
    why = plan.is_stale(result, FakeResolved("f" * 40))

    assert why is not None
    assert "now at ffffffffffff" in why


def test_a_plan_for_another_repository_is_stale():
    result = parse(task())
    why = plan.is_stale(result, FakeResolved(SNAPSHOT["base_sha"], repo_id="0" * 16))

    assert why is not None
    assert "repository" in why


def test_a_changed_planning_ref_is_stale():
    """The registry now points somewhere else; the plan predates that."""
    result = parse(task())
    why = plan.is_stale(
        result, FakeResolved(SNAPSHOT["base_sha"], ref="refs/heads/main")
    )

    assert why is not None
    assert "refs/heads/main" in why


# --- The prompt --------------------------------------------------------------


def test_the_prompt_carries_the_snapshot_and_asks_for_the_form():
    prompt = plan.render_prompt("SNAPSHOT GOES HERE", "make the thing faster")

    assert "SNAPSHOT GOES HERE" in prompt
    assert "make the thing faster" in prompt
    assert plan.BEGIN in prompt and plan.END in prompt
    # The planner is told it cannot grant itself the repository.
    assert "UNRESTRICTED is not available to you" in prompt
    # And is pointed at what it was not shown.
    assert "OMITTED OR TRUNCATED" in prompt


def test_the_prompt_forbids_stating_a_base():
    assert "Do not state a base_sha" in plan.render_prompt("snap")


# --- context_paths: what an author may read, as distinct from write ---------
#
# The rejection cycle's defect was an author with no shell asked to edit a file
# it had never been shown. Showing it the files it may write fixed that case.
# It does not fix the next one: a change that has to fit an interface, a
# caller, or a test the task does not write. The correction available before
# this field existed was to widen allowed_paths, which buys reading with write
# authority and is how a task authorised to touch one module comes back having
# rewritten four.


def test_context_paths_are_optional():
    """A task genuinely may need nothing but its own files."""
    assert parse(task())["tasks"][0]["context_paths"] == []


def test_context_paths_are_carried_through_separately():
    result = parse(task(
        allowed_paths=["notes"], context_paths=["src/reader.py", "tests"],
    ))

    assert result["tasks"][0]["allowed_paths"] == ["notes"]
    assert result["tasks"][0]["context_paths"] == ["src/reader.py", "tests"]


def test_a_plan_may_not_ask_to_read_the_whole_repository():
    """UNRESTRICTED context is not a reading list, it is the absence of one.

    The budget would then choose which files the author saw, in tree order,
    and present that arbitrary prefix as the files that matter.
    """
    with pytest.raises(PlanError, match="reading list"):
        parse(task(context_paths=[plan.UNRESTRICTED]))


@pytest.mark.parametrize("bad", [
    "../outside.py", "/etc/passwd", "C:\\windows\\x", ".git/config", "src/*.py",
])
def test_a_context_path_is_held_to_the_same_containment_rules(bad):
    """Both lists reach the harness as repository-relative paths."""
    with pytest.raises(PlanError):
        parse(task(context_paths=[bad]))


def test_a_context_path_error_names_the_field_it_came_from():
    """The message says which list was wrong. There are now two."""
    with pytest.raises(PlanError, match="context_paths"):
        parse(task(context_paths=["../escape"]))


def test_a_path_cannot_be_both_writable_and_reference_material():
    """The author would be handed both statements about one file at once."""
    with pytest.raises(PlanError, match="both"):
        parse(task(allowed_paths=["src"], context_paths=["src/reader.py"]))


def test_the_overlap_is_caught_in_either_direction():
    with pytest.raises(PlanError, match="both"):
        parse(task(allowed_paths=["src/reader.py"], context_paths=["src"]))


def test_a_neighbouring_prefix_is_not_an_overlap():
    """`notes` does not cover `notes-secret`; matching is by component."""
    result = parse(task(allowed_paths=["notes"], context_paths=["notes-secret"]))

    assert result["tasks"][0]["context_paths"] == ["notes-secret"]


def test_a_string_of_context_paths_is_refused_not_iterated():
    """A string is iterable. Reading it would produce one path per character."""
    with pytest.raises(PlanError, match="string"):
        parse(task(context_paths="src/reader.py"))


def test_an_unreasonable_reading_list_is_refused():
    many = [
        f"src/module_{n}.py"
        for n in range(plan.MAX_CONTEXT_PATHS_PER_TASK + 1)
    ]

    with pytest.raises(PlanError, match="context_paths"):
        parse(task(context_paths=many))


# --- Concurrent tasks that would silently revert each other ------------------
#
# The failure is not a merge conflict, which is loud. Both authors are shown
# the same file at the same base and both must return its complete contents.
# The second to integrate carries the base version of the first's edit, the
# first task's change disappears, and both tasks are approved.


def test_two_independent_tasks_may_not_write_the_same_path():
    with pytest.raises(PlanError, match="no dependency between them"):
        parse(
            task(task_id="A", allowed_paths=["src/shared.py"]),
            task(task_id="B", allowed_paths=["src/shared.py"]),
        )


def test_a_directory_and_a_file_inside_it_collide():
    with pytest.raises(PlanError, match="src/shared.py"):
        parse(
            task(task_id="A", allowed_paths=["src"]),
            task(task_id="B", allowed_paths=["src/shared.py"]),
        )


def test_a_dependency_makes_the_overlap_legitimate():
    """An edge is how a plan says these two touch the same thing."""
    result = parse(
        task(task_id="A", allowed_paths=["src/shared.py"]),
        task(task_id="B", allowed_paths=["src/shared.py"], dependencies=["A"]),
    )

    assert len(result["tasks"]) == 2


def test_a_transitive_dependency_is_enough():
    """C after B after A orders C after A, though C never names A.

    Working from declared edges alone would call A and C concurrent and refuse
    a plan that is fine.
    """
    result = parse(
        task(task_id="A", allowed_paths=["src/shared.py"]),
        task(task_id="B", allowed_paths=["src/b.py"], dependencies=["A"]),
        task(task_id="C", allowed_paths=["src/shared.py"], dependencies=["B"]),
    )

    assert len(result["tasks"]) == 3


def test_independent_tasks_may_read_the_same_files():
    """Reading is not writing. A shared interface is for sharing."""
    result = parse(
        task(task_id="A", allowed_paths=["src/a.py"], context_paths=["src/api.py"]),
        task(task_id="B", allowed_paths=["src/b.py"], context_paths=["src/api.py"]),
    )

    assert len(result["tasks"]) == 2


def test_the_colliding_pair_and_path_are_all_named():
    """A planner told only that a collision exists cannot fix it."""
    with pytest.raises(PlanError) as raised:
        parse(
            task(task_id="ALPHA", allowed_paths=["src/shared.py"]),
            task(task_id="BETA", allowed_paths=["src/shared.py"]),
        )

    message = str(raised.value)

    assert "ALPHA" in message
    assert "BETA" in message
    assert "src/shared.py" in message


# --- Grounding: the check that needs the repository --------------------------


def grounded(*tasks, tree=()):
    parsed = parse(*tasks)
    return plan.ground(parsed, "unused", ls_tree=lambda sha: list(tree))


def test_a_missing_context_path_is_a_defect():
    """Reference material can only be a file that is already there."""
    report = grounded(
        task(allowed_paths=["notes"], context_paths=["src/absent.py"]),
        tree=["README.md", "src/present.py"],
    )

    assert report["grounded"] is False
    assert report["tasks"][0]["missing_context"] == ["src/absent.py"]


def test_an_allowed_path_that_does_not_exist_is_a_file_being_created():
    """Half the tasks worth planning create files. Reported, not refused."""
    report = grounded(
        task(allowed_paths=["notes/new.md"], context_paths=["README.md"]),
        tree=["README.md"],
    )

    assert report["grounded"] is True
    assert report["tasks"][0]["creates"] == ["notes/new.md"]
    assert report["tasks"][0]["edits"] == []


def test_grounding_distinguishes_editing_from_creating():
    report = grounded(
        task(allowed_paths=["src/present.py", "src/brand_new.py"]),
        tree=["src/present.py"],
    )

    assert report["tasks"][0]["edits"] == ["src/present.py"]
    assert report["tasks"][0]["creates"] == ["src/brand_new.py"]


def test_a_directory_context_path_counts_the_files_under_it():
    report = grounded(
        task(allowed_paths=["notes"], context_paths=["src"]),
        tree=["src/a.py", "src/b.py", "README.md"],
    )

    assert report["tasks"][0]["context_files"] == 2
    assert report["tasks"][0]["missing_context"] == []


def test_an_empty_tree_is_a_failed_listing_not_a_wrong_plan():
    """Every path would report missing.

    The report would then read as a catastrophically wrong plan rather than as
    a git call that failed.
    """
    with pytest.raises(PlanError, match="lists no files"):
        grounded(task(), tree=[])
