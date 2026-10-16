"""Reviewing a change the swarm did not author: the request and the ingest report.

#74, slice 2 (#92). The wire format is section 8 of
`docs/design/92-ingest-contract.md`, and this module is its controller half:

- `create` turns an admin's request into a task in EXTERNAL_PENDING, in one
  transaction, storing the request as canonical JSON in `contract_yaml`.
- `load_request` reads it back. It is the only input an ingest activation is
  given about the pull request -- never the PR itself, never chat.
- `claim_inputs` is the `external` object a claimed ingest activation carries,
  including which earlier attempts' scratch refs are safe to delete.
- `check_report` is what the controller verifies itself before it applies a
  worker's report. The worker's evidence about git objects cannot be checked
  from here (the controller has no checkout); everything that *can* be
  compared against the stored request is, and no worker-supplied boolean
  stands in for a comparison.

Nothing here calls a model, reads a repository or reaches the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any, Optional

from . import engine
from .db import transaction
from .states import ADMIN

CONTRACT_SCHEMA = 7
REQUEST_SCHEMA = 1
REPORT_SCHEMA = 1
KIND = "external_review"

PIN_PREFIX = "refs/swarm/external/"
SCRATCH_PREFIX = "refs/swarm/ingest-tmp/"

# Chosen so `refs/swarm/external/<task_id>` is a valid ref by construction;
# the worker still runs `git check-ref-format`.
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# The same rule as `repo_registry.REPO_SLUG`, which guards `gh --repo` against
# option-like values. Copied rather than imported because `repo_registry` is not
# deployed to Tower -- only `hub.py` and this package are -- and a test holds
# the two patterns equal.
REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_ID_RE = re.compile(r"^[0-9a-f]{16}$")

FAMILIES = frozenset({"anthropic", "openai", "google", "human"})
PR_STATES = frozenset({"open", "closed", "merged"})
SIGNAL_KINDS = frozenset({"co_authored_by", "commit_author_email", "pr_body_footer"})

MAX_REPORT_BYTES = 131_072
MAX_TITLE_CHARS = 1_024
MAX_BODY_BYTES = 65_536
MAX_PATH_CHARS = 4_096
MAX_SIGNALS = 500
MAX_SIGNAL_CHARS = 512
MAX_DETAIL_CHARS = 2_000
MAX_OBJECTIVE_CHARS = 20_000

REFUSAL_OBSERVED = {
    "pr_not_found": (),
    "head_moved": ("head_sha", "resolved_ref_sha"),
    "at_sha_mismatch": ("head_sha",),
    "pin_conflict": ("head_sha", "existing_pin_sha"),
    "no_merge_base": ("head_sha", "base_ref_sha"),
    "empty_range": ("head_sha",),
    "evidence_too_large": ("head_sha",),
}

BLOCKED_REASONS = frozenset({
    "github_unreachable", "gh_auth", "gh_error", "git_fetch_failed",
    "object_missing", "repo_unusable", "repo_slug_mismatch",
    "slug_not_configured", "deadline_exhausted", "worker_error",
})

OBSERVED_KEYS = frozenset({
    "head_sha", "resolved_ref_sha", "base_ref_sha", "existing_pin_sha", "at_sha",
})

REGISTERED_KEYS = frozenset({
    "schema_version", "project", "repo_location", "repo_slug", "repo_id",
    "pr_number", "pr_url", "pr_state", "pr_draft", "pr_title", "pr_body",
    "pr_body_truncated", "pr_body_sha256", "head_sha", "resolved_ref_sha",
    "base_ref_sha", "merge_base", "pin_ref", "pin_created", "changed_files",
    "author_signals",
})


class ExternalRequestRefused(Exception):
    """An external-review request that will not become a task (400)."""


class ExternalReviewDisabled(ExternalRequestRefused):
    """External review is not configured, or not for this project (400)."""


class ReportInvalid(Exception):
    """An ingest report the controller will not apply. Carries the reason."""


def canonical(value: Any) -> str:
    """The one serialisation the request is stored and hashed as."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pin_ref(task_id: str) -> str:
    return PIN_PREFIX + task_id


def scratch_prefix(task_id: str, activation_id: str) -> str:
    return f"{SCRATCH_PREFIX}{task_id}/{activation_id}"


