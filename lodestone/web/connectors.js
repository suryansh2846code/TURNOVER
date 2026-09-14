/**
 * Adding a source, and setting one up.
 *
 * The per-connector setup help, the custom-app form, the connector catalog
 * browser, and the permission screen shown before an MCP server is added.
 *
 * **Consent to something nobody has been shown is not consent.** A connector's
 * tools are read from the server and displayed *before* it is added
 * (`connectorPermissions`), because "add" is the only moment the user is asked,
 * and a list they never saw is not a decision they made.
 *
 * Setup instructions are per-source prose, not a generic form. Every field a
 * user types lands in the chmod-600 secrets store through
 * `POST /api/connectors/{name}/secret` — never in a file in the repo, and never
 * asked for at a terminal.
 */

// ── what each source looks like, and where it belongs ──────────────────────
// The marks are drawn here rather than fetched: every asset a page pulls from
// a vendor's CDN is a request that says which app the user is running, and the
// whole product promise is that nothing leaves the machine. They are simple
// recognisable shapes in each brand's colour, not pixel copies.
//
// Keyed by connector name from REGISTRY, so a connector without an entry still
// renders — it falls back to a neutral mark and its own group. Adding a
// connector never needs an edit here to keep working.
const CONNECTOR_ICONS = {
  gmail: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path fill="#fff" d="M3 6.5A1.5 1.5 0 0 1 4.5 5h15A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/>
    <path fill="#EA4335" d="M3 6.9 12 13l9-6.1v2.3L12 15.4 3 9.2z"/></svg>`,
  gcal: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="3" y="4.5" width="18" height="16" rx="2.5" fill="#fff"/>
    <rect x="3" y="4.5" width="18" height="4" rx="2.5" fill="#4285F4"/>
    <text x="12" y="17" font-size="8.5" font-weight="700" text-anchor="middle" fill="#4285F4" font-family="Helvetica,Arial">31</text></svg>`,
  gdrive: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path fill="#0F9D58" d="m8.5 3.5 7 0 4.5 8-3.5 0z"/>
    <path fill="#F4B400" d="m20 11.5-3.5 6-7 0 3.5-6z"/>
    <path fill="#4285F4" d="M8.5 3.5 4 11.5l3.5 6 3.5-6z"/></svg>`,
  notion: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="3.5" fill="#fff"/>
    <path fill="#111" d="M8 8.2h1.9l4 5.6V8.2h1.6v7.6h-1.8l-4.1-5.8v5.8H8z"/></svg>`,
  github: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path fill="#e6edf3" d="M12 2.2a9.8 9.8 0 0 0-3.1 19.1c.5.1.7-.2.7-.5v-1.8c-2.7.6-3.3-1.3-3.3-1.3-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.6.3-1.1.6-1.3-2.2-.3-4.5-1.1-4.5-4.9 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.8-2.3 4.6-4.5 4.9.4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A9.8 9.8 0 0 0 12 2.2"/></svg>`,
  linear: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="4.5" fill="#5E6AD2"/>
    <path fill="#fff" d="M7 13.4 10.6 17a5.6 5.6 0 0 1-3.6-3.6m-.3-2.1 5.9 5.9q.8-.1 1.5-.4L7.1 9.8q-.3.7-.4 1.5m.9-2.8 7.6 7.6q.5-.4.9-.9L8.5 7.6q-.5.4-.9.9m2-1.4 7.1 7.1A5.7 5.7 0 0 0 9.6 7.1"/></svg>`,
  imessage: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="2.5" y="2.5" width="19" height="19" rx="5" fill="#34C759"/>
    <path fill="#fff" d="M12 6.4c-3.4 0-6.1 2.2-6.1 5s2.7 5 6.1 5q.8 0 1.5-.2l2.7 1.3-.7-2.3c1.6-.9 2.6-2.3 2.6-3.8 0-2.8-2.7-5-6.1-5"/></svg>`,
  apple_mail: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="2.5" y="4.5" width="19" height="15" rx="4" fill="#1F8DFB"/>
    <path fill="none" stroke="#fff" stroke-width="1.6" stroke-linejoin="round" d="m5.5 8.5 6.5 5 6.5-5"/></svg>`,
  apple_calendar: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="3" y="4.5" width="18" height="16" rx="3.5" fill="#fff"/>
    <rect x="3" y="4.5" width="18" height="4.5" rx="3.5" fill="#FF3B30"/>
    <text x="12" y="17.5" font-size="8.5" font-weight="600" text-anchor="middle" fill="#1c1c1e" font-family="Helvetica,Arial">17</text></svg>`,
  files: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path fill="#54A0FF" d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  notes: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <rect x="4" y="3" width="16" height="18" rx="2.5" fill="#FFD60A"/>
    <path stroke="#8a6d00" stroke-width="1.4" stroke-linecap="round" d="M8 8h8M8 12h8M8 16h5"/></svg>`,
};

