"""The deployed build must be identifiable from its own bytes.

A version constant would not solve this problem. The failure mode is a
forgotten deploy, and a forgotten deploy leaves the old constant behind with
the old code -- it would report the version it was told to report, which is the
version somebody meant to ship. Deriving the identifier from the files that are
actually loaded is the only form that cannot be right while the code is wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from controller import build


@pytest.fixture
def tree(tmp_path):
    """A minimal deployed layout: hub.py beside a controller package."""
    (tmp_path / "controller").mkdir()
    (tmp_path / "hub.py").write_text("app = 1\n", encoding="utf-8")
    (tmp_path / "controller" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "controller" / "engine.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


# --- The identifier ---------------------------------------------------------


def test_the_same_tree_produces_the_same_id(tree):
    assert build.describe(tree)["build_id"] == build.describe(tree)["build_id"]


def test_one_changed_byte_changes_the_id(tree):
    before = build.describe(tree)["build_id"]
    (tree / "controller" / "engine.py").write_text("x = 2\n", encoding="utf-8")

    assert build.describe(tree)["build_id"] != before


def test_a_new_module_changes_the_id(tree):
    """Adding a file is a deploy too, and the commonest one to half-do."""
    before = build.describe(tree)["build_id"]
    (tree / "controller" / "extra.py").write_text("y = 1\n", encoding="utf-8")

    assert build.describe(tree)["build_id"] != before


def test_a_removed_module_changes_the_id(tree):
    before = build.describe(tree)["build_id"]
    (tree / "controller" / "engine.py").unlink()

    assert build.describe(tree)["build_id"] != before


def test_non_python_files_are_ignored(tree):
    """A stray log or database next to the code is not part of the build."""
    before = build.describe(tree)["build_id"]
    (tree / "controller" / "notes.txt").write_text("hello\n", encoding="utf-8")
    (tree / "controller.db").write_text("not code\n", encoding="utf-8")

    assert build.describe(tree)["build_id"] == before


# --- Repository and deployment agree ----------------------------------------


def test_a_checkout_and_its_deployment_produce_the_same_id(tmp_path):
    """The two layouts differ; the identifier must not.

    In the repository hub.py sits under hub/; in the container it sits at the
    root beside controller/. If those produced different ids the check would
    fail permanently for a reason that has nothing to do with deployment,
    which is the fastest way to get a safety check switched off.
    """
    repo = tmp_path / "repo"
    (repo / "hub").mkdir(parents=True)
    (repo / "controller").mkdir()
    (repo / "hub" / "hub.py").write_text("app = 1\n", encoding="utf-8")
    (repo / "controller" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "controller" / "engine.py").write_text("x = 1\n", encoding="utf-8")

    deployed = tmp_path / "app"
    (deployed / "controller").mkdir(parents=True)
    (deployed / "hub.py").write_text("app = 1\n", encoding="utf-8")
    (deployed / "controller" / "__init__.py").write_text("", encoding="utf-8")
    (deployed / "controller" / "engine.py").write_text("x = 1\n", encoding="utf-8")

    assert (
        build.from_repository(repo)["build_id"] == build.describe(deployed)["build_id"]
    )


def test_the_real_repository_describes_itself(tmp_path):
    """Guards against from_repository quietly finding nothing.

    An empty manifest hashes to a perfectly stable id, so a broken discovery
    would produce a check that passes against anything.
    """
    described = build.from_repository(Path(__file__).resolve().parent.parent)

    assert "hub.py" in described["files"]
    assert "controller/engine.py" in described["files"]
    assert len(described["files"]) >= 5


# --- The comparison names the file ------------------------------------------


def test_a_matching_pair_reports_no_differences(tree):
    described = build.describe(tree)
    result = build.compare(described, described)

    assert result["match"] is True
    assert result["differing"] == []


def test_an_edited_file_is_named(tree):
    expected = build.describe(tree)
    (tree / "controller" / "engine.py").write_text("x = 999\n", encoding="utf-8")
    result = build.compare(expected, build.describe(tree))

    assert result["match"] is False
    assert result["differing"] == ["controller/engine.py"]
    assert result["missing_from_deployment"] == []


def test_a_module_never_deployed_is_reported_separately(tree):
    """"Missing" and "edited" are different mistakes with different fixes."""
    (tree / "controller" / "newthing.py").write_text("z = 1\n", encoding="utf-8")
    expected = build.describe(tree)
    (tree / "controller" / "newthing.py").unlink()

    result = build.compare(expected, build.describe(tree))

    assert result["missing_from_deployment"] == ["controller/newthing.py"]
    assert result["differing"] == []


def test_a_file_on_the_hub_that_is_not_in_the_repository_is_reported(tree):
    """Usually a module deleted locally and left behind on the host."""
    expected = build.describe(tree)
    (tree / "controller" / "leftover.py").write_text("old = 1\n", encoding="utf-8")

    result = build.compare(expected, build.describe(tree))

    assert result["not_in_the_repository"] == ["controller/leftover.py"]


def test_a_deployment_with_no_build_id_at_all_does_not_match(tree):
    """An older controller predating this check reports nothing.

    It must fail rather than compare equal to a missing value, which is
    exactly the deployment that caused the incident.
    """
    result = build.compare(build.describe(tree), {"build_id": None, "files": {}})

    assert result["match"] is False
