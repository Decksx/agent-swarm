"""Agent Swarm Hub -- the control plane.

Phase 0 authentication
----------------------

Every route requires an authenticated component, and the server derives the
message `sender` from that credential. A client-supplied `sender` is accepted
by the schema for compatibility and then **ignored**, because it was never
evidence of anything: before this change the browser UI hardcoded
`sender: "Admin"` on every send, so anyone who opened the page posted as Admin,
and any LAN client could claim any identity it liked.

HTTP Basic is used deliberately. The browser prompts and caches on its own, so
the UI needs no login page or cookie handling, and a worker authenticates with
one `auth=` argument. The Basic *username* is the component name, which makes
identity binding literal: the name the server trusts is the one whose secret
just verified.

Fail-closed startup
-------------------

`HUB_CREDENTIALS` is required. If it is missing or malformed the module raises
at import and uvicorn exits, so the hub does not come back up unauthenticated.
That direction matters: a hub that silently restarted open would look identical
to a healthy one in the UI, and the whole point of this change is that it is no
longer possible to reach it without a credential.

Dependencies
------------

The container installs exactly `fastapi uvicorn pydantic` at start and there is
no image build, so everything here is those three plus the standard library.
Adding an import outside that set means the hub does not survive a restart.
"""

import base64
import hmac
import html
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB_PATH = "/data/chat.db"

# Persisted under /data, which is the bind-mounted volume, so a pause survives
# a container restart. A pause that forgot itself on restart would be worse
# than none: the operator would believe the swarm was held when it was not.
PAUSE_PATH = Path("/data/control_pause.json")


def _load_credentials() -> Dict[str, str]:
    """Parse HUB_CREDENTIALS into {component: secret}, or refuse to start.

    Format is `name:secret,name:secret`. Read from the environment only --
    there is deliberately no file fallback, so a credential cannot be left
    sitting next to hub.py in appdata where a copy or a backup would spread it.

    Every failure path raises. None of the messages contains a secret: this
    text reaches the container log, and a credential in a log has to be treated
    as exposed and rotated.
    """
    raw = os.environ.get("HUB_CREDENTIALS", "").strip()

    if not raw:
        raise RuntimeError(
            "HUB_CREDENTIALS is not set. The hub refuses to start rather than "
            "serve unauthenticated. Set it in the container environment as "
            "'name:secret,name:secret'."
        )

    credentials: Dict[str, str] = {}

    for entry in raw.split(","):
        entry = entry.strip()

        if not entry:
            continue

        name, separator, secret = entry.partition(":")
        name = name.strip().lower()
        secret = secret.strip()

        if not separator or not name or not secret:
            raise RuntimeError(
                "HUB_CREDENTIALS entry is malformed; expected "
                "'name:secret' pairs separated by commas. The offending "
                "value is not repeated here on purpose."
            )

        credentials[name] = secret

    if not credentials:
        raise RuntimeError("HUB_CREDENTIALS parsed to no usable entries.")

    return credentials


CREDENTIALS = _load_credentials()

# Components allowed to change control state. Everyone else may read status.
ADMIN_COMPONENTS = {"admin", "operator"}

# Compared against when the component name is unknown, so an unknown name and a
# wrong secret take the same path and cost roughly the same time. Without it,
# an unknown name returns before any comparison and the difference is
# measurable, which turns the endpoint into an oracle for valid component names.
_DUMMY_SECRET = "x" * 32

