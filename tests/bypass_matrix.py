"""Fault injection: prove each containment guard is load-bearing.

A passing suite with the guards present proves nothing about the guards. It is
equally consistent with the guards being unreachable defensive code that fails
nothing when removed. The only way to tell the difference is to take each one
out and confirm that specific, named tests fail.

Each entry below is one guard, bypassed by an exact source substitution, with
the tests that are expected to catch it. The script applies one bypass, runs
the suite, restores the file, and reports whether the failures matched. Files
are restored in a `finally`, so an interrupted run does not leave a sabotaged
worker on disk -- and the restore is verified by hash afterwards.

Run it directly:

    python tests/bypass_matrix.py
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Bypass:
    def __init__(self, name, filename, old, new, expect_failures, rationale):
        self.name = name
        self.path = REPO / filename
        self.old = old
        self.new = new
        self.expect_failures = set(expect_failures)
        self.rationale = rationale


BYPASSES = [
    Bypass(
        "pause_ignored",
        "swarm_control.py",
        '''    source = os.environ if env is None else env

    flag = source.get("SWARM_PAUSED", "").strip().lower()''',
        '''    return None  # BYPASS
    source = os.environ if env is None else env

    flag = source.get("SWARM_PAUSED", "").strip().lower()''',
        [
            "test_pause_sentinel_prevents_execution",
            "test_pause_leaves_the_queued_work_intact",
            "test_env_var_pause_is_independent_of_the_sentinel",
            "test_truthy_pause_values_engage",
            "test_unreadable_pause_flag_fails_closed",
            "test_control_status_reports_the_containment_facts",
        ],
        "The global pause is what an operator reaches for in an incident.",
    ),
    Bypass(
        "claim_does_not_consume",
        "swarm_control.py",
        """        claimed = CONSUMED_DIR / path.name
        try:
            path.rename(claimed)
        except OSError:""",
        """        claimed = CONSUMED_DIR / path.name
        try:
            claimed.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:""",
        # The first draft of this list also named the two agent-routing tests
        # and the pause test. It was wrong, and the matrix caught it: routing is
        # enforced by the agent match (its own row below), and under a pause
        # nothing is claimed at all, so neither depends on the rename. The
        # third entry was not predicted and is the sharpest of the three -- with
        # copy-instead-of-rename the activation is re-claimed on every poll, so
        # a single task runs once per poll forever.
        [
            "test_duplicate_polls_cannot_claim_one_activation_twice",
            "test_activation_is_consumed_exactly_once_across_many_polls",
            "test_admin_issued_activation_runs",
        ],
        "Without the atomic rename, one activation runs on every poll forever.",
    ),
    Bypass(
        "claim_ignores_agent",
        "swarm_control.py",
        """        if normalize_handle(record.get("agent")) != bound_identity:
            continue""",
        """        if False:  # BYPASS
            continue""",
        [
            "test_a_worker_cannot_claim_another_workers_activation",
            "test_claiming_ignores_a_spoofed_actor_field_in_the_activation",
        ],
        "Routing must follow the claimant's bound identity, not a record field.",
    ),
    Bypass(
        "credentials_unvalidated",
        "swarm_control.py",
        """    if value.lower() in _PLACEHOLDER_CREDENTIALS:""",
        """    if False:  # BYPASS""",
        [
            "test_placeholder_credentials_are_rejected",
            "test_credential_refusals_never_quote_the_value",
        ],
        "A blank key must be refused at startup, not at the provider.",
    ),
    Bypass(
        "redaction_disabled",
        "swarm_control.py",
        """    return _SECRET_RE.sub("[REDACTED-CREDENTIAL]", text)""",
        """    return text  # BYPASS""",
        [
            "test_redaction_scrubs_credential_shapes",
            "test_redaction_is_applied_to_outbound_messages",
        ],
        "Task output can contain the environment; it is scrubbed before it ships.",
    ),
    Bypass(
        "identity_accepts_empty",
        "swarm_control.py",
        """    if not handle:
        raise IdentityViolation("worker identity is empty; refusing to start")""",
        """    if False:  # BYPASS
        raise IdentityViolation("worker identity is empty; refusing to start")""",
        ["test_an_empty_identity_is_refused"],
        "A worker with no identity must not start.",
    ),
    Bypass(
        "chat_activation_reintroduced",
        "claude_worker.py",
        """        if messages:
            swarm_control.record_narration(messages)""",
        """        if messages:
            swarm_control.record_narration(messages)

        for _m in messages:  # BYPASS: the pre-Phase-0 trigger, re-added
            _t = str(_m.get("target", "")).strip().lstrip("@").lower()
            if _t in ("claudecode", "claude"):
                execute_activation(
                    requests,
                    claude_binary,
                    {
                        "activation_id": _m.get("id"),
                        "task": _m.get("content"),
                        "issued_by": _m.get("sender"),
                    },
                )""",
        # The peer-target test is deliberately NOT expected here. Re-adding the
        # trigger still leaves REPLY_TARGET at "@Admin", so no peer-addressed
        # message is produced -- that test guards reply addressing, which is a
        # separate property with its own row below. Listing it here would have
        # credited this bypass with a failure it does not cause.
        [
            "test_agent_chat_and_mentions_never_invoke_a_model",
            "test_repeated_chat_delivery_creates_no_model_calls",
        ],
        "This is the exact defect Phase 0 exists to remove.",
    ),
    Bypass(
        "replies_addressed_to_a_peer",
        "claude_worker.py",
        '''REPLY_TARGET = "@Admin"''',
        '''REPLY_TARGET = "@Gemini"  # BYPASS: the pre-Phase-0 value''',
        ["test_no_hub_message_is_ever_addressed_to_a_peer_worker"],
        "Addressing a peer is the return leg of the self-driving loop.",
    ),
    Bypass(
        # A real regression from this branch, kept as a permanent row. Removing
        # the chat-era constants also removed SYSTEM_PROMPT, which
        # generate_reply still referenced: every generation raised NameError,
        # was swallowed by the broad `except Exception` that keeps one bad call
        # from killing the daemon, and returned None. The worker started
        # cleanly and silently never answered, and the whole pytest suite
        # stayed green because the loop tests stub generate_reply.
        "system_prompt_dropped",
        "gemini_worker.py",
        """                system_instruction=SYSTEM_PROMPT,""",
        """                system_instruction=None,  # BYPASS""",
        ["test_generation_uses_the_system_prompt_and_model"],
        "A silently-dropped constant broke every reply and no test noticed.",
    ),
    Bypass(
        "startup_invariant_removed",
        "claude_worker.py",
        """    if swarm_control.CHAT_IS_AUTHORITATIVE:
        log.error(
            "refusing to start: swarm_control.CHAT_IS_AUTHORITATIVE is True, "
            "but this worker has no audited path for chat-driven activation"
        )
        return 2""",
        """    if False:  # BYPASS
        return 2""",
        ["test_workers_refuse_to_start_if_chat_becomes_authoritative"],
        "Re-enabling chat authority must be a visible act, not a flag flip.",
    ),
    # --- Controller storage (Phase 1) --------------------------------------
    Bypass(
        "foreign_keys_off",
        "controller/db.py",
        '''conn.execute("PRAGMA foreign_keys = ON")''',
        '''pass  # BYPASS''',
        ["test_foreign_keys_are_enforced"],
        "SQLite ignores REFERENCES entirely unless this pragma is set.",
    ),
    Bypass(
        "deferred_transaction",
        "controller/db.py",
        '''conn.execute("BEGIN IMMEDIATE")''',
        '''conn.execute("BEGIN")''',
        ["test_a_transaction_is_immediate_not_deferred"],
        "Deferred lets two writers each decide from state the other has moved.",
    ),
    Bypass(
        "nesting_allowed",
        "controller/db.py",
        """    if conn.in_transaction:""",
        """    if False:  # BYPASS""",
        ["test_nesting_a_transaction_is_refused"],
        "A joined transaction turns the inner block's rollback into a no-op.",
    ),
    Bypass(
        "schema_version_check_removed",
        "controller/db.py",
        """    if version != SCHEMA_VERSION:""",
        """    if False:  # BYPASS""",
        ["test_a_wrong_schema_version_refuses_to_open"],
        "Half-matching SQL applied to real task state corrupts it quietly.",
    ),
    Bypass(
        # Regression: this broke schema creation on the very first run, because
        # a comment in schema.py contains a semicolon.
        "splitter_keeps_comments",
        "controller/db.py",
        """        line.split("--", 1)[0] for line in sql.splitlines()""",
        """        line for line in sql.splitlines()  # BYPASS""",
        # Removing it does not merely fail an assertion -- the schema stops
        # being creatable, so every test needing a database errors out. The
        # named two are the ones that fail on their own assertions.
        [
            "test_the_splitter_survives_a_semicolon_inside_a_comment",
            "test_the_splitter_returns_every_schema_statement",
        ],
        "A comment containing ';' splits into something executed as SQL.",
    ),
    # --- State machine (Phase 1) -------------------------------------------
    Bypass(
        "undefined_transition_allowed",
        "controller/states.py",
        """        raise UndefinedTransition(
            f"{kind!r} is not a defined transition from {from_state!r}"
        ) from None""",
        """        return Transition(from_state, frozenset(ROLES))  # BYPASS""",
        [
            "test_every_undefined_pair_is_rejected",
            "test_a_rejected_transition_appends_no_event",
        ],
        "Invariant 14: an undefined (state, event) pair must be refused.",
    ),
    Bypass(
        "authority_ignored",
        "controller/states.py",
        """    if authority not in transition.authorities:""",
        """    if False:  # BYPASS""",
        [
            "test_authority_is_enforced_separately_from_the_transition",
            "test_a_worker_cannot_declare_its_own_work_accepted",
        ],
        "A verifier that can emit review_requirements_satisfied accepts its own work.",
    ),
    Bypass(
        "stale_seq_ignored",
        "controller/engine.py",
        """        if expected_state_seq is not None and expected_state_seq != task["state_seq"]:""",
        """        if False:  # BYPASS""",
        ["test_a_stale_state_seq_is_refused"],
        "Applies a result computed against a state the task has since left.",
    ),
    Bypass(
        "conflicting_replay_merged",
        "controller/engine.py",
        """            if not same:""",
        """            if False:  # BYPASS""",
        ["test_a_conflicting_replay_is_refused"],
        "A different request reusing an event_id must never be merged.",
    ),
    Bypass(
        "note_advances_state",
        "controller/engine.py",
        """            to_state = from_state
            new_seq = task["state_seq"]""",
        """            to_state = from_state
            new_seq = task["state_seq"] + 1  # BYPASS""",
        ["test_a_note_appends_an_event_without_moving_the_task"],
        "A note that bumps state_seq invalidates every outstanding result.",
    ),
    # A sixth bypass sat here -- an explicit terminal-state check in
    # apply_transition -- and the matrix scored it NOT LOAD-BEARING with zero
    # tests caught. It was unreachable: TRANSITIONS holds no entry from a
    # terminal state except COMPLETE -> REVERTED, so resolve() already refused
    # all of them. The check was deleted rather than kept. That protection
    # lives in the table, guarded by
    # test_terminal_states_accept_nothing_except_the_one_allowed_exit.
]


