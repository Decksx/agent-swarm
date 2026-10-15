"""Model-free external PR fetch/pin engine. Controller dispatch is wired separately.

Inputs come from a validated, immutable activation. This module never creates
tasks, reports controller events, checks out code, runs tests or calls a model.
"""

from __future__ import annotations

import hashlib
import json
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

import repo_registry

MAX_EVIDENCE = 128 * 1024
SHA = re.compile(r"[0-9a-fA-F]{40}")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


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


class Commands:
    """Bounded commands with one monotonic budget and live-lease checkpoints."""

    def __init__(self, remaining: float, heartbeat: Callable[[], bool]):
        if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
                or not math.isfinite(remaining) or remaining <= 1):
            raise IngestError("deadline_exhausted")
        self.deadline = time.monotonic() + remaining - 1  # reserve result-report time
        self.heartbeat = heartbeat

    def checkpoint(self):
        if time.monotonic() >= self.deadline:
            raise IngestError("deadline_exhausted")
        try:
            live = self.heartbeat()
        except Exception:
            raise IngestError("lease_lost") from None
        if live is not True:
            raise IngestError("lease_lost")
        if time.monotonic() >= self.deadline:
            raise IngestError("deadline_exhausted")

    def run(self, args: list[str], repo: Path, *, allowed=(0,), evidence=False) -> tuple[int, str]:
        self.checkpoint()
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                   GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(args, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr,
                    **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                       if os.name == "nt" else {"start_new_session": True}))
            except OSError:
                raise IngestError("command_unavailable", command=args[0]) from None
            try:
                next_heartbeat = time.monotonic() + 2
                while process.poll() is None:
                    if os.fstat(stderr.fileno()).st_size > MAX_EVIDENCE:
                        raise IngestError("diagnostic_overflow")
                    if os.fstat(stdout.fileno()).st_size > MAX_EVIDENCE:
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
            output, diagnostic = stdout.read(MAX_EVIDENCE + 1), stderr.read(MAX_EVIDENCE + 1)
            if len(diagnostic) > MAX_EVIDENCE:
                raise IngestError("diagnostic_overflow")
            if len(output) > MAX_EVIDENCE:
                raise IngestError("evidence_too_large" if evidence else "command_output_overflow",
                                  refusal=evidence)
            if process.returncode not in allowed:
                # gh's machine-observable HTTP status distinguishes a missing
                # PR only after the caller has verified repository access.
                missing = args[0] == "gh" and b"HTTP 404" in diagnostic
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


def _json(command, args: list[str], repo: Path, *, evidence=False):
    try:
        value = json.loads(command.run(args, repo, evidence=evidence)[1])
    except (ValueError, TypeError):
        raise IngestError("invalid_forge_metadata") from None
    if not isinstance(value, dict):
        raise IngestError("invalid_forge_metadata")
    return value


