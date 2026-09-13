# Role: **<name>** — <one line: what this role is for>

> This is the scoped role definition. For a **custom specialist** fill it in and
> work from it for the current task only — it dissolves afterwards unless the user
> explicitly promotes it. For a **permanent role** the Architect follows
> `/CLAUDE.md` → *Adding a permanent role*. Either way: fill in every section. A
> file left as the template is worse than none, because it reads as law.
>
> Read `/CLAUDE.md` first (common law), then this, then `../HANDOFF.md`.

```
CUSTOM AGENT NAME:
MISSION:              one paragraph — the outcome, not the activity
RESPONSIBILITIES:
OWNED PATHS:          each one moved out of whichever role holds it now — name that role
READ-ONLY PATHS:
FORBIDDEN PATHS:
INPUT:                what it receives to start
OUTPUT:               what it must return
SUCCESS CRITERIA:
TEST REQUIREMENTS:
DEPENDENCIES:         other roles or contracts needed first
EXIT CRITERIA:        when this role stops existing
MODE:                 IMPLEMENT | REVIEW | DEBUG | TEST | AUDIT | PROFILE | DESIGN | INVESTIGATE
```

## Why this role exists

<The work that was being done badly, or not at all, because it was split across
existing roles. If you cannot name that, this should be a handoff instead.>

## You never

<The specific reaches this role will be tempted to make, each naming the role the
path actually belongs to. Plus the standing one: never change a cross-layer
contract alone — the Architect lands both sides.>

## The rules that are load-bearing here

<Not general advice: the already-paid-for lessons of this area, each with the
measurement or the symptom that taught it and the test that guards it. If a rule
has no failure behind it, leave it out — common law covers the generic.>

## Traps

<Ways a change here passes its tests and is still broken.>

## Done means

<The command that must be green, plus the human check: what you look at, in what
state, before saying it works. "Tests pass" is not a definition of done in a
product that ships to people who did not build it.>

---

Standing specialists worth reaching for rather than inventing: **macOS Desktop
Engineer** (already a dormant role — see `../desktop/CLAUDE.md`), **Security
Auditor** (origin checks, auth boundaries, credential handling, local API
exposure, open-browser/SSRF risk), **Performance Engineer** (recall scaling,
discovery latency, threadpool starvation, caching, startup), **OAuth Specialist**
(flows, callback lifecycle, CLI sign-in, account state, capability transitions),
**Frontend UX Specialist** (hierarchy, states, transitions, loading/error UX,
responsiveness, accessibility).
