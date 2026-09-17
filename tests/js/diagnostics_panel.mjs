/**
 * Render the "What just happened" panel, then press Refresh and Copy.
 *
 * The panel exists so a stuck user can see and send what the app recorded. Three
 * things have to hold and none is visible from the markup: the lines reach the
 * box, `ok: false` says something rather than showing an empty box, and Copy
 * puts the text on the clipboard rather than doing nothing quietly.
 *
 * argv: <a path inside chitragupta/web/>   stdin: a /api/diagnostics/log payload
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const payload = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = (tag = "div") => {
  const node = {
    tag, value: "", hidden: false, disabled: false, className: "", style: {},
    dataset: {}, onclick: null, onkeydown: null, children: [],
    scrollTop: 0, scrollHeight: 4242,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelectorAll: () => [], addEventListener() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, select() {},
    closest: () => null,
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return makeEl(); },
  };
  let html = "", text = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html, set(v) { html = String(v); },
  });
  Object.defineProperty(node, "textContent", {
    get: () => text, set(v) { text = String(v); },
  });
  return node;
};

const registry = new Map();
const el = (sel) => {
  if (!registry.has(sel)) registry.set(sel, makeEl());
  return registry.get(sel);
};
globalThis.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
globalThis.document = {
  querySelector: (s) => el(s), querySelectorAll: () => [],
  getElementById: (id) => el(`#${id}`), createElement: (t) => makeEl(t),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
  execCommand: () => true,
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
const store = {};
globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };

const calls = [];
const copied = [];
// Node 26 defines `navigator` as a getter-only global, so it is redefined rather
// than assigned. `copyToClipboard` reaches for `navigator.clipboard` first.
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: async (t) => { copied.push(t); } } },
  configurable: true, writable: true,
});
globalThis.fetch = async (url, opts = {}) => {
  calls.push({ url, method: opts.method || "GET" });
  if (payload.__http_error) throw new Error("network down");
  return { ok: true, status: 200, json: async () => payload };
};

const toasts = [];
new Function(appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__load = loadDiagnosticsLog;" +
  "\nglobalThis.__el = (s) => document.querySelector(s);" +
  "\ntoast = (m) => globalThis.__toasts.push(String(m));")();
globalThis.__toasts = toasts;

let error = null;
try {
  await globalThis.__load();
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

const box = el("#logBox"), meta = el("#logMeta");
const afterLoad = { text: box.textContent, meta: meta.textContent,
                    scrolled: box.scrollTop };

// The handlers were attached at load time, in the module's own block.
let refreshed = null, copyResult = null;
const refresh = el("#logRefresh");
if (typeof refresh.onclick === "function") {
  const before = calls.length;
  try {
    await refresh.onclick();
    refreshed = calls.length > before ? "refetched" : "did nothing";
  } catch (e) { refreshed = `THREW: ${e.message}`; }
}
const copy = el("#logCopy");
if (typeof copy.onclick === "function") {
  try {
    await copy.onclick();
    copyResult = "ran";
  } catch (e) { copyResult = `THREW: ${e.message}`; }
}

console.log(JSON.stringify({
  error, afterLoad, refreshed, copyResult, copied, toasts,
  urls: calls.map((c) => c.url),
  // Proof there is nothing to type into and nothing to run.
  hasInput: registry.has("#logInput") || registry.has("#logRun"),
}, null, 2));
