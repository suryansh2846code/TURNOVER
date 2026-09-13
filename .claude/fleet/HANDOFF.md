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
