"""One error taxonomy for every provider.

Each provider failed differently: some dumped raw JSON at the user, some said
nothing useful, some raised and 500'd the chat. This gives every backend the
same vocabulary and the same rule — **translate, never dump** — so a failure
tells the user what happened and what to do about it.

Classify once at the boundary:

    err = classify_http("openai", resp.status_code, resp.text, model=self.model)
    return ChatResult(text=err.as_reply())
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

MAX_DETAIL = 160


class ErrorKind(str, Enum):
    AUTH = "auth"                       # missing / invalid / expired credential
    BILLING = "billing"                 # out of credits, spending limit, quota
    RATE_LIMIT = "rate_limit"
    MODEL_NOT_FOUND = "model_not_found"  # the id does not exist here
    MODEL_NOT_ENTITLED = "model_not_entitled"  # exists, but not on this plan
    CONTEXT_TOO_LONG = "context_too_long"
    CONTENT_FILTERED = "content_filtered"
    BAD_REQUEST = "bad_request"
    SERVER = "server"
    NETWORK = "network"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


# Kinds worth retrying unchanged; the rest need the user to change something.
_RETRYABLE = {ErrorKind.RATE_LIMIT, ErrorKind.SERVER, ErrorKind.NETWORK, ErrorKind.TIMEOUT}

# Redact anything that looks like a credential before it reaches a UI or a log.
_SECRET = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,}|xai-[A-Za-z0-9_\-]{8,}|"
                     r"AIza[A-Za-z0-9_\-]{20,}|Bearer\s+[A-Za-z0-9._\-]{12,})")


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text or "")


def display_name(provider: str) -> str:
    """The provider's own name, so messages never show a raw internal id."""
    try:
        from .capabilities import get_capabilities

        caps = get_capabilities(provider)
        if caps:
            return caps.display_name
    except Exception:
        pass
    return provider.replace("-", " ").title() if provider.islower() else provider


@dataclass
class ProviderError:
    kind: ErrorKind
    provider: str
    message: str                 # user-facing and actionable
    status: int | None = None
    model: str | None = None
    detail: str = ""             # short, redacted provider detail
    retryable: bool = False

    def as_reply(self) -> str:
        """The string a user sees in the chat transcript."""
        text = f"⚠️ {self.message}"
        if self.detail and self.detail.lower() not in self.message.lower():
            text += f"\n\n_{self.detail}_"
        return text

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "provider": self.provider, "status": self.status,
                "model": self.model, "message": self.message, "detail": self.detail,
                "retryable": self.retryable}


def extract_detail(body: str | None) -> str:
    """Pull the human-readable sentence out of a provider's error body.

    Providers disagree on shape: OpenAI/xAI/DeepSeek use {"error": {...}} or
    {"error": "..."}, Google wraps it in a list, Ollama uses {"error": "..."}.
    Falls back to the raw text, always redacted and truncated.
    """
    if not body:
        return ""
    raw = body.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            err = data.get("error", data)
            if isinstance(err, dict):
                msg = err.get("message") or err.get("error") or err.get("detail") or ""
            else:
                msg = str(err)
            if msg:
                raw = str(msg)
    except (json.JSONDecodeError, TypeError):
        pass
    raw = redact(" ".join(raw.split()))
    return raw[:MAX_DETAIL] + ("…" if len(raw) > MAX_DETAIL else "")


def _kind_from_body(blob: str) -> ErrorKind | None:
    """Some conditions are only distinguishable from the body, not the status."""
    b = blob.lower()
    if any(k in b for k in ("spending-limit", "out of credits", "insufficient balance",
                            "insufficient_quota", "billing", "payment required",
                            "exceeded your current quota")):
        return ErrorKind.BILLING
    if any(k in b for k in ("context length", "context_length_exceeded", "too many tokens",
                            "maximum context", "input is too long", "prompt is too long")):
        return ErrorKind.CONTEXT_TOO_LONG
    if any(k in b for k in ("does not exist", "model not found", "unknown model",
                            "invalid model", "model_not_found", "no such model")):
        return ErrorKind.MODEL_NOT_FOUND
    if any(k in b for k in ("content filter", "content_policy", "safety", "blocked by")):
        return ErrorKind.CONTENT_FILTERED
    if any(k in b for k in ("not allowed", "not entitled", "upgrade your plan",
                            "not supported on your")):
        return ErrorKind.MODEL_NOT_ENTITLED
    return None


def _kind_from_status(status: int) -> ErrorKind:
    if status in (401, 403):
        return ErrorKind.AUTH
    if status == 402:
        return ErrorKind.BILLING
    if status == 404:
        return ErrorKind.MODEL_NOT_FOUND
    if status == 413:
        return ErrorKind.CONTEXT_TOO_LONG
    if status == 429:
        return ErrorKind.RATE_LIMIT
    if status >= 500:
        return ErrorKind.SERVER
    if status >= 400:
        return ErrorKind.BAD_REQUEST
    return ErrorKind.UNKNOWN


