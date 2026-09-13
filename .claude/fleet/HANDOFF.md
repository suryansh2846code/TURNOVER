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
