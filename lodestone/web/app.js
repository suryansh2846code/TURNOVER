// The workspace's own state. Primitives ($, api, esc, md, toast, orbs, icons)
// live in core.js, which index.html loads first.
let current = null;
let agents = [];
let CONNECTORS = [];

function applyIcons() {
  document.querySelectorAll(".snav").forEach((b) => {
    const el = b.querySelector(".snav-ic"); if (!el) return;
    const key = b.id === "helpBtn" ? "help" : (b.dataset.nav === "sources" ? "connectors" : b.dataset.nav);
    el.innerHTML = IC[key] || "";
  });
  const set = (id, name) => { const e = $(id); if (e) e.innerHTML = IC[name]; };
  set("#attachBtn", "attach"); set("#micBtn", "mic"); set("#send", "arrowUp");
}

// collapse / expand the sidebar (persisted)
function setCollapsed(on) {
  const app = document.querySelector(".app"); if (!app) return;
  app.classList.toggle("collapsed", on);
  const b = $("#collapseBtn");
  if (b) {
    b.textContent = on ? "›" : "‹";
    b.title = on ? "Expand sidebar" : "Collapse sidebar";
    b.setAttribute("aria-label", b.title);
    b.setAttribute("aria-expanded", on ? "false" : "true");
  }
  try { localStorage.setItem("ls_collapsed", on ? "1" : ""); } catch (_) {}
}
{
  const b = $("#collapseBtn");
  if (b) b.onclick = () => setCollapsed(!document.querySelector(".app").classList.contains("collapsed"));
  setCollapsed(localStorage.getItem("ls_collapsed") === "1");
}
function agentOrbId(a) { return (a && a.id === localStorage.getItem("lodestone_lead_agent")) ? "__lead" : (a ? a.id : ""); }
function agentDesc(a) {
  if (!a) return "";
  if (a.id === localStorage.getItem("lodestone_lead_agent")) return "Leads your team and helps with everything — your first stop for anything.";
  return "Helps you with " + (a.role || "your work") + ".";
}


async function loadAgents() {
  const d = await api("/api/agents");
  agents = d.agents;
  // pin the lead agent (created at welcome) to the top
  const leadId = localStorage.getItem("lodestone_lead_agent");
  agents.sort((a, b) => (b.id === leadId ? 1 : 0) - (a.id === leadId ? 1 : 0));
  $("#agentList").innerHTML = agents.map((a) => {
    const lead = a.id === leadId;
    return `
    <div class="agent ${a.id === current ? "active" : ""}" data-id="${a.id}"
         role="button" tabindex="0" aria-pressed="${a.id === current}"
         aria-label="${esc(a.name)}${lead ? " (lead agent)" : ""} — ${esc(a.role)}">
      <span class="orb" style="${orbStyle(agentOrbId(a))}"></span>
      <div class="a-meta">
        <div class="n">${esc(a.name)}${lead ? ` <span class="lead-tag">Lead</span>` : ""}</div>
        <div class="r">${esc(a.role)}</div>
      </div>
      ${a.custom && !lead ? `<button type="button" class="del-agent" data-del-agent="${a.id}" aria-label="Delete agent ${esc(a.name)}">✕</button>`
        : (a.id === current ? `<span class="dot"></span>` : "")}
    </div>`; }).join("");
  document.querySelectorAll(".agent").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest("[data-del-agent]")) return;   // handled below
      selectAgent(el.dataset.id);
    };
    // role="button" is a promise that Enter and Space work. Keep it.
    el.onkeydown = (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      if (e.target.closest("[data-del-agent]")) return;
      e.preventDefault();
      selectAgent(el.dataset.id);
    };
  });
  document.querySelectorAll("[data-del-agent]").forEach((el) => el.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm("Delete this agent?")) return;
    await api(`/api/agents/custom/${el.dataset.delAgent}`, { method: "DELETE" });
    if (current === el.dataset.delAgent) current = null;
    toast("Agent deleted"); loadAgents();
  });
  if (!current && agents.length) selectAgent(agents[0].id);
}


// ── slide-over drawers opened from the left nav ─────────────────────────────
const DRAWER_TITLES = { sources: "Connectors", tasks: "Tasks", model: "AI model", tools: "Tools & skills" };

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
function openDrawer(name) {
  const bg = $("#drawerBg"); if (!bg) return;
  $("#drawerTitle").textContent = DRAWER_TITLES[name] || name;
  document.querySelectorAll(".dpanel").forEach((p) => p.hidden = p.dataset.d !== name);
  bg.hidden = false;
  if (name === "sources") loadBrain();
  if (name === "tasks") { loadTasks(); loadReminders(); loadRoutines(); }
  if (name === "model") { loadProviders(); updateUsage(); }
  if (name === "tools") loadTools();
}
function closeDrawer() { const bg = $("#drawerBg"); if (bg) bg.hidden = true; }
document.querySelectorAll(".snav").forEach((b) => b.onclick = () => {
  if (b.id === "helpBtn") { window.location.href = "/onboarding?replay=1"; return; }  // re-experience onboarding (won't wipe)
  if (b.dataset.nav === "brain") return openBrainScreen();   // Brain → full-screen viz + tools
  openDrawer(b.dataset.nav);
});
$("#drawerClose").onclick = closeDrawer;
$("#drawerBg").onclick = (e) => { if (e.target.id === "drawerBg") closeDrawer(); };
{ const v = $("#viewBrainBtn"); if (v) v.onclick = () => { closeDrawer(); openBrainScreen(); }; }
{ const nr = $("#newAgentRow"); if (nr) nr.onclick = () => $("#newAgentBtn").click(); }
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#drawerBg") && !$("#drawerBg").hidden) closeDrawer(); });

