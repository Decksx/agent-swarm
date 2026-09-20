"""What a prompt will cost, measured before it is sent (#24).

T-INFRA-11 asked for a change across three writable files with four read-only
context files beside them. `swarm_control.py` alone is about 11.7k tokens; the
whole prompt came to roughly 38k against gpt-4o's 30k-per-minute organisation
limit. OpenAI refused it before generating anything, the worker recorded "the
model returned nothing" (#20), the activation was charged against the author
budget (#21), and the task had to be cancelled and recreated without its
context files.

Everything about that was avoidable at the moment the prompt existed and
nothing had been spent.

Measured, not estimated from its parts
--------------------------------------

The obvious design sums the files that will go into the prompt. This does not:
it takes the rendered prompt, the exact string that would be sent, and
measures that. Summing the parts means re-deriving what `render_author_prompt`
does -- the fixed sections, the contract, the rejection, the operator context
-- and that derivation silently goes wrong the day the prompt's shape changes.
The string cannot.

The contributors are passed in only for attribution: which files to drop. They
are a hint about where the size came from, never the total.

Tokens are estimated, and say so
--------------------------------

`CHARS_PER_TOKEN` is four. That is a heuristic, not a count, and every message
this module produces says "estimated" for that reason. A real tokenizer would
be exact for one provider and wrong for the others, and this runs in front of
OpenAI, Gemini and Claude alike; a dependency that is precise about the wrong
model is worse than an approximation that is honest about being one.

The margin absorbs the error. T-INFRA-11 was ~38k against 30k -- caught by a
wide margin at any plausible chars-per-token. A prompt close enough to the
limit that the heuristic decides it is a prompt that should be smaller anyway.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Four characters to a token, near enough. See the module docstring: this is
# the honest approximation, and nothing here claims otherwise.
CHARS_PER_TOKEN = 4

# gpt-4o's organisation limit at the time T-INFRA-11 hit it. A default, not a
# policy -- the caller passes what its own model allows.
DEFAULT_TOKEN_LIMIT = 30_000

# Warn from here. Below it the prompt is simply fine; above the limit it is
# refused. Between the two an operator gets told, and the run proceeds.
DEFAULT_WARN_FRACTION = 0.8

# How many contributors to name. Enough to act on, few enough to read in a
# chat room, where this ends up via the narrator.
LARGEST_SHOWN = 5


def estimated_tokens(text: str) -> int:
    """Roughly how many tokens `text` is, rounded up.

    Rounded up so that an empty string is 0 and anything at all is at least 1:
    a section that exists should never measure as nothing.
    """
    if not text:
        return 0

    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def measure(
    prompt: str,
    *,
    contributors: Iterable[dict] = (),
    limit: int = DEFAULT_TOKEN_LIMIT,
    warn_fraction: float = DEFAULT_WARN_FRACTION,
) -> dict:
    """`{estimate, limit, over, near, largest}` for a rendered prompt.

    `contributors` are `{"path", "text"}` entries -- the writable files and
    the read-only context the worker already holds. They attribute the size;
    they do not produce it. The estimate is the prompt's own length, so a
    prompt that is large for some reason no file explains is still measured
    correctly and simply has nothing useful to name.

    `over` and `near` are mutually exclusive: a prompt past the limit is over,
    not both. A caller that treated them as independent would report a refusal
    and a warning for the same prompt.
    """
    estimate = estimated_tokens(prompt)
    threshold = int(limit * warn_fraction)

    largest = sorted(
        (
            {"path": entry.get("path", "?"),
             "tokens": estimated_tokens(entry.get("text", ""))}
            for entry in contributors
        ),
        key=lambda entry: entry["tokens"],
        reverse=True,
    )[:LARGEST_SHOWN]

    over = estimate > limit

    return {
        "estimate": estimate,
        "limit": limit,
        "over": over,
        "near": (not over) and estimate >= threshold,
        "largest": [entry for entry in largest if entry["tokens"] > 0],
    }


def _naming(measured: dict) -> str:
    """The contributors, as a phrase, or nothing if there are none to name."""
    largest = measured["largest"]

    if not largest:
        return ""

    listed = ", ".join(
        f"{entry['path']} (~{entry['tokens']:,})" for entry in largest
    )

    return f" The largest inputs are {listed}."


def refusal(measured: dict) -> str:
    """Why this prompt was not sent, for the ledger and the room.

    Written to be acted on. An operator reading it in the chat room -- which
    is where the narrator puts a `reason` -- should know what to drop without
    opening anything, so the files come with their sizes and the numbers come
    with the word "estimated" attached to them.
    """
    return (
        f"the author prompt is an estimated {measured['estimate']:,} tokens, "
        f"over the {measured['limit']:,} configured for this model, so it was "
        f"not sent and no attempt was spent. Remove context files or narrow "
        f"the writable scope and retry.{_naming(measured)} "
        f"(Estimated at {CHARS_PER_TOKEN} characters per token, not counted.)"
    )


def warning(measured: dict) -> str:
    """That this one was close, carried on whatever outcome the run reports.

    Deliberately not an escalation. The run worked; this is a note in the
    ledger and one line in the room, for whoever reads the task next.
    """
    return (
        f"the author prompt was an estimated {measured['estimate']:,} tokens "
        f"against a {measured['limit']:,} limit -- close enough that a little "
        f"more context would have been refused.{_naming(measured)}"
    )


def carried(measured: Optional[dict]) -> dict:
    """The fields to merge into an outcome payload, or nothing.

    Kept here so a caller cannot half-report it: the numbers and the warning
    text travel together or not at all.
    """
    if not measured or not measured["near"]:
        return {}

    return {
        "prompt_tokens_estimated": measured["estimate"],
        "prompt_token_limit": measured["limit"],
        "reason": warning(measured),
    }
