/**
 * What the agents can do, and where each skill came from.
 *
 * The Tools & skills panel: the built-in tools, and the tools a connector the
 * user added exposes to the agent loop.
 *
 * **Every skill says where it came from.** A row that does not name its source
 * reads as something Lodestone invented, when it belongs to a server the user
 * connected and can disconnect. `toolConnector` resolves that provenance, and a
 * connector that cannot answer right now is shown as unreachable rather than
 * dropped from the list — a capability that silently vanishes is
 * indistinguishable from one that never existed.
 *
 * Names come from the connector, so they are escaped like any other text the
 * user's own sources supply.
 */

// ── the tools panel ────────────────────────────────────────────────────────
// A skill either ships with Lodestone or arrives with something the user
// connected, and they are entitled to know which: a tool that reaches into
// their mail is a different thing from one that searches their brain.
// Provenance rides on each row as `source` plus `connector` — the connector's
// own user-facing label. Rows that predate provenance carry no `source` at all,
// and those are builtins.
//
// The acronym for the protocol a connector speaks NEVER reaches this screen,
// exactly as "vendor CLI" never reaches the sign-in card. The user added
// Linear; the user sees Linear.
const BUILTIN_GROUP = "Built in";

// What a person reads for this tool. `name` is an id — for a connector tool it
// is a qualified one we minted — and an id on screen is an internal surfaced.
function toolLabel(t) {
  return ((t && (t.label || t.name)) || "").trim();
}

// A row that grants a whole category rather than naming one connector's tool.
// It belongs in the agent builder, where it is the switch a user flips, and not
// in a list of skills, where the concrete tools are already shown under their
// own connector.
function isCategoryRow(t) { return !!t && t.source === "category"; }

function toolConnector(t) {
  // Anything that is not explicitly a builtin came in with a connector —
  // including source kinds that do not exist yet, which is the whole point of
  // asking the question this way round.
  if (!t || !t.source || t.source === "builtin" || isCategoryRow(t)) return "";
  const label = (t.connector || "").trim();
  // A connector that did not name itself still must not be named after its
  // protocol. Vague is survivable; the acronym is not.
  return label || "A connected app";
}

// A connector row exists either because we ship it or because the user added
// it — `custom` apps come from their own form, `mcp` ones from a server they
// chose. Only those two can be "configured but unreachable"; the rest are
// merely not set up yet, which the Sources panel already says in its own words.
function userConfigured(c) { return !!(c && (c.custom || c.mcp)); }

//: A connector the user added that cannot answer right now. Both tool screens
//: need it, and `tool_provenance.mjs` mutates renderToolList's inline form to
//: prove its harness is not blind — so that line stays the single one it
//: pins, and everything else asks through here.
function unreachableConnector(c) { return userConfigured(c) && c.ready === false; }


