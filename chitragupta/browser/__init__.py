"""The browser an agent can drive, and the boundary around it.

Connectors, MCP servers and API keys reach the sources that *have* an interface
for us. Most of the internet does not: a payslip portal, a registrar, a utility
bill. The shape is always the same — the user already has an account, they are
already signed in somewhere, and the only interface is a page.

So this package owns a browser of our own, with its own profile, and a consent
boundary in front of it. Read [`docs/BROWSER.md`](../../docs/BROWSER.md) for the
decisions and [`origins.py`](origins.py) before changing any of them.

Layout, and the order to read it in:

| module | owns |
|---|---|
| `origins.py` | **which sites an agent may reach, and for what.** The boundary |
| `page.py` | a page reduced to text and refs a model can act on, bounded |
| `chromium.py` | fetching, storing and cleaning up the browser itself |
| `session.py` | the live browser, and the driver seam the tests replace |

**The profile is ours, not the user's.** They sign in here, once, to the sites
they want an agent to reach. That is slower on day one and it is the whole safety
story: the blast radius of a mistake is the set of sites somebody deliberately
signed into *in this app*, not everything they have ever logged into.
"""
from __future__ import annotations

__all__ = ["origins"]
