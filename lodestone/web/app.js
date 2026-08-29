const $ = (s) => document.querySelector(s);
const api = (p, o) => fetch(p, o).then((r) => r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText)));
let current = null;
let agents = [];

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }
function esc(s) { return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

async function loadAgents() {
  const d = await api("/api/agents");
  agents = d.agents;
  $("#agentList").innerHTML = agents.map((a) => `
    <div class="agent ${a.id === current ? "active" : ""}" data-id="${a.id}">
      <span class="n">${a.name}</span><span class="r">${a.role}</span>
    </div>`).join("");
  document.querySelectorAll(".agent").forEach((el) => el.onclick = () => selectAgent(el.dataset.id));
  if (!current && agents.length) selectAgent(agents[0].id);
}

async function loadProviders() {
  const d = await api("/api/providers");
  $("#provider").innerHTML = d.providers.map((p) =>
    `<option value="${p.name}" ${p.name === d.active ? "selected" : ""}>${p.name}${p.ready ? "" : " (not ready)"}</option>`).join("");
}

async function selectAgent(id) {
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
  if (!history.length) { box.innerHTML = `<div class="msg empty">This agent shares your brain. Say hello — it already knows you.</div>`; return; }
  box.innerHTML = history.filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("");
  box.scrollTop = box.scrollHeight;
}

function addMsg(role, text) {
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

async function send(text) {
  addMsg("user", text);
  const spin = addMsg("assistant", ""); spin.classList.add("spin"); spin.textContent = "thinking…";
  try {
    const res = await api(`/api/agents/${current}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, provider: $("#provider").value }),
    });
    spin.remove();
    addTrace(res.trace || []);
    addMsg("assistant", res.reply);
    loadBrain();
    loadTasks();   // an agent may have added/completed a task this turn
  } catch (e) { spin.remove(); addMsg("assistant", "⚠️ " + e); }
}

async function loadBrain() {
  const s = await api("/api/brain/stats");
  $("#brainStats").innerHTML = `
    <div class="b"><div class="num">${s.total}</div><div class="lbl">memories</div></div>
    <div class="b"><div class="num">${s.graph.entities}</div><div class="lbl">entities</div></div>
    <div class="b"><div class="num">${s.graph.relations}</div><div class="lbl">facts</div></div>`;
  const { entities } = await api("/api/brain/entities?limit=20");
  $("#entities").innerHTML = entities.length ? entities.map((e) =>
    `<div class="ent">${esc(e.name)} <span class="t">${e.type} · ${e.mentions}×</span></div>`).join("")
    : `<div class="ent t">empty — add notes or sync a connector</div>`;
  const { connectors } = await api("/api/connectors");
  $("#connectors").innerHTML = connectors.map((c) =>
    `<div class="conn"><span><span class="dot ${c.ready ? "ok" : "off"}"></span>${c.label}</span>
     <button class="tiny ghost" data-sync="${c.name}">sync</button></div>`).join("");
  document.querySelectorAll("[data-sync]").forEach((b) => b.onclick = () => syncConn(b.dataset.sync));
}

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

$("#composer").onsubmit = (e) => { e.preventDefault(); const v = $("#input").value.trim(); if (v && current) { $("#input").value = ""; send(v); } };
$("#clearBtn").onclick = async () => { await api(`/api/agents/${current}/clear`, { method: "POST" }); selectAgent(current); toast("chat cleared"); };
$("#ingestBtn").onclick = async () => {
  const t = $("#ingestText").value.trim(); if (!t) return;
  await api("/api/brain/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) });
  $("#ingestText").value = ""; toast("added to brain"); loadBrain();
};

loadAgents(); loadProviders(); loadBrain(); loadTasks();
