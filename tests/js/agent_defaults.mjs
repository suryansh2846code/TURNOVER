/**
 * Execute loadAgentDefaults() and report what the three controls became.
 *
 * Effort is the one that matters: /api/agents/effort has existed on the server
 * the whole time and nothing in the frontend ever called it, so the setting
 * every turn reads could not be changed from the app. A select that renders
 * but never POSTs looks identical on screen, so the calls are recorded.
 *
 * argv: <app.js>   stdin: {catalog, effort}
 */
import fs from "node:fs";

const [APP_JS] = process.argv.slice(2);
const { catalog, effort } = JSON.parse(fs.readFileSync(0, "utf8"));

const registry = new Map();
const makeEl = () => ({
  value: "", hidden: false, disabled: false, title: "", innerHTML: "", textContent: "",
  style: {}, dataset: {}, onclick: null, onchange: null, options: [],
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  querySelector: () => makeEl(), querySelectorAll: () => [],
  addEventListener() {}, appendChild() {}, setAttribute() {},
  getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
});
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
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
globalThis.sessionStorage = { getItem: () => null, setItem() {} };

const calls = [];
globalThis.fetch = async (path, opts = {}) => {
  calls.push({ path: String(path), method: opts.method || "GET", body: opts.body || null });
  if (String(path).includes("/api/agents/effort")) {
    return { ok: true, json: async () => effort };
  }
  return { ok: true, json: async () => ({}) };
};

new Function(
  fs.readFileSync(APP_JS, "utf8") +
  "\nglobalThis.__setCatalog = (c) => { MODEL_CATALOG = c; };" +
  "\nglobalThis.__loadDefaults = loadAgentDefaults;"
)();

globalThis.__setCatalog(catalog);
let error = null;
try {
  await globalThis.__loadDefaults();
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

const prov = el("#defProvider"), model = el("#defModel"), eff = el("#defEffort");

// Snapshot BEFORE mutating anything — the provider change below re-renders the
// model list, so reading it at the end would report the wrong provider's models.
const initial = {
  providerOptions: prov.innerHTML,
  modelOptions: model.innerHTML,
  effortOptions: eff.innerHTML,
};
const before = calls.length;

// Change the effort and confirm it reaches the server.
let effortPost = null;
if (typeof eff.onchange === "function") {
  eff.value = "high";
  try { await eff.onchange(); } catch (e) { error = error || `onchange: ${e.message}`; }
  effortPost = calls.slice(before).find((c) => c.method === "POST") || null;
}

// Change the provider and confirm the stored choice moves with it.
let providerWrote = null;
if (typeof prov.onchange === "function") {
  prov.value = "claude";
  try { prov.onchange(); } catch (e) { error = error || `prov onchange: ${e.message}`; }
  providerWrote = store["lodestone_provider"] || null;
}
// Snapshot here: the model change below writes lodestone_model, so reading it
// at the end would not show what the provider switch alone did.
const storedModelAfterProviderChange = store["lodestone_model"] ?? null;

// Choosing a model AFTER switching provider must store the NEW provider.
let pairAfterSwitch = null;
if (typeof model.onchange === "function") {
  model.value = "claude-opus-5";
  try { model.onchange(); } catch (e) { error = error || `model onchange: ${e.message}`; }
  pairAfterSwitch = { provider: store["lodestone_provider"] || null,
                      model: store["lodestone_model"] || null };
}

process.stdout.write(JSON.stringify({
  pairAfterSwitch,
  error,
  ...initial,
  modelOptionsAfterProviderChange: model.innerHTML,
  effortDesc: el("#defEffortDesc").textContent,
  effortDisabled: eff.disabled,
  effortPost,
  providerWrote,
  storedModelAfterProviderChange,
  calls,
}));
process.exit(0);
