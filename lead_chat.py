"""Post to and read the hive chat as an interactive engineering lead (#109).

The hub knows the background workers (`claudecode`, `gemini`, `chatgpt`) and
the operator (`admin`). The interactive Claude and Codex sessions that lead the
engineering are neither, so until now their handoffs lived only on GitHub, or
David copied them between chats. This gives each lead its own identity:

    python lead_chat.py post --as claude-lead "HANDOFF @codex-lead: review #111 at 1a2b3c4"
    python lead_chat.py read --as codex-lead --since 1200 --mentions
    python lead_chat.py find --as claude-lead "HANDOFF @codex-lead: review #111 at 1a2b3c4"

What a lead identity is, and is not:

* **Its own credential, chosen explicitly.** `--as` must name an allowlisted
  identity, and that identity's secret comes only from its own variable. There
  is no fallback to a worker's `HUB_SECRET` or to `admin`. A lead post that
  silently went out as `claudecode` would read as the background worker's
  claim, and one that went out as `admin` would read as David and reach the
  command ingress.
* **Not authority.** Lead identities are not admin components. The hub stores
  the message and never parses it as a command, and no worker activates on
  chat from any sender. Handoffs coordinate; controller-issued activations
  still carry execution authority, and review evidence is still the exact
  commit, CI and the PR review.
* **A receipt, not a claim.** `post` prints the message id the hub assigned and
  then reads that id back, checking the stored sender and content. Only a
  confirmed read-back is reported as posted.
* **No blind resend.** `/send` has no idempotency key, so a lost response is
  reported as UNCONFIRMED (exit 2), never retried. Run `find` with the same
  text before posting again.

Standard library only, so it runs from either lead's shell without installing
anything.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# The only identities this tool will post as, each with the one variable its
# secret may come from. `*_HUB_SECRET` is also the suffix the ingest worker's
# child-environment filter strips, so a lead secret never reaches git or gh.
IDENTITIES = {
    "claude-lead": "CLAUDE_LEAD_HUB_SECRET",
    "codex-lead": "CODEX_LEAD_HUB_SECRET",
}

HUB_URL = os.environ.get("HUB_URL", "http://192.168.42.50:8050").rstrip("/")
DEFAULT_TARGET = "@room"

# A handoff is a line or a paragraph with links. Anything near this size is a
# document, which belongs on the PR where it can be reviewed.
MAX_CONTENT = 4000
TIMEOUT = 15

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_UNCONFIRMED = 2
EXIT_REFUSED = 3


class LeadChatError(Exception):
    """A refusal this tool decided before or instead of talking to the hub."""


@dataclass
class Response:
    status: int
    body: object


# (method, url, headers, json body or None) -> Response. Raises OSError for a
# transport failure, which is the case that leaves a post unconfirmed.
Transport = Callable[[str, str, dict, Optional[dict]], Response]


def urllib_transport(method: str, url: str, headers: dict, body: Optional[dict]) -> Response:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={
        **headers, **({"Content-Type": "application/json"} if data is not None else {}),
    })

    # Every way the exchange can break becomes OSError, the one transport
    # failure `post` reports as UNCONFIRMED. A reply cut short (a declared
    # Content-Length that never arrives) raises http.client.IncompleteRead,
    # which is not an OSError, and the request may already have been stored
    # (Codex, #112 at 9f36273).
    try:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
                raw = reply.read()
                status = reply.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
    except http.client.HTTPException as exc:
        raise OSError(f"incomplete HTTP exchange ({type(exc).__name__})") from None

    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        parsed = None

    return Response(status, parsed)


def _user_environment(name: str) -> Optional[str]:
    """A user-level variable set after this shell started (Windows only).

    `setx` writes HKCU\\Environment, but a process sees only what it inherited,
    so a lead session opened before the secret was installed would otherwise
    report it missing until restarted.
    """
    if os.name != "nt":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None

    return value if isinstance(value, str) else None


def secret_for(identity: str, *, environ=None, user_environment=_user_environment) -> str:
    """The secret for exactly this identity, or LeadChatError. Never another's."""
    if identity not in IDENTITIES:
        raise LeadChatError(
            f"{identity!r} is not a lead identity; expected one of {sorted(IDENTITIES)}"
        )

    variable = IDENTITIES[identity]
    environ = os.environ if environ is None else environ
    secret = (environ.get(variable) or user_environment(variable) or "").strip()

    if not secret:
        raise LeadChatError(f"{variable} is not set; {identity} has no credential here")

    return secret


