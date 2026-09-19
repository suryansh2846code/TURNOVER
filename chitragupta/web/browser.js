/**
 * Websites agents may read — the visible half of the browser's consent model.
 *
 * It lives on the Connectors screen because that is where a person looks to
 * answer "what can this app reach on my behalf", and a site an agent can read
 * belongs in that answer just as much as a connected mailbox does.
 *
 * **Adding a site is a person's action, and only a person's.** No agent tool
 * reaches these endpoints. An agent that wants a site it does not have can name
 * it and nothing more, which is the only reason the list means anything.
 *
 * The setup button appears only when there is a browser to set up and a way to
 * drive it — `status.drivable` is false in builds that can store the list but
 * cannot yet open a page, and a button that cannot work reads as the app being
 * broken.
 */

let WEB_POLL = null;

async function loadBrowserSites() {
  const box = $("#webSites");
  if (!box) return;
  let s;
  try {
    s = await api("/api/browser/status");
  } catch {
    return;                       // a failed poll must not blank a live list
  }

  renderBrowserSetup(s);

  box.innerHTML = (s.sites || []).length
    ? s.sites.map((site) => `
        <div class="cn-web-row" data-site="${esc(site.host)}">
          <span class="cn-web-host">${esc(site.host)}</span>
          <span class="cn-web-cap">${site.may_act ? "read &amp; change" : "read only"}</span>
          <button class="tiny ghost" data-webdel="${esc(site.host)}">Remove</button>
        </div>`).join("")
    // Not an error: this is the correct starting state, and saying so beats an
    // empty box that reads as something having failed to load.
    : `<div class="cn-web-empty">No sites yet. Agents cannot open any page
         until you add one.</div>`;

  box.querySelectorAll("[data-webdel]").forEach((b) =>
    b.onclick = async () => {
      const host = b.dataset.webdel;
      b.disabled = true;
      try {
        await api(`/api/browser/sites/${encodeURIComponent(host)}`,
                  { method: "DELETE" });
        toast(`Agents can no longer read ${host}`);
      } catch (e) {
        toast(`Could not remove that — ${String(e)}`);
        b.disabled = false;
        return;
      }
      loadBrowserSites();
    });

  const forget = $("#webForget");
  if (forget) forget.hidden = !(s.sites || []).length && !s.installed;

  // Pick a sign-in back up. The state is the server's, so reloading the page
  // mid-sign-in has to find the flow again — otherwise a refresh strands a
  // browser window that nobody can now finish or cancel. This is the one
  // entry point the section has, so it is where that belongs.
  loadConnectState();
}

/** The one-time download, and what to say while there isn't one. */
function renderBrowserSetup(s) {
  const btn = $("#webSetup"), state = $("#webSetupState");
  if (!btn || !state) return;

  // Nothing to offer in a build that cannot drive a browser. The list still
  // works — it is stored either way — so the section is useful before the
  // download exists, and silent about a button that would do nothing.
  if (!s.drivable) {
    btn.hidden = true;
    state.hidden = false;
    state.textContent = s.installed
      ? "Browsing is set up. This version can remember which sites you allow, but cannot open pages yet."
      : "This version can remember which sites you allow. Opening pages is coming.";
    stopBrowserPoll();
    return;
  }

  if (s.state === "running") {
    btn.hidden = true;
    state.hidden = false;
    state.textContent = `${s.message || "Setting up…"} ${s.percent || 0}%`;
    startBrowserPoll();
    return;
  }

  stopBrowserPoll();
  if (s.state === "error") {
    btn.hidden = false;
    btn.textContent = "Try again";
    state.hidden = false;
    state.textContent = s.message || "Could not set up the browser.";
    return;
  }
  if (s.installed) {
    btn.hidden = true;
    state.hidden = true;
    return;
  }
  btn.hidden = false;
  btn.textContent = "Set up browsing";
  state.hidden = false;
  // Said before it starts, because 150 MB on a slow connection is a surprise
  // worth not having.
  state.textContent = `One-time download, about ${s.approx_mb || 150} MB.`;
}

