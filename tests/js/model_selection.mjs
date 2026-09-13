/**
 * Prove that the model the composer *shows* is the model a turn actually uses.
 *
 * These drifted apart in the shipped app: the composer picker saved the agent's
 * binding and updated its own label, while `streamTurn` sent
 * `$("#provider").value` — a hidden select in the Models drawer that nothing had
 * updated. On the server the request wins over the agent binding, so the stale
 * value overrode the fresh choice. The pill said xAI and the turn ran on Claude
 * Code, and the agent reported Claude Code because that is genuinely what it was
 * running on.
 *
 * Neither `node --check` nor reading the source finds that: both halves are
 * correct on their own. Only running the pick and then reading what the request
 * would carry shows it.
 *
 * Reads a scenario as JSON on stdin, writes one JSON result to stdout.
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];   // a path inside lodestone/web/
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));

const store = new Map();
const registry = new Map();
const posts = [];

function makeEl(id = "", tag = "div") {
  const el = {
    id, tagName: tag, _html: "", value: "", hidden: false, disabled: false,
    _found: new Map(),
    title: "", style: {}, dataset: {}, options: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    focus() {}, remove() {}, closest: () => null,
    appendChild(c) { el.options.push(c); },
    querySelector: () => null,
    querySelectorAll(sel) {
      // The real code finds rows by class (`.cmp-flyout-item`) and the harness
      // finds them by data-attribute. Both must return the *same* objects, so
      // a class selector is answered from the same index, keyed on the
      // `data-prov` each row carries.
      const attr = /\[data-([a-zA-Z]+)\]/.exec(sel)
        || (String(sel).startsWith(".") ? [null, "prov"] : null);
      if (!attr) return [];
      const re = new RegExp(`data-${attr[1]}="([^"]*)"`, "g");
      const out = [];
      let m;
      while ((m = re.exec(el._html))) {
        // Stable per (element, selector, value). The real code queries once to
        // attach handlers and the harness queries again to click; handing back
        // a fresh object the second time would lose the handler and quietly
        // test nothing.
        const key = `${attr[1]}=${m[1]}`;
        let b = el._found.get(key);
        if (!b) {
          b = makeEl();
          b.dataset[attr[1]] = m[1];
          el._found.set(key, b);
        }
        out.push(b);
      }
      return out;
    },
    get innerHTML() { return el._html; },
    set innerHTML(v) {
      el._html = String(v);
      el._found.clear();   // a re-render detaches what was there before
      // A <select> assigned options this way must behave like one: the option
      // marked `selected` becomes the value, and otherwise the first wins —
      // which is precisely the fallback that hid the bug.
      if (el.tagName === "select") {
        const opts = [...String(v).matchAll(/value="([^"]*)"([^>]*)>/g)]
          .map(([, value, rest]) => ({ value, selected: rest.includes("selected") }));
        el.options = opts;
        const chosen = opts.find((o) => o.selected) || opts[0];
        el.value = chosen ? chosen.value : "";
      }
    },
    get textContent() { return el._text || ""; },
    set textContent(v) { el._text = String(v); },
  };
  return el;
}

function elFor(sel) {
  const key = String(sel).replace(/^#/, "");
  if (!registry.has(key)) {
    registry.set(key, makeEl(key, key === "provider" ? "select" : "div"));
  }
  return registry.get(key);
}

// app.js installs a focus-management observer at load; every harness that
// evaluates the file needs one to exist, or the whole script throws before the
// function under test is ever reached.
globalThis.MutationObserver = class {
  observe() {}
  disconnect() {}
  takeRecords() { return []; }
};

globalThis.document = {
  querySelector: (s) => elFor(s),
  querySelectorAll: () => [],
  getElementById: (s) => elFor(s),
  createElement: (tag) => makeEl("", tag),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
globalThis.window = {
  location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.confirm = () => true;
globalThis.prompt = () => scenario.customModel ?? null;
globalThis.setTimeout = (fn) => fn;
globalThis.AbortController = class { constructor() { this.signal = {}; } };

globalThis.fetch = async (path, opts) => {
  if (opts && opts.method === "POST") posts.push({ path, body: opts.body });
  return { ok: true, json: async () => ({ ok: true }) };
};

for (const [k, v] of Object.entries(scenario.storage || {})) store.set(k, v);

// The whole workspace, in the order index.html loads it — one file today,
// several once app.js is split. `new Function` compiles a script, so every
// piece has to arrive in one shared scope; see tests/js/_app_source.mjs.
const src = appSource(path.dirname(APP_JS));
new Function(
  src +
  "\nglobalThis.__setActive = setActiveModel;" +
  "\nglobalThis.__renderProv = renderProviderFlyout;" +
  // Both are `const`, so they are mutated rather than reassigned — the real
  // code reads these exact arrays.
  "\nglobalThis.__setProviders = (p) => { COMPOSER_PROVIDERS.length = 0;" +
  "\n  COMPOSER_PROVIDERS.push(...p); };" +
  "\nglobalThis.__setCatalog = (c) => { MODEL_CATALOG = c; };" +
  "\nglobalThis.__setCurrent = (c) => { current = c; };" +
  "\nglobalThis.__pickerProvider = () => activePickerProvider;" +
  // The exact expression the composer uses to build a turn's request body.
  "\nglobalThis.__requestProvider = () => $(\"#provider\").value || undefined;" +
  "\nglobalThis.__requestModel = () => localStorage.getItem(\"lodestone_model\") || undefined;"
)();

const result = { ok: true, error: null, posts };
try {
  if (scenario.mode === "pick") {
    globalThis.__setCurrent("lead");
    globalThis.__setProviders(scenario.providers);
    // `isProviderConnected` reads the catalog, and an unconnected provider is
    // refused before anything is selected — which is correct behaviour and
    // would make this harness silently test nothing.
    globalThis.__setCatalog(scenario.providers.map(
      (x) => ({ id: x.id, label: x.label, connected: x.connected !== false })));
    const row = elFor("cmpProvFlyoutList");
    globalThis.__renderProv();
    const buttons = row.querySelectorAll("[data-prov]");
    const target = buttons.find((b) => b.dataset.prov === scenario.pick);
    if (!target) throw new Error(`no row rendered for ${scenario.pick}`);
    target.dataset.connected = "true";
    await target.onclick({ stopPropagation() {} });
  } else if (scenario.mode === "direct") {
    globalThis.__setActive(scenario.pick, scenario.model ?? null);
  }
  // `JSON.stringify` drops an `undefined` value entirely, and "the key is
  // absent" is the answer these tests are checking for — so it is made explicit.
  result.requestProvider = globalThis.__requestProvider() ?? null;
  result.requestModel = globalThis.__requestModel() ?? null;
  result.savedProvider = store.get("lodestone_provider") ?? null;
  result.savedModel = store.get("lodestone_model") ?? null;
  result.selectValue = elFor("provider").value;
} catch (e) {
  result.ok = false;
  result.error = `${e && e.name}: ${e && e.message}`;
}
process.stdout.write(JSON.stringify(result));