def valid_task_id(task_id: str) -> bool:
    return bool(
        isinstance(task_id, str) and TASK_ID_RE.fullmatch(task_id)
        and ".." not in task_id and not task_id.endswith((".lock", "."))
    )


def parse_repos(value: Optional[str]) -> dict:
    """`EXTERNAL_REVIEW_REPOS` as {project: "owner/name"}.

    Read per request, like `INGRESS_PROJECTS`. Anything wrong with it disables
    external review -- this raises -- and touches nothing else: the controller
    starts and serves every other route whatever this setting holds.
    """
    if not (value or "").strip():
        raise ExternalReviewDisabled(
            "external review is not configured: EXTERNAL_REVIEW_REPOS is unset"
        )

    try:
        repos = json.loads(value)
    except ValueError:
        raise ExternalReviewDisabled(
            "external review is disabled: EXTERNAL_REVIEW_REPOS is not valid JSON"
        ) from None

    if not isinstance(repos, dict):
        raise ExternalReviewDisabled(
            "external review is disabled: EXTERNAL_REVIEW_REPOS must be a JSON object"
        )

    parsed = {}

    for project, slug in repos.items():
        if not isinstance(project, str) or not isinstance(slug, str) \
                or not REPO_SLUG_RE.fullmatch(slug):
            raise ExternalReviewDisabled(
                f"external review is disabled: EXTERNAL_REVIEW_REPOS entry "
                f"{project!r} is not an owner/name slug"
            )
        parsed[project.strip().lower()] = slug

    return parsed


def _sorted_unique_paths(paths: Any) -> list:
    if not isinstance(paths, list) or not paths:
        raise ExternalRequestRefused("paths must be a non-empty list when given")

    for path in paths:
        if not _safe_path(path):
            raise ExternalRequestRefused(f"{path!r} is not a repository-relative path")

    return sorted(set(paths))


def _safe_path(path: Any) -> bool:
    return (
        isinstance(path, str) and 0 < len(path) <= MAX_PATH_CHARS
        and not path.startswith(("/", "\\")) and ":" not in path[:2]
        and ".." not in re.split(r"[\\/]", path) and "\x00" not in path
    )


def build_request(
    *,
    project: str,
    pr_number: Any,
    at_sha: Optional[str],
    paths: Optional[list],
    authored_by: Optional[list],
    projects: dict,
    repos: dict,
) -> dict:
    """The `external` block, validated. Raises ExternalRequestRefused."""
    name = (project or "").strip().lower()

    if name not in projects:
        known = ", ".join(sorted(projects)) or "none configured"
        raise ExternalRequestRefused(f"unknown project {project!r}; known: {known}")

    if name not in repos:
        raise ExternalReviewDisabled(f"project {name!r} not enabled for external review")

    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
        raise ExternalRequestRefused("pr_number must be a positive integer")

    if at_sha is not None:
        at_sha = at_sha.strip().lower() if isinstance(at_sha, str) else at_sha
        if not isinstance(at_sha, str) or not SHA_RE.fullmatch(at_sha):
            raise ExternalRequestRefused("at_sha must be a full 40-character commit SHA")

    families = authored_by or []
    if not isinstance(families, list) or not all(
            isinstance(f, str) and f in FAMILIES for f in families):
        raise ExternalRequestRefused(
            f"authored_by must name families from {sorted(FAMILIES)}"
        )

    return {
        "schema_version": REQUEST_SCHEMA,
        "project": name,
        "repo_location": projects[name],
        "repo_slug": repos[name],
        "pr_number": pr_number,
        "at_sha": at_sha,
        "paths": None if paths is None else _sorted_unique_paths(paths),
        "authored_by": sorted(set(families)),
    }