def ingest(request: Request, *, remaining: float, heartbeat: Callable[[], bool],
           registry: Path | None = None, commands: Commands | None = None,
           scratch_is_live: Callable[[str], bool | None] | None = None) -> dict:
    """Return complete evidence, or raise IngestError. No controller side effects.

    heartbeat must affirm the current lease; scratch_is_live must freshly
    identify a previous activation as not live before its scratch refs are
    removed. Unknown status is preserved. Neither callback grants authority
    to accept evidence: that remains the controller's fenced result route.
    """
    command = commands or Commands(remaining, heartbeat)
    for name in (request.task_id, request.activation_id):
        if not isinstance(name, str) or not COMPONENT.fullmatch(name):
            raise IngestError("invalid_activation_identity")
    if (isinstance(request.pr_number, bool) or not isinstance(request.pr_number, int)
            or request.pr_number <= 0 or not isinstance(request.repo_slug, str)
            or not isinstance(request.project, str) or not request.project.strip()
            or not isinstance(request.repo_location, str) or not request.repo_location.strip()
            or not repo_registry.REPO_SLUG.fullmatch(request.repo_slug)):
        raise IngestError("invalid_external_request")
    expected = _sha(request.at_sha, "at_sha") if request.at_sha is not None else None
    command.checkpoint()
    try:
        project = repo_registry.get(request.project, registry)
        if not project.path.is_absolute() or not Path(request.repo_location).is_absolute():
            raise IngestError("repository_location_mismatch")
        repo = project.path.resolve(strict=True)
        if repo != Path(request.repo_location).resolve(strict=True):
            raise IngestError("repository_location_mismatch")
    except (OSError, repo_registry.RegistryError):
        raise IngestError("repository_unavailable") from None
    if not project.publish_repo_slug or project.publish_repo_slug.casefold() != request.repo_slug.casefold():
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
        pin = f"refs/swarm/external/{request.task_id}"
        scratch_prefix = f"refs/swarm/ingest-tmp/{request.task_id}/"
        scratch = f"{scratch_prefix}{request.activation_id}"
        for ref in (pin, scratch + "/head", scratch + "/base"):
            git("check-ref-format", ref)
        if scratch_is_live is not None:
            listed = git("for-each-ref", "--format=%(refname) %(objectname)", scratch_prefix)[1]
            for line in listed.splitlines():
                ref, old = line.split(" ", 1)
                parts = ref[len(scratch_prefix):].split("/")
                if (not ref.startswith(scratch_prefix) or len(parts) != 2
                        or not COMPONENT.fullmatch(parts[0]) or parts[0] == request.activation_id
                        or parts[1] not in {"head", "base"}):
                    continue
                command.checkpoint()
                try:
                    live = scratch_is_live(parts[0])
                except Exception:
                    raise IngestError("scratch_status_unavailable") from None
                if live is False:
                    command.checkpoint()
                    git("update-ref", "-d", ref, _sha(old, "scratch_sha"))

        repo_metadata = _json(command, ["gh", "api", "--hostname", "github.com",
                                      f"repos/{request.repo_slug}"], repo)
        if str(repo_metadata.get("full_name", "")).casefold() != request.repo_slug.casefold():
            raise IngestError("repository_slug_mismatch")
        try:
            metadata = _json(command, ["gh", "api", "--hostname", "github.com",
                f"repos/{request.repo_slug}/pulls/{request.pr_number}"], repo, evidence=True)
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
        git("fetch", "--no-tags", "--no-write-fetch-head", "origin",
            f"+refs/pull/{request.pr_number}/head:{scratch}/head", f"+{base}:{scratch}/base")
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
        files = changed.split("\0")[:-1]
        if ancestor == head or not files:
            raise IngestError("empty_review_range", refusal=True)
        signals = []
        signal_bytes = 0
        for commit in git("rev-list", f"{ancestor}..{head}", evidence=True)[1].splitlines():
            commit = _sha(commit, "commit_sha")
            raw = git("show", "--no-patch", "--format=%ae%x00%B", commit, evidence=True)[1]
            email, separator, body = raw.partition("\0")
            if not separator:
                raise IngestError("invalid_commit_metadata")
            signal = {"source": "git_commit", "commit_sha": commit,
                      "author_email": email, "message": body}
            signal_bytes += len(json.dumps(signal, ensure_ascii=False).encode())
            if signal_bytes > MAX_EVIDENCE:
                raise IngestError("evidence_too_large", refusal=True)
            signals.append(signal)
        signals.append({"source": "github_pr", "pr_url": url,
                        "title": metadata.get("title"), "body": metadata.get("body") or "",
                        "author": metadata.get("user")})
        evidence = {"schema_version": 1, "repo_id": project.repo_id,
            "repo_location": str(repo), "pr_number": request.pr_number, "pr_url": url,
            "head_sha": head, "resolved_ref_sha": resolved, "base_ref_sha": base,
            "merge_base": ancestor, "pin_ref": pin, "changed_files": files,
            "author_signals": signals, "pr_state": metadata.get("state"),
            "pr_draft": metadata.get("draft"), "merged_at": metadata.get("merged_at")}
        if len(json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_EVIDENCE:
            raise IngestError("evidence_too_large", refusal=True)
        # CAS is distinct from lease fencing. A stale attempt can leave an
        # orphan, but may never replace an existing candidate or authorize it.
        code, _ = git("update-ref", pin, head, "0" * 40, allowed=(0, 128))
        if code:
            actual = git("rev-parse", "--verify", pin)[1].strip()
            if actual != head:
                raise IngestError("pin_conflict", refusal=True, observed_sha=actual, expected_sha=head)
        command.checkpoint()
        return evidence