// composer slash-style hint chips
{
  const hints = [["/catch me up", "Catch me up — what's new since yesterday?"],
    ["/tasks", "What should I focus on today? Show my open tasks."],
    ["/find", "Find "], ["/plan", "Help me plan my day and week."]];
  const box = $("#cmpHints");
  if (box) box.innerHTML = hints.map((h, i) => `<span data-i="${i}">${esc(h[0])}</span>`).join("");
  if (box) box.querySelectorAll("span").forEach((s) => s.onclick = () => {
    const [, q] = hints[+s.dataset.i];
    if (q.endsWith(" ")) { $("#input").value = q; $("#input").focus(); autoGrow(); } else send(q);
  });
}

// Cmd/Ctrl+R → refresh the workspace in place (picks up new code — assets are
// served no-cache). The desktop app runs in a webview where the browser's reload
// shortcut isn't wired, so we bind it ourselves. Note: it reloads "/", NOT the
// onboarding — a reload here should never restart onboarding.
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && (e.key === "r" || e.key === "R" || e.code === "KeyR")) {
    e.preventDefault();
    window.location.reload();
  }
}, true);

(async () => {
  if (await maybeOnboard()) return;   // redirecting to onboarding — stop here
  applyIcons();
  await loadProviders();
  loadAgents(); loadBrain(); loadTasks(); loadReminders(); loadRoutines();
  updateBrainStatus(); maybeWelcome();
  // poll the brain status often while it's building, and keep time-based panels fresh
  setInterval(updateBrainStatus, 5000);
  setInterval(() => { loadReminders(); loadRoutines(); }, 45000);
})();


// ── dialogs: escape closes them, and focus goes in and comes back ──────────
// Every overlay here is opened by clearing .hidden on its background element,
// in about fifteen different places. Rather than edit fifteen call sites (and
// miss the sixteenth), watch the attribute itself: an overlay that becomes
// visible takes focus, and whatever opened it gets focus back on the way out.
// Escape closes the topmost one by clicking its own close button, so each
// modal's existing teardown still runs instead of being bypassed.
// #welcome is deliberately excluded: its only exit is "Skip for now", which
// writes a preference, and Escape must not quietly make that choice.
{
  const FOCUSABLE = [
    'button:not([disabled])', 'a[href]', 'input:not([type="hidden"])',
    'select', 'textarea', '[tabindex]:not([tabindex="-1"])',
  ].join(",");
  // .modal-bg is position:fixed, so offsetParent is always null — visibility
  // has to be read from the attribute and from whether it has a box at all.
  const shown = (el) => el && !el.hidden;
  const boxed = (el) => el.getClientRects().length > 0;
  const openers = new WeakMap();
  const modals = () => [...document.querySelectorAll(".modal-bg")].filter(shown);

  function focusInto(el) {
    const all = [...el.querySelectorAll(FOCUSABLE)].filter(boxed);
    // Prefer the first field over the first focusable. In DOM order the first
    // focusable is the ✕ in the header, so "Create an agent" would open with
    // focus on Close — technically focused, practically useless.
    const field = all.find((n) =>
      /^(INPUT|TEXTAREA|SELECT)$/.test(n.tagName) && n.type !== "hidden");
    const target = field || all[0];
    if (target) { target.focus({ preventScroll: true }); return; }
    el.setAttribute("tabindex", "-1");
    el.focus({ preventScroll: true });
  }

  const watch = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.attributeName !== "hidden") continue;
      const el = m.target;
      if (shown(el)) {
        openers.set(el, document.activeElement);
        focusInto(el);
      } else {
        const back = openers.get(el);
        openers.delete(el);
        if (back && back.isConnected && boxed(back)) back.focus({ preventScroll: true });
      }
    }
  });
  document.querySelectorAll(".modal-bg").forEach((el) =>
    watch.observe(el, { attributes: true, attributeFilter: ["hidden"] }));

  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = modals();
    const top = open[open.length - 1];   // last in the DOM is the one on top
    if (!top) return;
    e.preventDefault(); e.stopPropagation();
    const close = top.querySelector(".modal-head button, .modal-head .ghost");
    if (close) close.click(); else top.hidden = true;
  });
}
