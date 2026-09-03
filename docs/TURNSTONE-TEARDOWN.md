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

## Open questions — capture on next screens
- [ ] What's behind the sign-in? (the main workspace layout, agents, chat)
- [ ] How do they show the "brain" / what they know about you? Visible or hidden?
- [ ] Which model do they use — BYO, or their own hosted? Any model picker?
- [ ] Can agents take actions (send email, create events)? Confirmation UX?
- [ ] Full connector catalog shown in-app.
- [ ] Pricing / limits / any free tier gating.
- [ ] Is there any local/offline mode at all, or 100% cloud?