// Render the tools list. Split out from the fetch so the real render path can
// be executed in a test — an empty drawer and a drawer that threw look
// identical from the outside, and this file has shipped both.
function renderToolList(boxEl, tools, connectors) {
  if (!boxEl) return;
  const rows = Array.isArray(tools) ? tools : [];

  // What each connector can do right now, keyed by the label the user sees —
  // which is the only name the tools payload gives us. No ids, so no id chain.
  const health = new Map();
  for (const c of (Array.isArray(connectors) ? connectors : [])) {
    const label = ((c && c.label) || "").trim();
    if (label) health.set(label.toLowerCase(), c);
  }

  const groups = [];
  const seen = new Map();
  const groupFor = (name) => {
    const key = name.toLowerCase();
    let g = seen.get(key);
    if (!g) { g = { name, tools: [] }; seen.set(key, g); groups.push(g); }
    return g;
  };
  for (const t of rows) {
    if (isCategoryRow(t)) continue;   // the tools behind it are listed already
    groupFor(toolConnector(t) || BUILTIN_GROUP).tools.push(t);
  }

  // A connector the user configured that cannot answer contributes no tools —
  // so without this it would simply be absent, and absent reads as "Lodestone
  // lost it". Say where it went, where the user is already looking.
  for (const c of (Array.isArray(connectors) ? connectors : [])) {
    if (!userConfigured(c) || c.ready !== false) continue;
    const label = (c.label || "").trim();
    if (label) groupFor(label);
  }

  if (!groups.length) { boxEl.innerHTML = `<div class="tasks-empty">no tools</div>`; return; }

  const ordered = [...groups.filter((g) => g.name === BUILTIN_GROUP),
                   ...groups.filter((g) => g.name !== BUILTIN_GROUP)];

  boxEl.innerHTML = ordered.map((g) => {
    const c = health.get(g.name.toLowerCase());
    const down = !!(c && c.ready === false);
    const n = g.tools.length;
    const count = down ? "unavailable" : n ? `${n} skill${n === 1 ? "" : "s"}` : "";
    // The reason is written for a person by the backend that failed; if it did
    // not write one, say the plain thing rather than nothing.
    const why = down ? `<p class="tool-why">${esc(c.reason || `${g.name} can't be reached right now.`)}</p>
      <button type="button" class="tiny tool-fix" data-tool-fix="1">Open Connectors</button>` : "";
    // Names and descriptions of connector tools are written by whoever wrote
    // the connector, not by us. Escape both, always.
    const items = g.tools.map((t) =>
      `<div class="tool"><div class="tool-nm">${esc(toolLabel(t))}</div><div class="tool-ds">${esc(t.description || "")}</div></div>`).join("");
    return `<div class="tool-group${down ? " down" : ""}">
      <div class="tool-group-head">${down ? `<span class="dot off"></span>` : ""}<span class="tool-group-nm">${esc(g.name)}</span>${count ? `<span class="tool-group-ct">${esc(count)}</span>` : ""}</div>
      ${why}${items}</div>`;
  }).join("");

  boxEl.querySelectorAll("[data-tool-fix]").forEach((b) => {
    b.onclick = () => openDrawer("sources");
  });
}

// ── per-agent tools ────────────────────────────────────────────────────────
// The screen that answers "why does my agent not know about Notion?".
//
// It replaced a read-only list of every tool that exists. That answered a
// different question from the one nobody could previously ask — an agent
// silently lacking connector access looked exactly like a connector that was
// still syncing, and no screen distinguished them.
//
// The render is split from its fetch so the real path can be executed in a
// test: an empty panel and a panel that threw are indistinguishable from
// outside, and this file has shipped both.

//: The agent whose tools are on screen. A save names the agent it was for, so
//: a reply arriving after the user has switched cannot repaint the new one.
let AGENT_TOOLS_FOR = "";
//: Saves in flight, by tool name, so a row can show its own progress and a
//: second click cannot race the first.
const _toolSaving = new Set();

function agentToolGroups(tools, connectors, agentTools) {
  const rows = Array.isArray(tools) ? tools : [];
  const have = new Set(Array.isArray(agentTools) ? agentTools : []);

  const health = new Map();
  for (const c of (Array.isArray(connectors) ? connectors : [])) {
    const label = ((c && c.label) || "").trim();
    if (label) health.set(label.toLowerCase(), c);
  }

  const groups = [];
  const seen = new Map();
  const groupFor = (name, kind) => {
    const key = name.toLowerCase();
    let g = seen.get(key);
    if (!g) { g = { name, kind, tools: [], connector: null }; seen.set(key, g); groups.push(g); }
    return g;
  };

  for (const t of rows) {
    const name = (t && t.name) || "";
    // The category row is its own group: it grants everything the connectors
    // can read and belongs to no single connector, so putting it under one
    // would be a lie about what the switch does.
    const group = isCategoryRow(t)
      ? groupFor("Your connectors", "category")
      : groupFor(toolConnector(t) || BUILTIN_GROUP,
                 toolConnector(t) ? "connector" : "builtin");
    group.tools.push({ row: t, on: have.has(name) });
  }

  // A connector the user added that cannot answer contributes no tools, so
  // without this it is simply absent — and absent reads as "Lodestone lost
  // it" rather than "sign in again".
  for (const c of (Array.isArray(connectors) ? connectors : [])) {
    if (!unreachableConnector(c)) continue;
    const label = (c.label || "").trim();
    if (label) groupFor(label, "connector").connector = c;
  }
  for (const g of groups) {
    if (!g.connector) g.connector = health.get(g.name.toLowerCase()) || null;
  }

  // Connectors first: this screen exists because of them. Built-ins last —
  // they are the part that never needed explaining.
  return [...groups.filter((g) => g.kind === "category"),
          ...groups.filter((g) => g.kind === "connector"),
          ...groups.filter((g) => g.kind === "builtin")];
}

//: Why this row cannot be switched, or "" if it can.
//:
//: The reason is the connector's OWN `reason`, written by the layer that
//: failed, for a person — never a string we compose from a name we happen to
//: recognise. There is deliberately no "this agent is built in" case: presets
//: are editable, so it could never be true, and a branch that cannot fire is
//: the kind that later fires for the wrong reason.
function toolBlockedReason(group) {
  const c = group.connector;
  if (c && c.ready === false) {
    return (c.reason || "").trim() || `${group.name} can't be reached right now.`;
  }
  return "";
}

function renderAgentTools(boxEl, { agent, tools, connectors }) {
  if (!boxEl) return;
  const groups = agentToolGroups(tools, connectors, agent && agent.tools);
  const usable = groups.reduce((n, g) =>
    n + (toolBlockedReason(g) ? 0 : g.tools.filter((t) => t.on).length), 0);

  if (!groups.length) {
    // Never a blank panel: say what it can still do, and offer the first thing
    // worth adding.
    boxEl.innerHTML = `<div class="at-empty">
      <p><b>${esc((agent && agent.name) || "This agent")}</b> has no tools yet. It can still
      answer from what it already knows about you — your brain is read on every
      question, whether or not any tool is switched on.</p>
      <p class="at-empty-next">The first one worth adding is a connector, so it can
      read something of yours.</p>
      <button type="button" class="tiny" data-tool-fix="1">Open Connectors</button>
    </div>`;
    wireAgentToolActions(boxEl);
    return;
  }

  boxEl.innerHTML = `<p class="at-summary">${esc((agent && agent.name) || "This agent")}
    can use <b>${usable}</b> of ${groups.reduce((n, g) => n + g.tools.length, 0)} tools.</p>`
    + groups.map((g) => {
    const why = toolBlockedReason(g);
    const rows = g.tools.map(({ row, on }) => {
      const name = (row && row.name) || "";
      const busy = _toolSaving.has(name);
      // A control that cannot work is not shown as a control: the row carries
      // the reason instead, and the place that fixes it.
      const control = why
        ? `<span class="at-blocked">${esc(why)}</span>`
        : `<button type="button" role="switch" aria-checked="${on}"
             class="at-toggle${on ? " is-on" : ""}${busy ? " is-busy" : ""}"
             data-tool="${esc(name)}" data-on="${on ? "1" : ""}"
             aria-label="${esc(toolLabel(row))}"><span class="at-knob"></span></button>`;
      return `<div class="at-row" data-row="${esc(name)}">
        <span class="at-text">
          <span class="at-nm">${esc(toolLabel(row))}</span>
          <span class="at-ds">${esc((row && row.description) || "")}</span>
          <span class="at-err" hidden></span>
        </span>
        ${control}</div>`;
    }).join("");
    const fix = why && g.connector
      ? `<button type="button" class="tiny at-fix" data-tool-fix="1">Open Connectors</button>` : "";
    // A connector that cannot answer contributes no tools, so its card would
    // otherwise be an empty box under a heading — which says less than nothing.
    // The reason goes IN the card, where the rows would have been.
    const body = rows || (why
      ? `<div class="at-row"><span class="at-text"><span class="at-ds">${esc(why)}</span></span>
         <span class="at-blocked">Unavailable</span></div>`
      : `<div class="at-row"><span class="at-text"><span class="at-ds">Nothing here yet.</span></span></div>`);
    return `<section class="at-group${why ? " is-blocked" : ""}">
      <div class="at-group-head">
        <h3 class="at-group-nm">${esc(g.name)}</h3>
        ${why ? `<span class="at-group-why">${esc(why)}</span>${fix}` : ""}
      </div>
      <div class="at-card">${body}</div>
    </section>`;
  }).join("");
  wireAgentToolActions(boxEl, agent);
}

function wireAgentToolActions(boxEl, agent) {
  // Rebound after every render: the list is replaced wholesale, so a handler
  // on the previous nodes is a handler on nothing the user can click.
  boxEl.querySelectorAll("[data-tool-fix]").forEach((b) => {
    b.onclick = () => openConnectorsScreen();
  });
  boxEl.querySelectorAll("[data-tool]").forEach((b) => {
    b.onclick = () => toggleAgentTool(agent, b);
  });
}

async function toggleAgentTool(agent, btn) {
  const name = btn.dataset.tool;
  if (!agent || !name || _toolSaving.has(name)) return;
  const wasOn = btn.dataset.on === "1";
  const forAgent = agent.id;

  // Move the switch first. It is the user's action; making them wait for a
  // round trip to see their own click land is what makes a toggle feel broken.
  const next = !wasOn;
  btn.dataset.on = next ? "1" : "";
  btn.setAttribute("aria-checked", String(next));
  btn.classList.toggle("is-on", next);
  btn.classList.add("is-busy");
  _toolSaving.add(name);

  const row = btn.closest(".at-row");
  const err = row && row.querySelector(".at-err");
  if (err) { err.hidden = true; err.textContent = ""; }

  const tools = new Set(agent.tools || []);
  if (next) tools.add(name); else tools.delete(name);

  try {
    const saved = await api(`/api/agents/${encodeURIComponent(forAgent)}/tools`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tools: [...tools] }),
    });
    // Trust what came back, not what we sent.
    agent.tools = saved.tools || [...tools];
    const inList = agents.find((a) => a.id === forAgent);
    if (inList) inList.tools = agent.tools;
  } catch (e) {
    // Put it back, and say so in the row. A toast would be gone by the time
    // the user looked at the switch that lied.
    btn.dataset.on = wasOn ? "1" : "";
    btn.setAttribute("aria-checked", String(wasOn));
    btn.classList.toggle("is-on", wasOn);
    if (err) { err.textContent = "Couldn't save that — try again."; err.hidden = false; }
  } finally {
    _toolSaving.delete(name);
    btn.classList.remove("is-busy");
  }
}

