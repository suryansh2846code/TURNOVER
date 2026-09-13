# Handoffs

Append-only. Newest at the bottom. One block per handoff. **Never edit or delete
another role's block** — add a `DONE:` block underneath it instead.

Format (copy this):

```
TASK:
OWNER:
FILES:
DEPENDENCIES:
CHANGES:
TESTS:
RISKS:
HANDOFF:
CONTRACT:     additive | renamed | removed — and what breaks if only one side ships
BLOCKING:     yes/no — yes means users see something broken until it lands
```

The Architect prunes closed handoffs at release and records anything load-bearing
in `docs/DECISIONS.md`.

---

```
TASK:         Stand up the eight-role fleet: ownership, worktrees, contracts
OWNER:        Architect
FILES:        CLAUDE.md · .gitignore · .claude/fleet/** · pointer CLAUDE.md in
              lodestone/{web,api,agents,models,brain,core,connectors,mcp_server},
              packaging/, tests/
DEPENDENCIES: none
CHANGES:      - /CLAUDE.md gained the role table, the ownership map, the six
                seams, the ten rules of parallel work, and Fleet operations
                (modes, handoffs, claims, worktrees, per-role verification,
                cross-layer contracts, the decomposition format, custom
                specialists, escalation).
              - .claude/fleet/ holds one rules file per role: architect,
                frontend, api, agents, brain, models, connectors, qa, plus a
                dormant desktop specialist and the custom-role template.
              - .gitignore no longer ignores all of .claude/ — only
                worktrees/ and fleet/locks/ — so these rules are committed and
                every worktree sees them.
              - Stale nested worktree .claude/worktrees/connectors retired
                (its HEAD 9c7a2dc was already an ancestor of main); merged
                branches `agents` and `connectors` deleted; seven sibling
                worktrees created on agent/* branches.
              - Two in-flight sessions' work committed separately first:
                7642f4c (models: xAI stops claiming an account it does not
                have) and 14f0e6d (web: design tokens, locked-model honesty,
                keyboard access).
TESTS:        Models slice 38 passed · frontend slice 91 passed · a worktree
              run verified (31 passed in ../lodestone-frontend, with
              assets.WEB resolving inside that worktree).
RISKS:        Three sessions were editing one checkout on main before this.
              Any session still holding that checkout must move to its own
              worktree before its next edit, or rule 2 breaks again.
HANDOFF:      Every role: read /CLAUDE.md's fleet sections and your own file in
              .claude/fleet/<role>/. Work from ../lodestone-<role> on
              agent/<role>. If a file you expected to own is listed under
              another role, escalate rather than editing it.
CONTRACT:     additive — no application code changed by this work.
BLOCKING:     no
```

---

