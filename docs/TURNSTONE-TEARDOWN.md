# Turnstone Teardown — competitive research (living doc)

> First-hand notes from running the **real Turnstone app** (v0.5.21, macOS) to
> find gaps and inform Lodestone's design. Updated as we walk more screens.
> Started 3 Sep 2026. Screens captured by the user; analysis by us.

---

## Why this doc
We built Lodestone by reverse-engineering Turnstone's *website*. Now we have the
actual app, so we can validate assumptions, find real gaps, and — critically —
decide where to **match** Turnstone and where to **deliberately differ** (our
local-first privacy edge). Every observation here should end in a Lodestone
implication.

---

## App identity & branding
- **Name:** Turnstone · **Version seen:** 0.5.21 · **Platform:** macOS (downloaded
  `.app`, Gatekeeper "downloaded from the internet" prompt on first launch).
- **Logo:** black square, white **`//`** (two parallel forward slashes).
- **Tagline:** *"Never explain yourself to AI agents."* (≈ our "Stop re-explaining
  yourself to AI" — same core promise.)
- **Design language:** dark charcoal UI, bold sans wordmark, heavy whitespace,
  centered single-column, one primary CTA. Premium, minimal, confident.

---

## Onboarding flow (screen by screen)

### Screen 0 — Gatekeeper
Standard macOS "downloaded from the internet — Open?" prompt. (We'll hit the same;
a signed + notarized build removes the scary version. Tracked in SCOPE packaging.)

### Screen 1 — Splash / brand
Huge **"Turnstone"** wordmark, tagline "Never explain yourself to AI agents."
Light background. Pure brand moment.

### Screen 2 — Welcome / SIGN-IN WALL  ← their real first screen
Full-screen dark. Centered:
- `//` logo
- **"Welcome to Turnstone"**
- **"Sign in to get started."**
- three small **agent avatars** (blue square, red ghost, green triangle) teasing
  the agents
- one big blue button: **"Continue in browser"**

That's the entire screen. **One action. No option to proceed without signing in.**

### Screen 3 — Account sign-in (their identity layer)
"Continue in browser" opens Google's account chooser **"to continue to
myturnstone.ai"** (their OWN OAuth client — identity/login). Meanwhile the app
shows a notification card: *"Waiting for sign-in — Finish signing in to Turnstone.
Continue in your browser. Turnstone will update when your account is ready."* +
"Open browser sign in".

### (Earlier) — Connecting a data source (Composio layer)
When connecting **Google Calendar**, the browser OAuth said **"to continue to
Composio"** with *Composio's* privacy policy + a Composio `client_id`. Card:
*"Waiting to connect — Connect Google Calendar in your browser… Turnstone will
update when the connection is ready."*

---

## Architecture observations (important)
1. **Account-based & cloud-backed.** You MUST sign into a `myturnstone.ai` account
   to use it at all. There is a Turnstone cloud backend behind the app.
2. **Two OAuth layers:**
   - **Identity** → `myturnstone.ai` (their own client) = log into the app/account.
   - **Data connectors** → **Composio** (3rd-party cloud) = Gmail/Calendar/etc.
     Composio holds the tokens and brokers the data (250+ app catalog, MCP-based).
3. **So your data + tokens leave your machine** (Turnstone cloud + Composio cloud).
   Their "local/agents-know-you" story is really cloud-brain, not on-device.
4. **Pattern for connecting** = app opens browser → cloud OAuth → app polls → a
   "waiting to connect… will update when ready" card. Polished and consistent.

---

## Gap analysis — Turnstone vs Lodestone

| Dimension | Turnstone | Lodestone (us) | Verdict |
|---|---|---|---|
| Account required | ✅ Must sign in (myturnstone.ai) | ❌ **No account, works offline** | **Our edge** |
| Where data lives | ☁️ Cloud (Turnstone + Composio) | 🔒 **Local (`~/Library/Lodestone`)** | **Our edge** |
| Connector breadth | ✅ 250+ via Composio | ⚠️ ~11 + custom-API | Their edge |
| Connect setup | ✅ Zero (Composio clients) | ⚠️ Gmail test-user list | Their edge |
| Connect UX polish | ✅ Very polished cards | ✅ Now matched (local card) | Even |
| First-run | Sign-in wall (1 CTA) | Agent-led / connect choices | Design choice |
| Privacy story | ❌ Undercut by cloud | ✅ **Genuinely private** | **Our edge** |
| Cross-device sync | ✅ (cloud account) | ❌ (local only) | Their edge |
| Model | (unknown — capture next) | BYO (7 backends) | TBD |

**Summary:** Turnstone bought **convenience + breadth** by going **cloud + account +
Composio**, and in doing so **gave up the privacy/local story**. That is precisely
the ground we should own.

---

## Implications for Lodestone's FIRST screen
- **Do NOT copy their sign-in wall.** Our superpower is *no account, instant, local*.
  Forcing a sign-in would throw away our biggest differentiator.
- Lead the first screen with **trust + instant value**: "Private AI that knows your
  work. No account. Everything stays on your Mac." Then one warm action to feed the
  brain (agent-led connect — Google/local/fact).
- We can still **borrow their polish**: the centered, dark, single-CTA calm; the
  agent avatars as a teaser; the "waiting to connect… updates when ready" card
  (already built, locally).
- Net: **same premium feel, opposite trust model.** "Turnstone in the cloud →
  Lodestone on your Mac."

---

---

## Onboarding flow — full walkthrough (batch 2, 3 Sep)

Order: **account sign-in → founder FaceTime video → connect email/calendar →
connect AI model → into the app.** "Skip" is always available (bottom-left).

### Step A — account sign-in success
Browser shows "✓ Signed in — Welcome to Turnstone — Your account is ready in the
app — You can close this tab." App card updates. (Confirms cloud account gate.)

### Step B — 🎬 Founder FaceTime onboarding  ← signature move
- An **incoming FaceTime call** appears (phone mockup): caller **"Aryan & Jai"**
  (the founders), Decline / Accept.
- Accept → the founders appear on a **personal video** speaking to you:
  *"We made Turnstone because we feel that AI should really know you."*
- Has **captions toggle, 1×/2× speed, pause**, and a **Continue** button.
- As you proceed, the video **shrinks to a picture-in-picture** phone in the
  corner and **keeps playing/narrating** ("So go ahead, plug in your AI
  subscriptions") through the connect steps. Warm, personal, unforgettable.

### Step C — Connect email & calendar (Composio)
Headline **"Connect your email and calendar."** Two big cards: **Google** (Gmail +
Google Calendar) and **Microsoft** (Outlook mail + calendar). Shows connected
status inline ("suryansh…@gmail.com ✓ Connected", "Google Calendar ✓ Connected").
Outlook connect goes through Composio ("Turnstone wants to connect to your
Outlook… Secured by Composio").

### Step D — Connect the model ("Use the AI you already pay for")
Headline **"Use the AI you already pay for."** Sub: "A free ChatGPT account works
too. Or use a paid ChatGPT or Claude plan, bring an API key, or start with a free
model." Cards:
- **OpenAI** — *"ChatGPT Go found · suryansh…@gmail.com"* — **Recommended**
- **Claude** — *"Claude Pro found · adis…@gmail.com"* — **Recommended**
- **Grok** · **Cursor** · "No subscription? More options."
- Each card → dropdown: **"Sign in with ChatGPT"** or **"Use an OpenAI API key."**
- Sign-in path uses OpenAI's **"Sign in with ChatGPT" (Codex) OAuth** → callback
  `localhost:1455/success?id_token=…` → "✅ ChatGPT is connected."

---

## Major findings (batch 2) — architecture & strategy

### F1 — 🧠 The brain is IN-MEMORY, never written to disk
Direct quote in-app: *"What Turnstone learned last time was never written to disk,
so that read starts over."* Turnstone rebuilds the brain in RAM every session by
re-reading your (cloud-connected) accounts.
- **Their angle:** privacy (nothing persisted).
- **Cost:** no long-term accumulated memory; slow re-read every launch.
- **Lodestone contrast (our win):** we **persist locally** → instant startup AND a
  brain that **grows over time** — essential for a depth-first "knows your work"
  product — while still private (on-device). We can claim **private *and*
  persistent**; they can't.

### F2 — 💳 Subscription detection + native use (the hard path, done)
Turnstone **auto-detects existing paid AI subs** (ChatGPT Go, Claude Pro) and lets
you use them with **no API key** via the vendor's own sign-in (Codex "Sign in with
ChatGPT", `localhost:1455`). Supports OpenAI, Claude, Grok, Cursor, API keys, free
model.
- **Lodestone status:** we already use the **Claude** subscription via `claude-code`
  (the CLI). We do **not** yet have **"Sign in with ChatGPT" (Codex flow)** to use a
  ChatGPT subscription keylessly. **← biggest model-path gap.**

### F3 — Connectors are Composio (Google + Microsoft/Outlook)
Everything brokered by Composio (cloud). **Microsoft/Outlook** is a connector we
lack. Consistent "waiting to connect → updates when ready" pattern for all.

### F4 — Consistent connect pattern
App shows a dark card ("Waiting to connect / for sign-in — … Turnstone will update
when the connection is ready — Open browser sign in"); browser does the OAuth;
app polls; ends with "✅ Connected as <email>". We already mirror this locally
(H10 connect card) — keep matching the polish.

---

## Design language (observed)
- Deep charcoal/near-black backgrounds; **big centered headlines** ("Connect your
  email and calendar", "Use the AI you already pay for"); generous whitespace.
- **Card-based choices** (Google/Microsoft, OpenAI/Claude/Grok/Cursor) with logos,
  a bold title, a muted one-line sub, and a "Recommended" tag.
- **Blue primary button** ("Continue"), ghost secondary, **"Skip" always bottom-left**.
- Playful **agent avatars** (blue square, red ghost, green triangle) as a recurring
  brand motif. Logo `//`.
- Motion + delight: FaceTime call metaphor, PiP video, smooth status transitions.

---

## Updated gap analysis (what to steal / what we win)

| Area | Turnstone | Lodestone | Action |
|---|---|---|---|
| Brain persistence | ❌ In-memory, re-read each session | ✅ **Local + persistent** | **Own it in messaging** |
| Account required | ✅ myturnstone.ai | ❌ none | Own it |
| Data location | ☁️ Composio + cloud | 🔒 local | Own it |
| ChatGPT subscription (keyless) | ✅ Codex sign-in | ⚠️ not yet | **Build: "Sign in with ChatGPT"** |
| Claude subscription (keyless) | ✅ | ✅ via claude-code | Even |
| Microsoft / Outlook | ✅ | ❌ | **Build: Outlook connector** |
| Onboarding warmth | ✅ founder FaceTime | ⚠️ card onboarding | Borrow the *agent-greets-you* feel |
| Model breadth | OpenAI/Claude/Grok/Cursor | 7 backends (incl. local) | Even/ours-broader |
| Connect UX polish | ✅ | ✅ (matched) | Keep |

### Prioritized actions surfaced
1. **"Sign in with ChatGPT" (Codex-style) provider** — use a ChatGPT subscription
   with no API key (localhost callback). High impact (cost) — matches their headline
   feature. Also consider Grok/Cursor sign-in.
2. **Microsoft / Outlook connector** (mail + calendar).
3. **Messaging:** lead with **"private AND remembers you"** — their in-memory brain
   can't accumulate; ours does, locally.
4. Optional: subscription **auto-detection** ("Claude Pro found") as a delightful touch.

---

## Still to capture (next screens)
- [ ] The **main workspace** after onboarding (layout, agents, chat).
- [ ] How they **show the brain** / what they know about you (visible? a graph?).
- [ ] Can agents **take actions** (send email, create events)? Confirmation UX?
- [ ] Full **connector catalog** in-app (beyond email/calendar).
- [ ] **Pricing / limits / free-tier** gating.
- [ ] Free/local model option details ("start with a free model").
