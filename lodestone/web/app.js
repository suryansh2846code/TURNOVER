const $ = (s) => document.querySelector(s);
const api = (p, o) => fetch(p, o).then((r) => r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText)));
let current = null;
let agents = [];

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }
function esc(s) { return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

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
  $("#agentList").innerHTML = agents.map((a) => `
    <div class="agent ${a.id === current ? "active" : ""}" data-id="${a.id}">
      <span class="n">${esc(a.name)}${a.custom ? ` <span class="del-agent" data-del-agent="${a.id}">✕</span>` : ""}</span>
      <span class="r">${esc(a.role)}</span>
    </div>`).join("");
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
function applyModelHint() { $("#modelHint").textContent = MODEL_HINTS[$("#provider").value] || ""; }

async function loadProviders() {
  const d = await api("/api/providers");
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
  const a = agents.find((x) => x.id === id);
  $("#agentName").textContent = a.name;
  $("#agentRole").textContent = a.role + " · tools: " + a.tools.join(", ");
  document.querySelectorAll(".agent").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const { history } = await api(`/api/agents/${id}/history`);
  renderHistory(history);
}

function renderHistory(history) {
  const box = $("#messages");
  box.innerHTML = "";
  const msgs = history.filter((m) => m.role === "user" || m.role === "assistant");
  if (!msgs.length) {
    box.innerHTML = `<div class="msg empty">This agent shares your brain. Say hello — it already knows you.</div>`;
    return;
  }
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
  if (role === "assistant") {
    const { clean, actions } = parseActions(text);
    const el = document.createElement("div");
    el.className = "msg assistant";
    el.innerHTML = md(clean);
    $("#messages").appendChild(el);
    for (const a of actions) $("#messages").appendChild(actionCard(a));
    $("#messages").scrollTop = 1e9; return el;
  }
  const el = document.createElement("div");
  el.className = "msg " + role; el.textContent = text;
  $("#messages").appendChild(el); $("#messages").scrollTop = 1e9; return el;
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

async function send(text) {
  if (busy) return;             // guard: ignore sends while a turn is running
  setBusy(true);
  controller = new AbortController();
  addMsg("user", text);
  const spin = addMsg("assistant", ""); spin.classList.add("spin"); spin.textContent = "thinking…";
  try {
    const res = await api(`/api/agents/${current}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, provider: $("#provider").value,
        model: $("#modelName").value.trim() || null }),
      signal: controller.signal,
    });
    spin.remove();
    addTrace(res.trace || []);
    addMsg("assistant", res.reply);
    loadBrain();
    loadTasks();       // an agent may have added/completed a task this turn
    loadReminders();   // …or set a reminder
  } catch (e) {
    spin.remove();
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
  const { entities } = await api("/api/brain/entities?limit=20");
  $("#entities").innerHTML = entities.length ? entities.map((e) =>
    `<div class="ent" data-entity="${e.id}" title="click for facts"><span class="etype ${e.type}">${e.type}</span> ${esc(e.name)} <span class="t">${e.mentions}×</span></div>`).join("")
    : `<div class="ent t">empty — add notes or sync a connector</div>`;
  document.querySelectorAll("[data-entity]").forEach((el) =>
    el.onclick = () => openEntity(el.dataset.entity));
  const { connectors } = await api("/api/connectors");
  $("#connectors").innerHTML = connectors.map((c) => {
    const last = c.state?.last_sync ? new Date(c.state.last_sync).toLocaleDateString() : "";
    const sub = c.ready ? (last ? `synced ${last}` : "ready") : (c.reason || "not configured");
    const btn = c.ready
      ? `<button class="tiny ghost" data-sync="${c.name}">sync</button>`
      : `<button class="tiny" data-setup="${c.name}">setup</button>`;
    return `<div class="conn">
      <span class="conn-meta"><span class="dot ${c.ready ? "ok" : "off"}"></span>
        <span><span class="conn-name">${c.label}</span><span class="conn-sub">${esc(sub)}</span></span></span>
      ${btn}</div>`;
  }).join("");
  document.querySelectorAll("[data-sync]").forEach((b) => b.onclick = () => syncConn(b.dataset.sync));
  document.querySelectorAll("[data-setup]").forEach((b) => b.onclick = () => connectorHelp(b.dataset.setup));
  loadSyncStatus();
  // one-click Google sign-in when a bundled client exists but we're not connected
  try {
    const g = await api("/api/google/status");
    $("#googleSignin").hidden = !(g.client_configured && !g.connected);
  } catch (_) {}
}
$("#googleSignin").onclick = async () => {
  $("#googleSignin").textContent = "Opening Google…"; $("#googleSignin").disabled = true;
  try {
    const r = await api("/api/google/reconnect", { method: "POST" });
    toast(r.detail || "Approve in the browser window");
    // poll until connected, then refresh connectors
    const poll = setInterval(async () => {
      const g = await api("/api/google/status");
      if (g.connected) { clearInterval(poll); toast("Google connected ✓"); loadBrain(); }
    }, 3000);
  } catch (e) { toast(String(e)); }
  finally { setTimeout(() => { $("#googleSignin").textContent = "Sign in with Google"; $("#googleSignin").disabled = false; }, 4000); }
};

async function loadSyncStatus() {
  try {
    const s = await api("/api/sync/status");
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
  toast(`syncing ${name}…`);
  try {
    const r = await api(`/api/connectors/${name}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ params: {} }) });
    toast(r.errors?.length ? `${name}: ${r.errors[0]}` : `${name}: +${r.added} added`);
    loadBrain();
  } catch (e) { toast(String(e)); }
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
  notion: `<p>Read the Notion pages you share with an integration.</p><ol>
    <li>Create an internal integration at
        <b>notion.so/my-integrations</b> and copy its secret.</li>
    <li>Set <code>NOTION_TOKEN</code> to that secret.</li>
    <li><b>Share</b> the pages/databases you want with the integration (⋯ → Connections).</li></ol>`,
};
function connectorHelp(name) {
  openBrainModal(`Set up ${name}`, (CONNECTOR_HELP[name] || "<p>No setup needed.</p>")
    + `<p class="t" style="margin-top:10px">Add the value to your <code>.env</code> and restart Lodestone.</p>`);
}

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
$("#obSkip").onclick = closeOnboard;
$("#obDone").onclick = closeOnboard;
$("#obConnect").onclick = () => { closeOnboard(); openPicker(); };
$("#obFact").onclick = () => { closeOnboard(); $("#ingestText").focus();
  $("#ingestText").scrollIntoView({ behavior: "smooth" }); };
$("#helpBtn").onclick = openOnboard;

async function maybeOnboard() {
  // show on a fresh brain, or the first time this browser opens the app
  try {
    const s = await api("/api/brain/stats");
    if (s.total === 0 || !localStorage.getItem("lodestone_onboarded")) openOnboard();
  } catch (_) {}
}

loadAgents(); loadProviders(); loadBrain(); loadTasks(); loadReminders(); loadRoutines(); maybeOnboard();
// keep time-based panels fresh so fired reminders / completed sends update
setInterval(() => { loadReminders(); loadRoutines(); }, 45000);