```
TASK:         Regression suite pinning where a third party's text stops being
              data and starts being an action — for MCP read tools in a turn
OWNER:        QA (role H) · MODE: TEST
FILES:        tests/test_mcp_tool_result_injection.py        (new, 37 tests)
              tests/test_frontend_tool_result_injection.py   (new, 7 tests)
              tests/js/tool_result_injection.mjs             (new harness)
              docs/AUDIT.md                                  (A2/A3 closed; A8–A11 new)
DEPENDENCIES: agents/permissions.py · agents/approvals.py · routines.py ·
              actions.py · agents/runtime.py · agents/tools.py ·
              connectors/mcp_source.py · web/app.js  (all READ ONLY — no
              production code was changed; `git status` shows only new tests
              plus docs/AUDIT.md)
CHANGES:      Covers the four cases in the brief:
              1. An `<action type="send_email">` in a TOOL RESULT sends no mail,
                 interactive AND unattended. Pinned at both ends: `run_turn`
                 builds `reply` from `result.text` only, and `addTrace` escapes
                 + truncates rather than parsing.
              2. Injected prose that the model FULLY OBEYS still cannot send —
                 the permission gate queues it, and the approval card names the
                 recipient the user has to judge.
              3. No MCP tool is callable mid-turn: `TOOL_DEFS` has no `mcp_*`
                 entry, `build_tools` emits only `TOOL_DEFS` names, `run_tool`
                 refuses unknown names, `mcp_action` is in `NEVER_UNATTENDED`,
                 and `perform()` fails closed without `confirmed`.
              4. Hostile results (2MB payload, control characters, null bytes,
                 nested/unterminated `<action>`, lone surrogates, HTML) neither
                 crash nor stall the turn, and parsing stays under 1s.
TESTS:        Full sequence, from ../lodestone-qa on agent/qa:
                pytest                      -> 1345 passed, 18 skipped, 5 xfailed, 44s
                                               (baseline was 1306/18; +39 new)
                ruff check lodestone tests  -> All checks passed!
                mypy lodestone              -> Success, 111 files
              Every test was MUTATION-VERIFIED: each defence was removed in turn
              and the suite confirmed red, then the tree restored. 8 server-side
              and 3 frontend mutations; all caught.
RISKS:        Two of my own harnesses were BLIND on the first attempt and are
              only trustworthy because the mutation pass caught them — recording
              this because it is the fourth time in this repo:
              · `test_a_permitted_recipient_is_not_a_blanket_permission` asserted
                only on "no mail sent", and passed with `check()` mutated to
                allow when ANY recipient is permitted, because `_send_email`
                refused the address for an unrelated reason. Now asserts the
                VERDICT first, then the effect.
              · The node harness counted action cards by array position around
                the `addMsg` call, so cards created during `addTrace` — the
                actual bug — were invisible. Now counts by `action-card` class
                across both phases.
              If you extend either file, re-run the mutation pass rather than
              trusting a green result.
HANDOFF:      Agents — A8 is yours and is the reason this task mattered. See the
              dedicated block below.
              Everyone else — these tests are the tripwire for the MCP-read-tools
              feature. Three will go red the moment MCP tools become mid-turn
              callable (`test_no_mcp_tool_is_offered_to_a_model_mid_turn`,
              `test_every_offered_tool_is_a_known_local_tool`,
              `test_run_tool_refuses_a_tool_name_it_does_not_define`). That is
              the design conversation, not a test to update: a READ tool may be
              added, a WRITE tool may not.
CONTRACT:     additive — tests and docs only.
BLOCKING:     no
```

```
TASK:         A8 — the unattended-action gate only splits recipients on "," and
              ";", so a whitespace-separated second recipient is never judged
OWNER:        QA (found) -> AGENTS (owns agents/permissions.py and actions.py)
FILES:        lodestone/agents/permissions.py  (recipients_of, normalise)
              lodestone/actions.py             (_create_event)
DEPENDENCIES: none — self-contained in Agents' own files
CHANGES:      none by QA. Report only, per the QA role's rule 5.
TESTS:        Repro (both currently xfail(strict=True), green tree preserved):
                pytest tests/test_mcp_tool_result_injection.py -q \
                  -k "whitespace_separated or calendar_invite" \
                  -p no:randomly --runxfail
                -> 5 failed
              Direct:
                python - <<'PY'
                from lodestone.agents.permissions import recipients_of
                print(recipients_of("send_email",
                      {"to": "colleague@work.test\nattacker@evil.test"}))
                PY
                -> ['colleague@work.test']     # attacker silently dropped
RISKS:        `send_email` is safe today ONLY because `actions._send_email`
              re-validates `to` against an anchored pattern that whitespace
              fails. That validator looks redundant and is not — deleting it
              turns A8 into mail delivery.
              `create_event` has NO such validator, so today an injected
              `<action type="create_event" attendees="allowed@x  attacker@y">`
              in a routine invites the stranger with no approval, and a Google
              Calendar invite emails them the event details. Verified through
              the real `run_routine` path.
HANDOFF:      Agents: fix in three parts (reasoning in docs/AUDIT.md → A8) —
              (1) split on whitespace too: `re.split(r"[,;\s]+", raw)`;
              (2) make `normalise()` fail closed (return "") when a token still
                  holds more than one `@` after the display name is stripped, so
                  silent truncation cannot be reintroduced;
              (3) give `_create_event` the per-address validation `_send_email`
                  already has.
              (1) alone closes the reported hole; (2) and (3) stop the next one.
              Then DELETE the two `xfail` markers — they are `strict=True`, so
              they fail as XPASS if you fix the bug and leave them.
CONTRACT:     unchanged — `check()` / `recipients_of()` signatures stay; only
              which recipients they report changes (strictly more).
BLOCKING:     no for shipping, YES for the MCP-read-tools feature — that feature
              multiplies the attacker-written text that can attempt exactly this
              shape, so it should land after A8 rather than before.
```

