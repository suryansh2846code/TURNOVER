# The onboarding → workspace flow

> The path a brand-new user takes, and what each screen is waiting for.
> Order: **Hero → Connect → Build → Digest → Workspace (welcome + lead agent)**.

---

## Connect

The source grid comes from `GET /api/connectors`; an **AI Model** card
(`openLLM`) picks a provider and an optional key.

Google sources are shown as **disconnected until real sign-in** —
`/api/google/status` overrides the bundled-client `ready`, because a shipped
OAuth client makes the connector look configured when the user has not consented
to anything.

Clicking a source really connects it: Google OAuth, an inline token, a folder
picker, or a custom form. **Continue requires Gmail connected AND an AI model
chosen** (`canContinue()`), with a gold hint that narrows as each is satisfied.

## Start from zero

"Build my brain" calls `POST /api/brain/reset` — wipes memories and graph and
connector state, clears connector secrets, disconnects Google — and clears local
prefs, so it genuinely feels like a new user rather than a cleared screen.

A wiped or empty brain also redirects `/` → `/onboarding` once per session
(`sessionStorage.ls_saw_onboarding` guards it).

## Build

Kicks `POST /api/sync/now`, then the progress bar **loads until the profile is
extracted** — it waits for real data to land, then calls the digest. The bar
never shows 100%, because the brain keeps building in the background and a full
bar that is followed by more work is a lie.

Cancel → `POST /api/sync/cancel` (cooperative). It never blocks on a full first
sync.

## Digest — "Here's your brain"

Cards stay hidden until `POST /api/brain/digest` returns, then fade in.

The digest is **LLM-written from the real brain** and uses the caller's
provider/model, passed in the body — the server default is `mock`. A computed
counts-and-themes fallback plus a timeout means it can never hang.

The cards in `onboarding.html` are **neutral placeholders**; `fillCards`
populates them from the real brain. Nothing in them may be specific to one
person or one machine.

## Workspace welcome

First entry (onboarded, no lead agent yet) shows "name your lead agent":

1. `POST /api/agents/lead` — system prompt personalised from the brain, pinned
   with a **Lead** badge.
2. `POST /api/agents/{id}/welcome` — a one-time LLM intro that teaches the app.
   Scripted fallback offline, and not persisted.

## Brain status

The header pill polls `/api/sync/status` + `/api/brain/stats`. Clicking it opens
the live "Your brain" panel (`#brainBuild`).

---

## The state this flow writes

| key | where | what it means |
|---|---|---|
| `lodestone_onboarded` | localStorage | the user finished onboarding |
| `lodestone_lead_agent` | localStorage | which agent wears the Lead badge |
| `lodestone_provider` / `lodestone_model` | localStorage | the chosen backend |
| `ls_saw_onboarding` | sessionStorage | guards the empty-brain redirect |
| onboarded flag | `GET`/`POST /api/onboarded` | **server-side**, because localStorage is per-origin and the desktop app binds a different port per launch |

That last row is the one to remember: the webview origin is user state. A launch
that lands on a different port loses everything keyed to localStorage, and the
app opens looking empty. See [`../DESKTOP-SIGNIN.md`](../DESKTOP-SIGNIN.md) → 5.

## Endpoints this flow added

`POST /api/brain/reset` · `POST /api/brain/digest` · `POST /api/agents/lead` ·
`POST /api/agents/{id}/welcome` · `POST /api/providers/{name}/key` ·
`POST /api/sync/cancel`

The authoritative list of every endpoint is `tests/api_surface.json`, not this
file.
