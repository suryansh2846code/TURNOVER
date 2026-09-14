/**
 * Execute app.js's `renderToolList` against a realistic /api/agents/tools
 * payload and report what actually landed on screen.
 *
 * `node --check` passes on a temporal-dead-zone ReferenceError — one of those
 * silently blanked the whole Models drawer — and a source-order assertion
 * cannot tell a rendered button from a dead one. So this runs the real
 * function, then clicks what it drew.
 *
 * Reads `{tools, connectors}` as JSON on stdin, writes one JSON report to
 * stdout. No assertions live here; the driver owns those, so a failure names
 * the behaviour rather than a line of stub.
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];   // a path inside lodestone/web/
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));

const clickable = [];

const makeEl = () => ({
  innerHTML: "", value: "", hidden: false, disabled: false, title: "",
  textContent: "", style: {}, dataset: {},
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {}, appendChild() {}, setAttribute() {},
  getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
});

// The box under test is the one place the stub has to be honest: the render
// path looks its own markup back up to wire the handler, so `querySelectorAll`
// must return one node per button actually written — otherwise a button that
// was drawn but never wired reads as wired.
const makeBox = () => {
  const box = makeEl();
  box._html = "";
  Object.defineProperty(box, "innerHTML", {
    get() { return box._html; },
    set(v) { box._html = String(v); },
  });
  box.querySelectorAll = (sel) => {
    if (sel !== "[data-tool-fix]") return [];
    const n = (box._html.match(/data-tool-fix/g) || []).length;
    return Array.from({ length: n }, () => {
      const b = { onclick: null };
      clickable.push(b);
      return b;
    });
  };
  return box;
};

// app.js installs a focus-management MutationObserver at load; without one the
// whole file throws before the function under test is ever reached.
globalThis.MutationObserver = class {
  observe() {} disconnect() {} takeRecords() { return []; }
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

// The whole workspace, in the order index.html loads it — one file today,
// several once app.js is split. `new Function` compiles a script, so every
// piece has to arrive in one shared scope; see tests/js/_app_source.mjs.
const src = appSource(path.dirname(APP_JS));
new Function(
  src +
  "\nglobalThis.__renderTools = renderToolList;" +
  // openDrawer is a function declaration, so it can be replaced in place —
  // which both records the click and keeps its real side effects (a panel
  // swap, a /api/connectors fetch) out of a test that is not about them.
  "\nglobalThis.__drawers = [];" +
  "\nopenDrawer = (name) => { globalThis.__drawers.push(name); };"
)();

// ── run it ────────────────────────────────────────────────────────────────
const box = makeBox();
const report = { ok: true, html: "", groups: [], wired: 0, drawers: [] };
try {
  globalThis.__renderTools(box, scenario.tools, scenario.connectors);
} catch (e) {
  report.ok = false;
  report.error = `${e.constructor.name}: ${e.message}`;
  process.stdout.write(JSON.stringify(report));
  process.exit(0);
}
report.html = box.innerHTML;

// ── read back what was drawn ──────────────────────────────────────────────
const all = (body, re) => [...body.matchAll(re)].map((m) => m[1]);
const one = (body, re) => (body.match(re) || [null, null])[1];

const parts = report.html.split(/<div class="tool-group( down)?">/).slice(1);
for (let i = 0; i < parts.length; i += 2) {
  const down = parts[i] === " down";
  const body = parts[i + 1] || "";
  report.groups.push({
    name: one(body, /<span class="tool-group-nm">([\s\S]*?)<\/span>/),
    count: one(body, /<span class="tool-group-ct">([\s\S]*?)<\/span>/),
    why: one(body, /<p class="tool-why">([\s\S]*?)<\/p>/),
    down,
    hasOffDot: body.includes('class="dot off"'),
    hasFixButton: body.includes("data-tool-fix"),
    // Keyboard access is not a style: a <button> is operable by Enter and
    // Space because it is a button. A div with an onclick is not.
    fixIsButton: /<button type="button"[^>]*data-tool-fix/.test(body),
    tools: all(body, /<div class="tool-nm">([\s\S]*?)<\/div>/g),
    descriptions: all(body, /<div class="tool-ds">([\s\S]*?)<\/div>/g),
  });
}
report.empty = report.html.includes("tasks-empty") ? report.html : null;

// Every button that was drawn must do something when it is pressed.
report.wired = clickable.filter((b) => typeof b.onclick === "function").length;
report.drawn = clickable.length;
for (const b of clickable) if (typeof b.onclick === "function") b.onclick();
report.drawers = globalThis.__drawers;

process.stdout.write(JSON.stringify(report));
