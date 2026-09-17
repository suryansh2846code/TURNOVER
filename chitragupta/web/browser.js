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
