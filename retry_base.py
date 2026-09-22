"""Which commit a retry authors from, and what the author is told about it.

The defect this exists for (#68)
--------------------------------

A rejected task's retry was given the reviewer's rationale verbatim and then
shown the files as they stood at `base_sha` -- the original, not the candidate
that had just been rejected. So the third attempt at `T-CMD-99a5880f3e` was
told "the change removes the leading `- ` bullet marker" while looking at a
README where that bullet was still present, and "placing this under the
section header creates a contradiction" about a placement that existed only in
a commit it had never seen.

Feedback about an invisible state is not actionable. The author was not
ignoring it; it was being asked to correct a diff it had not been shown. The
apparent regression in that run -- attempt 3 losing a fix attempt 2 had made --
was the same cause: attempt 3 never saw attempt 2.

So a retry opens in the rejected candidate. The reviewer's words then describe
the tree the author is standing in.

What does not change
--------------------

The review range. `controller.activations._review_evidence` pairs a candidate
with the task's own `base_sha`, and nothing in the issuing path overrides it,
so the reviewer still reads `base_sha..candidate` -- the rejected attempt's
edits and the retry's together. The author moves; what it is judged on does
not. That is the half of the design that needed no code.

Why this is a separate module
-----------------------------

`authored_change.py` and `chatgpt_worker.py` were at 87% and 99.7% of
`DEFAULT_FILE_VIEW`, the 50,000 characters an author can be shown of one file.
Adding this to either would have taken it past the cap and made the module
unauthorable -- a task scoped to write it would be shown part of it and told to
refuse. `tests/test_view_budgets_fit_this_repository.py` caught exactly that,
which is the guard working. See #62 for the underlying size problem.
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Optional

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def rejected_candidate(task: dict) -> str:
    """The SHA of the candidate the last review rejected, or "".

    Read from `last_rejection`, which the engine writes from the reviewer's
    own report, so it names the commit that was actually judged rather than
    whatever an author most recently pushed.
    """
    sha = str(((task.get("last_rejection") or {}).get("candidate_sha")) or "").strip()

    return sha.lower() if SHA40.match(sha) else ""


def _ok(repo: str, *args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True,
        check=False, timeout=60,
    ).returncode == 0


def resolve(repo: str, task: dict, log=None, activation_id=None) -> dict:
    """Which commit this attempt authors from, and why.

    A first attempt authors from the task's base. A retry authors from the
    candidate the reviewer rejected.

    The candidate is used only when this repository can prove two things about
    it: that the object is present, and that the task's base is an ancestor of
    it. The ancestry check is the one that matters. Without it a retry could be
    based on a commit from another task, another branch, or a rewritten
    history, and the cumulative diff the reviewer is then shown would contain
    changes nobody in this task authorised -- the same class of defect as
    reviewing the wrong repository (#64), arriving through the base instead of
    the checkout.

    Neither failure blocks the attempt. A candidate that has been garbage
    collected is a normal consequence of an abandoned branch, and refusing to
    retry would turn a recoverable task into a dead one. The fallback is the
    behaviour every retry had before this, and `prompt_lines` says outright
    that the rejected attempt could not be shown -- so the author is told its
    feedback refers to something invisible rather than left to infer it.
    """
    base = str(task.get("base_sha") or "").strip().lower()
    candidate = rejected_candidate(task)
    detail = {"sha": base, "source": "base", "original_base": base, "reason": ""}

    if not candidate:
        return detail

    if candidate == base:
        return {**detail, "reason": "the rejected candidate is the base itself"}

    unusable = ""

    if not _ok(repo, "cat-file", "-e", f"{candidate}^{{commit}}"):
        unusable = "the commit is not present in this repository"
    elif not _ok(repo, "merge-base", "--is-ancestor", base, candidate):
        unusable = (
            f"the task's base {base[:12]} is not an ancestor of it, so it is "
            "not a continuation of this task"
        )

    if unusable:
        return announce({
            "sha": base, "source": "base_after_unusable_candidate",
            "original_base": base, "reason": unusable,
            "rejected_candidate": candidate,
        }, log, activation_id)

    chosen = {
        "sha": candidate, "source": "rejected_candidate",
        "original_base": base, "reason": "",
        "rejected_candidate": candidate,
    }

    return announce(chosen, log, activation_id)


def announce(detail: dict, log=None, activation_id=None) -> dict:
    """Log which tree this attempt opens in, and why. Returns `detail`.

    Folded into `resolve` rather than left to each caller because the two
    author paths are both within a few hundred characters of
    `DEFAULT_FILE_VIEW`, and a decision every caller has to narrate for itself
    is a decision that costs each of them the space to narrate it (#62).
    """
    if log is None:
        return detail

    where = f"activation {activation_id}: " if activation_id else ""

    if detail.get("source") == "rejected_candidate":
        log.info(
            "%sretry authoring from rejected candidate %s, judged cumulatively "
            "from %s", where, str(detail.get("sha") or "")[:12],
            str(detail.get("original_base") or "")[:12],
        )
    elif detail.get("source") == "base_after_unusable_candidate":
        # Warned rather than blocked: a collected object is a normal
        # consequence of an abandoned branch, and this is what every retry did
        # before #68. It is a warning because the author is about to be given
        # feedback about a change it cannot see.
        log.warning(
            "%srejected candidate %s unusable (%s); authoring from base %s",
            where, str(detail.get("rejected_candidate") or "")[:12],
            detail.get("reason"), str(detail.get("original_base") or "")[:12],
        )

    return detail


def prompt_lines(detail: Optional[dict]) -> List[str]:
    """What the author is told about the tree the files above came from.

    Without this the author reads the tree as the original and re-makes the
    edit that was sent back. The "not a floor" sentence matters as much as the
    rest: an author that believes it is judged on the increment treats the
    rejected attempt as something to build on, when reverting it is often the
    correction being asked for.
    """
    source = (detail or {}).get("source")
    base = str((detail or {}).get("original_base") or "")[:12]
    candidate = str((detail or {}).get("sha") or "")[:12]

    if source == "rejected_candidate":
        return [
            f"THE FILES SHOWN ABOVE ARE THAT REJECTED ATTEMPT'S VERSION "
            f"({candidate}), not the original. The reviewer's words describe "
            "exactly the text you have been shown, so what it objected to is "
            "visible to you, and your edits apply on top of it.",
            "",
            f"You are judged on the entire change from {base}, this task's "
            "original base -- the rejected attempt's edits and yours together. "
            "That attempt is not a floor you have to build on: undo or rewrite "
            "any part of it that the reviewer objected to, including reverting "
            "a file to how it originally stood.",
        ]

    if source == "base_after_unusable_candidate":
        named = str((detail or {}).get("rejected_candidate") or "")[:12] or "unknown"

        return [
            "THE FILES SHOWN ABOVE ARE THE ORIGINAL, NOT THE REJECTED ATTEMPT. "
            f"That attempt ({named}) could not be read in this repository, so "
            "the change the reviewer was describing is not visible to you: "
            f"{(detail or {}).get('reason') or 'reason not recorded'}. Read "
            "the rationale as a description of a change that is not in front "
            "of you, and re-derive the correction from the objective rather "
            "than assuming which lines it refers to.",
        ]

    return []


def cumulative_paths(repo, original_base: Optional[str], sha: str) -> List[str]:
    """Every path the range `original_base..sha` touches, slash-separated.

    Empty when there is no separate original base -- the attempt started from
    the task's base, so the paths written are the whole of the change and the
    caller has already authorised each one.

    Returns [] rather than raising when git cannot answer. The caller decides
    what an unanswerable range means; every caller here already refuses on
    evidence it does have.
    """
    base = str(original_base or "").strip()

    if not base:
        return []

    listing = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{sha}"], cwd=str(repo),
        capture_output=True, encoding="utf-8", errors="replace",
        check=False, timeout=60,
    )

    if listing.returncode != 0:
        return []

    return sorted({
        line.strip().replace("\\", "/")
        for line in (listing.stdout or "").splitlines() if line.strip()
    })


def outside_contract(paths, allowed, unrestricted: bool = False) -> List[str]:
    """Which of `paths` the contract does not authorise."""
    if unrestricted:
        return []

    from authored_change import matches_allowed

    return sorted(p for p in paths if not matches_allowed(p, list(allowed)))


def check(repo, original_base: Optional[str], sha: str, scope) -> tuple:
    """(paths in the cumulative range, why it must not be reviewed or "").

    The paths an attempt writes are authorised as it writes them. On a retry
    the range the reviewer reads also holds the rejected attempt's edits,
    which arrive through the base rather than through anything this run wrote,
    and so were never checked at this point.

    They were checked when that attempt was written, so this should always
    pass -- which is exactly the condition under which a base gets taken on
    trust. An out-of-scope path here means the commit being built on is not
    the one this task produced, and a candidate carrying unauthorised changes
    must not reach a reviewer who will read them as this task's work.
    """
    paths = cumulative_paths(repo, original_base, sha)
    outside = outside_contract(paths, scope.paths, scope.unrestricted)

    if not outside:
        return paths, ""

    return paths, (
        f"the change from {str(original_base or '')[:12]} to this commit "
        f"touches {len(outside)} path(s) the contract does not authorise: "
        + ", ".join(outside[:10])
        + ". Refusing to hand a reviewer a candidate carrying changes this "
        "task never authorised."
    )


def rejection_section(task: dict, retry_from: Optional[dict] = None) -> List[str]:
    """What the last review sent this task back for, if anything.

    Included verbatim and attributed, because a retry that is not told what
    was wrong is not an attempt at the correction -- it is the same generation
    with the same inputs, and it will produce the same candidate. The
    reviewer's words are labelled as the reviewer's: they are a judgment to
    address, not part of the objective, and an author that treats them as new
    requirements will drift away from what was actually asked for.

    `retry_from` says which tree the files above were read from -- see
    `prompt_lines` and this module's header for why that decides whether the
    feedback is actionable at all (#68).
    """
    rejection = task.get("last_rejection") or {}
    rationale = str(rejection.get("rationale") or "").strip()

    if not rationale:
        return []

    return [
        "",
        "-" * 60,
        "A PREVIOUS ATTEMPT AT THIS TASK WAS REJECTED IN REVIEW.",
        "",
        "The reviewer said:",
        rationale,
        "",
    ] + prompt_lines(retry_from) + [
        "",
        "Address that. The objective above is unchanged and is still what you "
        "are being judged against; the rejection tells you where the last "
        "attempt fell short of it.",
        "",
        "If addressing it means moving content, adding or retitling a section, "
        "or otherwise restructuring a file rather than rewording it in place, "
        "that is in scope -- provided every file you write is one you are "
        "authorised to write. A rejection about where something sits is not "
        "answered by changing what it says.",
    ]
