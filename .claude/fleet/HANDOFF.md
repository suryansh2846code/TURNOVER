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
BLOCKING:     no
```