def _auth(identity: str, secret: str) -> dict:
    token = base64.b64encode(f"{identity}:{secret}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _messages(transport: Transport, url: str, headers: dict, since_id: int) -> list:
    reply = transport("GET", f"{url}/messages?since_id={int(since_id)}", headers, None)

    if reply.status == 401:
        raise LeadChatError("the hub rejected this credential (401)")
    if reply.status != 200 or not isinstance(reply.body, list):
        raise OSError(f"GET /messages answered {reply.status}")

    return reply.body


# A whole handle: not inside a word or an address before it, and not followed
# by more handle characters or a domain-like `.x` after it. `target_for` and
# `mentions` share these boundaries so a post can never be addressed to a lead
# that reading it back would not count as mentioned (Codex, #112 at 9f36273).
HANDLE_BEFORE = r"(?<![\w@.-])"
HANDLE_AFTER = r"(?![\w-]|\.\w)"
MENTION = re.compile(HANDLE_BEFORE + r"@([A-Za-z][\w-]*)" + HANDLE_AFTER)


def target_for(content: str) -> str:
    """The first @mention, so `QUESTION @admin: …` shows as to @admin; else the room.

    The chat page only looks at the first token, but lead posts start with
    their kind (HANDOFF, REVIEW, QUESTION), so the addressee comes second.
    """
    match = MENTION.search(content)
    return "@" + match.group(1) if match else DEFAULT_TARGET


@dataclass
class Receipt:
    state: str            # "confirmed", "unconfirmed" or "mismatch"
    message_id: Optional[int]
    detail: str

    @property
    def exit_code(self) -> int:
        return {"confirmed": EXIT_OK, "unconfirmed": EXIT_UNCONFIRMED}.get(
            self.state, EXIT_REFUSED)


def post(identity: str, content: str, *, target: Optional[str] = None,
         url: str = HUB_URL, transport: Transport = urllib_transport,
         environ=None, user_environment=_user_environment) -> Receipt:
    """Post once, then read the assigned id back. Never resends."""
    content = content.strip()

    if not content:
        raise LeadChatError("nothing to post")
    if len(content) > MAX_CONTENT:
        raise LeadChatError(
            f"{len(content)} characters is over {MAX_CONTENT}; put the detail on the PR and link it"
        )

    headers = _auth(identity, secret_for(identity, environ=environ,
                                         user_environment=user_environment))
    target = target or target_for(content)

    try:
        # No `sender`: the hub derives it from the credential and ignores the field.
        reply = transport("POST", f"{url}/send", headers, {"target": target, "content": content})
    except OSError as exc:
        return Receipt("unconfirmed", None, f"no response from the hub ({type(exc).__name__}); "
                       "the message may or may not be stored -- run `find` before posting again")

    if reply.status in (401, 403, 422):
        raise LeadChatError(f"the hub refused the post ({reply.status})")

    body = reply.body if isinstance(reply.body, dict) else {}
    message_id = body.get("id")

    if reply.status != 200 or type(message_id) is not int:
        return Receipt("unconfirmed", None, f"the hub answered {reply.status} without a message id; "
                       "run `find` before posting again")

    try:
        stored = [m for m in _messages(transport, url, headers, message_id - 1)
                  if isinstance(m, dict) and m.get("id") == message_id]
    except (OSError, LeadChatError) as exc:
        # The POST already returned an id, so the send was accepted. A read-back
        # that fails -- including a 401 if the credential rotated in between --
        # says nothing about that; keep the id and leave the outcome unknown
        # rather than report a rejection (Codex, #112 at 9f36273).
        return Receipt("unconfirmed", message_id,
                       f"the hub assigned #{message_id}, but reading it back failed ({exc}); "
                       "run `find` before posting again")

    if not stored:
        return Receipt("unconfirmed", message_id, f"#{message_id} was not found on read-back")

    row = stored[0]
    if row.get("sender") != identity or row.get("content") != content or row.get("target") != target:
        return Receipt("mismatch", message_id,
                       f"#{message_id} reads back as sender {row.get('sender')!r}, not what was sent")

    return Receipt("confirmed", message_id, f"#{message_id} stored as {identity} -> {target}")


def find(identity: str, content: str, *, since_id: int = 0, url: str = HUB_URL,
         transport: Transport = urllib_transport, environ=None,
         user_environment=_user_environment) -> list:
    """Ids of messages this identity already posted with exactly this content."""
    headers = _auth(identity, secret_for(identity, environ=environ,
                                         user_environment=user_environment))
    content = content.strip()

    return [m["id"] for m in _messages(transport, url, headers, since_id)
            if isinstance(m, dict) and m.get("sender") == identity and m.get("content") == content]


def mentions(message: dict, identity: str) -> bool:
    """Addressed to this identity, by target or by an @mention in the text."""
    handle = "@" + identity.lower()
    target = str(message.get("target", "")).strip().lower()
    # Whole handle only: `@claude-lead:` and `(@claude-lead)` are mentions,
    # `@claude-leader` and `x@claude-lead.example` are not.
    pattern = HANDLE_BEFORE + re.escape(handle) + HANDLE_AFTER

    return target == handle or re.search(pattern, str(message.get("content", "")).lower()) is not None


def read(identity: str, *, since_id: int = 0, only_mentions: bool = False,
         url: str = HUB_URL, transport: Transport = urllib_transport, environ=None,
         user_environment=_user_environment) -> list:
    """Messages after `since_id`, optionally only those addressed to `identity`.

    A lead's own posts are left out: reading back what it said is `find`.
    """
    headers = _auth(identity, secret_for(identity, environ=environ,
                                         user_environment=user_environment))
    rows = [m for m in _messages(transport, url, headers, since_id)
            if isinstance(m, dict) and m.get("sender") != identity]

    return [m for m in rows if mentions(m, identity)] if only_mentions else rows


def main(argv=None, *, transport: Transport = urllib_transport, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=HUB_URL)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("post", help="post one message and confirm it by read-back")
    p.add_argument("--as", dest="identity", required=True, choices=sorted(IDENTITIES))
    p.add_argument("--to", dest="target", help="target; default: a leading @mention, else @room")
    p.add_argument("content")

    p = sub.add_parser("find", help="ids of this lead's earlier posts with exactly this text")
    p.add_argument("--as", dest="identity", required=True, choices=sorted(IDENTITIES))
    p.add_argument("--since", type=int, default=0)
    p.add_argument("content")

    p = sub.add_parser("read", help="messages after an id, as JSON lines")
    p.add_argument("--as", dest="identity", required=True, choices=sorted(IDENTITIES))
    p.add_argument("--since", type=int, default=0)
    p.add_argument("--mentions", action="store_true", help="only messages addressed to this lead")

    args = parser.parse_args(argv)

    try:
        if args.command == "post":
            receipt = post(args.identity, args.content, target=args.target,
                           url=args.url, transport=transport)
            print(f"{receipt.state.upper()}: {receipt.detail}", file=out)
            return receipt.exit_code

        if args.command == "find":
            ids = find(args.identity, args.content, since_id=args.since,
                       url=args.url, transport=transport)
            print(json.dumps({"ids": ids}), file=out)
            return EXIT_OK

        for message in read(args.identity, since_id=args.since, only_mentions=args.mentions,
                            url=args.url, transport=transport):
            print(json.dumps(message, ensure_ascii=False), file=out)
        return EXIT_OK
    except LeadChatError as exc:
        print(f"REFUSED: {exc}", file=out)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"UNREACHABLE: {type(exc).__name__}: {exc}", file=out)
        return EXIT_UNCONFIRMED


if __name__ == "__main__":
    sys.exit(main())