# docs_url/redoc_url/openapi_url are disabled rather than protected. They were
# three unauthenticated routes handing the full API surface to any LAN caller,
# and nothing operational reads them -- removing them is a smaller change than
# authenticating them and leaves less to get wrong.
app = FastAPI(
    title="Agent Swarm Hub",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_UNAUTHENTICATED = HTTPException(
    status_code=401,
    detail="authentication required",
    headers={"WWW-Authenticate": 'Basic realm="Agent Swarm Hub"'},
)


def authenticate(request: Request) -> str:
    """Return the authenticated component name, or raise 401.

    This is the only place an identity is established. Every route depends on
    it, and no route reads an identity from a request body.
    """
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")

    if scheme.lower() != "basic" or not encoded:
        raise _UNAUTHENTICATED

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except Exception:
        # Any malformed credential is one failure with one message. Saying
        # which part was wrong would help an attacker more than an operator.
        raise _UNAUTHENTICATED

    name, separator, secret = decoded.partition(":")

    if not separator:
        raise _UNAUTHENTICATED

    name = name.strip().lower()
    expected = CREDENTIALS.get(name)

    # Always compare, even when the name is unknown, and always with
    # compare_digest rather than ==, which short-circuits on the first
    # differing byte.
    matched = hmac.compare_digest(
        secret, expected if expected is not None else _DUMMY_SECRET
    )

    if expected is None or not matched:
        raise _UNAUTHENTICATED

    return name


def require_admin(component: str = Depends(authenticate)) -> str:
    """Authenticated *and* permitted to change control state."""
    if component not in ADMIN_COMPONENTS:
        raise HTTPException(
            status_code=403,
            detail="this component may not change control state",
        )

    return component

class Message(BaseModel):
    id: int
    sender: str
    target: str
    content: str
    # Unix seconds, as it has always been stored. Kept, and kept first: every
    # existing reader parses this field, and a rename would have been a
    # migration of every client to gain nothing the new field does not give.
    timestamp: Optional[float] = None
    # The same instant, written so it cannot be misread: `2026-09-10T17:42:07Z`.
    # A float is unambiguous to a machine and unreadable to a person, and the
    # rendering of it was being done independently by the browser, by each
    # worker's transcript builder, and by anybody reading a log -- three
    # chances to disagree about what timezone a number meant. This is the
    # answer, computed once, on the machine that assigned it.
    timestamp_utc: str


# Rows predating the timestamp column, or written by a client that sent none,
# have NULL. There are not many and they are old, but they must render: a
# transcript that drops its earliest messages loses exactly the context a
# handoff is read for.
UNKNOWN_TIME = "unknown"


def iso_utc(value) -> str:
    """One stored timestamp as ISO-8601 UTC, or a word saying it is not known.

    Never guesses. A NULL timestamp rendered as the epoch would put 1970 in
    the transcript and read as a real time somebody could reason about; a
    NULL rendered as "now" would be worse still. `unknown` is the honest
    answer and is visibly not a date.
    """
    if value is None:
        return UNKNOWN_TIME

    try:
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return UNKNOWN_TIME

    # `Z`, not `+00:00`. Both are valid ISO-8601 and every consumer understands
    # Z; the offset form is the one that gets truncated to a local-looking
    # string by something downstream.
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

class SendRequest(BaseModel):
    # `sender` and `token` are still accepted so existing clients do not start
    # getting 422s, and both are ignored. `sender` is now derived from the
    # credential, and `token` never authenticated anything: it was accepted on
    # write and never returned by GET /messages, so no reader could check it.
    sender: Optional[str] = None
    target: str
    content: str
    token: Optional[str] = None

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/messages/high-water")
def messages_high_water(component: str = Depends(authenticate)):
    """The highest committed message id, as a start fence (#113).

    An id, not a timestamp. `send_message` stamps `time.time()` before it
    opens the database, so concurrent sends can commit out of timestamp order,
    and "the newest message before T0" can sit above a later-stamped handoff
    that committed first. SQLite assigns the id at insert under the write lock
    it holds until commit, so ids become visible in commit order: every
    message committed after this read has a higher id. 0 for an empty room.
    """
    with get_db() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()

    return {"high_water": int(row[0])}


@app.get("/messages", response_model=List[Message])
def get_messages(since_id: int = 0, component: str = Depends(authenticate)):
    # Ordered by time, then by id. The id alone was very nearly right -- it is
    # monotonic and it is what `since_id` pages through -- but it is the order
    # rows were *written*, and a transcript is read as the order things were
    # *said*. Those agree until they do not.
    #
    # The tie-break is the point, not decoration. Several messages routinely
    # share a timestamp: time.time() has coarser resolution than the hub can
    # accept posts at, and a burst of agent replies lands inside one tick.
    # Ordering by timestamp alone would leave those rows in whatever order
    # SQLite found convenient, which is stable until an index changes and then
    # silently is not -- so a conversation would reorder itself between two
    # reads with nothing having changed.
    #
    # COALESCE, because NULL sorts before everything in SQLite. Untimestamped
    # historical rows are old, so sorting them first is very nearly right by
    # accident; saying so explicitly means it stays right on purpose.
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, sender, target, content, timestamp FROM messages "
            "WHERE id > ? ORDER BY COALESCE(timestamp, 0) ASC, id ASC",
            (since_id,)
        ).fetchall()

    return [
        {**dict(row), "timestamp_utc": iso_utc(row["timestamp"])}
        for row in rows
    ]

@app.post("/send")
def send_message(req: SendRequest, component: str = Depends(authenticate)):
    now = time.time()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (sender, target, content, timestamp) VALUES (?, ?, ?, ?)",
            # `component`, not `req.sender`. This is the identity binding: the
            # stored sender is the name whose secret just verified, so a client
            # cannot post as somebody else however it fills in the body.
            (component, req.target, req.content, now)
        )
        conn.commit()
        msg_id = cur.lastrowid

    # Chat-command ingress. After the message is stored, never instead of it,
    # and only for admin senders: a worker's message is never parsed, and the
    # reply is posted as `controller`, which is not an admin, so a reply can
    # never be read as a command.
    if component in ADMIN_COMPONENTS:
        reply = _ingress_reply(component, req.content)

        if reply:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO messages (sender, target, content, timestamp) VALUES (?, ?, ?, ?)",
                    (controller_ingress.REPLY_SENDER, "@Admin", reply, time.time()),
                )
                conn.commit()

    return {"status": "ok", "id": msg_id}


