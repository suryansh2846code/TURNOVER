"""Images the user attaches to a turn, and the one place that says no.

`Message.content` is a string and every provider serialises it differently, so
an image cannot just be appended to the text. This module is the seam:

* `ImageInput` is the one shape an image has once it is inside Lodestone —
  a media type and raw base64, never a `data:` URL. A data URL is a *wire*
  format; carrying it around means every consumer re-parses it and one of them
  eventually forgets to validate.
* `parse_data_url` is the only door in, and it validates before decoding
  rather than after: the size cap has to be enforced on what arrived, not on
  what it expands to.
* `refusal_for` is the one place that decides an image cannot be sent, so the
  answer is the same whether the turn came from chat, a routine or a stream.

**Why a refusal rather than an exception.** The caller is a model loop and the
reader is a person. A model that cannot see gets told which of *their* models
can, because "this model does not support images" with no way forward is the
kind of dead end the product rules here exist to prevent.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass

from ..log import get_logger

log = get_logger(__name__)

#: What every vision model in the catalog actually accepts. Deliberately not
#: "anything image/*": SVG is a script vector, and TIFF/BMP are accepted by
#: nobody we talk to, so allowing them only moves the failure to the provider.
SUPPORTED_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

#: Per image, measured on the BASE64, which is what the request actually
#: carries. Anthropic rejects images over ~5MB decoded; 7MB of base64 is
#: ~5.25MB decoded, so this refuses just before they do, with a better message.
MAX_BASE64_BYTES = 7 * 1024 * 1024

#: Four is what fits in a composer row and well inside every provider's limit.
MAX_IMAGES = 4

_DATA_URL = re.compile(r"^data:(?P<mt>[a-zA-Z0-9.+/-]+);base64,(?P<data>.+)$", re.S)


class ImageError(ValueError):
    """The attachment cannot be used, with a reason a person can act on."""


@dataclass(frozen=True)
class ImageInput:
    """One attached image, normalised. `data` is base64 with no URL prefix."""

    media_type: str
    data: str
    #: Original filename when there was one — a paste has none. Shown to the
    #: user, never sent to a provider.
    name: str = ""

    def as_data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.data}"

    @property
    def approx_bytes(self) -> int:
        return (len(self.data) * 3) // 4


def parse_data_url(url: str, *, name: str = "") -> ImageInput:
    """Turn one `data:image/...;base64,...` URL into an `ImageInput`.

    Raises `ImageError` with a message meant for the user.
    """
    if not isinstance(url, str) or not url.startswith("data:"):
        raise ImageError("That attachment isn't an image Lodestone can read.")
    m = _DATA_URL.match(url.strip())
    if not m:
        raise ImageError("That image is in a format Lodestone can't read.")

    media_type = m.group("mt").lower()
    if media_type not in SUPPORTED_MEDIA_TYPES:
        pretty = media_type.split("/")[-1].upper()
        raise ImageError(
            f"{pretty} images aren't supported. Use PNG, JPEG, GIF or WebP.")

    data = m.group("data").strip()
    # Check the size BEFORE decoding: decoding first is how a size guard turns
    # into the thing it was meant to guard against.
    if len(data) > MAX_BASE64_BYTES:
        raise ImageError(
            f"That image is too large. Images need to be under "
            f"{MAX_BASE64_BYTES // (1024 * 1024)}MB.")
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageError("That image looks corrupted — try attaching it again.") from exc

    return ImageInput(media_type=media_type, data=data, name=name)


def parse_many(urls: list, *, names: list | None = None) -> list[ImageInput]:
    """Parse a whole attachment set, refusing the set before any of it."""
    if not urls:
        return []
    if len(urls) > MAX_IMAGES:
        raise ImageError(f"Up to {MAX_IMAGES} images at a time.")
    names = names or []
    return [parse_data_url(u, name=(names[i] if i < len(names) else ""))
            for i, u in enumerate(urls)]


def _model_sees_images(provider_name: str, model: str | None) -> bool | None:
    """Does this model report vision? `None` means we could not find out.

    Unknown is not the same as no. Discovery can fail, and refusing the user's
    image because a network call timed out would be inventing a limitation.
    """
    if not model:
        return None
    try:
        from .discovery import get_discovered_models
        models, _meta = get_discovered_models(provider_name)
    except Exception:
        log.debug("vision lookup failed for %s/%s", provider_name, model)
        return None
    for m in models:
        if m.get("id") == model or m.get("name") == model:
            return bool(m.get("vision"))
    return None


def _vision_alternatives(provider_name: str, limit: int = 3) -> list[str]:
    """Models on THIS provider that this user can actually run and that see."""
    try:
        from .discovery import get_discovered_models
        models, _meta = get_discovered_models(provider_name)
    except Exception:
        return []
    out = []
    for m in models:
        if m.get("vision") and not m.get("locked"):
            out.append(str(m.get("name") or m.get("id")))
        if len(out) >= limit:
            break
    return out


def refusal_for(images: list[ImageInput], provider, provider_name: str,
                model: str | None) -> str | None:
    """The reason these images cannot be sent, or `None` if they can.

    Two different noes, because they have different fixes:

    * the **backend** cannot carry an image at all — the vendor CLIs take a
      prompt string on argv, so there is nowhere for one to go. Changing model
      within that provider will not help; the fix is a different provider.
    * the **model** has no vision. Another model on the same provider will do,
      so name the ones this account can actually run.
    """
    if not images:
        return None

    label = getattr(provider, "display_name", None) or provider_name
    if not getattr(provider, "supports_images", False):
        return (f"{label} can't accept images on this connection — it runs "
                f"through a command-line tool that only takes text. "
                f"Switch to a provider with an API key to send images.")

    sees = _model_sees_images(provider_name, model)
    if sees is False:
        alts = _vision_alternatives(provider_name)
        suggestion = (f" Try {', '.join(alts)}." if alts else
                      " Pick a model marked with vision in Model settings.")
        return f"{model} can't read images.{suggestion}"

    # None → discovery could not tell us. Send it and let the provider answer;
    # a real 400 from the vendor is a better error than a guess.
    return None
