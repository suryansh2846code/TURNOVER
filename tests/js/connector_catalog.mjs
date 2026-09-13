/**
 * Execute the connector catalog's real render paths and report what landed.
 *
 * `node --check` validates syntax and nothing else — a temporal-dead-zone
 * ReferenceError passes it and silently empties a drawer, which is exactly how
 * the Models panel broke once. So this calls `loadConnectorCatalog()` and
 * `connectorPermissions()` for real and reads what they wrote.
 *
 * The DOM stub models the two things that have caught bugs here before:
 * reassigning `innerHTML` clears the subtree (so a card written into a
 * container a re-render already replaced is detectable), and every
 * `textContent` write is recorded, because a handler's own catch can wipe the
 * error it just set before any assertion sees it.
 *
 * Reads a scenario as JSON on stdin, writes one JSON result to stdout.
 */
import fs from "node:fs";

const APP_JS = process.argv[2];
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));

const textWrites = [];
const registry = new Map();

function makeEl(id = "") {
  const children = [];
  const el = {
    id,
    _html: "",
    value: "",
    hidden: false,
    disabled: false,
    title: "",
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {},
    appendChild(c) { children.push(c); },
    setAttribute() {},
    getAttribute: () => null,
    focus() {},
    remove() {},
    closest: () => null,
    get innerHTML() { return el._html; },
    set innerHTML(v) {
      // Detachment is modelled deliberately: anything previously written into
      // this container is gone, which is the bug class this harness exists for.
      el._html = String(v);
      children.length = 0;
    },
    get textContent() { return el._text || ""; },
    set textContent(v) {
      el._text = String(v);
      textWrites.push({ id: el.id, text: String(v) });
    },
    querySelectorAll(sel) {
      // Buttons are discovered by data-attribute in the real code; the stub
      // hands back one element per match found in the HTML just written.
      const attr = /\[data-([a-zA-Z]+)\]/.exec(sel);
      if (!attr) return [];
      const re = new RegExp(`data-${attr[1]}="([^"]*)"`, "g");
      const out = [];
      let m;
      while ((m = re.exec(el._html))) {
        const b = makeEl();
        b.dataset[attr[1]] = m[1];
        b.disabled = el._html.includes(`data-${attr[1]}="${m[1]}"\n        disabled`)
          || new RegExp(`data-${attr[1]}="${m[1]}"[^>]*disabled`).test(el._html);
        out.push(b);
      }
      return out;
    },
    querySelector: () => null,
  };
  return el;
}

function elFor(sel) {
  const key = String(sel).replace(/^#/, "");
  if (!registry.has(key)) registry.set(key, makeEl(key));
  return registry.get(key);
}

globalThis.document = {
  querySelector: (s) => elFor(s),
  querySelectorAll: () => [],
  getElementById: (s) => elFor(s),
  createElement: () => makeEl(),
  addEventListener() {},
  body: makeEl(),
  documentElement: makeEl(),
};
globalThis.window = {
  location: { pathname: "/", href: "/" },
  addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.confirm = () => true;
globalThis.setTimeout = (fn) => fn;

// Faked at `fetch`, not at `api()`. `api` is a `const`, but more importantly
// stubbing it would skip its own error handling — which is part of what these
// paths depend on when a request fails.
const calls = [];
globalThis.fetch = async (path) => {
  calls.push(path);
  for (const [pattern, answer] of Object.entries(scenario.api || {})) {
    if (String(path).startsWith(pattern)) {
      if (answer && answer.__throw) throw new Error(answer.__throw);
      return { ok: true, json: async () => answer };
    }
  }
  return { ok: false, statusText: "Not Found",
           json: async () => ({ detail: `no canned answer for ${path}` }) };
};

const src = fs.readFileSync(APP_JS, "utf8");
new Function(
  src +
  "\nglobalThis.__browser = connectorBrowser;" +
  "\nglobalThis.__loadCatalog = loadConnectorCatalog;" +
  "\nglobalThis.__permissions = connectorPermissions;" +
  "\nglobalThis.__approvals = loadApprovals;"
)();

const result = { ok: true, calls, modals: [], textWrites, error: null };
try {
  if (scenario.mode === "catalog") {
    globalThis.__browser();
    await globalThis.__loadCatalog();
    const box = elFor("cxList");
    result.catalogHtml = box.innerHTML;
    result.addButtons = box.querySelectorAll("[data-cxadd]").map((b) => ({
      id: b.dataset.cxadd, disabled: !!b.disabled,
    }));
  } else if (scenario.mode === "permissions") {
    await globalThis.__permissions(scenario.entry);
    result.permHtml = elFor("cxPerm").innerHTML;
  } else if (scenario.mode === "approvals") {
    await globalThis.__approvals();
    const box = elFor("approvals");
    result.approvalsHtml = box.innerHTML;
    result.approvalsHidden = box.hidden;
    result.approveButtons = box.querySelectorAll("[data-aprok]").map(
      (b) => b.dataset.aprok);
  }
} catch (e) {
  result.ok = false;
  result.error = `${e && e.name}: ${e && e.message}`;
}
// The real `openBrainModal` writes the title into #bmTitle, so the recorded
// textContent writes are what prove it opened.
result.modals = textWrites.filter((w) => w.id === "bmTitle").map((w) => w.text);
process.stdout.write(JSON.stringify(result));
