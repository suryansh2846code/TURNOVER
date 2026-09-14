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

**Re-reviewed 2026-09-13 (QA, MODE: TEST) against `223610c`.** Current state:
**1345 passed, 18 skipped, 5 xfailed in 44s** · `ruff check lodestone tests`
clean · `mypy lodestone` clean over 111 files. **A2 and A3 are now closed** — see
their entries. **A8 is new and is the most serious item in this file.**

**Re-reviewed 2026-09-14 after the complexity-reduction pass.** CI on `main`:
**1440 passed, 20 skipped in ~2min** · ruff clean · mypy clean over 114 files ·
coverage **76%**, now printed on every run.

**A4, A5 and A11 are closed.** A11 was a real bug a user could hit — the
brain-search delete button had never worked. **A12 is new**, and is the most
serious item in this file: the background sync loop runs unattended on every
machine at 30% coverage, where a failure is silent by construction.

Still open and unchanged: A1 (the committed Google client), A6 (recall
throughput), A7 (`suppressed()` call sites), A9 (the review queue has no
consumer), A10 (the extractors disagree).

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

## A2 — ~~The origin guard does not stop other loopback origins~~ · **CLOSED**

> **Closed 2026-09-13.** `security.same_origin()` now compares *authorities*
> (host **and** port) via `_authority()`, so `localhost:3000` is refused against
> a server bound on `127.0.0.1:8787`. Re-verified:
>
> ```bash
> python -c "from lodestone.api import security as s; print(s.refusal('POST', \
>   {'host':'127.0.0.1:8787','origin':'http://localhost:3000', \
>    'sec-fetch-site':'same-site'}))"
> # Lodestone ignores requests that come from a website.
> ```
>
> The original text is kept below for the reasoning, which is still worth
> reading.

### Original finding

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

## A3 — ~~Dead branch in `security.refusal()`~~ · **CLOSED**

> **Closed 2026-09-13.** The duplicated condition is gone; `refusal()` now has a
> single `is_local_origin` / `same_origin` path and the comment sits with the
> check it describes. `grep -n is_local_origin lodestone/api/security.py` shows
> two sites, both live.

### Original finding

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

## A4 — ~~`app.js` is the largest maintainability liability left~~ · **CLOSED**

> **Closed 2026-09-14.** The frontend is eleven plain scripts, each with one
> responsibility; `app.js` is the shell at 237 lines, and the largest module is
> `providers.js` at 886. `index.html` declares the load order and is the only
> place it is written down — the browser and the test harnesses both read it
> from there.
>
> The blocker was never the code. The nine `tests/js` harnesses evaluate the
> frontend with `new Function`, which compiles a script and cannot process
> `import` — so the loader had to change first and land as a proven no-op before
> a single line moved. Method, and the five checks to run before any further
> move: [`development/frontend-testing.md`](development/frontend-testing.md).
>
> The original finding is kept below; the reasoning in it is still why the file
> grew that large in the first place.

### Original finding

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

## A5 — ~~No type checker, and lint scoped to `F,E9`~~ · **CLOSED**

> **Closed.** `pyproject.toml` selects seventeen rule groups, and `mypy` runs in
> CI over 114 files — strict on the modules that are contracts, with a
> grandfathered list that only ever gets shorter. Coverage prints on every run
> too (76%), deliberately without a threshold: the per-module table is the
> point, not the percentage.
>
> ```bash
> ruff check lodestone tests && mypy lodestone
> ```

### Original finding

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

## A8 — ~~The unattended-action gate only splits recipients on `,` and `;`~~ · **CLOSED**

> **Closed 2026-09-13** by `permissions._every_address_in()`, which enumerates
> every address in a recipient field whatever separates them, and still returns
> an unparseable token so an unrecognisable recipient fails closed rather than
> reading as nobody. The two `xfail(strict=True)` tests that recorded this bug
> lost their markers in the same commit — which is what strict was for. Verified
> load-bearing: reintroducing the old splitter turns 5 tests red.
>
> ```bash
> ./.venv/bin/python -m pytest tests/test_mcp_tool_result_injection.py -q   # 37 passed
> ```
>
> The original finding is kept below; the reasoning about *why* this shape is
> what an injection reaches for is still the reason the fix looks as it does.

### Original finding

**Severity: high** · **Owner: Agents** · **Cost: low**

