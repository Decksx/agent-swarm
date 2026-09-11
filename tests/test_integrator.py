"""The integrator refuses far more often than it merges.

`READY_INTEGRATION` is where every task in this system has ever stopped. The
state machine has modelled integration since v7 and nothing drove it, so there
is no live incident behind these tests -- which makes it more important, not
less, that each refusal is exercised before the first real merge rather than
discovered by it.

The failures worth preventing all look like success at the moment they happen:
a branch that moved after approval still merges cleanly, a target that advanced
still accepts the merge, a conflict resolution still produces a tree, and a
merge API still returns 200 when nothing landed.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import integrator
from integrator import Evidence, IntegrationRefused, Plan


CANDIDATE = "a" * 40
TARGET = "b" * 40
MERGED = "c" * 40


def plan(**over) -> Plan:
    base = {
        "task_id": "T-1",
        "repo": "/nonexistent",
        "candidate_sha": CANDIDATE,
        "target_ref": "refs/heads/master",
        "target_sha_expected": TARGET,
        "pr_number": 91,
        "evidence": (
            Evidence(name="unit", command="pytest tests", exit_code=0, passed=53),
            Evidence(name="full", command="pytest", exit_code=0, passed=2287,
                     skipped=3),
        ),
    }
    base.update(over)
    return Plan(**base)


# --- Approval is the controller's state, and nothing else -------------------


def test_a_task_not_in_ready_integration_is_refused():
    with pytest.raises(IntegrationRefused, match="READY_INTEGRATION"):
        integrator.check_approval(
            {"state": "AUTHORING", "approved_candidate_sha": CANDIDATE}, plan()
        )


def test_an_approved_task_with_the_matching_candidate_passes():
    integrator.check_approval(
        {"state": "READY_INTEGRATION", "approved_candidate_sha": CANDIDATE},
        plan(),
    )


def test_a_candidate_that_moved_after_approval_is_refused():
    """The failure most likely to look like success: the branch still merges
    cleanly, and the tree that lands is not the one anybody read."""
    with pytest.raises(IntegrationRefused, match="different tree"):
        integrator.check_approval(
            {"state": "READY_INTEGRATION", "approved_candidate_sha": "d" * 40},
            plan(),
        )


def test_a_task_recording_no_candidate_is_refused_rather_than_assumed():
    """Refusing to take the branch head as "what was reviewed".

    The field is `approved_candidate_sha`, not a generic `candidate_sha`. The
    generic name would be read as "the current candidate" by the next person
    to touch it, and an integrator reading that would merge whatever was last
    authored rather than what was last approved.
    """
    with pytest.raises(
        IntegrationRefused, match="no\s+approved_candidate_sha"
    ):
        integrator.check_approval({"state": "READY_INTEGRATION"}, plan())


# --- Evidence is named suites with counts, not an assurance -----------------


def test_no_evidence_is_refused():
    with pytest.raises(IntegrationRefused, match="no test evidence"):
        integrator.check_evidence(plan(evidence=()), required=["unit"])


def test_a_missing_required_suite_is_refused():
    with pytest.raises(IntegrationRefused, match="integration"):
        integrator.check_evidence(plan(), required=["integration"])


def test_a_failing_suite_is_refused_whatever_the_review_said():
    with pytest.raises(IntegrationRefused, match="exited 1"):
        integrator.check_evidence(
            plan(evidence=(Evidence("unit", "pytest", 1, 0, failed=3),)),
            required=["unit"],
        )


def test_failures_reported_alongside_exit_zero_are_refused():
    """A result nobody should have to reconcile."""
    with pytest.raises(IntegrationRefused, match="failure"):
        integrator.check_evidence(
            plan(evidence=(Evidence("unit", "pytest", 0, 10, failed=2),)),
            required=["unit"],
        )


def test_a_suite_that_ran_nothing_is_refused():
    """The deploy gate's rule, for the same reason: an all-skipped suite exits
    0 having verified nothing, and "no failures" renders almost identically to
    "no tests"."""
    with pytest.raises(IntegrationRefused, match="Nothing failed"):
        integrator.check_evidence(
            plan(evidence=(Evidence("unit", "pytest", 0, 0, skipped=40),)),
            required=["unit"],
        )


def test_green_evidence_passes():
    integrator.check_evidence(plan(), required=["unit", "full"])


# --- The target must not have moved -----------------------------------------


def test_a_target_that_moved_is_refused(monkeypatch):
    """The window between pinning and merging is exactly where somebody else's
    merge lands, and it may carry the change this candidate conflicts with."""
    monkeypatch.setattr(integrator, "pin_target", lambda p: "e" * 40)

    with pytest.raises(IntegrationRefused, match="It moved"):
        integrator.check_target_unmoved(plan())


def test_an_unmoved_target_passes(monkeypatch):
    monkeypatch.setattr(integrator, "pin_target", lambda p: TARGET)

    assert integrator.check_target_unmoved(plan()) == TARGET


def test_the_target_is_read_from_the_remote(monkeypatch):
    """Not from a local ref, which is whatever this host last fetched."""
    seen = {}

    def fake_git(repo, *args):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, f"{TARGET}\trefs/heads/master\n", "")

    monkeypatch.setattr(integrator, "_git", fake_git)

    assert integrator.pin_target(plan()) == TARGET
    assert seen["args"][0] == "ls-remote"
    assert "origin" in seen["args"]


def test_an_unresolvable_target_is_refused(monkeypatch):
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 0, "", ""),
    )

    with pytest.raises(IntegrationRefused, match="did not resolve"):
        integrator.pin_target(plan())


# --- The pull request, and the conflict that must never be resolved ---------


def pr_json(**over):
    body = {
        "number": 91, "state": "OPEN", "isDraft": False,
        "headRefOid": CANDIDATE, "baseRefOid": TARGET,
        "baseRefName": "master", "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }
    body.update(over)
    return body


def fake_gh(monkeypatch, payload, code=0):
    monkeypatch.setattr(
        integrator, "_gh",
        lambda *a: subprocess.CompletedProcess(a, code, json.dumps(payload), ""),
    )


def test_a_clean_pr_passes(monkeypatch):
    fake_gh(monkeypatch, pr_json())

    assert integrator.check_pr(plan(), repo_slug="o/r")["number"] == 91


def test_a_conflicting_pr_is_refused_and_not_resolved(monkeypatch):
    """The tree that would land after a resolution is not the tree that was
    reviewed, and resolving one is a judgment no reviewer made."""
    fake_gh(monkeypatch, pr_json(mergeable="CONFLICTING"))

    with pytest.raises(IntegrationRefused, match="will not resolve it"):
        integrator.check_pr(plan(), repo_slug="o/r")


def test_an_unknown_mergeable_answer_is_refused(monkeypatch):
    """Refusing to merge on an answer that is not yes."""
    fake_gh(monkeypatch, pr_json(mergeable="UNKNOWN"))

    with pytest.raises(IntegrationRefused, match="not yes"):
        integrator.check_pr(plan(), repo_slug="o/r")


def test_a_draft_pr_is_refused(monkeypatch):
    """Marking it ready is a person's decision."""
    fake_gh(monkeypatch, pr_json(isDraft=True))

    with pytest.raises(IntegrationRefused, match="draft"):
        integrator.check_pr(plan(), repo_slug="o/r")


