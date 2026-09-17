# The onboarding → workspace flow

> The path a brand-new user takes, and what each screen is waiting for.
> Order: **Hero → Connect → Build → Digest → Workspace (Agent Library)**.

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

## Build — and when it is allowed to end

The build screen used to hand over on a **timer**: 4.5s minimum, 45s cap. That
is before the first enrichment pass has typed a single entity, so onboarding
ended on four cards reading "still sorting" — true, and a terrible finale.

It now waits for real state, in three stages, each reporting its own numbers:

| stage | the screen says | driven by |
|---|---|---|
| sync | `Reading your sources…` · `N memories read so far…` | `/api/brain/stats` · `/api/sync/status` |
| enrichment | `Working out who's who — 600 of 1,200` | `/api/brain/enrich/status` |
| snapshot | `Assembling your snapshot…` | `/api/brain/digest` |

The first enrichment pass is **started by onboarding** (`/api/brain/enrich/start`,
once real memories have landed and settled), not left to the workspace. Handover
happens only when that pass is over **and** at least one persona is `grounded`.

Three things stop it becoming a hostage situation:

- enrichment that never shows life within `ENRICH_GRACE` (no model connected) is
  treated as unavailable and skipped, not waited on;
- while nothing is groundable the digest is re-asked every `DIGEST_RETRY` — the
  sync is still running, so the answer really does change;
- after `PATIENCE` a **Continue anyway →** appears. Both jobs keep running in the
  app. (`Skip for now` in the header is hidden once `.stage.on` is set, so the
  build screen needs its own way out.)

The block is bracketed by `// >>> build-progress >>>` and is **executed** by
`tests/js/onboarding_build.mjs` against a scripted backend and a scripted clock —
a 150-second patience window costs the suite no seconds.

## Digest — "Here's your brain"

Cards stay hidden until `POST /api/brain/digest` returns, then fade in.

**Every line on a card is measured or absent.** There is no written-in-advance
sentence anywhere — not in the markup, not as a server fallback, not as a client
one. "What you're building and working on." used to ship in all three, on a
screen a person reads as the app's first finding about them.

### The contract

```jsonc
{ "generated": true,      // a model wrote the summaries
  "total": 4200,          // memories in the brain
  "typed": true,          // the graph has worked out WHAT things are
  "reason": null,         // else: no_data | no_model | not_written | model_failed
  "personas": [ { "key": "work",        // work | learning | comm | personal
                  "title": "Work",      // what a person reads
                  "items": 1280,        // memories backing it — exact, needs facts
                  "mentions": 3100,     // times named — exists from the first sync
                  "themes": ["Atlas"],  // entities really typed into this area
                  "sources": ["gmail"], // connectors those memories came from
                  "summary": "…",       // null unless a model wrote it
                  "grounded": true } ]  // false ⇒ the card shows no claim
}
```

- An area is chosen **by entity type**, in `brain/graph.py::DIGEST_AREAS` — never
  by which connector a memory arrived from. `thing` is deliberately unmapped.
- `items` and `mentions` are different true numbers and the card labels each as
  what it is. `items` needs relations, which only enrichment produces.
- `sources` is derived from `relations.source_mem → memories.source`, so a
  connector added tomorrow appears without touching this code. It is **exact or
  absent** — a vector search stood in for it briefly and was pulled, because
  `embedding_provider` defaults to `hash`.
- `?written=0` returns the measured half without calling a model. The page asks
  for it when the written pass is slow, instead of computing personas of its own.

### `typed` is why the empty states differ

Before enrichment every entity is an untyped `thing`, so all four areas count
zero. That is **not** an empty brain, and the card says so:

| state | the card reads |
|---|---|
| `total == 0` | Nothing here yet. |
| `typed == false` | Still sorting your memories into this one. |
| `typed == true`, area empty | Nothing here yet. |
| grounded, no summary | Read from Gmail and Notion. + what to do |
| summary | the model's sentence |

A model summary stands even when `typed` is false — it read the real recall
context, which is grounding the type check cannot see.

The render block is bracketed by `// >>> digest-render >>>` markers and is
**executed** by `tests/js/onboarding_digest.mjs`; a grep over the page would
pass while the cards rendered nothing.

## First entry — the Agent Library

There used to be a fifth step here: *name your lead agent*, which built a custom
agent from the brain and gave it a **Lead** badge. It is gone, and so is the
one-time LLM intro it delivered.

It was a second answer to a question the library already answers. "Chief of
Staff" is that agent, written once, in `library.py`, with the tools for the job
— where the lead agent was built from a hardcoded list that had no connector
access and a prompt naming three specialists a new user does not have. Two
definitions of the same role is how one of them ends up stale, and that one did.

So first entry opens the **Agent Library** instead. Nothing is pre-added and
there is no lead agent, so a new install genuinely has no agents: the library is
not a nicety here, it is the only way to get one. It opens once
(`lodestone_saw_library`), and the agent rail says so and points there whenever
it is empty.

## Brain status

The header pill polls `/api/sync/status` + `/api/brain/stats`. Clicking it opens
the live "Your brain" panel (`#brainBuild`).

---

## The state this flow writes

| key | where | what it means |
|---|---|---|
| `lodestone_onboarded` | localStorage | the user finished onboarding |
| `lodestone_saw_library` | localStorage | the Agent Library has opened itself once |
| `lodestone_provider` / `lodestone_model` | localStorage | the chosen backend |
| `ls_saw_onboarding` | sessionStorage | guards the empty-brain redirect |
| onboarded flag | `GET`/`POST /api/onboarded` | **server-side**, because localStorage is per-origin and the desktop app binds a different port per launch |

That last row is the one to remember: the webview origin is user state. A launch
that lands on a different port loses everything keyed to localStorage, and the
app opens looking empty. See [`../DESKTOP-SIGNIN.md`](../DESKTOP-SIGNIN.md) → 5.

## Endpoints this flow added

`POST /api/brain/reset` · `POST /api/brain/digest` ·
`POST /api/providers/{name}/key` · `POST /api/sync/cancel`

(`POST /api/agents/lead` and `POST /api/agents/{id}/welcome` were removed with
the lead agent.)

The authoritative list of every endpoint is `tests/api_surface.json`, not this
file.
