"""Signing in to Telegram, and holding the session afterwards.

Telegram is the one mainstream messenger with a real, public, personal-account
API. The user gets an `api_id` / `api_hash` from my.telegram.org in about a
minute; there have been third-party Telegram clients for a decade and they are
the intended use of it, not a tolerated one. That is why `docs/MESSAGING.md`
puts this first and WhatsApp nowhere.

Two things here are not obvious and both were chosen deliberately.

**One event loop, on one thread, for the whole process.** Telethon is asyncio
and a `TelegramClient` belongs to the loop that created it. The app around it is
FastAPI — sometimes a request thread with no loop, sometimes a worker in a
bounded lane, sometimes the scheduler. `telethon.sync`'s implicit global loop
breaks the moment two of those overlap. So there is exactly one loop, owned by
one daemon thread, and every call is handed to it. The client is created there
and never touched from anywhere else.

**Signing in is three steps and they are three calls.** Phone, then the code
Telegram sends, then a password if the account has two-factor on. The
`phone_code_hash` from step one has to survive into step two, so it is held
here — in memory only. A login code is a credential with a two-minute life; it
is never written to disk and never logged, and neither is the password.

The window and the card that drive this: the frontend lane owns those. What
this module promises them is in `docs/development/telegram.md`.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from ..config import get_settings
from ..log import get_logger, suppressed

log = get_logger(__name__)

#: How long any one Telegram call may take before we give up on it. Generous:
#: the first connection negotiates a new session with a datacentre that may be
#: on the other side of the world.
TIMEOUT_SECONDS = 60

#: Held between `start_login` and `submit_code`. In memory, never on disk — a
#: login code is a credential that expires in about two minutes, and the one
#: place it must not end up is a file we back up.
_pending: dict[str, Any] = {}

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_client: Any = None
_lock = threading.Lock()


# ── the one loop everything runs on ──────────────────────────────────────
def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _lock:
        if _loop is not None and _thread is not None and _thread.is_alive():
            return _loop
        _loop = asyncio.new_event_loop()
        _thread = threading.Thread(target=_loop.run_forever, daemon=True,
                                   name="chitragupta-telegram")
        _thread.start()
        return _loop


def run(coro) -> Any:
    """Run one coroutine on Telegram's loop and wait for it.

    Every entry point goes through this, including from a request thread. A
    caller that is itself async must still reach it from a worker — the bounded
    lanes in `api/` exist for exactly this.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    return future.result(timeout=TIMEOUT_SECONDS)


# ── credentials ──────────────────────────────────────────────────────────
API_ID = "TELEGRAM_API_ID"
API_HASH = "TELEGRAM_API_HASH"

#: Said in three places (the connector, the status endpoint, the agent's tool),
#: so it is written once.
NEEDS_CREDENTIALS = (
    "Telegram needs an API ID and hash of your own. Get them free at "
    "my.telegram.org → API development tools, then add them under Connectors.")
NEEDS_SIGN_IN = "Telegram is set up but not signed in — sign in under Connectors."


def credentials() -> tuple[int, str] | None:
    settings = get_settings()
    raw_id = settings.get_secret(API_ID)
    api_hash = settings.get_secret(API_HASH)
    if not raw_id or not api_hash:
        return None
    with suppressed("reading the stored Telegram API id"):
        return int(str(raw_id).strip()), str(api_hash).strip()
    return None


def save_credentials(api_id: str, api_hash: str) -> dict:
    """Store the user's own Telegram API credentials."""
    cleaned_id = str(api_id or "").strip()
    cleaned_hash = str(api_hash or "").strip()
    if not cleaned_id.isdigit():
        return {"ok": False, "error": "The API ID is the number from "
                                      "my.telegram.org — digits only."}
    if len(cleaned_hash) < 16:
        return {"ok": False, "error": "That does not look like an API hash. "
                                      "Copy the whole value from my.telegram.org."}
    settings = get_settings()
    settings.set_secret(API_ID, cleaned_id)
    settings.set_secret(API_HASH, cleaned_hash)
    return {"ok": True, "detail": "Telegram credentials saved."}


def _session_path() -> str:
    home = get_settings().home
    home.mkdir(parents=True, exist_ok=True)
    # Telethon appends `.session` itself.
    return str(home / "telegram")


# ── the client ───────────────────────────────────────────────────────────
async def _client_on_loop() -> Any:
    """The one client, created on this loop, connected."""
    global _client
    if _client is not None and _client.is_connected():
        return _client

    from telethon import TelegramClient

    creds = credentials()
    if creds is None:
        return None
    api_id, api_hash = creds
    _client = TelegramClient(_session_path(), api_id, api_hash)
    await _client.connect()
    return _client


def client(require_auth: bool = True) -> Any | None:
    """A connected client, or None with the reason available from `status()`."""
    if credentials() is None:
        return None

    async def _get():
        conn = await _client_on_loop()
        if conn is None:
            return None
        if require_auth and not await conn.is_user_authorized():
            return None
        return conn

    with suppressed("connecting to Telegram"):
        return run(_get())
    return None


