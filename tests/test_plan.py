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
        "existing_work_checked": {
            "searched": ["src/api.py", "tests/test_reader.py"],
            "why_missing": "Nothing under src/ implements this and no test "
                           "asserts it; the closest is api.py, which only "
                           "declares the interface.",
        },
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


# --- Semantic grounding: the failure structural grounding did not catch -----
#
# Four proposals, every path resolving, no collisions, all four rejected. Each
# duplicated an implementation or a test suite that already existed: a
# documentation task for a 553-line module that already documents itself, a
# test task for a suite that already had 21 tests, and a config validator
# proposed beside scripts/cbz_routing.py, which already had parse(), load() and
# RoutingConfigError.
#
# The planner had been told, accurately, that no source was included. It said
# so in its summary and planned anyway -- because its only alternatives were to
# guess or to produce nothing, and producing nothing reads as failure. "Safe to
# author" and "worth doing" came apart, and nothing in the loop could tell.


def test_a_task_must_say_what_it_searched():
    """A path being free is not evidence that the job is not already done."""
    entry = task()
    del entry["existing_work_checked"]

    with pytest.raises(PlanError, match="existing_work_checked"):
        parse(entry)


def test_an_empty_search_is_refused():
    with pytest.raises(PlanError, match="searched"):
        parse(task(existing_work_checked={
            "searched": [], "why_missing": "x" * 60,
        }))


def test_a_search_of_only_blank_entries_is_refused():
    with pytest.raises(PlanError, match="searched"):
        parse(task(existing_work_checked={
            "searched": ["", "   "], "why_missing": "x" * 60,
        }))


@pytest.mark.parametrize("why", ["", "N/A", "none", "It does not exist yet."])
def test_a_non_answer_about_why_it_is_missing_is_refused(why):
    """Every one of these is shorter than engaging with the question."""
    with pytest.raises(PlanError, match="why_missing"):
        parse(task(existing_work_checked={
            "searched": ["src/api.py"], "why_missing": why,
        }))


def test_the_search_is_carried_onto_the_task():
    result = parse(task(existing_work_checked={
        "searched": ["src/api.py", "tests/test_reader.py"],
        "why_missing": "api.py declares the interface and nothing implements "
                       "the caching described here.",
    }))

    assert result["tasks"][0]["existing_work_checked"]["searched"] == [
        "src/api.py", "tests/test_reader.py"
    ]


# --- Work in progress is the likeliest thing to duplicate -------------------


def test_a_task_writing_an_uncommitted_file_is_not_grounded():
    """Somebody is editing it now. A candidate written against the baseline
    would conflict with or silently discard their work."""
    report = plan.ground(
        parse(task(allowed_paths=["src/live.py"], context_paths=["README.md"])),
        "unused",
        ls_tree=lambda sha: ["README.md", "src/live.py", "src/other.py"],
        dirty=["src/live.py"],
    )

    assert report["grounded"] is False
    assert report["tasks"][0]["active_work_collisions"] == ["src/live.py"]


def test_a_directory_scope_collides_with_a_dirty_file_inside_it():
    report = plan.ground(
        parse(task(allowed_paths=["src"], context_paths=["README.md"])),
        "unused",
        ls_tree=lambda sha: ["README.md", "src/live.py"],
        dirty=["src/live.py"],
    )

    assert report["tasks"][0]["active_work_collisions"] == ["src/live.py"]


def test_a_clean_tree_collides_with_nothing():
    report = plan.ground(
        parse(task(allowed_paths=["src/new.py"], context_paths=["README.md"])),
        "unused",
        ls_tree=lambda sha: ["README.md", "src/other.py"],
        dirty=[],
    )

    assert report["tasks"][0]["active_work_collisions"] == []


