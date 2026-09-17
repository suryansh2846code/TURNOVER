/**
 * Render the sync line for a given `/api/sync/status` payload.
 *
 * The line said "last 12:34" after a sweep in which every connector failed:
 * `last_result` has carried the per-connector errors all along and nothing read
 * them. A timestamp on its own is a claim that it worked.
 *
 * argv: <a path inside chitragupta/web/>   stdin: a /api/sync/status payload
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const status = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = (tag = "div") => {
  const classes = new Set();
  const node = {
    tag, value: "", hidden: false, disabled: false, className: "", style: {},
    dataset: {}, onclick: null, textContent: "", children: [],
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      contains: (c) => classes.has(c),
    },
    _classes: classes,
    querySelectorAll: () => [], addEventListener() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
    appendChild(c) { this.children.push(c); return c; },
    querySelector(sel) {
      this._q = this._q || {};
      if (!this._q[sel]) this._q[sel] = makeEl();
      return this._q[sel];
    },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html, set(v) { html = String(v); },
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
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
const store = {};
globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => status });

new Function(appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__sync = loadSyncStatus;" +
  "\nglobalThis.__failed = failedSources;")();

let error = null;
try {
  await globalThis.__sync();
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

const line = el("#syncStatus");
console.log(JSON.stringify({
  error,
  text: line.textContent,
  trouble: line._classes.has("sync-trouble"),
  failed: globalThis.__failed(status.last_result),
}, null, 2));
