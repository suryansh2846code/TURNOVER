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