def test_an_unrelated_dirty_file_is_not_a_collision():
    report = plan.ground(
        parse(task(allowed_paths=["docs/new.md"],
                   context_paths=["README.md"],
                   existing_work_checked={
                       "searched": ["docs/other.md"],
                       "why_missing": "docs/other.md covers the adjacent "
                                      "subject and not this one.",
                   })),
        "unused",
        ls_tree=lambda sha: ["README.md", "docs/other.md", "src/live.py"],
        dirty=["src/live.py"],
    )

    assert report["tasks"][0]["active_work_collisions"] == []


# --- The ROUTING-1 check: a free path in a directory nobody read ------------


def test_a_new_file_in_an_unread_directory_is_not_grounded():
    """This is ROUTING-1 exactly. `scripts/validate_routing_config.py` was
    proposed beside `scripts/cbz_routing.py`, which already did the job, and
    which appeared in neither its context nor its search."""
    report = plan.ground(
        parse(task(
            allowed_paths=["scripts/validate_routing_config.py"],
            context_paths=["docs/cbz_watcher.md"],
            existing_work_checked={
                "searched": ["docs/cbz_watcher.md"],
                "why_missing": "The document describes routing but no "
                               "validator is mentioned anywhere in it.",
            },
        )),
        "unused",
        ls_tree=lambda sha: [
            "docs/cbz_watcher.md", "scripts/cbz_routing.py", "scripts/other.py",
        ],
    )

    assert report["grounded"] is False
    blind = report["tasks"][0]["unexamined_directories"][0]
    assert blind["creates"] == "scripts/validate_routing_config.py"
    assert "scripts/cbz_routing.py" in blind["examples"]


def test_reading_one_sibling_is_enough():
    """Requiring all of them would refuse every task touching a large
    directory, and a check that always fires gets switched off."""
    report = plan.ground(
        parse(task(
            allowed_paths=["scripts/validate_routing_config.py"],
            context_paths=["scripts/cbz_routing.py"],
            existing_work_checked={
                "searched": ["scripts/cbz_routing.py"],
                "why_missing": "cbz_routing.py parses and loads but exposes no "
                               "standalone entry point for checking a file.",
            },
        )),
        "unused",
        ls_tree=lambda sha: ["scripts/cbz_routing.py", "scripts/other.py"],
    )

    assert report["tasks"][0]["unexamined_directories"] == []
    assert report["grounded"] is True


def test_a_sibling_named_only_in_the_search_counts():
    """Searching a file is looking at it. It need not also be context."""
    report = plan.ground(
        parse(task(
            allowed_paths=["scripts/new.py"],
            context_paths=["README.md"],
            existing_work_checked={
                "searched": ["scripts/cbz_routing.py"],
                "why_missing": "cbz_routing.py handles routing only and does "
                               "nothing resembling what this task adds.",
            },
        )),
        "unused",
        ls_tree=lambda sha: ["README.md", "scripts/cbz_routing.py"],
    )

    assert report["tasks"][0]["unexamined_directories"] == []


def test_a_brand_new_directory_has_nothing_to_read():
    report = plan.ground(
        parse(task(allowed_paths=["newdir/thing.py"], context_paths=["README.md"])),
        "unused",
        ls_tree=lambda sha: ["README.md", "src/api.py", "tests/test_reader.py"],
    )

    assert report["tasks"][0]["unexamined_directories"] == []
    assert report["grounded"] is True


def test_editing_an_existing_file_is_not_subject_to_the_check():
    """The rule is about adding beside code you have not read. Editing a file
    means it is in scope and shown in full already."""
    report = plan.ground(
        parse(task(allowed_paths=["scripts/cbz_routing.py"],
                   context_paths=["README.md"])),
        "unused",
        ls_tree=lambda sha: ["README.md", "scripts/cbz_routing.py", "scripts/x.py"],
    )

    assert report["tasks"][0]["unexamined_directories"] == []


# --- NEEDS_CONTEXT: asking is an outcome, not a failure ---------------------


def context_reply(**over):
    body = {
        "outcome": "needs_context",
        "reason": "I cannot tell whether the routing validator already exists "
                  "without reading the routing implementation.",
        "requests": [
            {"path": "scripts/cbz_routing.py",
             "why": "to see whether it already validates configuration"},
        ],
    }
    body.update(over)
    return f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}"


