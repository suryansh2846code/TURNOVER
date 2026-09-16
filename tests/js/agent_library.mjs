/**
 * Execute the Agent Library render path and report what each card carried.
 *
 * `node --check` passes on the temporal-dead-zone ReferenceError that blanked
 * the model drawer, and a source-order assertion once passed while a card was
 * being written into a detached container. So the cards are actually built, in
 * the real load order, and read back from the container they were appended to.
 *
 * What matters on a card is not that it rendered — it is that it carried the
 * two things a person needs BEFORE they add an agent: what it cannot work
 * without, and what it can do to their machine.
 *
 * argv: <a path inside chitragupta/web/>   stdin: {library}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { library } = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = (tag = "div") => {
  const node = {
    tag, value: "", hidden: false, disabled: false, title: "",
    textContent: "", className: "", style: {}, dataset: {}, onclick: null,
    onchange: null, options: [], children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => makeEl(), querySelectorAll: () => [],
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    focus() {}, remove() {}, closest: () => null,
    appendChild(child) { this.children.push(child); return child; },
  };
  // `innerHTML = ""` is how the app clears a container before re-rendering.
  // A fake that ignored it would hide the bug where a filter appends to what
  // is already there — which is exactly what this harness caught first time.
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
globalThis.window = {
  location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }), open() {},
};
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
globalThis.sessionStorage = { getItem: () => null, setItem() {} };

const calls = [];
globalThis.fetch = async (p, opts = {}) => {
  calls.push({ path: String(p), method: opts.method || "GET", body: opts.body || null });
  if (String(p).includes("/api/agents/library")) {
    return { ok: true, json: async () => library };
  }
  return { ok: true, json: async () => ({}) };
};

new Function(
  appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__openLibrary = openLibrary;" +
  "\nglobalThis.__setCat = (c) => { libCat = c; renderLibrary(); };"
)();

let error = null;
try {
  globalThis.__openLibrary();
  // openLibrary kicks off an async load; let it settle.
  await new Promise((r) => setTimeout(r, 0));
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

/** Everything a card rendered, flattened — the card is read back from the
 *  container it was appended to, never from what we think we built. */
const textOf = (node) => {
  let out = node.textContent || "";
  if (node.innerHTML) out += " " + node.innerHTML;
  for (const child of node.children || []) out += " " + textOf(child);
  return out;
};

const grid = el("#libGrid");
const cards = grid.children.map((c) => ({
  className: c.className,
  text: textOf(c).replace(/\s+/g, " ").trim(),
  buttons: (c.children || []).flatMap((x) =>
    (x.children || []).filter((b) => b.tag === "button").map((b) => b.textContent)),
}));

// Filtering has to actually filter, or the shelves are decoration.
let filtered = null;
if (!error && library.categories.length) {
  globalThis.__setCat(library.categories[0]);
  filtered = el("#libGrid").children.length;
  globalThis.__setCat("All");
}

console.log(JSON.stringify({
  error,
  screenVisible: el("#libraryScreen").hidden === false,
  cardCount: cards.length,
  cards,
  categoryButtons: el("#libCats").children.map((b) => b.textContent),
  filteredCount: filtered,
  emptyHidden: el("#libEmpty").hidden,
  calls: calls.map((c) => c.path),
}, null, 2));