def _ingress_reply(component: str, content: str) -> Optional[str]:
    """What the controller answers to a command, or None for ordinary chat.

    Configuration is read per message, like the progression routes read theirs,
    so a changed `hub.env` takes effect on the next recreate without a code path
    that caches a stale map. Any failure becomes a reply rather than a 500: the
    message is already stored, and the operator needs to see why nothing happened.
    """
    try:
        projects = controller_ingress.parse_projects(os.environ.get("INGRESS_PROJECTS", ""))
        routing = controller_progression.Routing(
            verifier=os.environ.get("PROGRESSION_VERIFIER", ""),
            integrator=os.environ.get("PROGRESSION_INTEGRATOR", ""),
            host=os.environ.get("PROGRESSION_HOST", ""),
            repo_location=os.environ.get("PROGRESSION_REPO_LOCATION", ""),
        )
        conn = controller_db.open_controller_db(CONTROLLER_DB, same_thread_only=False)
        try:
            return controller_ingress.handle_message(
                conn, sender=component, content=content, projects=projects, routing=routing,
            )
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 -- reported to the operator, not swallowed
        return f"Not accepted: the controller could not process this command ({type(exc).__name__}: {exc})"

class PauseRequest(BaseModel):
    reason: Optional[str] = None


def _read_pause() -> Optional[dict]:
    """The current pause record, or None when running.

    An unreadable or corrupt pause file is reported as an engaged pause rather
    than ignored. The asymmetry is deliberate and matches the worker-side flag:
    a spurious pause costs a delay, a missed one lets work start that an
    operator believed was held.
    """
    try:
        if not PAUSE_PATH.exists():
            return None

        return json.loads(PAUSE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "reason": "pause file unreadable ({0}); failing closed".format(exc),
            "engaged_by": "unknown",
            "engaged_at": None,
        }


@app.get("/control/status")
def control_status(component: str = Depends(authenticate)):
    """Readable by any authenticated component, changeable by none of them."""
    pause = _read_pause()

    return {
        "paused": pause is not None,
        "pause": pause,
        "you": component,
        "components": sorted(CREDENTIALS),
        "authenticated": True,
        "server_time": time.time(),
    }


@app.post("/control/pause")
def control_pause(req: PauseRequest, component: str = Depends(require_admin)):
    record = {
        "reason": req.reason or "paused by operator",
        "engaged_by": component,
        "engaged_at": time.time(),
    }
    PAUSE_PATH.write_text(json.dumps(record), encoding="utf-8")

    return {"status": "ok", "paused": True, "pause": record}


