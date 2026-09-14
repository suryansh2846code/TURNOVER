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
