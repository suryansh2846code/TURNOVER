/**
 * Pull a lapsed session out of a turn's tool results and build its card.
 *
 * `browser/session.py` writes one sentence when a granted site lands on its own
 * login page, and the card is matched off that sentence — so this exists to
 * prove the match still holds, and that a result which is not that sentence
 * produces nothing rather than a card about a site nobody mentioned.
 *
 * It must land OUTSIDE the trace fold: the trace is collapsed by default and a
 * logged-out account is not trace detail.
 *
 * argv: <path to chat.js>   stdin: {steps: [...]}
 */
import fs from "node:fs";
const SRC = fs.readFileSync(process.argv[2], "utf8");
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const slice = (name) => {
  const i = SRC.indexOf(`function ${name}(`);
  let d = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}" && --d === 0) return SRC.slice(i, j + 1);
  }
};
const mk = () => ({ className: "", innerHTML: "", _q: {},
  querySelector(s) { return (this._q[s] ||= { onclick: null, value: "", focus(){}, scrollIntoView(){} }); } });
const ctx = { esc: (t) => String(t), IC: { lock: "[lock]" },
  document: { createElement: mk }, $: () => null,
  openConnectorsScreen: () => {} };
const run = new Function(...Object.keys(ctx),
  slice("lapsedSites") + slice("reconnectCard") +
  "\nreturn { lapsedSites, reconnectCard };");
const api = run(...Object.values(ctx));

const hosts = api.lapsedSites(input.steps);
const card = hosts.length ? api.reconnectCard(hosts[0]) : null;
process.stdout.write(JSON.stringify({
  hosts,
  html: card ? card.innerHTML.replace(/\s+/g, " ") : "",
  wired: card ? typeof card._q[".signout-go"].onclick === "function" : false,
}));
