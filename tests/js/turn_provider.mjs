/**
 * Send a turn before the model catalog has loaded, and report what provider
 * the request carried.
 *
 * The turn used to read `$("#provider").value` — a hidden <select> that is
 * EMPTY until loadProviders() fills it, and loadProviders fetches the catalog,
 * measured cold at about ten seconds. For those ten seconds the composer
 * showed the provider from localStorage while the request carried nothing; the
 * server fell back to settings.model_provider, which is `mock` on a fresh
 * install, and the offline model answered in a real model's clothes.
 *
 * The window is the whole bug, so the harness reproduces it: localStorage
 * holds a chosen provider, the select is still empty, and a turn is sent.
 *
 * argv: <a path inside chitragupta/web/>   stdin: {saved, selectValue}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { saved, selectValue } = JSON.parse(fs.readFileSync(0, "utf8"));

const bodies = [];
const registry = new Map();
const makeEl = () => ({
  innerHTML: "", value: "", hidden: false, disabled: false, title: "",
  textContent: "", style: {}, dataset: {}, scrollTop: 0, _attrs: {},
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  querySelector: () => makeEl(), querySelectorAll: () => [],
  addEventListener() {}, appendChild() {},
  setAttribute(k, v) { this._attrs[k] = v; },
  getAttribute(k) { return this._attrs[k] ?? null; },
  focus() {}, remove() {}, closest: () => null,
});
const el = (sel) => {
  if (!registry.has(sel)) registry.set(sel, makeEl());
  return registry.get(sel);
};

globalThis.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
globalThis.document = {
  querySelector: (s) => el(s), querySelectorAll: () => [],
  getElementById: (i) => el(`#${i}`), createElement: () => makeEl(),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
                      matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
const store = {};
if (saved) store["chitragupta_provider"] = saved;
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.AbortController = class { constructor() { this.signal = {}; } abort() {} };
globalThis.fetch = async (p, opts = {}) => {
  if (opts.body) bodies.push({ path: String(p), body: JSON.parse(opts.body) });
  // No streaming body, so streamTurn falls through to its plain-turn path.
  return { ok: false, body: null, json: async () => ({ reply: "ok", trace: [] }) };
};

// send() is the real entry point: it is what creates the AbortController
// that streamTurn reads, so calling streamTurn directly would trip over a
// null the app never actually has.
new Function(appSource(path.dirname(APP_JS)) + "\nglobalThis.__send = send; globalThis.__agent = (id) => { current = id; };")();
globalThis.__agent("inbox");

// The state the bug happened in: the catalog has not landed, so the hidden
// select is still whatever index.html shipped.
el("#provider").value = selectValue || "";

try { await globalThis.__send("who is Divyansh"); } catch (_) { /* transport stubbed */ }

const turn = bodies.find((b) => b.path.includes("/chat"));
process.stdout.write(JSON.stringify({
  sentProvider: turn ? (turn.body.provider ?? null) : "NO REQUEST",
  allPaths: bodies.map((b) => b.path),
}));
process.exit(0);
