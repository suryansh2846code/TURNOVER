/**
 * Execute the "Sign in" click handler for one provider and report what the
 * sign-in container ended up containing.
 *
 * Asserting on source order does not catch DOM-lifetime bugs: the CLI card was
 * being built into a container that a preceding re-render had already detached,
 * so the button appeared to do nothing. This clicks it for real.
 *
 * argv: <app.js> <providerId>   stdin: {catalog, authStartResponse}
 */
import fs from "node:fs";

const [APP_JS, PROVIDER_ID] = process.argv.slice(2);
const { catalog, authStartResponse } = JSON.parse(fs.readFileSync(0, "utf8"));

// Elements remember their children by selector, so querySelector returns the
// same object twice — which is what makes onclick reachable.
// Error text set during the click is wiped by the re-render that follows it,
// so reading the DOM afterwards shows nothing. Record every write instead.
const textWrites = [];

const makeEl = (tag = "div") => {
  const el = {
    tag, value: "", hidden: false, disabled: false, title: "",
    style: {}, dataset: {}, onclick: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    _kids: new Map(),
    _html: "",
    // Reassigning innerHTML replaces the subtree, so previously-returned
    // children are detached. Modelling that is the point: writing into a
    // container that a later re-render replaced is invisible to the user.
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this._kids.clear(); },
    _text: "",
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); textWrites.push(this._text); },
    querySelector(sel) {
      if (!this._kids.has(sel)) this._kids.set(sel, makeEl());
      return this._kids.get(sel);
    },
    querySelectorAll(sel) { return [this.querySelector(sel)]; },
    addEventListener() {}, appendChild() {}, setAttribute() {},
    getAttribute: () => null, focus() {}, remove() {}, closest: () => null,
  };
  return el;
};

globalThis.document = {
  querySelector: () => makeEl(), querySelectorAll: () => [],
  getElementById: () => makeEl(), createElement: () => makeEl(),
  addEventListener() {}, body: makeEl(), documentElement: makeEl(),
};
// The desktop app exposes a native-window bridge here. Recording the calls is
// how we prove the floating sign-in card was actually raised.
const hudCalls = [];
globalThis.window = { location: { pathname: "/", href: "/" }, addEventListener() {},
                      matchMedia: () => ({ matches: false, addEventListener() {} }), open() {},
                      pywebview: { api: {
                        async open_signin_hud(...a) { hudCalls.push(["open", ...a]); return true; },
                        async close_signin_hud() { hudCalls.push(["close"]); },
                      } } };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} };
const calls = [];
globalThis.fetch = async (path) => {
  calls.push(String(path));
  const body = String(path).includes("/auth/start") ? authStartResponse : {};
  return { ok: true, json: async () => body };
};
const src = fs.readFileSync(APP_JS, "utf8");
new Function(
  src +
  "\nglobalThis.__render = renderProviderConnectBox;" +
  "\nglobalThis.__setCatalog = (c) => { MODEL_CATALOG = c; };"
)();

globalThis.__setCatalog(catalog);

const box = makeEl();
globalThis.__render(box, PROVIDER_ID);
const btn = box.querySelector(".ts-signin-btn");

let error = null;
try {
  if (typeof btn.onclick === "function") await btn.onclick();
  else error = "sign-in button has no click handler";
} catch (e) {
  error = `${e.constructor.name}: ${e.message}`;
}

process.stdout.write(JSON.stringify({
  error,
  clicked: typeof btn.onclick === "function",
  // Re-query after the click: whatever is attached to the box NOW is what the
  // user actually sees.
  containerHtml: box.querySelector(".ts-signin-container").innerHTML || "",
  feedback: box.querySelector(".pc-feedback").textContent || "",
  calls,
  hudCalls,
  textWrites,
}));

// The browser branch starts a polling HUD whose timers would keep node alive.
process.exit(0);