@app.post("/control/resume")
def control_resume(component: str = Depends(require_admin)):
    PAUSE_PATH.unlink(missing_ok=True)

    return {"status": "ok", "paused": False}


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Swarm Live Terminal</title>
  <style>
    :root {
      --bg: #0f1117;
      --card: #1a1d26;
      --border: #2e3440;
      --text: #c0caf5;
      --gemini: #7aa2f7;
      --claude: #f7768e;
      --admin: #9ece6a;
      --chatgpt: #bb9af7;
      --claude-lead: #ff9e64;
      --codex-lead: #2ac3de;
    }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: Consolas, monospace;
      margin: 0;
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    header {
      padding: 1rem 1.5rem;
      background: var(--card);
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #chat-log {
      flex: 1;
      overflow-y: auto;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .msg {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 1rem;
      max-width: 90%;
      box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .meta {
      display: flex;
      gap: 0.75rem;
      font-size: 0.85rem;
      margin-bottom: 0.5rem;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      padding-bottom: 0.25rem;
    }
    .sender-Gemini { color: var(--gemini); font-weight: bold; }
    .sender-ClaudeCode { color: var(--claude); font-weight: bold; }
    .sender-Admin { color: var(--admin); font-weight: bold; }
    .sender-ChatGPT { color: var(--chatgpt); font-weight: bold; }
    /* Senders are stored lowercase (the credential's name), so these are
       the classes that actually match. The interactive leads (#109) get
       their own colours, distinct from the background workers. */
    .sender-gemini { color: var(--gemini); font-weight: bold; }
    .sender-claudecode { color: var(--claude); font-weight: bold; }
    .sender-admin { color: var(--admin); font-weight: bold; }
    .sender-chatgpt { color: var(--chatgpt); font-weight: bold; }
    .sender-claude-lead { color: var(--claude-lead); font-weight: bold; }
    .sender-codex-lead { color: var(--codex-lead); font-weight: bold; }
    .target { color: #565f89; }
    /* The UTC instant is on the title attribute, so the exact value the
       server assigned is one hover away without every line carrying two
       renderings of the same moment. */
    .when { color: #565f89; cursor: help; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.4;
      font-family: inherit;
    }
    footer {
      padding: 1rem 1.5rem;
      background: var(--card);
      border-top: 1px solid var(--border);
      display: flex;
      gap: 0.5rem;
    }
    #prompt {
      flex: 1;
      background: #131620;
      border: 1px solid var(--border);
      color: #fff;
      padding: 0.6rem 1rem;
      font-family: inherit;
      font-size: inherit;
      line-height: 1.4;
      border-radius: 4px;
      resize: vertical;
      min-height: 2.6rem;
    }
    button {
      background: #7aa2f7;
      color: #0f1117;
      border: none;
      padding: 0.6rem 1.2rem;
      font-weight: bold;
      cursor: pointer;
      border-radius: 4px;
    }
    button:hover { background: #89ddff; }
    /* The dashboard (#1737): the chat keeps the left, the panel the right,
       and on a narrow screen the panel goes under the chat instead. */
    #layout { flex: 1; display: flex; min-height: 0; }
    #chat-log { min-width: 0; }
    #panel {
      width: 400px; flex-shrink: 0; border-left: 1px solid var(--border);
      background: #131620; display: flex; flex-direction: column; min-height: 0;
    }
    #panel.hidden { display: none; }
    #tabs { display: flex; flex-wrap: wrap; gap: 0.25rem; padding: 0.5rem; border-bottom: 1px solid var(--border); }
    #tabs button { background: var(--card); color: var(--text); padding: 0.35rem 0.6rem; font-weight: normal; }
    #tabs button.active { background: #7aa2f7; color: #0f1117; font-weight: bold; }
    #tab-body { overflow-y: auto; padding: 0.75rem; font-size: 0.85rem; line-height: 1.45; }
    #tab-body h3 { margin: 0.75rem 0 0.35rem; font-size: 0.9rem; color: #7aa2f7; }
    #tab-body h3:first-child { margin-top: 0; }
    .row { display: flex; justify-content: space-between; gap: 0.5rem; }
    .muted { color: #565f89; }
    .warn { color: #e0af68; }
    .bad { color: #f7768e; }
    .ok { color: #9ece6a; }
    .bar { height: 6px; background: var(--border); border-radius: 3px; margin: 0.15rem 0 0.5rem; }
    .bar > div { height: 100%; border-radius: 3px; background: #7aa2f7; }
    .bar > div.full { background: #f7768e; }
    .task { border-left: 2px solid var(--border); padding: 0.2rem 0 0.2rem 0.5rem; margin: 0.3rem 0; }
    .task.sub { margin-left: 1rem; }
    .badge { font-size: 0.75rem; padding: 0 0.35rem; border-radius: 3px; border: 1px solid var(--border); }
    .s-in_progress { color: #7aa2f7; } .s-review { color: #bb9af7; } .s-blocked { color: #f7768e; }
    .s-todo { color: #565f89; } .s-done { color: #9ece6a; } .s-dropped { color: #565f89; text-decoration: line-through; }
    #tab-body a { color: #7dcfff; }
    #toggle-panel { padding: 0.3rem 0.7rem; font-size: 0.8rem; }
    @media (max-width: 900px) {
      #layout { flex-direction: column; }
      #panel { width: auto; max-height: 45vh; border-left: none; border-top: 1px solid var(--border); }
      header { flex-wrap: wrap; gap: 0.5rem; padding: 0.75rem 1rem; }
      header > div { min-width: 0; overflow-wrap: anywhere; }
      #chat-log { padding: 0.75rem 1rem; }
    }
  </style>
</head>
<body>
  <header>
    <div><strong>Autonomous Swarm Hub</strong> <span id="build-id" style="color: #565f89; font-size: 0.85rem;">build __BUILD_ID__</span> | Live Feed</div>
    <div style="display: flex; gap: 1rem; align-items: center;">
      <div id="status" style="color: #9ece6a; font-size: 0.85rem;">● Connected</div>
      <button id="toggle-panel" onclick="togglePanel()">Dashboard</button>
    </div>
  </header>

  <main id="layout">
    <div id="chat-log"></div>
    <aside id="panel">
      <nav id="tabs">
        <button data-tab="relay" onclick="showTab('relay')">Relay</button>
        <button data-tab="projects" onclick="showTab('projects')">Projects</button>
        <button data-tab="tasks" onclick="showTab('tasks')">Tasks</button>
        <button data-tab="completed" onclick="showTab('completed')">Completed</button>
        <button data-tab="stats" onclick="showTab('stats')">Stats</button>
      </nav>
      <div id="tab-body" class="muted">Loading…</div>
    </aside>
  </main>

  <footer>
    <!-- A textarea, not an input: a command puts each field on its own line,
         and an <input> drops line breaks. Enter sends; Shift+Enter is a new line. -->
    <textarea id="prompt" rows="3" placeholder="Message, or a command such as @swarm <title> (Shift+Enter for a new line)" onkeydown="promptKey(event)"></textarea>
    <button onclick="sendMsg()">Send</button>
  </footer>

  <script>
    let lastId = 0;
    const log = document.getElementById('chat-log');

    // The full local date, the time, and the zone it is in -- never the time
    // of day on its own. This page is left open across days and read after
    // the fact during a handoff, and "11:42:07" in a scrollback is a claim
    // about a day nobody can recover. The zone is shown because the reader is
    // not always in the same one as the machine that assigned the timestamp,
    // and a bare local time silently asserts they are.
    //
    // Converted in the browser from the server's instant. The server does not
    // know where it is being read, so it says UTC and the viewer's own
    // timezone database does the rest -- which is also what makes daylight
    // saving correct for historical messages: the conversion applies the rule
    // that was in force at that instant, not the one in force now.
    function localTime(msg) {
      if (msg.timestamp_utc === 'unknown' || !msg.timestamp_utc) {
        return 'time unknown';
      }

      const when = new Date(msg.timestamp_utc);

      if (isNaN(when.getTime())) return 'time unknown';

      // Fixed field order rather than a locale format: the log is read
      // alongside ISO timestamps from the API and the transcripts, and
      // year-month-day next to those does not require re-reading. The clock
      // stays local-conventional, because that is the half a person checks
      // against their own watch.
      const date = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
      const clock = when.toLocaleTimeString(undefined, { hour12: true });
      const zone = zoneName(when);

      return `${date} ${clock} ${zone}`;
    }

    function pad(n) { return String(n).padStart(2, '0'); }

    // The short zone abbreviation, e.g. MDT. Falls back to the IANA name and
    // then to the UTC offset: every browser can produce one of the three, and
    // a message with no zone at all is the ambiguity this set out to remove.
    function zoneName(when) {
      try {
        const parts = new Intl.DateTimeFormat(undefined, {
          timeZoneName: 'short'
        }).formatToParts(when);
        const named = parts.find(p => p.type === 'timeZoneName');
        if (named && named.value) return named.value;
      } catch (err) { /* fall through */ }

      try {
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (zone) return zone;
      } catch (err) { /* fall through */ }

      const offset = -when.getTimezoneOffset();
      const sign = offset < 0 ? '-' : '+';
      const abs = Math.abs(offset);

      return `UTC${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
    }

    async function fetchMessages() {
      try {
        const res = await fetch(`/messages?since_id=${lastId}`);
        const data = await res.json();
        for (const msg of data) {
          if (msg.id > lastId) lastId = msg.id;
          const el = document.createElement('div');
          el.className = 'msg';
          // sender and target are escaped for the same reason content always
          // was: they are stored strings that arrive from the network. Before
          // authentication any LAN caller could choose them freely, so a
          // sender of `<img src=x onerror=...>` ran script in the browser of
          // anyone watching this page. Authentication narrows who can plant
          // that; escaping is what stops it rendering.
          const senderText = escapeHtml(String(msg.sender));
          const targetText = escapeHtml(String(msg.target));
          // The class name is built from a strict allowlist rather than
          // escaped. Escaping is right for text, but a class attribute is not
          // text, and stripping to [A-Za-z0-9_-] means nothing can terminate
          // the attribute no matter what it contains.
          const senderClass = String(msg.sender).replace(/[^A-Za-z0-9_-]/g, '');
          el.innerHTML = `
            <div class="meta">
              <span class="sender-${senderClass}">${senderText}</span>
              <span class="target">&#10142; ${targetText}</span>
              <span class="when" title="${escapeHtml(String(msg.timestamp_utc))}">${escapeHtml(localTime(msg))}</span>
              <span style="margin-left: auto; color: #565f89;">#${escapeHtml(String(msg.id))}</span>
            </div>
            <pre>${escapeHtml(msg.content)}</pre>
          `;
          log.appendChild(el);
          log.scrollTop = log.scrollHeight;
        }
      } catch (err) {
        console.error(err);
      }
    }

    // Enter sends; Shift+Enter inserts a line break. Skipped while an input
    // method is composing, so Enter that confirms an IME candidate does not send.
    function promptKey(event) {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMsg();
      }
    }

    async function sendMsg() {
      const input = document.getElementById('prompt');
      const val = input.value.trim();
      if (!val) return;
      input.value = '';

      // Determine target from the text, matching @Agent tag if present
      let target = '@ClaudeCode';
      if (val.startsWith('@')) {
        const firstToken = val.split(/\\s+/)[0];
        target = firstToken;
      }

      // No `sender` field. The server derives it from the credential this
      // request is authenticated with and ignores anything sent here, so
      // claiming to be Admin would be both pointless and misleading.
      await fetch('/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          target: target,
          content: val
        })
      });
      fetchMessages();
    }

    function escapeHtml(str) {
      return str.replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
      );
    }

    // Identity comes from the server, not from anything this page decided.
    // Worth showing: now that the sender is derived from the credential, the
    // operator needs to see which component they are posting as.
    async function showIdentity() {
      try {
        const res = await fetch('/control/status');
        const s = await res.json();
        const el = document.getElementById('status');
        el.textContent = s.paused
          ? '● PAUSED — ' + s.you
          : '● Connected as ' + s.you;
        el.style.color = s.paused ? '#f7768e' : '#9ece6a';
      } catch (err) {
        console.error(err);
      }
    }

    // --- Dashboard (#1737) -----------------------------------------------
    // Read-only: the relay pushes its snapshot, the leads keep the board.
    // Every stored string is escaped, and a link becomes an anchor only when
    // it is plainly http(s), so a stored value can never become script.
    let currentTab = 'relay';
    let boardData = null;
    let relayData = null;
    // When each answer arrived here, and why the latest refresh failed. A
    // cached answer keeps ageing on this clock, so a hub this browser can no
    // longer reach never shows old health as current (Codex, #128 at a236d22).
    let boardFetchedAt = null, relayFetchedAt = null;
    let boardError = null, relayError = null;

    function sinceFetch(at) { return at === null ? 0 : Math.max(0, (Date.now() - at) / 1000); }

    // The relay report's real age: its age at the hub plus how long ago we heard.
    function relayAge() { return relayData.age_seconds + sinceFetch(relayFetchedAt); }

    // Stale is about the relay's report: its age alone. A failed refresh is
    // about this browser's view of the hub, and is reported as that.
    function relayStale() {
      const limit = relayData.stale_after_seconds || 120;
      return relayData.stale || relayAge() > limit;
    }

    function refreshLine(error, fetchedAt) {
      return error === null ? ''
        : `<div class="bad">Refresh failed (${esc(error)}); showing data fetched ${esc(ago(sinceFetch(fetchedAt)))}.</div>`;
    }
    try { currentTab = localStorage.getItem('hub-tab') || 'relay'; } catch (err) { /* private mode */ }
    try {
      if (localStorage.getItem('hub-panel') === 'hidden') {
        document.getElementById('panel').classList.add('hidden');
      }
    } catch (err) { /* private mode */ }

    function togglePanel() {
      const panel = document.getElementById('panel');
      panel.classList.toggle('hidden');
      try { localStorage.setItem('hub-panel', panel.classList.contains('hidden') ? 'hidden' : 'shown'); } catch (err) { /* ignore */ }
    }

    function showTab(name) {
      currentTab = name;
      try { localStorage.setItem('hub-tab', name); } catch (err) { /* ignore */ }
      renderPanel();
    }

    function esc(value) { return escapeHtml(String(value === null || value === undefined ? '' : value)); }

    function linkHtml(link) {
      if (!link) return '';
      const text = esc(link.length > 60 ? link.slice(0, 57) + '...' : link);
      return /^https?:[/][/]/i.test(link)
        ? ` <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${text}</a>`
        : ` <span class="muted">${text}</span>`;
    }

    // Red only for a limit that has been reached, never for a full chart bar.
    function bar(used, cap, isLimit = true) {
      const pct = cap ? Math.min(100, Math.round(100 * used / cap)) : 0;
      return `<div class="bar"><div class="${isLimit && used >= cap ? 'full' : ''}" style="width:${pct}%"></div></div>`;
    }

    function ago(seconds) {
      if (seconds < 90) return Math.round(seconds) + ' s ago';
      if (seconds < 5400) return Math.round(seconds / 60) + ' min ago';
      return (seconds / 3600).toFixed(1) + ' h ago';
    }

    function when(epoch) {
      return epoch ? localTime({ timestamp_utc: new Date(epoch * 1000).toISOString() }) : '';
    }

    function renderRelay() {
      if (!relayData) {
        return relayError === null ? '<span class="muted">Loading…</span>'
          : `<span class="bad">Relay status unavailable (${esc(relayError)}).</span>`;
      }
      if (!relayData.available) return refreshLine(relayError, relayFetchedAt) + `<span class="warn">${esc(relayData.reason)}</span>`;
      const s = relayData.snapshot;
      const caps = s.caps || {};
      const stale = relayStale();
      let out = refreshLine(relayError, relayFetchedAt);
      out += `<div class="row"><span>Last report</span><span class="${stale ? 'bad' : 'ok'}">`
        + `${esc(ago(relayAge()))}${stale ? ' — STALE, relay may be down' : ''}</span></div>`;
      // "running" is a claim about now: a stale report or a failed refresh never makes it.
      const state = s.paused ? '<span class="bad">paused</span>'
        : stale || relayError !== null ? '<span class="warn">unknown</span>' : '<span class="ok">running</span>';
      out += `<div class="row"><span>Relay</span><span>${state}`
        + ` <span class="muted">pid ${esc(s.owner_pid)}</span></span></div>`;
      out += `<div class="row"><span>Lead↔lead chain</span><span>${esc(s.chain)} / ${esc(caps.chain)}</span></div>`
        + bar(s.chain, caps.chain)
        + '<div class="muted">An admin message resets the chain.</div>';
      for (const [lead, l] of Object.entries(s.leads || {})) {
        out += `<h3>${esc(lead)}</h3>`;
        out += `<div class="row"><span>Binding</span><span>${l.session ? esc(l.session) + '…' : '<span class="muted">unregistered</span>'}`
          + ` ${l.session ? (l.enabled ? '<span class="ok">enabled</span>' : '<span class="warn">disabled</span>') : ''}</span></div>`;
        out += `<div class="row"><span>Launches this hour</span><span>${esc(l.launches_hour)} / ${esc(caps.launches_per_hour)}</span></div>`
          + bar(l.launches_hour, caps.launches_per_hour);
        out += `<div class="row"><span>Launches today (24 h)</span><span>${esc(l.launches_day)} / ${esc(caps.launches_per_day)}</span></div>`
          + bar(l.launches_day, caps.launches_per_day);
        const held = Object.entries(l.held || {});
        out += `<div class="row"><span>Held</span><span>${held.length ? held.map(([r, n]) => esc(n) + ' ' + esc(r)).join(', ') : '0'}</span></div>`;
        out += `<div class="row"><span>Active</span><span>${(l.active || []).length ? l.active.map(a => '#' + esc(a.message_id) + ' ' + esc(a.state)).join(', ') : 'none'}</span></div>`;
      }
      return out + '<p class="muted">Launches count headless starts only; notices to an open chat are free.</p>';
    }

    function taskLine(t, byId) {
      const parent = t.parent_id && byId[t.parent_id];
      return `<div class="task ${parent ? 'sub' : ''}"><div class="row"><span>#${esc(t.id)} ${esc(t.title)}</span>`
        + `<span class="badge s-${esc(t.status).replace(/[^a-z_]/g, '')}">${esc(t.status)}</span></div>`
        + `<div class="muted">${t.owner ? esc(t.owner) : 'unassigned'}${linkHtml(t.link)}</div>`
        + (t.note ? `<div class="muted">${esc(t.note)}</div>` : '') + '</div>';
    }

    function renderProjects() {
      if (!boardData) return '<span class="muted">Loading…</span>';
      if (!boardData.projects.length) return '<span class="muted">No projects on the board yet.</span>';
      const stats = boardData.stats.projects;
      let out = '';
      for (const p of boardData.projects) {
        const st = stats[p.key] || { open: 0, counts: {}, percent_done: null };
        const working = boardData.tasks.filter(t => t.project === p.key && ['in_progress', 'review', 'blocked'].includes(t.status));
        out += `<h3>${esc(p.title)} <span class="muted">${esc(p.repo || '')}</span></h3>`;
        out += `<div class="row"><span>${st.percent_done === null ? 'no tasks yet' : esc(st.percent_done) + '% done'}</span>`
          + `<span>${esc(st.open)} open · ${esc(st.counts.done || 0)} done</span></div>`
          + bar(st.percent_done || 0, 100, false);
        out += working.length
          ? working.map(t => `<div>${esc(t.owner || 'unassigned')}: ${esc(t.title)} <span class="s-${esc(t.status)}">${esc(t.status)}</span></div>`).join('')
          : '<div class="muted">Nobody is actively on this project.</div>';
      }
      return out;
    }

    function renderTasks() {
      if (!boardData) return '<span class="muted">Loading…</span>';
      const byId = Object.fromEntries(boardData.tasks.map(t => [t.id, t]));
      const open = boardData.tasks.filter(t => !['done', 'dropped'].includes(t.status));
      if (!open.length) return '<span class="muted">No open tasks.</span>';
      let out = '';
      for (const p of boardData.projects) {
        const mine = open.filter(t => t.project === p.key);
        if (mine.length) out += `<h3>${esc(p.title)}</h3>` + mine.map(t => taskLine(t, byId)).join('');
      }
      return out;
    }

    function renderCompleted() {
      if (!boardData) return '<span class="muted">Loading…</span>';
      const done = boardData.tasks.filter(t => t.status === 'done').sort((a, b) => b.completed_at - a.completed_at);
      if (!done.length) return '<span class="muted">Nothing completed on the board yet.</span>';
      return done.map(t => `<div class="task"><div class="row"><span>${esc(t.title)}</span><span class="muted">${esc(t.project)}</span></div>`
        + `<div class="muted">${esc(when(t.completed_at))} · ${esc(t.owner || 'unassigned')}${linkHtml(t.link)}</div></div>`).join('');
    }

    function renderStats() {
      if (!boardData) return '<span class="muted">Loading…</span>';
      const s = boardData.stats;
      let out = `<div class="row"><span>Open tasks</span><span>${esc(s.open_tasks)}</span></div>`;
      out += `<div class="row"><span>Completed per day (last ${esc(s.rate_window_days)} days)</span><span>${esc(s.completion_rate_per_day)}</span></div>`;
      out += `<div class="row"><span>Projected days to clear (estimate)</span><span>${s.estimate_days_remaining === null ? '<span class="muted">no recent rate</span>' : esc(s.estimate_days_remaining)}</span></div>`;
      out += '<h3>Completions by day (UTC)</h3>';
      const days = Object.entries(s.completed_per_day_utc);
      const peak = Math.max(1, ...days.map(([, n]) => n));
      out += days.length ? days.map(([d, n]) => `<div class="row"><span>${esc(d)}</span><span>${esc(n)}</span></div>` + bar(n, peak, false)).join('')
        : '<div class="muted">None in the window.</div>';
      out += '<h3>Per project</h3>';
      for (const [key, p] of Object.entries(s.projects)) {
        out += `<div class="row"><span>${esc(key)}</span><span>${esc(p.open)} open · `
          + `${p.estimate_days_remaining === null ? 'no estimate' : '~' + esc(p.estimate_days_remaining) + ' days'}</span></div>`;
      }
      return out + `<p class="muted">${esc(s.estimate_note)}</p>`;
    }

    function renderPanel() {
      for (const b of document.querySelectorAll('#tabs button')) {
        b.classList.toggle('active', b.dataset.tab === currentTab);
      }
      const render = { relay: renderRelay, projects: renderProjects, tasks: renderTasks,
                       completed: renderCompleted, stats: renderStats }[currentTab] || renderRelay;
      const body = document.getElementById('tab-body');
      body.className = '';
      // Board tabs say how old the board is, and why it is old if a refresh failed.
      const boardStatus = currentTab === 'relay' ? ''
        : boardError !== null ? refreshLine(boardError, boardFetchedAt)
        : boardFetchedAt !== null ? `<div class="muted">Board updated ${esc(ago(sinceFetch(boardFetchedAt)))}.</div>` : '';
      body.innerHTML = boardStatus + render();
    }

    // One source at a time: a failure keeps the last answer, records why,
    // and is rendered, never swallowed.
    async function refresh(url, apply) {
      try {
        const res = await fetch(url);
        if (!res.ok) return `HTTP ${res.status}`;
        apply(await res.json());
        return null;
      } catch (err) {
        return 'hub unreachable';
      }
    }

    async function fetchDashboard() {
      const [b, r] = await Promise.all([
        refresh('/board', data => { boardData = data; boardFetchedAt = Date.now(); }),
        refresh('/relay/status', data => { relayData = data; relayFetchedAt = Date.now(); }),
      ]);
      boardError = b;
      relayError = r;
      renderPanel();
    }

    setInterval(fetchMessages, 2000);
    setInterval(showIdentity, 10000);
    setInterval(fetchDashboard, 10000);
    fetchMessages();
    showIdentity();
    fetchDashboard();
  </script>
</body>
</html>
"""

# --- Controller ---------------------------------------------------------------
#
# The controller's routes are mounted onto this same app, sharing this file's
# authentication and this process. Two reasons it is not a second service:
# there is exactly one writer to the controller database, which is what makes
# its transactions safe without a lock manager, and the components already
# have credentials here.
#
# Imported at module scope with no try/except, deliberately. If the package is
# not importable the container fails to start and the log names the import
# error, which is the same fail-closed behaviour as a missing HUB_CREDENTIALS.
# A hub that silently came up serving chat with no controller would look
# healthy while every worker poll found nothing to do, and that is a much
# harder failure to diagnose than one that never started.
#
# This import is why the container bind-mounts the application *directory*
# rather than hub.py alone.
from controller import api as controller_api  # noqa: E402
from controller import board as controller_board  # noqa: E402
from controller import build as controller_build  # noqa: E402
from controller import db as controller_db  # noqa: E402
from controller import ingress as controller_ingress  # noqa: E402
from controller import progression as controller_progression  # noqa: E402

CONTROLLER_DB = os.environ.get("CONTROLLER_DB", "/data/controller.db")

# Created at import rather than on first request: a request that has to decide
# whether to create the schema is a request that can race another one doing the
# same.
controller_api.ensure_database(CONTROLLER_DB)

app.include_router(
    controller_api.build_router(
        authenticate=authenticate,
        require_admin=require_admin,
        db_path=CONTROLLER_DB,
    )
)

# The leads' work board and the relay snapshot (#1737), in their own database:
# they are records for the page, not controller state.
BOARD_DB = os.environ.get("BOARD_DB", "/data/board.db")
controller_board.ensure_database(BOARD_DB)
app.include_router(controller_board.build_router(authenticate=authenticate, db_path=BOARD_DB))


@app.get("/", response_class=HTMLResponse)
def index(component: str = Depends(authenticate)):
    """The live terminal, behind the same credential as everything else.

    The browser prompts for Basic credentials and caches them, so the page's
    own fetch() calls to /messages and /send authenticate without any login
    form or cookie handling here.

    The header shows the same build id /controller/status reports as
    loaded_build_id, so the page says which build is actually running.
    """
    build_id = html.escape(controller_build.loaded()["build_id"])

    return HTML_TEMPLATE.replace("__BUILD_ID__", build_id)