def test_a_context_request_is_recognised_as_its_own_outcome():
    result = plan.parse_reply(context_reply(), snapshot=SNAPSHOT)

    assert result["outcome"] == "needs_context"
    assert result["requests"][0]["path"] == "scripts/cbz_routing.py"


def test_a_plan_is_still_recognised_as_a_plan():
    result = plan.parse_reply(reply(task()), snapshot=SNAPSHOT)

    assert result["outcome"] == "plan"
    assert result["plan"]["tasks"][0]["task_id"] == "T-1"


def test_requests_without_the_outcome_key_are_still_read_as_a_request():
    """The right answer in the wrong envelope. Refusing on a formality would
    spend a call to get the same content back under a different key."""
    result = plan.parse_reply(
        context_reply(outcome="plan"), snapshot=SNAPSHOT
    )

    assert result["outcome"] == "needs_context"


def test_a_request_must_say_what_it_is_missing():
    with pytest.raises(PlanError, match="cannot evaluate|nobody can evaluate"):
        plan.parse_reply(context_reply(reason="need code"), snapshot=SNAPSHOT)


def test_every_request_must_say_why():
    """Each one costs a call to fulfil and somebody decides whether to spend
    it. "I need to see the code" is not a request anyone can evaluate."""
    with pytest.raises(PlanError, match="no reason given"):
        plan.parse_reply(
            context_reply(requests=[{"path": "src/api.py", "why": "need"}]),
            snapshot=SNAPSHOT,
        )


def test_an_empty_request_list_is_refused():
    """If nothing specific is missing, the answer is a plan."""
    with pytest.raises(PlanError, match="no requests"):
        plan.parse_reply(context_reply(requests=[]), snapshot=SNAPSHOT)


def test_a_request_naming_neither_path_nor_symbol_is_refused():
    with pytest.raises(PlanError, match="neither a path nor a symbol"):
        plan.parse_reply(
            context_reply(requests=[{"why": "because I would like to know"}]),
            snapshot=SNAPSHOT,
        )


def test_the_repository_cannot_be_requested_one_file_at_a_time():
    many = [
        {"path": f"src/module_{n}.py", "why": "to understand the module"}
        for n in range(plan.MAX_CONTEXT_REQUESTS + 1)
    ]

    with pytest.raises(PlanError, match="one file at a time"):
        plan.parse_reply(context_reply(requests=many), snapshot=SNAPSHOT)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", ".git/config"])
def test_a_requested_path_is_held_to_the_containment_rules(bad):
    with pytest.raises(PlanError):
        plan.parse_reply(
            context_reply(requests=[
                {"path": bad, "why": "to read the configuration in it"},
            ]),
            snapshot=SNAPSHOT,
        )


def test_a_symbol_may_be_requested_without_a_path():
    """The host cannot fulfil it, but refusing to parse it would stop the
    planner saying the one thing it may genuinely know: a name."""
    result = plan.parse_reply(
        context_reply(requests=[
            {"symbol": "RoutingConfigError",
             "why": "to find out whether validation already raises it"},
        ]),
        snapshot=SNAPSHOT,
    )

    assert result["requests"][0]["symbol"] == "RoutingConfigError"
    assert result["requests"][0]["path"] == ""


# --- NEEDS_SEARCH: the question asking for files by path cannot answer ------
#
# A planner read provenance_backfill_cli.py in full, correctly observed that
# tests/test_provenance_backfill_cli.py did not exist, and proposed writing it.
# tests/test_provenance_backfill_planner.py was already calling cli.main() six
# times and asserting both exit-130 paths. No number of requests for files by
# path surfaces that, because naming the file requires already suspecting the
# answer. One search for "cli.main(" finds it.


