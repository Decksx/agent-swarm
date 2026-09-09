"""Fault injection: prove each containment guard is load-bearing.

A passing suite with the guards present proves nothing about the guards. It is
equally consistent with the guards being unreachable defensive code that fails
nothing when removed. The only way to tell the difference is to take each one
out and confirm that specific, named tests fail.

Each entry below is one guard, bypassed by an exact source substitution, with
the tests that are expected to catch it. The script applies one bypass, runs
the suite, restores the file, and reports whether the failures matched. The
restore happens in a `finally` and is verified by hash.

**A `finally` is not enough, and this was learned the hard way.** On
2026-09-09 a run was killed by an external timeout part-way through and left
`claude_worker.py` sabotaged on disk -- `finally` does not run when the process
is killed rather than interrupted. The next test run then failed for a reason
that had nothing to do with the change being tested, which is a genuinely
confusing way to lose an hour.

So before applying anything, this script now writes a sidecar recording which
file it is about to touch and that file's original contents, and removes it
only after a verified restore. A later run finds the sidecar, restores from it,
and says so. The sidecar is the recovery path a `finally` cannot provide.

Run it directly:

    python tests/bypass_matrix.py
"""

from __future__ import annotations

import hashlib
import io
import json
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


# Where the in-progress record lives. Deliberately inside the repository and
# deliberately not gitignored: a stray one should be visible in `git status`.
SIDECAR = REPO / ".bypass_in_progress"


def _write_sidecar(path: Path, original: str) -> None:
    payload = json.dumps({"path": str(path.relative_to(REPO)), "original": original})
    io.open(SIDECAR, "w", encoding="utf-8", newline="").write(payload)


def _clear_sidecar() -> None:
    try:
        SIDECAR.unlink()
    except FileNotFoundError:
        pass