`permissions.recipients_of()` splits an action's recipients on `[,;]`, then
`normalise()` returns the **first** address it finds in each token and discards
the rest. So a token holding two addresses separated by *whitespace* is reported
to `check()` as one recipient — the permitted one. The stranger is never judged.

```bash
python - <<'EOF'
from lodestone.agents.permissions import recipients_of
for sep in ("\n", " ", "\t"):
    raw = f"colleague@work.test{sep}attacker@evil.test"
    print(repr(raw), "->", recipients_of("send_email", {"to": raw}))
EOF
# 'colleague@work.test\nattacker@evil.test' -> ['colleague@work.test']
# 'colleague@work.test attacker@evil.test'  -> ['colleague@work.test']
# 'colleague@work.test\tattacker@evil.test' -> ['colleague@work.test']
#                                    attacker@evil.test silently dropped
```

`send_email` survives this **by accident**: `actions._send_email` re-validates
`to` against the anchored `^[^@\s]+@[^@\s]+\.[^@\s]+$`, which whitespace fails,
so the mail is refused. The user sees a confusing "not a valid email address"
rather than an approval request, but nothing leaves.

**`create_event` does not survive it.** `actions._create_event` performs no
address validation at all, so the action runs and the stranger is added as an
attendee — and a Google Calendar invite emails the attendee the event's title,
time and description. `create_event` is in `OUTBOUND_ACTIONS` precisely because
"a calendar entry with attendees reaches somebody other than the user".

Full repro, unattended, through the real routine path:

```bash
pytest tests/test_mcp_tool_result_injection.py -q \
  -k "whitespace_separated or calendar_invite" -p no:randomly --runxfail
```

Both are currently `xfail(strict=True)` so the tree stays green for the other
seven sessions; `--runxfail` shows them failing for real. Strict means they turn
into failures the moment the splitter is fixed, which forces whoever fixes it to
remove the marker rather than inherit a dead test.

**Why it matters more now.** This is exactly the shape of an injected action: a
stranger's text names a recipient the user *has* allow-listed, plus their own,
separated by a space. Piping MCP read-tool results into every turn multiplies the
text that can attempt it.

**Likely root cause.** `normalise()` is documented as stripping display names
(`"Dana <dana@example.com>"` → `dana@example.com`), and `_ADDRESS.search` is the
right tool for *that*. It becomes wrong when handed a token that legitimately
contains two addresses, because `search` returns one and says nothing about the
remainder — it truncates where it should refuse.