def test_a_closed_pr_is_refused(monkeypatch):
    fake_gh(monkeypatch, pr_json(state="MERGED"))

    with pytest.raises(IntegrationRefused, match="not OPEN"):
        integrator.check_pr(plan(), repo_slug="o/r")


def test_a_pr_head_that_is_not_the_candidate_is_refused(monkeypatch):
    fake_gh(monkeypatch, pr_json(headRefOid="f" * 40))

    with pytest.raises(IntegrationRefused, match="branch moved after approval"):
        integrator.check_pr(plan(), repo_slug="o/r")


def test_a_pr_based_on_a_different_target_is_refused(monkeypatch):
    fake_gh(monkeypatch, pr_json(baseRefOid="f" * 40))

    with pytest.raises(IntegrationRefused, match="pinned target"):
        integrator.check_pr(plan(), repo_slug="o/r")


# --- COMPLETE only after the remote says so ---------------------------------


def test_a_merge_that_did_not_move_the_target_is_refused(monkeypatch):
    """A merge API returning success is a claim about a request."""
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 0, "", ""),
    )
    monkeypatch.setattr(integrator, "pin_target", lambda p: TARGET)

    with pytest.raises(IntegrationRefused, match="Nothing landed"):
        integrator.verify_landed(plan(), MERGED)


