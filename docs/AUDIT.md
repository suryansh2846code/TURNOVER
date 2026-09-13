# Audit — known gaps, with the evidence

> A standing list of things found wrong or weak in the codebase, each with the
> command that shows it and what closing it takes. Reviewed 2026-09-13 against
> `419fa3c` plus the uncommitted serving-layer work.
>
> This is not a wishlist. Everything here is a defect or a measured liability;
> aspirational work lives in [`ROADMAP.md`](ROADMAP.md) and
> [`DECISIONS.md`](DECISIONS.md) → Deferred.

**State at review:** 791 passed, 1 skipped in 13.22s · `ruff check` clean on the
configured `F,E9` · 475 test functions, 1,421 assertions over ~19k lines of
Python and 5.9k of frontend.

---

## A1 — A live Google OAuth client secret is committed

`lodestone/data/google_client.json` holds a real `client_id`, `project_id` and
`client_secret` for the Lodestone Google Cloud project.

```bash
head -c 200 lodestone/data/google_client.json
```

This is **not** a credential compromise on its own — Google classifies installed
-app clients as public, and the secret is not treated as confidential. It is
already a conscious decision (`DECISIONS.md` → H12), taken so the app works on
first launch without asking the user to create a Cloud project.

What the existing decision does not cover is the **abuse path**: anyone can stand
up a consent screen branded "Lodestone" using this client id, and abuse
attributed to the project gets it rate-limited or suspended — which takes Gmail,
Calendar and Drive sync down for *every* user at once, with no fix shippable from
our side.

**To close:** not by removing the file (that breaks first launch). Add to H12
what happens when it goes wrong — a documented rotation procedure, and a
verification screen check. If the repo goes public, treat the id as burned and
plan for per-user clients as the escape hatch.

**Severity:** medium · **Cost:** low (documentation + a rehearsed procedure)

---

## A2 — The origin guard does not stop other loopback origins

`api/security.py` correctly refuses a foreign `Host` (DNS rebinding) and a
foreign `Origin` (CSRF). It does not refuse *another local web origin*:

```python
>>> from lodestone.api import security as s
>>> s.refusal("POST", {"host": "127.0.0.1:8787",
...                    "origin": "http://localhost:3000",
...                    "sec-fetch-site": "same-site"})
None        # allowed
```

Any dev server, notebook or local web app the user has open in a tab can
therefore `POST /api/brain/reset`, read `/api/providers/connections`, or list the
home directory via `/api/fs/browse`.

The module's docstring argues against a token on the grounds that it "adds
nothing against a local process". That is true and is not this case — a browser
origin is not a local process, and a per-launch value the page holds is exactly
what distinguishes our page from `localhost:3000`. The `Sec-Fetch-Site:
same-site` allowance is what leaves it open.

**To close:** a per-launch secret injected into the served page and required on
`/api/*`, or narrowing the loopback-origin allowance to the exact port we bound.
The second is cheaper and covers the realistic case.

**Severity:** medium · **Cost:** low–medium

---

## A3 — Dead branch in `security.refusal()`

`lodestone/api/security.py:105`:

```python
origin = headers.get("origin") or ""
if origin and not is_local_origin(origin):
    return _FOREIGN_SITE
...
# unreachable — identical condition, three lines later
if method.upper() in MUTATING_METHODS and origin and not is_local_origin(origin):
    return _FOREIGN_SITE
```

Harmless at runtime. It matters because its comment describes covering a
mutating request that arrives with **no** `Origin`, and it does not do that —
`origin and …` is false in precisely that case. A future reader trusts the
comment and believes a check exists that never runs.

**To close:** delete the branch, and move its comment (which is correct about
*why* the `Host` check carries that case) up to the first check.

**Severity:** low · **Cost:** trivial

---

## A4 — `app.js` is the largest maintainability liability left

3,007 lines · 92 top-level functions · 57 `innerHTML` writes · no build step, no
module boundaries, no type checking.

```bash
wc -l lodestone/web/app.js
grep -c innerHTML lodestone/web/app.js
```

