/**
 * The things the workspace keeps for you: approvals, tasks, reminders,
 * routines, the folder picker, and first-run.
 *
 * **The approvals queue is the visible half of the unattended-action gate.** An
 * agent reading a new email is reading text a stranger wrote, and that text can
 * contain an instruction aimed at the model. Anything leaving the machine
 * without a permitted recipient waits here for one tap, and `decide()` says
 * what happened either way — an approval that silently does nothing is the same
 * bug as a dead spinner.
 *
 * First-run lives here too: the welcome, naming the lead agent, and the
 * one-time intro. `flashConnectors` exists because pointing at the thing you
 * mean is better than describing where it is.
 */

async function loadApprovals() {
  const box = $("#approvals");
  if (!box) return;
  let rows;
  try {
    rows = (await api("/api/agents/approvals")).approvals || [];
  } catch {
    return;                       // a failed poll must not blank a live list
  }
  if (!rows.length) { box.hidden = true; box.innerHTML = ""; return; }

  box.hidden = false;
  box.innerHTML =
    `<div class="ctx-label">Waiting for you (${rows.length})</div>` +
    rows.map((a) => `
      <div class="apr" data-apr="${esc(a.id)}">
        <div class="apr-sum">${esc(a.summary)}</div>
        <div class="apr-why">${esc(a.reason || "")}${
          a.routine_name ? ` · from “${esc(a.routine_name)}”` : ""}</div>
        <div class="apr-btns">
          <button class="tiny" data-aprok="${esc(a.id)}">Approve</button>
          <button class="tiny ghost" data-aprno="${esc(a.id)}">Dismiss</button>
        </div>
      </div>`).join("");

  const decide = async (id, verb, path) => {
    const card = box.querySelector(`[data-apr="${id}"]`);
    if (card) card.classList.add("apr-busy");
    try {
      const r = await api(`/api/agents/approvals/${encodeURIComponent(id)}/${path}`,
                          { method: "POST" });
      // Say what happened, including when the action itself failed — an
      // approval that silently does nothing is the same bug as a dead spinner.
      toast(r.ok === false ? (r.error || `couldn't ${verb} that`)
                           : (r.detail || `${verb}d`));
    } catch (e) {
      toast(String(e));
    }
    loadApprovals();
  };

  box.querySelectorAll("[data-aprok]").forEach((b) =>
    b.onclick = () => decide(b.dataset.aprok, "approve", "approve"));
  box.querySelectorAll("[data-aprno]").forEach((b) =>
    b.onclick = () => decide(b.dataset.aprno, "dismiss", "reject"));
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
  rows += d.dirs.map((name) => `<div class="pick-row" data-go="${esc(d.path.replace(/\/$/, "") + "/" + name)}">${esc(name)}</div>`).join("");
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
        <span><span class="check" data-toggle-r="${r.id}" data-on="${r.enabled}" title="${r.enabled ? "disable" : "enable"}">${r.enabled ? "‖" : "▶"}</span>
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
  $("#rmAgent").innerHTML = agents.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("");
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
  // The value is the id the agent stores; the text is what a person reads.
  // They differ for a connector tool, whose id is a qualified name we minted.
  $("#amTools").innerHTML = tools.map((t) =>
    `<label class="am-tool"><input type="checkbox" value="${esc(t.name)}" ${["search_brain", "remember", "web_search"].includes(t.name) ? "checked" : ""}/> ${esc(toolLabel(t))}</label>`).join("");
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
  // Onboarded state lives on the SERVER (survives the desktop app's per-launch
  // port, which resets localStorage). Only a genuine first run goes to onboarding.
  try {
    const s = await api("/api/onboarded");
    if (s.onboarded) return false;
  } catch (_) {}
  if (localStorage.getItem("lodestone_onboarded")) return false;   // legacy fallback
  window.location.href = "/onboarding";
  return true;
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
  } catch (e) { think.done(); addMsg("assistant", "△ " + e); }
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
