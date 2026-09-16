/**
 * Build an assistant turn with addMsg and click its Copy button.
 *
 * What gets copied is the point: the MARKDOWN the model wrote, not the text
 * the browser rendered. A source-order check cannot tell those apart — both
 * are a string being handed to a clipboard call — so the button is clicked and
 * the clipboard is recorded.
 *
 * argv: <a path inside chitragupta/web/>   stdin: {text}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const { text } = JSON.parse(fs.readFileSync(0, "utf8"));

let copied = null;
const children = [];
const makeEl = (tag = "div") => {
  const el = {
    tag, innerHTML: "", className: "", value: "", hidden: false, disabled: false,
    title: "", textContent: "", style: {}, dataset: {}, scrollTop: 0, _attrs: {},
    _kids: new Map(), onclick: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector(sel) {
      if (!this._kids.has(sel)) this._kids.set(sel, makeEl());
      return this._kids.get(sel);
    },
    querySelectorAll() { return []; },
    addEventListener() {}, appendChild(c) { children.push(c); },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k] ?? null; },
    focus() {}, remove() {}, closest: () => null, select() {},
  };
  return el;
};
const registry = new Map();
const el = (sel) => {
  if (!registry.has(sel)) registry.set(sel, makeEl());
  return registry.get(sel);
};

globalThis.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
globalThis.document = {
  querySelector: (s) => el(s), querySelectorAll: () => [],
  getElementById: (i) => el(`#${i}`), createElement: (t) => makeEl(t),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
  execCommand: () => true,
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
                      matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
// node ships a read-only `navigator`, so it has to be redefined rather than
// assigned — the app reads navigator.clipboard and there must be one.
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: async (t) => { copied = t; } } },
  configurable: true, writable: true,
});
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
globalThis.setTimeout = () => 0;            // keep the "Copied" state to read

new Function(appSource(path.dirname(APP_JS)) + "\nglobalThis.__add = addMsg;")();

globalThis.__add("assistant", text);
const assistant = children[children.length - 1];
const html = assistant.innerHTML;

const btn = assistant.querySelector(".msg-copy");
let afterClick = "";
if (typeof btn.onclick === "function") {
  await btn.onclick();
  afterClick = btn.innerHTML;
}

globalThis.__add("user", "thanks");
const userHtml = children[children.length - 1].innerHTML || "";

process.stdout.write(JSON.stringify({ html, copied, afterClick, userHtml }));
process.exit(0);