```
TASK:         A9 / A10 / A11 — findings from the same pass, outside Agents
OWNER:        QA (found) -> see each
FILES:        A9  lodestone/web/**            -> FRONTEND (+ Architect: contract)
              A10 lodestone/brain/canonical/  -> BRAIN
              A11 lodestone/api/routes/brain.py + web/app.js -> API + FRONTEND
DEPENDENCIES: none between them
CHANGES:      none by QA — reports, with repros, in docs/AUDIT.md.
TESTS:        Each entry in docs/AUDIT.md carries a copy-pasteable repro that was
              run and whose real output is quoted. No regression tests written
              for these: they need an owner's design decision first, not a pin.
RISKS:        A9  (medium) The canonical review queue is reachable from ORDINARY
                  CHAT ("would override a confirmed fact", "uncertain person
                  identity") and no UI drains it — 16 canonical/open-loop/
                  contradiction endpoints have zero frontend consumers. A fact
                  the user states is silently swallowed. Also: nothing feeds
                  `learn_from_text` with a connector source_type, so the
                  connector-review path /CLAUDE.md documents does not exist in
                  either direction.
              A10 (medium) The LLM extraction prompt cannot emit `location`,
                  `availability` or `status`, which ARE in `SINGULAR_TYPES`. So
                  the LLM path types "I moved to Berlin" as `preference` and
                  accumulates two contradictory current facts, while the free
                  heuristic path supersedes correctly — the opt-in expensive
                  path is the less correct one, and recall injects both.
                  Same cause: `TIME_SENSITIVE | {"goal"}` is unreachable, and
                  every supersession branch below curate.py:143 is dead for
                  every non-singular type.
              A11 (low) `app.js:2406` calls `DELETE /api/memories/{id}`, which
                  404s — no DELETE route for memories exists. `api()` rejects
                  and the handler has no catch, so the ✕ in brain search does
                  nothing at all, silently. `Brain.forget()` already exists;
                  only the route is missing.
HANDOFF:      Frontend: A9 needs a review surface, or the Architect records that
              chat conflicts auto-resolve and the queue is connector-only.
              Brain:    A10 — align the LLM prompt's type vocabulary with
                        SINGULAR_TYPES, and make `goal` singular or drop it from
                        TIME_SENSITIVE so the set stops claiming a guard it
                        cannot run.
              API:      A11 — add `DELETE /api/brain/memories/{id}` ->
                        `Brain.forget()`; Frontend corrects the path and adds a
                        catch so a failed delete says so.
              Architect: A2 and A3 in docs/AUDIT.md are now CLOSED (verified
                        this pass); the file's "state at review" line was 791/1
                        and is now 1345/18/5.
CONTRACT:     A11 is additive (a new route). A9/A10 are behaviour, no contract move.
BLOCKING:     no
TASK:         Expose configured MCP servers' READ tools as a callable surface
              for the agent loop (connector half only)
OWNER:        Connectors
FILES:        lodestone/connectors/mcp_tools.py (new)
              lodestone/connectors/mcp_source.py (upsert_server/delete_server
                now flush the tool cache — 16 lines, no behaviour moved)
              docs/CONNECTORS.md (Phase 5)
              tests/connectors/test_mcp_tools.py (new, 22 tests)
              tests/connectors/fake_mcp_server.py (two modes added: `huge`,
                `stall`)
DEPENDENCIES: mcp_source (MCPServerSpec, _converse, classify_tools,
              spec.permits, _records), mcp_errors.explain,
              models/cache.py::ttl_cached. Nothing under lodestone/agents/**
              was read or written.
CHANGES:      The interface the Architect fixed, exactly as specified:

                @dataclass(frozen=True) MCPToolRef
                    qualified_name · server_id · server_label · tool
                    description · parameters · writes
                list_tools()  -> list[MCPToolRef]
                call_tool(qualified_name, arguments) -> str
                invalidate()  -> None

              - list_tools() is TTL-cached for 300s via models/cache.py's
                ttl_cached. invalidate() flushes it and is called from
                upsert_server() and delete_server(), which is every path that
                adds a server, removes one, or changes allowed_tools (the spec
                is saved whole). Nothing in api/routes/connectors.py needed to
                change.
              - Every server is listed CONCURRENTLY under its own
                LIST_TIMEOUT_SECONDS ceiling, so N connectors cost one timeout,
                not N. Sequentially this was 8.4s for two dead servers; it is
                now 4.0s, and the test asserts the difference.
              - list_tools() never raises. A server that crashes, is missing, or
                stalls its handshake contributes nothing and is logged at debug;
                the servers either side are unaffected.
              - Tools excluded by spec.allowed_tools are not listed at all.
                Write tools ARE listed, flagged writes=True, so a confirmation
                card can be built from them.
              - call_tool() is reads only and fails closed: unknown name →
                refusal with no process started; writes=True → refusal; server
                since deleted → refusal; tool since disallowed → refusal
                (the saved spec is re-read, the cache is never the authority);
                and inside the session it re-runs classify_tools() against the
                server's live tool list, so a tool that became a write after the
                cache was filled is still refused. mcp_action stays in
                NEVER_UNATTENDED — this widens nothing.
              - Replies are truncated at MAX_RESULT_CHARS = 8000 (~2k tokens)
                with the truncation stated in the returned text, so the model
                narrows its query instead of concluding it saw everything. The
                reasoning is in the constant's comment.
              - Every failure returns a sentence from mcp_errors.explain() —
                never a raise, never a traceback, never raw stderr. The whole
                conversation is time-boxed at TURN_TIMEOUT_SECONDS = 20s
                (spawn + handshake + call), because read_timeout_seconds cannot
                bound a server that hangs before the call.
TESTS:        pytest tests/connectors → 299 passed, 17 skipped.
              Full suite → 1328 passed, 18 skipped (baseline 1306/18 + 22 new).
              ruff clean · mypy clean over 112 files.
              The cache is proven by
                tests/connectors/test_mcp_tools.py::test_the_second_call_spawns_no_subprocess
              — it counts calls to mcp_source._converse, the only place a server
              process is started, so a cache that re-listed on every hit could
              not pass it. Verified by removing @ttl_cached: 5 tests go red,
              that one first. The concurrency test was verified the same way
              (sequential listing → 8.42s, fails the 6.0s bound).
              Writes: test_a_write_tool_is_never_callable (refused, and the
              fake server's record is NOT deleted).
              Down server: test_a_server_that_is_down_degrades_to_a_message,
              test_one_broken_server_does_not_remove_the_others,
              test_a_hanging_server_does_not_hold_the_turn.
RISKS:        - A 20s conversation ceiling is a long time inside one turn. It is
                the worst case for a server that hangs mid-handshake, and the
                cached path costs nothing; if Agents wants it tighter, it is one
                module constant (TURN_TIMEOUT_SECONDS) and I would rather change
                it than have you wrap it.
              - ttl_cached registers with models/cache.py's registry, so
                clear_provider_cache() also flushes the MCP tool list. Harmless
                (it only costs one re-listing) but worth knowing.
              - qualified_name is built to OpenAI's tool-name rule
                (^[A-Za-z0-9_-]{1,64}$) and is stable across restarts; long or
                punctuated server ids get a digest suffix rather than a counter,
                so the loop's repeat detector sees the same signature twice.
HANDOFF:      Agents: the four functions above are ready to call from
              lodestone/agents/**. Offer only refs with writes=False as tools;
              pass `parameters` through as the tool's JSON Schema unchanged, and
              `description` prefixed with server_label if your tool list needs
              the provenance. call_tool() always returns a string — including
              for every refusal and every failure — so it can go straight back
              as the tool result without a try/except.
              Do not add your own cache in front of list_tools(); it is already
              cached and yours would not be invalidated when a connector changes.
              API/Frontend: nothing to do. No route, schema or payload moved;
              test_api_surface.py is untouched and green.
CONTRACT:     additive — a new module and four new functions. Nothing existing
              changed shape; upsert_server/delete_server keep their signatures
              and return values. Shipping the Agents half without this is the
              only breaking order, and that is an ImportError at start-up, not a
              user-visible failure.
BLOCKING:     no — with only this half landed, MCP servers behave exactly as they
              did before.
```
```
TASK:         Agents can call the user's MCP connector tools mid-turn (read-only)
OWNER:        Agents
FILES:        lodestone/agents/mcp_tools.py (new) · lodestone/agents/tools.py ·
              lodestone/agents/presets.py · lodestone/agents/evaluation.py ·
              body of lodestone/api/routes/agents.py::available_tools ·
              tests/test_agent_mcp_tools.py (new) · tests/test_agent_evaluation.py ·
              docs/AGENTS.md
DEPENDENCIES: Connectors' lodestone/connectors/mcp_tools.py — consumed exactly as
              specified (MCPToolRef: qualified_name, server_id, server_label,
              tool, description, parameters, writes; list_tools(); call_tool()).
              Not present in this worktree yet, so it is imported BY NAME at call
              time (importlib) and a missing module means "no extra tools", not a
              broken turn. Tests install a stand-in that mirrors the dataclass.
CHANGES:      - agents/mcp_tools.py resolves connector tools at turn time:
                filters out every ref with writes=True, makes qualified names
                provider-safe (`notion:search` → `notion_search`, and the
                qualified name is what goes back to call_tool), caches discovery
                for 20s (listing starts every server as a subprocess), caps a
                server's answer at 6000 chars, and turns a failure into
                connectors/mcp_errors.explain()'s sentence.
              - build_tools() gains them when the agent's list contains the
                sentinel "mcp" (mcp_tools.SENTINEL), or names one tool outright.
                All four presets now carry the sentinel via _BASE_TOOLS.
              - validate_tool_arguments()/run_tool() resolve unknown names
                through the same path. Argument cleaning is unchanged, with one
                addition: a schema with NO `properties` key passes arguments
                through instead of stripping them all — built-ins all declare
                theirs, somebody else's server may not, and stripping would turn
                its search tool into a search for nothing. An unknown tool is
                still "Unknown tool: <name>", never an exception.
              - permissions.py untouched: mcp_action stays in NEVER_UNATTENDED
                and connector writes stay on propose → confirm.
              - GET /api/agents/tools body now returns describe_tools().
TESTS:        tests/test_agent_mcp_tools.py — 16 cases, including the three asked
              for (a write tool is never offered/lookup-able/runnable; an MCP
              result flows into a real turn via ScriptedProvider; an agent
              without the sentinel gets exactly the 13 built-ins). Harness
              verified by mutation: dropping the write filter fails 3 cases,
              disabling the sentinel fails 3.
              Scorecard: two new checks (connector_tools,
              connector_writes_withheld) → 17/17, score still 10.0, no regression.
              Slice: tests/test_agent_*.py 94 passed. Full: 1324 passed, 18
              skipped (baseline 1306+18). ruff clean · mypy clean, 112 files.
              test_api_surface.py green — paths unchanged.
RISKS:        - The supplier contract is duck-typed (getattr on the ref fields).
                If Connectors renames a field, tools vanish silently rather than
                erroring; test_agent_mcp_tools.py mirrors the dataclass so the
                drift shows there.
              - call_tool() must enforce its own timeout. A hung server holds an
                agent's worker thread and one of the three connector slots.
              - Agent turns now depend on connector discovery latency the first
                time in any 20s window. Cheap when no servers are configured
                (the module import fails and we return []).
HANDOFF:      **Frontend** — GET /api/agents/tools rows are ADDITIVE: `name` and
              `description` are byte-identical to before, plus
              `source`: "builtin" | "mcp" and `connector`: the connector's label
              ("" for built-ins). app.js:2905 (agent-builder checkboxes) and
              :3338 (Tools drawer) keep working untouched; grouping by
              `connector` is the improvement available whenever you want it.
              One row is special: `{"name": "mcp", "source": "mcp",
              "connector": ""}` is the *category* — checking it gives an agent
              every read tool the user's connectors expose, now and in future.
              It only appears when at least one connector tool exists.
              **Connectors** — nothing needed from you beyond the agreed module;
              call `agents.mcp_tools.clear_cache()` (or wait 20s) if you want a
              newly added server's tools to appear in an in-flight session.
PARALLEL WIDTH (the question asked): the loop's ThreadPoolExecutor +
              copy_context()-per-call structure still holds unchanged — MCP calls
              are ordinary blocking callables, results are still reassembled by
              request order, and the per-call context copy still carries the
              delegation chain. The width itself does NOT need lowering, and
              lowering it would be the wrong lever: it would slow every SQLite
              read to protect a case only some installs have. Instead the
              ceiling sits with the connector tools —
              mcp_tools.MAX_CONCURRENT_CALLS = 3, a process-wide semaphore — so
              a High-effort round still fans out six ways while at most three
              subprocesses are talking at once. Covered by
              test_connector_calls_are_bounded_below_the_loops_parallel_width,
              which also asserts the gate did not serialise the round.
CONTRACT:     additive — new rows and new fields only; no existing name,
              description, route or tool schema changed. Nothing breaks if
              Connectors' half lands later: until it does, agents simply get the
              13 built-ins.
```
TASK:         Show which tools an agent has, and which connector each came from
OWNER:        Frontend
FILES:        lodestone/web/app.js · lodestone/web/styles.css ·
              tests/js/tool_provenance.mjs (new) ·
              tests/test_frontend_tool_provenance.py (new)