def create(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    project: str,
    pr_number: Any,
    objective: str,
    at_sha: Optional[str] = None,
    paths: Optional[list] = None,
    authored_by: Optional[list] = None,
    projects: dict,
    repos: dict,
    actor: str,
    now: Optional[float] = None,
) -> dict:
    """Create an external-review task and move it to EXTERNAL_PENDING, atomically.

    Every refusal happens before anything is written, and the insert and the
    transition share one transaction, so no request leaves a DRAFT row behind.

    `base_sha` is the empty sentinel: an external review has no authoring
    baseline, and the PR's real base is recorded when ingest pins it. Only
    this route may store it (the generic task route requires a full SHA).
    """
    if not valid_task_id(task_id):
        raise ExternalRequestRefused(
            "task_id must be 1-64 characters of letters, digits, '.', '_' or '-', "
            "starting with a letter or digit, with no '..' and not ending in "
            "'.lock' or '.'"
        )

    objective = (objective or "").strip() if isinstance(objective, str) else ""
    if not objective:
        raise ExternalRequestRefused("objective is required: the operator states it")
    if len(objective) > MAX_OBJECTIVE_CHARS:
        raise ExternalRequestRefused(f"objective is over {MAX_OBJECTIVE_CHARS} characters")

    request = build_request(
        project=project, pr_number=pr_number, at_sha=at_sha, paths=paths,
        authored_by=authored_by, projects=projects, repos=repos,
    )
    contract = canonical({
        "external": request, "kind": KIND, "schema_version": CONTRACT_SCHEMA,
    })

    with transaction(conn):
        created = engine.create_task_within(
            conn, task_id=task_id,
            title=f"External review: {request['repo_slug']} PR #{request['pr_number']}",
            objective=objective, contract_yaml=contract, base_sha="",
            created_by=actor, proof_mode="branch_only",
            protocol_schema_version=CONTRACT_SCHEMA, now=now,
        )
        outcome = engine.apply_transition_within(
            conn, task_id=task_id, kind="external_review_requested",
            actor=actor, authority=ADMIN, now=now,
            payload={
                "project": request["project"],
                "repo_slug": request["repo_slug"],
                "pr_number": request["pr_number"],
                "at_sha": request["at_sha"],
                "contract_hash": created["contract_hash"],
            },
        )

    return {
        "task_id": task_id,
        "state": outcome["to_state"],
        "state_seq": outcome["state_seq"],
        "contract_hash": created["contract_hash"],
        "request": request,
    }


