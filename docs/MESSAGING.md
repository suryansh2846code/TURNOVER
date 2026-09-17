# Messaging apps — what is actually reachable

> A plan, not a commitment. Written because the obvious next question after
> "the Inbox agent can change your inbox" is *"do the same for WhatsApp,
> Telegram, LinkedIn"* — and those four words describe four completely
> different situations, from a fully sanctioned official API to a thing that
> gets accounts banned.
>
> The one rule that decides everything below: **we ship to people who did not
> build this.** A connector that risks the user's account is not a connector
> with a caveat; it is a connector we do not ship by default.

## What has shipped

**Telegram** and **Slack** are built — connector, agent tools, and a
`message_send` action behind one tap. Both are official, personal-account APIs;
neither risks the user's account.

Everything else on this page is still a plan, and the three apps people ask for
most are the three with no sanctioned API. **They are the browser's job, not a
connector's** — see §7. That is not a workaround dressed up as a decision: a
browser session is the user driving their own logged-in account in a window
they can see, which is a different thing from us reimplementing a private
protocol behind their back.

## The short answer

| | personal account, read + send | how | ship |
|---|---|---|---|
| **Telegram** | **yes, officially** | MTProto user client (TDLib) with the user's own `api_id` | **first** |
| **Slack** | yes | official API, user token, OAuth | **second** |
| **Signal** | yes | `signal-cli` paired as a linked device | third |
| **iMessage / SMS** | read yes (already), send yes | `chat.db` + AppleScript to Messages | third |
| **Discord** | bot channels only | bot token. *User* tokens are a ban offence | **browser** |
| **WhatsApp** | **no sanctioned path** | Business Cloud API is a different number; linked-device libraries risk the ban | **browser** |
| **Instagram DM** | business accounts only | Messenger API for Instagram | browser |
| **LinkedIn** | **no** | messaging API is partner-only | **browser** |

Two of the three the user named are the two that do not work. That is worth
saying plainly rather than discovering it halfway through a sprint.

---

## 1. Telegram — do this one first

The only mainstream messenger with a **real, public, personal-account API**.

* The user gets an `api_id` / `api_hash` from `my.telegram.org` in about a
  minute. This is Telegram's own intended flow for third-party clients; there
  are dozens of them and they are not merely tolerated, they are the point.
