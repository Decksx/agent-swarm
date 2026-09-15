"""Retrying and cancelling a task from chat (#33).

Chat could start a task and nothing after that: a rejected candidate needed
`controller_admin.py retry` and `issue ... author` over SSH, and a cancellation
needed `controller_admin.py cancel`. T-CMD-614eafb32c and T-CMD-058924af3d both
stopped for exactly that.

What must hold, by name: the controller still decides a retry and its budget;
a repeated retry issues nothing new; the next attempt goes on its own branch to
the previous author unless the mention names another; a cancellation is a
preview until a confirmation whose code matches the task as it is now and the
reason as previewed; and nothing is cancelled while work is live.
"""

from __future__ import annotations

import pytest

from controller import activations, db, engine, ingress, progression, states

BASE = "6edf2a1a6e9d4ca2633944fd1e2f6eaeb9e818e7"
PROJECTS = {"agenthub": "C:/git/agent-swarm"}
ROUTING = progression.Routing(verifier="gemini", integrator="claudecode", host="officepc")

COMMAND = (
    "@ChatGPT Show stage filters on the status page\n"
    "project: agenthub\n"
    f"base: {BASE}\n"
    "paths: tests/test_status.py, hub/hub.py\n"
    "\n"
    "Add the applied claim stages to the hub status page."
)
RATIONALE = "The test asserts the header text but never checks the escaping."


@pytest.fixture
def conn(tmp_path):
    connection = db.open_controller_db(tmp_path / "controller.db")
    activations.set_host_capacity(connection, host="officepc", max_concurrent=3)
    yield connection
    connection.close()


def send(conn, content, sender="admin", routing=ROUTING):
    return ingress.handle_message(conn, sender=sender, content=content,
                                  projects=PROJECTS, routing=routing)


def author_rows(conn, task_id):
    return conn.execute(
        "SELECT activation_id, agent, expected_branch, repo_location, status FROM activations "
        "WHERE task_id = ? AND stage = 'author' ORDER BY attempt_no", (task_id,)).fetchall()


def state(conn, task_id):
    return engine.get_task(conn, task_id)["state"]


@pytest.fixture
def task(conn):
    """A chat-started task whose first author attempt has just been claimed."""
    preview = send(conn, COMMAND)
    draft_id = next(t for t in preview.split() if t.startswith("CMD-"))
    send(conn, f"@swarm confirm {draft_id}")
    return ingress.task_id_for(draft_id)


def reject(conn, task_id, rationale=RATIONALE):
    """End the live author attempt with a rejection carrying a rationale."""
    live = [r for r in author_rows(conn, task_id) if r["status"] in ("ISSUED", "CLAIMED")][-1]

    if live["status"] == "ISSUED":
        activations.claim(conn, activation_id=live["activation_id"], agent=live["agent"])

    activations.submit_author_outcome(
        conn, activation_id=live["activation_id"], agent=live["agent"],
        outcome="failed", payload={"rationale": rationale},
    )
    assert state(conn, task_id) == "CHANGES_REQUESTED"


@pytest.fixture
def rejected(conn, task):
    reject(conn, task)
    return task


# --- Retry -----------------------------------------------------------------------


def test_a_retry_is_authorised_and_issued_to_the_previous_author(conn, rejected):
    reply = send(conn, f"@swarm retry {rejected}")
    rows = author_rows(conn, rejected)

    assert len(rows) == 2
    assert rows[1]["agent"] == "chatgpt"
    assert rows[1]["expected_branch"] == f"task/{rejected}-a2"
    assert rows[1]["repo_location"] == rows[0]["repo_location"] == "C:/git/agent-swarm"
    assert state(conn, rejected) == "AUTHOR_ASSIGNED"
    assert "retry_authorized" in [e["kind"] for e in engine.event_log(conn, rejected)]
    assert rows[1]["activation_id"] in reply
    assert f"task/{rejected}-a2" in reply
    assert "2 of 3 used" in reply


def test_the_reply_carries_the_rationale_the_author_will_be_given(conn, rejected):
    reply = send(conn, f"@swarm retry {rejected}")

    assert RATIONALE in reply
    assert engine.get_task(conn, rejected)["last_rejection"]["rationale"] == RATIONALE


def test_a_long_rationale_is_truncated_in_the_reply(conn, task):
    reject(conn, task, rationale="x" * 5000)

    reply = send(conn, f"@swarm retry {task}")

    assert "x" * 600 + " [truncated]" in reply
    assert "x" * 601 not in reply


def test_a_repeated_retry_issues_nothing_new(conn, rejected):
    send(conn, f"@swarm retry {rejected}")
    reply = send(conn, f"@swarm retry {rejected}")

    assert len(author_rows(conn, rejected)) == 2
    assert "nothing new was issued" in reply
    assert [e["kind"] for e in engine.event_log(conn, rejected)].count("retry_authorized") == 1


