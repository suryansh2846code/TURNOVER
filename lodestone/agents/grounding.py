"""The date we hand the model, and getting it back out of what it says.

`run_turn` states the current date directly in front of the question, because a
small model ignores a mid-context system note and then invents a date. That is
the right call. The cost of it is that a model copies its own input into the
arguments it emits, and the note then stops being a note and starts being data:

* in `search_brain`'s query it reaches `brain.recall`, which runs
  `parse_date_range` over the query, finds the date we just supplied, and
  filters the whole brain down to items dated today. Every question asked on a
  day nothing was ingested answers "nothing in the brain matches that date",
  with only the canonical block — which is always included — left standing. Ask
  an agent who someone is and it replies with the user's weight goal.
* in `remember`'s text it is stored as a fact about the user, permanently.

So the note is written in one place and removed in one place. Anything this
layer adds to the model's input is this layer's to take back out before it
reaches a tool that would read it as data.
"""
from __future__ import annotations

import re
from typing import Any

#: How the date is stated to the model. `_PREFIX` below has to keep matching
#: whatever this produces — they are one decision written twice, so they live
#: next to each other.
TEMPLATE = "[Today is {date}.]"

#: Anchored to the start, because the start is the only place the note is ours.
#: A bracketed line further into an argument was written by somebody else — the
#: email the agent just read, most likely — and deleting that would be editing
#: the user's own data on a guess.
_PREFIX = re.compile(r"\A\s*\[\s*today is [^\]\n]{0,64}\]\s*", re.I)


def prefixed(date_line: str, text: str) -> str:
    """The user's question with the date stated in front of it."""
    return f"{TEMPLATE.format(date=date_line)}\n{text}"


def strip(text: str) -> str:
    """`text` without the grounding note, if it opens with one."""
    return _PREFIX.sub("", text, count=1)


def strip_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Tool arguments with the grounding note taken out of every string.

    Applied to every tool rather than to `search_brain` alone: the note is
    never meaningful in any argument, and the next tool handed the user's turn
    verbatim should not have to rediscover this one.
    """
    if not isinstance(arguments, dict):
        return arguments
    return {k: strip(v) if isinstance(v, str) else v for k, v in arguments.items()}
