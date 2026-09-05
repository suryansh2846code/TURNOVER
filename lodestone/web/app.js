const $ = (s) => document.querySelector(s);
const api = (p, o) => fetch(p, o).then((r) => r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText)));
let current = null;
let agents = [];
let CONNECTORS = [];

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }
function esc(s) { return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

// gradient orb avatar per agent (stable colour from the id; the lead is always blue)
const ORB_COLORS = [["#8fb0ff", "#2f3a5e"], ["#7fd8b0", "#1f4636"], ["#c3a0f5", "#382a54"],
  ["#e0b489", "#48331f"], ["#e79aa0", "#48232e"], ["#9ad0e0", "#1e444f"], ["#b8c0cf", "#2b3140"]];
function orbPair(id) {
  if (id === "__lead") return ORB_COLORS[0];
  let h = 0; for (const ch of String(id || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return ORB_COLORS[h % ORB_COLORS.length];
}
function orbStyle(id) { const [a, b] = orbPair(id); return `background:radial-gradient(circle at 32% 26%, ${a}, ${b} 74%)`; }
function agentOrbId(a) { return (a && a.id === localStorage.getItem("lodestone_lead_agent")) ? "__lead" : (a ? a.id : ""); }
function agentDesc(a) {
  if (!a) return "";
  if (a.id === localStorage.getItem("lodestone_lead_agent")) return "Leads your team and helps with everything — your first stop for anything.";
  return "Helps you with " + (a.role || "your work") + ".";
}

// which side panel / view a sidebar nav item opens
function switchTab(tab) {
  document.querySelectorAll(".ctx-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".ctx-pane").forEach((p) => p.hidden = p.dataset.pane !== tab);
}

// tiny, safe markdown renderer (escapes first, then applies a subset)
function mdInline(s) {
  return s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])((https?:\/\/[^\s<)]+))/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}
function md(src) {
  const lines = esc(src).split("\n");
  let html = "", inList = false, inCode = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    if (/^```/.test(raw)) {
      if (inCode) { html += "</code></pre>"; inCode = false; }
      else { closeList(); html += "<pre><code>"; inCode = true; }
      continue;
    }
    if (inCode) { html += raw + "\n"; continue; }
    const h = raw.match(/^(#{1,4})\s+(.*)/);
    if (h) { closeList(); const lvl = Math.min(h[1].length + 2, 6); html += `<h${lvl}>${mdInline(h[2])}</h${lvl}>`; continue; }
    const li = raw.match(/^\s*[-*]\s+(.*)/) || raw.match(/^\s*\d+\.\s+(.*)/);
    if (li) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${mdInline(li[1])}</li>`; continue; }
    if (raw.trim() === "") { closeList(); continue; }
    closeList(); html += `<p>${mdInline(raw)}</p>`;
  }
  closeList(); if (inCode) html += "</code></pre>";
  return html;
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
    <div class="agent ${a.id === current ? "active" : ""}" data-id="${a.id}">
      <span class="orb" style="${orbStyle(agentOrbId(a))}"></span>
      <div class="a-meta">
        <div class="n">${esc(a.name)}${lead ? ` <span class="lead-tag">Lead</span>` : ""}</div>
        <div class="r">${esc(a.role)}</div>
      </div>
      ${a.custom && !lead ? `<span class="del-agent" data-del-agent="${a.id}">✕</span>`
        : (a.id === current ? `<span class="dot"></span>` : "")}
    </div>`; }).join("");
  document.querySelectorAll(".agent").forEach((el) => el.onclick = (e) => {
    if (e.target.dataset.delAgent) return;   // handled below
    selectAgent(el.dataset.id);
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

const MODEL_HINTS = {
  ollama: "e.g. llama3.2, qwen2.5:3b", "claude-code": "leave blank (uses your Claude)",
  anthropic: "e.g. claude-sonnet-5", openai: "e.g. gpt-4o-mini",
  openrouter: "e.g. anthropic/claude-3.5-sonnet", mock: "offline test model",
};
function applyModelHint() {
  $("#modelHint").textContent = MODEL_HINTS[$("#provider").value] || "";
  updatePrivacyBadge();
}
function updatePrivacyBadge() {
  const el = $("#privacyBadge");
  if (!el) return;
  const p = (PROVIDERS || []).find((x) => x.name === $("#provider").value);
  if (!p) { el.hidden = true; return; }
  el.hidden = false;
  const local = p.locality === "local";
  el.className = "privacy-badge " + (local ? "loc-local" : "loc-cloud");
  el.innerHTML = `<span class="pb-ic">${local ? "🔒" : "☁️"}</span>` +
    `<span>${local ? "On-device" : "Leaves your Mac"}</span>`;
  el.title = p.destination || "";
}

let PROVIDERS = [];
async function loadProviders() {
  const d = await api("/api/providers");
  PROVIDERS = d.providers;
  const savedP = localStorage.getItem("lodestone_provider");
  const active = savedP || d.active;
  $("#provider").innerHTML = d.providers.map((p) =>
    `<option value="${p.name}" ${p.name === active ? "selected" : ""}>${p.name}${p.ready ? "" : " (not ready)"}</option>`).join("");
  $("#modelName").value = localStorage.getItem("lodestone_model") || "";
  applyModelHint();
  $("#provider").onchange = () => { localStorage.setItem("lodestone_provider", $("#provider").value); applyModelHint(); };
  $("#modelName").onchange = () => localStorage.setItem("lodestone_model", $("#modelName").value.trim());
}

async function selectAgent(id) {
  if (busy) { toast("finishing current reply…"); return; }
  current = id;
  const a = agents.find((x) => x.id === id) || { name: "—", role: "", tools: [] };
  const oid = agentOrbId(a);
  $("#agentName").textContent = a.name;
  $("#agentRole").textContent = a.role;
  const chOrb = $("#chOrb"); if (chOrb) chOrb.style.cssText = orbStyle(oid);
  const ctxOrb = $("#ctxOrb"); if (ctxOrb) ctxOrb.style.cssText = orbStyle(oid);
  if ($("#ctxAgentName")) $("#ctxAgentName").textContent = a.name;
  if ($("#ctxAgentRole")) $("#ctxAgentRole").textContent = a.role;
  if ($("#ctxAgentDesc")) $("#ctxAgentDesc").textContent = agentDesc(a);
  $("#input").placeholder = "Message " + a.name + "…";
  document.querySelectorAll(".agent").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  loadAgents();   // refresh the active dot in the rail
  const { history } = await api(`/api/agents/${id}/history`);
  renderHistory(history);
}

function heroEmpty() {
  const a = agents.find((x) => x.id === current) || { name: "your agent" };
  const hr = new Date().getHours();
  const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const div = document.createElement("div");
  div.className = "hero-empty";
  div.innerHTML = `
    <div class="he-top">
      <span class="orb orb-xl" style="${orbStyle(agentOrbId(a))}"></span>
      <div>
        <h1 class="he-hi">${greet}.</h1>
        <p class="he-sub">Your second brain, always on your side. Ask ${esc(a.name)} anything — it already knows your world.</p>
      </div>
    </div>
    <div class="he-cards">
      <button class="he-card" data-q="Catch me up — what's new since yesterday?"><span class="hc-ic">💬</span><b>Catch me up</b><span>What's new since yesterday?</span></button>
      <button class="he-card" data-q="What should I focus on today? Show my open tasks."><span class="hc-ic">☑</span><b>Show my tasks</b><span>What should I focus on today?</span></button>
      <button class="he-card" data-fill="Find "><span class="hc-ic">🔎</span><b>Find something</b><span>Search across my apps &amp; notes.</span></button>
      <button class="he-card" data-q="Help me plan my day and week."><span class="hc-ic">✨</span><b>Help me plan</b><span>Plan my day / week.</span></button>
    </div>`;
  div.querySelectorAll(".he-card").forEach((c) => c.onclick = () => {
    if (c.dataset.fill) { $("#input").value = c.dataset.fill; $("#input").focus(); autoGrow(); }
    else send(c.dataset.q);
  });
  return div;
}

function renderHistory(history) {
  const box = $("#messages");
  box.innerHTML = "";
  const msgs = history.filter((m) => m.role === "user" || m.role === "assistant");
  if (!msgs.length) { box.appendChild(heroEmpty()); return; }
  for (const m of msgs) addMsg(m.role, m.content);   // so history shows action cards too
  box.scrollTop = box.scrollHeight;
}

function parseActions(text) {
  const actions = [];
  const clean = text.replace(/<action\s+([^>]*?)>([\s\S]*?)<\/action>/gi, (m, attrs, inner) => {
    const a = { params: {} };
    let mm; const re = /(\w+)="([^"]*)"/g;
    while ((mm = re.exec(attrs))) { if (mm[1] === "type") a.type = mm[2]; else a.params[mm[1]] = mm[2]; }
    if (a.type === "send_email") a.params.body = inner.trim();
    else if (a.type === "create_event") a.params.description = inner.trim();
    else if (a.type === "set_reminder") a.params.message = inner.trim();
    else if (a.type === "create_routine") a.params.instruction = inner.trim();
    if (a.type) actions.push(a);
    return "";   // strip the tag from the visible text
  });
  return { clean: clean.trim(), actions };
}

function actionCard(a) {
  const p = a.params;
  let title, rows, verb = "send";
  const at = p.at || p.when;
  if (a.type === "send_email") {
    title = "✉️ Send email"; verb = at ? "schedule" : "send";
    rows = `<div class="ac-row"><b>To</b> ${esc(p.to || "")}</div>
       <div class="ac-row"><b>Subject</b> ${esc(p.subject || "")}</div>
       ${at ? `<div class="ac-row"><b>Send at</b> ${esc(at)}</div>` : ""}
       <div class="ac-body">${esc(p.body || "")}</div>`;
  } else if (a.type === "set_reminder") {
    title = "⏰ Set reminder"; verb = "set";
    rows = `<div class="ac-row"><b>Remind</b> ${esc(p.message || "")}</div>
       <div class="ac-row"><b>When</b> ${esc(p.at || p.when || "")}</div>`;
  } else if (a.type === "create_routine") {
    title = "⚡ Create automation"; verb = "create";
    const trig = p.trigger === "schedule" ? `every ${p.interval_min || 60} min` : "on every new email";
    rows = `<div class="ac-row"><b>Name</b> ${esc(p.name || "Automation")}</div>
       <div class="ac-row"><b>Runs</b> ${trig} · ${esc(p.agent || p.agent_id || "personal")}</div>
       <div class="ac-body">${esc(p.instruction || "")}</div>`;
  } else {
    title = "📅 Create calendar event"; verb = "create";
    rows = `<div class="ac-row"><b>Title</b> ${esc(p.title || "")}</div>
       <div class="ac-row"><b>When</b> ${esc(p.start || "")}${p.end ? " → " + esc(p.end) : ""}</div>
       ${p.description ? `<div class="ac-body">${esc(p.description)}</div>` : ""}`;
  }
  const isEmail = a.type === "send_email";
  const el = document.createElement("div");
  el.className = "action-card";
  el.innerHTML = `<div class="ac-head">${title}<span class="ac-tag">needs your confirmation</span></div>
    ${rows}
    <div class="ac-actions"><button class="ac-confirm">Confirm & ${verb}</button>
    <button class="ac-cancel ghost">Cancel</button></div>
    <div class="ac-result"></div>`;
  el.querySelector(".ac-cancel").onclick = () => { el.querySelector(".ac-actions").innerHTML = "<span class='muted'>Cancelled</span>"; };
  el.querySelector(".ac-confirm").onclick = async () => {
    const btns = el.querySelector(".ac-actions"); btns.innerHTML = "<span class='muted'>Working…</span>";
    try {
      const r = await api("/api/actions/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: a.type, params: { ...p, agent_id: current } }) });
      const rr = el.querySelector(".ac-result");
      if (r.ok) { rr.innerHTML = `<span class="ac-ok">✓ ${esc(r.detail || "Done")}</span>`; loadReminders(); loadRoutines(); return; }
      rr.innerHTML = `<span class="ac-err">⚠️ ${esc(r.error || "Failed")}</span>`;
      if (r.reauth) {
        const b = document.createElement("button");
        b.className = "tiny"; b.textContent = "Reconnect Google"; b.style.marginTop = "8px";
        b.onclick = async () => { const x = await api("/api/google/reconnect", { method: "POST" }); toast(x.detail || "Opening browser…"); };
        rr.appendChild(document.createElement("br")); rr.appendChild(b);
      }
    } catch (e) { el.querySelector(".ac-result").innerHTML = `<span class="ac-err">⚠️ ${esc(String(e))}</span>`; }
  };
  return el;
}

function addMsg(role, text) {
  const box = $("#messages");
  const he = box.querySelector(".hero-empty"); if (he) he.remove();
  if (role === "assistant") {
    const { clean, actions } = parseActions(text);
    const el = document.createElement("div");
    el.className = "msg assistant";
    const oid = agentOrbId(agents.find((x) => x.id === current));
    el.innerHTML = `<span class="orb a-orb" style="${orbStyle(oid)}"></span><div class="a-body">${md(clean)}</div>`;
    box.appendChild(el);
    for (const a of actions) box.appendChild(actionCard(a));
    box.scrollTop = 1e9; return el;
  }
  const el = document.createElement("div");
  el.className = "msg " + role; el.textContent = text;
  box.appendChild(el); box.scrollTop = 1e9; return el;
}
function addTrace(steps) {
  if (!steps.length) return;
  const el = document.createElement("div"); el.className = "trace";
  el.innerHTML = steps.filter((s) => s.kind === "tool_call").map((s) => {
    const res = (steps.find((r) => r.kind === "tool_result" && r.name === s.name) || {}).result || "";
    return `<div class="step"><span class="tname">${s.name}</span>(${esc(JSON.stringify(s.arguments))})<span class="res">${esc(res.slice(0, 160))}</span></div>`;
  }).join("");
  $("#messages").appendChild(el); $("#messages").scrollTop = 1e9;
}

let busy = false;               // one turn at a time per the whole workspace
let controller = null;          // AbortController for the in-flight turn

function setBusy(on) {
  busy = on;
  $("#input").disabled = on;
  $("#send").textContent = on ? "Stop" : "Send";
  $("#send").classList.toggle("stopbtn", on);
  if (!on) { $("#input").focus(); autoGrow(); }
}

// Phrases + rough per-provider time estimates for the reply indicator.
const THINK_PHRASES = [
  "Recalling what I know about you…",
  "Searching your brain…",
  "Pulling in the right context…",
  "Connecting the dots…",
  "Composing a reply…",
];
const THINK_EST = { "claude-code": 18, ollama: 12, subscription: 15,
  anthropic: 8, openai: 8, openrouter: 9, mock: 1 };

function makeThinking(provider) {
  const est = THINK_EST[provider] || 12;
  const el = addMsg("assistant", "");
  el.classList.add("thinking");
  el.innerHTML =
    `<div class="think-row"><span class="think-dot"></span>
       <span class="think-msg">Thinking…</span><span class="think-time"></span></div>
     <div class="think-bar"><div class="think-fill"></div></div>`;
  const msgEl = el.querySelector(".think-msg");
  const timeEl = el.querySelector(".think-time");
  const fill = el.querySelector(".think-fill");
  const t0 = performance.now();
  let pi = -1;
  const tick = () => {
    const elapsed = (performance.now() - t0) / 1000;
    // asymptotic progress: approaches ~97% but never completes until the reply lands
    fill.style.width = Math.min(97, 100 * (1 - Math.exp(-elapsed / est))).toFixed(1) + "%";
    const remain = est - elapsed;
    timeEl.textContent = remain > 0.5 ? `~${Math.ceil(remain)}s` : "almost there…";
    const want = Math.min(THINK_PHRASES.length - 1, Math.floor(elapsed / 2.5));
    if (want !== pi) { pi = want; msgEl.textContent = THINK_PHRASES[pi]; }
  };
  tick();
  const timer = setInterval(tick, 150);
  return { el, done: () => { clearInterval(timer); el.remove(); } };
}

async function send(text) {
  if (busy) return;             // guard: ignore sends while a turn is running
  setBusy(true);
  controller = new AbortController();
  addMsg("user", text);
  const think = makeThinking($("#provider").value);
  try {
    const res = await api(`/api/agents/${current}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, provider: $("#provider").value,
        model: $("#modelName").value.trim() || null }),
      signal: controller.signal,
    });
    think.done();
    addTrace(res.trace || []);
    addMsg("assistant", res.reply);
    loadBrain();
    loadTasks();       // an agent may have added/completed a task this turn
    loadReminders();   // …or set a reminder
  } catch (e) {
    think.done();
    if (controller && controller.signal.aborted) addMsg("assistant", "⏹ stopped");
    else addMsg("assistant", "⚠️ " + e);
  }
  finally { controller = null; setBusy(false); }
}