function startBrowserPoll() {
  if (WEB_POLL) return;
  WEB_POLL = setInterval(loadBrowserSites, 1500);
}
function stopBrowserPoll() {
  if (!WEB_POLL) return;
  clearInterval(WEB_POLL);
  WEB_POLL = null;
}

{
  const add = $("#webAdd"), input = $("#webInput"), err = $("#webErr");
  const show = (message) => {
    if (!err) return;
    err.hidden = !message;
    err.textContent = message || "";
  };

  const allow = async () => {
    const url = (input && input.value || "").trim();
    if (!url) return;
    if (add) add.disabled = true;
    show("");
    try {
      await api("/api/browser/sites", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, note: "" }) });
      if (input) input.value = "";
      toast(`Agents can now read ${url}`);
    } catch (e) {
      // The server's sentence, not a generic one: "only https addresses can be
      // used" tells somebody what to change, and a 400 does not.
      show(String(e).replace(/^Error:\s*/, ""));
    }
    if (add) add.disabled = false;
    loadBrowserSites();
  };

  if (add) add.onclick = allow;
  if (input) input.onkeydown = (e) => { if (e.key === "Enter") allow(); };

  const setup = $("#webSetup");
  if (setup) setup.onclick = async () => {
    setup.disabled = true;
    try { await api("/api/browser/install", { method: "POST" }); }
    catch (e) { toast(`Could not start setup — ${String(e)}`); }
    setup.disabled = false;
    loadBrowserSites();
  };

  const forget = $("#webForget");
  if (forget) forget.onclick = async () => {
    if (!confirm("Forget every website sign-in made inside this app? Agents "
                 + "will need you to sign in again before they can read those "
                 + "sites.")) return;
    try {
      await api("/api/browser/forget-everything", { method: "POST" });
      toast("Every sign-in forgotten");
    } catch (e) { toast(`Could not do that — ${String(e)}`); }
    loadBrowserSites();
  };
}


// ── connecting a site: signing in once, in a window you can watch ──────────
//
// The state lives on the SERVER (`browser/signin.py`), which is what makes this
// survive a refresh: reload mid-sign-in and the panel picks the flow back up
// rather than stranding a browser window nobody can now finish or cancel.
//
// Three states, and the middle one is the one that is easy to get wrong:
//
//   idle              → an address and a Connect button
//   connecting        → "the window is open", Done, and Cancel
//   still_signing_in  → NOT a failure. It is our guess that you are still on
//                       the login page, and pressing Done again overrules it.
//
// That last one matters more than it looks. The check is a heuristic over the
// address the browser landed on; it will be wrong on some site, and a user who
// cannot overrule it is locked out of an account that is already theirs.
let CONNECT_POLL = null;

//: Sites where connecting is worth a word of warning first, per
//: docs/development/connected-sites.md — "say the risk in the UI, once, before
//: the user connects one of the bottom four. Not buried in a doc."
//:
//: Editorial copy, not capability: these are judgements about how each company
//: treats automation, and they belong with the site catalogue in the backend
//: the day one exists. Matched on the registered domain so `www.` and `m.` do
//: not slip past it.
const CONNECT_RISK = {
  "linkedin.com": "LinkedIn watches for automation. Reading your own feed at "
    + "human pace is not scraping, but accounts have been restricted for less — "
    + "connect it only if you accept that risk.",
  "x.com": "X watches for automation and restricts accounts that look automated.",
  "twitter.com": "X watches for automation and restricts accounts that look automated.",
  "whatsapp.com": "This signs in through WhatsApp Web, the same as linking a "
    + "device. Safer than a reimplemented protocol, but not risk-free.",
  "discord.com": "Discord's rules do not allow automating a user account. A real "
    + "browser session is less clearly against them, not clearly within them.",
};

