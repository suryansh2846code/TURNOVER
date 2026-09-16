# Connecting Telegram — the contract

> Written alongside the code, per `/CLAUDE.md`. The backend half is here; the
> card that drives it is the frontend lane's, so **every field is named**.
>
> Why Telegram and not WhatsApp: [`../MESSAGING.md`](../MESSAGING.md).

## 1. Why this is a flow and not a box

Every other token-based connector in the app is one `secret_field` — paste a
key, done. Telegram cannot be, and the reason is worth stating once so nobody
tries to collapse it later.

This is **MTProto, the client API**, not the Bot API. A bot only sees chats it
was explicitly added to, which is not the user's life. The client API is how
every third-party Telegram client works, it is public, and it needs four things
in order:

1. an **API ID** and **API hash**, which the user fetches once from
   `my.telegram.org` → *API development tools*;
2. their **phone number**;
3. the **login code** Telegram sends to that number;
4. a **password**, but only if the account has two-factor enabled.

Step 4 is not a failure. It is a step, and the payload says so with
`needs_password: true` rather than an error the card would render in red.

## 2. One event loop, on one thread

Telethon is asyncio, and a `TelegramClient` belongs to the loop that created it.
The app around it is not: a request thread has no loop, a bounded lane has a
worker, the scheduler has its own. `telethon.sync`'s implicit global loop breaks
the moment two of those overlap.

So `telegram_auth.py` owns **one** loop on **one** daemon thread, the client is
created there, and every call is handed to it with
`asyncio.run_coroutine_threadsafe`. Nothing touches the client from anywhere
else. A handler that calls this must be on a bounded lane
(`@probes_a_provider`), because it blocks its thread while the loop works.

## 3. The endpoints

Every one returns the same shape — `{ok, error, detail, …}` — so a card driving
the flow never has to tell them apart.

| endpoint | body | returns |
|---|---|---|
| `GET /api/telegram/status` | — | `{configured, authorized, account, reason}` |
| `POST /api/telegram/credentials` | `{api_id, api_hash}` | `{ok, error?}` |
| `POST /api/telegram/login` | `{phone}` | `{ok, sent?, already?, error?}` |
| `POST /api/telegram/code` | `{code}` | `{ok, authorized?, needs_password?, error?}` |
| `POST /api/telegram/password` | `{password}` | `{ok, authorized?, error?}` |
| `POST /api/telegram/disconnect` | — | `{ok, detail}` |

| field | promise |
|---|---|
| `configured` | the API id and hash are stored. Says nothing about being signed in. |
| `authorized` | there is a live session. This is the one that means "connected". |
| `account` | display only — a name or handle. **Never** an id, never a phone number to render as identity. |
| `reason` | a sentence for a person, already written. Render it; do not compose your own. |
| `needs_password` | two-factor is on. Show the password step. Not an error. |

`already: true` on `/login` means there was already a session — show connected,
do not ask for a code that will never arrive.

## 4. What is never stored

* **The login code and the password are never written to disk and never
  logged.** The `phone_code_hash` that step 2 needs lives in a module dict for
  the couple of minutes the code is valid, and is cleared on success, on
  expiry, and on disconnect.
* The API id and hash go through `settings.set_secret`, like every other
  credential.
* The session file is `~/Library/Lodestone/telegram.session`. It is the
  credential; treat it as one.

## 5. Disconnecting signs out on Telegram's side too

Deleting the session file alone would leave a live session listed under the
user's *Active Sessions* on their phone. That is a lie about what the button
did, so `disconnect()` calls `log_out()` first and removes the file after.

## 6. What the agent gets

Nothing Telegram-shaped. The connector implements the three methods in
`lodestone/messaging.py` — `chats`, `history`, `send` — and the agent layer sees
`list_chats` / `read_chat` / a `message_send` action that work the same way for
Slack. Adding a third app is one class and no change above it.

`history` returns **oldest first**. Telethon yields newest first, and it is
reversed here rather than anywhere above, so every app keeps the same promise.

## 7. Deliberately open

* **No live updates.** Reading is on demand and on the sync timer; there is no
  "new message" trigger yet. Telethon supports one, and a routine that fires on
  an incoming message is exactly the case `permissions.py` warns about — the
  text was written by a stranger — so it needs its own decision first.
* **No media.** A photo reads as `(photo)`. Downloading attachments means a
  place to put them and a size budget.
* **One account.** The session is a single file; a second Telegram account
  needs a second path and a way to choose.
