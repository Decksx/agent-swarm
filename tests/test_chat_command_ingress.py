"""Chat-command ingress: operator commands become drafts, and confirmed drafts become tasks.

What must hold, by name: only an authenticated admin's exact leading mention is
a command; a command is previewed and nothing runs until a separate
confirmation; the same command or confirmation delivered twice produces one
draft, one task and one author activation; every refusal says why and stores
nothing; and @Gemini cannot start work.
"""

from __future__ import annotations

import time

import pytest

from controller import activations, db, drafts, engine, ingress, progression, schema, states

BASE = "6edf2a1a6e9d4ca2633944fd1e2f6eaeb9e818e7"
PROJECTS = {"agenthub": "C:/git/agent-swarm"}
ROUTING = progression.Routing(verifier="gemini", integrator="claudecode", host="officepc")

COMMAND = (
    "@ChatGPT Show stage filters on the status page\n"
    "project: agenthub\n"
    f"base: {BASE}\n"
    "paths: tests/test_status.py, hub/hub.py\n"
    "context: controller/api.py\n"
    "\n"
    "Add the applied claim stages to the hub status page.\n"
    "Keep the unfiltered response unchanged."
)


@pytest.fixture
def conn(tmp_path):
    connection = db.open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, host="officepc", max_concurrent=3)
    yield connection
    connection.close()


def send(conn, content, sender="admin", routing=ROUTING, projects=PROJECTS):
    return ingress.handle_message(conn, sender=sender, content=content,
                                  projects=projects, routing=routing)


