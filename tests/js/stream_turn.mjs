/**
 * Execute app.js's `streamTurn` against a scripted Server-Sent Events body.
 *
 * The interesting part is not the happy path but the framing: SSE frames are
 * separated by a blank line and a network chunk can split one anywhere,
 * including mid-JSON. A reader that assumes one chunk is one frame works in
 * every hand test and drops tokens against a real server.
 *
 * Reads {chunks, ok} as JSON on stdin; writes {previews, notes, result, error}.
 */
import fs from "node:fs";

const APP_JS = process.argv[2];
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const previews = [];
const notes = [];

const makeEl = () => {
  const e = {
    innerHTML: "", textContent: "", className: "", value: "", hidden: false,
    style: {}, dataset: {}, scrollTop: 0, scrollHeight: 100,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => makeEl(), querySelectorAll: () => [],
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
globalThis.TextDecoder = class {
  decode(v) { return typeof v === "string" ? v : Buffer.from(v).toString("utf8"); }
};

const encoder = (s) => s;
let chunkIndex = 0;
globalThis.fetch = async () => {
  if (!input.ok) return { ok: false };
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (chunkIndex >= input.chunks.length) return { done: true };
          return { done: false, value: encoder(input.chunks[chunkIndex++]) };
        },
      }),
    },
  };
};

const src = fs.readFileSync(APP_JS, "utf8");
new Function(
  src +
  "\nglobalThis.__streamTurn = streamTurn;" +
  "\nglobalThis.__setCurrent = (c) => { current = c; };" +
  "\nglobalThis.__setController = (c) => { controller = c; };" +
  "\nglobalThis.__setApi = (f) => { plainTurn = f; };"
)();

globalThis.__setCurrent("research");
globalThis.__setController({ signal: { aborted: false } });

const think = {
  preview: (t) => previews.push(t),
  note: (t) => notes.push(t),
  done: () => {},
};

let result = null, error = null;
try {
  result = await globalThis.__streamTurn("hello", think);
} catch (e) {
  error = String(e);
}
process.stdout.write(JSON.stringify({ previews, notes, result, error }));
