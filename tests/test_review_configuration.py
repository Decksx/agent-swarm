"""The reviewer is told what configuration a change starts reading (#34).

T-CMD-614eafb32c asked for the controller's build id in the hub header. The
candidate read `os.environ.get("CONTROLLER_BUILD_ID", "unknown")` -- a name
nothing in the repository sets, so the live page would have shown "unknown"
forever -- and its test passed because the test set the variable. Gemini's
rejection named the broken test and an unrelated deletion, not the thing that
would have shipped.

So the packet says, for every configuration name the change begins reading,
where else that name appears at the candidate commit; and the verdict rules
say what the reviewer is judging: the path that runs in production.
"""

from __future__ import annotations

import subprocess

import pytest

import review_packet

TASK = {"task_id": "T-1", "title": "show the build id",
        "objective": "Show the controller build id in the header."}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@test")
    git(root, "config", "user.name", "t")
    (root / "hub.py").write_text("import os\n\n\ndef header():\n    return 'Agent Hub'\n",
                                 encoding="utf-8", newline="\n")
    (root / "run.sh").write_text("export HUB_SECRET=x\n", encoding="utf-8", newline="\n")
    (root / "tests" / "test_hub.py").write_text("def test_header():\n    assert True\n",
                                                encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def candidate(repo, **files):
    base = git(repo, "rev-parse", "HEAD")

    for name, text in files.items():
        path = repo / name.replace("__", "/").replace("_py", ".py").replace("_sh", ".sh")
        path.write_text(text, encoding="utf-8", newline="\n")

    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "candidate")
    return base, git(repo, "rev-parse", "HEAD")


def reads(repo, base, head):
    return review_packet.configuration_reads(str(repo), base, head)


HEADER_READING = (
    "import os\n\n\ndef header():\n"
    "    return 'Agent Hub ' + os.environ.get('CONTROLLER_BUILD_ID', 'unknown')\n"
)


# --- What a change starts reading ------------------------------------------------


def test_a_variable_nothing_else_provides_is_named_as_such(repo):
    base, head = candidate(repo, hub_py=HEADER_READING)

    assert reads(repo, base, head) == [{
        "name": "CONTROLLER_BUILD_ID", "default": "'unknown'",
        "elsewhere": [], "elsewhere_count": 0, "only_tests": False,
    }]


def test_a_variable_the_deployment_sets_is_reported_with_where(repo):
    base, head = candidate(
        repo, hub_py="import os\n\n\ndef header():\n    return os.environ['HUB_SECRET']\n")
    [read] = reads(repo, base, head)

    assert read["name"] == "HUB_SECRET"
    assert read["elsewhere"] == ["run.sh"] and read["only_tests"] is False


def test_a_variable_only_tests_provide_is_marked(repo):
    """The T-CMD-614eafb32c shape: the test supplies the value the code reads."""
    base, head = candidate(
        repo, hub_py=HEADER_READING,
        tests__test_hub_py="import os\n\n\ndef test_header():\n"
                           "    os.environ['CONTROLLER_BUILD_ID'] = 'abc'\n",
    )

    # The test file is itself changed here, so the name has to be found in a file
    # the diff did not touch to count as provided elsewhere.
    assert reads(repo, base, head)[0]["elsewhere"] == []

    base2, head2 = candidate(repo, hub_py=HEADER_READING.replace("Agent Hub", "Hub"))
    [read] = reads(repo, base2, head2)

    assert read["elsewhere"] == ["tests/test_hub.py"] and read["only_tests"] is True


@pytest.mark.parametrize("line,name,default", [
    ("    x = os.environ.get('A_NAME')", "A_NAME", ""),
    ('    x = os.environ.get("A_NAME", "fallback")', "A_NAME", '"fallback"'),
    ("    x = os.getenv('A_NAME', DEFAULT)", "A_NAME", "DEFAULT"),
    ("    x = os.environ['A_NAME']", "A_NAME", ""),
    ("    const x = process.env.A_NAME;", "A_NAME", ""),
])
def test_each_way_of_reading_configuration_is_found(repo, line, name, default):
    base, head = candidate(repo, hub_py=f"import os\n\n\ndef header():\n{line}\n")
    [read] = reads(repo, base, head)

    assert (read["name"], read["default"]) == (name, default)


def test_a_read_the_change_only_moves_is_not_reported_twice(repo):
    base, head = candidate(
        repo, hub_py=HEADER_READING + "\n\ndef footer():\n"
        "    return os.environ.get('CONTROLLER_BUILD_ID', 'unknown')\n")

    assert [read["name"] for read in reads(repo, base, head)] == ["CONTROLLER_BUILD_ID"]


def test_a_removed_read_is_not_reported(repo):
    base, head = candidate(repo, hub_py=HEADER_READING)
    later, head2 = candidate(repo, hub_py="import os\n\n\ndef header():\n    return 'Agent Hub'\n")

    assert reads(repo, later, head2) == []


def test_a_change_that_reads_no_configuration_reports_none(repo):
    base, head = candidate(repo, hub_py="def header():\n    return 'Hub'\n")

    assert reads(repo, base, head) == []


def test_the_number_of_names_is_bounded(repo, monkeypatch):
    monkeypatch.setattr(review_packet, "CONFIG_NAME_BUDGET", 2)
    body = "".join(f"    x{n} = os.environ.get('NAME_{n}')\n" for n in range(6))
    base, head = candidate(repo, hub_py=f"import os\n\n\ndef header():\n{body}")

    assert len(reads(repo, base, head)) == 2


# --- What the reviewer is shown ---------------------------------------------------


def prompt_for(repo, base, head):
    return review_packet.render(
        review_packet.build(str(repo), task=TASK, base=base, candidate=head))


def test_the_packet_and_the_prompt_carry_the_reads(repo):
    base, head = candidate(repo, hub_py=HEADER_READING)
    packet = review_packet.build(str(repo), task=TASK, base=base, candidate=head)
    prompt = review_packet.render(packet)

    assert packet["configuration_reads"][0]["name"] == "CONTROLLER_BUILD_ID"
    assert "CONFIGURATION THIS CHANGE STARTS READING" in prompt
    assert "CONTROLLER_BUILD_ID (default 'unknown') -- named nowhere else" in prompt
    assert "runs on its default" in prompt
    assert prompt.index("FULL DIFF") < prompt.index("CONFIGURATION THIS CHANGE")
    assert prompt.index("CONFIGURATION THIS CHANGE") < prompt.index("TEST RESULTS")


def test_a_name_only_tests_provide_says_so_in_the_prompt(repo):
    candidate(repo, hub_py=HEADER_READING,
              tests__test_hub_py="import os\n\n\ndef test_header():\n"
                                 "    os.environ['CONTROLLER_BUILD_ID'] = 'abc'\n")
    base, head = candidate(repo, hub_py=HEADER_READING.replace("Agent Hub", "Hub"))

    assert "only in tests: tests/test_hub.py" in prompt_for(repo, base, head)


def test_a_change_reading_nothing_gets_no_section(repo):
    base, head = candidate(repo, hub_py="def header():\n    return 'Hub'\n")

    assert "CONFIGURATION THIS CHANGE" not in prompt_for(repo, base, head)


def test_the_verdict_rules_name_the_production_path(repo):
    base, head = candidate(repo, hub_py="def header():\n    return 'Hub'\n")
    prompt = prompt_for(repo, base, head)

    assert "through the code path that runs in production, not only under test" in prompt
    assert "proves nothing about production" in prompt
    assert "standing in for the real source is CHANGES_REQUESTED" in prompt
