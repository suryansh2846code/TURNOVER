/**
 * Render a connector confirmation card and report what a person would read.
 *
 * Two things went wrong on a real machine and this executes both. The card
 * printed the tool's id and every argument raw — `notion-update-page`, a UUID,
 * `properties {}` — which tells nobody what they are approving. And `esc()`
 * threw on a non-string, so the TypeError replaced the message it was escaping:
 * a successful action rendered as a red crash.
 *
 * argv: <a path inside chitragupta/web/>   stdin: {action, result}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { action, result } = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = (tag = "div") => {
  const node = {
    tag, value: "", hidden: false, disabled: false, className: "", style: {},
    dataset: {}, onclick: null, textContent: "", children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelectorAll: () => [],
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    focus() {}, remove() {}, closest: () => null,
    appendChild(c) { this.children.push(c); return c; },
    querySelector(sel) {
      this._q = this._q || {};
      if (!this._q[sel]) this._q[sel] = makeEl();
      return this._q[sel];
    },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html,
    set(v) { html = String(v); if (v === "") node.children.length = 0; },
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
globalThis.fetch = async () => ({ ok: true, json: async () => result });

new Function(appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__card = actionCard;" +
  "\nglobalThis.__esc = esc;")();

// `esc` is the escaper every innerHTML path in the app goes through, so a
// throw here does not lose one message — it blanks whatever was being drawn.
// Exercised directly, because a caller that stringifies first would hide it.
const escaped = {};
for (const [name, value] of [["object", {}], ["array", []], ["number", 7],
                             ["bool", true], ["null", null],
                             ["nested", { a: { b: 1 } }]]) {
  try {
    escaped[name] = { ok: true, out: globalThis.__esc(value) };
  } catch (e) {
    escaped[name] = { ok: false, out: `${e.constructor.name}: ${e.message}` };
  }
}

let error = null, card = null;
try {
  card = globalThis.__card(action);
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

let confirmed = null;
if (card) {
  try {
    await card.querySelector(".ac-confirm").onclick();
    confirmed = card.querySelector(".ac-result").innerHTML;
  } catch (e) {
    confirmed = `THREW: ${e.constructor.name}: ${e.message}`;
  }
}

console.log(JSON.stringify({
  error,
  html: card ? card.innerHTML : "",
  afterConfirm: confirmed,
  escaped,
}, null, 2));