def failing_tests():
    """Run the suite and return the set of failing test function names."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    names = set()
    for line in proc.stdout.splitlines():
        # ERROR counts as caught, not just FAILED. When a bypass breaks a
        # fixture rather than an assertion, pytest reports the tests that
        # depended on it as errors -- and a guard whose removal makes the
        # database fail to open is about as load-bearing as a guard gets.
        # Counting only FAILED under-reported exactly that case.
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            # "FAILED tests/test_x.py::test_name[param] - AssertionError"
            node = line.split(" ", 1)[1].split(" - ")[0]
            func = node.split("::")[-1].split("[")[0]
            if func:
                names.add(func)

    return names, proc.returncode


def main() -> int:
    baseline, code = failing_tests()

    if baseline:
        print("REFUSING TO RUN: the suite is not green to begin with.")
        print("failing:", sorted(baseline))
        return 1

    print("baseline: suite green (exit %d)\n" % code)

    results = []

    for bypass in BYPASSES:
        original = io.open(bypass.path, encoding="utf-8", newline="").read()

        if original.count(bypass.old) != 1:
            results.append((bypass.name, "ANCHOR-MISS", set(), set()))
            print("%-32s ANCHOR MISS (source moved)" % bypass.name)
            continue

        digest = hashlib.sha256(original.encode()).hexdigest()

        try:
            io.open(bypass.path, "w", encoding="utf-8", newline="").write(
                original.replace(bypass.old, bypass.new)
            )
            caught, _ = failing_tests()
        finally:
            io.open(bypass.path, "w", encoding="utf-8", newline="").write(original)
            restored = hashlib.sha256(
                io.open(bypass.path, encoding="utf-8", newline="").read().encode()
            ).hexdigest()
            assert restored == digest, "FAILED TO RESTORE %s" % bypass.path

        missed = bypass.expect_failures - caught
        extra = caught - bypass.expect_failures
        verdict = "LOAD-BEARING" if not missed and caught else "NOT LOAD-BEARING"

        results.append((bypass.name, verdict, caught, missed))
        print(
            "%-32s %-17s caught=%-2d expected=%-2d%s"
            % (
                bypass.name,
                verdict,
                len(caught),
                len(bypass.expect_failures),
                "  MISSED: %s" % sorted(missed) if missed else "",
            )
        )
        if extra:
            print("%-32s   also failed: %s" % ("", sorted(extra)))

    print()
    bad = [r for r in results if r[1] != "LOAD-BEARING"]
    print("guards proven load-bearing: %d/%d" % (len(results) - len(bad), len(results)))

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