function autoGrow() {
  const t = $("#input"); if (!t) return;
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 140) + "px";
}

async function loadBrain() {
  const s = await api("/api/brain/stats");
  $("#brainStats").innerHTML = `
    <div class="b"><div class="num">${s.total}</div><div class="lbl">memories</div></div>
    <div class="b"><div class="num">${s.graph.entities}</div><div class="lbl">entities</div></div>
    <div class="b"><div class="num">${s.graph.relations}</div><div class="lbl">facts</div></div>`;
  if ($("#ctxMem")) $("#ctxMem").textContent = s.total > 0 ? "On" : "Empty";
  if ($("#ctxEntities")) $("#ctxEntities").textContent = (s.graph.entities || 0).toLocaleString();
  const { entities } = await api("/api/brain/entities?limit=20");
  $("#entities").innerHTML = entities.length ? entities.map((e) =>
    `<div class="ent" data-entity="${e.id}" title="click for facts"><span class="etype ${e.type}">${e.type}</span> ${esc(e.name)} <span class="t">${e.mentions}×</span></div>`).join("")
    : `<div class="ent t">empty — add notes or sync a connector</div>`;
  document.querySelectorAll("[data-entity]").forEach((el) =>
    el.onclick = () => openEntity(el.dataset.entity));
  const { connectors } = await api("/api/connectors");
  CONNECTORS = connectors;
  if ($("#ctxSources")) $("#ctxSources").textContent = connectors.filter((c) => c.ready).length;
  const staleAfterMin = Math.max(120, (SYNC_INTERVAL_MIN || 30) * 4);
  $("#connectors").innerHTML = connectors.map((c) => {
    const ls = c.state?.last_sync ? new Date(c.state.last_sync) : null;
    const ageMin = ls ? (Date.now() - ls.getTime()) / 60000 : null;
    const stale = c.ready && ageMin !== null && ageMin > staleAfterMin;
    const last = ls ? ls.toLocaleDateString() : "";
    const dot = !c.ready ? "off" : stale ? "stale" : "ok";
    const sub = !c.ready ? (c.reason || "not configured")
      : !last ? "ready · not synced yet"
      : stale ? `stale · last ${last}` : `synced ${last}`;
    const sync = c.ready ? `<button class="tiny ghost" data-sync="${esc(c.name)}">sync</button>` : "";
    const setup = c.custom
      ? `<button class="tiny ghost" data-editapp="${esc(c.name)}">edit</button>`
      : (c.ready ? "" : `<button class="tiny" data-setup="${esc(c.name)}">setup</button>`);
    const del = c.custom ? `<button class="tiny ghost" data-delapp="${esc(c.name)}" title="remove">✕</button>` : "";
    return `<div class="conn" data-conn="${esc(c.name)}">
      <span class="conn-meta"><span class="dot ${dot}"></span>
        <span><span class="conn-name">${esc(c.label)}</span><span class="conn-sub">${esc(sub)}</span></span></span>
      <span style="display:flex;gap:4px">${sync}${setup}${del}</span></div>`;
  }).join("");
  document.querySelectorAll("[data-sync]").forEach((b) => b.onclick = () => syncConn(b.dataset.sync));
  document.querySelectorAll("[data-setup]").forEach((b) => b.onclick = () => connectorHelp(b.dataset.setup));
  document.querySelectorAll("[data-editapp]").forEach((b) => b.onclick = () =>
    customAppForm(CONNECTORS.find((x) => x.name === b.dataset.editapp)?.config));
  document.querySelectorAll("[data-delapp]").forEach((b) => b.onclick = async () => {
    const id = b.dataset.delapp.split(":")[1];
    if (!confirm("Remove this custom app? (synced records stay in the brain.)")) return;
    await api(`/api/custom-apps/${id}`, { method: "DELETE" });
    toast("custom app removed"); loadBrain();
  });
  loadSyncStatus();
  try { renderGoogleCard(await api("/api/google/status")); } catch (_) {}
}

