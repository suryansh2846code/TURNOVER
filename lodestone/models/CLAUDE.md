# `lodestone/models/` — providers, auth, entitlements

Providers, auth flows, entitlements, discovery, the CLI manager, the error
taxonomy, streaming wire formats.

**Model availability is resolved per user, never hardcoded** — read that section
of [`/CLAUDE.md`](../../CLAUDE.md) before adding a model id anywhere. The short
version: the provider's own answer beats every table we ship, hardcoded lists are
fallbacks flagged `is_fallback=True`, a stored id is re-checked before use, and
**detection is never consent** — finding a CLI on the machine lets us *offer* it
and never marks it connected.

Adding a provider means registering an `AuthFlow` and its capabilities, not
adding a route or a UI branch.
