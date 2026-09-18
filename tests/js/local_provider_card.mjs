/**
 * Render one provider's connect box and hand back the markup.
 *
 * Ollama's box used to come back with no account card, no sign-in and no API
 * key field — nothing to press at all — while every one of its models carried
 * the label "Connect in Models", read by somebody already standing in Models.
 * A local server has no credential to collect, so all three cards render empty
 * for it, and nobody had noticed because the box was never rendered in a test.
 *
 * argv: <provider id> <catalog json path>
 * stdout: the box's innerHTML, with SVGs collapsed to [i].
 */
import fs from "node:fs";
import { appSource } from "./_app_source.mjs";
const [PROVIDER, CATALOG] = process.argv.slice(2);
const catalog = JSON.parse(fs.readFileSync(CATALOG, "utf8"));
const mk = () => ({ innerHTML: "", className: "", dataset: {}, style: {}, textContent: "",
  hidden: false, value: "", classList: { add(){}, remove(){}, toggle(){}, contains:()=>false },
  querySelector: () => mk(), querySelectorAll: () => [], addEventListener(){}, appendChild(){},
  setAttribute(){}, getAttribute:()=>null, focus(){}, remove(){}, closest:()=>null });
globalThis.MutationObserver = class { observe(){} disconnect(){} takeRecords(){return[];} };
globalThis.document = { querySelector: mk, querySelectorAll: () => [], getElementById: mk,
  createElement: mk, addEventListener(){}, body: mk(), documentElement: mk() };
globalThis.window = { location:{pathname:"/",href:"/"}, addEventListener(){},
  matchMedia: () => ({matches:false, addEventListener(){}}) };
globalThis.localStorage = { getItem:()=>null, setItem(){}, removeItem(){} };
globalThis.sessionStorage = { getItem:()=>null, setItem(){} };
globalThis.fetch = async () => ({ ok:true, json: async () => ({}) });
globalThis.requestAnimationFrame = () => 0;
globalThis.__cat = catalog;
new Function(appSource("chitragupta/web") + "\nMODEL_CATALOG = globalThis.__cat;" +
  "\nglobalThis.__render = renderProviderConnectBox;").call(globalThis);
const box = mk();
globalThis.__render(box, PROVIDER);
const h = box.innerHTML.replace(/<svg[^>]*>[\s\S]*?<\/svg>/g, "[i]").replace(/\s+/g, " ");
process.stdout.write(h);
