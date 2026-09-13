/**
 * Execute app.js's parseActions + actionCard against model-written text and
 * report every string the card wrote into the DOM.
 *
 * An action card is built from an `<action …>` tag the *model* emits, and it is
 * assembled with template strings into `innerHTML`. That makes every attribute
 * in that tag attacker-influenced in the only sense that matters here: the model
 * is summarising the user's own email and documents, so a crafted message can
 * decide what an attribute contains.
 *
 * Reads {text} as JSON on stdin, writes {clean, actions, html, writes} to stdout.
 */
import fs from "node:fs";

const APP_JS = process.argv[2];
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const writes = [];

const makeEl = (tag = "div") => {
  const e = {
    tagName: tag, _html: "", value: "", hidden: false, disabled: false,
    className: "", title: "", textContent: "", style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => makeEl(), querySelectorAll: () => [],
    addEventListener() {}, appendChild() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
  };
  Object.defineProperty(e, "innerHTML", {
    get() { return this._html; },
    set(v) { this._html = String(v); writes.push(String(v)); },
  });
  return e;
};

globalThis.document = {
  querySelector: () => makeEl(), querySelectorAll: () => [],
  getElementById: () => makeEl(), createElement: (t) => makeEl(t),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
globalThis.window = {
  location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });

const src = fs.readFileSync(APP_JS, "utf8");
new Function(
  src +
  "\nglobalThis.__parseActions = parseActions;" +
  "\nglobalThis.__actionCard = actionCard;" +
  "\nglobalThis.__md = md;"
)();

const { clean, actions } = globalThis.__parseActions(input.text);
for (const a of actions) globalThis.__actionCard(a);

process.stdout.write(JSON.stringify({
  clean,
  actions,
  writes,
  markdown: input.markdown === undefined ? null : globalThis.__md(input.markdown),
}));