def load_request(
    conn: sqlite3.Connection, task_id: str, version: Optional[int] = None
) -> Optional[dict]:
    """The stored `external` block, or None if this is not an external review.

    The current version unless one is named. A contract that is not this
    route's JSON is not an external request, whatever else it says.
    """
    if version is None:
        row = conn.execute(
            "SELECT v.contract_yaml FROM task_versions v JOIN tasks t "
            "ON t.task_id = v.task_id AND t.current_version = v.version "
            "WHERE t.task_id = ?",
            (task_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT contract_yaml FROM task_versions WHERE task_id = ? AND version = ?",
            (task_id, version),
        ).fetchone()

    if row is None:
        return None

    try:
        contract = json.loads(row["contract_yaml"])
    except (TypeError, ValueError):
        return None

    if not isinstance(contract, dict) or contract.get("kind") != KIND:
        return None

    request = contract.get("external")

    if not isinstance(request, dict) or request.get("schema_version") != REQUEST_SCHEMA:
        return None

    return request


def claim_inputs(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """The `external` object a claimed ingest activation carries (section 8.2).

    `reclaimable_scratch_prefixes` is the controller deciding what is safe to
    delete, because only it knows which activations are dead: every other
    ingest activation of this task that is no longer live. Only one ingest
    activation per task can be live, and the caller holds it, so none of the
    listed attempts can have a result accepted any more.
    """
    request = load_request(conn, row["task_id"], row["task_version"]) or {}

    dead = conn.execute(
        "SELECT activation_id FROM activations WHERE task_id = ? AND stage = 'ingest' "
        "AND activation_id <> ? AND status NOT IN ('ISSUED', 'CLAIMED') "
        "ORDER BY issued_at, activation_id",
        (row["task_id"], row["activation_id"]),
    ).fetchall()

    return {
        "schema_version": REQUEST_SCHEMA,
        "project": request.get("project"),
        "repo_location": request.get("repo_location"),
        "repo_slug": request.get("repo_slug"),
        "pr_number": request.get("pr_number"),
        "at_sha": request.get("at_sha"),
        "paths": request.get("paths"),
        "pin_ref": pin_ref(row["task_id"]),
        "scratch_ref_prefix": scratch_prefix(row["task_id"], row["activation_id"]),
        "reclaimable_scratch_prefixes": [
            scratch_prefix(row["task_id"], d["activation_id"]) for d in dead
        ],
    }


# --- The report ----------------------------------------------------------------


def _sha(payload: dict, key: str) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ReportInvalid(f"{key} must be a lowercase 40-character SHA")

    return value


def _string(payload: dict, key: str, *, max_chars: int) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or len(value) > max_chars:
        raise ReportInvalid(f"{key} must be a string of at most {max_chars} characters")

    return value


def _bool(payload: dict, key: str) -> bool:
    value = payload.get(key)

    if not isinstance(value, bool):
        raise ReportInvalid(f"{key} must be true or false")

    return value


def _is_int(value: Any) -> bool:
    """An integer in the JSON sense: `True` and `102.0` are not."""
    return type(value) is int


def _same_slug(a: str, b: str) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.casefold() == b.casefold()


def check_report(request: dict, task_id: str, outcome: str, payload: Any) -> None:
    """Refuse a report the stored request contradicts. Raises ReportInvalid.

    Section 8.4 and 8.5 of the contract, checked here rather than trusted.
    """
    if not isinstance(request, dict) or not request:
        raise ReportInvalid(f"{task_id} has no external-review request to check against")

    if not isinstance(payload, dict):
        raise ReportInvalid("payload must be an object")

    if not _is_int(payload.get("schema_version")) or payload["schema_version"] != REPORT_SCHEMA:
        raise ReportInvalid(f"schema_version must be {REPORT_SCHEMA}")

    size = len(canonical(payload).encode("utf-8"))
    if size > MAX_REPORT_BYTES:
        raise ReportInvalid(
            f"report is {size} bytes, over {MAX_REPORT_BYTES}; report refused "
            "with evidence_too_large instead"
        )

    try:
        if outcome == "registered":
            _check_registered(request, task_id, payload)
        elif outcome in ("refused", "blocked"):
            _check_failure(request, outcome, payload)
        else:
            raise ReportInvalid(f"unknown ingest outcome {outcome!r}")
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        # The explicit type checks above should make this unreachable. It is
        # here so a shape nobody anticipated is still a refused report (422)
        # rather than a server error the worker would retry unchanged.
        raise ReportInvalid(f"malformed report: {type(exc).__name__}") from None


def _check_registered(request: dict, task_id: str, payload: dict) -> None:
    unknown = sorted(set(payload) - REGISTERED_KEYS)
    missing = sorted(REGISTERED_KEYS - set(payload))

    if unknown:
        raise ReportInvalid(f"unknown keys {unknown}")
    if missing:
        raise ReportInvalid(f"missing keys {missing}")

    if payload["project"] != request["project"]:
        raise ReportInvalid("project does not match the request")
    if payload["repo_location"] != request["repo_location"]:
        raise ReportInvalid("repo_location does not match the request")
    if not _same_slug(payload["repo_slug"], request["repo_slug"]):
        raise ReportInvalid("repo_slug does not match the request")

    repo_id = payload["repo_id"]
    if not isinstance(repo_id, str) or not REPO_ID_RE.fullmatch(repo_id):
        raise ReportInvalid("repo_id must be 16 lowercase hex characters")

    number = payload["pr_number"]
    if not _is_int(number) or number != request["pr_number"]:
        raise ReportInvalid("pr_number does not match the request")

    url = payload["pr_url"]
    prefix = "https://github.com/"
    expected_tail = f"/pull/{request['pr_number']}"
    if not (isinstance(url, str) and url.startswith(prefix) and url.endswith(expected_tail)
            and _same_slug(url[len(prefix):-len(expected_tail)], request["repo_slug"])):
        raise ReportInvalid(
            f"pr_url must be {prefix}{request['repo_slug']}{expected_tail}"
        )

    if not isinstance(payload["pr_state"], str) or payload["pr_state"] not in PR_STATES:
        raise ReportInvalid(f"pr_state must be one of {sorted(PR_STATES)}")
    _bool(payload, "pr_draft")

    _string(payload, "pr_title", max_chars=MAX_TITLE_CHARS)
    body = payload["pr_body"]
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ReportInvalid(f"pr_body must be a string of at most {MAX_BODY_BYTES} bytes")
    truncated = _bool(payload, "pr_body_truncated")
    digest = payload["pr_body_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ReportInvalid("pr_body_sha256 must be 64 lowercase hex characters")
    if not truncated and hashlib.sha256(body.encode("utf-8")).hexdigest() != digest:
        raise ReportInvalid("pr_body_sha256 is not the SHA-256 of an untruncated pr_body")

    head = _sha(payload, "head_sha")
    resolved = _sha(payload, "resolved_ref_sha")
    _sha(payload, "base_ref_sha")
    merge_base = _sha(payload, "merge_base")

    if resolved != head:
        raise ReportInvalid("resolved_ref_sha differs from head_sha; that is head_moved")
    if request.get("at_sha") and head != request["at_sha"]:
        raise ReportInvalid("head_sha differs from the requested at_sha; that is at_sha_mismatch")
    if merge_base == head:
        raise ReportInvalid("merge_base equals head_sha; that is empty_range")

    if payload["pin_ref"] != pin_ref(task_id):
        raise ReportInvalid(f"pin_ref must be {pin_ref(task_id)}")
    _bool(payload, "pin_created")

    files = payload["changed_files"]
    if not isinstance(files, list) or not files:
        raise ReportInvalid("changed_files must be a non-empty list")
    if not all(_safe_path(f) for f in files):
        raise ReportInvalid("changed_files must be repository-relative paths")
    if files != sorted(set(files)):
        raise ReportInvalid("changed_files must be sorted and unique")

    signals = payload["author_signals"]
    if not isinstance(signals, list) or len(signals) > MAX_SIGNALS:
        raise ReportInvalid(f"author_signals must be a list of at most {MAX_SIGNALS}")
    for signal in signals:
        if not (isinstance(signal, dict) and set(signal) == {"kind", "value", "source"}
                and isinstance(signal["kind"], str) and signal["kind"] in SIGNAL_KINDS
                and isinstance(signal["value"], str)
                and len(signal["value"]) <= MAX_SIGNAL_CHARS
                and isinstance(signal["source"], str)
                and (signal["source"] == "pr_body"
                     or (signal["source"].startswith("commit:")
                         and SHA_RE.fullmatch(signal["source"][len("commit:"):])))):
            raise ReportInvalid(f"author signal {signal!r} is not kind/value/source as specified")


def _check_failure(request: dict, outcome: str, payload: dict) -> None:
    unknown = sorted(set(payload) - {"schema_version", "reason_code", "detail", "observed"})
    if unknown:
        raise ReportInvalid(f"unknown keys {unknown}")

    reason = payload.get("reason_code")
    if not isinstance(reason, str):
        raise ReportInvalid("reason_code must be a string")
    _string(payload, "detail", max_chars=MAX_DETAIL_CHARS)

    observed = payload.get("observed", {})
    if not isinstance(observed, dict) or set(observed) - OBSERVED_KEYS:
        raise ReportInvalid(f"observed may only hold {sorted(OBSERVED_KEYS)}")
    for key in observed:
        _sha(observed, key)

    if outcome == "blocked":
        if reason not in BLOCKED_REASONS:
            raise ReportInvalid(f"unknown blocked reason_code {reason!r}")
        return

    if reason not in REFUSAL_OBSERVED:
        raise ReportInvalid(f"unknown refused reason_code {reason!r}")

    absent = [k for k in REFUSAL_OBSERVED[reason] if k not in observed]
    if absent:
        raise ReportInvalid(f"{reason} must carry observed {absent}")

    if reason == "head_moved" and observed["head_sha"] == observed["resolved_ref_sha"]:
        raise ReportInvalid("head_moved needs head_sha and resolved_ref_sha to differ")
    if reason == "pin_conflict" and observed["head_sha"] == observed["existing_pin_sha"]:
        raise ReportInvalid("pin_conflict needs head_sha and existing_pin_sha to differ")
    if reason == "at_sha_mismatch":
        at_sha = request.get("at_sha")
        if not at_sha:
            raise ReportInvalid("at_sha_mismatch, but the request named no at_sha")
        if observed["head_sha"] == at_sha:
            raise ReportInvalid("at_sha_mismatch, but head_sha equals the requested at_sha")