// ── polished Google connect flow (local backend, Turnstone-grade UX) ────────
function renderGoogleCard(s) {
  const el = $("#googleCard");
  if (!el) return;
  if (!s.client_configured) { el.hidden = true; return; }
  el.hidden = false;
  if (s.connected) {
    const chips = (s.services || []).map((x) => `<span class="gchip">${esc(x)}</span>`).join("");
    el.className = "google-card connected";
    el.innerHTML =
      `<div class="gc-row"><span class="gc-ic">✅</span>
         <div class="gc-txt"><b>Google connected</b>
           <span class="gc-sub">${esc(s.account || "signed in")}</span></div>
         <button class="tiny ghost" id="gcDisconnect">Disconnect</button></div>
       <div class="gchips">${chips}</div>
       <div class="gc-note">🔒 Token stays on your Mac — not sent to any third party.</div>`;
    $("#gcDisconnect").onclick = disconnectGoogle;
  } else {
    el.className = "google-card";
    el.innerHTML =
      `<div class="gc-txt"><b>Connect Google</b>
         <span class="gc-sub">Gmail · Calendar · Drive — read-only</span></div>
       <button class="gsignin" id="gcConnect"><span class="g-logo">G</span>Sign in with Google</button>
       <div class="gc-note">🔒 One click. Token stays on your Mac.</div>`;
    $("#gcConnect").onclick = connectGoogle;
  }
}
async function connectGoogle() {
  const el = $("#googleCard");
  el.className = "google-card connecting";
  el.innerHTML =
    `<div class="gc-row"><span class="gc-spin"></span>
       <div class="gc-txt"><b>Waiting for approval…</b>
         <span class="gc-sub">Approve access in the browser window that opened.</span></div></div>
     <button class="tiny ghost" id="gcReopen">Reopen browser sign-in</button>`;
  const open = () => api("/api/google/reconnect", { method: "POST" }).catch(() => {});
  $("#gcReopen").onclick = open;
  await open();
  let tries = 0;
  const poll = setInterval(async () => {
    let g; try { g = await api("/api/google/status"); } catch { return; }
    if (g.connected) { clearInterval(poll); toast("Google connected ✓"); renderGoogleCard(g); loadBrain(); }
    else if (++tries > 60) { clearInterval(poll); renderGoogleCard(g); toast("Didn't finish — try again"); }
  }, 3000);
}
async function disconnectGoogle() {
  if (!confirm("Disconnect Google? You can reconnect anytime.")) return;
  await api("/api/google/disconnect", { method: "POST" });
  toast("Google disconnected");
  renderGoogleCard(await api("/api/google/status")); loadBrain();
}