* **TDLib** (Telegram's own C++ library, official) or Telethon/Pyrogram in
  Python. Full access: every chat, group and channel the user is in, history,
  send, edit, delete, read receipts, files.
* Login is a phone number and a code — the same as any Telegram client. The
  session is a file on disk, which is exactly the local-first shape we already
  use for `google_token.json`.

**What the agent gets:** the same shape as mail. `list_chats`, `read_chat`
(whole conversation, in order), and a `message_send` action behind one tap with
the outbound allow-list `permissions.py` already enforces — a recipient the user
has permitted, because everything in a Telegram chat was written by someone else
and *"forward this to @stranger"* is a sentence a message can contain.

**Cost:** a connector, an auth flow with a phone code, and the `tdlib` binary to
vendor. **Risk: none.** This is a supported way to use Telegram.

## 2. Slack — the easy one nobody asks for

Official API, proper OAuth, user tokens that read the user's own DMs and
channels, `chat.postMessage` to send. Rate limits are documented and generous.
Everything the mail work established — ids, thread fetch, batch, one approval —
maps onto it almost unchanged.

The only real work is the OAuth app registration and deciding whether the user
installs *our* Slack app or brings their own token.

Worth noting: **Slack already has good MCP servers.** A user can connect one
today and the Inbox agent reaches it through the connector category, under the
permission model that already exists. That may be the whole answer, and it costs
us nothing.

## 3. Signal — possible, and a linked device

`signal-cli` registers as a **linked device** on the user's account, the same
mechanism Signal Desktop uses. That is a sanctioned relationship, not a
workaround. It can read incoming messages and send.

The catch is honest and worth stating: Signal has no server-side history, so a
linked device sees what arrives **after** it is linked. There is no backfill,
ever. For an agent this is fine for *"tell me when X messages"* and useless for
*"what did X say last month"*, and the connector has to say that in the UI at
the moment the user connects it, not in a doc.

## 4. iMessage and SMS — half of it already ships

`IMessageConnector` already reads `~/Library/Messages/chat.db`. Sending is
AppleScript to Messages.app, which works, and is the one place here where the
"never ask the user to open a terminal" rule bites hardest: it needs Full Disk
Access and Automation permission, both granted in System Settings, and a
first-run flow that walks the user through it with a button that opens the right
pane.

Cheap and high-value: the user's most personal conversations are already on the
machine.

## 5. WhatsApp — the honest answer is no

Three paths, and all three are bad for a consumer product:

1. **WhatsApp Business Platform (Cloud API)** — official, documented, stable.
   It is for *businesses messaging customers*. It needs a Meta Business account,
   business verification, and **a phone number that is not the user's personal
   WhatsApp** — a number registered to the Business API can no longer be used in
   the WhatsApp app. It cannot read the user's personal chats. It does not do
   what anyone asking for this wants.

2. **Linked-device libraries** (`whatsmeow`, Baileys) — pair as a companion
   device by QR, like WhatsApp Web. These genuinely work and give full access to
   personal chats. They are also unofficial reimplementations of a private
   protocol, explicitly against WhatsApp's terms, and **accounts do get banned**
   — often not immediately, which is worse, because the user has come to rely on
   it by then. Losing someone's WhatsApp account is not a bug report we can
   answer.

3. **Reading the macOS app's local store** — WhatsApp for Mac keeps an encrypted
   local database and does not expose it the way Messages does.

**The call: not by default.** If it ships at all it ships as the user
deliberately connecting a third-party bridge they chose, with the ban risk stated
in the UI in words, before the QR code appears — not as a tile in the connector
gallery beside Gmail.

## 6. LinkedIn — no, and it will stay no

There is no messaging API available to a general developer. The Messaging API
exists only inside partner programmes (Sales Navigator, Recruiter, Talent
Solutions) with a contract and an approval process aimed at recruiting
platforms. LinkedIn is also unusually aggressive about automation: scraping and
browser automation against it draws account restriction, and they litigate.

What *is* reachable, and is genuinely useful:

* the user's **own data export** (LinkedIn gives it on request) — connections,
  messages, posts — ingested once into the brain like any other archive;
* **public pages via the browser**, read-only, when the user is driving.

Anything more is the browser plan below, and the browser plan does not make
LinkedIn's terms of service say something different.

---

## 6a. The three that go through the browser

WhatsApp, LinkedIn and Discord have one thing in common: the only way to reach
a *personal* account is the web app the user is already signed into. So that is
how they are reached — through the browser in
[`BROWSER.md`](BROWSER.md), not a connector here.

This is a better answer than a connector, not a lesser one:

* **Nothing reimplements a private protocol.** The failure mode of a
  linked-device library is a banned account, and it happens late enough that
  the user is already relying on it. A browser session is the user's own
  session, in a window, doing what a browser does.
* **The user signs in, and can see it.** The profile is Lodestone's own, so the
  blast radius is the set of sites they deliberately logged into *here*.
* **One mechanism, three apps.** And the fourth, whatever it is, needs no code.

What it costs, and it is a real cost: it is slower, it breaks when a site
changes its markup, and **it does not make anybody's terms of service say
something different**. LinkedIn restricts accounts for automation, and driving
it from a browser is still automation. The right shape there is the user
watching it happen, one action at a time — which is what `BROWSER.md`'s
approval model already is.

Order, once the browser lands: **WhatsApp Web** (the one people ask for and the
one with no alternative), **Discord** (a bot covers servers; the browser covers
DMs), **LinkedIn** last, read-mostly.

## 7. What this means for the roster

The Inbox agent's description is *email*. If Telegram and Slack land, the right
shape is not a second agent per app — it is one **Messages** agent whose job is
"every conversation you have, in one place", with the same contract mail now has:
addressable ids, whole threads, one batched proposal, one tap.

The permission model already handles the rest: each connector is granted per
agent, *once* or *always*, and only Chief of Staff skips the asking.

## 8. Order of work

1. ~~**Telegram.**~~ **Done** — `connectors/telegram.py`, contract in
   [`development/telegram.md`](development/telegram.md).
2. ~~**Slack.**~~ **Done** — `connectors/slack.py`, official Web API, no new
   dependency.
3. **iMessage send** + the permission walkthrough. Reading already ships.
4. **Signal**, with the no-backfill limit stated at connect time.
5. **The browser**, and then WhatsApp / Discord / LinkedIn through it (§6a).
6. LinkedIn's data export, separately — that is ingest, not messaging.