**Recommended fix** (Agents' call; do not apply from QA):

1. Split on whitespace as well as punctuation —
   `re.split(r"[,;\s]+", raw)` — so every address is judged; **and**
2. Make `normalise()` fail closed: return `""` (or raise) when the token still
   contains more than one `@` after stripping a display name, so a future caller
   cannot reintroduce silent truncation; **and**
3. Give `_create_event` the same anchored per-address validation
   `_send_email` has, so the second layer exists there too.

(1) alone closes the reported hole. (2) and (3) are what stop the next one — the
`send_email` case is only safe today because of a validator that looks redundant
and would plausibly be deleted as such.

**Regression tests:** `tests/test_mcp_tool_result_injection.py` —
`test_a_whitespace_separated_second_recipient_is_visible_to_the_gate`,
`test_an_injected_calendar_invite_cannot_reach_a_stranger`, and
`test_the_second_validator_still_stops_the_mail_variant` (which pins the
accidental `send_email` defence so it is not removed as redundant).

---

## A9 — The canonical review queue has a producer and no consumer

**Severity: medium** · **Owner: Frontend (UI) + Architect (contract)** · **Cost: medium**

`/CLAUDE.md` describes the review queue as the trust core's safety valve. It
works — `curate.py` queues correctly — but **no UI ever drains it**:

```bash
grep -rn "canonical\|open-loops\|contradiction" lodestone/web/*.js lodestone/web/*.html
# (no output)
```

Sixteen endpoints have zero frontend consumers: `/api/brain/canonical/**`,
`/api/brain/open-loops*`, `/api/brain/contradictions*`, `/api/brain/recall`,
`/api/brain/memories/{id}/explain`.

The queue is reachable from **ordinary chat**, not just connectors — `_apply_claim`
queues on "uncertain person identity" and "would override a confirmed fact":

```bash
python - <<'EOF'
import os, tempfile; os.environ['LODESTONE_HOME'] = tempfile.mkdtemp()
from lodestone.brain.canonical.service import get_canonical
c = get_canonical(); cur = c.curator
cur.apply_candidate({"kind":"claim","type":"role","value":"Staff Engineer",
  "confidence":"confirmed","section":"about_you"}, source_type="chat",
  source_timestamp="2026-01-01T00:00:00Z")
print(cur.apply_candidate({"kind":"claim","type":"role","value":"Intern",
  "confidence":"inferred","section":"about_you"}, source_type="chat",
  source_timestamp="2026-06-01T00:00:00Z"))
print("pending:", len(c.pending()))
EOF
# {'outcome': 'queued', ... 'would override a confirmed fact — needs review'}
# pending: 1
```

From the user's side a fact they stated is simply forgotten, with no way to see
or approve it. **To close:** a review surface in the Brain screen, or an explicit
decision that chat-sourced conflicts auto-resolve and the queue is connector-only
(at which point the connector producer below is the missing half).

**Also:** nothing calls `learn_from_text(source_type=<a connector>)` — only chat
and manual. So the connector-review path `/CLAUDE.md` documents does not exist
yet in either direction.

---

## A10 — The LLM and heuristic extractors disagree on claim type, so the richer path supersedes worse

**Severity: medium** · **Owner: Brain** · **Cost: low**

`SINGULAR_TYPES` (one truth current at a time) is
`{role, project_status, location, availability, status, next_step}`. The LLM
extraction prompt's allowed type vocabulary is
`preference|goal|role|project_status|decision|risk|next_step|relationship`.

`location`, `availability` and `status` are singular but **cannot be produced by
the LLM path** — so "I moved to Berlin" extracted by the LLM is typed
`preference`, which accumulates. The offline heuristic (which *does* emit
`location`) supersedes correctly. The opt-in, more expensive path is the less
correct one:

```bash
python - <<'EOF'
import os, tempfile; os.environ['LODESTONE_HOME'] = tempfile.mkdtemp()
from lodestone.brain.canonical.service import get_canonical
c = get_canonical(); cur = c.curator
for t in ("location", "preference"):
    for v, ts in (("Lisbon","2026-01-01T00:00:00Z"), ("Berlin","2026-06-01T00:00:00Z")):
        cur.apply_candidate({"kind":"claim","type":t,"value":f"lives in {v}",
          "confidence":"confirmed","section":"about_you"},
          source_type="chat", source_timestamp=ts)
    print(t, [x["value"] for x in c.about_you() if x["type"] == t])
EOF
# location   ['lives in Berlin']                          <- correct
# preference ['lives in Berlin', 'lives in Lisbon']       <- both current
```

Recall then injects two contradictory "current" facts into the agent's context.

**Related, same cause:** `TIME_SENSITIVE = SINGULAR_TYPES | {"goal"}` — the
`{"goal"}` half is **unreachable**. `_claim_key` includes the value hash for
non-singular types, so a *different* goal yields a different key,
`current_claim_by_key` returns `None`, and the timestamp guard at `curate.py:159`
is never evaluated. More generally **every supersession branch below
`curate.py:143` is dead for every non-singular type**: a matching key implies a
matching normalised value, which returns `reconfirmed` three lines earlier.

**To close:** align the LLM prompt's type vocabulary with `SINGULAR_TYPES`, and
either make `goal` singular or drop it from `TIME_SENSITIVE` so the set does not
claim a guard it cannot run.

---

## A11 — ~~The brain-search delete button calls an endpoint that does not exist~~ · **CLOSED**

> **Closed 2026-09-13.** `DELETE /api/brain/memories/{memory_id}` exists and the
> button calls it. A hard delete rather than a retraction: `store.count()` counts
> every row whatever its status, so a soft delete would have left the memory
> count unchanged and read as "nothing happened".
>
> The regression test is deliberately wider than the bug.
> `test_frontend_calls_real_endpoints.py` extracts every `(method, path)` pair
> the frontend asks for and checks each against the live route table — the class
> of defect, not the instance, and it catches a right path with the wrong verb
> as well as a wrong path.

### Original finding

**Severity: low** · **Owner: API (route) + Frontend (path)** · **Cost: trivial**

`app.js:2406` issues `DELETE /api/memories/{id}`. There is no such route — the
only memory routes are `GET /api/brain/memories/{id}` and `…/explain`, and no
`DELETE` exists anywhere for memories.

```bash
python - <<'EOF'
import os, tempfile; os.environ['LODESTONE_HOME'] = tempfile.mkdtemp()
from fastapi.testclient import TestClient
from lodestone.api.app import app
H = {'host':'127.0.0.1:8000','origin':'http://127.0.0.1:8000','sec-fetch-site':'same-origin'}
print(TestClient(app).request('DELETE', '/api/memories/abc', headers=H).status_code)
EOF
# 404
```

`api()` rejects on a non-ok response and the click handler has no `catch`, so the
✕ button does nothing at all — no deletion, no error, no toast. The capability
exists server-side (`Brain.forget()`, `store.delete()`); only the route is
missing. This is a half-landed feature, not a design gap.

**To close:** API adds `DELETE /api/brain/memories/{id}` → `Brain.forget()`;
Frontend corrects the path and adds a `catch` so a failed delete says so.

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

Added 2026-09-13 (QA), each checked directly rather than assumed:

- **The concurrency lanes are real and pinned.** `calls_a_model` /
  `probes_a_provider` decorate 38 handlers, and
  `test_threadpool_isolation.py::test_the_slow_routes_are_the_ones_on_a_lane`
  asserts by name that each measured-in-seconds route is a coroutine. An earlier
  pass of this audit wrongly read the decorators as unused — they are applied
  under their sugar names, not via `MODEL_CALLS` / `PROBES` directly.
- **SSE frame reassembly in the browser.** `app.js:2147-2159` buffers across
  chunks, splits on `\n\n` and keeps the remainder — the documented failure mode
  is handled.
- **`"key" in row` on a `sqlite3.Row`.** Fixed and using `row.keys()` at all
  three sites in `brain/graph.py`; `SIM118`/`SIM401` remain disabled.
- **`chat()` never raises.** All five `raise_for_status()` calls in the provider
  layer sit inside `try` blocks within their own `chat()` / `stream()`.
- **Tool results never reach `parse_actions`.** `run_turn` builds `reply` from
  `result.text` only; `routines.run_routine` parses `res.reply`; `addTrace`
  escapes and truncates. Pinned by
  `tests/test_mcp_tool_result_injection.py` and
  `tests/test_frontend_tool_result_injection.py`, both mutation-verified.
- **The agent tool surface is a closed allow-list.** `build_tools` only emits
  names present in `TOOL_DEFS`, and `run_tool` refuses anything else — so no MCP
  tool is callable mid-turn today.
- **No TODO/FIXME/HACK markers** anywhere in `lodestone/`, `tests/` or
  `scripts/`.

**Still open and getting worse:** A4 — `app.js` is now **3,462 lines** (3,007 at
the last review) with 62 `innerHTML` writes and 93 top-level functions. The
`tests/js/` harnesses have grown 3 → 8, but they still execute roughly six of
those 93 functions.

---

## A12 — `scheduler.py` runs unattended on every machine at 30% coverage

The background sync loop is the least-protected code in the repository, and it
is code no user ever watches run.

```bash
pytest -q --cov --cov-report=term-missing | grep scheduler
# lodestone/scheduler.py   184   129   30%   41-45, 54, 72-75, 79-88, 91-188, ...
```

`_sync_all` — 99 lines, the function that drives every connector, decides what
is stale, and is meant to be cooperatively cancellable — is almost entirely
uncovered. So is the loop that calls it.

This matters more than it looks. A failure here is silent by construction: the
loop swallows what it must to survive a bad connector, it runs on a timer with
nobody watching, and the symptom a user reports is "my brain stopped updating",
days later, with nothing in the UI to say so.

**To close:** a fake connector and a driven clock, then test the things that
only this module does — cancellation actually stopping mid-pass, one failing
connector not taking the others down, the watermark advancing only on success,
and two scheduler instances never running at once after a reload.

**Severity: medium** (silent, unattended, user-visible only long after the fact)
· **Owner: Connectors + API** · **Cost: medium**

> Found while measuring coverage during the complexity-reduction pass, not while
> working on the scheduler. Recorded rather than fixed because it is a testing
> gap, not a complexity one — it was outside that task's scope, and deserves to
> be someone's actual task rather than a footnote in another.
