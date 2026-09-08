"""The real model-call path, exercised against fake SDKs.

Why this file exists
--------------------

The containment tests stub ``generate_reply`` and ``run_task``, because what
they assert is whether the boundary is *reached*, not what happens past it.
That is the right shape for those tests and it leaves a hole: nothing in them
executes the real generation code, so a Phase 0 edit could break every reply
and the suite would stay green.

That is not hypothetical. Removing the chat-era constants from
``gemini_worker`` also removed ``SYSTEM_PROMPT``, which ``generate_reply``
still referenced. Every generation would have raised ``NameError``, been caught
by the broad ``except Exception`` that exists so one bad call cannot kill the
daemon, and returned ``None`` -- a worker that started cleanly, logged an error
per attempt and silently never answered. The full pytest suite passed
throughout. ``workspace/guard_check.py`` caught it; these tests make the suite
catch it too.

They also carry forward the assertions ``guard_check.py`` makes about behaviour
that still exists, so the checks survive in a runner rather than only in a
script someone has to remember to run.
"""

from __future__ import annotations

import logging

import pytest

import claude_worker
import gemini_worker


class FakeTypes:
    @staticmethod
    def GenerateContentConfig(**_kwargs):
        return None


def _client(models):
    return type("Client", (), {"models": models})()


CONTEXT = [{"sender": "Admin", "target": "@Gemini", "content": "ping"}]


def test_a_successful_generation_returns_the_text():
    """The happy path actually runs.

    This is the assertion that would have caught the SYSTEM_PROMPT regression:
    any NameError, missing constant or bad SDK argument inside generate_reply
    surfaces here as None instead of the expected string.
    """

    class Ok:
        def generate_content(self, **_kwargs):
            return type("R", (), {"text": "  a real answer  "})()

    assert gemini_worker.generate_reply(_client(Ok()), FakeTypes, CONTEXT) == (
        "a real answer"
    )


def test_generation_uses_the_system_prompt_and_model(monkeypatch):
    """The arguments the SDK is called with are the configured ones.

    Asserting the call arguments, not just that a string came back, is what
    makes a silently-dropped constant visible: a reply can look correct while
    the system prompt has quietly become None.
    """
    seen = {}

    class Recorder:
        def generate_content(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"text": "ok"})()

    class CapturingTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            # A distinct key: generate_content is then called with
            # config=None (this returns None), and seen.update() there would
            # otherwise overwrite what was recorded here.
            seen["config_kwargs"] = kwargs
            return None

    gemini_worker.generate_reply(_client(Recorder()), CapturingTypes, CONTEXT)

    assert seen["model"] == gemini_worker.GEMINI_MODEL
    assert seen["config_kwargs"]["system_instruction"] == gemini_worker.SYSTEM_PROMPT
    assert seen["config_kwargs"]["system_instruction"], "system prompt is empty"
    assert "Admin (to @Gemini): ping" in seen["contents"]


def test_an_sdk_failure_returns_none_and_is_not_posted(caplog):
    """An outage stays in the log rather than becoming hub content.

    Returning the error text would post it as an ordinary reply, and a peer
    reading "[Gemini worker: generation failed: 429]" as content answers it --
    which is how a transient rate limit used to become a conversation.
    """

    class Boom:
        def generate_content(self, **_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with caplog.at_level(logging.ERROR):
        result = gemini_worker.generate_reply(_client(Boom()), FakeTypes, CONTEXT)

    assert result is None
    assert "429" in caplog.text


def test_an_empty_candidate_returns_none():
    """A safety block yields no text; that is silence, not a crash."""

    class Empty:
        def generate_content(self, **_kwargs):
            return type("R", (), {"text": None})()

    assert gemini_worker.generate_reply(_client(Empty()), FakeTypes, CONTEXT) is None


# --- Carried forward from workspace/guard_check.py --------------------------


@pytest.mark.parametrize(
    "text",
    [
        "[Gemini worker: generation failed: 404 model not found]",
        "[ChatGPT worker: model returned an empty reply]",
        "  [gemini worker: rate limited]",
        "[Claude worker : timed out]",
    ],
)
def test_worker_error_envelopes_are_recognised(text):
    """An error envelope is not a task.

    It can no longer arrive from a peer -- peers cannot reach the activation
    path at all -- but it still catches an operator pasting a worker's error
    message back in as one, which is now the only way that text can get there.
    """
    assert claude_worker.ERROR_ENVELOPE_RE.match(text.lstrip())


@pytest.mark.parametrize(
    "text",
    [
        "Investigate why [Gemini worker: generation failed] keeps appearing.",
        "[task 45 exit=0]\nHere is the result.",
        "Please restart the gemini worker.",
        "[note] worker: check this",
    ],
)
def test_real_tasks_that_merely_quote_an_envelope_are_kept(text):
    """Anchored at the start, so quoting an envelope is still a real task."""
    assert not claude_worker.ERROR_ENVELOPE_RE.match(text.lstrip())
