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


// queue drains, showing live progress. General across any connector's content.
let _enriching = false;
function fmtTokens(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
function fmtEta(sec) { sec = Math.round(sec); if (sec < 60) return sec + "s"; const m = Math.round(sec / 60); return m < 60 ? m + "m" : Math.round(m / 60) + "h"; }
const ENRICH_TIPS = [
  "Entities are pulled from your emails, docs, notes & calendar.",
  "Click any entity in the list to see the facts behind it.",
  "Bounce emails, boilerplate & encoded junk are filtered out.",
  "The model types every entity — person, org, project or tool.",
  "Extraction is simple — a small model (Haiku 4.5, gpt-5.4-mini) is plenty.",
  "Local models (Ollama) or your Claude subscription do this for free.",
  "It runs batch by batch — you can Stop anytime and resume later.",
];
// providers with no per-token API cost (free to enrich with)
const FREE_PROVIDERS = { ollama: 1, "claude-code": 1, subscription: 1, mock: 1 };
// ── model token usage (persisted server-side) ──────────────────────────────
async function updateUsage() {
  const box = $("#usageBox"); if (!box) return;
  let u; try { u = await api("/api/usage"); } catch (e) { return; }
  const a = u.active || {}, tin = a.in || 0, tout = a.out || 0, calls = a.calls || 0;
  const local = u.locality === "local";
  const limit = local ? "local · no API limit"
    : (u.context_window ? `~${Math.round(u.context_window / 1000)}K context/call` : "—");
  box.innerHTML = `
    <div class="usage-row"><span>Active model</span><b>${esc(u.active_provider || "—")}${a.model ? " · " + esc(a.model) : ""}</b></div>
    <div class="usage-row"><span>Tokens used</span><b>${(tin + tout).toLocaleString()}</b></div>
    <div class="usage-row"><span>In / Out</span><b>${tin.toLocaleString()} / ${tout.toLocaleString()}</b></div>
    <div class="usage-row"><span>Calls</span><b>${calls.toLocaleString()}</b></div>
    <div class="usage-row"><span>Limit</span><b>${limit}</b></div>`;
}
{ const rb = $("#usageReset"); if (rb) rb.onclick = async () => {
  try { await api("/api/usage/reset", { method: "POST" }); updateUsage(); } catch (e) {}
}; }

// Enrichment runs SERVER-SIDE (a background job) — the UI just starts/stops it and
// polls status, so a refresh reconnects to the running job instead of killing it.
let _enrichPoll = null, _enrichTip = 0;
function renderEnrich(s) {
  const eb = $("#enrichBtn"), panel = $("#enrichPanel"), bar = panel && panel.querySelector(".ep-bar");
  const fill = $("#epFill"), state = $("#epState"), pctEl = $("#epPct"),
        meta = $("#epMeta"), foundEl = $("#epFound"), tipEl = $("#epTip");
  if (panel) panel.hidden = false;
  const LOCAL = { ollama: 1, "claude-code": 1, subscription: 1, mock: 1 };
  const total = (s.processed || 0) + (s.remaining || 0);
  const pct = total ? Math.min(100, Math.round(s.processed / total * 100)) : (s.running ? 0 : 100);
  if (fill) fill.style.width = pct + "%"; if (pctEl) pctEl.textContent = pct + "%";
  if (eb) eb.style.setProperty("--p", pct + "%");
  if (s.running) {
    if (eb) { eb.classList.add("running"); eb.textContent = `Stop · ${pct}%`; }
    if (bar) bar.classList.add("working");
    if (state) { state.textContent = `Enriching with ${s.provider || "AI"}`; state.classList.remove("done"); }
    if (tipEl) tipEl.textContent = "Tip — " + ENRICH_TIPS[_enrichTip++ % ENRICH_TIPS.length];
  } else {
    if (eb) { eb.classList.remove("running"); eb.style.setProperty("--p", "0%"); eb.textContent = "Enrich with AI"; }
    if (bar) bar.classList.remove("working");
    if (state) {
      state.textContent = (s.remaining === 0 && s.processed > 0) ? `Fully enriched · +${s.entities} entities`
        : s.processed > 0 ? `Stopped · +${s.entities} entities · +${s.facts} facts` : "Ready to enrich";
      state.classList.add("done");
    }
  }
  const rate = s.elapsed > 0 ? s.processed / s.elapsed : 0;
  const eta = s.running && s.remaining > 0 && rate > 0 ? ` · ~${fmtEta(s.remaining / rate)} left` : "";
  const tok = LOCAL[s.provider] ? "local · free"
    : (s.tokens ? `${fmtTokens(s.tokens_in)}↑ ${fmtTokens(s.tokens_out)}↓ tokens${s.estimated ? " (est)" : ""}` : "");
  const capNote = s.cap ? ` · recent ${s.cap}/bulk source` : "";
  if (meta) meta.innerHTML =
    `${(s.processed || 0).toLocaleString()} of ${total.toLocaleString()} memories${capNote} · +${s.entities || 0} entities · +${s.facts || 0} facts${eta}` + (tok ? `<br>${tok}` : "");
  if (foundEl && s.found && s.found.length)
    foundEl.innerHTML = s.found.map((f) => `<span class="ep-chip ${esc(f.type || "")}">${esc(f.name)}</span>`).join("");
}
function pollEnrich() {
  clearInterval(_enrichPoll);
  const tick = async () => {
    let s; try { s = await api("/api/brain/enrich/status"); } catch (e) { return; }
    renderEnrich(s); loadBrain(); _bsRefresh(); updateUsage();
    if (!s.running) { clearInterval(_enrichPoll); _enrichPoll = null; }
  };
  tick(); _enrichPoll = setInterval(tick, 2000);
}
{ const eb = $("#enrichBtn"); if (eb) eb.onclick = async () => {
  if (eb.classList.contains("running")) {
    eb.textContent = "Stopping…";
    try { await api("/api/brain/enrich/stop", { method: "POST" }); } catch (e) {}
    return;
  }
  // Warn before spending real tokens on a big queue with a metered cloud model.
  const em = enrichModel();
  const prov = em.provider;
  if (!FREE_PROVIDERS[prov]) {
    let remaining = 0;
    try { remaining = (await api("/api/brain/enrich/status")).remaining || 0; } catch (_) {}
    if (remaining > 150) {
      const estTok = remaining * 500;   // rough: ~0.5k tokens per memory
      const ok = confirm(
        `Enrich ~${remaining.toLocaleString()} memories with “${prov}” (a metered cloud model)?\n\n`
        + `This can use a LOT of tokens — very roughly ~${fmtTokens(estTok)} — and may cost money.\n\n`
        + `Extraction is a simple task, so this is a better fit for a FREE model:\n`
        + `  • a local model (Ollama), or your Claude subscription/CLI — free\n`
        + `  • or a small cheap model (Haiku 4.5, gpt-5.4-mini)\n\n`
        + `You can Stop anytime. Continue with ${prov}?`);
      if (!ok) return;
    }
  }
  eb.classList.add("running"); eb.textContent = "Starting…"; eb.style.setProperty("--p", "3%");
  if ($("#enrichPanel")) $("#enrichPanel").hidden = false;
  if ($("#epTip")) $("#epTip").textContent = "Tip — " + ENRICH_TIPS[0];
  try {
    await api("/api/brain/enrich/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: em.provider, model: em.model }) });
  } catch (e) {
    const st = $("#epState"); if (st) { st.textContent = "Couldn't start — check Model."; st.classList.add("done"); }
    eb.classList.remove("running"); eb.textContent = "Enrich with AI"; return;
  }
  pollEnrich();
}; }
// resume on load: if the server job is running, reconnect the UI
(async () => { try { const s = await api("/api/brain/enrich/status"); if (s.running) { pollEnrich(); } } catch (_) {} })();
$("#bsSync").onclick = async () => {
  try { const r = await api("/api/sync/now", { method: "POST" });
    toast(r.started ? "syncing your sources…" : (r.reason || "already syncing"));
    _bsRefresh(); updateBrainStatus();
  } catch (e) { toast(String(e)); }
};
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#brainScreen").hidden) closeBrainScreen(); });

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
