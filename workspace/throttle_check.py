"""Exercise the gemini worker's loop brakes without touching hub or API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gemini_worker as gw

failures = []


def check(label, actual, expected_throttled):
    got = actual is not None
    status = "ok  " if got == expected_throttled else "FAIL"
    if got != expected_throttled:
        failures.append(label)
    print(f"{status} {label}: {actual or 'answered'}")


# 1. A human is never throttled, no matter how fast they talk.
gw._last_reply_at.clear()
gw._recent_replies.clear()
for i in range(30):
    gw.record_reply("Admin", 1000.0 + i)
check("Admin burst of 30", gw.throttle_reason("@Admin", 1030.0), False)

# 2. An agent gets one reply, then is held off for the cooldown.
gw._last_reply_at.clear()
gw._recent_replies.clear()
check("ChatGPT first message", gw.throttle_reason("ChatGPT", 1000.0), False)
gw.record_reply("ChatGPT", 1000.0)
check("ChatGPT +5s (ping-pong)", gw.throttle_reason("ChatGPT", 1005.0), True)
check("ChatGPT +59s", gw.throttle_reason("ChatGPT", 1059.0), True)
check("ChatGPT +60s (cooldown up)", gw.throttle_reason("ChatGPT", 1060.0), False)

# 3. '@'-prefixed and odd-cased handles are the same peer.
gw._last_reply_at.clear()
gw._recent_replies.clear()
gw.record_reply("claudecode", 1000.0)
check("@ClaudeCode aliases claudecode", gw.throttle_reason("@ClaudeCode", 1005.0), True)

# 4. Peers each under their own cooldown still trip the swarm-wide cap.
#    Two peers interleaved: each waits out its own 60s cooldown, so the
#    worker still emits a reply every ~30s -- exactly the case the
#    per-sender cooldown alone cannot catch.
gw._last_reply_at.clear()
gw._recent_replies.clear()
now = 1000.0
spacing = gw.REPLY_COOLDOWN_SECONDS / 2
for i in range(gw.MAX_REPLIES_PER_WINDOW):
    peer = "ChatGPT" if i % 2 else "ClaudeCode"
    gw.record_reply(peer, now + i * spacing)
tripped = now + gw.MAX_REPLIES_PER_WINDOW * spacing

# Ask as the peer whose own cooldown has just expired, so a refusal here can
# only be the burst cap and not the cooldown branch again.
reason = gw.throttle_reason("ClaudeCode", tripped)
check("cap tripped across peers", reason, True)
if reason is not None and "burst cap" not in reason:
    failures.append("cap tripped for the wrong reason")
    print("FAIL cap refusal came from the cooldown, not the burst cap")
check("human still answered while capped", gw.throttle_reason("Admin", tripped), False)
check(
    "cap released after window drains",
    gw.throttle_reason("ChatGPT", tripped + gw.REPLY_WINDOW_SECONDS),
    False,
)

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
