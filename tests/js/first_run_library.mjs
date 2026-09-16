/**
 * Does the Agent Library open on first entry, and only on first entry?
 *
 * Nothing is pre-added any more, so a workspace holding one lead agent and no
 * way to find the rest is a dead end. This executes the real first-run path —
 * naming a lead agent, and skipping one — and reports whether the library
 * opened, and whether it opens again on a second launch.
 *
 * argv: <a path inside lodestone/web/>   stdin: {path: "create" | "skip", seen: bool}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { path: which, seen } = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = () => {
  const node = {
    value: "", hidden: true, disabled: false, className: "", style: {},
    dataset: {}, onclick: null, onkeydown: null, textContent: "", children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => makeEl(), querySelectorAll: () => [],
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    focus() {}, select() {}, remove() {}, closest: () => null,
    scrollIntoView() {}, appendChild(c) { this.children.push(c); return c; },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html, set(v) { html = String(v); if (v === "") node.children.length = 0; },
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
  getElementById: (id) => el(`#${id}`), createElement: () => makeEl(),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
const store = { lodestone_onboarded: "1" };
if (seen) store.lodestone_saw_library = "1";
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
/** Routed by path: a fixture thin enough to throw would abort the very flow
 *  under test, and the abort would look like "the library did not open". */
const FIXTURES = [
  [/\/api\/agents\/lead/, { id: "atlas", name: "Atlas", role: "lead agent" }],
  [/\/api\/brain\/stats/, { total: 0, graph: { entities: 0, relations: 0 } }],
  [/\/api\/brain\/entities/, { entities: [] }],
  [/\/api\/agents\/library/, { categories: [], templates: [] }],
  [/\/api\/agents\/[^/]+\/history/, { history: [] }],
  [/\/api\/agents\/[^/]+\/model/, { provider: null, model: null }],
  [/\/api\/agents/, { agents: [] }],
];
globalThis.fetch = async (p) => {
  const url = String(p);
  const hit = FIXTURES.find(([re]) => re.test(url));
  return { ok: true, json: async () => (hit ? hit[1] : {}) };
};

new Function(appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__createLead = createLead;" +
  "\nglobalThis.__maybeWelcome = maybeWelcome;")();

let error = null;
try {
  if (which === "create") {
    await globalThis.__createLead("Atlas");
  } else {
    await globalThis.__maybeWelcome();
    const skip = el("#wSkip");
    if (skip.onclick) await skip.onclick();
  }
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

console.log(JSON.stringify({
  error,
  libraryOpen: el("#libraryScreen").hidden === false,
  sawFlag: store.lodestone_saw_library || null,
  // `createLead` catches its own failures, so a silent abort looks identical
  // to "the library did not open". These say which happened.
  createButton: el("#wCreate").textContent,
  note: el("#wNote").textContent,
  leadStored: store.lodestone_lead_agent || null,
}, null, 2));