@pytest.mark.parametrize("mention,agent", [
    ("@ClaudeCode", "claudecode"), ("@ChatGPT", "chatgpt"),
    ("@swarm", "chatgpt"), ("@all", "chatgpt"),
])
def test_the_mention_chooses_the_author_or_keeps_the_previous_one(conn, rejected, mention, agent):
    send(conn, f"{mention} retry {rejected}")

    assert author_rows(conn, rejected)[1]["agent"] == agent


def test_the_previous_author_is_the_latest_attempts_not_the_first(conn, rejected):
    send(conn, f"@ClaudeCode retry {rejected}")
    reject(conn, rejected)

    send(conn, f"@swarm retry {rejected}")

    rows = author_rows(conn, rejected)
    assert [r["agent"] for r in rows] == ["chatgpt", "claudecode", "claudecode"]
    assert rows[2]["expected_branch"] == f"task/{rejected}-a3"


def test_a_spent_budget_escalates_and_issues_nothing(conn, rejected):
    for _ in range(2):
        send(conn, f"@swarm retry {rejected}")
        reject(conn, rejected)

    reply = send(conn, f"@swarm retry {rejected}")

    assert state(conn, rejected) == "NEEDS_HUMAN"
    assert len(author_rows(conn, rejected)) == 3
    assert "3 of 3" in reply and "Nothing was issued" in reply


def test_a_retry_refused_for_capacity_can_be_sent_again(conn, rejected):
    activations.set_host_capacity(conn, host="officepc", max_concurrent=0)

    reply = send(conn, f"@swarm retry {rejected}")

    assert reply.startswith("Not accepted:") and "at capacity" in reply
    assert state(conn, rejected) == "READY_AUTHOR"
    assert len(author_rows(conn, rejected)) == 1

    activations.set_host_capacity(conn, host="officepc", max_concurrent=3)
    send(conn, f"@swarm retry {rejected}")

    rows = author_rows(conn, rejected)
    assert len(rows) == 2 and rows[1]["expected_branch"] == f"task/{rejected}-a2"
    assert [e["kind"] for e in engine.event_log(conn, rejected)].count("retry_authorized") == 1


def test_a_retry_while_the_first_attempt_is_live_issues_nothing(conn, task):
    reply = send(conn, f"@swarm retry {task}")

    assert "nothing new was issued" in reply
    assert len(author_rows(conn, task)) == 1


def test_a_task_in_another_state_is_not_retried(conn, task):
    row = author_rows(conn, task)[0]
    activations.claim(conn, activation_id=row["activation_id"], agent=row["agent"])
    activations.submit_author_outcome(
        conn, activation_id=row["activation_id"], agent=row["agent"], outcome="candidate",
        payload={"candidate_sha": "a" * 40, "branch": f"task/{task}-a1"},
    )

    reply = send(conn, f"@swarm retry {task}")

    assert reply.startswith("Not accepted:") and "READY_REVIEW" in reply
    assert len(author_rows(conn, task)) == 1


def test_an_unknown_task_is_named(conn):
    assert "there is no task T-NOPE" in send(conn, "@swarm retry T-NOPE")


def test_no_host_means_no_retry(conn, rejected):
    reply = send(conn, f"@swarm retry {rejected}", routing=progression.Routing())

    assert "PROGRESSION_HOST" in reply
    assert state(conn, rejected) == "CHANGES_REQUESTED"


def test_the_next_branch_skips_any_an_activation_already_used(conn, rejected):
    conn.execute("UPDATE activations SET expected_branch = ? WHERE task_id = ?",
                 (f"task/{rejected}-a2", rejected))
    conn.commit()

    assert ingress._next_author_branch(conn, rejected) == f"task/{rejected}-a3"


@pytest.mark.parametrize("content", [
    "@swarm retry", "@swarm retry T-1 now", "@swarm retry CMD-0123456789",
])
def test_a_malformed_retry_is_refused(conn, content):
    assert send(conn, content).startswith("Not accepted: a retry is exactly")


# --- Cancel ------------------------------------------------------------------------


def confirm_line(reply):
    return next(line for line in reply.splitlines() if line.startswith("@swarm confirm-cancel"))


def test_a_cancel_is_only_a_preview(conn, rejected):
    before = engine.get_task(conn, rejected)
    reply = send(conn, f"@swarm cancel {rejected} superseded by T-OTHER")
    code = ingress.cancel_code(rejected, before["state_seq"], "superseded by T-OTHER")

    assert engine.get_task(conn, rejected)["state_seq"] == before["state_seq"]
    assert confirm_line(reply) == f"@swarm confirm-cancel {rejected} {code} superseded by T-OTHER"


def test_the_previewed_confirmation_cancels_with_the_reason(conn, rejected):
    line = confirm_line(send(conn, f"@swarm cancel {rejected} superseded by T-OTHER"))

    reply = send(conn, line)
    event = engine.event_log(conn, rejected)[-1]

    assert state(conn, rejected) == "CANCELLED"
    assert reply.startswith(f"Cancelled {rejected}")
    assert event["kind"] == "admin_cancelled"
    assert event["actor"] == "admin"
    assert "superseded by T-OTHER" in str(event.get("payload") or event.get("payload_json"))


