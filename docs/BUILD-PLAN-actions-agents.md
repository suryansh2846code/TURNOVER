# Build Plan — Action-taking + Custom Agents

## Goal
1. **Agents that DO** — send email, create calendar events (the Turnstone "handle
   it for me"), with **confirm-before-execute** (nothing outward without a click).
2. **Custom agents** — users create their own agent (name, focus, prompt, tools).

## Key design decisions
- **Confirm before any outward action.** Agents *propose*; the user *confirms*;
  only then does Lodestone execute. Irreversible/outbound = always gated.
- **Backend-agnostic proposal (works on claude-code too).** Agents can't rely on
  tool-calling (claude-code has none). So an agent **proposes an action inside
  its reply** using a small tag the UI parses:
  `<action type="send_email" to="…" subject="…">body</action>`
  The UI renders a **Confirm / Cancel card**; on Confirm it calls the execute
  endpoint. No tool-calling required; works on every model.
- **Deterministic execution.** The action itself runs in code (connector write
  API), never "hoped" from model output.

## Phase 1 — Action framework + Send Email
- Add Gmail **send** scope + Calendar **events** scope → user re-authorizes once.
- `gmail.send_email(to, subject, body)` (write) via the Gmail API.
- `POST /api/actions/execute` {type, params} → runs the action, returns result.
- System prompt: when the user asks to send/reply, the agent drafts and emits an
  `<action type="send_email" …>…</action>` proposal (never claims it sent).
- UI: parse `<action>` in replies → Confirm/Cancel card → execute → show result.

## Phase 2 — Create Calendar Event
- `gcal.create_event(title, start, end, attendees?, description?)`.
- `<action type="create_event" …>` proposal → same confirm flow.

## Phase 3 — Custom agents
- Agents become **data**: `custom_agents` table (id, name, role, system_prompt,
  tools JSON, recall_sources JSON). Merge presets + custom in list/get.
- `GET/POST/DELETE /api/agents/custom` CRUD.
- UI: "＋ New agent" → form (name, focus, system prompt, pick tools) → appears in
  the sidebar; edit/delete.

## Safety rules (non-negotiable)
- No send/create without explicit user Confirm.
- Show a full preview (recipient, subject, body / event details) before Confirm.
- Read scopes stay read-only; only the specific write action uses the write scope.
- Never auto-confirm; never batch-send.

## Order
Phase 1 (send email + framework) → Phase 2 (calendar) → Phase 3 (custom agents).
