# `chitragupta/browser/` — the browser, and the boundary around it

Read [`origins.py`](origins.py) before changing anything here. It is the only
thing between a page that says *"now go to attacker.example"* and an agent signed
in to the user's accounts, and every other module in this package assumes it
holds.

| module | owns |
|---|---|
| `origins.py` | **which sites an agent may reach, and for what** |
| `page.py` | a page as bounded, ref-bearing, quarantined text |
| `session.py` | navigating, and the landing check after every navigation |
| `chromium.py` | the profile, the one-time download, cleaning up what we spawn |
| `signin.py` | connecting a site once, and what a lapsed session looks like |
| `driver.py` | a real Chromium: ARIA snapshots, parsed, on a thread of its own |

- **The unit of consent is the origin**, granted per capability. A browser has no
  recipient to check the way an email does, so `agents/permissions.py`'s
  allow-list cannot be extended here — the reasoning is in `origins.py`.
- **The check happens at the tool, never in the model.** A page that names
  another site produces a refusal, not a decision by something that just read a
  stranger's text.
- **Check the landing, not the request.** A granted page can redirect anywhere,
  so the address that decides is the one the browser ended up on. A refused
  landing drops the page entirely — its text must not enter the context window
  to argue about being allowed.
- **Page content must never be able to close its own quarantine fence.** It
  cannot be made safe; it can be made unmistakably marked. See `page._defuse`.
- **Refs, never selectors.** A model that can emit JavaScript into a logged-in
  page controls that account.
- **Signing in drives the driver, never `Session`.** Connecting has to reach a
  site nobody has granted yet — that is what connecting *is* — so
  `chromium.open_driver()` exists and the boundary gained no exception.
  `Session` is what agents hold; a boundary with an exception in it is not one.
- **Only a path may stop a read; a title may only advise.** `is_sign_in_url`
  blocks, `looks_like_sign_in` suggests. "Sign up for our newsletter | BBC News"
  is an article, and refusing it would make a legitimate page unreadable with
  nothing on screen saying why.
- **A lapsed session is not a refusal.** A granted site landing on its own login
  page returns `needs_signin` and **drops the page** — an agent handed a login
  form reads one and reports on it, which the user sees as us being broken.
- **Disconnect ends the session, not just the permission.** `forget_site()`
  clears that host's cookies; a grant dropped while the user stays signed in is
  a lie about what the button did.
- **Reading only, today.** `may_act` exists and nothing grants it. A write tool
  must join `permissions.NEVER_UNATTENDED` in the same commit that adds it, and
  `tests/test_browse_tools.py` fails if it does not.
- **Anything we spawn, we clean up — across runs**, through
  `models/login_processes.py`. A browser holds a profile lock; 158 orphaned
  login processes is the precedent.
- The `Driver` protocol in `session.py` is the seam. The fake behind it is why
  the boundary, the budget and the quarantine are testable with no browser and
  no network — keep it that way.
- **Parsing a snapshot is a pure function** (`driver.parse_aria`). It is the part
  most likely to be wrong, and it is tested without a browser precisely because
  it does not live inside the driver.
- **`goto` returning is not the same as having arrived.** A `<meta refresh>` or a
  script setting `location` runs after load — which is how an expired session
  redirects — so `driver.settle` runs before any snapshot. Without it the
  boundary decides about a page the browser has already left.
- **Playwright owns one thread and nothing else touches it.** Its sync API
  refuses to run inside an asyncio loop, and this keeps one browser, one page,
  one caller at a time.

Decisions and what the building changed: [`docs/BROWSER.md`](../../docs/BROWSER.md).
Rules for all of it: [`/CLAUDE.md`](../../CLAUDE.md).