let SYNC_INTERVAL_MIN = 30;
async function loadSyncStatus() {
  try {
    const s = await api("/api/sync/status");
    if (s.interval_minutes) SYNC_INTERVAL_MIN = s.interval_minutes;
    const last = s.last_run ? new Date(s.last_run).toLocaleTimeString() : "not yet";
    $("#syncStatus").textContent = s.syncing ? "syncing now…"
      : (s.enabled ? `auto every ${s.interval_minutes}m · last ${last}` : "auto-sync off");
    $("#syncAll").textContent = s.syncing ? "syncing…" : "sync all";
    $("#syncAll").disabled = !!s.syncing;
  } catch (_) {}
}
$("#syncAll").onclick = async () => {
  const r = await api("/api/sync/now", { method: "POST" });
  if (!r.started) { toast(r.reason || "already syncing"); return; }
  toast("syncing all connectors…");
  const poll = setInterval(async () => {
    const s = await api("/api/sync/status");
    loadSyncStatus();
    if (!s.syncing) { clearInterval(poll); toast("sync complete"); loadBrain(); }
  }, 3000);
};

async function syncConn(name) {
  if (name === "files") { openPicker(); return; }   // folder picker for local files
  const row = document.querySelector(`.conn[data-conn="${CSS.escape(name)}"]`);
  const subEl = row?.querySelector(".conn-sub");
  const dotEl = row?.querySelector(".dot");
  const btn = row?.querySelector(`[data-sync="${CSS.escape(name)}"]`);
  if (subEl) subEl.textContent = "syncing…";
  if (dotEl) { dotEl.className = "dot syncing"; }
  if (btn) btn.disabled = true;
  try {
    const r = await api(`/api/connectors/${name}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ params: {} }) });
    if (r.errors?.length) {
      toast(`${name}: ${r.errors[0]}`);
      if (subEl) subEl.textContent = "error — see setup";
      if (dotEl) dotEl.className = "dot off";
    } else {
      toast(`${name}: +${r.added} added${r.skipped ? ` · ${r.skipped} skipped` : ""}`);
      loadBrain();          // re-render with fresh state (green dot, "synced today")
    }
  } catch (e) {
    toast(String(e));
    if (subEl) subEl.textContent = "sync failed";
    if (dotEl) dotEl.className = "dot off";
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── brain detail modal (entity facts / memory search) ──────────────────────
function openBrainModal(title, bodyHtml) {
  $("#bmTitle").textContent = title;
  $("#bmBody").innerHTML = bodyHtml;
  $("#brainModal").hidden = false;
}
$("#bmClose").onclick = () => $("#brainModal").hidden = true;
$("#brainModal").onclick = (e) => { if (e.target.id === "brainModal") $("#brainModal").hidden = true; };

async function openEntity(id) {
  const d = await api(`/api/brain/entities/${id}/facts`);
  const e = d.entity;
  const facts = d.facts.length
    ? d.facts.map((f) => `<li>${esc(f)}</li>`).join("")
    : "<li class='t'>no facts recorded</li>";
  openBrainModal(`${e.name}`,
    `<div class="bm-sub"><span class="etype ${e.type}">${e.type}</span> · ${e.mentions} mentions</div>
     ${e.summary ? `<p>${esc(e.summary)}</p>` : ""}
     <ul class="bm-facts">${facts}</ul>`);
}

async function searchBrain(q) {
  const d = await api(`/api/brain/search?q=${encodeURIComponent(q)}`);
  if (!d.memories.length) { openBrainModal(`Search: "${q}"`, `<p class="t">No matches.</p>`); return; }
  const rows = d.memories.map((m) =>
    `<div class="bm-mem">
       <div class="bm-mem-head"><b>${esc(m.title || m.source)}</b>
         <span><span class="bm-score">${m.score}</span>
         <button class="tiny ghost" data-delmem="${m.id}">✕</button></span></div>
       <div class="bm-mem-body">${esc(m.text)}</div>
     </div>`).join("");
  openBrainModal(`Search: "${q}"`, rows);
  document.querySelectorAll("[data-delmem]").forEach((b) => b.onclick = async () => {
    await api(`/api/memories/${b.dataset.delmem}`, { method: "DELETE" });
    toast("Deleted"); b.closest(".bm-mem").remove(); loadBrain();
  });
}
$("#brainSearch").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) searchBrain(e.target.value.trim());
});

const CONNECTOR_HELP = {
  gmail: `<p>Read-only access to your Gmail.</p><ol>
    <li>In <b>Google Cloud Console</b> → APIs & Services → Credentials, create an
        <b>OAuth client ID</b> of type <b>Desktop app</b>.</li>
    <li>Download the <code>client_secret.json</code>.</li>
    <li>Set <code>GOOGLE_CLIENT_SECRETS</code> to its path, or drop it at
        <code>~/Library/Lodestone/google_client_secret.json</code>.</li>
    <li>Run a sync — a browser opens once to authorize (read-only).</li></ol>`,
  gdrive: `<p>Read-only access to your Google Drive (Docs, text, PDFs).</p>
    <p>Uses the <b>same Google OAuth Desktop client</b> as Gmail — set it up once
    (see the Gmail setup) and Drive works too.</p>`,
  gcal: `<p>Read-only access to your Google Calendar events.</p>
    <p>Uses the <b>same Google OAuth Desktop client</b> as Gmail — set it up once
    (see the Gmail setup). Then re-authorize once so Calendar scope is granted.</p>`,
  apple_mail: `<p>Reads mail straight off your Mac — <b>no Google sign-in</b>.
    Works if you have your account in the <b>Mail app</b>.</p><ol>
    <li>Add your email account in <b>Mail</b> (if not already).</li>
    <li><b>System Settings → Privacy & Security → Full Disk Access</b> → add your
        terminal / Lodestone → enable.</li>
    <li>Restart Lodestone, then click sync.</li></ol>`,
  apple_calendar: `<p>Reads events off your Mac — <b>no sign-in</b>. Works with any
    calendar in the <b>Calendar app</b>.</p><ol>
    <li>Enable <b>Full Disk Access</b> for your terminal / Lodestone.</li>
    <li>Restart Lodestone, then click sync.</li></ol>`,
  imessage: `<p>Reads your local iMessages (fully on-device, no cloud).</p><ol>
    <li>Open <b>System Settings → Privacy & Security → Full Disk Access</b>.</li>
    <li>Add your <b>Terminal</b> (or whatever runs Lodestone) and enable it.</li>
    <li>Restart Lodestone, then click sync.</li></ol>
    <p class="t">macOS only. Lodestone only reads, never sends.</p>`,
  notion: `Read-only access to the Notion pages you share with an integration.`,
  linear: `Read-only access to your Linear issues (status, priority, team).`,
  github: `Read-only access to the GitHub issues & PRs you're involved in.`,
};
function connectorHelp(name) {
  const c = CONNECTORS.find((x) => x.name === name);
  const f = c?.secret_field;
  if (f) {
    // Connectors that authenticate with a single pasted token: show steps +
    // an in-app field (no .env editing, no restart needed).
    const steps = (f.steps || []).map((s) => `<li>${s}</li>`).join("");
    const link = f.help_url
      ? `<p style="margin:6px 0 12px"><a href="${f.help_url}" target="_blank" rel="noopener">Open ${c.label} to get your key →</a></p>` : "";
    openBrainModal(`Connect ${c.label}`,
      `<p>${CONNECTOR_HELP[name] || ""}</p>
       ${steps ? `<ol>${steps}</ol>` : ""}${link}
       <label class="t" style="display:block;margin-bottom:4px">${esc(f.label)}</label>
       <div style="display:flex;gap:8px">
         <input id="secretInput" type="password" autocomplete="off" spellcheck="false"
                placeholder="${esc(f.placeholder || "")}"
                style="flex:1;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font-family:monospace" />
         <button id="secretSave" class="tiny">Save</button>
       </div>
       <p class="t" style="margin-top:8px">Stored locally on your Mac only
         (<code>~/Library/Lodestone/secrets.json</code>) — never uploaded.</p>`);
    const input = $("#secretInput");
    input.focus();
    $("#secretSave").onclick = async () => {
      const value = input.value.trim();
      if (!value) { toast("paste your key first"); return; }
      $("#secretSave").disabled = true; $("#secretSave").textContent = "Saving…";
      try {
        const r = await api(`/api/connectors/${name}/secret`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value }) });
        if (r.ready) {
          toast(`${c.label} connected ✓ — syncing…`);
          $("#brainModal").hidden = true;
          await syncConn(name);
        } else {
          toast(r.reason || "saved, but not ready yet");
        }
        loadBrain();
      } catch (e) { toast(String(e)); }
      finally { $("#secretSave").disabled = false; $("#secretSave").textContent = "Save"; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#secretSave").click(); });
    return;
  }
  openBrainModal(`Set up ${name}`, (CONNECTOR_HELP[name] || "<p>No setup needed.</p>")
    + `<p class="t" style="margin-top:10px">Add the value to your <code>.env</code> and restart Lodestone.</p>`);
}

// ── custom API app: connect any REST app, no code ──────────────────────────
function customAppForm(app) {
  app = app || {};
  const row = (label, id, val, ph) =>
    `<label class="t" style="display:block;margin:8px 0 3px">${label}</label>
     <input id="${id}" value="${esc(val || "")}" placeholder="${esc(ph || "")}" spellcheck="false"
       style="width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)" />`;
  const at = app.auth_type || "none";
  const opt = (v, t) => `<option value="${v}"${at === v ? " selected" : ""}>${t}</option>`;
  openBrainModal(app.id ? `Edit ${app.name}` : "Connect a custom app",
    `<p class="t">Point Lodestone at any REST API that returns JSON. It fetches the
       endpoint and adds each record to your brain. Stays on your Mac.</p>
     ${row("App name", "ca_name", app.name, "My CRM")}
     ${row("Base URL", "ca_base", app.base_url, "https://api.myapp.com/v1")}
     ${row("Endpoint", "ca_ep", app.endpoint, "/contacts")}
     <label class="t" style="display:block;margin:8px 0 3px">Auth</label>
     <select id="ca_auth" style="width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)">
       ${opt("none", "None")}${opt("bearer", "Bearer token")}${opt("header", "Custom header")}${opt("query", "Query parameter")}</select>
     ${row("Header / param name (for custom header or query)", "ca_authname", app.auth_name, "X-API-Key")}
     ${row("Token (leave blank to keep current)", "ca_token", "", "•••••••• stored locally, chmod 600")}
     <hr style="border:none;border-top:1px solid var(--line);margin:12px 0">
     <p class="t">Map the JSON (dot-paths, e.g. <code>data.results</code>):</p>
     ${row("Items path — where the list lives", "ca_items", app.items_path, "data.results")}
     ${row("Title field", "ca_title", app.title_field, "name")}
     ${row("Body field", "ca_body", app.body_field, "notes")}
     <div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end">
       <button id="ca_save" class="tiny">${app.id ? "Save changes" : "Save & sync"}</button></div>`);
  $("#ca_name").focus();
  $("#ca_save").onclick = async () => {
    const payload = {
      id: app.id || null,
      name: $("#ca_name").value.trim() || "Custom app",
      base_url: $("#ca_base").value.trim(),
      endpoint: $("#ca_ep").value.trim(),
      auth_type: $("#ca_auth").value,
      auth_name: $("#ca_authname").value.trim(),
      items_path: $("#ca_items").value.trim(),
      title_field: $("#ca_title").value.trim(),
      body_field: $("#ca_body").value.trim(),
    };
    const tok = $("#ca_token").value.trim();
    if (tok) payload.token = tok;
    if (!payload.base_url) { toast("base URL is required"); return; }
    $("#ca_save").disabled = true; $("#ca_save").textContent = "Saving…";
    try {
      const r = await api("/api/custom-apps", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload) });
      $("#brainModal").hidden = true;
      toast("custom app saved — syncing…");
      await syncConn(r.name);
      loadBrain();
    } catch (e) { toast(String(e)); $("#ca_save").disabled = false; $("#ca_save").textContent = "Save"; }
  };
}
$("#addCustomApp").onclick = () => customAppForm();

