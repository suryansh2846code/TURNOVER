/**
 * The workspace's JavaScript, in the order the browser loads it.
 *
 * Every harness here evaluates the app with `new Function(src)`, which compiles
 * a *script* — it cannot process `import` or `export`. That is not a limitation
 * to work around: the app is a classic script by design, and several harnesses
 * have to reach into its scope to install a fixture (`MODEL_CATALOG = …`),
 * which only same-scope code can do.
 *
 * So when `app.js` is split, it splits into more classic `<script src>` tags
 * sharing one global scope in document order — semantically identical to one
 * file. This module is what lets a harness keep loading "the app" rather than
 * "app.js": it reads the order out of `index.html` and concatenates.
 *
 * **The order comes from the page, never from a list here.** That is the whole
 * point. A hardcoded list is a second source of truth that drifts, and the
 * drift is silent — the browser would load one order and the tests another,
 * which is exactly the class of bug these harnesses exist to catch. It also
 * means a future module needs no change to any harness: add the tag, and every
 * harness picks it up. And if a file is added to disk but never wired into the
 * page, the harness loads what the browser loads — nothing — which is a bug the
 * old one-path setup could not express.
 *
 * See docs/development/frontend-testing.md.
 */
import fs from "node:fs";
import path from "node:path";

/** `<script src="/static/app.js">` — local sources only, in document order. */
const SCRIPT_TAG = /<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;

/**
 * Paths of the scripts `index.html` loads, resolved against the web directory.
 *
 * Anything absolute (`//cdn…`, `https://…`) is skipped — it is not ours to
 * evaluate, and there should never be one here anyway.
 */
export function appScripts(webDir) {
  const html = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
  const out = [];
  for (const [, src] of html.matchAll(SCRIPT_TAG)) {
    if (/^(?:[a-z]+:)?\/\//i.test(src)) continue;
    // `/static/app.js` is served from the web directory itself.
    out.push(path.join(webDir, src.replace(/^\/static\//, "").replace(/^\//, "")));
  }
  return out;
}

/**
 * Those scripts concatenated, which is what the browser ends up with.
 *
 * Joined with a newline so a file that does not end in one cannot glue its last
 * line to the next file's first. While the app is a single file this returns
 * that file's contents unchanged, byte for byte.
 */
export function appSource(webDir) {
  return appScripts(webDir).map((p) => fs.readFileSync(p, "utf8")).join("\n");
}

/**
 * The web directory, found from a harness's own location.
 *
 * Harnesses are given a path on argv today; this is here so that when they stop
 * being, they do not each re-derive it.
 */
export function webDir(importMetaUrl) {
  return path.resolve(new URL(".", importMetaUrl).pathname, "../../chitragupta/web");
}
