/**
 * Execute the plan-limit card and report what it showed, at four instants.
 *
 * A countdown is behaviour, not markup: that it says "2h 30m" now, "30s" near
 * the end, and arms its retry the moment the wait is over cannot be read off
 * the source. So the card is built for real and the clock is a number this file
 * controls — three hours of waiting costs the suite nothing.
 *
 * The functions are sliced out of chat.js rather than loading the whole app,
 * because this is the one path that must work when everything else has failed.
 *
 * argv: none.   stdout: one JSON report.
 */
import fs from "node:fs";
const src = fs.readFileSync(process.argv[2] || "chitragupta/web/chat.js", "utf8");
const slice = (name) => {
  const i = src.indexOf(`function ${name}(`);
  let d = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}" && --d === 0) return src.slice(i, j + 1);
  }
};
const els = [];
const makeEl = () => {
  const e = { className: "", innerHTML: "", textContent: "", dataset: {}, disabled: false,
    _kids: {}, onclick: null,
    querySelector(sel) { return (this._kids[sel] ||= makeEl()); },
    appendChild() {}, };
  els.push(e); return e;
};
let now = Date.parse("2026-09-18T22:00:00Z");
const timers = [];
const ctx = {
  Date: { now: () => now, parse: Date.parse },
  IC: { clock: "<svg/>" },
  esc: (t) => String(t),
  document: { createElement: makeEl, querySelectorAll: () => [] },
  setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearInterval: () => {},
  send: (t) => { ctx.__sent = t; },
};
const fn = new Function(...Object.keys(ctx),
  slice("parseLimit") + slice("untilLabel") + slice("limitCard") +
  "\nreturn { parseLimit, untilLabel, limitCard };");
const api = fn(...Object.values(ctx));

const raw = '<limit until="2026-09-19T00:30:00Z">5-hour session limit · resets 12am (Asia/Calcutta)</limit>';
const lim = api.parseLimit(raw);
const card = api.limitCard(lim);
const out = { parsed: lim && lim.message, hasMarkerLeft: /<limit/.test(card.innerHTML) };
out.countdown = card._kids[".limit-countdown"].textContent;
out.retryDisabled = card._kids[".limit-retry"].disabled;
out.tickMs = timers[0] && timers[0].ms;

now = Date.parse("2026-09-19T00:29:30Z");            // 30 seconds left
timers[0].fn();
out.nearEnd = card._kids[".limit-countdown"].textContent;

now = Date.parse("2026-09-19T00:31:00Z");            // past the reset
timers[0].fn();
out.afterReset = card._kids[".limit-countdown"].textContent;
out.retryArmed = card._kids[".limit-retry"].disabled === false;

out.plain = api.parseLimit("Here is your answer.") === null;
out.labels = ["2h 30m", "5m 0s", "42s"].map((_, i) =>
  api.untilLabel([9000000, 300000, 42000][i]));
process.stdout.write(JSON.stringify(out, null, 1));