// ── tasks ────────────────────────────────────────────────────────────────
function dueLabel(iso) {
  if (!iso) return { text: "", cls: "" };
  const today = new Date().toISOString().slice(0, 10);
  const d = new Date(iso + "T00:00:00");
  const nice = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  if (iso < today) return { text: "overdue · " + nice, cls: "over" };
  if (iso === today) return { text: "today", cls: "today" };
  return { text: nice, cls: "" };
}

async function loadTasks() {
  const d = await api("/api/tasks");
  const n = d.stats.today, o = d.stats.overdue;
  $("#taskCount").textContent =
    d.tasks.length ? `· ${n} today${o ? ", " + o + " overdue" : ""}` : "";
  if (!d.tasks.length) {
    $("#taskList").innerHTML = `<div class="tasks-empty">No open tasks. Add one, or ask an agent.</div>`;
    return;
  }
  $("#taskList").innerHTML = d.tasks.map((t) => {
    const due = dueLabel(t.due);
    return `<div class="task">
      <span class="check" data-done="${t.id}">✓</span>
      <div class="body">
        <div class="ttl">${esc(t.title)}</div>
        ${due.text ? `<div class="due ${due.cls}">${due.text}</div>` : ""}
      </div>
      <span class="del" data-del-task="${t.id}">✕</span>
    </div>`;
  }).join("");
  document.querySelectorAll("[data-done]").forEach((el) => el.onclick = async () => {
    await api(`/api/tasks/${el.dataset.done}/complete`, { method: "POST" });
    toast("Done ✓"); loadTasks();
  });
  document.querySelectorAll("[data-del-task]").forEach((el) => el.onclick = async () => {
    await api(`/api/tasks/${el.dataset.delTask}`, { method: "DELETE" });
    loadTasks();
  });
}