async function loadAgentTools(agentId) {
  const box = $("#agentToolList"); if (!box) return;
  const id = agentId || AGENT_TOOLS_FOR || current;
  AGENT_TOOLS_FOR = id;
  box.innerHTML = `<div class="at-empty">Loading…</div>`;
  let tools = [];
  try { ({ tools } = await api("/api/agents/tools")); }
  catch (e) { box.innerHTML = `<div class="at-empty">Couldn't load the tool list.</div>`; return; }
  if (AGENT_TOOLS_FOR !== id) return;      // the user switched while we waited

  const agent = (agents || []).find((a) => a.id === id);
  if (!agent) { box.innerHTML = `<div class="at-empty">Pick an agent.</div>`; return; }

  renderAgentTools(box, { agent, tools, connectors: CONNECTORS });
  if (!CONNECTORS.length) {
    // /api/connectors starts every added server to answer honestly, so it is
    // far too slow to block a panel on. Render what we know, then sharpen.
    try {
      const { connectors } = await api("/api/connectors");
      CONNECTORS = connectors;
      if (AGENT_TOOLS_FOR === id) renderAgentTools(box, { agent, tools, connectors });
    } catch (_) { /* the tools are on screen; health is a bonus */ }
  }
}

function renderAgentToolPicker() {
  const sel = $("#agentToolPicker"); if (!sel) return;
  const id = AGENT_TOOLS_FOR || current;
  sel.innerHTML = (agents || []).map((a) =>
    `<option value="${esc(a.id)}"${a.id === id ? " selected" : ""}>${esc(a.name)}</option>`).join("");
  sel.onchange = () => loadAgentTools(sel.value);
}

async function loadTools() {
  const box = $("#toolList"); if (!box) return;
  box.innerHTML = `<div class="tasks-empty">loading…</div>`;
  let tools;
  try { ({ tools } = await api("/api/agents/tools")); }
  catch (e) { box.innerHTML = `<div class="tasks-empty">couldn't load tools</div>`; return; }
  // Connector health comes from the list the Sources panel already loaded.
  // /api/connectors starts each added server to answer honestly, so it is far
  // too slow to open a panel behind: render what we know now, and only go
  // asking if nobody has asked yet.
  renderToolList(box, tools, CONNECTORS);
  if (!CONNECTORS.length) {
    try {
      const { connectors } = await api("/api/connectors");
      CONNECTORS = connectors;
      renderToolList(box, tools, CONNECTORS);
    } catch (_) { /* the tools are already on screen; health is a bonus */ }
  }
}
