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
import json
import os
import sqlite3
import time
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
    timestamp: float

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

@app.get("/messages", response_model=List[Message])
def get_messages(since_id: int = 0, component: str = Depends(authenticate)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, sender, target, content, timestamp FROM messages WHERE id > ? ORDER BY id ASC",
            (since_id,)
        ).fetchall()
    return [dict(row) for row in rows]

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
    return {"status": "ok", "id": msg_id}

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
    .target { color: #565f89; }
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
    input {
      flex: 1;
      background: #131620;
      border: 1px solid var(--border);
      color: #fff;
      padding: 0.6rem 1rem;
      font-family: inherit;
      border-radius: 4px;
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
  </style>
</head>
<body>
  <header>
    <div><strong>Autonomous Swarm Hub</strong> | Live Feed</div>
    <div id="status" style="color: #9ece6a; font-size: 0.85rem;">● Connected</div>
  </header>
  
  <div id="chat-log"></div>

  <footer>
    <input id="prompt" placeholder="Directive (e.g. @ClaudeCode or @ChatGPT)..." onkeydown="if(event.key==='Enter') sendMsg()"/>
    <button onclick="sendMsg()">Send</button>
  </footer>

  <script>
    let lastId = 0;
    const log = document.getElementById('chat-log');

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

    setInterval(fetchMessages, 2000);
    setInterval(showIdentity, 10000);
    fetchMessages();
    showIdentity();
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index(component: str = Depends(authenticate)):
    """The live terminal, behind the same credential as everything else.

    The browser prompts for Basic credentials and caches them, so the page's
    own fetch() calls to /messages and /send authenticate without any login
    form or cookie handling here.
    """
    return HTML_TEMPLATE