//: A neutral mark for anything without one — a custom API app, an MCP server,
//: or a connector added after this file was last touched.
const CONNECTOR_ICON_FALLBACK = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
  <rect x="3" y="3" width="18" height="18" rx="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/>
  <path stroke="currentColor" stroke-width="1.5" stroke-linecap="round" d="M8 12h8M12 8v8"/></svg>`;

//: One line saying what the source actually gives the brain, and which group
//: it sits in. Same fallback rule: no entry is not an error.
const CONNECTOR_META = {
  gmail:          { group: "mail", desc: "Your mail, read-only — threads, senders and what you agreed to." },
  gcal:           { group: "mail", desc: "Meetings, who is in them, and what your week looks like." },
  apple_mail:     { group: "mail", desc: "Mail from the Mail app on this Mac." },
  apple_calendar: { group: "mail", desc: "Events from the Calendar app on this Mac." },
  imessage:       { group: "chat", desc: "Messages on this Mac — who you talk to and about what." },
  notion:         { group: "docs", desc: "Pages and databases from your Notion workspace." },
  gdrive:         { group: "docs", desc: "Documents in your Drive, read-only." },
  files:          { group: "docs", desc: "A folder on this machine, indexed where it sits." },
  notes:          { group: "docs", desc: "Anything you type in yourself — the highest-trust source." },
  github:         { group: "code", desc: "Issues, pull requests and what you are shipping." },
  linear:         { group: "code", desc: "Issues, projects and cycles from your Linear workspace." },
};

//: Group order and headings. `other` catches everything without a group, which
//: is where a custom app or an MCP server lands.
const CONNECTOR_GROUPS = [
  { id: "mail",  title: "Email & calendar", sub: "Mail, scheduling, and the meetings on your week." },
  { id: "chat",  title: "Messaging",        sub: "Where your conversations actually happen." },
  { id: "docs",  title: "Docs & notes",     sub: "Documents, pages, and what you write down." },
  { id: "code",  title: "Code & projects",  sub: "What you are building and what is in flight." },
  { id: "other", title: "Custom sources",   sub: "Apps and servers you connected yourself." },
];

function connectorIcon(name) {
  return CONNECTOR_ICONS[name] || CONNECTOR_ICON_FALLBACK;
}
function connectorMeta(name) {
  return CONNECTOR_META[name] || { group: "other", desc: "" };
}

// ── the connector list ─────────────────────────────────────────────────────
// Grouped, with each source's own mark, because a flat list of eleven names in
// one column is a list you read rather than a page you scan. The rows keep the
// same data-sync / data-setup / data-editapp / data-delapp / data-delmcp hooks
// the old list had, so every existing handler still finds its button.
let _cnRows = [];           // {name, label, group, ready, html} — for filtering
let _cnFilter = "all";

function _cnRowHtml(c, staleAfterMin) {
  const meta = connectorMeta(c.name);
  const ls = c.state?.last_sync ? new Date(c.state.last_sync) : null;
  const ageMin = ls ? (Date.now() - ls.getTime()) / 60000 : null;
  const stale = c.ready && ageMin !== null && ageMin > staleAfterMin;
  const last = ls ? ls.toLocaleDateString() : "";
  const state = !c.ready ? "off" : stale ? "stale" : "ok";
  // What the row says about itself: connected sources report their freshness,
  // unconnected ones say what they would give you if you connected them.
  const status = !c.ready ? (meta.desc || c.reason || "Not connected")
    : !last ? "Connected · not synced yet"
    : stale ? `Connected · last synced ${last}` : `Connected · synced ${last}`;
  const badge = !c.ready ? ""
    : `<span class="cn-badge ${stale ? "is-stale" : ""}">${stale ? "Stale" : "Connected"}</span>`;

  const sync = c.ready ? `<button class="tiny ghost" data-sync="${esc(c.name)}">Sync</button>` : "";
  const setup = c.custom
    ? `<button class="tiny ghost" data-editapp="${esc(c.name)}">Edit</button>`
    : (c.ready ? "" : `<button class="tiny" data-setup="${esc(c.name)}">Connect</button>`);
  const del = c.custom
    ? `<button class="tiny ghost cn-x" data-delapp="${esc(c.name)}" title="Remove" aria-label="Remove ${esc(c.label)}">✕</button>`
    : c.mcp ? `<button class="tiny ghost cn-x" data-delmcp="${esc(c.name)}" title="Remove" aria-label="Remove ${esc(c.label)}">✕</button>` : "";

  return `<div class="cn-row" data-conn="${esc(c.name)}">
    <span class="cn-logo" data-state="${state}">${connectorIcon(c.name)}</span>
    <span class="cn-text">
      <span class="cn-name">${esc(c.label)}${badge}</span>
      <span class="cn-sub">${esc(status)}</span>
    </span>
    <span class="cn-actions">${sync}${setup}${del}</span>
  </div>`;
}

// Bound after every render, not once at load: the list is replaced wholesale
// on each filter keystroke, so a handler attached to the previous nodes is
// attached to nothing the user can click.
function bindConnectorRowActions() {
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
}

function renderConnectors(connectors, staleAfterMin) {
  const box = $("#connectors"); if (!box) return;
  _cnRows = connectors.map((c) => ({
    name: c.name, label: c.label, ready: Boolean(c.ready),
    group: connectorMeta(c.name).group,
    html: _cnRowHtml(c, staleAfterMin),
  }));
  renderConnectorFilters();
  applyConnectorFilter();
}

function renderConnectorFilters() {
  const box = $("#cnFilters"); if (!box) return;
  const total = _cnRows.length;
  const connected = _cnRows.filter((r) => r.ready).length;
  // Only groups that actually have a source are offered. A filter that can
  // only ever return nothing is a control that cannot work.
  const present = CONNECTOR_GROUPS.filter((g) => _cnRows.some((r) => r.group === g.id));
  const chips = [
    { id: "all", label: `All`, n: total },
    { id: "connected", label: `Connected`, n: connected },
    ...present.map((g) => ({ id: g.id, label: g.title, n: _cnRows.filter((r) => r.group === g.id).length })),
  ];
  box.innerHTML = chips.map((c) =>
    `<button type="button" role="tab" class="cn-chip${c.id === _cnFilter ? " is-on" : ""}" data-cnf="${c.id}"
      aria-selected="${c.id === _cnFilter}">${esc(c.label)} <span class="cn-chip-n">${c.n}</span></button>`).join("");
  box.querySelectorAll("[data-cnf]").forEach((b) => b.onclick = () => {
    _cnFilter = b.dataset.cnf;
    renderConnectorFilters();
    applyConnectorFilter();
  });
}

function applyConnectorFilter() {
  const box = $("#connectors"); if (!box) return;
  const q = (($("#cnSearch") || {}).value || "").trim().toLowerCase();
  const match = (r) => {
    if (q && !r.label.toLowerCase().includes(q) && !r.name.toLowerCase().includes(q)) return false;
    if (_cnFilter === "all") return true;
    if (_cnFilter === "connected") return r.ready;
    return r.group === _cnFilter;
  };
  const shown = _cnRows.filter(match);
  const sections = CONNECTOR_GROUPS.map((g) => {
    const rows = shown.filter((r) => r.group === g.id);
    if (!rows.length) return "";
    const conn = rows.filter((r) => r.ready).length;
    return `<section class="cn-group">
      <div class="cn-group-head">
        <div><h2 class="cn-group-title">${esc(g.title)}</h2><p class="cn-group-sub">${esc(g.sub)}</p></div>
        <span class="cn-group-count">${conn} of ${rows.length} connected</span>
      </div>
      <div class="cn-card">${rows.map((r) => r.html).join("")}</div>
    </section>`;
  }).join("");
  box.innerHTML = sections;
  const empty = $("#cnEmpty"); if (empty) empty.hidden = shown.length > 0;
  // The handlers are rebound here rather than delegated, because this markup is
  // replaced wholesale on every filter keystroke — a listener bound to a node
  // that a re-render has already detached is the bug these harnesses exist for.
  bindConnectorRowActions();
}

{
  const inp = $("#cnSearch");
  if (inp) inp.addEventListener("input", () => applyConnectorFilter());
}

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

// ── the connector catalog ────────────────────────────────────────────────
// Everything here is a "connector" to the user. Several are backed by MCP
// servers, which is an implementation detail they never need — the same way
// signing in to Claude never mentions a vendor CLI.

function connectorBrowser() {
  openBrainModal("Add a connector",
    `<p class="t">Connectors run on your Mac and talk to the service directly.
       Nothing is routed through us, and you sign in with the service itself.</p>
     <div id="cxList" class="t" style="margin-top:12px">Loading…</div>`);
  loadConnectorCatalog();
}

async function loadConnectorCatalog() {
  const box = $("#cxList");
  if (!box) return;
  let data;
  try {
    data = await api("/api/connectors/catalog");
  } catch (e) {
    box.textContent = "Could not load the connector list. " + String(e);
    return;
  }

  const card = (c) => `
    <div class="cx-row" data-cx="${esc(c.id)}">
      <span>
        <span class="conn-name">${esc(c.name)}</span>
        <span class="conn-sub">${c.added ? "already added"
          : esc(c.notes || (c.first_party ? "Official connector" : "Community connector"))}</span>
      </span>
      <button class="tiny${c.added ? " ghost" : ""}" data-cxadd="${esc(c.id)}"
        ${c.added ? "disabled" : ""}>${c.added ? "added" : "Add"}</button>
    </div>`;

  // Blocked sources are shown, not hidden. Leaving LinkedIn out of the grid
  // teaches the user this app is missing a feature; the truth is that no app
  // can offer it, and saying so is the only honest version of that control.
  const blocked = (b) => `
    <div class="cx-row cx-off">
      <span>
        <span class="conn-name">${esc(b.name)}</span>
        <span class="conn-sub">${esc(b.reason)}</span>
      </span>
      <span class="tiny ghost" style="opacity:.5;cursor:default">unavailable</span>
    </div>`;

  box.innerHTML =
    `<div class="cx-head">Available</div>${data.available.map(card).join("")}` +
    (data.blocked.length
      ? `<div class="cx-head" style="margin-top:14px">Not possible</div>
         ${data.blocked.map(blocked).join("")}` : "");

  box.querySelectorAll("[data-cxadd]").forEach((b) => {
    if (!b.disabled) b.onclick = () => connectorPermissions(b.dataset.cxadd);
  });
}

// Consent to something nobody has been shown is not consent, so the tools a
// connector exposes are read from the server and displayed before it is added.
async function connectorPermissions(entryId) {
  openBrainModal("Add a connector",
    `<div id="cxPerm" class="t">Checking what this connector can do…</div>`);
  let info;
  try {
    info = await api(`/api/connectors/catalog/${encodeURIComponent(entryId)}/permissions`);
  } catch (e) {
    $("#cxPerm").textContent = "Could not check this connector. " + String(e);
    return;
  }

  if (!info.available) {
    $("#cxPerm").innerHTML =
      `<p class="t">${esc(info.reason || "This connector cannot be added.")}</p>
       <div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end">
         <button id="cxBack" class="tiny ghost">Back</button></div>`;
    $("#cxBack").onclick = connectorBrowser;
    return;
  }

  const list = (items, empty) => items.length
    ? `<ul style="margin:4px 0 0 16px;padding:0">${
        items.map((t) => `<li><code>${esc(t)}</code></li>`).join("")}</ul>`
    : `<div class="t" style="opacity:.7;margin-top:4px">${empty}</div>`;

  const env = (info.needs_env || []).map((f) => `
    <label class="t" style="display:block;margin:8px 0 3px">${esc(f.name)}</label>
    <div class="t" style="opacity:.7;margin-bottom:4px">${esc(f.help)}</div>
    <input id="cxenv_${esc(f.name)}" spellcheck="false" type="password"
      style="width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)" />`
  ).join("");

  $("#cxPerm").innerHTML =
    `<p class="t"><b>${esc(info.name)}</b> would be able to:</p>
     <div style="margin-top:8px"><b class="t">Read</b>${list(info.reads, "nothing")}</div>
     <div style="margin-top:8px"><b class="t">Change</b>${
       list(info.writes, "nothing — this connector is read-only")}</div>
     ${info.writes.length ? `<p class="t" style="margin-top:8px;opacity:.8">
       Anything that changes something always asks you first.</p>` : ""}
     ${info.can_sync ? "" : `<p class="t" style="margin-top:8px">
       This one answers questions but cannot list its records, so it is searched
       on demand rather than synced.</p>`}
     ${env ? `<hr style="border:none;border-top:1px solid var(--line);margin:12px 0">${env}` : ""}
     <div id="cxErr" class="t" style="color:var(--bad);margin-top:8px" hidden></div>
     <div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end">
       <button id="cxBack" class="tiny ghost">Back</button>
       <button id="cxGo" class="tiny">Add connector</button></div>`;

  $("#cxBack").onclick = connectorBrowser;
  $("#cxGo").onclick = async () => {
    const body = { env: {} };
    (info.needs_env || []).forEach((f) => {
      const v = $(`#cxenv_${f.name}`);
      if (v && v.value.trim()) body.env[f.name] = v.value.trim();
    });
    const go = $("#cxGo"), err = $("#cxErr");
    go.disabled = true; go.textContent = "Checking…"; err.hidden = true;
    try {
      const r = await api(`/api/connectors/catalog/${encodeURIComponent(entryId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      if (!r.ok) {
        // Say why here, where they are looking — a failed add that closes the
        // dialog and shows nothing is the shape of "the app is broken".
        err.textContent = r.error; err.hidden = false;
        go.disabled = false; go.textContent = "Add connector";
        return;
      }
      $("#brainModal").hidden = true;
      toast(`${r.label} connected — syncing…`);
      await syncConn(r.name);
      loadBrain();
    } catch (e) {
      err.textContent = String(e); err.hidden = false;
      go.disabled = false; go.textContent = "Add connector";
    }
  };
}

$("#addConnector").onclick = () => connectorBrowser();

// ── waiting for approval ─────────────────────────────────────────────────
// An action an unattended agent wanted to take, held until the user decides.
// The queue, the notification and the endpoints existed before this; what did
// not was anywhere to look, which made a desktop notification the only trace a
// request ever happened. A queue nobody can see is not an approval system.