def test_a_replayed_confirmation_changes_nothing(conn, rejected):
    line = confirm_line(send(conn, f"@swarm cancel {rejected} not needed"))
    send(conn, line)
    events = len(engine.event_log(conn, rejected))

    assert "already CANCELLED" in send(conn, line)
    assert len(engine.event_log(conn, rejected)) == events


def test_a_wrong_code_cancels_nothing_and_offers_the_right_line(conn, rejected):
    line = confirm_line(send(conn, f"@swarm cancel {rejected} not needed"))
    wrong = line.replace(line.split()[3], "00000000")

    reply = send(conn, wrong)

    assert reply.startswith("Not accepted:") and state(conn, rejected) == "CHANGES_REQUESTED"
    assert confirm_line(reply) == line


def test_a_different_reason_cancels_nothing(conn, rejected):
    line = confirm_line(send(conn, f"@swarm cancel {rejected} not needed"))

    reply = send(conn, line.replace("not needed", "something else"))

    assert reply.startswith("Not accepted:") and state(conn, rejected) == "CHANGES_REQUESTED"


def test_a_task_that_moved_since_the_preview_is_not_cancelled(conn, rejected):
    line = confirm_line(send(conn, f"@swarm cancel {rejected} not needed"))
    engine.authorize_retry(conn, task_id=rejected, actor="admin")

    reply = send(conn, line)

    assert reply.startswith("Not accepted:") and "does not match" in reply
    assert state(conn, rejected) == "READY_AUTHOR"


def test_nothing_is_cancelled_while_an_activation_is_live(conn, task):
    live = author_rows(conn, task)[0]["activation_id"]

    preview = send(conn, f"@swarm cancel {task} not needed")
    code = ingress.cancel_code(task, engine.get_task(conn, task)["state_seq"], "not needed")
    confirmed = send(conn, f"@swarm confirm-cancel {task} {code} not needed")

    for reply in (preview, confirmed):
        assert reply.startswith("Not accepted:") and live in reply and "live" in reply
    assert state(conn, task) == "AUTHOR_ASSIGNED"


def test_a_claimed_activation_also_blocks_cancellation(conn, task):
    row = author_rows(conn, task)[0]
    activations.claim(conn, activation_id=row["activation_id"], agent=row["agent"])

    assert "CLAIMED" in send(conn, f"@swarm cancel {task} not needed")


def test_a_terminal_task_is_not_cancelled(conn, rejected):
    for _ in range(2):
        send(conn, f"@swarm retry {rejected}")
        reject(conn, rejected)
    send(conn, f"@swarm retry {rejected}")
    engine.apply_transition(conn, task_id=rejected, kind="admin_failed", actor="admin",
                            authority=states.ADMIN)

    reply = send(conn, f"@swarm cancel {rejected} not needed")

    assert reply.startswith("Not accepted:") and "FAILED" in reply and "terminal" in reply


@pytest.mark.parametrize("content,named", [
    ("@swarm cancel {t}", "needs a reason"),
    ("@swarm cancel {t} " + "r" * 501, "longer than 500"),
    ("@ChatGPT cancel {t} no", "@swarm cancel"),
    ("@swarm cancel", "needs a task id"),
    ("@swarm confirm-cancel {t}", "exactly as the preview gave it"),
    ("@swarm confirm-cancel {t} ZZZZZZZZ why", "exactly as the preview gave it"),
    ("@swarm confirm-cancel {t} 0123abcd", "needs a reason"),
])
def test_a_malformed_cancel_is_refused(conn, rejected, content, named):
    reply = send(conn, content.format(t=rejected))

    assert reply.startswith("Not accepted:") and named in reply
    assert state(conn, rejected) == "CHANGES_REQUESTED"


# --- Containment ---------------------------------------------------------------------


@pytest.mark.parametrize("sender", ["chatgpt", "claudecode", "gemini", "controller"])
def test_only_an_admin_can_retry_or_cancel(conn, rejected, sender):
    assert send(conn, f"@swarm retry {rejected}", sender=sender) is None
    assert send(conn, f"@swarm cancel {rejected} x", sender=sender) is None
    assert len(author_rows(conn, rejected)) == 1


def test_a_mention_that_is_not_leading_is_ordinary_chat(conn, rejected):
    assert send(conn, f"please @swarm retry {rejected}") is None
    assert send(conn, f" @swarm retry {rejected}") is None


def test_a_lifecycle_command_is_one_line(conn, rejected):
    reply = send(conn, f"@swarm retry {rejected}\nand hurry")

    assert "one-line command" in reply
    assert len(author_rows(conn, rejected)) == 1


def test_a_multi_line_task_titled_retry_still_drafts(conn):
    reply = send(conn, COMMAND.replace("Show stage filters", "retry flaky status test"))

    assert reply.startswith("Draft CMD-")
