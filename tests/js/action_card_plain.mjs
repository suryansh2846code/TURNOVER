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
const { action, result, edits } = JSON.parse(fs.readFileSync(0, "utf8"));

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
// What the confirm actually POSTed. The claim an editable card makes is about
// this and nothing else, and it is invisible in the rendered HTML.
//
// Only requests that CARRY a body, and only the first: a successful confirm
// calls `loadReminders()` and `loadRoutines()` straight afterwards, and those
// have no body — so "last call wins" recorded null over the thing under test.
let sent = null;
globalThis.fetch = async (_url, options) => {
  const body = options && options.body;
  if (body && sent === null) {
    try { sent = JSON.parse(body); } catch { sent = "unparseable"; }
  }
  return { ok: true, json: async () => result };
};

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

/** Every element under `node` with this class. The fake DOM has no selectors,
 *  and an editable card holds its inputs as real children — so the test walks
 *  what was actually appended rather than trusting a query that returns []. */
const findAll = (node, className, found = []) => {
  for (const child of node.children || []) {
    if (child.className === className) found.push(child);
    findAll(child, className, found);
  }
  return found;
};

/** Everything a person would actually read on the card.
 *
 *  `innerHTML` only holds what was set as a string — anything built with
 *  `createElement` and appended is invisible to it, which is a blind spot the
 *  moment a card has real inputs in it. This walks what was appended too.
 */
const visibleText = (node) => {
  let out = String(node.innerHTML || "").replace(/<[^>]*>/g, " ");
  out += " " + String(node.textContent || "");
  if (node.value) out += " " + node.value;
  for (const child of node.children || []) out += " " + visibleText(child);
  return out;
};

let error = null, card = null;
try {
  card = globalThis.__card(action);
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

// Let the caller correct the card the way a person would, before confirming.
// This is the whole feature: what executes must be what is on screen NOW.
let fields = [];
if (card && edits) {
  fields = findAll(card, "ac-field");
  for (const [index, value] of Object.entries(edits.set || {})) {
    if (fields[index]) fields[index].value = String(value);
  }
  for (const index of edits.drop || []) {
    const drops = findAll(card, "ac-drop ghost");
    if (drops[index] && drops[index].onclick) drops[index].onclick();
  }
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
  text: card ? visibleText(card).replace(/\s+/g, " ").trim() : "",
  afterConfirm: confirmed,
  // What the confirm actually POSTed. The claim an editable card makes is
  // about this and nothing else.
  sent,
  fieldCount: card ? findAll(card, "ac-field").length : 0,
  escaped,
}, null, 2));