def status() -> dict:
    """Where the user is in setting Telegram up, in the user's terms."""
    if credentials() is None:
        return {"configured": False, "authorized": False, "account": None,
                "reason": NEEDS_CREDENTIALS}

    async def _check():
        conn = await _client_on_loop()
        if conn is None:
            return None, False
        if not await conn.is_user_authorized():
            return None, False
        me = await conn.get_me()
        name = " ".join(filter(None, [getattr(me, "first_name", ""),
                                      getattr(me, "last_name", "")])).strip()
        handle = getattr(me, "username", "") or getattr(me, "phone", "")
        return (name or handle or "your account"), True

    with suppressed("asking Telegram who is signed in"):
        account, ok = run(_check())
        return {"configured": True, "authorized": ok, "account": account,
                "reason": "" if ok else NEEDS_SIGN_IN}
    return {"configured": True, "authorized": False, "account": None,
            "reason": "Telegram could not be reached just now."}


# ── signing in, in three steps ───────────────────────────────────────────
def start_login(phone: str) -> dict:
    """Ask Telegram to send a login code to this number."""
    number = str(phone or "").strip().replace(" ", "")
    if not number.startswith("+") or len(number) < 7:
        return {"ok": False, "error": "Enter your phone number with the country "
                                      "code, like +441234567890."}
    if credentials() is None:
        return {"ok": False, "error": NEEDS_CREDENTIALS}

    async def _send():
        conn = await _client_on_loop()
        if conn is None:
            return {"ok": False, "error": NEEDS_CREDENTIALS}
        if await conn.is_user_authorized():
            return {"ok": True, "already": True,
                    "detail": "Already signed in to Telegram."}
        sent = await conn.send_code_request(number)
        _pending["phone"] = number
        _pending["hash"] = sent.phone_code_hash
        return {"ok": True, "sent": True,
                "detail": f"Telegram sent a code to {number}."}

    return _guarded(_send, "sending your Telegram login code")


def submit_code(code: str) -> dict:
    """Finish signing in with the code Telegram sent."""
    typed = str(code or "").strip().replace(" ", "")
    if not typed:
        return {"ok": False, "error": "Enter the code Telegram sent you."}
    if "hash" not in _pending:
        return {"ok": False, "error": "That code has expired — start again."}

    async def _sign_in():
        from telethon.errors import (
            PhoneCodeExpiredError,
            PhoneCodeInvalidError,
            SessionPasswordNeededError,
        )

        conn = await _client_on_loop()
        if conn is None:
            return {"ok": False, "error": NEEDS_CREDENTIALS}
        try:
            await conn.sign_in(_pending["phone"], typed,
                               phone_code_hash=_pending["hash"])
        except SessionPasswordNeededError:
            # Two-factor is on. Not an error — the next step.
            return {"ok": False, "needs_password": True,
                    "error": "This account has a Telegram password. Enter it "
                             "to finish signing in."}
        except PhoneCodeInvalidError:
            return {"ok": False, "error": "That code is not right. Check it and "
                                          "try again."}
        except PhoneCodeExpiredError:
            _pending.clear()
            return {"ok": False, "error": "That code has expired — start again."}
        _pending.clear()
        return {"ok": True, "authorized": True, "detail": "Telegram connected."}

    return _guarded(_sign_in, "signing in to Telegram")


def submit_password(password: str) -> dict:
    """The two-factor password, for accounts that have one."""
    if not str(password or ""):
        return {"ok": False, "error": "Enter your Telegram password."}

    async def _sign_in():
        from telethon.errors import PasswordHashInvalidError

        conn = await _client_on_loop()
        if conn is None:
            return {"ok": False, "error": NEEDS_CREDENTIALS}
        try:
            await conn.sign_in(password=password)
        except PasswordHashInvalidError:
            return {"ok": False, "error": "That password is not right."}
        _pending.clear()
        return {"ok": True, "authorized": True, "detail": "Telegram connected."}

    return _guarded(_sign_in, "signing in to Telegram")


def disconnect() -> dict:
    """Sign out and delete the session file.

    Signs out on Telegram's side as well as ours. Deleting the file alone would
    leave a live session listed on the user's other devices, which is a lie
    about what disconnecting did.
    """
    global _client
    from pathlib import Path

    async def _out():
        conn = await _client_on_loop()
        if conn is not None:
            with suppressed("signing out of Telegram"):
                await conn.log_out()
            with suppressed("closing the Telegram connection"):
                await conn.disconnect()
        return {"ok": True}

    with suppressed("disconnecting Telegram"):
        run(_out())
    _client = None
    _pending.clear()
    with suppressed("removing the stored Telegram session"):
        Path(_session_path() + ".session").unlink(missing_ok=True)
    return {"ok": True, "detail": "Telegram disconnected."}


def _guarded(make_coro, what: str) -> dict:
    """Run a login step, and turn anything it raises into something readable.

    Never re-raises: a sign-in that fails has to say what to do next, and
    Telethon's exception text is written for a developer reading a traceback.
    """
    if not _telethon_installed():
        return {"ok": False, "error": "Telegram support is not installed in "
                                      "this build."}
    try:
        return run(make_coro())
    except Exception as exc:
        log.warning("%s failed: %s", what, type(exc).__name__)
        return {"ok": False, "error": f"Telegram refused: {exc}"[:200]}


def _telethon_installed() -> bool:
    with suppressed("checking whether Telegram support is installed"):
        import telethon  # noqa: F401
        return True
    return False
