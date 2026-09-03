# Lodestone — Design Brief ("Living Constellation")

> The visual identity for the app + onboarding. Chosen 3 Sep 2026 from a
> reference the user picked: the **dark generative particle / point-cloud**
> aesthetic (near-black, white particle fields forming organic shapes,
> monospace/HUD type, constellation/node graphs).

## Brand hook
**Lodestone** = the original compass stone; it points you *true north*. The
product orients you around your own work. So the brain is a **living
constellation** — memories as drifting star-particles, the knowledge graph as
the lines between them — on a night sky, guided by one warm **pole-star**.

## Aesthetic: "Living Constellation"
Near-black cool ground · cool-white drifting particles that wire into a
constellation · **monospace-forward** technical type · hairline **HUD** overlays
(coordinates, brackets, status) · one warm **gold "true-north" accent**.

## Tokens
- `--ground: #060810` (cool near-black) · `--ground-2: #0b0e1a` (panel)
- `--star: #dfe7f2` (cool white — particles + text) · `--muted: #7a8397`
- `--line: rgba(223,231,242,.10)` (hairlines)
- `--north: #f5c877` (warm pole-star gold — the ONE accent: live/hover/primary)
- `--north-dim: rgba(245,200,119,.14)`

## Type
- **Mono-forward** (system mono: `ui-monospace, 'SF Mono', 'JetBrains Mono',
  Menlo, monospace`). Headline = mono, light (300), tight letter-spacing.
  Labels = uppercase mono, letter-spaced. Body may use system sans for long reads.
- Distinctly *not* Inter / Space Grotesk (the AI defaults).

## Motion
- Page-load: particles drift in + wire into faint constellation lines (brain
  "igniting"); headline rises/fades in.
- Cursor: nearby particles connect to the pointer with hairlines.
- One pulsing gold pole-star. Respect `prefers-reduced-motion` (static field).

## Layout principles
- Full-viewport **Canvas** particle field as living background.
- **Left-aligned** content column (centered is the AI default), max ~640px.
- **HUD framing**: corner brackets, a status line ("● LOCAL · offline-ready"),
  a live coordinate/particle readout.
- Connect choices = **hairline technical rows** (not rounded chat bubbles), mono
  labels + a gold `→` on hover. NOT numbered (they're choices, not a sequence).
- Commit to **dark single-theme** (deliberate — a night sky isn't "light mode").

## Rollout
- Build the **first screen** first (welcome / connect), then every onboarding
  screen in this aesthetic, then the workspace. Reference: `TURNSTONE-TEARDOWN.md`
  for flow + content; this brief for the look.
