"""Check the two loop-breaking guards without touching the hub or any API.

1. ``claude_worker.ERROR_ENVELOPE_RE`` -- peer error envelopes are dropped,
   real tasks that merely quote one still run.
2. ``gemini_worker.generate_reply`` -- an SDK failure or an empty candidate
   returns None (logged locally) instead of a string that would be posted.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claude_worker as cw
import gemini_worker as gw

failures = []


def check(label, actual, expected):
    ok = actual == expected
    if not ok:
        failures.append(label)
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {actual!r}")


# --- 1. claude_worker: error envelopes are not tasks ----------------------

dropped = [
    "[Gemini worker: generation failed: 404 model not found]",
    "[ChatGPT worker: model returned an empty reply]",
    "  [gemini worker: rate limited]",  # leading space, lowercase
    "[Claude worker : timed out]",  # space before the colon
]
for text in dropped:
    check(f"dropped {text[:40]!r}", bool(cw.ERROR_ENVELOPE_RE.match(text.lstrip())), True)

kept = [
    "Investigate why [Gemini worker: generation failed] keeps appearing.",
    "[task 45 exit=0]\nHere is the result.",
    "Please restart the gemini worker.",
    "[note] worker: check this",  # 'worker:' outside the bracket
]
for text in kept:
    check(f"kept    {text[:40]!r}", bool(cw.ERROR_ENVELOPE_RE.match(text.lstrip())), False)


# --- 2. gemini_worker: failures stay in the log --------------------------

class BoomModels:
    def generate_content(self, **_kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


class EmptyModels:
    def generate_content(self, **_kwargs):
        return type("R", (), {"text": None})()


class OkModels:
    def generate_content(self, **_kwargs):
        return type("R", (), {"text": "  a real answer  "})()


class Client:
    def __init__(self, models):
        self.models = models


class Types:
    @staticmethod
    def GenerateContentConfig(**_kwargs):
        return None


context = [{"sender": "ChatGPT", "target": "@Gemini", "content": "ping"}]

logging.disable(logging.CRITICAL)  # the error path logs on purpose; keep output clean
check("API failure -> None", gw.generate_reply(Client(BoomModels()), Types, context), None)
check("empty candidate -> None", gw.generate_reply(Client(EmptyModels()), Types, context), None)
check("good reply passes through", gw.generate_reply(Client(OkModels()), Types, context), "a real answer")
logging.disable(logging.NOTSET)

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
