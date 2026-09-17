/**
 * Execute the onboarding digest render path and report what each card shows.
 *
 * The four "Here's your brain" cards used to carry their sentences in the
 * markup — "What you're building and working on." was ours, written before we
 * had read anything, and it sat on a card a person reads as a finding about
 * themselves. A grep would happily confirm those strings are gone while the
 * cards rendered nothing at all, so this slices the real render block out of
 * `onboarding.html` and runs it against a real response shape.
 *
 * What matters is not that a card rendered. It is that every line on it is
 * either something the brain measured or an honest statement that there is
 * nothing to show.
 *
 * argv: <path to onboarding.html>   stdin: {digest, connectors}
 */
import fs from "node:fs";

const PAGE = process.argv[2];
const { digest, connectors } = JSON.parse(fs.readFileSync(0, "utf8"));

const src = fs.readFileSync(PAGE, "utf8");
const a = src.indexOf("// >>> digest-render >>>");
const b = src.indexOf("// <<< digest-render <<<");
if (a < 0 || b < 0) {
  console.error("digest-render markers missing from onboarding.html");
  process.exit(2);
}
const block = src.slice(a, b);

// ── the smallest DOM the block actually touches ─────────────────────────────
const el = (area) => {
  const kids = {
    ".dc-nm": { textContent: "" },
    ".dc-it": { textContent: "" },
    ".dc-p": { textContent: "" },
    ".dc-k span": { textContent: "" },
  };
  const classes = new Set();
  return {
    area, kids, classes,
    getAttribute: (n) => (n === "data-area" ? area : null),
    querySelector: (sel) => kids[sel] || null,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
  };
};

const cards = ["work", "learning", "comm", "personal"].map(el);
const digestBox = { classes: new Set(), classList: { add(c) { digestBox.classes.add(c); } } };
const headP = { textContent: "" };

const document = {
  querySelector(sel) {
    if (sel === ".digest") return digestBox;
    if (sel === ".dhead p") return headP;
    return null;
  },
  querySelectorAll(sel) {
    return sel === ".digest .dcard" ? cards : [];
  },
};

let error = null;
try {
  // The block is plain script, exactly as the page runs it. `CONNECTORS` and
  // `document` are what it closes over there, so they are what it gets here.
  const run = new Function("document", "CONNECTORS", block + "\nreturn fillCards;");
  run(document, connectors)(digest);
} catch (e) {
  error = String((e && e.stack) || e);
}

process.stdout.write(JSON.stringify({
  error,
  ready: digestBox.classes.has("ready"),
  head: headP.textContent,
  cards: cards.map((c) => ({
    area: c.area,
    empty: c.classes.has("empty"),
    name: c.kids[".dc-nm"].textContent,
    items: c.kids[".dc-it"].textContent,
    body: c.kids[".dc-p"].textContent,
    themes: c.kids[".dc-k span"].textContent,
  })),
}));