def _alternatives(provider: str, model: str | None) -> str:
    """Name a few models this user can actually run, for a model-level failure."""
    try:
        from .discovery import get_discovered_models

        usable = [m["id"] for m in get_discovered_models(provider)[0]
                  if not m.get("locked") and m["id"] != model][:3]
    except Exception:
        return ""
    return f" Available to you: {', '.join(f'`{m}`' for m in usable)}." if usable else ""


def classify_http(provider: str, status: int, body: str | None = None, *,
                  model: str | None = None, key_env: str | None = None) -> ProviderError:
    """Map an HTTP failure onto the shared taxonomy with an actionable message."""
    detail = extract_detail(body)
    kind = _kind_from_body(f"{body or ''} {detail}") or _kind_from_status(status)
    name = display_name(provider)

    # A 401/403 whose body names a billing problem is a billing problem.
    if status in (401, 403) and kind is ErrorKind.AUTH:
        override = _kind_from_body(body or "")
        if override in (ErrorKind.BILLING, ErrorKind.MODEL_NOT_ENTITLED):
            kind = override

    key_hint = f" Check {key_env} in Models & Accounts." if key_env else \
               " Check your credentials in Models & Accounts."

    if kind is ErrorKind.AUTH:
        msg = f"{name} rejected the credential.{key_hint}"
    elif kind is ErrorKind.BILLING:
        msg = (f"{name} refused the request for billing reasons — the account "
               "is out of credits or has hit a spending limit.")
    elif kind is ErrorKind.RATE_LIMIT:
        msg = f"{name} rate-limited you. Wait a moment and try again."
    elif kind is ErrorKind.MODEL_NOT_FOUND:
        msg = (f"`{model}` isn't available on {name}." if model
               else f"{name} doesn't recognise that model.")
        msg += _alternatives(provider, model)
    elif kind is ErrorKind.MODEL_NOT_ENTITLED:
        msg = f"`{model or 'That model'}` isn't included in your {name} plan."
        msg += _alternatives(provider, model)
    elif kind is ErrorKind.CONTEXT_TOO_LONG:
        msg = ("This conversation is too long for the model's context window. "
               "Start a new chat, or switch to a model with a larger window.")
    elif kind is ErrorKind.CONTENT_FILTERED:
        msg = f"{name} declined to answer this request."
    elif kind is ErrorKind.SERVER:
        msg = f"{name} had a server error ({status}). Try again shortly."
    else:
        msg = f"{name} rejected the request ({status})."

    return ProviderError(kind=kind, provider=provider, message=msg, status=status,
                         model=model, detail=detail, retryable=kind in _RETRYABLE)


def classify_exception(provider: str, exc: BaseException, *,
                       model: str | None = None, base_url: str | None = None) -> ProviderError:
    """Map a transport-level failure (no HTTP response) onto the taxonomy."""
    import httpx

    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(ErrorKind.TIMEOUT, provider, model=model, retryable=True,
                             message=f"{display_name(provider)} timed out. Try again, or pick a faster model.")
    where = f" at {base_url}" if base_url else ""
    return ProviderError(ErrorKind.NETWORK, provider, model=model, retryable=True,
                         detail=redact(str(exc))[:MAX_DETAIL],
                         message=f"Can't reach {display_name(provider)}{where}. Check your connection.")


def classify_cli(provider: str, returncode: int, stdout: str, stderr: str, *,
                 model: str | None = None) -> ProviderError:
    """Map a CLI-backed provider's failure onto the same taxonomy."""
    blob = f"{stdout} {stderr}"
    kind = _kind_from_body(blob) or ErrorKind.UNKNOWN
    name = display_name(provider)
    # Don't say "Claude Code CLI CLI" — some display names already end in it.
    cli_name = name if name.lower().endswith("cli") else f"{name} CLI"
    low = blob.lower()
    if kind is ErrorKind.UNKNOWN:
        if any(k in low for k in ("not logged in", "unauthorized", "please log in",
                                  "authentication", "sign in")):
            kind = ErrorKind.AUTH
        elif any(k in low for k in ("issue with the selected model", "does not support")):
            kind = ErrorKind.MODEL_NOT_FOUND

    if kind is ErrorKind.AUTH:
        msg = f"The {cli_name} isn't signed in. Sign in from a terminal, then retry."
    elif kind is ErrorKind.MODEL_NOT_FOUND:
        msg = f"`{model}` isn't available in the {cli_name}." + _alternatives(provider, model)
    elif kind is ErrorKind.BILLING:
        msg = f"Your {name} plan has no remaining quota for this request."
    elif kind is ErrorKind.CONTEXT_TOO_LONG:
        msg = ("This conversation is too long for the model's context window. "
               "Start a new chat, or switch models.")
    else:
        msg = (f"The {cli_name} couldn't answer. Try rephrasing, or switch "
               "model in the sidebar.")

    return ProviderError(kind=kind, provider=provider, message=msg, model=model,
                         status=returncode or None,
                         detail=extract_detail(stderr.strip() or stdout.strip()),
                         retryable=kind in _RETRYABLE)
