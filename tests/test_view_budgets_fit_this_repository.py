"""An author can be shown the files a task actually asks it to change.

The view budgets are not abstract limits. They decide whether a task is
authorable at all: a writable file shown in part cannot be rewritten, because
the author must return its complete new contents and has not seen them. The
prompt says exactly that and tells it to answer CANNOT_AUTHOR instead.

So a cap below the size of a module does not degrade authoring, it removes
it. `DEFAULT_FILE_VIEW` sat at 12,000 while every controller module exceeded
it, and two tasks were refused before anyone found the cause. Raised to
20,000 it was still under `integrator.py` at 33,591 -- and the function a
task needed to change began at character 30,376, inside the part no author
would ever have seen. At 40,000 the workers and the controller's own API were
still out of reach, which is to say the swarm could not be given a task about
itself.

These assert against the repository rather than against numbers, so the
failure arrives when a module outgrows the window rather than when a task is
issued against it. The costly version of this discovery is a spent attempt
and a refusal that reads like the model's fault.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import authored_change  # noqa: E402


def size_of(relative: str) -> int:
    """Characters, as the view budget counts them."""
    return len((REPO_ROOT / relative).read_text(encoding="utf-8"))


# Every module a task is realistically scoped to write, including the ones a
# task about this swarm itself would have to touch: the two worker harnesses,
# the controller's API surface, and the process-control module.
AUTHORABLE = [
    "authored_change.py",
    "chatgpt_worker.py",
    "claude_worker.py",
    "controller/activations.py",
    "controller/api.py",
    "integrator.py",
    "supervisor.py",
    "swarm_control.py",
]


@pytest.mark.parametrize("relative", AUTHORABLE)
def test_a_module_a_task_writes_fits_in_one_file_view(relative):
    """Truncated means unauthorable, not merely abbreviated."""
    size = size_of(relative)

    assert size <= authored_change.DEFAULT_FILE_VIEW, (
        f"{relative} is {size} chars and the per-file view is "
        f"{authored_change.DEFAULT_FILE_VIEW}. An author scoped to write it "
        "would be shown part of it and told to refuse."
    )


# The one module still beyond the window, recorded rather than rediscovered.
# A task scoped to write `plan.py` cannot be authored by the API worker: it
# would be shown two thirds of the file and told to refuse. Splitting it, or
# raising the cap past it, is the way to change that -- and the cap is a cost
# paid by every prompt, so this is a deliberate exclusion and not an oversight.
KNOWN_TOO_LARGE = {"plan.py"}


def test_every_other_root_module_fits():
    """The list above is hand-kept; this covers the whole surface.

    A new module larger than the window is a task that cannot be authored,
    and a hand-kept list is exactly the thing that would not mention it. The
    known exclusion is checked both ways, so a `plan.py` that shrank under
    the cap is news too.
    """
    oversized = {
        path.name
        for path in REPO_ROOT.glob("*.py")
        if len(path.read_text(encoding="utf-8")) > authored_change.DEFAULT_FILE_VIEW
    }

    assert oversized == KNOWN_TOO_LARGE, (
        "the set of unauthorable root modules changed: newly too large "
        f"{sorted(oversized - KNOWN_TOO_LARGE)}, no longer too large "
        f"{sorted(KNOWN_TOO_LARGE - oversized)}"
    )


def test_a_module_and_its_tests_fit_together():
    """The pairing a real task uses: change the module, change its tests.

    Scoping those separately is what the contract discipline here refuses --
    a guard without its test -- so the budget has to hold both at once.
    """
    together = size_of("integrator.py") + size_of("tests/test_integrator.py")

    assert together <= authored_change.DEFAULT_VIEW_BUDGET, (
        f"integrator.py and its tests are {together} chars together and the "
        f"writable budget is {authored_change.DEFAULT_VIEW_BUDGET}. One of "
        "them would be cut or omitted."
    )


def test_the_per_file_cap_does_not_exceed_the_budget_it_spends_from():
    """A cap above its own budget is a cap that never binds.

    `room = min(per_file, total - spent)`, so a per-file view larger than the
    total silently becomes the total for the first file and nothing for the
    second -- and the second is then *omitted*, which reads to an author as a
    file that is not there.
    """
    assert authored_change.DEFAULT_FILE_VIEW <= authored_change.DEFAULT_VIEW_BUDGET
    assert authored_change.DEFAULT_FILE_VIEW <= authored_change.DEFAULT_CONTEXT_BUDGET


def test_two_writable_files_at_the_cap_are_both_shown_whole():
    """Composability: whether a second file is shown must not depend on the first.

    A budget between one and two full views makes that dependency real, and
    it is a rule nobody writing a contract could predict -- the second file
    would arrive truncated, and a truncated writable file is a refusal.
    """
    assert (
        authored_change.DEFAULT_VIEW_BUDGET >= 2 * authored_change.DEFAULT_FILE_VIEW
    ), (
        f"the writable budget ({authored_change.DEFAULT_VIEW_BUDGET}) cannot "
        f"hold two files at the per-file cap "
        f"({authored_change.DEFAULT_FILE_VIEW}), so a two-file scope can "
        "silently truncate its second file"
    )
