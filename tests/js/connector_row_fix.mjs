/**
 * Render one connector row for real, and report what it offers the user.
 *
 * The row is where a Full-Disk-Access refusal either becomes actionable or
 * stays a sentence. Two things here are only true at runtime and invisible to
 * `node --check`: that an actionable `reason` beats the catalogue blurb (the
 * status line used to prefer `meta.desc`, so the explanation never appeared at
 * all), and that the fix button is withheld when the native bridge is absent.
 *
 * Reads a scenario as JSON on stdin, writes one JSON result to stdout.
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];   // a path inside lodestone/web/
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));

const registry = new Map();

function makeEl(id = "") {
  const el = {
    id, _html: "", value: "", hidden: false, disabled: false, title: "",
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, appendChild() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
    get innerHTML() { return el._html; },
    set innerHTML(v) { el._html = String(v); },
    get textContent() { return el._text || ""; },
    set textContent(v) { el._text = String(v); },
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  return el;
}

function elFor(sel) {
  const key = String(sel).replace(/^#/, "");
  if (!registry.has(key)) registry.set(key, makeEl(key));
  return registry.get(key);
}

globalThis.MutationObserver = class {
  observe() {} disconnect() {} takeRecords() { return []; }
};
globalThis.document = {
  querySelector: (s) => elFor(s),
  querySelectorAll: () => [],
  getElementById: (s) => elFor(s),
  createElement: () => makeEl(),
  addEventListener() {},
  body: makeEl(),
  documentElement: makeEl(),
};
globalThis.window = {
  location: { pathname: "/", href: "/" },
  addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
// The whole point of the scenario: the desktop app has this bridge and a
// browser tab does not.
if (scenario.bridge) {
  globalThis.window.pywebview = { api: { open_privacy_settings: async () => true } };
}
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.confirm = () => true;
globalThis.setTimeout = (fn) => fn;
globalThis.fetch = async () => ({ ok: false, statusText: "not used",
                                  json: async () => ({}) });

const src = appSource(path.dirname(APP_JS));
new Function(src + "\nglobalThis.__row = _cnRowHtml;")();

const result = { ok: true, error: null };
try {
  const html = globalThis.__row(scenario.connector, 1440);
  result.html = html;
  result.hasFixButton = /data-fda="/.test(html);
  result.hasConnectButton = /data-setup="/.test(html);
  // What the row actually says about itself, from the rendered markup.
  const sub = /<span class="cn-sub">([\s\S]*?)<\/span>/.exec(html);
  result.status = sub ? sub[1] : "";
} catch (e) {
  result.ok = false;
  result.error = `${e && e.name}: ${e && e.message}`;
}
process.stdout.write(JSON.stringify(result));
