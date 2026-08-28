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
  let params = {};
  if (name === "files") { const p = prompt("Folder/file to ingest:"); if (!p) return; params = { path: p }; }
  toast(`syncing ${name}…`);
  try {
    const r = await api(`/api/connectors/${name}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ params }) });
    toast(r.errors?.length ? `${name}: ${r.errors[0]}` : `${name}: +${r.added} added`);
    loadBrain();
  } catch (e) { toast(String(e)); }
}

$("#composer").onsubmit = (e) => { e.preventDefault(); const v = $("#input").value.trim(); if (v && current) { $("#input").value = ""; send(v); } };
$("#clearBtn").onclick = async () => { await api(`/api/agents/${current}/clear`, { method: "POST" }); selectAgent(current); toast("chat cleared"); };
$("#ingestBtn").onclick = async () => {
  const t = $("#ingestText").value.trim(); if (!t) return;
  await api("/api/brain/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) });
  $("#ingestText").value = ""; toast("added to brain"); loadBrain();
};

loadAgents(); loadProviders(); loadBrain();
