/**
 * Run addTrace() and report the element it appended.
 *
 * The tool trace used to render open, so a turn that read six files put six
 * blocks of raw JSON arguments between the question and the answer. It is
 * folded now — but "folded" is a property of the element that gets created,
 * and a refactor that rebuilds the markup can quietly reopen it while every
 * other assertion still passes. So this asks what was actually appended.
 *
 * argv: <a path inside lodestone/web/>   stdin: the trace steps
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const steps = JSON.parse(fs.readFileSync(0, "utf8"));

let appended = null;
const makeEl = (tag = "div") => ({
  tag, innerHTML: "", className: "", value: "", hidden: false, disabled: false,
  title: "", textContent: "", style: {}, dataset: {}, scrollTop: 0, _attrs: {},
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  querySelector: () => makeEl(), querySelectorAll: () => [],
  addEventListener() {}, appendChild(c) { appended = c; },
  setAttribute(k, v) { this._attrs[k] = v; },
  getAttribute(k) { return this._attrs[k] ?? null; },
  focus() {}, remove() {}, closest: () => null,
});
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
};
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
                      matchMedia: () => ({ matches: false, addEventListener() {} }), open() {} };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });

new Function(appSource(path.dirname(APP_JS)) + "\nglobalThis.__trace = addTrace;")();

globalThis.__trace(steps);
process.stdout.write(JSON.stringify(appended === null ? { appended: false } : {
  appended: true,
  tag: appended.tag,
  className: appended.className,
  // `open` is what decides whether the user sees this or a one-line summary.
  open: appended._attrs.open !== undefined || /(^|\s)open(\s|=|$)/.test(appended.innerHTML.split(">")[0]),
  html: appended.innerHTML,
}));
process.exit(0);