def test_a_target_that_moved_without_containing_the_merge_is_refused(monkeypatch):
    """Something else landed; this integration is not complete."""
    def fake_git(repo, *args):
        code = 1 if args[0] == "merge-base" else 0
        return subprocess.CompletedProcess(args, code, "", "")

    monkeypatch.setattr(integrator, "_git", fake_git)
    monkeypatch.setattr(integrator, "pin_target", lambda p: "9" * 40)

    with pytest.raises(IntegrationRefused, match="does not contain"):
        integrator.verify_landed(plan(), MERGED)


def test_a_landed_merge_verifies(monkeypatch):
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 0, "", ""),
    )
    monkeypatch.setattr(integrator, "pin_target", lambda p: "9" * 40)

    integrator.verify_landed(plan(), MERGED)


def test_a_failed_fetch_is_not_reported_as_a_landing(monkeypatch):
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 1, "", "network down"),
    )

    with pytest.raises(IntegrationRefused, match="could not fetch"):
        integrator.verify_landed(plan(), MERGED)


# --- What the ledger is told -------------------------------------------------


def test_the_ledger_record_carries_every_measured_figure():
    record = integrator.ledger_record(
        plan(), target_before=TARGET, merge_sha=MERGED,
        target_after="9" * 40, authority="controller", actor="claudecode",
    )

    assert record["candidate_sha"] == CANDIDATE
    assert record["target_sha_before"] == TARGET
    assert record["merge_sha"] == MERGED
    assert record["target_sha_after"] == "9" * 40
    assert record["authority"] == "controller"
    assert record["pr_number"] == 91
    assert [e["name"] for e in record["evidence"]] == ["unit", "full"]
    assert record["method"] == "github_pr_merge"


def test_the_record_names_the_before_and_after_separately():
    """A ledger that recorded only the merge SHA could not answer what the
    branch was before, which is what a rollback needs."""
    record = integrator.ledger_record(
        plan(), target_before=TARGET, merge_sha=MERGED,
        target_after="9" * 40, authority="controller", actor="claudecode",
    )

    assert record["target_sha_before"] != record["target_sha_after"]


# --- The merge itself, and the race it must not leave open ------------------


def test_the_merge_names_the_head_that_must_still_be_current(monkeypatch):
    """Without --match-head-commit the call is "merge PR #N", and a push
    landing between the check and the call is merged instead -- the exact race
    every earlier check exists to close, left open at the one moment it
    matters."""
    seen = {}

    def fake_gh(*args):
        seen.setdefault("calls", []).append(args)
        if args[0:2] == ("pr", "merge"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"mergeCommit": {"oid": MERGED},
                                 "state": "MERGED"}), "")

    monkeypatch.setattr(integrator, "_gh", fake_gh)

    assert integrator.merge_pr(
        plan(), repo_slug="o/r", expected_head=CANDIDATE
    ) == MERGED

    merge_call = seen["calls"][0]

    assert "--match-head-commit" in merge_call
    assert CANDIDATE in merge_call
    assert "--merge" in merge_call
    assert "--squash" not in merge_call and "--rebase" not in merge_call