DEPENDENCIES: Agents' additive extension of GET /api/agents/tools
              ({name, description, source, connector}). Built and shipped
              BEFORE that half lands — see CONTRACT.
              Reads the existing GET /api/connectors for connector health.
CHANGES:      - The Tools panel is grouped by provenance instead of being one
                flat list. `renderToolList(boxEl, tools, connectors)` is split
                out of `loadTools()` so the render path can be executed in a
                test rather than parsed.
              - A row with no `source` is a builtin; anything whose `source` is
                not "builtin" came in with a connector, including source kinds
                that do not exist yet. So the panel is correct today, with the
                old two-field payload, and correct after Agents lands theirs.
              - Connector tools are attributed by the connector's own
                user-facing label. The protocol's acronym never reaches the
                screen (mcp_source.py's rule); a row that arrives with a source
                and no label renders as "A connected app", never as the
                acronym. A test greps the rendered HTML for it.
              - A connector the user configured that cannot answer now renders
                its own group with the backend's reason sentence, a status dot,
                "unavailable", and an "Open Connectors" button — instead of
                contributing nothing and reading as "Lodestone lost it". If it
                does have tools, they stay listed and dimmed rather than
                hidden: they exist, they just cannot run yet.
              - Connectors we ship that were simply never set up (Gmail) do
                NOT appear here — only `custom`/`mcp` rows, which exist because
                the user configured them. Not-set-up is the Sources panel's
                sentence to say, and it already says it.
              - Health comes from the `CONNECTORS` cache the Sources panel
                already filled. /api/connectors starts every added server to
                answer honestly, so the panel never waits on it: tools render
                first, and the endpoint is only called if nothing has.
              - CSS: new group/unavailable styles built only from existing
                :root tokens (--faint/--muted/--text/--danger/--panel-2/--mono).
                No new literals; gold stays the only interactive colour and red
                carries "failed", which is the meaning gold cannot hold.
TESTS:        NEW tests/js/tool_provenance.mjs — executes the real
              `renderToolList`, then CLICKS what it drew (its box stub returns
              one node per button actually written, so a button drawn and left
              inert is caught). Driven by tests/test_frontend_tool_provenance.py,
              25 tests: grouping, the acronym ban, the unreachable path, the
              keyboard path, injection from connector-written text, and a
              rename-everything case that proves there is no id chain.
              Verified the harness FAILS with each bug reintroduced — measured,
              not assumed: provenance dropped (9 failed), unreachable connector
              silent (9), acronym leaked (1), escaping removed (3), button
              became a div (1), button left unwired (2).
              Frontend slice: 135 passed. Full suite: 1331 passed, 18 skipped
              (baseline 1306 + the 25 new). ruff clean. Looked at the panel on
              screen in both states — healthy and unreachable.
RISKS:        - Until Agents lands their half every tool groups under "Built in",
                which is what the old payload actually means. No user-visible
                regression, just no attribution yet.
              - Health is matched on the connector's LABEL, because that is the
                only name the tools payload carries. Two connectors sharing a
                label would share a group. Ids would fix it and would also be
                the id chain rule 4 forbids; if it ever matters, the payload
                should carry a stable key, which is an API/Agents decision.
              - `loadTools` can render twice (once from cache, once after
                fetching health). The second render re-queries its own markup
                to re-wire, so it does not hit the detached-container trap —
                but any future edit that wires handlers outside
                `renderToolList` will.
HANDOFF:      Agents — the frontend is ready for `source`/`connector` now.
              `connector` must be the connector's USER-FACING LABEL and must
              match `label` in GET /api/connectors, case-insensitively, or the
              unreachable state will not attach to the right group. `source`
              may be any string; only the literal "builtin" is treated as ours.
              Send no acronym in `connector` — it goes straight to the screen.
CONTRACT:     additive — consumes fields that do not exist yet and degrades to
              today's behaviour without them. Nothing breaks if only one side
              ships, in either order.
BLOCKING:     no
```
