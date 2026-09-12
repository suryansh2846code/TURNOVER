/**
 * Execute app.js's renderProviderConnectBox against a real /api/models/catalog
 * payload and report what each provider rendered.
 *
 * `node --check` only validates syntax — it cannot catch a temporal-dead-zone
 * ReferenceError, which silently emptied the whole Models drawer. This actually
 * runs the function.
 *
 * Reads the catalog as JSON on stdin, writes one JSON result to stdout.
 */
import fs from "node:fs";

const APP_JS = process.argv[2];
const catalog = JSON.parse(fs.readFileSync(0, "utf8"));

const makeEl = () => {
  const e = {
    innerHTML: "", value: "", hidden: false, disabled: false, title: "",
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, appendChild() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
  };
  return e;
};

globalThis.document = {
  querySelector: () => makeEl(), querySelectorAll: () => [],
  getElementById: () => makeEl(), createElement: () => makeEl(),
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
  "\nglobalThis.__render = renderProviderConnectBox;" +
  "\nglobalThis.__setCatalog = (c) => { MODEL_CATALOG = c; };"
)();

globalThis.__setCatalog(catalog);

const out = {};
for (const p of catalog) {
  const box = makeEl();
  try {
    globalThis.__render(box, p.id);
    const html = box.innerHTML || "";
    out[p.id] = {
      ok: true,
      length: html.length,
      hasAccountCard: html.includes("active-account"),
      hasSigninButton: html.includes("ts-signin-btn"),
      hasApiKeyCard: html.includes("ts-toggle-key-btn"),
      connectedBadge: html.includes("ts-badge using"),
    };
  } catch (e) {
    out[p.id] = { ok: false, error: `${e.constructor.name}: ${e.message}` };
  }
}
process.stdout.write(JSON.stringify(out));
