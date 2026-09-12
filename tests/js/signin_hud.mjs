/**
 * Drive the floating sign-in card through its states and report what it shows.
 *
 * argv: <signin_hud.html> <scenario>   scenario: waiting | success | timeout
 */
import fs from "node:fs";

const [HTML_PATH, SCENARIO] = process.argv.slice(2);
const html = fs.readFileSync(HTML_PATH, "utf8");

const els = new Map();
const makeEl = (id) => {
  const e = {
    id, _html: "", textContent: "", className: "", onclick: null, title: "",
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this.textContent = String(v).replace(/<[^>]*>/g, ""); },
  };
  els.set(id, e);
  return e;
};
globalThis.document = {
  getElementById: (id) => els.get(id) || makeEl(id),
  addEventListener() {},
};
globalThis.location = { search: "?provider=xai&brand=Grok&auth_url=https%3A%2F%2Fx&limit=180" };
globalThis.URLSearchParams = URLSearchParams;
globalThis.window = { pywebview: { api: { close_hud() {}, focus_main() {} } } };

let statusCalls = 0;
globalThis.fetch = async (path) => {
  const body = () => {
    if (path.includes("/auth/status")) {
      statusCalls++;
      if (SCENARIO === "success") return { status: "success", email: "me@example.com" };
      return { status: "waiting" };
    }
    return {};
  };
  return { ok: true, json: async () => body() };
};

// Timeout scenario: make the clock jump past the limit immediately.
if (SCENARIO === "timeout") {
  const realNow = Date.now;
  let calls = 0;
  Date.now = () => (calls++ === 0 ? realNow() : realNow() + 200_000);
}

const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
new Function(script)();

await new Promise((r) => setTimeout(r, 60));

const read = (id) => (els.get(id)?.textContent || "").trim();
process.stdout.write(JSON.stringify({
  scenario: SCENARIO,
  status: read("status"),
  title: read("title"),
  body: read("body"),
  action: read("action"),
  cardClass: els.get("card")?.className || "",
  polled: statusCalls,
}));
process.exit(0);