def test_a_forge_refusal_is_not_reported_as_a_merge(monkeypatch):
    monkeypatch.setattr(
        integrator, "_gh",
        lambda *a: subprocess.CompletedProcess(a, 1, "", "head has changed"),
    )

    with pytest.raises(IntegrationRefused, match="refused by the forge"):
        integrator.merge_pr(plan(), repo_slug="o/r", expected_head=CANDIDATE)


def test_a_merge_whose_commit_cannot_be_named_is_refused(monkeypatch):
    def fake_gh(*args):
        if args[0:2] == ("pr", "merge"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, json.dumps({}), "")

    monkeypatch.setattr(integrator, "_gh", fake_gh)

    with pytest.raises(IntegrationRefused, match="cannot be named"):
        integrator.merge_pr(plan(), repo_slug="o/r", expected_head=CANDIDATE)


# --- The merged tree is the approved tree -----------------------------------


def test_a_merged_tree_identical_to_the_candidate_passes(monkeypatch):
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(a, 0, "", ""),
    )

    integrator.check_tree_identical(plan(), MERGED)


def test_a_merged_tree_that_differs_is_refused(monkeypatch):
    """Catches what nothing else can: a squash that rewrote content, a merge
    driver that resolved something, a forge setting nobody knew was on."""
    monkeypatch.setattr(
        integrator, "_git",
        lambda repo, *a: subprocess.CompletedProcess(
            a, 0, "src/api.py\nsrc/other.py\n", ""),
    )

    with pytest.raises(IntegrationRefused, match="not what was reviewed"):
        integrator.check_tree_identical(plan(), MERGED)


# --- CI evidence comes from the runner, by commit ---------------------------


def test_ci_is_asked_for_by_commit_not_by_branch(monkeypatch):
    """A branch's checks are the checks of whatever its head happens to be
    now; this integration is about one commit."""
    seen = {}

    def fake_gh(*args):
        seen["args"] = args
        return subprocess.CompletedProcess(
            args, 0,
            json.dumps({"name": "build", "conclusion": "success",
                        "status": "completed", "id": 1}), "")

    monkeypatch.setattr(integrator, "_gh", fake_gh)
    evidence = integrator.ci_evidence(CANDIDATE, repo_slug="o/r")

    assert CANDIDATE in " ".join(seen["args"])
    assert evidence[0].name == "ci:build"
    assert evidence[0].passed == 1


def test_a_failing_check_becomes_evidence_of_failure_not_silence(monkeypatch):
    """Returning only the passes would make a red build indistinguishable from
    a repository with no CI at all, and those need opposite responses."""
    monkeypatch.setattr(
        integrator, "_gh",
        lambda *a: subprocess.CompletedProcess(
            a, 0, json.dumps({"name": "build", "conclusion": "failure",
                              "status": "completed", "id": 1}), ""),
    )

    evidence = integrator.ci_evidence(CANDIDATE, repo_slug="o/r")

    assert evidence[0].exit_code == 1
    with pytest.raises(IntegrationRefused):
        integrator.check_evidence(plan(evidence=evidence), required=["ci:build"])


def test_a_still_running_check_is_refused(monkeypatch):
    """Merging while a check is running is merging on a result nobody has."""
    monkeypatch.setattr(
        integrator, "_gh",
        lambda *a: subprocess.CompletedProcess(
            a, 0, json.dumps({"name": "build", "conclusion": None,
                              "status": "in_progress", "id": 1}), ""),
    )

    with pytest.raises(IntegrationRefused, match="not completed"):
        integrator.ci_evidence(CANDIDATE, repo_slug="o/r")


def test_unreadable_ci_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(
        integrator, "_gh",
        lambda *a: subprocess.CompletedProcess(a, 1, "", "404"),
    )

    with pytest.raises(IntegrationRefused, match="not a build that passed"):
        integrator.ci_evidence(CANDIDATE, repo_slug="o/r")
