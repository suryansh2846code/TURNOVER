/**
 * Execute the Create-an-agent modal and report what it drew.
 *
 * This screen shipped unreadable: `.am-body input` was in the shared form-field
 * rule, and a tool row's checkbox IS an input inside `.am-body` — so all
 * thirty-odd of them rendered as full-width padded boxes with the label
 * squeezed down to its first letter. A second rule, `.am-body label`, matched
 * the rows too and uppercased them. Both are CSS, and CSS is not what a
 * harness sees — but the DOM the renderer produces is, and every claim worth
 * making about this modal is a property of that DOM: which group a tool landed
 * in, whether its control is a switch or a reason, and what Create reads back.
 *
 * `workspace.js` loads BEFORE `tools.js`, and this modal calls four functions
 * that tools.js declares. That works only because nothing calls it until after
 * every script has run — so the modal is opened here for real, in the real load
 * order, rather than reasoned about.
 *
 * argv: <a path inside chitragupta/web/>
 * stdin: {tools, categories, connectors, toggle?}
 */
import fs from "node:fs";
import path from "node:path";

import { appSource } from "./_app_source.mjs";

const APP_JS = process.argv[2];
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const calls = [];
let posted = null;

const makeEl = (tag = "div") => ({
  tag, innerHTML: "", className: "", value: "", hidden: true, textContent: "",
  style: {}, dataset: {}, _attrs: {}, onclick: null,
  classList: {
    _on: new Set(),
    add(c) { this._on.add(c); }, remove(c) { this._on.delete(c); },
    toggle(c, v) { if (v) this._on.add(c); else this._on.delete(c); },
    contains(c) { return this._on.has(c); },
  },
  querySelectorAll: () => [], querySelector: () => null,
  setAttribute(k, v) { this._attrs[k] = v; },
  getAttribute(k) { return this._attrs[k] ?? null; },
  addEventListener() {}, appendChild() {}, focus() {}, remove() {}, closest: () => null,
});

const els = {};
const el = (sel) => (els[sel] ||= makeEl());

// The switches the renderer writes into #amTools. Parsed back out of the HTML
// so a click runs the handler the renderer actually bound to it.
const box = el("#amTools");
let switches = [];
let switchesFor = null;
const reparse = () => {
  if (switchesFor === box.innerHTML) return switches;
  switchesFor = box.innerHTML;
  switches = [...box.innerHTML.matchAll(/data-tool="([^"]*)"\s+data-on="([^"]*)"/g)]
    .map(([, name, on]) => {
      const b = makeEl("button");
      b.dataset.tool = name;
      b.dataset.on = on;
      return b;
    });
  return switches;
};
box.querySelectorAll = (sel) => (sel === "[data-tool]" ? reparse() : []);

globalThis.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
globalThis.document = {
  querySelector: (sel) => el(sel),
  querySelectorAll: (sel) => {
    if (sel === "#amTools [data-tool]") return reparse();
    if (sel === '#amTools [data-tool][data-on="1"]') return reparse().filter((b) => b.dataset.on === "1");
    if (sel === ".snav" || sel === ".sp" || sel === ".ms-nav-item" || sel === ".modal-bg") return [];
    return [];
  },
  getElementById: (id) => el(`#${id}`),
  createElement: (t) => makeEl(t),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
globalThis.window = {
  location: { pathname: "/", href: "/" }, addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.fetch = async (url, opts = {}) => {
  calls.push(url);
  if (String(url).startsWith("/api/agents/tools")) {
    return { ok: true, json: async () => ({ tools: input.tools, categories: input.categories }) };
  }
  if (String(url) === "/api/agents/custom" && opts.method === "POST") {
    posted = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ id: "new" }) };
  }
  return { ok: true, json: async () => ({}) };
};

let error = null;
const report = { error: null, groups: [], html: "", count: "", posted: null, opened: false };
try {
  globalThis.__connectors = input.connectors || [];
  new Function(
    appSource(path.dirname(APP_JS)) +
    // The rail and the turn are not what this is about, and both would fetch.
    "\nloadAgents = async () => {};" +
    "\nselectAgent = async () => {};" +
    "\nCONNECTORS = globalThis.__connectors;" +
    "\nglobalThis.__open = openAgentModal;" +
    "\nglobalThis.__create = () => document.getElementById('amCreate').onclick();"
  ).call(globalThis);

  await globalThis.__open();
  reparse();

  report.opened = el("#agentModal").hidden === false;
  report.html = box.innerHTML;
  report.count = el("#amToolCount").textContent;

  // Read the groups back out of what was drawn, not out of the input.
  for (const m of report.html.matchAll(
    /<h4 class="am-group-nm">([\s\S]*?)<\/h4>\s*<div class="am-card">([\s\S]*?)<\/section>/g)) {
    report.groups.push({
      name: m[1],
      tools: [...m[2].matchAll(/<span class="am-nm">([\s\S]*?)<\/span>/g)].map((x) => x[1]),
      switches: [...m[2].matchAll(/data-tool="([^"]*)"/g)].map((x) => x[1]),
      blocked: [...m[2].matchAll(/<span class="am-blocked">([\s\S]*?)<\/span>/g)].map((x) => x[1]),
    });
  }

  if (input.toggle) {
    const b = switches.find((x) => x.dataset.tool === input.toggle);
    if (b && typeof b.onclick === "function") { b.onclick(); report.count = el("#amToolCount").textContent; }
  }

  el("#amName").value = "Sales";
  el("#amRole").value = "outreach";
  el("#amPrompt").value = "be helpful";
  await globalThis.__create();
  report.posted = posted;
} catch (e) {
  error = String((e && e.stack) || e);
}
report.error = error;
report.calls = calls;
process.stdout.write(JSON.stringify(report));
