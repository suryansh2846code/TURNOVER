"""What a tool gives back: the text a model reads, and whether it worked.

The loop used to decide that a tool had failed by matching the start of its
output against a list of prefixes. It was wrong in both directions, and the
directions mattered:

    web_search failed: boom          -> read as success
    Gmail not connected: no creds    -> read as success
    Tool budget …                    -> read as failure

So the three failures that actually happen — a connector that is down, a search
that threw, a sync that errored — all looked fine, and the model re-issued the
same broken call, got the memo's cached answer with a "you already ran this"
note, and burned the stall counter instead of trying something else.

Whether a call worked is a fact the tool knows and nothing downstream can
recover. So it is carried rather than guessed.

**A `str` subclass, deliberately.** Every tool in the app returns a string,
every call site treats the result as one, and the model only ever sees the text.
Subclassing keeps all of that true — a tool that has not been taught about this
keeps working, and `run_tool` keeps its contract — while the loop gets a field
to read instead of a prefix to match. That is the "additive first" rule from
`/CLAUDE.md` applied to a return type.
"""
from __future__ import annotations


class ToolResult(str):
    """A tool's output, plus what the loop needs to know about it."""

    #: Did the call do what it was asked? False means the model should try
    #: something else rather than repeat it.
    ok: bool
    #: Was the output cut down to fit? The model is told, so it can narrow its
    #: question instead of assuming it saw everything.
    truncated: bool

    def __new__(cls, text: object = "", *, ok: bool = True,
                truncated: bool = False) -> ToolResult:
        self = super().__new__(cls, "" if text is None else str(text))
        self.ok = ok
        self.truncated = truncated
        return self

    @classmethod
    def failed(cls, text: object) -> ToolResult:
        """A call that did not do what it was asked."""
        return cls(text, ok=False)

    def but(self, text: object) -> ToolResult:
        """The same verdict, different text — for annotating an output.

        Used where the loop appends a note to a result it is handing back, so
        that adding the note does not quietly turn a failure into a success.
        """
        return ToolResult(text, ok=self.ok, truncated=self.truncated)


def worked(output: object) -> bool:
    """Did this output come from a call that worked?

    Anything that is not a `ToolResult` is taken at face value as success —
    a plain string is what a tool returned before this existed, and guessing
    about it is the thing being removed.
    """
    return bool(getattr(output, "ok", True))
