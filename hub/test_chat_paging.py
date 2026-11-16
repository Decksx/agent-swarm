"""The chat page opens on recent messages, not the whole history.

At message 5,555 the hub answered the full history in about 10 ms, but the page
appended every message to the log one at a time and scrolled after each, so the
browser laid the log out once per message ever posted. Opening the page got
slower with every message, though the data was small and the server was fast.

The page now asks for the newest page of messages, renders each batch in one
insertion, and fetches older pages only when asked. The API change is optional
parameters: a caller that sends neither gets exactly the answer it always got,
which is what every worker, the relay and lead_chat rely on.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_PATH = Path(__file__).resolve().parent / "hub.py"
REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SECRET = "s" * 32
AUTH = ("admin", SECRET)
T0 = 1789062127.0


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_CREDENTIALS", f"admin:{SECRET}")
    monkeypatch.setenv("CONTROLLER_DB", str(tmp_path / "controller.db"))
    monkeypatch.setenv("BOARD_DB", str(tmp_path / "board.db"))
    db = tmp_path / "chat.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "sender TEXT, target TEXT, content TEXT, timestamp REAL)"
    )
    conn.commit()
    conn.close()
    spec = importlib.util.spec_from_file_location("hub_paging", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hub_paging"] = module
    spec.loader.exec_module(module)
    module.DB_PATH = str(db)
    module._db = db
    return module


def store(hub, timestamps):
    conn = sqlite3.connect(hub._db)
    for n, ts in enumerate(timestamps, 1):
        conn.execute(
            "INSERT INTO messages (sender, target, content, timestamp) VALUES (?, ?, ?, ?)",
            ("gemini", "@Admin", f"m{n}", ts),
        )
    conn.commit()
    conn.close()


def ids(hub, query=""):
    with TestClient(hub.app) as client:
        response = client.get("/messages" + query, auth=AUTH)
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


# --- The API: optional, and invisible to callers that do not use it ---------


def test_without_the_new_parameters_the_answer_is_unchanged(hub):
    store(hub, [T0 + n for n in range(10)])
    assert ids(hub) == list(range(1, 11))
    assert ids(hub, "?since_id=7") == [8, 9, 10]


def test_limit_returns_the_newest_messages_oldest_first(hub):
    store(hub, [T0 + n for n in range(10)])
    assert ids(hub, "?limit=3") == [8, 9, 10]
    assert ids(hub, "?since_id=2&limit=3") == [8, 9, 10]
    assert ids(hub, "?since_id=8&limit=5") == [9, 10]


def test_newest_means_by_id_and_the_page_is_still_shown_in_time_order(hub):
    """A message can commit after one stamped later (#113). The page is chosen
    by id, the order since_id pages through, and read in the order said."""
    store(hub, [T0, T0 + 1, T0 + 5, T0 + 3])
    assert ids(hub, "?limit=2") == [4, 3]
    assert ids(hub, "?before_id=3&limit=5") == [1, 2]


def test_before_id_pages_back_through_everything_exactly_once(hub):
    store(hub, [T0 + n for n in range(23)])
    seen, before = [], None
    while True:
        page = ids(hub, "?limit=5" + (f"&before_id={before}" if before else ""))
        if not page:
            break
        seen = page + seen
        before = min(page)
    assert seen == list(range(1, 24))


def test_the_limit_is_clamped(hub, monkeypatch):
    store(hub, [T0 + n for n in range(10)])
    monkeypatch.setattr(hub, "MAX_PAGE", 4)
    assert ids(hub, "?limit=0") == [10]
    assert ids(hub, "?limit=-3") == [10]
    assert ids(hub, "?limit=999") == [7, 8, 9, 10]


# --- The page's own script, against a fake DOM -------------------------------

HARNESS = r"""
let appends = 0, scrolls = 0, inserts = [];
function node(tag) {
  const n = { tag, children: [], className: '', textContent: '', innerHTML: '', style: {}, onclick: null,
    appendChild(c) { if (c.frag) this.children.push(...c.children); else this.children.push(c); return c; },
    remove() { chatLog.children = chatLog.children.filter(c => c !== this); } };
  Object.defineProperty(n, 'nextSibling', { get() {
    const i = chatLog.children.indexOf(n); return i < 0 ? null : (chatLog.children[i + 1] || null); } });
  return n;
}
const chatLog = node('div');
chatLog.appendChild = c => { appends++; if (c.frag) chatLog.children.push(...c.children); else chatLog.children.push(c); return c; };
chatLog.insertBefore = (c, ref) => {
  const items = c.frag ? c.children : [c];
  const at = ref ? chatLog.children.indexOf(ref) : chatLog.children.length;
  chatLog.children.splice(at < 0 ? chatLog.children.length : at, 0, ...items);
  inserts.push(items.length);
  return c;
};
Object.defineProperty(chatLog, 'firstChild', { get: () => chatLog.children[0] || null });
chatLog.clientHeight = 500;
Object.defineProperty(chatLog, 'scrollHeight', { get: () => chatLog.children.length * 100 });
let top = 0;
Object.defineProperty(chatLog, 'scrollTop', { get: () => top, set: v => { top = v; scrolls++; } });
const other = {};
globalThis.document = {
  getElementById: id => id === 'chat-log' ? chatLog : (other[id] || (other[id] = node(id))),
  querySelectorAll: () => [],
  createElement: tag => node(tag),
  createDocumentFragment: () => { const f = node('#frag'); f.frag = true; return f; },
};
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.setInterval = () => 0;
let rows = [];                  // the chat database
const calls = [];
let gate = null;                // when set, /messages answers wait on it
globalThis.fetch = async (url) => {
  if (!url.startsWith('/messages')) return { ok: true, status: 200, json: async () => ({}) };
  calls.push(url);
  if (gate) await gate;
  const q = new URLSearchParams(url.split('?')[1] || '');
  const since = +(q.get('since_id') || 0), before = q.get('before_id'), limit = q.get('limit');
  let out = rows.filter(r => r.id > since && (before === null || r.id < +before));
  // Like the real endpoint: the newest `limit` by id, answered in
  // COALESCE(timestamp, 0), id order.
  out.sort((a, b) => a.id - b.id);
  if (limit !== null) out = out.slice(-limit);
  out.sort((a, b) => ((a.timestamp || 0) - (b.timestamp || 0)) || (a.id - b.id));
  return { ok: true, status: 200, json: async () => out };
};
const msg = (id, timestamp = 0) => ({ id, sender: 'gemini', target: '@Admin', content: 'm' + id, timestamp, timestamp_utc: 'unknown' });
const shownIds = () => chatLog.children.filter(c => c.className === 'msg').map(c => +c.innerHTML.match(/>#(\d+)</)[1]);
const tick = () => new Promise(r => setTimeout(r, 0));
const shown = () => chatLog.children.filter(c => c.className === 'msg').length;
const button = () => chatLog.children.find(c => c.className === 'older');
"""

SCENARIO = r"""
const out = {};
(async () => {
  for (let i = 1; i <= 650; i++) rows.push(msg(i));
  await fetchMessages();                     // the page's first load
  out.first_call = calls[0];
  out.first_shown = shown();
  out.first_appends = appends;
  out.first_scrolls = scrolls;
  out.button = !!button() && chatLog.children[0] === button();

  // A reader scrolled up is not pulled down by a new message.
  rows.push(msg(651));
  top = 0; scrolls = 0;
  await fetchMessages();
  out.new_shown = shown();
  out.scrolled_up_scrolls = scrolls;
  out.poll_call = calls[calls.length - 1];

  // A reader at the bottom follows new messages.
  rows.push(msg(652));
  top = chatLog.scrollHeight - chatLog.clientHeight; scrolls = 0;
  await fetchMessages();
  out.at_bottom_scrolls = scrolls;

  // A poll while one is in flight neither fetches twice nor appends twice;
  // it runs once the first finishes.
  rows.push(msg(653));
  let open; gate = new Promise(r => { open = r; });
  const before = calls.length;
  const p1 = fetchMessages(); await tick();
  fetchMessages(); fetchMessages(); await tick();
  out.inflight_calls = calls.length - before;
  gate = null; open(); await p1; await tick(); await tick();
  out.after_inflight_calls = calls.length - before;
  out.after_inflight_shown = shown();

  // Older pages arrive above, oldest first, and the button goes when done.
  top = 1000; const fromBottom = chatLog.scrollHeight - top;
  await loadOlder();
  out.place_kept = chatLog.scrollHeight - top === fromBottom && top > 1000;
  out.older_call = calls[calls.length - 1];
  out.older_shown = shown();
  out.older_order = chatLog.children.filter(c => c.className === 'msg').slice(0, 2).map(c => c.innerHTML.match(/>#(\d+)</)[1]);
  out.button_after_one = !!button();
  await loadOlder();
  out.all_shown = shown();
  out.button_at_end = !!button();
  const n = calls.length; await loadOlder(); out.no_more_calls = calls.length - n;
  out.ids_unique = new Set(chatLog.children.filter(c => c.className === 'msg').map(c => c.innerHTML.match(/>#(\d+)</)[1])).size;
  console.log(JSON.stringify(out));
})();
"""

SMALL = r"""
(async () => {
  for (let i = 1; i <= 12; i++) rows.push(msg(i));
  await fetchMessages();
  console.log(JSON.stringify({ shown: shown(), button: !!button() }));
})();
"""

# Ids 1-650 with timestamp 1000 + id, except the rows named in `skew`, which
# get the given timestamp (null for a historical row). The page opens on
# #351-#650 and loads #51-#350, then #1-#50, as older pages. After every load
# the shown rows must be in the order the whole history would be shown in.
SKEW = r"""
(async () => {
  const skew = __SKEW__;
  for (let i = 1; i <= 650; i++) rows.push(msg(i, i in skew ? skew[i] : 1000 + i));
  const order = ids => ids.slice().sort((a, b) =>
    ((rows[a - 1].timestamp || 0) - (rows[b - 1].timestamp || 0)) || (a - b));
  const out = { loads: [] };
  await fetchMessages();
  out.loads.push(shownIds());
  inserts = [];
  await loadOlder();
  out.loads.push(shownIds());
  out.inserts_first_older = inserts.slice();
  await loadOlder();
  out.loads.push(shownIds());
  out.sorted = out.loads.map(ids => JSON.stringify(ids) === JSON.stringify(order(ids)));
  out.final = shownIds();
  out.expected_final = order(rows.map(r => r.id));
  out.button_at_end = !!button();
  console.log(JSON.stringify(out));
})();
"""


def _skew(skew: dict) -> str:
    return SKEW.replace("__SKEW__", json.dumps({str(k): v for k, v in skew.items()}))


def _page_script(hub) -> str:
    page = hub.HTML_TEMPLATE
    script = page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]
    # Drop the page's own start-up calls; each scenario drives the page itself.
    return script[:script.rindex("    setInterval(fetchMessages")]


def run(hub, tmp_path, scenario):
    program = tmp_path / "chat.js"
    program.write_text(HARNESS + _page_script(hub) + scenario, encoding="utf-8")
    result = subprocess.run(["node", str(program)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "Error" not in result.stderr, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_the_page_opens_on_one_page_added_in_one_insertion(hub, tmp_path):
    out = run(hub, tmp_path, SCENARIO)
    assert out["first_call"] == "/messages?limit=300"
    assert out["first_shown"] == 300
    assert out["first_appends"] == 1, "one insertion for the whole page, not one per message"
    assert out["first_scrolls"] == 1
    assert out["button"], "an 'older' button sits at the top when there is more"


@needs_node
def test_new_messages_follow_only_a_reader_at_the_bottom(hub, tmp_path):
    out = run(hub, tmp_path, SCENARIO)
    assert out["poll_call"] == "/messages?since_id=650"
    assert out["new_shown"] == 301
    assert out["scrolled_up_scrolls"] == 0
    assert out["at_bottom_scrolls"] == 1


@needs_node
def test_a_poll_never_overlaps_another(hub, tmp_path):
    out = run(hub, tmp_path, SCENARIO)
    assert out["inflight_calls"] == 1
    assert out["after_inflight_calls"] == 2, "the waiting call runs once, afterwards"
    assert out["after_inflight_shown"] == 303


@needs_node
def test_older_pages_load_above_until_the_history_is_complete(hub, tmp_path):
    out = run(hub, tmp_path, SCENARIO)
    assert out["older_call"] == "/messages?before_id=351&limit=300"
    assert out["older_shown"] == 603
    assert out["older_order"] == ["51", "52"]
    assert out["place_kept"], "the reader stays on what they were reading"
    assert out["button_after_one"]
    assert out["all_shown"] == 653 and out["ids_unique"] == 653
    assert not out["button_at_end"]
    assert out["no_more_calls"] == 0


@needs_node
def test_an_older_row_with_a_later_timestamp_is_merged_not_stacked(hub, tmp_path):
    # #350 is on the older page by id but was said after everything shown, so
    # it belongs at the bottom, not directly above #351 (Codex's #229 witness).
    out = run(hub, tmp_path, _skew({350: 10000}))
    assert all(out["sorted"]), out["sorted"]
    assert out["final"] == out["expected_final"]
    assert out["final"][-1] == 350
    assert out["final"].index(349) + 1 == out["final"].index(351)
    assert len(out["inserts_first_older"]) == 2, "one insertion per gap, not one per row"
    assert not out["button_at_end"]


@needs_node
def test_a_shown_row_without_a_timestamp_stays_above_older_timed_rows(hub, tmp_path):
    # #351 opens the first page but has no timestamp, which sorts as 0: once
    # the older pages arrive, every timed row belongs below it.
    out = run(hub, tmp_path, _skew({351: None}))
    assert all(out["sorted"]), out["sorted"]
    assert out["final"] == out["expected_final"]
    assert out["final"][0] == 351


@needs_node
def test_an_older_row_without_a_timestamp_goes_to_the_top(hub, tmp_path):
    out = run(hub, tmp_path, _skew({200: None, 40: None}))
    assert all(out["sorted"]), out["sorted"]
    assert out["final"] == out["expected_final"]
    assert out["final"][:2] == [40, 200]


@needs_node
def test_a_short_history_has_no_older_button(hub, tmp_path):
    out = run(hub, tmp_path, SMALL)
    assert out == {"shown": 12, "button": False}