function connectRisk(value) {
  const host = String(value || "").trim().toLowerCase()
    .replace(/^https?:\/\//, "").replace(/\/.*$/, "").replace(/^www\./, "");
  const parts = host.split(".");
  // Check the registered domain, so m.linkedin.com and www.x.com both match.
  for (let i = 0; i < parts.length - 1; i++) {
    const hit = CONNECT_RISK[parts.slice(i).join(".")];
    if (hit) return hit;
  }
  return "";
}

function renderConnectRisk() {
  const box = $("#webConnectRisk"), input = $("#webConnectInput");
  if (!box) return;
  const why = connectRisk(input && input.value);
  box.hidden = !why;
  box.textContent = why;
}

/** Draw whichever of the three states the server says we are in. */
function renderConnect(st) {
  const idle = $("#webConnectIdle"), live = $("#webConnectLive");
  const msg = $("#webConnectMsg"), done = $("#webConnectDone");
  if (!idle || !live) return;

  if (!st || !st.connecting) {
    idle.hidden = false;
    live.hidden = true;
    stopConnectPoll();
    return;
  }

  idle.hidden = true;
  live.hidden = false;
  live.classList.toggle("is-waiting", Boolean(st.still_signing_in));
  // The server's sentence when it has one — it knows whether this is the first
  // ask or the "that still looks like a login page" one, and writing our own
  // here would mean two places deciding what the user is being told.
  if (msg) {
    msg.textContent = st.note || (st.host
      ? `A browser window is open at ${st.host}. Sign in there — it is a separate `
        + `window, not part of this app — then come back and press Done.`
      : "A browser window is open. Sign in there, then press Done.");
  }
  // Second press means "I really am in", and says so rather than looking like
  // the same button failing twice.
  if (done) done.textContent = st.still_signing_in ? "Done anyway" : "Done";
  startConnectPoll();
}

async function loadConnectState() {
  try { renderConnect(await api("/api/browser/connect")); }
  catch (_) { /* a failed poll must not tear down a live sign-in */ }
}

function startConnectPoll() {
  if (CONNECT_POLL) return;
  CONNECT_POLL = setInterval(loadConnectState, 2000);
}
function stopConnectPoll() {
  if (!CONNECT_POLL) return;
  clearInterval(CONNECT_POLL);
  CONNECT_POLL = null;
}

{
  const err = $("#webConnectErr");
  const show = (m) => { if (err) { err.hidden = !m; err.textContent = m || ""; } };

  const input = $("#webConnectInput");
  if (input) input.oninput = renderConnectRisk;

  const go = $("#webConnectGo");
  if (go) go.onclick = async () => {
    const url = (input && input.value || "").trim();
    if (!url) return;
    go.disabled = true; show("");
    try {
      const r = await api("/api/browser/connect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }) });
      // The endpoint answers `{ok: false, error}` rather than raising, so a
      // refusal has to be read out of the body — awaiting it and assuming
      // success is how "already signing in to X" became a silent no-op.
      if (r && r.ok === false) show(r.error || "Could not open that site.");
      else if (input) input.value = "";
    } catch (e) {
      show(String(e).replace(/^Error:\s*/, ""));
    }
    go.disabled = false;
    renderConnectRisk();
    loadConnectState();
  };

  const done = $("#webConnectDone");
  if (done) done.onclick = async () => {
    done.disabled = true; show("");
    // `force` is the second press. The first asks the server to check; the
    // second says the user knows better, which is the whole point of the flag.
    const force = done.textContent.trim() === "Done anyway";
    try {
      const r = await api("/api/browser/connect/finish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }) });
      if (r && r.ok) {
        toast(r.detail || `${r.host || "That site"} is connected`);
        show("");
      } else if (r && r.still_signing_in) {
        show("");                 // the live message says it; a red line as well is shouting
      } else {
        show((r && r.error) || "Could not finish connecting.");
      }
    } catch (e) {
      show(String(e).replace(/^Error:\s*/, ""));
    }
    done.disabled = false;
    await loadConnectState();
    loadBrowserSites();
  };

  const cancel = $("#webConnectCancel");
  if (cancel) cancel.onclick = async () => {
    cancel.disabled = true;
    try {
      const r = await api("/api/browser/connect/cancel", { method: "POST" });
      if (r && r.detail) toast(r.detail);
    } catch (e) { toast(`Could not stop that — ${String(e)}`); }
    cancel.disabled = false;
    show("");
    loadConnectState();
  };
}
