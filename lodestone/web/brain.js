/**
 * The brain panel: what is in it, where it came from, and searching it.
 *
 * Memory and entity counts, the connector list and its sync state, the Google
 * connection card, and the entity/search modals.
 *
 * **Google sources are shown as disconnected until a real sign-in.** The app
 * ships an OAuth client, which makes the connector look configured before the
 * user has consented to anything — `/api/google/status` overrides the bundled
 * client's `ready`, and `renderGoogleCard` renders that answer rather than the
 * connector's own.
 *
 * Everything user-supplied here is escaped before it reaches `innerHTML`:
 * memory text, entity names and connector names all come from the user's own
 * sources, which is to say from whoever emailed them.
 */

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
    const del = c.custom
      ? `<button class="tiny ghost" data-delapp="${esc(c.name)}" title="remove">✕</button>`
      : c.mcp ? `<button class="tiny ghost" data-delmcp="${esc(c.name)}" title="remove">✕</button>` : "";
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
  document.querySelectorAll("[data-delmcp]").forEach((b) => b.onclick = async () => {
    const id = b.dataset.delmcp.split(":")[1];
    // Say what removing does and does not do. Silently keeping the memories
    // would be a surprise; silently deleting them would be worse.
    if (!confirm("Remove this connector? (what it already synced stays in your brain.)")) return;
    await api(`/api/connectors/mcp/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("connector removed"); loadBrain();
  });
  loadSyncStatus();
  loadApprovals();
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
      `<div class="gc-row"><span class="gc-ic">✓</span>
         <div class="gc-txt"><b>Google connected</b>
           <span class="gc-sub">${esc(s.account || "signed in")}</span></div>
         <button class="tiny ghost" id="gcDisconnect">Disconnect</button></div>
       <div class="gchips">${chips}</div>
       <div class="gc-note">Token stays on your Mac — not sent to any third party.</div>`;
    $("#gcDisconnect").onclick = disconnectGoogle;
  } else {
    el.className = "google-card";
    el.innerHTML =
      `<div class="gc-txt"><b>Connect Google</b>
         <span class="gc-sub">Gmail · Calendar · Drive — read-only</span></div>
       <button class="gsignin" id="gcConnect"><span class="g-logo">G</span>Sign in with Google</button>
       <div class="gc-note">One click. Token stays on your Mac.</div>`;
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
    await api(`/api/brain/memories/${b.dataset.delmem}`, { method: "DELETE" });
    toast("Deleted"); b.closest(".bm-mem").remove(); loadBrain();
  });
}
$("#brainSearch").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) searchBrain(e.target.value.trim());
});
