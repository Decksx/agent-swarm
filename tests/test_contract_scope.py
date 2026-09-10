"""A contract that cannot be read authorises nothing.

The correction these pin down: `allowed_paths` used to be parsed leniently and
an empty result meant unrestricted, so the quietest possible failure -- a
truncated contract, a misspelt key, a format the hand-parser had never seen --
produced the widest possible authority. Every case below is one of those quiet
failures, and each one must now refuse.
"""

from __future__ import annotations

import pytest

import authored_change
from authored_change import ContractError, Scope


CONTRACT = """
task_id: T-0042
title: Add a note
allowed_paths:
  - notes
  - docs/changelog.md
"""


# --- What a readable contract says ------------------------------------------


def test_a_listed_scope_is_read(repo=None):
    scope = authored_change.parse_scope(CONTRACT)

    assert scope.unrestricted is False
    assert scope.paths == ("notes", "docs/changelog.md")


def test_an_inline_list_is_read():
    scope = authored_change.parse_scope("allowed_paths: [notes, 'docs/x.md']")

    assert scope.paths == ("notes", "docs/x.md")


def test_a_list_ends_at_the_next_key():
    contract = (
        "allowed_paths:\n"
        "  - notes\n"
        "author_self_checks:\n"
        "  - shell: pwsh\n"
    )

    assert authored_change.parse_scope(contract).paths == ("notes",)


def test_the_controller_record_wins_over_the_contract_text():
    """The controller's own column is the authoritative statement."""
    scope = authored_change.parse_scope(CONTRACT, declared=["src/only.py"])

    assert scope.paths == ("src/only.py",)


# --- What silence must not say ----------------------------------------------


def test_no_allowed_paths_key_at_all_refuses():
    with pytest.raises(ContractError, match="does not declare allowed_paths"):
        authored_change.parse_scope("task_id: T-1\ntitle: something\n")


def test_an_empty_contract_refuses():
    with pytest.raises(ContractError):
        authored_change.parse_scope("")


def test_a_none_contract_refuses():
    with pytest.raises(ContractError):
        authored_change.parse_scope(None)


def test_the_key_with_no_entries_refuses():
    """The likeliest shape of a half-written contract."""
    with pytest.raises(ContractError, match="lists none"):
        authored_change.parse_scope("allowed_paths:\ntitle: x\n")


def test_an_empty_inline_list_refuses():
    with pytest.raises(ContractError, match="authorises nothing"):
        authored_change.parse_scope("allowed_paths: []")


def test_a_contract_truncated_mid_key_refuses():
    """A generation cut short by a token limit is a real arrival shape."""
    with pytest.raises(ContractError):
        authored_change.parse_scope("task_id: T-1\nallowed_pa")


def test_a_scalar_this_parser_does_not_understand_refuses():
    """Refusing beats guessing, because the guess would be a permission."""
    with pytest.raises(ContractError, match="does not understand"):
        authored_change.parse_scope("allowed_paths: everything")


def test_a_glob_is_not_the_unrestricted_marker():
    """`**` is what a contract arrives at by accident.

    A model emitting plausible YAML writes `**` readily; it does not write
    UNRESTRICTED by accident. The marker has to be the one that cannot be
    stumbled into.
    """
    scope = authored_change.parse_scope("allowed_paths:\n  - '**'\n")

    assert scope.unrestricted is False
    assert scope.paths == ("**",)


# --- The one way to say it --------------------------------------------------


def test_the_explicit_marker_authorises_the_repository():
    scope = authored_change.parse_scope("allowed_paths: UNRESTRICTED")

    assert scope.unrestricted is True


def test_the_marker_is_case_sensitive():
    """A near-miss is a mistake, and a mistake must not widen authority."""
    with pytest.raises(ContractError):
        authored_change.parse_scope("allowed_paths: unrestricted")


def test_the_marker_works_as_a_declared_value():
    assert authored_change.parse_scope("", declared="UNRESTRICTED").unrestricted
    assert authored_change.parse_scope("", declared=["UNRESTRICTED"]).unrestricted


# --- And the refusal reaches authoring ---------------------------------------


def test_authoring_cannot_be_reached_without_a_scope(tmp_path):
    """Keyword-only and no default: a caller must have decided."""
    with pytest.raises(TypeError):
        authored_change.apply_and_commit(
            str(tmp_path), branch="task/T-1",
            files=[("a.txt", "x\n")], message="m",
        )


def test_a_scope_object_is_required_not_a_bare_list(tmp_path):
    """A list used to mean paths and None used to mean everything.

    Requiring the type means the two cannot be confused by a caller that
    passes the wrong one, which is how the hole stayed open.
    """
    with pytest.raises(ContractError):
        authored_change.safe_relative_path(tmp_path, "a.txt", ["notes"])


def test_a_restricted_scope_still_refuses_paths_outside_it(tmp_path):
    scope = Scope.restricted_to(["notes"])

    with pytest.raises(authored_change.UnsafePath):
        authored_change.safe_relative_path(tmp_path, "build.sh", scope)
