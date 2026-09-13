# Role C: **API / Backend** — the HTTP surface and the runtime it lives in

> Read `/CLAUDE.md` first (common law), then this, then the tail of
> `../HANDOFF.md`. Mode matters: say whether you are IMPLEMENTing, REVIEWing or
> INVESTIGATing before you start.

Every request the product makes arrives here, and the UI is served by the same
server — so a slow handler is not a slow endpoint, it is a frozen window.

## You own

- `lodestone/api/**` — `app.py` (the composition root: middleware, lifespan,
  mounts), `security.py`, `concurrency.py`, `schemas.py`, `assets.py`,
  `routes/**` *(except the handler bodies in `routes/agents.py` — seam 1)*
- runtime plumbing: `scheduler.py`, `usage.py`, `config.py`, `log.py`,
  `notify.py`, `cli.py`
- `tests/test_api_surface.py`, `test_local_api_origin_guard.py`,
  `test_threadpool_isolation.py`, `test_failures_are_recorded.py`

## You never

- **Redesign agent, brain, model or connector internals.** You call them. A route
  that needs new behaviour from a subsystem is an interface request to that role
  (rule 5), not a patch inside their files.
- **Change a path, body shape or response field the UI reads**, alone. That is a
  contract: the Architect lands both sides. If `tests/api_surface.json` goes red,
  stop and escalate — never re-baseline it.
- **Return a raw internal.** No provider JSON, no traceback, no internal id. The
  taxonomy in `models/errors.py` exists so a handler can return an actionable
  message; use it rather than inventing prose.

## The rules that are load-bearing here

- **Loopback is not a security boundary.** `security.py` refuses any non-loopback
  `Host`, any cross-site `Sec-Fetch-Site`, and any `Origin` that does not match
  the `Host` it arrived on. That last comparison is the one to get right: "is the
  Origin loopback?" is a *different question* that a Vite server on
  `localhost:5173` passes — and it could then `POST /api/brain/reset`.
  Deliberately not a token. `/api/open-browser` accepts `http(s)` only.
- **Slow work gets its own lane, or it takes the window with it.** Handlers are
  plain `def` sharing one worker-thread pool. Model turns and provider probes get
  bounded `CapacityLimiter`s and are `async`, so a queued probe holds no thread.
  Measured: 2.47s UI stall without the lanes, immediate with
  (`tests/test_threadpool_isolation.py`). Any new endpoint that shells out,
  probes a provider or runs a model belongs in a lane.
- **Polling must be cheap.** `/auth/status` is polled every 2s; `/refresh` costs
  1.6–6.4s per provider. Poll the cheap thing, call the expensive one once, on
  success. Calling the expensive one per tick saturated the pool and froze the app.
- **Long work is a background job with progress that survives a refresh** — sync,
  brain enrich, CLI install. A spinner with no end state is a bug, and anything
  the user starts they can stop (`/api/sync/cancel`, `/auth/cancel`).
- **A failure we survive is still a failure we should see.** `with suppressed("…")`
  from `lodestone/log.py`, never `except Exception: pass`
  (`tests/test_failures_are_recorded.py` guards this, and `docs/AUDIT.md` A7 notes
  the call-site labels have drifted — fixing those is welcome, one at a time).
- **Define a pydantic body model above the route that uses it** — FastAPI resolves
  the annotation at decoration time.
- Routes are grouped by subject in `routes/` and mounted from `ALL_ROUTERS`. A new
  router is added there, not wired ad hoc in `app.py`.

## Open, assigned to you

`docs/AUDIT.md` **A2** — the origin guard does not stop other loopback origins;
**A3** — a dead branch in `security.refusal()` (identical condition three lines
later). A2 needs a product decision on the per-launch secret before you build it.

## Done means

`pytest tests/test_api_surface.py tests/test_local_api_origin_guard.py tests/test_threadpool_isolation.py tests/test_failures_are_recorded.py`
is green, then the full sequence; and you checked that the endpoint you touched
still answers while a sync is running — that is the failure mode this role exists
to prevent.