def search_reply(*queries, reason=None):
    body = {
        "outcome": "needs_search",
        "reason": reason or "I need to know whether this is already tested "
                            "before proposing a test for it.",
        "queries": [
            {"query": q, "why": "to see whether it already exists"}
            if isinstance(q, str) else q
            for q in queries
        ],
    }
    return f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}"


def test_a_search_request_is_its_own_outcome():
    result = plan.parse_reply(search_reply("cli.main("), snapshot=SNAPSHOT)

    assert result["outcome"] == "needs_search"
    assert result["queries"][0]["query"] == "cli.main("


def test_queries_without_the_outcome_key_are_still_read_as_a_search():
    body = {
        "reason": "I need to know whether this is already covered somewhere.",
        "queries": [{"query": "cli.main(", "why": "to find existing tests"}],
    }
    result = plan.parse_reply(
        f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}", snapshot=SNAPSHOT
    )

    assert result["outcome"] == "needs_search"


def test_a_bare_string_query_is_accepted():
    """The shape a model reaches for first. Refusing it would spend a call to
    get the same query back wrapped in an object."""
    body = {
        "outcome": "needs_search",
        "reason": "checking whether the helper already exists anywhere",
        "queries": ["def read_guard"],
    }
    result = plan.parse_reply(
        f"{plan.BEGIN}\n{json.dumps(body)}\n{plan.END}", snapshot=SNAPSHOT
    )

    assert result["queries"][0]["query"] == "def read_guard"


def test_a_search_must_say_what_it_is_trying_to_find_out():
    with pytest.raises(PlanError, match="cannot be spent|nobody can evaluate"):
        plan.parse_reply(search_reply("cli.main(", reason="looking"), snapshot=SNAPSHOT)


@pytest.mark.parametrize("query", ["", "a", "ab"])
def test_a_query_too_short_to_narrow_anything_is_refused(query):
    """One or two characters match everything, and the truncated result would
    read as "this is everywhere" -- the opposite of what a search is for."""
    with pytest.raises(PlanError, match="characters"):
        plan.parse_reply(search_reply(query), snapshot=SNAPSHOT)


def test_a_multi_line_query_is_refused():
    """git grep matches within a line, so it would return nothing -- and
    nothing is indistinguishable from the text being absent, which is the most
    misleading answer a search can give."""
    with pytest.raises(PlanError, match="newline"):
        plan.parse_reply(search_reply("def a():\n    return 1"), snapshot=SNAPSHOT)


def test_the_repository_cannot_be_grepped_through_the_model():
    many = [f"query_number_{n}" for n in range(plan.MAX_SEARCH_QUERIES + 1)]

    with pytest.raises(PlanError, match="grepping the repository"):
        plan.parse_reply(search_reply(*many), snapshot=SNAPSHOT)


def test_duplicate_queries_are_collapsed():
    result = plan.parse_reply(
        search_reply("cli.main(", "cli.main(", "other"), snapshot=SNAPSHOT
    )

    assert [q["query"] for q in result["queries"]] == ["cli.main(", "other"]


def test_a_search_path_is_held_to_the_containment_rules():
    with pytest.raises(PlanError):
        plan.parse_reply(
            search_reply({"query": "anything", "why": "to look",
                          "path": "../../etc"}),
            snapshot=SNAPSHOT,
        )


def test_an_empty_query_list_is_refused():
    with pytest.raises(PlanError, match="no queries"):
        plan.parse_reply(search_reply(), snapshot=SNAPSHOT)


def test_searched_queries_are_recorded_on_the_task():
    result = parse(task(existing_work_checked={
        "searched": ["src/api.py"],
        "queries": ["def read(", "class Reader"],
        "why_missing": "Neither query found an implementation of the caching "
                       "behaviour this task adds.",
    }))

    assert result["tasks"][0]["existing_work_checked"]["queries"] == [
        "def read(", "class Reader",
    ]


def test_queries_are_optional_on_a_task():
    assert parse(task())["tasks"][0]["existing_work_checked"]["queries"] == []
