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


class ChatImageIn(BaseModel):
    """One attached image on its way in from the browser.

    `name` is the original filename where there was one — a pasted image has
    none. It is shown back to the user and never sent to a provider.
    """

    #: A little over the base64 cap in models.images, leaving room for the
    #: `data:image/jpeg;base64,` prefix itself.
    data_url: str = Field(max_length=7 * 1024 * 1024 + 1024)
    name: str = Field(default="", max_length=200)


class ChatIn(BaseModel):
    """A message plus the model the client wants it answered with.

    The provider/model are chosen client-side and stored in localStorage, so any
    endpoint that calls an LLM for the UI accepts them and falls back to
    `settings.model_provider`.
    """

    message: str = Field(max_length=24000)   # guardrail against runaway input
    provider: str | None = None
    model: str | None = None
    #: Images attached to this turn, as `data:image/...;base64,...` URLs. The
    #: length cap is on the FIELD so pydantic rejects an oversized payload
    #: before anything decodes it; the media type, the count and the real size
    #: are checked by `models.images`, which is the one place that knows what
    #: a provider will actually take.
    images: list[ChatImageIn] = Field(default_factory=list)
    #: "low" | "medium" | "high". Absent means the level saved on this machine.
    #: An unknown value falls back rather than failing — it arrives from a
    #: client's localStorage, which can outlive a rename.
    effort: str | None = None
    #: A name the CLIENT chose for this turn, so it can stop it later. Chosen
    #: client-side because a turn is cancellable from the moment the user can
    #: see a Stop button, and an id handed back by the server would leave a
    #: window at the start of exactly the slowest turns. Absent means the turn
    #: cannot be stopped, which is what an internal caller gets.
    turn_id: str | None = Field(default=None, max_length=128)


class SecretIn(BaseModel):
    """A single credential value. Empty means *forget the one I saved*."""

    value: str = ""
