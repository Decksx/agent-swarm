import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Agent Swarm Hub")

class Message(BaseModel):
    id: int
    sender: str
    target: str
    content: str
    timestamp: float

class SendRequest(BaseModel):
    sender: str
    target: str
    content: str
    token: Optional[str] = None

# In-memory message store with initial seed
messages: List[Message] = []
msg_counter = 0

def add_message(sender: str, target: str, content: str) -> Message:
    global msg_counter
    msg_counter += 1
    msg = Message(
        id=msg_counter,
        sender=sender,
        target=target,
        content=content,
        timestamp=time.time()
    )
    messages.append(msg)
    return msg

@app.get("/messages", response_model=List[Message])
def get_messages(since_id: int = 0):
    return [m for m in messages if m.id > since_id]

@app.post("/send")
def send_message(req: SendRequest):
    msg = add_message(req.sender, req.target, req.content)
    return {"status": "ok", "id": msg.id}

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
    <div id="status" style="color: #9ece6a; font-size: 0.85rem;">● Polling</div>
  </header>
  
  <div id="chat-log"></div>

  <footer>
    <input id="prompt" placeholder="Send directive to @Gemini..." onkeydown="if(event.key==='Enter') sendMsg()"/>
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
          el.innerHTML = `
            <div class="meta">
              <span class="sender-${msg.sender}">${msg.sender}</span>
              <span class="target">&#10142; ${msg.target}</span>
              <span style="margin-left: auto; color: #565f89;">#${msg.id}</span>
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

      await fetch('/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          sender: 'Admin',
          target: '@Gemini',
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

    setInterval(fetchMessages, 2000);
    fetchMessages();
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_TEMPLATE