def count(conn, table, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


def draft_id_in(reply):
    return next(token for token in reply.split() if token.startswith("CMD-"))


# --- Schema 6 ----------------------------------------------------------------


def test_a_fresh_database_has_task_drafts_at_schema_six(conn):
    assert schema.SCHEMA_VERSION == 6
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert count(conn, "sqlite_master", "type='table' AND name='task_drafts'") == 1


def test_a_schema_five_database_migrates_to_six_and_gains_task_drafts(tmp_path):
    path = tmp_path / "old.db"
    old = db.connect(str(path))
    db.initialize(old)
    old.execute("DROP TABLE task_drafts")
    old.execute("PRAGMA user_version = 5")
    old.commit()
    old.close()

    migrated = db.open_controller_db(path)

    assert migrated.execute("PRAGMA user_version").fetchone()[0] == 6
    assert count(migrated, "sqlite_master", "type='table' AND name='task_drafts'") == 1


def test_the_drafts_migration_step_can_run_twice_without_losing_rows(conn):
    drafts.ensure_draft(conn, {"k": "v"}, draft_id="CMD-0000000001", created_by="admin")

    db._create_task_drafts(conn)
    db._create_task_drafts(conn)

    assert count(conn, "task_drafts") == 1


# --- drafts.ensure_draft ---------------------------------------------------------


def test_ensure_draft_stores_once_for_the_same_content(conn):
    first, created_first = drafts.ensure_draft(conn, {"a": 1}, draft_id="CMD-00000000aa", created_by="admin")
    second, created_second = drafts.ensure_draft(conn, {"a": 1}, draft_id="CMD-00000000aa", created_by="admin")

    assert (created_first, created_second) == (True, False)
    assert first == second
    assert count(conn, "task_drafts") == 1


def test_ensure_draft_refuses_different_content_under_an_existing_id(conn):
    drafts.ensure_draft(conn, {"a": 1}, draft_id="CMD-00000000bb", created_by="admin")

    with pytest.raises(drafts.DraftHashMismatch):
        drafts.ensure_draft(conn, {"a": 2}, draft_id="CMD-00000000bb", created_by="admin")

    assert drafts.get_draft(conn, "CMD-00000000bb")["content"] == {"a": 1}


# --- What counts as a command ------------------------------------------------------


@pytest.mark.parametrize("sender", ["claudecode", "chatgpt", "gemini", "narrator", "controller", ""])
def test_only_an_admin_sender_is_parsed(conn, sender):
    assert send(conn, COMMAND, sender=sender) is None
    assert count(conn, "task_drafts") == 0


@pytest.mark.parametrize("content", [
    " " + COMMAND,
    "please " + COMMAND,
    COMMAND.replace("@ChatGPT", "@ChatGPTx", 1),
    COMMAND.replace("@ChatGPT", "@bob", 1),
    "hello everyone",
    "",
])
def test_anything_but_an_exact_leading_mention_is_ordinary_chat(conn, content):
    assert send(conn, content) is None
    assert count(conn, "task_drafts") == 0


# --- Preview -------------------------------------------------------------------------


def test_a_command_is_previewed_and_nothing_runs(conn):
    reply = send(conn, COMMAND)
    draft_id = draft_id_in(reply)

    assert reply.startswith(f"Draft {draft_id}")
    for expected in (
        "project:     agenthub (C:/git/agent-swarm)",
        f"base:        {BASE}",
        "proof mode:  branch_only",
        "paths:       hub/hub.py, tests/test_status.py",
        "context:     controller/api.py",
        "routing:     author chatgpt -> review gemini -> integrate claudecode",
        "title:       Show stage filters on the status page",
        "  Keep the unfiltered response unchanged.",
        f"@swarm confirm {draft_id}",
    ):
        assert expected in reply, expected
    assert count(conn, "task_drafts") == 1
    assert count(conn, "tasks") == 0 and count(conn, "activations") == 0


@pytest.mark.parametrize("mention, author", [
    ("@ChatGPT", "chatgpt"), ("@ClaudeCode", "claudecode"), ("@swarm", "chatgpt"),
    ("@all", "chatgpt"), ("@CLAUDECODE", "claudecode"),
])
def test_the_mention_selects_the_author(conn, mention, author):
    reply = send(conn, COMMAND.replace("@ChatGPT", mention, 1))

    assert f"routing:     author {author} -> review gemini -> integrate claudecode" in reply
    assert drafts.get_draft(conn, draft_id_in(reply))["content"]["author"] == author


def test_the_same_command_delivered_twice_is_one_draft(conn):
    first = send(conn, COMMAND)
    second = send(conn, COMMAND)
    reordered = send(conn, COMMAND.replace("tests/test_status.py, hub/hub.py", "hub/hub.py, tests/test_status.py")
                     .replace("\n", "\r\n"))

    assert draft_id_in(first) == draft_id_in(second) == draft_id_in(reordered)
    assert "(already drafted; nothing new stored)" in second
    assert count(conn, "task_drafts") == 1


def test_different_content_is_a_different_draft(conn):
    first = send(conn, COMMAND)
    second = send(conn, COMMAND + " And document it.")

    assert draft_id_in(first) != draft_id_in(second)
    assert count(conn, "task_drafts") == 2


@pytest.mark.parametrize("content, reason", [
    ("@ChatGPT\nproject: agenthub", "needs a title"),
    (COMMAND.replace("project: agenthub\n", ""), "`project:` is required"),
    (COMMAND.replace("project: agenthub", "project: comicautomation"), "unknown project"),
    (COMMAND.replace(f"base: {BASE}", "base: main"), "full 40-character commit SHA"),
    (COMMAND.replace(f"base: {BASE}", f"base: {BASE[:12]}"), "full 40-character commit SHA"),
    (COMMAND.replace("paths: tests/test_status.py, hub/hub.py\n", ""), "`paths:` is required"),
    (COMMAND.replace("hub/hub.py", "../outside.py"), "not a relative repository path"),
    (COMMAND.replace("hub/hub.py", "/etc/passwd"), "not a relative repository path"),
    (COMMAND.replace("hub/hub.py", "C:\\git\\x.py"), "not a relative repository path"),
    (COMMAND.replace("context: controller/api.py", "context: hub/hub.py"), "both writable"),
    (COMMAND.replace("context: controller/api.py", "proof: vibes"), "`proof:` must be one of"),
    (COMMAND.replace("context: controller/api.py", "owner: me"), "is not one of"),
    (COMMAND.replace("context: controller/api.py", "project: agenthub"), "given twice"),
    (COMMAND.split("\n\n")[0], "objective is missing"),
])
def test_a_malformed_command_is_refused_with_its_reason_and_stores_nothing(conn, content, reason):
    reply = send(conn, content)

    assert reply.startswith("Not accepted:") and reason in reply, reply
    assert count(conn, "task_drafts") == 0


# --- Confirmation ----------------------------------------------------------------------


def confirmed(conn):
    draft_id = draft_id_in(send(conn, COMMAND))
    return draft_id, send(conn, f"@swarm confirm {draft_id}")


def test_confirming_creates_queues_and_starts_one_task(conn):
    draft_id, reply = confirmed(conn)
    task_id = f"T-{draft_id}"

    task = engine.get_task(conn, task_id)
    assert task["state"] == "AUTHOR_ASSIGNED"
    assert task["base_sha"] == BASE and task["proof_mode"] == "branch_only"
    assert "  - hub/hub.py\n  - tests/test_status.py\n" in task["contract_yaml"]
    assert "context_paths:\n  - controller/api.py\n" in task["contract_yaml"]

    row = conn.execute("SELECT activation_id, agent, host, expected_branch, repo_location "
                       "FROM activations WHERE task_id = ?", (task_id,)).fetchall()
    assert len(row) == 1
    activation_id, agent, host, branch, location = row[0]
    assert (agent, host, branch, location) == ("chatgpt", "officepc", f"task/{task_id}-a1", "C:/git/agent-swarm")

    assert drafts.get_draft(conn, draft_id)["status"] == drafts.CONFIRMED
    for expected in (f"Confirmed {draft_id} as {task_id}", f"task:        {task_id} (AUTHOR_ASSIGNED)",
                     f"author activation: {activation_id}", f"base:        {BASE}",
                     "paths:       hub/hub.py, tests/test_status.py", "proof mode:  branch_only",
                     "routing:     author chatgpt -> review gemini -> integrate claudecode"):
        assert expected in reply, expected


def test_a_repeated_confirmation_creates_nothing_more(conn):
    draft_id, _ = confirmed(conn)

    again = send(conn, f"@all confirm {draft_id}")

    assert again.startswith(f"{draft_id} was already confirmed as T-{draft_id}")
    assert count(conn, "tasks") == 1 and count(conn, "activations") == 1


def test_a_redelivered_command_after_confirmation_points_at_the_task(conn):
    draft_id, _ = confirmed(conn)

    reply = send(conn, COMMAND)

    assert f"Already confirmed as T-{draft_id}." in reply
    assert "@swarm confirm" not in reply
    assert count(conn, "tasks") == 1 and count(conn, "task_drafts") == 1


def test_an_interrupted_confirmation_is_finished_by_sending_it_again(conn):
    draft_id = draft_id_in(send(conn, COMMAND))
    task_id = f"T-{draft_id}"
    content = drafts.get_draft(conn, draft_id)["content"]
    engine.create_task(conn, task_id=task_id, title=content["title"], objective=content["objective"],
                       contract_yaml=ingress.contract_yaml_for(task_id, content), base_sha=BASE,
                       created_by="admin", proof_mode="branch_only")
    engine.apply_transition(conn, task_id=task_id, kind="contract_validated", actor="admin", authority=states.CONTROLLER)
    engine.apply_transition(conn, task_id=task_id, kind="queued", actor="admin", authority=states.CONTROLLER)

    send(conn, f"@swarm confirm {draft_id}")
    send(conn, f"@swarm confirm {draft_id}")

    assert count(conn, "activations", "task_id = ?", (task_id,)) == 1
    assert drafts.get_draft(conn, draft_id)["status"] == drafts.CONFIRMED


def test_a_full_host_leaves_the_draft_pending_and_a_later_confirmation_completes_it(conn):
    activations.set_host_capacity(conn, host="officepc", max_concurrent=0)
    draft_id = draft_id_in(send(conn, COMMAND))

    refused = send(conn, f"@swarm confirm {draft_id}")

    assert refused.startswith("Not accepted:") and "at capacity" in refused
    assert drafts.get_draft(conn, draft_id)["status"] == drafts.PENDING
    assert count(conn, "activations") == 0

    activations.set_host_capacity(conn, host="officepc", max_concurrent=3)
    send(conn, f"@swarm confirm {draft_id}")

    assert count(conn, "tasks") == 1 and count(conn, "activations") == 1
    assert drafts.get_draft(conn, draft_id)["status"] == drafts.CONFIRMED


@pytest.mark.parametrize("content, reason", [
    ("@swarm confirm CMD-0123456789", "there is no draft"),
    ("@ChatGPT confirm CMD-0123456789", "confirm with `@swarm confirm"),
    ("@swarm confirm", "exactly `@swarm confirm"),
    ("@swarm confirm CMD-XYZ", "exactly `@swarm confirm"),
    ("@swarm confirm CMD-0123456789 now", "exactly `@swarm confirm"),
])
def test_a_bad_confirmation_is_refused_and_creates_nothing(conn, content, reason):
    reply = send(conn, content)

    assert reply.startswith("Not accepted:") and reason in reply, reply
    assert count(conn, "tasks") == 0


def test_without_a_host_nothing_is_created(conn):
    draft_id = draft_id_in(send(conn, COMMAND))

    reply = send(conn, f"@swarm confirm {draft_id}", routing=progression.Routing(verifier="gemini", integrator="claudecode"))

    assert "PROGRESSION_HOST" in reply
    assert count(conn, "tasks") == 0


# --- @Gemini ---------------------------------------------------------------------------


@pytest.mark.parametrize("content", ["@Gemini review the status page", COMMAND.replace("@ChatGPT", "@Gemini", 1),
                                     "@Gemini status", "@Gemini status not-a-task!"])
def test_gemini_cannot_start_new_work(conn, content):
    reply = send(conn, content)

    assert reply.startswith("Not accepted:") and "cannot start new work" in reply
    assert count(conn, "task_drafts") == 0 and count(conn, "tasks") == 0


def test_gemini_status_reports_a_task_without_changing_it(conn):
    draft_id, _ = confirmed(conn)
    before = engine.get_task(conn, f"T-{draft_id}")

    reply = send(conn, f"@Gemini status T-{draft_id}")

    assert reply.startswith(f"T-{draft_id} is AUTHOR_ASSIGNED")
    assert engine.get_task(conn, f"T-{draft_id}")["state_seq"] == before["state_seq"]
    assert send(conn, "@Gemini status T-NOPE").startswith("Not accepted: there is no task")


# --- Configuration ----------------------------------------------------------------------


def test_projects_are_parsed_from_name_equals_location():
    assert ingress.parse_projects("agenthub=C:/git/agent-swarm, comics = D:/comics ") == {
        "agenthub": "C:/git/agent-swarm", "comics": "D:/comics"}
    assert ingress.parse_projects("") == {}


@pytest.mark.parametrize("value", ["agenthub", "=C:/x", "agenthub=", "Bad Name=C:/x"])
def test_a_malformed_project_entry_is_an_error_not_a_skip(value):
    with pytest.raises(ValueError):
        ingress.parse_projects(value)


# --- A command typed on one line ------------------------------------------------------


def test_fields_typed_on_the_title_line_get_a_refusal_that_names_the_fix(conn):
    one_line = COMMAND.split("\n\n")[0].replace("\n", " ") + "  " + COMMAND.split("\n\n")[1]

    reply = send(conn, one_line)

    assert reply.startswith("Not accepted:")
    assert "each on its own line below the title" in reply and "Shift+Enter" in reply
    assert count(conn, "task_drafts") == 0


def test_a_title_that_mentions_a_field_name_is_fine_when_the_fields_follow(conn):
    reply = send(conn, COMMAND.replace("Show stage filters on the status page", "Fix base: handling in the status page", 1))

    assert reply.startswith("Draft CMD-")
    assert "title:       Fix base: handling in the status page" in reply
