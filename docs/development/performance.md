# Performance — what was slow, what it measured, and what fixed it

> Every number here came from this app on a real machine. They are recorded
> because in each case the obvious suspect was wrong, and the fix only looks
> obvious once you know which one it was.
>
> Recall cost at scale is a separate subject: [`SCALING.md`](../SCALING.md).

---

## Opening a panel must not block on subprocesses

**Symptom.** Opening the Models drawer froze the app for about ten seconds.
Often long enough to force-quit.

**Measured, uncached:** `/api/providers` **5.7s** + `/api/models/catalog`
**4.4s** — and both are fetched *every* time the drawer opens.

Where it went:

| cost | why |
|---|---|
| ~50 Keychain reads | each one spawns `security` |
| `detect_all_accounts()` | every provider probed in turn |
| `agent --list-models` | 223 rows, **3.1s** on its own |

**Fix.** `models/cache.py::ttl_cached` memoises the expensive probes — seconds
for detection, minutes for CLI model lists. `clear_provider_cache()` flushes the
lot the moment a credential changes, so connecting is still instant.

**Warm drawer open: 0.05s.**

Cheap probes stay uncached deliberately — Gemini answers in ~60ms, and caching
it would only buy staleness.

**The lesson worth keeping: profile before optimising.** SQLite and the window
layer both looked guilty here. Neither was.

---

## Polling must be cheap

**Symptom.** The whole app froze during sign-in.

`/auth/status` is polled every 2s. It called `/refresh`, which re-runs discovery
at **1.6–6.4s per provider** — so requests queued faster than the server could
finish them, saturated FastAPI's sync threadpool, and took the window with them.
The UI is served by the same server.

**Fix.** Poll the cheap endpoint; call the expensive one **once**, on success.
CLI sign-in checks shell out, so they are cached for a few seconds
(`reset_auth_cache()` on login and on cancel).

This treated the symptom. The cause is below.

---

## Slow work gets its own lane, or it takes the window with it

Every route handler is a plain `def`, so FastAPI runs them all in one shared
worker-thread pool. That is the right default — the handlers block — but it
makes the pool a single shared resource with no priority in it, and the app's
own interface is served by the same server.

**Measured** (`tests/test_threadpool_isolation.py`): with the shared pool
throttled and 20 blocking probes in flight, the UI waited **2.47s** without
lanes and answered **immediately** with them.

**Fix.** `api/concurrency.py` gives model turns and provider probes bounded
`CapacityLimiter`s and makes those endpoints `async`, so a queued probe holds
**no** thread at all:

- `MODEL_CALLS` (8) — a turn against a provider, which can run for a minute.
- `PROBES` (6) — shelling out to a vendor CLI, reading the Keychain. Seconds,
  and far more frequent.

Two lanes rather than one, because a single chat turn must not hold up every
sign-in probe behind it — which is the same failure this module exists to
prevent, one level down.

---

## Startup must not wait for the embedder

The embedding model takes ~10s to load, and the UI's own endpoints do not need
it. `warm_embedder()` is called from the lifespan hook off the critical path, so
the workspace answers immediately and the first search is fast anyway.

Related: `store.stats()` returns the *configured* embedder name, never the
loaded object's. Reading a string off the embedder forced the whole model to
load — **16 seconds** to answer "how many memories do I have", on the endpoint
the header pill polls.

---

## Where each of these is pinned

| behaviour | test |
|---|---|
| lanes keep the UI responsive | `tests/test_threadpool_isolation.py` |
| the drawer opens without blocking | `tests/test_catalog_performance.py` |
| startup does not wait on the model | `tests/test_startup_is_not_blocked.py` |
| the cache is flushed when a credential changes | `tests/test_model_cache_invalidation.py` |
| singletons are built once | `tests/test_singletons_build_once.py` |
