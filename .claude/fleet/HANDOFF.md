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