async function loadReminders() {
  try {
    const { reminders } = await api("/api/reminders");
    $("#reminderWrap").hidden = reminders.length === 0;
    $("#reminderList").innerHTML = reminders.map((r) => {
      const when = new Date(r.fire_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      return `<div class="task"><div class="body"><div class="ttl">${esc(r.label || r.message)}</div>
        <div class="due today">${esc(when)}${r.agent_id ? " · " + esc(r.agent_id) : ""}</div></div>
        <span class="del" data-del-rem="${r.id}">✕</span></div>`;
    }).join("");
    document.querySelectorAll("[data-del-rem]").forEach((b) => b.onclick = async () => {
      await api(`/api/reminders/${b.dataset.delRem}`, { method: "DELETE" });
      toast("Reminder removed"); loadReminders();
    });
  } catch (_) {}
}

async function addTask() {
  const title = $("#taskInput").value.trim();
  if (!title) return;
  await api("/api/tasks", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  $("#taskInput").value = "";
  toast("Task added"); loadTasks();
}
$("#taskAdd").onclick = addTask;
$("#taskInput").addEventListener("keydown", (e) => { if (e.key === "Enter") addTask(); });

// ── folder picker ──────────────────────────────────────────────────────────
let pickPath = null;
async function openPicker(path) {
  const d = await api("/api/fs/browse" + (path ? `?path=${encodeURIComponent(path)}` : ""));
  pickPath = d.path;
  $("#picker").hidden = false;
  $("#pickPath").textContent = d.path;
  $("#pickInfo").textContent = d.ingestible_here
    ? `${d.ingestible_here} ingestible file(s) directly here` : "no text files directly here (subfolders may still have them)";
  let rows = "";
  if (d.parent) rows += `<div class="pick-row up" data-go="${esc(d.parent)}">⤴  ..</div>`;
  rows += d.dirs.map((name) => `<div class="pick-row" data-go="${esc(d.path.replace(/\/$/, "") + "/" + name)}">📁  ${esc(name)}</div>`).join("");
  $("#pickList").innerHTML = rows || `<div class="pick-row up">(no subfolders)</div>`;
  document.querySelectorAll("#pickList [data-go]").forEach((el) => el.onclick = () => openPicker(el.dataset.go));
}
$("#pickClose").onclick = () => $("#picker").hidden = true;
$("#pickIngest").onclick = async () => {
  $("#picker").hidden = true;
  toast(`ingesting ${pickPath.split("/").pop()}…`);
  try {
    const r = await api(`/api/connectors/files/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params: { path: pickPath } }) });
    toast(r.errors?.length ? `files: ${r.errors[0]}` : `files: +${r.added} added from ${r.detail}`);
    loadBrain();
  } catch (e) { toast(String(e)); }
};

$("#composer").onsubmit = (e) => {
  e.preventDefault();
  if (busy) { if (controller) controller.abort(); return; }   // Stop
  const v = $("#input").value.trim();
  if (v && current) { $("#input").value = ""; autoGrow(); send(v); }
};
$("#input").addEventListener("input", autoGrow);
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#clearBtn").onclick = async () => { await api(`/api/agents/${current}/clear`, { method: "POST" }); selectAgent(current); toast("chat cleared"); };
$("#ingestBtn").onclick = async () => {
  const t = $("#ingestText").value.trim(); if (!t) return;
  await api("/api/brain/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) });
  $("#ingestText").value = ""; toast("added to brain"); loadBrain();
};

// ── automations / routines ─────────────────────────────────────────────────
async function loadRoutines() {
  try {
    const { routines } = await api("/api/routines");
    $("#routineList").innerHTML = routines.length ? routines.map((r) => {
      const trig = r.trigger === "new_email" ? "on new email" : `every ${r.interval_min}m`;
      return `<div class="task"><div class="body">
        <div class="ttl">${esc(r.name)} ${r.enabled ? "" : "<span class='t'>(off)</span>"}</div>
        <div class="due">${trig} · ${esc(r.agent_id)}</div></div>
        <span><span class="check" data-toggle-r="${r.id}" data-on="${r.enabled}" title="${r.enabled ? "disable" : "enable"}">${r.enabled ? "⏸" : "▶"}</span>
        <span class="del" data-del-r="${r.id}">✕</span></span></div>`;
    }).join("") : `<div class="tasks-empty">No automations yet.</div>`;
    document.querySelectorAll("[data-toggle-r]").forEach((b) => b.onclick = async () => {
      await api(`/api/routines/${b.dataset.toggleR}/toggle?on=${b.dataset.on !== "1"}`, { method: "POST" });
      loadRoutines();
    });
    document.querySelectorAll("[data-del-r]").forEach((b) => b.onclick = async () => {
      await api(`/api/routines/${b.dataset.delR}`, { method: "DELETE" }); toast("Automation removed"); loadRoutines();
    });
  } catch (_) {}
}
$("#newRoutineBtn").onclick = async () => {
  const { agents } = await api("/api/agents");
  $("#rmAgent").innerHTML = agents.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  $("#rmName").value = ""; $("#rmInstruction").value = ""; $("#rmInterval").value = "60";
  $("#routineModal").hidden = false;
};
$("#rmTrigger").onchange = () => { $("#rmIntervalWrap").hidden = $("#rmTrigger").value !== "schedule"; };
$("#rmClose").onclick = () => $("#routineModal").hidden = true;
$("#rmCreate").onclick = async () => {
  const name = $("#rmName").value.trim(), instruction = $("#rmInstruction").value.trim();
  if (!name || !instruction) { toast("Name & instruction required"); return; }
  await api("/api/routines", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, agent_id: $("#rmAgent").value, trigger: $("#rmTrigger").value,
      instruction, interval_min: parseInt($("#rmInterval").value) || 60 }) });
  $("#routineModal").hidden = true; toast("Automation created"); loadRoutines();
};

// ── create custom agent ─────────────────────────────────────────────────
async function openAgentModal() {
  const { tools } = await api("/api/agents/tools");
  $("#amTools").innerHTML = tools.map((t) =>
    `<label class="am-tool"><input type="checkbox" value="${t.name}" ${["search_brain", "remember", "web_search"].includes(t.name) ? "checked" : ""}/> ${t.name}</label>`).join("");
  $("#amName").value = ""; $("#amRole").value = ""; $("#amPrompt").value = "";
  $("#agentModal").hidden = false;
}
$("#newAgentBtn").onclick = openAgentModal;
$("#amClose").onclick = () => $("#agentModal").hidden = true;
$("#amCreate").onclick = async () => {
  const name = $("#amName").value.trim();
  if (!name) { toast("Name required"); return; }
  const chosen = [...document.querySelectorAll("#amTools input:checked")].map((c) => c.value);
  const a = await api("/api/agents/custom", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role: $("#amRole").value.trim(),
      system_prompt: $("#amPrompt").value.trim(), tools: chosen }) });
  $("#agentModal").hidden = true; toast("Agent created");
  await loadAgents(); selectAgent(a.id);
};

// ── onboarding ───────────────────────────────────────────────────────────
function openOnboard() { $("#onboard").hidden = false; }
function closeOnboard() {
  $("#onboard").hidden = true;
  localStorage.setItem("lodestone_onboarded", "1");
}
function flashConnectors() {
  const el = $("#connectors");
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
}
$("#obSkip").onclick = closeOnboard;
$("#obDone").onclick = closeOnboard;
$("#obGoogle").onclick = () => { closeOnboard(); flashConnectors(); connectGoogle(); };
$("#obLocal").onclick = () => { closeOnboard(); flashConnectors();
  toast("Pick Files, Apple Mail, Calendar or iMessage below → click setup"); };
$("#obApps").onclick = () => { closeOnboard(); flashConnectors();
  toast("Notion · Linear · GitHub — or + Connect a custom app"); };
$("#obFact").onclick = () => { closeOnboard(); $("#ingestText").focus();
  $("#ingestText").scrollIntoView({ behavior: "smooth" }); };
$("#helpBtn").onclick = openOnboard;

// ── brain export / import (you own your data) ──────────────────────────────
$("#brainExport").onclick = async () => {
  try {
    const r = await fetch("/api/brain/export");
    if (!r.ok) throw new Error("export failed");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `lodestone-brain-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    toast("Brain exported ✓");
  } catch (e) { toast(String(e)); }
};
$("#brainImport").onclick = () => $("#brainImportFile").click();
$("#brainImportFile").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const r = await api("/api/brain/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data) });
    toast(`Imported ${r.added} memories${r.skipped ? ` · ${r.skipped} already had` : ""}`);
    loadBrain();
  } catch (err) { toast("Import failed — is it a Lodestone backup?"); }
  finally { e.target.value = ""; }
};

async function maybeOnboard() {
  // Only a genuine first run (never onboarded in this browser) goes to the
  // onboarding flow. Once onboarded, reloading always stays in the workspace —
  // even if the brain is still empty/building. (A reset clears this flag, so the
  // reset flow still sends you back through onboarding.)
  if (!localStorage.getItem("lodestone_onboarded")) {
    window.location.href = "/onboarding";
    return true;
  }
  return false;
}

// ── first entry: meet + name your lead agent, who then teaches the app ──────
async function maybeWelcome() {
  if (!localStorage.getItem("lodestone_onboarded")) return;
  if (localStorage.getItem("lodestone_lead_agent")) return;   // already have a lead
  const wrap = $("#welcome"); if (!wrap) return;
  wrap.hidden = false;
  const inp = $("#wName"); inp.focus(); inp.select();
  const go = () => createLead(inp.value.trim());
  $("#wCreate").onclick = go;
  inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
  $("#wSkip").onclick = () => { wrap.hidden = true; localStorage.setItem("lodestone_lead_agent", "skipped"); };
}
async function createLead(name) {
  name = (name || "Atlas").trim() || "Atlas";
  const btn = $("#wCreate"), note = $("#wNote");
  btn.disabled = true; btn.textContent = "Creating…"; note.textContent = `Building ${name} from your brain…`;
  try {
    const r = await api("/api/agents/lead", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }) });
    localStorage.setItem("lodestone_lead_agent", r.id);
    $("#welcome").hidden = true;
    await loadAgents();
    await selectAgent(r.id);
    agentWelcome(r.id);           // the agent introduces itself + teaches the app
  } catch (e) {
    btn.disabled = false; btn.textContent = "Create →"; toast(String(e));
    note.textContent = "Couldn't create the agent — try again.";
  }
}
async function agentWelcome(id) {
  if (busy) return;
  setBusy(true);
  const think = makeThinking($("#provider").value);
  try {
    const res = await api(`/api/agents/${id}/welcome`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "welcome", provider: $("#provider").value,
        model: $("#modelName").value.trim() || null }) });
    think.done();
    addMsg("assistant", res.reply);
  } catch (e) { think.done(); addMsg("assistant", "⚠️ " + e); }
  finally { setBusy(false); }
}

