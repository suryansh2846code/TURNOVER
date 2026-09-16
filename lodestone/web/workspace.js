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

let REMINDERS = [];
let _editingReminder = null;     // null = creating

async function loadReminders() {
  try {
    const { reminders } = await api("/api/reminders");
    REMINDERS = reminders;
    $("#reminderList").innerHTML = reminders.length ? reminders.map((r) => {
      const when = new Date(r.fire_at).toLocaleString(undefined,
        { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      // Two different things share this list. A reminder is text with a time and
      // can be reworded; a queued ACTION is an email or an event an agent is
      // about to send, and a half-edited one is worse than one you cancel and
      // ask for again — so it offers cancel, not edit.
      const isAction = r.kind === "action";
      const edit = isAction ? ""
        : `<button class="tiny ghost" data-edit-rem="${r.id}">Edit</button>`;
      return `<div class="ib-row">
        <span class="ib-state" data-on="${isAction ? "queued" : "1"}" aria-hidden="true"></span>
        <span class="ib-text">
          <span class="ib-name">${esc(r.label || r.message)}${isAction ? `<span class="ib-badge">Queued action</span>` : ""}</span>
          <span class="ib-meta">${esc(when)}${r.agent_id ? " · " + esc(r.agent_id) : ""}</span>
        </span>
        <span class="ib-actions">${edit}
          <button class="tiny ghost ib-x" data-del-rem="${r.id}" aria-label="${isAction ? "Cancel" : "Delete"}">✕</button>
        </span></div>`;
    }).join("") : `<div class="ib-empty">Nothing coming up.</div>`;
    document.querySelectorAll("[data-del-rem]").forEach((b) => b.onclick = async () => {
      await api(`/api/reminders/${b.dataset.delRem}`, { method: "DELETE" });
      toast("Removed"); loadReminders();
    });
    document.querySelectorAll("[data-edit-rem]").forEach((b) => b.onclick = () =>
      reminderForm(REMINDERS.find((x) => x.id === b.dataset.editRem)));
  } catch (_) {}
}

//: `<input type="datetime-local">` speaks local wall time with no zone, which
//: is exactly what a person means by "9am" — so convert by hand rather than
//: through toISOString(), which would shift it to UTC and move the reminder.
function _toLocalInput(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function reminderForm(existing) {
  _editingReminder = existing || null;
  const when = existing ? new Date(existing.fire_at) : new Date(Date.now() + 60 * 60 * 1000);
  $("#remMessage").value = existing ? (existing.label || existing.message || "") : "";
  $("#remWhen").value = _toLocalInput(when);
  $("#remTitle").textContent = existing ? "Edit reminder" : "New reminder";
  $("#remSave").textContent = existing ? "Save" : "Create";
  $("#remHint").textContent = "";
  $("#reminderModal").hidden = false;
}
{
  const nb = $("#newReminderBtn"); if (nb) nb.onclick = () => reminderForm(null);
  const cl = $("#remClose"); if (cl) cl.onclick = () => { $("#reminderModal").hidden = true; };
  const bg = $("#reminderModal");
  if (bg) bg.onclick = (e) => { if (e.target.id === "reminderModal") bg.hidden = true; };
  const save = $("#remSave");
  if (save) save.onclick = async () => {
    const message = $("#remMessage").value.trim();
    const local = $("#remWhen").value;
    if (!message) { $("#remHint").textContent = "Say what it should remind you about."; return; }
    if (!local) { $("#remHint").textContent = "Pick a date and time."; return; }
    // The local value carries no zone. Stamping it with the browser's offset is
    // what keeps "9am" meaning 9am here rather than 9am UTC.
    const fire_at = new Date(local).toString() === "Invalid Date" ? null : _isoWithOffset(new Date(local));
    if (!fire_at) { $("#remHint").textContent = "That date does not look right."; return; }
    const editing = _editingReminder;
    try {
      if (editing) {
        await api(`/api/reminders/${editing.id}`, { method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, fire_at }) });
      } else {
        await api("/api/reminders", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, fire_at }) });
      }
    } catch (e) { $("#remHint").textContent = "Could not save that reminder."; return; }
    $("#reminderModal").hidden = true;
    _editingReminder = null;
    toast(editing ? "Reminder updated" : "Reminder set");
    loadReminders();
  };
}
function _isoWithOffset(d) {
  const p = (n) => String(n).padStart(2, "0");
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const a = Math.abs(off);
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    + `T${p(d.getHours())}:${p(d.getMinutes())}:00${sign}${p(Math.floor(a / 60))}:${p(a % 60)}`;
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
  if (busy) { stopTurn(); return; }   // Stop — the server hears about it
  const v = $("#input").value.trim();
  if ((v || attachments.length) && current) {
    $("#input").value = ""; autoGrow(); send(v);
  }
};
$("#input").addEventListener("input", () => { autoGrow(); updateConnectorPicker(); });
$("#input").addEventListener("blur", () => setTimeout(closeConnectorPicker, 120));
$("#input").addEventListener("keydown", (e) => {
  const picker = $("#cmpPicker");
  const open = picker && !picker.hidden;
  if (open && (e.key === "Enter" || e.key === "Tab")) {
    // While the picker is up, Enter chooses rather than sends — otherwise the
    // half-typed @mention goes to the agent as a word it has to ignore.
    e.preventDefault();
    const chosen = picker.querySelector(".cmp-opt.on") || picker.querySelector(".cmp-opt");
    if (chosen) chosen.click();
    return;
  }
  if (open && e.key === "Escape") { e.preventDefault(); closeConnectorPicker(); return; }
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
    ROUTINES = routines;
    $("#routineList").innerHTML = routines.length ? routines.map((r) => {
      const trig = r.trigger === "new_email" ? "When new email arrives"
        : `Every ${r.interval_min} min`;
      // An automation the user never watches run is one they cannot trust, so
      // the row says when it last ran and whether that run went anywhere.
      const ran = r.last_run
        ? `Last run ${new Date(r.last_run).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
        : "Not run yet";
      return `<div class="ib-row${r.enabled ? "" : " is-off"}">
        <span class="ib-state" data-on="${r.enabled ? 1 : 0}" aria-hidden="true"></span>
        <span class="ib-text">
          <span class="ib-name">${esc(r.name)}${r.enabled ? "" : `<span class="ib-badge">Paused</span>`}</span>
          <span class="ib-meta">${esc(trig)} · ${esc(r.agent_id)} · ${esc(ran)}</span>
        </span>
        <span class="ib-actions">
          <button class="tiny ghost" data-toggle-r="${r.id}" data-on="${r.enabled}">${r.enabled ? "Pause" : "Resume"}</button>
          <button class="tiny ghost" data-edit-r="${r.id}">Edit</button>
          <button class="tiny ghost ib-x" data-del-r="${r.id}" aria-label="Delete ${esc(r.name)}">✕</button>
        </span></div>`;
    }).join("") : `<div class="ib-empty">No automations yet. One is an instruction plus when to run it.</div>`;
    document.querySelectorAll("[data-edit-r]").forEach((b) => b.onclick = () =>
      routineForm(ROUTINES.find((x) => x.id === b.dataset.editR)));
    document.querySelectorAll("[data-toggle-r]").forEach((b) => b.onclick = async () => {
      await api(`/api/routines/${b.dataset.toggleR}/toggle?on=${b.dataset.on !== "1"}`, { method: "POST" });
      loadRoutines();
    });
    document.querySelectorAll("[data-del-r]").forEach((b) => b.onclick = async () => {
      const r = ROUTINES.find((x) => x.id === b.dataset.delR);
      // Deleting an automation stops future work; it does not undo past work.
      if (!confirm(`Delete "${r ? r.name : "this automation"}"? It stops running from now on — anything it already did stays.`)) return;
      await api(`/api/routines/${b.dataset.delR}`, { method: "DELETE" }); toast("Automation removed"); loadRoutines();
    });
  } catch (_) {}
}
let ROUTINES = [];
let _editingRoutine = null;      // null = creating

// One form for both, because "new" and "edit" differ only in what it opens
// holding and where it saves. Two forms drift, and the one you edit less is
// the one that ends up missing a field.
async function routineForm(existing) {
  _editingRoutine = existing || null;
  const { agents } = await api("/api/agents");
  $("#rmAgent").innerHTML = agents.map((a) =>
    `<option value="${esc(a.id)}"${existing && a.id === existing.agent_id ? " selected" : ""}>${esc(a.name)}</option>`).join("");
  $("#rmName").value = existing ? existing.name : "";
  $("#rmInstruction").value = existing ? existing.instruction : "";
  $("#rmInterval").value = existing ? String(existing.interval_min) : "60";
  $("#rmTrigger").value = existing ? existing.trigger : "new_email";
  $("#rmIntervalWrap").hidden = $("#rmTrigger").value !== "schedule";
  const save = $("#rmCreate"); if (save) save.textContent = existing ? "Save" : "Create";
  const title = $("#rmTitle"); if (title) title.textContent = existing ? "Edit automation" : "New automation";
  $("#routineModal").hidden = false;
}
$("#newRoutineBtn").onclick = () => routineForm(null);
$("#rmTrigger").onchange = () => { $("#rmIntervalWrap").hidden = $("#rmTrigger").value !== "schedule"; };
$("#rmClose").onclick = () => $("#routineModal").hidden = true;
$("#rmCreate").onclick = async () => {
  const name = $("#rmName").value.trim(), instruction = $("#rmInstruction").value.trim();
  if (!name || !instruction) { toast("Name & instruction required"); return; }
  const body = JSON.stringify({ name, agent_id: $("#rmAgent").value, trigger: $("#rmTrigger").value,
    instruction, interval_min: parseInt($("#rmInterval").value) || 60 });
  const editing = _editingRoutine;
  try {
    if (editing) await api(`/api/routines/${editing.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body });
    else await api("/api/routines", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  } catch (e) { toast("Could not save that automation"); return; }
  $("#routineModal").hidden = true;
  _editingRoutine = null;
  toast(editing ? "Automation updated" : "Automation created");
  loadRoutines();
};

// ── create custom agent ─────────────────────────────────────────────────

//: What a new agent starts with.
//:
//: The category row is checked, and that is a bug fix rather than a
//: preference: every preset ships with it, and an agent built in the app did
//: not — so an agent the user made was born unable to see any connector they
//: had added, with no screen that said so. A connector somebody deliberately
//: connected is one they want their agents to use.
//:
//: Asked of the ROW, not of a list of names, so the category is recognised by
//: what the API says it is. The row only exists when there is a connector
//: behind it, so this cannot check a box that grants nothing.
const NEW_AGENT_TOOLS = ["search_brain", "remember", "web_search"];
function newAgentDefault(t) {
  return isCategoryRow(t) || NEW_AGENT_TOOLS.includes((t && t.name) || "");
}

async function openAgentModal() {
  const { tools } = await api("/api/agents/tools");
  // The value is the id the agent stores; the text is what a person reads.
  // They differ for a connector tool, whose id is a qualified name we minted.
  $("#amTools").innerHTML = tools.map((t) =>
    `<label class="am-tool"><input type="checkbox" value="${esc(t.name)}" ${newAgentDefault(t) ? "checked" : ""}/> ${esc(toolLabel(t))}</label>`).join("");
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

//: Shown once, the first time somebody reaches the workspace with onboarding
//: behind them. Nothing is pre-added and there is no lead agent any more, so a
//: new install has NO agents at all — the library is not a nicety here, it is
//: the only way to get one.
const SAW_LIBRARY = "lodestone_saw_library";

/** Open the Agent Library the first time, and never again on its own. */
function libraryOnFirstRun() {
  if (!localStorage.getItem("lodestone_onboarded")) return;
  if (localStorage.getItem(SAW_LIBRARY)) return;
  localStorage.setItem(SAW_LIBRARY, "1");
  // A function declaration in library.js, which loads before this file — but
  // guarded anyway, because a missing screen must not break first entry.
  if (typeof openLibrary === "function") openLibrary();
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
