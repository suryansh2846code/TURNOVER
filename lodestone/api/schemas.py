"""Request bodies that more than one router accepts.

Most request models belong beside the single route that takes them. These two
do not: `ChatIn` carries the client's provider/model choice, which the UI sends
to every endpoint that calls a model on the user's behalf, and `SecretIn` is the
one-field shape for saving a credential — whether that credential belongs to a
connector or to a model provider.

Keeping the shared ones here is what stops them being redefined per router and
drifting: a second `ChatIn` that forgot `max_length` would silently reopen the
runaway-input guard on whichever endpoints used the copy.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    """A message plus the model the client wants it answered with.

    The provider/model are chosen client-side and stored in localStorage, so any
    endpoint that calls an LLM for the UI accepts them and falls back to
    `settings.model_provider`.
    """

    message: str = Field(max_length=24000)   # guardrail against runaway input
    provider: str | None = None
    model: str | None = None
    #: "low" | "medium" | "high". Absent means the level saved on this machine.
    #: An unknown value falls back rather than failing — it arrives from a
    #: client's localStorage, which can outlive a rename.
    effort: str | None = None


class SecretIn(BaseModel):
    """A single credential value. Empty means *forget the one I saved*."""

    value: str = ""