// ── live brain-building status ─────────────────────────────────────────────
// Sync started in onboarding keeps running here; this pill shows how the brain
// is filling in real time. Click to kick a fresh sync.
let _wasSyncing = false;
async function updateBrainStatus() {
  const el = $("#brainStatus");
  if (!el) return;
  try {
    const [s, st] = await Promise.all([
      api("/api/sync/status"), api("/api/brain/stats"),
    ]);
    const mem = (st.total || 0).toLocaleString();
    const ent = (st.graph?.entities || 0).toLocaleString();
    if (s.syncing) {
      el.classList.add("syncing");
      el.innerHTML = `<span class="bs-dot"></span>Building your brain… <b>${mem}</b> memories`;
    } else {
      el.classList.remove("syncing");
      el.innerHTML = `<span class="bs-dot"></span>Brain ready · <b>${mem}</b> memories · <b>${ent}</b> entities`;
      if (_wasSyncing) loadBrain();   // refresh panels when a sync just finished
    }
    _wasSyncing = s.syncing;
  } catch (_) {}
}
// clicking the header status (or the sidebar Brain nav) opens the full brain screen
{ const el = $("#brainStatus"); if (el) el.onclick = () => openBrainScreen(); }

// ── full-screen "Your Brain" view: live neural viz + real building status ────
let _bsPoll = null, _bsRaf = null, _bsNodes = null, _bsRot = 0, _bsDensity = 0.15;
function _bsBuildNodes() {
  // ~520 points on a jittered sphere → reads as a neural cluster
  const N = 520, pts = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
    const jit = 0.12;
    pts.push({ x: Math.cos(th) * r + (Math.random() - 0.5) * jit, y: y + (Math.random() - 0.5) * jit,
      z: Math.sin(th) * r + (Math.random() - 0.5) * jit, p: Math.random() * 6.28 });
  }
  _bsNodes = pts;
}
function _bsDraw() {
  const cv = $("#bsCanvas"); if (!cv || $("#brainScreen").hidden) return;
  const dpr = Math.min(devicePixelRatio || 1, 2), W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  _bsRot += 0.0016;
  const cx = W / 2, cy = H * 0.46, R = Math.min(W, H) * 0.30;
  const sy = Math.sin(_bsRot), cyr = Math.cos(_bsRot), t = Date.now() / 1000;
  const shown = Math.max(40, Math.floor(_bsNodes.length * (0.25 + 0.75 * _bsDensity)));
  const proj = [];
  for (let i = 0; i < shown; i++) {
    const n = _bsNodes[i];
    const x1 = n.x * cyr + n.z * sy, z1 = -n.x * sy + n.z * cyr;
    const sx = cx + x1 * R, sYy = cy + n.y * R, depth = (z1 + 1) / 2;
    proj.push({ sx, sy: sYy, depth, p: n.p });
  }
  // links between nearby points (front-ish only)
  ctx.lineWidth = 0.6;
  for (let i = 0; i < proj.length; i += 2) {
    for (let j = i + 1; j < Math.min(i + 10, proj.length); j++) {
      const dx = proj[i].sx - proj[j].sx, dy = proj[i].sy - proj[j].sy, d = dx * dx + dy * dy;
      if (d < 46 * 46 && proj[i].depth > 0.35) {
        ctx.strokeStyle = `rgba(120,160,240,${(0.05 + 0.06 * proj[i].depth).toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(proj[i].sx, proj[i].sy); ctx.lineTo(proj[j].sx, proj[j].sy); ctx.stroke();
      }
    }
  }
  for (const p of proj) {
    const pulse = 0.5 + 0.5 * Math.sin(t * 1.5 + p.p);
    const a = (0.25 + 0.6 * p.depth) * (0.6 + 0.4 * pulse);
    const rad = 0.7 + 1.7 * p.depth;
    ctx.fillStyle = `rgba(${170 + 60 * p.depth | 0},${195 + 40 * p.depth | 0},255,${a.toFixed(3)})`;
    ctx.beginPath(); ctx.arc(p.sx, p.sy, rad, 0, 6.283); ctx.fill();
  }
  _bsRaf = requestAnimationFrame(_bsDraw);
}
async function _bsRefresh() {
  try {
    const [s, st] = await Promise.all([api("/api/sync/status"), api("/api/brain/stats")]);
    const mem = st.total || 0, ent = st.graph?.entities || 0, rel = st.graph?.relations || 0;
    $("#bsMem").textContent = mem.toLocaleString();
    $("#bsEnt").textContent = ent.toLocaleString();
    $("#bsRel").textContent = rel.toLocaleString();
    _bsDensity = Math.min(1, 0.15 + mem / 4000);
    const state = $("#bsState");
    if (s.syncing) { state.textContent = "Building your brain…"; state.classList.remove("done"); }
    else { state.textContent = "Brain ready"; state.classList.add("done"); }
  } catch (_) {}
}
function openBrainScreen() {
  const m = $("#brainScreen"); if (!m) return;
  m.hidden = false;
  if (!_bsNodes) _bsBuildNodes();
  _bsRefresh(); clearInterval(_bsPoll); _bsPoll = setInterval(_bsRefresh, 2500);
  cancelAnimationFrame(_bsRaf); _bsRaf = requestAnimationFrame(_bsDraw);
}
function closeBrainScreen() {
  $("#brainScreen").hidden = true;
  clearInterval(_bsPoll); _bsPoll = null; cancelAnimationFrame(_bsRaf); _bsRaf = null;
}
$("#bsClose").onclick = closeBrainScreen;
$("#bsSync").onclick = async () => {
  try { const r = await api("/api/sync/now", { method: "POST" });
    toast(r.started ? "syncing your sources…" : (r.reason || "already syncing"));
    _bsRefresh(); updateBrainStatus();
  } catch (e) { toast(String(e)); }
};
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#brainScreen").hidden) closeBrainScreen(); });

// ── slide-over drawers opened from the left nav ─────────────────────────────
const DRAWER_TITLES = { brain: "Brain", sources: "Sources", tasks: "Tasks", model: "AI model" };
function openDrawer(name) {
  const bg = $("#drawerBg"); if (!bg) return;
  $("#drawerTitle").textContent = DRAWER_TITLES[name] || name;
  document.querySelectorAll(".dpanel").forEach((p) => p.hidden = p.dataset.d !== name);
  bg.hidden = false;
  if (name === "brain" || name === "sources") loadBrain();
  if (name === "tasks") { loadTasks(); loadReminders(); loadRoutines(); }
  if (name === "model") loadProviders();
}
function closeDrawer() { const bg = $("#drawerBg"); if (bg) bg.hidden = true; }
document.querySelectorAll(".snav").forEach((b) => b.onclick = () => {
  if (b.id === "helpBtn") return openDrawer("sources");
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
  loadAgents(); loadProviders(); loadBrain(); loadTasks(); loadReminders(); loadRoutines();
  updateBrainStatus(); maybeWelcome();
  // poll the brain status often while it's building, and keep time-based panels fresh
  setInterval(updateBrainStatus, 5000);
  setInterval(() => { loadReminders(); loadRoutines(); }, 45000);
})();