`renderProviderConnectBox` alone spans lines 477–992. Test coverage is the three
node harnesses under `tests/js/`, which cover the sign-in path well and leave the
other ~85 functions unexercised — in a file whose whole history is bugs that
`node --check` passes (the TDZ `ReferenceError`, the detached container).

**The XSS surface is actually clean** and should stay that way: `md()` escapes
with `esc()` *before* applying inline markdown, and the link regex is constrained
to `https?`. Any new `innerHTML` path must keep that order.

**To close:** split by the boundaries that already exist in the file — provider
cards, model picker, chat, brain screen — and extend the harness pattern to the
render paths that move most. Not a rewrite; the vanilla-JS/no-build decision is
sound and should hold.

**Severity:** medium (rising) · **Cost:** high

---

## A5 — No type checker, and lint scoped to `F,E9`

`pyproject.toml` selects only `F` and `E9`, with an honest comment about why
(~480 findings would ship a red pipeline that everyone learns to ignore). The
full ruleset now reports ~2,300:

```bash
./.venv/bin/python -m ruff check --select ALL --statistics lodestone | head -20
```

Two entries there are substance rather than style: **132 `BLE001`** blind excepts
and **33 `C901`** complex functions. The blind-except count should fall on its
own as `log.suppressed()` adoption completes.

Meanwhile 637 of 871 defs (73%) are already annotated — enough that mypy would
pay for itself now rather than being a migration.

**To close:** add mypy in non-strict mode over `lodestone/models` and
`lodestone/api` first (the layers with the most invariants and the most
provider-shaped dict passing), then widen. Enable ruff rule families in waves,
as the existing comment intends.

**Severity:** low · **Cost:** medium

---

## A6 — `store.search()` is the known throughput ceiling

207 lines, and it runs on **every** agent turn. Measured in
[`SCALING.md`](SCALING.md): 3k memories ≈ 120 ms, 10k ≈ 430 ms, 50k ≈ 2.5 s, with
95% of the cost in the eight-factor Python scoring loop and 0.1% in the matmul.

This is listed not as a defect but so it is not rediscovered: the analysis is
done, the conclusion (don't reach for an ANN index — it optimises the 0.1%) is
correct, and the remaining work is vectorising the scoring loop or moving the
cheap filters into SQL. The function's length is what will make that hard.

**To close:** unchanged from `DECISIONS.md` → Deferred (Tier 2). Decompose the
function first; the optimisation is much safer against a function with seams.

**Severity:** low today · **Cost:** medium

---

## A7 — `suppressed()` call sites do not match their own contract

`log.py` documents `doing` as a plain-language fragment so the line reads as a
sentence — `suppressed("reading the saved port")` → *"failed while reading the
saved port: …"*. All ~60 adopted sites pass a truncated code fragment instead:

```bash
grep -rho 'suppressed("[^"]*"' --include='*.py' lodestone | head
# suppressed("path.chmod(0o600)")
# suppressed("from .capabilities import get_capabilities …")
# suppressed("claims = _decode_jwt_payload(token) …")
```

*"failed while path.chmod(0o600): Read-only file system"* is not a sentence, and
the point of the module was legible evidence in a bug report. The mechanical
migration landed; the editing pass did not.

**To close:** one site at a time, reading what the block is actually attempting.
Worth doing before the log becomes the thing bug reports are read from.

**Severity:** low · **Cost:** low but not automatable

---

## Not findings — checked and sound

Recorded so they are not re-audited:

- **XSS in the markdown renderer.** `md()` escapes before inlining; the link
  regex is scheme-constrained; `href="$2"` cannot break out because `"` is
  already `&quot;`. (A4 notes the invariant to preserve.)
- **Secrets in source.** No `sk-`, `xai-` or `AIza` literals anywhere in
  `lodestone/`. Secrets go through `settings.get_secret` → env → Keychain.
- **Dependency pinning.** `uv.lock` present, 409 packages.
- **DB migrations.** `core/db.py::_migrate` is additive `ALTER TABLE` only and
  idempotent, so no backup step is required for the current shape. Revisit if a
  destructive migration is ever needed.
- **Test hygiene.** `conftest.py` neutralises real vendor `login` spawns, forces
  `mock`/`hash` providers, and redirects `LODESTONE_HOME` to a temp dir.
