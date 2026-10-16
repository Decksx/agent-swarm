"""Model-free external PR fetch/pin engine, dispatched by claude_worker.

Inputs come from a validated, immutable activation. This module never creates
tasks, reports controller events, checks out code, runs tests or calls a model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import repo_registry
import controller_client
import swarm_control

MAX_EVIDENCE = 128 * 1024
SHA = re.compile(r"[0-9a-fA-F]{40}")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
log = logging.getLogger("claude_ingest")
FOOTER = re.compile(r"^[ ]{0,3}(?:\U0001f916[ \t]*)?(?:generated (?:with|by)\s+|co-authored-by:\s*)", re.I)
TRAILING_LINK = re.compile(r"^[ ]{0,3}(?:https?://[^\s<>]+|<https?://[^\s<>]+>)[ \t]*$", re.I)


def footer_lines(body: str) -> list[str]:
    """Only an explicit trailing attribution block, outside Markdown fences."""
    lines = body.rstrip().splitlines()
    start = len(lines)
    separators = {"---", "___", "***"}
    while start:
        previous = lines[start - 1]
        if (previous.strip() and not FOOTER.match(previous)
                and not TRAILING_LINK.fullmatch(previous) and previous.strip() not in separators):
            break
        start -= 1
    block = lines[start:]
    if (not block or not any(FOOTER.match(line) for line in block)
            or (start and block[0].strip() and block[0].strip() not in separators)):
        return []
    # A blank line inside a still-open code fence cannot turn an example into
    # an attribution claim. Fence length follows Markdown's closing rule.
    fence_char, fence_size = None, 0
    for line in lines[:start]:
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence_char is None:
                fence_char, fence_size = token[0], len(token)
            elif (token[0] == fence_char and len(token) >= fence_size
                  and not line[marker.end():].strip()):
                fence_char = None
    return [] if fence_char else [line for line in block if FOOTER.match(line)]


def signal_excerpts(value: str):
    if len(value) <= 512:
        yield value
        return
    found = False
    seen = set()
    covered_end = 0
    for anchor in re.finditer(r"claude|anthropic|codex|openai|gemini|google|<[^>\n]+>", value, re.I):
        found = True
        if anchor.end() <= covered_end:
            continue
        center = anchor.start()
        start = max(0, min(center - 200, len(value) - 510))
        end = min(len(value), start + 510)
        covered_end = max(covered_end, end)
        excerpt = ("\u2026" if start else "") + value[start:end] + ("\u2026" if end < len(value) else "")
        if excerpt not in seen:
            seen.add(excerpt)
            yield excerpt
    if not found:
        yield value[:511] + "\u2026"
        yield "\u2026" + value[-511:]


def command_environment() -> dict:
    """Keep gh authentication, remove worker credentials and Git overrides."""
    model_keys = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("GIT_") and k.upper() != "HUB_SECRET"
           and not k.upper().endswith("_HUB_SECRET") and k.upper() not in model_keys}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
    return env


def origin_matches(url: str, slug: str) -> bool:
    """Recognise GitHub fetch URL forms without exposing embedded credentials."""
    if url.casefold().startswith("git@github.com:"):
        path = url[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"https", "ssh"} or not parsed.hostname
                    or parsed.hostname.casefold() != "github.com" or parsed.query or parsed.fragment
                    or parsed.port not in {None, 443 if parsed.scheme == "https" else 22}):
                return False
            path = parsed.path.removeprefix("/")
        except ValueError:
            return False
    path = path.removesuffix("/")
    if path.casefold().endswith(".git"):
        path = path[:-4]
    return path.casefold() == slug.casefold()


class IngestError(Exception):
    """A typed outcome with bounded facts, never raw process diagnostics."""

    def __init__(self, code: str, *, refusal: bool = False, **facts):
        super().__init__(code)
        self.code, self.refusal, self.facts = code, refusal, facts


@dataclass(frozen=True)
class Request:
    task_id: str
    activation_id: str
    project: str
    repo_location: str
    repo_slug: str
    pr_number: int
    at_sha: str | None = None
    reclaimable_scratch_prefixes: tuple[str, ...] = ()


class Commands:
    """Bounded commands with one monotonic budget and live-lease checkpoints."""

    def __init__(self, remaining: float, heartbeat: Callable[[], bool]):
        if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
                or not math.isfinite(remaining) or remaining <= 1):
            raise IngestError("deadline_exhausted")
        self.deadline = time.monotonic() + remaining - 1  # reserve result-report time
        self.heartbeat = heartbeat
        self.next_heartbeat = float("-inf")

    def checkpoint(self, *, force=False):
        if time.monotonic() >= self.deadline:
            raise IngestError("deadline_exhausted")
        if not force and time.monotonic() < self.next_heartbeat:
            return
        try:
            live = self.heartbeat()
        except Exception:
            raise IngestError("lease_lost") from None
        if live is not True:
            raise IngestError("lease_lost")
        self.next_heartbeat = time.monotonic() + 15
        if time.monotonic() >= self.deadline:
            raise IngestError("deadline_exhausted")

    def run(self, args: list[str], repo: Path, *, allowed=(0,), evidence=False,
            output_limit=None) -> tuple[int, str]:
        self.checkpoint()
        limit = MAX_EVIDENCE if output_limit is None else output_limit
        env = command_environment()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(args, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr,
                    **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                       if os.name == "nt" else {"start_new_session": True}))
            except OSError:
                raise IngestError("gh_error" if args[0] == "gh" else "command_unavailable",
                                  command=args[0]) from None
            try:
                next_heartbeat = time.monotonic() + 2
                while process.poll() is None:
                    if os.fstat(stderr.fileno()).st_size > MAX_EVIDENCE:
                        raise IngestError("diagnostic_overflow")
                    if os.fstat(stdout.fileno()).st_size > limit:
                        raise IngestError("evidence_too_large" if evidence else "command_output_overflow",
                                          refusal=evidence)
                    if time.monotonic() >= self.deadline:
                        raise IngestError("deadline_exhausted")
                    if time.monotonic() >= next_heartbeat:
                        self.checkpoint()
                        next_heartbeat = time.monotonic() + 2
                    time.sleep(min(.05, max(0, self.deadline - time.monotonic())))
            finally:
                if process.poll() is None:
                    try:
                        if os.name == "nt":
                            try:
                                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=5, check=False)
                            except (OSError, subprocess.TimeoutExpired):
                                pass
                        else:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
            self.checkpoint()
            stdout.seek(0)
            stderr.seek(0)
            output, diagnostic = stdout.read(limit + 1), stderr.read(MAX_EVIDENCE + 1)
            if len(diagnostic) > MAX_EVIDENCE:
                raise IngestError("diagnostic_overflow")
            if len(output) > limit:
                raise IngestError("evidence_too_large" if evidence else "command_output_overflow",
                                  refusal=evidence)
            if process.returncode not in allowed:
                # gh's machine-observable HTTP status distinguishes a missing
                # PR only after the caller has verified repository access.
                missing = args[0] == "gh" and b"HTTP 404" in diagnostic
                if args[0] == "gh" and (process.returncode == 4 or b"HTTP 401" in diagnostic):
                    raise IngestError("gh_auth")
                if args[0] == "gh" and not missing:
                    network = (b"could not resolve", b"no such host", b"dial tcp", b"error connecting",
                               b"failed to connect", b"connection refused", b"network is unreachable",
                               b"tls handshake timeout")
                    raise IngestError("github_unreachable" if any(
                        marker in diagnostic.lower() for marker in network) else "gh_error")
                raise IngestError("not_found" if missing else "command_failed",
                                  command=args[0], exit_code=process.returncode)
            try:
                return process.returncode, output.decode("utf-8")
            except UnicodeDecodeError:
                raise IngestError("unreadable_evidence") from None


def _sha(value, name: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise IngestError("invalid_sha", field=name)
    return value.lower()


def _json(command, args: list[str], repo: Path, *, evidence=False, output_limit=None):
    try:
        value = json.loads(command.run(args, repo, evidence=evidence, output_limit=output_limit)[1])
    except (ValueError, TypeError):
        raise IngestError("invalid_forge_metadata") from None
    if not isinstance(value, dict):
        raise IngestError("invalid_forge_metadata")
    return value


def ingest(request: Request, *, remaining: float, heartbeat: Callable[[], bool],
           registry: Path | None = None, commands: Commands | None = None) -> dict:
    """Return complete evidence, or raise IngestError. No controller side effects.

    heartbeat must affirm the current lease. Only controller-named terminal
    attempts' scratch prefixes may be reclaimed. Result acceptance remains
    the controller's decision, separately from Git pin protection.
    """
    command = commands or Commands(remaining, heartbeat)
    for name in (request.task_id, request.activation_id):
        if (not isinstance(name, str) or not COMPONENT.fullmatch(name)
                or ".." in name or name.endswith((".lock", "."))):
            raise IngestError("invalid_activation_identity")
    if not TASK_ID.fullmatch(request.task_id):
        raise IngestError("invalid_activation_identity")
    if (isinstance(request.pr_number, bool) or not isinstance(request.pr_number, int)
            or request.pr_number <= 0 or not isinstance(request.repo_slug, str)
            or not isinstance(request.project, str) or not request.project.strip()
            or not isinstance(request.repo_location, str) or not request.repo_location.strip()
            or not repo_registry.REPO_SLUG.fullmatch(request.repo_slug)):
        raise IngestError("invalid_external_request")
    if request.at_sha is not None:
        _sha(request.at_sha, "at_sha")
    command.checkpoint(force=True)
    try:
        project = repo_registry.get(request.project, registry)
        if not project.path.is_absolute() or not Path(request.repo_location).is_absolute():
            raise IngestError("repository_location_mismatch")
        repo = project.path.resolve(strict=True)
        if repo != Path(request.repo_location).resolve(strict=True):
            raise IngestError("repository_location_mismatch")
    except (OSError, repo_registry.RegistryError):
        raise IngestError("repository_unavailable") from None
    if not project.publish_repo_slug:
        raise IngestError("slug_not_configured")
    if project.publish_repo_slug.casefold() != request.repo_slug.casefold():
        raise IngestError("repository_slug_mismatch")
    # Disable fetch hooks without changing repository config or relying on a
    # platform-specific null path. Every Git command shares this empty hook dir.
    with tempfile.TemporaryDirectory(prefix="swarm-ingest-hooks-") as hooks:
        def git(*args, allowed=(0,), evidence=False):
            return command.run(["git", "-c", f"core.hooksPath={hooks}",
                                "-c", "protocol.ext.allow=never", *args], repo,
                               allowed=allowed, evidence=evidence)

        roots = sorted(git("rev-list", "--max-parents=0", "HEAD")[1].splitlines())
        identity = hashlib.sha256("\n".join(roots).encode()).hexdigest()[:16]
        if not roots or identity != project.repo_id:
            raise IngestError("repository_identity_mismatch")
        origins = git("remote", "get-url", "--all", "origin")[1].splitlines()
        if len(origins) != 1 or not origin_matches(origins[0], request.repo_slug):
            raise IngestError("repository_slug_mismatch")
        pin = f"refs/swarm/external/{request.task_id}"
        scratch_prefix = f"refs/swarm/ingest-tmp/{request.task_id}/"
        scratch = f"{scratch_prefix}{request.activation_id}"
        for ref in (pin, scratch + "/head", scratch + "/base"):
            git("check-ref-format", ref)
        for prefix in request.reclaimable_scratch_prefixes:
            if not isinstance(prefix, str) or not prefix.startswith(scratch_prefix):
                raise IngestError("invalid_scratch_prefix")
            old_id = prefix[len(scratch_prefix):]
            if (not COMPONENT.fullmatch(old_id) or ".." in old_id
                    or old_id.endswith((".lock", ".")) or old_id == request.activation_id):
                raise IngestError("invalid_scratch_prefix")

        def cleanup(prefixes):
            # Best effort: failure to delete cannot change a measured outcome.
            # The next ordinary command/checkpoint still fences a lost lease.
            for prefix in prefixes:
                try:
                    listed = git("for-each-ref", "--format=%(refname) %(objectname)", prefix + "/")[1]
                    for line in listed.splitlines():
                        ref, old = line.split(" ", 1)
                        if not ref.startswith(prefix + "/"):
                            continue
                        try:
                            git("update-ref", "-d", ref, _sha(old, "scratch_sha"))
                        except IngestError:
                            log.warning("scratch delete failed; leaving ref in place")
                except (IngestError, ValueError):
                    log.warning("scratch cleanup unavailable; leaving refs in place")

        cleanup(request.reclaimable_scratch_prefixes)
        try:
            return _fetch_pin(request, project, repo, pin, scratch, git, command)
        finally:
            cleanup((scratch,))


def _fetch_pin(request, project, repo, pin, scratch, git, command):
    head = base = None
    expected = _sha(request.at_sha, "at_sha") if request.at_sha is not None else None
    try:

        try:
            repo_metadata = _json(command, ["gh", "api", "--hostname", "github.com",
                                          f"repos/{request.repo_slug}"], repo)
        except IngestError as exc:
            if exc.code == "not_found":
                raise IngestError("gh_error") from None
            raise
        if str(repo_metadata.get("full_name", "")).casefold() != request.repo_slug.casefold():
            raise IngestError("repository_slug_mismatch")
        try:
            metadata = _json(command, ["gh", "api", "--hostname", "github.com",
                f"repos/{request.repo_slug}/pulls/{request.pr_number}"], repo,
                output_limit=2 * 1024 * 1024)
        except IngestError as exc:
            if exc.code == "not_found":
                raise IngestError("pr_not_found", refusal=True) from None
            raise
        if (not isinstance(metadata.get("head"), dict) or not isinstance(metadata.get("base"), dict)
                or metadata.get("state") not in {"open", "closed"}
                or not isinstance(metadata.get("draft"), bool)
                or (metadata.get("body") is not None and not isinstance(metadata["body"], str))):
            raise IngestError("invalid_forge_metadata")
        head = _sha(metadata["head"].get("sha"), "head_sha")
        base = _sha(metadata["base"].get("sha"), "base_ref_sha")
        if not isinstance(metadata.get("title"), str):
            raise IngestError("invalid_forge_metadata")
        url = f"https://github.com/{request.repo_slug}/pull/{request.pr_number}"
        if str(metadata.get("html_url", "")).casefold() != url.casefold():
            raise IngestError("repository_slug_mismatch")
        if type(metadata.get("number")) is not int or metadata["number"] != request.pr_number:
            raise IngestError("pr_identity_mismatch")
        if expected is not None and head != expected:
            raise IngestError("operator_sha_mismatch", refusal=True, expected_sha=expected, observed_sha=head)
        existing_code, existing = git("show-ref", "--verify", "--hash", pin, allowed=(0, 1, 128))
        if existing_code == 0 and _sha(existing.strip(), "pin_sha") != head:
            raise IngestError("pin_conflict", refusal=True, observed_sha=existing.strip(), expected_sha=head)
        try:
            git("fetch", "--no-tags", "--no-write-fetch-head", "origin",
                f"+refs/pull/{request.pr_number}/head:{scratch}/head", f"+{base}:{scratch}/base")
        except IngestError as exc:
            if exc.code in {"command_failed", "command_unavailable"}:
                raise IngestError("git_fetch_failed") from None
            raise
        resolved = _sha(git("rev-parse", "--verify", scratch + "/head^{commit}")[1].strip(), "resolved_ref_sha")
        resolved_base = _sha(git("rev-parse", "--verify", scratch + "/base^{commit}")[1].strip(), "resolved_base_sha")
        if resolved != head:
            raise IngestError("pr_moved", refusal=True, expected_sha=head, observed_sha=resolved)
        if resolved_base != base:
            raise IngestError("base_object_mismatch")
        code, ancestor = git("merge-base", base, head, allowed=(0, 1))
        if code == 1:
            raise IngestError("no_common_ancestor", refusal=True)
        ancestor = _sha(ancestor.strip(), "merge_base")
        changed = git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", ancestor, head, "--", evidence=True)[1]
        files = sorted(set(changed.split("\0")[:-1]))
        if ancestor == head or not files:
            raise IngestError("empty_review_range", refusal=True)
        signals = []
        seen_signals = set()
        def signal(kind, value, source):
            for excerpt in signal_excerpts(value):
                key = (kind, excerpt)
                if key in seen_signals:
                    continue
                if len(signals) >= 500:
                    raise IngestError("evidence_too_large", refusal=True)
                seen_signals.add(key)
                signals.append({"kind": kind, "value": excerpt, "source": source})
        for commit in git("rev-list", f"{ancestor}..{head}", evidence=True)[1].splitlines():
            commit = _sha(commit, "commit_sha")
            raw = git("show", "--no-patch", "--format=%ae%x00%B", commit, evidence=True)[1]
            email, separator, body = raw.partition("\0")
            if not separator:
                raise IngestError("invalid_commit_metadata")
            signal("commit_author_email", email, f"commit:{commit}")
            for match in re.finditer(r"^Co-Authored-By:[ \t]*(.*)$", body, re.I | re.M):
                signal("co_authored_by", match.group(1).rstrip("\r"), f"commit:{commit}")
        full_body = metadata.get("body") or ""
        for line in footer_lines(full_body):
            signal("pr_body_footer", line, "pr_body")
        raw_body = full_body.encode("utf-8")
        truncated = len(raw_body) > 65_536
        saved_body = raw_body[:65_536].decode("utf-8", "ignore")
        if len(metadata["title"]) > 1_024:
            raise IngestError("evidence_too_large", refusal=True)
        evidence = {"schema_version": 1, "project": request.project,
            "repo_slug": request.repo_slug, "repo_id": project.repo_id,
            "repo_location": request.repo_location, "pr_number": request.pr_number, "pr_url": url,
            "head_sha": head, "resolved_ref_sha": resolved, "base_ref_sha": base,
            "merge_base": ancestor, "pin_ref": pin, "changed_files": files,
            "author_signals": signals,
            "pr_state": "merged" if metadata.get("merged_at") else metadata["state"],
            "pr_draft": metadata["draft"], "pr_title": metadata["title"],
            "pr_body": saved_body, "pr_body_truncated": truncated,
            "pr_body_sha256": hashlib.sha256(raw_body).hexdigest(), "pin_created": False}
        if len(json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_EVIDENCE:
            raise IngestError("evidence_too_large", refusal=True)
        # CAS is distinct from lease fencing. A stale attempt can leave an
        # orphan, but may never replace an existing candidate or authorize it.
        command.checkpoint(force=True)
        code, _ = git("update-ref", pin, head, "0" * 40, allowed=(0, 128))
        if code:
            actual = git("rev-parse", "--verify", pin)[1].strip()
            if actual != head:
                raise IngestError("pin_conflict", refusal=True, observed_sha=actual, expected_sha=head)
        evidence["pin_created"] = code == 0
        command.checkpoint(force=True)
        return evidence
    except IngestError as exc:
        # Every refusal except pr_not_found needs the observed head on the wire.
        if head is not None:
            exc.facts.setdefault("head_sha", head)
        if base is not None:
            exc.facts.setdefault("base_ref_sha", base)
        raise


def failure_payload(error: IngestError) -> tuple[str, dict]:
    """Translate internal errors to the fixed section 8.5 report vocabulary."""
    refusal_codes = {
        "pr_not_found": "pr_not_found", "operator_sha_mismatch": "at_sha_mismatch",
        "pr_moved": "head_moved", "pin_conflict": "pin_conflict",
        "no_common_ancestor": "no_merge_base", "empty_review_range": "empty_range",
        "evidence_too_large": "evidence_too_large",
    }
    blocked_codes = {
        "repository_unavailable": "repo_unusable", "repository_location_mismatch": "repo_unusable",
        "repository_identity_mismatch": "repo_unusable", "repository_slug_mismatch": "repo_slug_mismatch",
        "deadline_exhausted": "deadline_exhausted", "git_fetch_failed": "git_fetch_failed",
        "base_object_mismatch": "object_missing", "gh_auth": "gh_auth",
        "slug_not_configured": "slug_not_configured",
        "gh_error": "gh_error", "github_unreachable": "github_unreachable",
    }
    outcome, code = "blocked", blocked_codes.get(error.code, "worker_error")
    observed = {k: v for k, v in error.facts.items()
                if k in {"head_sha", "base_ref_sha"} and isinstance(v, str)
                and re.fullmatch(r"[0-9a-f]{40}", v)}
    if error.refusal and error.code in refusal_codes:
        if error.code == "pr_not_found" or "head_sha" in observed:
            outcome, code = "refused", refusal_codes[error.code]
    if code == "head_moved":
        observed["resolved_ref_sha"] = _sha(error.facts["observed_sha"], "resolved_ref_sha")
    elif code == "pin_conflict":
        observed["existing_pin_sha"] = _sha(error.facts["observed_sha"], "existing_pin_sha")
    return outcome, {"schema_version": 1, "reason_code": code,
                     "detail": f"External ingest stopped: {code}.", "observed": observed}


def execute_ingest(activation: dict, queue, *, registry: Path | None = None) -> None:
    """Run a controller ingest claim, maintaining its lease and reporting evidence."""
    activation_id = activation.get("activation_id")
    if queue is None:
        log.error("ingest requires the controller queue")
        return
    try:
        external = activation.get("external")
        if (activation.get("source") != "controller" or activation.get("stage") != "ingest"
                or activation.get("role") != "operator"
                or (activation.get("task_record") or {}).get("state") != "EXTERNAL_INGESTING"
                or not isinstance(external, dict) or type(external.get("schema_version")) is not int
                or external["schema_version"] != 1):
            raise IngestError("invalid_external_activation")
        request = Request(
            task_id=activation["task_id"], activation_id=activation_id,
            project=external["project"], repo_location=external["repo_location"],
            repo_slug=external["repo_slug"], pr_number=external["pr_number"],
            at_sha=external["at_sha"],
            reclaimable_scratch_prefixes=tuple(external["reclaimable_scratch_prefixes"]),
        )
        if (external.get("pin_ref") != f"refs/swarm/external/{request.task_id}"
                or external.get("scratch_ref_prefix") !=
                f"refs/swarm/ingest-tmp/{request.task_id}/{request.activation_id}"
                or not isinstance(external["reclaimable_scratch_prefixes"], list)):
            raise IngestError("invalid_external_activation")
        timing = queue.heartbeat(activation_id, 900.0)
        if not timing:
            raise IngestError("lease_lost")
        command = None
        def heartbeat():
            fresh = queue.heartbeat(activation_id, 900.0)
            if not fresh:
                return False
            remaining = fresh.get("hard_deadline_seconds_remaining")
            if (isinstance(remaining, bool) or not isinstance(remaining, (float, int))
                    or not math.isfinite(remaining) or remaining <= 1):
                return False
            if command is not None:
                command.deadline = min(command.deadline, time.monotonic() + remaining - 1)
            return True
        command = Commands(timing.get("hard_deadline_seconds_remaining"), heartbeat)
        evidence = ingest(request, remaining=timing["hard_deadline_seconds_remaining"],
                          heartbeat=heartbeat, registry=registry, commands=command)
        outcome, payload = "registered", evidence
    except IngestError as exc:
        outcome, payload = failure_payload(exc)
    except Exception:
        outcome, payload = failure_payload(IngestError("worker_error"))
    try:
        response = queue.report_ingest(activation_id, outcome=outcome, payload=payload)
        if response is None:
            log.warning("ingest report delivery unconfirmed for %s", activation_id)
    except controller_client.Refused as exc:
        if outcome != "registered" or exc.status_code != 422:
            log.warning("ingest report refused for %s (status %s)", activation_id, exc.status_code)
            return
        detail = exc.detail
        for key, value in os.environ.items():
            if value and ("SECRET" in key.upper() or "TOKEN" in key.upper() or "API_KEY" in key.upper()):
                detail = detail.replace(value, "[REDACTED-CREDENTIAL]")
        detail = swarm_control.redact(detail).encode("utf-8", "replace").decode("utf-8")
        blocked = {"schema_version": 1, "reason_code": "worker_error", "observed": {},
                   "detail": ("Controller rejected registered ingest report (422): " + detail)[:2000]}
        try:
            queue.report_ingest(activation_id, outcome="blocked", payload=blocked)
        except controller_client.ControllerError:
            log.warning("corrected blocked ingest report was not accepted for %s", activation_id)
