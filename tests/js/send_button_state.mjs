/**
 * Run setBusy() through a whole turn and report what the send button holds.
 *
 * The button is 34px and round. It used to be given `textContent`, which is
 * two bugs in one property: the word "Stop" does not fit a 34px circle, and
 * writing textContent REPLACES the element's children — so it also deleted the
 * arrow SVG that applyIcons had put there. After the first message the send
 * button was the word "Send" for the rest of the session.
 *
 * Neither shows up in a source-order check: both states assign something, and
 * both look like code that works. So the turn is actually run.
 *
 * argv: <a path inside lodestone/web/>   stdout: one JSON array of snapshots
 */
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];

const registry = new Map();
const makeEl = () => ({
  innerHTML: "", value: "", hidden: false, disabled: false, title: "",
  textContent: "", style: {}, dataset: {}, _attrs: {},
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
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });

new Function(
  appSource(path.dirname(APP_JS)) +
  "\nglobalThis.__busy = setBusy;" +
  "\nglobalThis.__icons = applyIcons;"
)();

globalThis.__icons();                       // what the page starts with
const send = el("#send");
const input = el("#input");
const snap = (state) => ({
  state,
  hasIcon: send.innerHTML.includes("<svg"),
  html: send.innerHTML,
  text: send.textContent,
  aria: send.getAttribute("aria-label"),
  title: send.title,
  inputDisabled: input.disabled,
});

const out = [snap("load")];
globalThis.__busy(true);
out.push(snap("busy"));
globalThis.__busy(false);
out.push(snap("idle"));

process.stdout.write(JSON.stringify(out));
process.exit(0);