def recover_from_a_killed_run() -> None:
    """Restore a file a previous run was killed before it could put back.

    Called at startup. Silent when there is nothing to do, loud when there is,
    because a sabotaged source file that quietly repaired itself would leave
    somebody wondering what they had actually just measured.
    """
    if not SIDECAR.exists():
        return

    try:
        record = json.loads(io.open(SIDECAR, encoding="utf-8", newline="").read())
        target = REPO / record["path"]
        original = record["original"]
    except (ValueError, KeyError, OSError) as exc:
        print(f"!! {SIDECAR.name} is unreadable ({exc}); restore by hand")
        return

    current = io.open(target, encoding="utf-8", newline="").read()

    if current == original:
        print(f"!! a previous run was killed but {record['path']} was already intact")
    else:
        io.open(target, "w", encoding="utf-8", newline="").write(original)
        print(f"!! restored {record['path']} from a killed run before starting")

    _clear_sidecar()


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
    # --- Worker conversion (Phase 1 MVP) -----------------------------------
    Bypass(
        "both_queue_sources",
        "claude_worker.py",
        """            if queue is not None:
                try:
                    activation = queue.claim()""",
        """            if queue is not None:
                swarm_control.claim_activation(AGENT_IDENTITY)  # BYPASS
                try:
                    activation = queue.claim()""",
        ["test_the_controller_source_never_touches_the_local_directory"],
        "Two queues means two activations held at once, and neither queue "
        "knows about the other's -- host capacity would count one while a "
        "second ran beside it.",
    ),
    Bypass(
        "inflight_marker_resumed",
        "claude_worker.py",
        """    if INFLIGHT_PATH.exists():
        try:""",
        """    if False:  # BYPASS
        try:""",
        ["test_an_inflight_marker_is_not_resumed"],
        "A worker that ignores the marker leaves a stale one on disk forever, "
        "so the next crash is indistinguishable from the last.",
    ),
    Bypass(
        "marker_written_after_the_run",
        "claude_worker.py",
        """    if activation_id:
        try:
            INFLIGHT_PATH.write_text(str(activation_id), encoding="utf-8")""",
        """    if False and activation_id:  # BYPASS
        try:
            INFLIGHT_PATH.write_text(str(activation_id), encoding="utf-8")""",
        ["test_the_marker_is_written_before_the_model_runs"],
        "Without the marker a crash mid-run is invisible at restart, which is "
        "the one case it exists to catch.",
    ),
    Bypass(
        "auth_failure_backed_off_not_fatal",
        "controller_client.py",
        """        except Unauthenticated:
            # Raised, not swallowed. The worker exits on this.
            raise""",
        """        except Unauthenticated as exc:  # BYPASS
            self.backoff.fail(str(exc))
            return None""",
        [
            "test_a_rejected_credential_is_raised_and_not_backed_off",
            "test_a_server_error_backs_off_but_a_fatal_one_does_not",
        ],
        "Backing off a rejected credential produces a worker that is alive, "
        "logging, and structurally incapable of ever doing work.",
    ),
    Bypass(
        "claim_forbidden_not_fatal",
        "controller_client.py",
        """            if " 403 " in str(exc):
                raise ClaimForbidden(str(exc)) from exc""",
        """            if False:  # BYPASS
                raise ClaimForbidden(str(exc)) from exc""",
        ["test_a_forbidden_claim_is_fatal_too"],
        "A component refused work entirely cannot poll its way out of it.",
    ),
    Bypass(
        "retry_after_ignored",
        "controller_client.py",
        """            self.retry_after = exc.retry_after
            return None""",
        """            self.retry_after = 0.0  # BYPASS
            return None""",
        [
            "test_a_429_is_honoured_rather_than_guessed_at",
            "test_a_missing_retry_after_falls_back_to_a_sane_wait",
        ],
        "Ignoring a named interval means polling straight back into the "
        "throttle that produced it.",
    ),
    # The worker's own handling of what the client raises. Separate rows from
    # the client-side classification above, because the matrix showed they are
    # separate guards: the tests that drive a stub queue directly are
    # unaffected by anything controller_client does.
    Bypass(
        "fatal_auth_exit_code_erased",
        "claude_worker.py",
        """                    return 4""",
        """                    return 0  # BYPASS""",
        [
            "test_the_worker_exits_with_a_distinct_code_on_a_rejected_credential",
            "test_a_forbidden_claim_also_exits",
        ],
        "The exit code is the whole signal: a supervisor has to tell "
        "'this credential is wrong' from a crash or a missing binary, "
        "because only one of them is fixed by editing the launcher. "
        "Bypassed by returning 0 rather than by swallowing the exception -- "
        "swallowing it makes the worker poll forever, which is the real "
        "failure but hangs the matrix instead of failing a named test.",
    ),
    Bypass(
        "server_interval_not_awaited",
        "claude_worker.py",
        """            wait = max(wait, getattr(queue, "retry_after", 0.0), queue.backoff.current)""",
        """            wait = wait  # BYPASS""",
        ["test_a_throttle_paces_the_next_poll"],
        "Polling at the ordinary cadence through a throttle walks straight "
        "back into the throttle that produced it.",
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
    # --- Activation lifecycle (Phase 1) ------------------------------------
    Bypass(
        "deadline_extended_by_heartbeat",
        "controller/activations.py",
        """            "UPDATE activations SET heartbeat_at = ?, lease_expires_at = ?, "
            "heartbeat_seq = heartbeat_seq + 1 WHERE activation_id = ?",
            (now, now + lease_seconds, activation_id),""",
        """            "UPDATE activations SET heartbeat_at = ?, lease_expires_at = ?, "
            "heartbeat_seq = heartbeat_seq + 1, hard_deadline_at = ? "
            "WHERE activation_id = ?",
            (now, now + lease_seconds, now + 99999, activation_id),  # BYPASS""",
        ["test_a_heartbeat_renews_the_lease_but_never_the_deadline"],
        "Invariant 10: a looping worker would keep itself alive forever.",
    ),
    Bypass(
        "wrong_worker_accepted",
        "controller/activations.py",
        """        if row["agent"] != agent:
            raise NotTheAssignedWorker(
                f"activation is assigned to another agent, not {agent!r}"
            )

        # 2-3. Idempotency, before liveness.""",
        """        if False:  # BYPASS
            raise NotTheAssignedWorker("")

        # 2-3. Idempotency, before liveness.""",
        ["test_only_the_assigned_worker_may_act", "test_identity_is_checked_before_expiry"],
        "Any worker could submit any other worker's result.",
    ),
    Bypass(
        "capacity_ignored",
        "controller/activations.py",
        """        blocked = _capacity_blocked(conn, host)
        if blocked is not None:""",
        """        blocked = _capacity_blocked(conn, host)
        if False:  # BYPASS""",
        [
            "test_capacity_prevents_a_second_activation",
            "test_an_undeclared_host_is_refused_rather_than_treated_as_unlimited",
            "test_a_draining_host_takes_no_new_activations",
            "test_an_exclusive_holder_excludes_everything_else",
        ],
        "Without a cap the system retries directly into its own contention.",
    ),
    Bypass(
        "result_deadline_ignored",
        "controller/activations.py",
        """        if now >= row["hard_deadline_at"]:
            raise DeadlineExceeded("hard deadline has passed")

        if now >= row["lease_expires_at"]:
            raise LeaseExpired("lease has expired")

        # 5. The activation must still be for the task version""",
        """        if False:  # BYPASS
            raise DeadlineExceeded("")

        if False:
            raise LeaseExpired("")

        # 5. The activation must still be for the task version""",
        [
            "test_the_controller_is_authoritative_regardless_of_harness_belief",
            "test_a_late_result_after_lease_expiry_is_refused",
        ],
        "The controller is authoritative regardless of harness arithmetic.",
    ),
    Bypass(
        "stale_task_version_accepted",
        "controller/activations.py",
        """        if task["current_version"] != row["task_version"]:""",
        """        if False:  # BYPASS""",
        ["test_a_result_for_a_superseded_task_version_is_refused"],
        "A refreshed contract invalidates work done under the old one.",
    ),
    Bypass(
        "evidence_durability_skipped",
        "controller/activations.py",
        """        problem = _evidence_is_durable(conn, evidence_ids)
        if problem is not None:""",
        """        problem = _evidence_is_durable(conn, evidence_ids)
        if False:  # BYPASS""",
        [
            "test_a_result_citing_missing_evidence_is_refused",
            "test_a_result_citing_evidence_without_blobs_is_refused",
            "test_a_rejected_result_leaves_the_activation_claimable_again",
        ],
        "A COMPLETE whose proof is a reaped temp directory is not proof.",
    ),
    Bypass(
        "sweep_does_not_recover",
        "controller/activations.py",
        """    for item in reclaimed:
        task = engine.get_task(conn, item["task_id"])""",
        """    for item in []:  # BYPASS
        task = engine.get_task(conn, item["task_id"])""",
        [
            "test_the_sweep_recovers_the_task_not_just_the_activation",
            "test_a_deadline_during_work_uses_the_without_checkpoint_branch",
            "test_an_unclaimed_activation_recovers_from_the_assigned_state",
            "test_sweeping_frees_the_host_slot",
        ],
        "Reclaiming without recovering leaves a permanently stuck task.",
    ),
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
    # Before the baseline, not after: a file left sabotaged by a killed run
    # would make the baseline fail and this script refuse to run, reporting a
    # red suite that is entirely its own doing.
    recover_from_a_killed_run()

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

        # Written before the file is touched, so a hard kill leaves a recovery
        # path rather than a sabotaged worker. `finally` covers an exception;
        # it does not cover the process being killed.
        _write_sidecar(bypass.path, original)

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
            _clear_sidecar()

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
