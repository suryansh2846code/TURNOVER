/**
 * Drive the `@` connector picker and report what it did.
 *
 * `@` is how a user answers "may this agent use Gmail?" in advance, for one
 * message. The chips are rendered before sending on purpose — a permission you
 * cannot see at the moment you grant it is not one you granted — so this reads
 * the composer back rather than trusting the array behind it.
 *
 * argv: <a path inside chitragupta/web/>   stdin: {typed, caret, choose, labels}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { typed, choose, labels } = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = () => {
  const node = {
    value: "", hidden: true, disabled: false, className: "", style: {},
    dataset: {}, onclick: null, textContent: "", children: [],
    selectionStart: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    focus() {}, select() {}, remove() {}, closest: () => null,
    scrollIntoView() {}, appendChild(c) { this.children.push(c); return c; },
    querySelectorAll(sel) {
      // Enough of a selector engine for the two the picker uses.
      const want = sel.replace(/[[\]]/g, "").split("=")[0];
      return (node._opts || []).filter((o) => want in o.dataset || o.className.includes("cmp-opt"));
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html,
    set(v) {
      html = String(v);
      // Rebuild the option buttons the picker just wrote, so a click can find
      // them the way the browser would.
      node._opts = [...String(v).matchAll(/data-(pick|drop-connector)="([^"]+)"/g)]
        .map(([, kind, id]) => {
          const b = makeEl();
          b.className = "cmp-opt on";
          b.dataset[kind === "pick" ? "pick" : "dropConnector"] = id;
          return b;
        });
      if (v === "") node.children.length = 0;
    },
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
const store = {};
globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });

new Function(appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__setLabels = (l) => { CONNECTOR_LABELS = l; };" +
  "\nglobalThis.__update = updateConnectorPicker;" +
  "\nglobalThis.__attached = () => attachedConnectors.slice();" +
  "\nglobalThis.__attached2 = () => attachedConnectors.slice();")();

let error = null;
const input = el("#input");
try {
  globalThis.__setLabels(labels);
  input.value = typed;
  input.selectionStart = typed.length;
  globalThis.__update();
  if (choose) {
    const opt = el("#cmpPicker").querySelector("[data-pick]");
    if (opt && opt.onclick) opt.onclick();
  }
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

console.log(JSON.stringify({
  error,
  pickerOpen: el("#cmpPicker").hidden === false,
  offered: [...el("#cmpPicker").innerHTML.matchAll(/data-pick="([^"]+)"/g)].map((m) => m[1]),
  attached: globalThis.__attached(),
  inputAfter: input.value,
  chipsShown: el("#cmpConnectors").hidden === false,
  chipsHtml: el("#cmpConnectors").innerHTML,
}, null, 2));
process.exit(0);
