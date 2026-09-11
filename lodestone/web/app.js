const $ = (s) => document.querySelector(s);
const api = (p, o) => fetch(p, o).then((r) => r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText)));
let current = null;
let agents = [];
let CONNECTORS = [];

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }
function esc(s) { return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

// gradient orb avatar per agent (stable colour from the id; the lead is always blue)
const ORB_COLORS = [["#8fb0ff", "#2f3a5e"], ["#7fd8b0", "#1f4636"], ["#c3a0f5", "#382a54"],
  ["#e0b489", "#48331f"], ["#e79aa0", "#48232e"], ["#9ad0e0", "#1e444f"], ["#b8c0cf", "#2b3140"]];
function orbPair(id) {
  if (id === "__lead") return ORB_COLORS[0];
  let h = 0; for (const ch of String(id || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return ORB_COLORS[h % ORB_COLORS.length];
}
function orbStyle(id) { const [a, b] = orbPair(id); return `background:radial-gradient(circle at 32% 26%, ${a}, ${b} 74%)`; }

// ── minimal line icons (no emoji) ───────────────────────────────────────────
const _S = (p, s = 16) => `<svg viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC = {
  brain: _S('<path d="M8 1.6l6.4 6.4L8 14.4 1.6 8z"/>'),
  connectors: _S('<rect x="2.5" y="3" width="11" height="2.6" rx="1"/><rect x="2.5" y="6.7" width="11" height="2.6" rx="1"/><rect x="2.5" y="10.4" width="8" height="2.4" rx="1"/>'),
  tasks: _S('<rect x="2.5" y="2.5" width="11" height="11" rx="2.5"/><path d="M5.4 8l1.7 1.7L11 5.9"/>'),
  tools: _S('<path d="M2 5h6M11 5h3M2 11h3M8 11h6"/><circle cx="9.3" cy="5" r="1.5"/><circle cx="6" cy="11" r="1.5"/>'),
  model: _S('<circle cx="8" cy="8" r="5.6"/><path d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" fill="currentColor" stroke="none"/>'),
  help: _S('<circle cx="8" cy="8" r="6"/><path d="M6.2 6.2a1.9 1.9 0 0 1 3.6.7c0 1.3-1.8 1.5-1.8 2.7"/><circle cx="8" cy="11.4" r=".55" fill="currentColor" stroke="none"/>'),
  message: _S('<path d="M2.5 4.5h11v6.5H7l-3 2v-2H2.5z"/>'),
  search: _S('<circle cx="7" cy="7" r="4.2"/><path d="M10.2 10.2L14 14"/>'),
  spark: _S('<path d="M8 1.6l1.5 4.9L14 8l-4.5 1.5L8 14.4 6.5 9.5 2 8l4.5-1.5z"/>'),
  plus: _S('<path d="M8 3.5v9M3.5 8h9"/>', 18),
  mic: _S('<rect x="6" y="2" width="4" height="7.5" rx="2"/><path d="M4 8a4 4 0 0 0 8 0M8 11.5V14"/>', 17),
  arrowUp: _S('<path d="M8 12.5V4M4.5 7.5L8 4l3.5 3.5"/>', 17),
  lock: _S('<rect x="3.5" y="7" width="9" height="6" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>', 13),
  cloud: _S('<path d="M5 12a3 3 0 0 1 .3-6 3.5 3.5 0 0 1 6.6.8A2.6 2.6 0 0 1 11.5 12z"/>', 13),
  clock: _S('<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.4 1.4"/>'),
  bolt: _S('<path d="M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z"/>'),
  attach: _S('<path d="M12 6.5l-5 5a2.4 2.4 0 0 1-3.4-3.4l5.2-5.2a1.6 1.6 0 0 1 2.3 2.3l-5.2 5.2a.8.8 0 0 1-1.1-1.1L9.5 5"/>', 17),
};
function applyIcons() {
  document.querySelectorAll(".snav").forEach((b) => {
    const el = b.querySelector(".snav-ic"); if (!el) return;
    const key = b.id === "helpBtn" ? "help" : (b.dataset.nav === "sources" ? "connectors" : b.dataset.nav);
    el.innerHTML = IC[key] || "";
  });
  const set = (id, name) => { const e = $(id); if (e) e.innerHTML = IC[name]; };
  set("#attachBtn", "attach"); set("#micBtn", "mic"); set("#send", "arrowUp");
}

// collapse / expand the sidebar (persisted)
function setCollapsed(on) {
  const app = document.querySelector(".app"); if (!app) return;
  app.classList.toggle("collapsed", on);
  const b = $("#collapseBtn"); if (b) { b.textContent = on ? "›" : "‹"; b.title = on ? "Expand sidebar" : "Collapse sidebar"; }
  try { localStorage.setItem("ls_collapsed", on ? "1" : ""); } catch (_) {}
}
{
  const b = $("#collapseBtn");
  if (b) b.onclick = () => setCollapsed(!document.querySelector(".app").classList.contains("collapsed"));
  setCollapsed(localStorage.getItem("ls_collapsed") === "1");
}
function agentOrbId(a) { return (a && a.id === localStorage.getItem("lodestone_lead_agent")) ? "__lead" : (a ? a.id : ""); }
function agentDesc(a) {
  if (!a) return "";
  if (a.id === localStorage.getItem("lodestone_lead_agent")) return "Leads your team and helps with everything — your first stop for anything.";
  return "Helps you with " + (a.role || "your work") + ".";
}

// which side panel / view a sidebar nav item opens
function switchTab(tab) {
  document.querySelectorAll(".ctx-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".ctx-pane").forEach((p) => p.hidden = p.dataset.pane !== tab);
}

// tiny, safe markdown renderer (escapes first, then applies a subset)
function mdInline(s) {
  return s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])((https?:\/\/[^\s<)]+))/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}
function md(src) {
  const lines = esc(src).split("\n");
  let html = "", inList = false, inCode = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    if (/^```/.test(raw)) {
      if (inCode) { html += "</code></pre>"; inCode = false; }
      else { closeList(); html += "<pre><code>"; inCode = true; }
      continue;
    }
    if (inCode) { html += raw + "\n"; continue; }
    const h = raw.match(/^(#{1,4})\s+(.*)/);
    if (h) { closeList(); const lvl = Math.min(h[1].length + 2, 6); html += `<h${lvl}>${mdInline(h[2])}</h${lvl}>`; continue; }
    const li = raw.match(/^\s*[-*]\s+(.*)/) || raw.match(/^\s*\d+\.\s+(.*)/);
    if (li) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${mdInline(li[1])}</li>`; continue; }
    if (raw.trim() === "") { closeList(); continue; }
    closeList(); html += `<p>${mdInline(raw)}</p>`;
  }
  closeList(); if (inCode) html += "</code></pre>";
  return html;
}

async function loadAgents() {
  const d = await api("/api/agents");
  agents = d.agents;
  // pin the lead agent (created at welcome) to the top
  const leadId = localStorage.getItem("lodestone_lead_agent");
  agents.sort((a, b) => (b.id === leadId ? 1 : 0) - (a.id === leadId ? 1 : 0));
  $("#agentList").innerHTML = agents.map((a) => {
    const lead = a.id === leadId;
    return `
    <div class="agent ${a.id === current ? "active" : ""}" data-id="${a.id}">
      <span class="orb" style="${orbStyle(agentOrbId(a))}"></span>
      <div class="a-meta">
        <div class="n">${esc(a.name)}${lead ? ` <span class="lead-tag">Lead</span>` : ""}</div>
        <div class="r">${esc(a.role)}</div>
      </div>
      ${a.custom && !lead ? `<span class="del-agent" data-del-agent="${a.id}">✕</span>`
        : (a.id === current ? `<span class="dot"></span>` : "")}
    </div>`; }).join("");
  document.querySelectorAll(".agent").forEach((el) => el.onclick = (e) => {
    if (e.target.dataset.delAgent) return;   // handled below
    selectAgent(el.dataset.id);
  });
  document.querySelectorAll("[data-del-agent]").forEach((el) => el.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm("Delete this agent?")) return;
    await api(`/api/agents/custom/${el.dataset.delAgent}`, { method: "DELETE" });
    if (current === el.dataset.delAgent) current = null;
    toast("Agent deleted"); loadAgents();
  });
  if (!current && agents.length) selectAgent(agents[0].id);
}

const MODEL_HINTS = {
  claude: "e.g. claude-3-7-sonnet-latest, claude-3-5-sonnet-latest, claude-3-5-haiku-latest",
  anthropic: "e.g. claude-3-7-sonnet-latest, claude-3-5-sonnet-latest, claude-3-5-haiku-latest",
  cursor: "e.g. cursor-fast, cursor-small, claude-3.7-sonnet, gpt-5.6-terra",
  gemini: "e.g. gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash",
  xai: "e.g. grok-3, grok-3-mini, grok-2-latest",
  openai: "e.g. gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol, gpt-6-astra",
  deepseek: "e.g. deepseek-chat (V3), deepseek-reasoner (R1)",
  ollama: "e.g. llama3.3:70b, llama3.2, qwen2.5-coder:7b, deepseek-r1:8b",
  "claude-code": "uses your local Claude CLI session",
  openrouter: "e.g. anthropic/claude-3.7-sonnet, openai/gpt-5.6-terra",
  subscription: "local session gateway proxy",
  mock: "offline test model",
};

function applyModelHint() {
  const prov = $("#provider") ? $("#provider").value : "";
  if (!prov) return;
  $("#modelHint").textContent = MODEL_HINTS[prov] || "";
  updatePrivacyBadge();
  const defBox = $("#defaultProviderConnectBox");
  if (defBox) renderProviderConnectBox(defBox, prov);
}

function updatePrivacyBadge() {
  const el = $("#privacyBadge");
  if (!el) return;
  const p = (PROVIDERS || []).find((x) => x.name === $("#provider").value);
  if (!p) { el.hidden = true; return; }
  el.hidden = false;
  const local = p.locality === "local";
  el.className = "privacy-badge " + (local ? "loc-local" : "loc-cloud");
  el.innerHTML = `<span class="pb-ic">${local ? IC.lock : IC.cloud}</span>` +
    `<span>${local ? "On-device" : "Leaves your Mac"}</span>`;
  el.title = p.destination || "";
}

const FALLBACK_CATALOG = [
  { id: "claude", label: "Claude (Anthropic)", key_env: "ANTHROPIC_API_KEY", key_url: "https://console.anthropic.com/settings/keys", destination: "Sent to Anthropic's API.", locality: "cloud", default_model: "claude-3-7-sonnet-latest", models: [{ id: "claude-3-7-sonnet-latest", name: "Claude 3.7 Sonnet", desc: "Hybrid reasoning & coding flagship" }, { id: "claude-3-5-sonnet-latest", name: "Claude 3.5 Sonnet", desc: "High-intelligence workhorse" }, { id: "claude-3-5-haiku-latest", name: "Claude 3.5 Haiku", desc: "Fast & responsive everyday model" }] },
  { id: "cursor", label: "Cursor", key_env: "CURSOR_API_KEY", key_url: "https://cursor.com", destination: "Connects to your local Cursor bridge or Cursor API.", locality: "local", default_model: "cursor-fast", models: [{ id: "cursor-fast", name: "Cursor Fast", desc: "Low latency reasoning & agent flow" }, { id: "cursor-small", name: "Cursor Small", desc: "Fast local coding & agent flow" }, { id: "claude-3.7-sonnet", name: "Cursor Claude 3.7 Sonnet", desc: "Via Cursor bridge" }, { id: "gpt-5.6-terra", name: "Cursor GPT-5.6-Terra", desc: "Via Cursor bridge" }] },
  { id: "gemini", label: "Google Gemini", key_env: "GEMINI_API_KEY", key_url: "https://aistudio.google.com/apikey", destination: "Sent to Google Gemini API.", locality: "cloud", default_model: "gemini-2.5-flash", models: [{ id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", desc: "Deep reasoning powerhouse" }, { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", desc: "Next-gen speed & reasoning" }, { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash", desc: "Ultra-fast generation & tools" }] },
  { id: "xai", label: "xAI (Grok)", key_env: "XAI_API_KEY", key_url: "https://console.x.ai", destination: "Sent to xAI Grok API.", locality: "cloud", default_model: "grok-3", models: [{ id: "grok-3", name: "Grok 3", desc: "Flagship reasoning & deep intelligence" }, { id: "grok-3-mini", name: "Grok 3 Mini", desc: "High-speed reasoning & code generation" }, { id: "grok-2-latest", name: "Grok 2", desc: "Advanced reasoning & tool calling" }, { id: "grok-2-vision-latest", name: "Grok 2 Vision", desc: "Multimodal reasoning & image input" }, { id: "grok-2-1212", name: "Grok 2 (1212)", desc: "Stable production snapshot" }] },
  { id: "openai", label: "OpenAI", key_env: "OPENAI_API_KEY", key_url: "https://platform.openai.com/api-keys", destination: "Sent to OpenAI's API.", locality: "cloud", default_model: "gpt-5.6-terra", models: [{ id: "gpt-5.6-terra", name: "GPT-5.6-Terra", desc: "Balanced agentic coding model for everyday work" }, { id: "gpt-5.6-luna", name: "GPT-5.6-Luna", desc: "Fast and affordable agentic coding model" }, { id: "gpt-5.6-sol", name: "GPT-5.6-Sol", desc: "Flagship agentic coding model for complex tasks", locked: true, plan_required: "Pro" }, { id: "gpt-6-astra", name: "GPT-6-Astra", desc: "Our most capable model for complex, demanding work", locked: true, plan_required: "Pro" }, { id: "gpt-reserve", name: "GPT-Reserve", desc: "Fast backup agentic coding model" }, { id: "o3-mini", name: "o3-mini", desc: "Fast STEM & code reasoning", locked: true, plan_required: "Plus" }, { id: "gpt-5.5", name: "GPT-5.5", desc: "Proven previous-generation coding model" }] },
  { id: "deepseek", label: "DeepSeek", key_env: "DEEPSEEK_API_KEY", key_url: "https://platform.deepseek.com/api_keys", destination: "Sent to DeepSeek's API.", locality: "cloud", default_model: "deepseek-chat", models: [{ id: "deepseek-chat", name: "DeepSeek V3", desc: "Elite coding & general intelligence" }, { id: "deepseek-reasoner", name: "DeepSeek R1", desc: "Reasoning model with chain of thought" }] },
  { id: "ollama", label: "Ollama (Local)", key_env: "", key_url: "https://ollama.com", destination: "Runs on your Mac — your context stays on-device.", locality: "local", default_model: "llama3.2", models: [{ id: "llama3.3:70b", name: "Llama 3.3 (70B)", desc: "Latest flagship open weights model" }, { id: "llama3.2", name: "Llama 3.2", desc: "Compact offline local model" }, { id: "qwen2.5-coder:7b", name: "Qwen 2.5 Coder (7B)", desc: "Strong multilingual local model" }, { id: "deepseek-r1:8b", name: "DeepSeek R1 (8B)", desc: "Local reasoning model" }] },
  { id: "openrouter", label: "OpenRouter", key_env: "OPENROUTER_API_KEY", key_url: "https://openrouter.ai/keys", destination: "Sent to OpenRouter (and the chosen model's host).", locality: "cloud", default_model: "anthropic/claude-3.7-sonnet", models: [{ id: "anthropic/claude-3.7-sonnet", name: "Claude 3.7 Sonnet", desc: "Via OpenRouter" }, { id: "openai/gpt-5.6-terra", name: "GPT-5.6-Terra", desc: "Via OpenRouter" }, { id: "deepseek/deepseek-r1", name: "DeepSeek R1", desc: "Via OpenRouter" }, { id: "meta-llama/llama-3.3-70b-instruct", name: "Llama 3.3 70B", desc: "Via OpenRouter" }] },
  { id: "claude-code", label: "Claude Code CLI", key_env: "", key_url: "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview", destination: "Sent to Anthropic through the Claude CLI.", locality: "cloud", default_model: "claude-code", models: [{ id: "claude-code", name: "Claude Code Session", desc: "Local Anthropic CLI bridge" }] },
];

let PROVIDERS = [];
let MODEL_CATALOG = FALLBACK_CATALOG;

const BRAND_ICONS = {
  openai: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M22.28 9.82a5.98 5.98 0 0 0-.51-4.91 6.05 6.05 0 0 0-6.51-2.9 6.06 6.06 0 0 0-10.28 2.17 5.98 5.98 0 0 0-4 2.9 6.05 6.05 0 0 0 .74 7.1 5.98 5.98 0 0 0 .51 4.91 6.05 6.05 0 0 0 6.51 2.9 6.06 6.06 0 0 0 10.28-2.17 5.99 5.99 0 0 0 4-2.9 6.05 6.05 0 0 0-.74-7.1zm-9.02 12.61a4.48 4.48 0 0 1-2.88-1.04l.14-.08 4.78-2.76a.8.8 0 0 0 .39-.68v-6.74l2.02 1.17a.07.07 0 0 1 .04.05v5.58a4.5 4.5 0 0 1-4.49 4.5zm-9.66-4.13a4.47 4.47 0 0 1-.53-3.01l.14.08 4.78 2.76a.77.77 0 0 0 .78 0l5.84-3.37v2.33a.08.08 0 0 1-.03.06L9.74 19.95a4.5 4.5 0 0 1-6.14-1.65zM2.34 7.9a4.48 4.48 0 0 1 2.37-1.98v5.69a.77.77 0 0 0 .38.67l5.82 3.36-2.02 1.17a.08.08 0 0 1-.07 0L3.99 14.02A4.5 4.5 0 0 1 2.34 7.9zm16.1 3.85l-5.84-3.37 2.02-1.16a.08.08 0 0 1 .07 0l4.83 2.79a4.5 4.5 0 0 1-.68 8.1v-5.67a.79.79 0 0 0-.4-.69zm2.01-3.02l-.14-.09-4.78-2.78a.78.78 0 0 0-.78 0L9.41 9.23V6.9a.07.07 0 0 1 .03-.06l4.83-2.79a4.5 4.5 0 0 1 6.68 4.66zM8.31 12.86l-2.02-1.16a.08.08 0 0 1-.04-.06V6.07a4.5 4.5 0 0 1 7.38-3.45l-.14.08-4.78 2.76a.8.8 0 0 0-.4.68v6.72zm1.14-2.07l2.55-1.47 2.55 1.47v2.94l-2.55 1.47-2.55-1.47z"/></svg>`,
  claude: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a1 1 0 0 1 1 1v2.5a1 1 0 0 1-2 0V3a1 1 0 0 1 1-1zm0 15.5a1 1 0 0 1 1 1V21a1 1 0 0 1-2 0v-2.5a1 1 0 0 1 1-1zm8-6.5a1 1 0 0 1 1 1 1 1 0 0 1-1 1h-2.5a1 1 0 0 1 0-2H20zM6.5 12a1 1 0 0 1 0 2H4a1 1 0 0 1 0-2h2.5zm11.16-6.25a1 1 0 0 1 1.42 0 1 1 0 0 1 0 1.42l-1.77 1.76a1 1 0 0 1-1.41-1.41l1.76-1.77zm-11.31 11.32a1 1 0 0 1 1.41 0 1 1 0 0 1 0 1.41l-1.77 1.77a1 1 0 0 1-1.41-1.41l1.77-1.77zm12.73 0a1 1 0 0 1 0 1.41l-1.77 1.77a1 1 0 0 1-1.41-1.41l1.77-1.77a1 1 0 0 1 1.41 0zM6.35 7.17a1 1 0 0 1 0-1.42l1.77-1.76a1 1 0 1 1 1.41 1.41L7.76 7.17a1 1 0 0 1-1.41 0z"/></svg>`,
  cursor: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1.75l9.5 5.5v11.5L12 24.25 2.5 18.75V7.25L12 1.75zm0 2.3L4.5 8.38l7.5 4.33 7.5-4.33L12 4.05zm8 6.13l-7 4.04v7.73l7-4.04v-7.73zm-9 11.77v-7.73l-7-4.04v7.73l7 4.04z"/></svg>`,
  xai: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M18.24 2.25h3.31l-7.23 8.26 8.5 11.24H16.17l-5.21-6.82L4.99 21.75H1.68l7.73-8.84L1.25 2.25H8.08l4.71 6.23zm-1.16 17.52h1.83L7.08 4.13H5.12z"/></svg>`,
  gemini: `<svg width="15" height="15" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.75 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.98 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>`,
};

let activeWaitingHud = null;

function showWaitingHud({ brandName, authUrl, providerId, requiresCode = false, onCancel, onConnected }) {
  if (activeWaitingHud) {
    activeWaitingHud.dismiss();
  }

  const hud = document.createElement("div");
  hud.className = "ts-floating-hud";
  hud.innerHTML = `
    <div class="ts-hud-header">
      <div class="ts-hud-status">
        <span class="ts-hud-icon">✨</span>
        <span>Waiting to connect</span>
      </div>
      <button type="button" class="ts-hud-close" title="Dismiss">✕</button>
    </div>
    <div class="ts-hud-title">Connect ${esc(brandName)} in your browser</div>
    <div class="ts-hud-body">Sign in and approve access there. TURNOVER will update when the connection is ready.</div>
    ${authUrl ? `<button type="button" class="ts-hud-btn"><span>↗</span> Open browser sign in</button>` : ""}
    ${requiresCode ? `
      <div class="ts-hud-code-form" style="margin-top:8px;display:flex;gap:6px">
        <input type="text" class="ts-hud-code-input" placeholder="Paste code#state here" style="flex:1;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);border-radius:7px;padding:6px 10px;font-size:11px;color:#fff;font-family:var(--mono)">
        <button type="button" class="ts-hud-code-submit tiny primary" style="padding:6px 12px;font-size:11px">Connect</button>
      </div>
    ` : ""}
  `;

  document.body.appendChild(hud);

  const closeBtn = hud.querySelector(".ts-hud-close");
  const openBtn = hud.querySelector(".ts-hud-btn");
  const codeInput = hud.querySelector(".ts-hud-code-input");
  const codeSubmit = hud.querySelector(".ts-hud-code-submit");

  if (openBtn && authUrl) {
    openBtn.onclick = async () => {
      try {
        await api("/api/open-browser", { method: "POST", body: { url: authUrl } });
      } catch (_) {
        window.open(authUrl, "_blank");
      }
    };
  }

  if (codeInput && codeSubmit) {
    codeSubmit.onclick = async () => {
      const code = codeInput.value.trim();
      if (!code) return;
      codeSubmit.disabled = true;
      codeSubmit.innerText = "Connecting…";
      try {
        const res = await api(`/api/providers/${providerId}/submit-code`, {
          method: "POST",
          body: { code }
        });
        toast(`✓ ${res.message || 'Authenticated!'}`);
        await api(`/api/providers/${providerId}/refresh`, { method: "POST" });
        dismiss();
        if (onConnected) onConnected();
      } catch (err) {
        toast(`Error: ${err.message || err}`);
        codeSubmit.disabled = false;
        codeSubmit.innerText = "Connect";
      }
    };
  }

  let pollTimer = null;
  const dismiss = () => {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    hud.style.opacity = "0";
    hud.style.transform = "translateY(-10px) scale(0.95)";
    hud.style.transition = "all 0.2s ease";
    setTimeout(() => {
      if (hud.parentNode) hud.parentNode.removeChild(hud);
    }, 220);
    if (activeWaitingHud && activeWaitingHud.el === hud) {
      activeWaitingHud = null;
    }
    if (onCancel) onCancel();
  };

  closeBtn.onclick = dismiss;

  let attempts = 0;
  pollTimer = setInterval(async () => {
    attempts++;
    if (attempts > 120) { // ~2.5 mins
      dismiss();
      return;
    }
    try {
      if (providerId === "gemini") {
        const st = await api("/api/google/status");
        if (st.connected && st.account) {
          clearInterval(pollTimer);
          pollTimer = null;
          await api("/api/providers/gemini/refresh", { method: "POST" });
          dismiss();
          toast(`✓ Google account connected (${st.account})!`);
          if (onConnected) onConnected();
        }
      } else {
        // Check dedicated oauth-status if applicable
        if (["openai", "xai", "claude"].includes(providerId)) {
          const st = await api(`/api/providers/${providerId}/oauth-status`).catch(() => ({}));
          if (st.status === "success") {
            clearInterval(pollTimer);
            pollTimer = null;
            await api(`/api/providers/${providerId}/refresh`, { method: "POST" });
            dismiss();
            toast(`✓ Connected ${brandName} (${st.email || ''})!`);
            if (onConnected) onConnected();
            return;
          }
        }
        const ref = await api(`/api/providers/${providerId}/refresh`, { method: "POST" });
        if (ref.ready || ref.connection?.connection_status === "ACCOUNT_CONNECTED") {
          clearInterval(pollTimer);
          pollTimer = null;
          dismiss();
          const email = ref.connection?.email || "";
          toast(`✓ Connected ${brandName}${email ? ` (${email})` : ""}!`);
          if (onConnected) onConnected();
        }
      }
    } catch (_) {}
  }, 1200);

  activeWaitingHud = { el: hud, dismiss };
  return activeWaitingHud;
}

function formatSubscriptionUsageUpdated(updatedAt, now) {
  if (!updatedAt) return "Updated just now";
  const nowMs = now || Date.now();
  const ageMinutes = Math.max(0, Math.floor((nowMs - updatedAt) / 60000));
  if (ageMinutes < 1) return "Updated just now";
  if (ageMinutes < 60) return `Updated ${ageMinutes}m ago`;
  const ageHours = Math.floor(ageMinutes / 60);
  if (ageHours < 24) return `Updated ${ageHours}h ago`;
  return `Updated ${Math.floor(ageHours / 24)}d ago`;
}

function formatSubscriptionUsageReset(resetsAt, now) {
  if (!resetsAt) return "";
  const nowMs = now || Date.now();
  const resetMs = Number(resetsAt) < 1e11 ? Number(resetsAt) * 1000 : Number(resetsAt);
  const remainingMinutes = Math.ceil((resetMs - nowMs) / 60000);
  if (remainingMinutes <= 0) return "resetting now";
  if (remainingMinutes < 60) return `resets in ${remainingMinutes}m`;
  const hours = Math.floor(remainingMinutes / 60);
  const minutes = remainingMinutes % 60;
  if (hours < 24) return `resets in ${hours}h${minutes ? ` ${minutes}m` : ""}`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return `resets in ${days}d${remainingHours ? ` ${remainingHours}h` : ""}`;
}

function subscriptionUsageRemainingPercent(usedPercent) {
  return Math.max(0, Math.min(100, Math.round(100 - (Number(usedPercent) || 0))));
}

function renderProviderConnectBox(boxEl, providerId, options = {}) {
  if (!boxEl) return;
  const p = (MODEL_CATALOG || []).find((c) => c.id === providerId)
         || (PROVIDERS || []).find((x) => x.name === providerId)
         || { id: providerId, label: providerId, ready: false };

  const conn = p.connection || {};
  const isDisconnected = (conn.connection_status === "DISCONNECTED");
  const isReady = Boolean(p.ready && !isDisconnected);
  const caps = p.capabilities || {};
  const detected = p.detected_account || {};
  const accountEmail = (!isDisconnected && (conn.email || (conn.connection_status === "ACCOUNT_CONNECTED" && detected.email) || (p.account_meta && p.account_meta.email))) || "";
  const hasActiveAccount = Boolean(!isDisconnected && isReady && (accountEmail || conn.auth_method === "account" || conn.connection_status === "ACCOUNT_CONNECTED"));
  const isFoundOnComputer = Boolean(!hasActiveAccount && detected.found_on_computer && detected.email);
  const keyEnv = p.key_env || (caps.key_env || (providerId === "openai" ? "OPENAI_API_KEY" : (providerId === "anthropic" || providerId === "claude" ? "ANTHROPIC_API_KEY" : (providerId === "gemini" ? "GEMINI_API_KEY" : (providerId === "xai" ? "XAI_API_KEY" : (providerId === "deepseek" ? "DEEPSEEK_API_KEY" : (providerId === "openrouter" ? "OPENROUTER_API_KEY" : (providerId === "cursor" ? "CURSOR_API_KEY" : ""))))))));
  const keyUrl = p.key_url || (caps.official_auth_url || "");
  const models = p.models || [];

  let brandName = "Account";
  let signinBtnName = "Sign in";
  let brandIcon = "";
  if (providerId === "openai") {
    brandName = "ChatGPT";
    signinBtnName = "Sign in with ChatGPT";
    brandIcon = BRAND_ICONS.openai;
  } else if (providerId === "claude" || providerId === "anthropic") {
    brandName = "Claude";
    signinBtnName = "Sign in with Claude";
    brandIcon = BRAND_ICONS.claude;
  } else if (providerId === "cursor") {
    brandName = "Cursor";
    signinBtnName = "Sign in with Cursor";
    brandIcon = BRAND_ICONS.cursor;
  } else if (providerId === "xai") {
    brandName = "Grok";
    signinBtnName = "Sign in with Grok";
    brandIcon = BRAND_ICONS.xai;
  } else if (providerId === "gemini") {
    brandName = "Google";
    signinBtnName = "Sign in with Google";
    brandIcon = BRAND_ICONS.gemini;
  }

  // 1. Detected / Active Account Card
  let activeCardHtml = "";
  if (hasActiveAccount || isFoundOnComputer) {
    let cardTitle = "Connected Account";
    let badgeText = "Using this account";
    let badgeClass = "using";

    if (providerId === "openai") {
      cardTitle = isFoundOnComputer ? `${detected.plan || p.plan || "ChatGPT"} found` : (detected.plan || p.plan || conn.plan || "ChatGPT Free");
      badgeText = isFoundOnComputer ? "Found on this computer" : "Using this account";
      badgeClass = isFoundOnComputer ? "found" : "using";
    } else if (providerId === "claude" || providerId === "anthropic") {
      cardTitle = isFoundOnComputer ? `${detected.plan || "Claude Pro"} found` : "Claude connected";
      badgeText = isFoundOnComputer ? "Found on this computer" : "Using this account";
      badgeClass = isFoundOnComputer ? "found" : "using";
    } else if (providerId === "cursor") {
      cardTitle = isFoundOnComputer ? `${detected.plan || "Cursor"} found` : "Cursor connected";
      badgeText = isFoundOnComputer ? "Found on this computer" : "Connected";
      badgeClass = isFoundOnComputer ? "found" : "using";
    } else if (providerId === "xai") {
      cardTitle = isFoundOnComputer ? `${detected.plan || "Grok"} found` : "Grok connected";
      badgeText = isFoundOnComputer ? "Found on this computer" : "Connected";
      badgeClass = isFoundOnComputer ? "found" : "using";
    } else if (providerId === "gemini") {
      cardTitle = isFoundOnComputer ? "Google found" : "Google connected";
      badgeText = isFoundOnComputer ? "Found on this computer" : "Using this account";
      badgeClass = isFoundOnComputer ? "found" : "using";
    }

    const subText = isFoundOnComputer
      ? `${esc(detected.email || accountEmail)} · Found on this computer`
      : `${esc(accountEmail || "API Key Active")} · Added to TURNOVER`;

    const descText = providerId === "openai"
      ? "Your ChatGPT plan includes a limited set of models. TURNOVER automatically uses the best model available with your plan."
      : "Added to TURNOVER. Other apps keep their own sign-in.";

    let usageHtml = "";
    const usage = detected.usage || p.usage || conn.usage;
    if (providerId === "openai" && hasActiveAccount && usage && usage.state !== "unavailable") {
      const windows = usage.windows && usage.windows.length ? usage.windows : [
        { id: "primary", label: "30-day limit", usedPercent: 5, resetsAt: Date.now() + 2588800000 }
      ];
      const updatedLabel = formatSubscriptionUsageUpdated(usage.updatedAt, Date.now());
      usageHtml = `
        <div class="ts-usage-section" role="group" aria-label="Usage limits">
          <div class="ts-usage-head">
            <span class="ts-usage-title">Usage limits</span>
            <span class="ts-usage-updated">${esc(updatedLabel)}</span>
          </div>
          ${windows.map((w) => {
            const remainingPercent = subscriptionUsageRemainingPercent(w.usedPercent);
            const resetLabel = w.resetsAt ? formatSubscriptionUsageReset(w.resetsAt, Date.now()) : "";
            return `
              <div class="ts-usage-window">
                <div class="ts-usage-row">
                  <span>${esc(w.label || "30-day limit")}</span>
                  <span class="ts-usage-remaining">${remainingPercent}% remaining${resetLabel ? ` · ${esc(resetLabel)}` : ""}</span>
                </div>
                <div class="ts-progress-track">
                  <div class="ts-progress-fill" style="width:${remainingPercent}%"></div>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    let actionBtnHtml = "";
    if (isFoundOnComputer) {
      actionBtnHtml = `
        <button type="button" class="tiny primary ts-continue-btn" style="padding:5px 12px">Continue</button>
        <button type="button" class="ts-btn-link ts-refresh-btn">Refresh</button>
        <button type="button" class="ts-btn-link ts-disconnect-btn" style="color:#ef4444" title="Disconnect provider">✕</button>
      `;
    } else if (providerId === "openai") {
      // In Turnstone/real UI, top card has no action buttons on the right
      actionBtnHtml = "";
    } else {
      actionBtnHtml = `
        <button type="button" class="tiny ts-btn-signin" style="background:rgba(16,185,129,0.12);border-color:rgba(16,185,129,0.3);color:#34d399;cursor:default">Connected</button>
        <button type="button" class="ts-btn-link ts-refresh-btn">Refresh</button>
        <button type="button" class="ts-btn-link ts-disconnect-btn" style="color:#ef4444" title="Disconnect provider">✕</button>
      `;
    }

    activeCardHtml = `
      <div class="ts-card active-account">
        <div class="ts-card-row">
          <div class="ts-card-left">
            <div class="ts-card-title-wrap">
              <span class="ts-card-title">${esc(cardTitle)}</span>
              <span class="ts-badge ${badgeClass}">${esc(badgeText)}</span>
            </div>
            <div class="ts-card-sub" style="font-weight:500;color:var(--text)">${subText}</div>
            <div class="ts-card-desc">${descText}</div>
          </div>
          ${actionBtnHtml ? `<div class="ts-action-group">${actionBtnHtml}</div>` : ""}
        </div>
        ${usageHtml}
      </div>
    `;
  }

  // 2. Account Sign-in / Different Account Card
  let signinCardHtml = "";
  if (caps.browser_login_supported || caps.oauth_supported || ["openai", "claude", "cursor", "xai", "gemini"].includes(providerId)) {
    const signinTitle = `${brandName} account for TURNOVER`;
    const signinSub = `Sign in again or use a different account without changing other apps.`;

    signinCardHtml = `
      <div class="ts-card ts-signin-container">
        <div class="ts-card-row">
          <div class="ts-card-left">
            <span class="ts-card-title">${esc(signinTitle)}</span>
            <span class="ts-card-sub">${esc(signinSub)}</span>
          </div>
          <div class="ts-action-group">
            <button type="button" class="ts-btn-signin ts-signin-btn">
              ${brandIcon}
              <span>${esc(signinBtnName)}</span>
            </button>
            <button type="button" class="ts-btn-link ts-refresh-btn">Refresh</button>
            ${hasActiveAccount ? `<button type="button" class="ts-btn-link ts-disconnect-btn" style="color:var(--muted)" title="Disconnect provider">✕</button>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  // 3. API Key Card
  let apiKeyCardHtml = "";
  if (keyEnv) {
    apiKeyCardHtml = `
      <div class="ts-card">
        <div class="ts-card-row">
          <div class="ts-card-left">
            <span class="ts-card-title">${esc(p.label || providerId)} API key</span>
            <span class="ts-card-sub">Used for ${esc(p.label || providerId)} runs.${keyUrl ? ` <a href="${keyUrl}" target="_blank" rel="noopener" class="pc-link" style="margin-left:4px">Get key ↗</a>` : ""}</span>
          </div>
          <div class="ts-action-group">
            <button type="button" class="tiny ghost ts-toggle-key-btn">${isReady ? 'Update API key' : 'Add API key'}</button>
          </div>
        </div>
        <div class="ts-key-collapse" style="display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
          <input type="password" class="pc-key-input" placeholder="Paste ${esc(keyEnv)}…" autocomplete="off" />
          <button type="button" class="tiny primary pc-connect-btn">Save</button>
          <button type="button" class="tiny ghost pc-test-btn">Test</button>
        </div>
      </div>
    `;
  }

  // 4. Models Card
  let modelsCardHtml = "";
  if (models && models.length) {
    modelsCardHtml = `
      <div style="margin-top:4px">
        <div class="pc-models-list">
          ${models.slice(0, 8).map((m) => {
            const isReasoning = Boolean(m.reasoning);
            const hasTools = m.tool_calling !== false;
            const hasVision = Boolean(m.vision);
            return `
              <div class="pc-model-pill" title="${esc(m.desc || m.id)}">
                <span>${esc(m.name || m.id)}</span>
                ${isReasoning ? `<span class="pc-tag reasoning">r1/o1</span>` : ""}
                ${hasTools ? `<span class="pc-tag tools">tools</span>` : ""}
                ${hasVision ? `<span class="pc-tag vision">vision</span>` : ""}
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  boxEl.innerHTML = `
    ${activeCardHtml}
    ${signinCardHtml}
    ${apiKeyCardHtml}
    ${modelsCardHtml}
    <div class="pc-feedback" style="display:none;margin-top:4px;padding:4px 6px"></div>
  `;

  const feedbackEl = boxEl.querySelector(".pc-feedback");
  const setFeedback = (msg, isErr = false) => {
    if (!feedbackEl) return;
    feedbackEl.style.display = "block";
    feedbackEl.style.color = isErr ? "#f87171" : "#34d399";
    feedbackEl.textContent = msg;
  };

  // Toggle API key form
  const toggleKeyBtn = boxEl.querySelector(".ts-toggle-key-btn");
  const keyCollapse = boxEl.querySelector(".ts-key-collapse");
  if (toggleKeyBtn && keyCollapse) {
    toggleKeyBtn.onclick = () => {
      const isClosed = keyCollapse.style.display === "none";
      keyCollapse.style.display = isClosed ? "flex" : "none";
      if (isClosed) {
        const inp = keyCollapse.querySelector(".pc-key-input");
        if (inp) inp.focus();
      }
    };
  }

  // Connect local account (e.g. Claude / Cursor found on this computer)
  const continueBtn = boxEl.querySelector(".ts-continue-btn");
  if (continueBtn) {
    continueBtn.onclick = async () => {
      continueBtn.disabled = true;
      setFeedback("Connecting local account…");
      try {
        const res = await api(`/api/providers/${providerId}/connect-local`, { method: "POST" });
        toast(`✓ Connected ${p.label || providerId} account!`);
        await loadProviders();
        if (options.onConnect) options.onConnect();
      } catch (e) {
        setFeedback(`Connection error: ${e.message || e}`, true);
      } finally {
        continueBtn.disabled = false;
      }
    };
  }

  // Sign in flow with live waiting card and reactive polling
  const signinBtn = boxEl.querySelector(".ts-signin-btn");
  const signinContainer = boxEl.querySelector(".ts-signin-container");
  if (signinBtn && signinContainer) {
    signinBtn.onclick = async () => {
      signinBtn.disabled = true;
      const originalHtml = signinContainer.innerHTML;

      signinContainer.innerHTML = `
        <div class="ts-waiting-card">
          <div class="ts-spinner"></div>
          <div class="ts-waiting-body">
            <div class="ts-waiting-title">Waiting for ${esc(brandName)} sign-in…</div>
            <div class="ts-waiting-sub">Finish signing in to ${esc(brandName)} in your browser. TURNOVER will automatically update when your account is ready.</div>
          </div>
          <button type="button" class="tiny ghost ts-cancel-poll-btn">Cancel</button>
        </div>
      `;

      let hud = null;
      const cancelBtn = signinContainer.querySelector(".ts-cancel-poll-btn");
      const stopPolling = () => {
        if (hud) {
          hud.dismiss();
          hud = null;
        }
        signinContainer.innerHTML = originalHtml;
        renderProviderConnectBox(boxEl, providerId, options);
      };

      if (cancelBtn) cancelBtn.onclick = stopPolling;

      try {
        const res = await api(`/api/providers/${providerId}/signin`, { method: "POST" });
        toast(`Opening ${brandName} in browser…`);

        if (res.connected) {
          toast(`✓ ${res.detail || 'Connected!'}`);
          stopPolling();
          await loadProviders();
          if (options.onConnect) options.onConnect();
          return;
        }

        // Open browser tab if the backend hasn't already (e.g. no CLI available)
        if (res.auth_url && !res.browser_opened) {
          try {
            await api("/api/open-browser", { method: "POST", body: { url: res.auth_url } });
          } catch (_) {
            window.open(res.auth_url, "_blank");
          }
        }

        // Show floating HUD widget
        hud = showWaitingHud({
          brandName,
          authUrl: res.auth_url || "",
          providerId,
          requiresCode: res.requires_code || false,
          onCancel: () => {
            signinContainer.innerHTML = originalHtml;
            renderProviderConnectBox(boxEl, providerId, options);
          },
          onConnected: async () => {
            await loadProviders();
            if (options.onConnect) options.onConnect();
          }
        });

      } catch (e) {
        stopPolling();
        setFeedback(`Sign in error: ${e.message || e}`, true);
      }
    };
  }

  // Refresh
  boxEl.querySelectorAll(".ts-refresh-btn").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      setFeedback("Refreshing connection & models…");
      try {
        const res = await api(`/api/providers/${providerId}/refresh`, { method: "POST" });
        setFeedback(res.ready ? `✓ Ready! (${res.models?.length || 0} models)` : `Status: ${res.reason || 'not ready'}`, !res.ready);
        toast(`Refreshed ${p.label || providerId}`);
        await loadProviders();
      } catch (e) {
        setFeedback(`Refresh error: ${e.message || e}`, true);
      } finally {
        btn.disabled = false;
      }
    };
  });

  // Disconnect
  const disconnectBtn = boxEl.querySelector(".ts-disconnect-btn");
  if (disconnectBtn) {
    disconnectBtn.onclick = async () => {
      disconnectBtn.disabled = true;
      setFeedback("Disconnecting…");
      try {
        if (providerId === "gemini") {
          await api("/api/google/disconnect", { method: "POST" });
        }
        await api(`/api/providers/${providerId}/disconnect`, { method: "POST" });
        toast(`Disconnected ${p.label || providerId}`);
        await loadProviders();
        if (options.onConnect) options.onConnect();
      } catch (e) {
        setFeedback(`Disconnect error: ${e.message || e}`, true);
      } finally {
        disconnectBtn.disabled = false;
      }
    };
  }

  // Connect via API key
  const connectBtn = boxEl.querySelector(".pc-connect-btn");
  const inputEl = boxEl.querySelector(".pc-key-input");
  if (connectBtn && inputEl) {
    connectBtn.onclick = async () => {
      const keyVal = inputEl.value.trim();
      if (!keyVal) { setFeedback("Please paste an API key first", true); return; }
      connectBtn.disabled = true;
      setFeedback("Connecting & verifying…");
      try {
        const res = await api(`/api/providers/${providerId}/key`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: keyVal }),
        });
        toast(res.ready ? `✓ Connected ${p.label || providerId}!` : `Saved key for ${p.label || providerId}`);
        inputEl.value = "";
        await loadProviders();
        if (options.onConnect) options.onConnect();
      } catch (e) {
        setFeedback(`Failed to connect: ${e.message || e}`, true);
      } finally {
        connectBtn.disabled = false;
      }
    };
  }

  // Test connection
  const testBtn = boxEl.querySelector(".pc-test-btn");
  if (testBtn && inputEl) {
    testBtn.onclick = async () => {
      testBtn.disabled = true;
      setFeedback("Testing connection…");
      try {
        const res = await api(`/api/providers/${providerId}/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: inputEl.value.trim() || "" }),
        });
        setFeedback(res.ok ? `✓ ${res.message}` : `⚠️ ${res.message}`, !res.ok);
      } catch (e) {
        setFeedback(`Test request error: ${e.message || e}`, true);
      } finally {
        testBtn.disabled = false;
      }
    };
  }
}


const COMPOSER_PROVIDERS = [
  { id: "claude", label: "Anthropic" },
  { id: "openai", label: "OpenAI" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "deepseek", label: "Free open-source models" },
  { id: "ollama", label: "Ollama" },
  { id: "xai", label: "xAI" },
  { id: "cursor", label: "Cursor" },
  { id: "gemini", label: "Google Gemini" },
];

let activePickerProvider = "cursor";
let activePickerModel = null;

function closeAllPickerFlyouts() {
  const pf = $("#cmpProvFlyout");
  const mf = $("#cmpModelFlyout");
  const pr = $("#cmpProvRow");
  const mr = $("#cmpModelRow");
  if (pf) pf.hidden = true;
  if (mf) mf.hidden = true;
  if (pr) pr.classList.remove("cmp-active");
  if (mr) mr.classList.remove("cmp-active");
}

function renderProviderFlyout() {
  const list = $("#cmpProvFlyoutList");
  if (!list) return;

  list.innerHTML = COMPOSER_PROVIDERS.map((p) => {
    const isSel = p.id === activePickerProvider;
    return `
      <div class="cmp-flyout-item ${isSel ? 'is-selected' : ''}" data-prov="${esc(p.id)}">
        <span>${esc(p.label)}</span>
        ${isSel ? '<span class="cmp-flyout-check">✓</span>' : ''}
      </div>
    `;
  }).join("");

  list.querySelectorAll(".cmp-flyout-item").forEach((el) => {
    el.onclick = async (e) => {
      e.stopPropagation();
      const pid = el.dataset.prov;
      const p = COMPOSER_PROVIDERS.find((x) => x.id === pid);
      const pLabel = p ? p.label : pid;
      activePickerProvider = pid;
      activePickerModel = null;
      if ($("#cmpSelectedProvLabel")) $("#cmpSelectedProvLabel").textContent = pLabel;
      if ($("#cmpSelectedModelLabel")) $("#cmpSelectedModelLabel").textContent = "Auto";
      const pillLabel = $("#cmpModelLabel");
      if (pillLabel) pillLabel.textContent = pLabel;
      closeAllPickerFlyouts();

      if (current) {
        try {
          await api(`/api/agents/${current}/model`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider: pid, model: null }),
          });
          toast(`Selected ${pLabel} (Auto) for ${current}`);
          await updateAgentModelChip(current);
          refreshPickerPopover();
        } catch (err) {
          toast("Could not update model: " + err);
        }
      }
    };
  });
}

function renderModelFlyout() {
  const list = $("#cmpModelFlyoutList");
  if (!list) return;

  const pEntry = (MODEL_CATALOG || []).find((c) => c.id === activePickerProvider);
  const models = (pEntry && pEntry.models) || [];

  const items = [
    { id: "", name: "Auto", desc: "Recommended model automatically", locked: false, plan_required: null },
    ...models.map((m) => ({
      id: m.id,
      name: m.name,
      desc: m.desc,
      locked: Boolean(m.locked),
      plan_required: m.plan_required || null,
    })),
  ];

  list.innerHTML = items.map((m) => {
    const isSel = (!activePickerModel && m.id === "") || (activePickerModel === m.id);
    const isLocked = Boolean(m.locked);
    const badgeHtml = isLocked && m.plan_required
      ? `<span class="cmp-lock-badge" title="Requires ${esc(m.plan_required)} plan">🔒 ${esc(m.plan_required)}</span>`
      : (isLocked ? `<span class="cmp-lock-badge">🔒 Locked</span>` : "");
    return `
      <div class="cmp-flyout-item ${isSel ? 'is-selected' : ''} ${isLocked ? 'is-locked' : ''}"
           data-model="${esc(m.id)}"
           data-locked="${isLocked ? 'true' : 'false'}"
           data-plan-req="${esc(m.plan_required || '')}"
           title="${isLocked ? `Requires ${esc(m.plan_required || 'higher')} plan` : esc(m.desc || '')}">
        <div class="cmp-flyout-item-label">
          <span>${esc(m.name)}</span>
          ${badgeHtml}
        </div>
        ${isSel ? '<span class="cmp-flyout-check">✓</span>' : ''}
      </div>
    `;
  }).join("") + `
    <div class="cmp-flyout-item" data-model="__custom__">
      <span style="font-size:12px;color:var(--muted)">Custom model identifier…</span>
    </div>
  `;

  list.querySelectorAll(".cmp-flyout-item").forEach((el) => {
    el.onclick = async (e) => {
      e.stopPropagation();
      if (el.dataset.locked === "true") {
        const req = el.dataset.planReq || "a higher";
        const modelId = el.dataset.model;
        const targetModel = items.find((x) => x.id === modelId);
        const name = targetModel ? targetModel.name : modelId;
        toast(`🔒 ${name} requires ${req} plan. Not supported on your current plan.`);
        return;
      }
      let chosen = el.dataset.model;
      if (chosen === "__custom__") {
        const customName = prompt("Enter custom model identifier:", activePickerModel || "");
        if (customName === null) return;
        chosen = customName.trim();
      }
      activePickerModel = chosen || null;
      const displayLabel = chosen ? (items.find((x) => x.id === chosen)?.name || chosen) : "Auto";
      if ($("#cmpSelectedModelLabel")) $("#cmpSelectedModelLabel").textContent = displayLabel;
      const pillLabel = $("#cmpModelLabel");
      if (pillLabel) {
        const pSpec = COMPOSER_PROVIDERS.find((x) => x.id === activePickerProvider);
        pillLabel.textContent = chosen ? displayLabel : (pSpec ? pSpec.label : "Auto");
      }
      $("#cmpModelMenu").hidden = true;
      closeAllPickerFlyouts();
      const pill = $("#cmpModelPill");
      if (pill) pill.classList.remove("is-active");

      if (current) {
        try {
          await api(`/api/agents/${current}/model`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider: activePickerProvider, model: activePickerModel }),
          });
          toast(`Selected ${displayLabel} for ${current}`);
          await updateAgentModelChip(current);
        } catch (err) {
          toast("Could not update model: " + (err.message || err));
        }
      }
    };
  });
}

function formatProviderPlanInfo(providerId) {
  const p = (MODEL_CATALOG || []).find((c) => c.id === providerId);
  const pSpec = COMPOSER_PROVIDERS.find((x) => x.id === providerId);
  const providerLabel = pSpec ? pSpec.label : (p ? p.label : providerId);

  if (!p) {
    return {
      title: `${providerLabel} plan`,
      plan: "Not configured",
      identity: "",
      connected: false,
    };
  }

  const conn = (typeof p.connection === "object" && p.connection !== null) ? p.connection : {};
  const acct = (typeof p.detected_account === "object" && p.detected_account !== null) ? p.detected_account : {};
  const isConnected = Boolean(
    p.ready ||
    conn.connection_status === "ACCOUNT_CONNECTED" ||
    conn.connection_status === "API_KEY_CONNECTED" ||
    acct.connected
  );

  if (!isConnected) {
    return {
      title: `Sign in with ${providerLabel} to see plan usage`,
      plan: "",
      identity: "",
      connected: false,
    };
  }

  // Extract clean string for plan
  let planLabel = "";
  if (acct.plan && typeof acct.plan === "string") {
    planLabel = acct.plan;
  } else if (conn.auth_method === "api_key") {
    planLabel = "API Key";
  } else {
    if (providerId === "openai") planLabel = "ChatGPT Subscription";
    else if (providerId === "claude") planLabel = "Claude Pro";
    else if (providerId === "cursor") planLabel = "Cursor Free";
    else if (providerId === "xai") planLabel = "Grok Account";
    else if (providerId === "gemini") planLabel = "Google Gemini";
    else planLabel = "Connected Account";
  }

  // Extract clean string for email / account identity
  let emailOrIdentity = "";
  if (acct.email && typeof acct.email === "string") {
    emailOrIdentity = acct.email;
  } else if (conn.email && typeof conn.email === "string") {
    emailOrIdentity = conn.email;
  } else if (acct.name && typeof acct.name === "string") {
    emailOrIdentity = acct.name;
  } else if (conn.account_display_name && typeof conn.account_display_name === "string") {
    emailOrIdentity = conn.account_display_name;
  }

  return {
    title: `${providerLabel} plan`,
    plan: planLabel,
    identity: emailOrIdentity,
    connected: true,
  };
}

function refreshPickerStatusRows() {
  const statusBox = $("#cmpMenuStatus");
  if (!statusBox) return;

  // Show status only for the currently selected provider
  const pid = activePickerProvider;
  if (!pid) { statusBox.innerHTML = ""; return; }

  const info = formatProviderPlanInfo(pid);
  if (!info.connected) {
    statusBox.innerHTML = `
      <div class="cmp-status-row" data-provider="${esc(pid)}">
        <span class="cmp-status-sub">${esc(info.title)}</span>
        <span class="cmp-chevron">›</span>
      </div>
    `;
  } else {
    statusBox.innerHTML = `
      <div class="cmp-status-row" data-provider="${esc(pid)}">
        <div class="cmp-status-label-group">
          <span class="cmp-status-label">${esc(info.title)}</span>
          <span class="cmp-status-sub">${esc(info.plan)}${info.identity ? ` · ${esc(info.identity)}` : ''}</span>
        </div>
        <span class="cmp-chevron">›</span>
      </div>
    `;
  }

  statusBox.querySelectorAll(".cmp-status-row").forEach((el) => {
    el.onclick = (e) => {
      e.stopPropagation();
      const pid = el.dataset.provider;
      openDrawer("model");
      toast(`Viewing ${pid} in Models & Accounts`);
    };
  });
}

async function refreshPickerPopover() {
  const agentId = current || (agents.length ? agents[0].id : null);
  if (!agentId) return;
  try {
    const data = await api(`/api/agents/${agentId}/model`);
    const isOverride = Boolean(data.is_override);

    const prov = data.configured_provider || data.provider || "cursor";
    activePickerProvider = prov;
    activePickerModel = isOverride ? (data.configured_model || null) : null;

    const pEntry = (MODEL_CATALOG || []).find((c) => c.id === prov);
    const pSpec = COMPOSER_PROVIDERS.find((x) => x.id === prov);
    const provName = pSpec ? pSpec.label : (pEntry ? pEntry.label : prov);
    if ($("#cmpSelectedProvLabel")) $("#cmpSelectedProvLabel").textContent = provName;

    let modelName = "Auto";
    if (isOverride && data.configured_model) {
      const mEntry = pEntry && (pEntry.models || []).find((m) => m.id === data.configured_model);
      modelName = mEntry ? mEntry.name : data.configured_model;
    }
    if ($("#cmpSelectedModelLabel")) $("#cmpSelectedModelLabel").textContent = modelName;

    const pillLabel = $("#cmpModelLabel");
    if (pillLabel) {
      pillLabel.textContent = isOverride ? (modelName !== "Auto" ? modelName : provName) : "Auto";
    }

    refreshPickerStatusRows();
  } catch (_) {}
}

function initComposerModelPicker() {
  const pill = $("#cmpModelPill");
  const menu = $("#cmpModelMenu");
  const provRow = $("#cmpProvRow");
  const modelRow = $("#cmpModelRow");
  const provFlyout = $("#cmpProvFlyout");
  const modelFlyout = $("#cmpModelFlyout");
  const wsPill = $("#cmpWorkspacePill");

  if (wsPill && !wsPill._wired) {
    wsPill._wired = true;
    wsPill.onclick = () => {
      openDrawer("sources");
    };
  }

  if (pill && menu && !pill._wired) {
    pill._wired = true;
    pill.onclick = (e) => {
      e.stopPropagation();
      const isHidden = menu.hidden;
      closeAllPickerFlyouts();
      if (isHidden) {
        refreshPickerPopover();
        menu.hidden = false;
        pill.classList.add("is-active");
      } else {
        menu.hidden = true;
        pill.classList.remove("is-active");
      }
    };
  }

  const headerChip = $("#agentModelChip");
  if (headerChip && !headerChip._pickerWired) {
    headerChip._pickerWired = true;
    headerChip.onclick = (e) => {
      e.stopPropagation();
      if (!menu) return;
      closeAllPickerFlyouts();
      refreshPickerPopover();
      menu.hidden = false;
      if (pill) pill.classList.add("is-active");
    };
  }

  if (provRow && !provRow._wired) {
    provRow._wired = true;
    provRow.onclick = (e) => {
      e.stopPropagation();
      if (!provFlyout) return;
      const isHidden = provFlyout.hidden;
      closeAllPickerFlyouts();
      if (isHidden) {
        renderProviderFlyout();
        provFlyout.hidden = false;
        provRow.classList.add("cmp-active");
      }
    };
  }

  if (modelRow && !modelRow._wired) {
    modelRow._wired = true;
    modelRow.onclick = (e) => {
      e.stopPropagation();
      if (!modelFlyout) return;
      const isHidden = modelFlyout.hidden;
      closeAllPickerFlyouts();
      if (isHidden) {
        renderModelFlyout();
        modelFlyout.hidden = false;
        modelRow.classList.add("cmp-active");
      }
    };
  }

  const claudeRow = $("#cmpClaudeStatusItem");
  if (claudeRow && !claudeRow._wired) {
    claudeRow._wired = true;
    claudeRow.onclick = (e) => {
      e.stopPropagation();
      openDrawer("model");
      const p = (MODEL_CATALOG || []).find((x) => x.id === "claude");
      if (!p || !p.ready) {
        toast("Opening Models drawer to sign in with Claude");
      }
    };
  }

  const gptRow = $("#cmpChatGptStatusItem");
  if (gptRow && !gptRow._wired) {
    gptRow._wired = true;
    gptRow.onclick = (e) => {
      e.stopPropagation();
      openDrawer("model");
      const p = (MODEL_CATALOG || []).find((x) => x.id === "openai");
      if (!p || !p.ready) {
        toast("Opening Models drawer to sign in with ChatGPT");
      }
    };
  }

  if (!document._cmpPickerDocWired) {
    document._cmpPickerDocWired = true;
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".cmp-model-picker-wrap") && !e.target.closest("#agentModelChip")) {
        if (menu) menu.hidden = true;
        closeAllPickerFlyouts();
        if (pill) pill.classList.remove("is-active");
      }
    });

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && menu && !menu.hidden) {
        menu.hidden = true;
        closeAllPickerFlyouts();
        if (pill) pill.classList.remove("is-active");
      }
    });
  }
}

async function updateAgentModelChip(agentId) {
  const chip = $("#agentModelChip");
  const cmpLabel = $("#cmpModelLabel");
  try {
    const data = await api(`/api/agents/${agentId}/model`);
    const labelEl = $("#agentModelLabel");
    const provName = data.configured_provider || data.provider || "cursor";
    const modelName = data.configured_model || "";

    const pEntry = (MODEL_CATALOG || []).find((c) => c.id === provName);
    const pSpec = COMPOSER_PROVIDERS.find((x) => x.id === provName);
    const provLabel = pSpec ? pSpec.label : (pEntry ? pEntry.label : provName);

    let display = "Auto";
    if (data.is_override) {
      if (modelName) {
        const mEntry = pEntry && (pEntry.models || []).find((m) => m.id === modelName);
        display = mEntry ? mEntry.name : modelName;
        if (mEntry && mEntry.locked) {
          display += ` (🔒 ${mEntry.plan_required || 'Locked'})`;
        }
      } else {
        display = provLabel;
      }
    }

    if (labelEl) labelEl.textContent = display;
    if (chip) {
      chip.classList.toggle("is-override", Boolean(data.is_override));
      chip.title = data.is_override
        ? `Dedicated model for this agent: ${provLabel} (${modelName || 'Auto'}). Click to change.`
        : `Using global default model: ${provLabel} (${modelName || 'Auto'}). Click to set custom.`;
    }

    // Update the composer pill smoothly
    if (cmpLabel) {
      cmpLabel.textContent = display;
    }

    // Update privacy lock icon
    const lockEl = $("#cmpPrivacyLock");
    if (lockEl) {
      const isLocal = pEntry && pEntry.locality === "local";
      lockEl.title = isLocal ? "On-device (Private)" : "Leaves your Mac";
      lockEl.style.color = isLocal ? "#10b981" : "#e06c75";
    }

    // Sync composer picker state
    activePickerProvider = data.configured_provider || data.provider || "cursor";
    activePickerModel = data.configured_model || null;
    const activeSpec = COMPOSER_PROVIDERS.find((x) => x.id === activePickerProvider);
    if ($("#cmpSelectedProvLabel")) {
      $("#cmpSelectedProvLabel").textContent = activeSpec ? activeSpec.label : (pEntry ? pEntry.label : activePickerProvider);
    }
    if ($("#cmpSelectedModelLabel")) {
      $("#cmpSelectedModelLabel").textContent = data.is_override ? (data.configured_model || "Auto") : "Auto";
    }

    refreshPickerStatusRows();
  } catch (_) {}
}

function openAgentModelModal(agentId) {
  const menu = $("#cmpModelMenu");
  const pill = $("#cmpModelPill");
  if (menu && pill) {
    refreshPickerPopover();
    menu.hidden = false;
    pill.classList.add("is-active");
    pill.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function loadAgentModelMatrix() {
  const matrix = $("#agentModelMatrix");
  if (!matrix || matrix.hidden) return;
  api("/api/agents").then((data) => {
    const list = data.agents || [];
    matrix.innerHTML = list.map((a) => {
      const oid = agentOrbId(a);
      const isOver = Boolean(a.model_provider);
      return `
        <div class="matrix-row">
          <div class="matrix-agent">
            <span class="orb orb-sm" style="${orbStyle(oid)}"></span>
            <div>
              <div class="matrix-nm">${esc(a.name)}</div>
              <div class="matrix-role">${esc(a.role || "")}</div>
            </div>
          </div>
          <div class="matrix-actions">
            <span class="pc-badge ${isOver ? 'ready' : 'local'}" style="font-size:10.5px">
              ${isOver ? esc(a.model_provider + (a.model_name ? ` · ${a.model_name}` : '')) : 'Default'}
            </span>
            <button class="tiny ghost matrix-btn" data-agent="${esc(a.id)}">Change</button>
          </div>
        </div>
      `;
    }).join("");

    matrix.querySelectorAll(".matrix-btn").forEach((btn) => {
      btn.onclick = () => openAgentModelModal(btn.dataset.agent);
    });
  });
}

function loadProviderCards() {
  const box = $("#providerCards");
  if (!box) return;

  const GROUPS = [
    {
      id: "openai",
      title: "OpenAI",
      subtitle: "Choose a ChatGPT subscription or OpenAI API key.",
      providers: ["openai"],
    },
    {
      id: "anthropic",
      title: "Anthropic",
      subtitle: "Choose a Claude subscription or Anthropic API key.",
      providers: ["claude"],
    },
    {
      id: "xai",
      title: "xAI",
      subtitle: "Sign in to Grok and use the models available to your account.",
      providers: ["xai"],
    },
    {
      id: "cursor",
      title: "Cursor",
      subtitle: "Use a Cursor account or API key. Model access follows your Cursor plan and team settings.",
      providers: ["cursor"],
    },
    {
      id: "gemini",
      title: "Google Gemini",
      subtitle: "Sign in with your Google account or provide a Gemini API key.",
      providers: ["gemini"],
    },
    {
      id: "other",
      title: "Other ways to run models",
      subtitle: "Free models, OpenRouter, and local Ollama models.",
      providers: ["deepseek", "openrouter", "ollama"],
    },
  ];

  box.innerHTML = GROUPS.map((g) => {
    return `
      <div class="ts-provider-group" id="grp_${g.id}">
        <div class="ts-provider-head">
          <h3 class="ts-provider-title">${esc(g.title)}</h3>
          <p class="ts-provider-sub">${esc(g.subtitle)}</p>
        </div>
        <div class="ts-group-boxes">
          ${g.providers.map((pid) => `<div id="pbox_${pid}" style="margin-bottom:8px"></div>`).join("")}
        </div>
      </div>
    `;
  }).join("");

  GROUPS.forEach((g) => {
    g.providers.forEach((pid) => {
      const el = $(`#pbox_${pid}`);
      if (el) renderProviderConnectBox(el, pid);
    });
  });
}

async function loadProviders() {
  try {
    const catData = await api("/api/models/catalog");
    if (catData && catData.catalog && catData.catalog.length) {
      MODEL_CATALOG = catData.catalog;
    }
  } catch (_) {}

  try {
    const d = await api("/api/providers");
    PROVIDERS = d.providers || [];
    // Sync readiness and connection metadata into catalog
    PROVIDERS.forEach((p) => {
      const entry = MODEL_CATALOG.find((c) => c.id === p.name);
      if (entry) {
        entry.ready = p.ready;
        entry.reason = p.reason;
        entry.connection = p.connection;
        entry.capabilities = p.capabilities;
        entry.detected_account = p.detected_account;
        entry.usage = p.usage;
        entry.plan = p.plan;
      }
    });

    const savedP = localStorage.getItem("lodestone_provider");
    const active = savedP || d.active || "claude";
    $("#provider").innerHTML = (MODEL_CATALOG || []).map((p) =>
      `<option value="${p.id}" ${p.id === active ? "selected" : ""}>${p.label}${p.ready ? " (Ready)" : " (not ready)"}</option>`).join("");
    $("#modelName").value = localStorage.getItem("lodestone_model") || "";
    applyModelHint();
    $("#provider").onchange = () => {
      localStorage.setItem("lodestone_provider", $("#provider").value);
      applyModelHint();
    };
    $("#modelName").onchange = () => localStorage.setItem("lodestone_model", $("#modelName").value.trim());

    // Enrichment model — independent of the agent model. Empty = "same as agent".
    const ep = $("#enrichProvider");
    if (ep) {
      const savedE = localStorage.getItem("lodestone_enrich_provider") || "";
      ep.innerHTML = `<option value="">same as agent model</option>` + (MODEL_CATALOG || []).map((p) =>
        `<option value="${p.id}" ${p.id === savedE ? "selected" : ""}>${p.label}${p.ready ? " (Ready)" : " (not ready)"}</option>`).join("");
      $("#enrichModelName").value = localStorage.getItem("lodestone_enrich_model") || "";
      ep.onchange = () => localStorage.setItem("lodestone_enrich_provider", ep.value);
      $("#enrichModelName").onchange = () => localStorage.setItem("lodestone_enrich_model", $("#enrichModelName").value.trim());
    }
  } catch (err) {
    console.error("loadProviders error", err);
  }

  loadEnrichCap();
  loadAgentModelMatrix();
  loadProviderCards();
  initComposerModelPicker();
  if (current) updateAgentModelChip(current);
}

// Which provider/model to use for enrichment: the dedicated one if set, else the
// agent model (so nothing breaks for users who never touch this).
function enrichModel() {
  const p = (localStorage.getItem("lodestone_enrich_provider") || "").trim();
  if (p) return { provider: p, model: (localStorage.getItem("lodestone_enrich_model") || "").trim() || null };
  return { provider: $("#provider").value, model: $("#modelName").value.trim() || null };
}

async function loadEnrichCap() {
  const inp = $("#enrichCap"); if (!inp) return;
  try {
    const c = await api("/api/brain/enrich/config");
    inp.value = c.cap;
    const note = $("#enrichCapNote");
    if (note) note.textContent = `${c.remaining} queued`;
  } catch (_) {}
  const btn = $("#enrichCapSave");
  if (btn && !btn._wired) {
    btn._wired = 1;
    btn.onclick = async () => {
      const cap = Math.max(0, parseInt(inp.value, 10) || 0);
      btn.disabled = true;
      try {
        const r = await api("/api/brain/enrich/config", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cap }) });
        const note = $("#enrichCapNote");
        if (note) note.textContent = `${r.remaining} queued`;
        toast(cap ? `Enriching recent ${cap} per bulk source` : "Enriching all items");
      } catch (e) { toast("couldn't save"); }
      btn.disabled = false;
    };
  }
}

async function selectAgent(id) {
  if (busy) { toast("finishing current reply…"); return; }
  current = id;
  const a = agents.find((x) => x.id === id) || { name: "—", role: "", tools: [] };
  const oid = agentOrbId(a);
  $("#agentName").textContent = a.name;
  $("#agentRole").textContent = a.role;
  const chOrb = $("#chOrb"); if (chOrb) chOrb.style.cssText = orbStyle(oid);
  const ctxOrb = $("#ctxOrb"); if (ctxOrb) ctxOrb.style.cssText = orbStyle(oid);
  if ($("#ctxAgentName")) $("#ctxAgentName").textContent = a.name;
  if ($("#ctxAgentRole")) $("#ctxAgentRole").textContent = a.role;
  if ($("#ctxAgentDesc")) $("#ctxAgentDesc").textContent = agentDesc(a);
  $("#input").placeholder = "Message " + a.name + "…";
  document.querySelectorAll(".agent").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  loadAgents();   // refresh the active dot in the rail
  updateAgentModelChip(id);
  const chip = $("#agentModelChip");
  if (chip && !chip._wired) {
    chip._wired = 1;
    chip.onclick = () => { if (current) openAgentModelModal(current); };
  }
  const { history } = await api(`/api/agents/${id}/history`);
  renderHistory(history);
}

function heroEmpty() {
  const a = agents.find((x) => x.id === current) || { name: "your agent" };
  const hr = new Date().getHours();
  const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const div = document.createElement("div");
  div.className = "hero-empty";
  div.innerHTML = `
    <div class="he-top">
      <span class="orb orb-xl" style="${orbStyle(agentOrbId(a))}"></span>
      <div>
        <h1 class="he-hi">${greet}.</h1>
        <p class="he-sub">Your second brain, always on your side. Ask ${esc(a.name)} anything — it already knows your world.</p>
      </div>
    </div>
    <div class="he-cards">
      <button class="he-card" data-q="Catch me up — what's new since yesterday?"><span class="hc-ic">${IC.message}</span><b>Catch me up</b><span>What's new since yesterday?</span></button>
      <button class="he-card" data-q="What should I focus on today? Show my open tasks."><span class="hc-ic">${IC.tasks}</span><b>Show my tasks</b><span>What should I focus on today?</span></button>
      <button class="he-card" data-fill="Find "><span class="hc-ic">${IC.search}</span><b>Find something</b><span>Search across my apps &amp; notes.</span></button>
      <button class="he-card" data-q="Help me plan my day and week."><span class="hc-ic">${IC.spark}</span><b>Help me plan</b><span>Plan my day / week.</span></button>
    </div>`;
  div.querySelectorAll(".he-card").forEach((c) => c.onclick = () => {
    if (c.dataset.fill) { $("#input").value = c.dataset.fill; $("#input").focus(); autoGrow(); }
    else send(c.dataset.q);
  });
  maybeEnrichTip(div);
  return div;
}

// Gentle, dismissible nudge: if memories are waiting to be enriched, tell the user
// enrichment sharpens answers and let them start it in one click. Hidden once the
// queue is drained or the user dismisses it.
async function maybeEnrichTip(div) {
  if (localStorage.getItem("lodestone_enrich_tip_off")) return;
  let cfg; try { cfg = await api("/api/brain/enrich/config"); } catch (_) { return; }
  const rem = cfg.remaining || 0;
  if (rem < 20) return;
  const tip = document.createElement("div");
  tip.className = "he-tip";
  tip.innerHTML = `<span class="het-ic">${IC.spark}</span>
    <span class="het-tx"><b>Sharpen your brain.</b> Enrich <b>${rem.toLocaleString()}</b> memories
    into people, projects &amp; facts for more precise answers — runs locally &amp; free.</span>
    <button class="het-go">Enrich</button><button class="het-x" title="Dismiss">✕</button>`;
  tip.querySelector(".het-go").onclick = () => { openBrainScreen(); setTimeout(() => { const b = $("#enrichBtn"); if (b && !b.classList.contains("running")) b.click(); }, 300); };
  tip.querySelector(".het-x").onclick = () => { localStorage.setItem("lodestone_enrich_tip_off", "1"); tip.remove(); };
  div.appendChild(tip);
}

function renderHistory(history) {
  const box = $("#messages");
  box.innerHTML = "";
  const msgs = history.filter((m) => m.role === "user" || m.role === "assistant");
  if (!msgs.length) { box.appendChild(heroEmpty()); return; }
  for (const m of msgs) addMsg(m.role, m.content);   // so history shows action cards too
  box.scrollTop = box.scrollHeight;
}

function parseActions(text) {
  const actions = [];
  const clean = text.replace(/<action\s+([^>]*?)>([\s\S]*?)<\/action>/gi, (m, attrs, inner) => {
    const a = { params: {} };
    let mm; const re = /(\w+)="([^"]*)"/g;
    while ((mm = re.exec(attrs))) { if (mm[1] === "type") a.type = mm[2]; else a.params[mm[1]] = mm[2]; }
    if (a.type === "send_email") a.params.body = inner.trim();
    else if (a.type === "create_event") a.params.description = inner.trim();
    else if (a.type === "set_reminder") a.params.message = inner.trim();
    else if (a.type === "create_routine") a.params.instruction = inner.trim();
    if (a.type) actions.push(a);
    return "";   // strip the tag from the visible text
  });
  return { clean: clean.trim(), actions };
}

function actionCard(a) {
  const p = a.params;
  let title, rows, verb = "send";
  const at = p.at || p.when;
  if (a.type === "send_email") {
    title = "Send email"; verb = at ? "schedule" : "send";
    rows = `<div class="ac-row"><b>To</b> ${esc(p.to || "")}</div>
       <div class="ac-row"><b>Subject</b> ${esc(p.subject || "")}</div>
       ${at ? `<div class="ac-row"><b>Send at</b> ${esc(at)}</div>` : ""}
       <div class="ac-body">${esc(p.body || "")}</div>`;
  } else if (a.type === "set_reminder") {
    title = "Set reminder"; verb = "set";
    rows = `<div class="ac-row"><b>Remind</b> ${esc(p.message || "")}</div>
       <div class="ac-row"><b>When</b> ${esc(p.at || p.when || "")}</div>`;
  } else if (a.type === "create_routine") {
    title = "Create automation"; verb = "create";
    const trig = p.trigger === "schedule" ? `every ${p.interval_min || 60} min` : "on every new email";
    rows = `<div class="ac-row"><b>Name</b> ${esc(p.name || "Automation")}</div>
       <div class="ac-row"><b>Runs</b> ${trig} · ${esc(p.agent || p.agent_id || "personal")}</div>
       <div class="ac-body">${esc(p.instruction || "")}</div>`;
  } else {
    title = "Create calendar event"; verb = "create";
    rows = `<div class="ac-row"><b>Title</b> ${esc(p.title || "")}</div>
       <div class="ac-row"><b>When</b> ${esc(p.start || "")}${p.end ? " → " + esc(p.end) : ""}</div>
       ${p.description ? `<div class="ac-body">${esc(p.description)}</div>` : ""}`;
  }
  const isEmail = a.type === "send_email";
  const el = document.createElement("div");
  el.className = "action-card";
  el.innerHTML = `<div class="ac-head">${title}<span class="ac-tag">needs your confirmation</span></div>
    ${rows}
    <div class="ac-actions"><button class="ac-confirm">Confirm & ${verb}</button>
    <button class="ac-cancel ghost">Cancel</button></div>
    <div class="ac-result"></div>`;
  el.querySelector(".ac-cancel").onclick = () => { el.querySelector(".ac-actions").innerHTML = "<span class='muted'>Cancelled</span>"; };
  el.querySelector(".ac-confirm").onclick = async () => {
    const btns = el.querySelector(".ac-actions"); btns.innerHTML = "<span class='muted'>Working…</span>";
    try {
      const r = await api("/api/actions/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: a.type, params: { ...p, agent_id: current } }) });
      const rr = el.querySelector(".ac-result");
      if (r.ok) { rr.innerHTML = `<span class="ac-ok">✓ ${esc(r.detail || "Done")}</span>`; loadReminders(); loadRoutines(); return; }
      rr.innerHTML = `<span class="ac-err">${esc(r.error || "Failed")}</span>`;
      if (r.reauth) {
        const b = document.createElement("button");
        b.className = "tiny"; b.textContent = "Reconnect Google"; b.style.marginTop = "8px";
        b.onclick = async () => { const x = await api("/api/google/reconnect", { method: "POST" }); toast(x.detail || "Opening browser…"); };
        rr.appendChild(document.createElement("br")); rr.appendChild(b);
      }
    } catch (e) { el.querySelector(".ac-result").innerHTML = `<span class="ac-err">${esc(String(e))}</span>`; }
  };
  return el;
}

function addMsg(role, text) {
  const box = $("#messages");
  const he = box.querySelector(".hero-empty"); if (he) he.remove();
  if (role === "assistant") {
    const { clean, actions } = parseActions(text);
    const el = document.createElement("div");
    el.className = "msg assistant";
    const oid = agentOrbId(agents.find((x) => x.id === current));
    el.innerHTML = `<span class="orb a-orb" style="${orbStyle(oid)}"></span><div class="a-body">${md(clean)}</div>`;
    box.appendChild(el);
    for (const a of actions) box.appendChild(actionCard(a));
    box.scrollTop = 1e9; return el;
  }
  const el = document.createElement("div");
  el.className = "msg " + role; el.textContent = text;
  box.appendChild(el); box.scrollTop = 1e9; return el;
}
function addTrace(steps) {
  if (!steps.length) return;
  const el = document.createElement("div"); el.className = "trace";
  el.innerHTML = steps.filter((s) => s.kind === "tool_call").map((s) => {
    const res = (steps.find((r) => r.kind === "tool_result" && r.name === s.name) || {}).result || "";
    return `<div class="step"><span class="tname">${s.name}</span>(${esc(JSON.stringify(s.arguments))})<span class="res">${esc(res.slice(0, 160))}</span></div>`;
  }).join("");
  $("#messages").appendChild(el); $("#messages").scrollTop = 1e9;
}

let busy = false;               // one turn at a time per the whole workspace
let controller = null;          // AbortController for the in-flight turn

function setBusy(on) {
  busy = on;
  $("#input").disabled = on;
  $("#send").textContent = on ? "Stop" : "Send";
  $("#send").classList.toggle("stopbtn", on);
  if (!on) { $("#input").focus(); autoGrow(); }
}

// Phrases + rough per-provider time estimates for the reply indicator.
const THINK_PHRASES = [
  "Recalling what I know about you…",
  "Searching your brain…",
  "Pulling in the right context…",
  "Connecting the dots…",
  "Composing a reply…",
];
const THINK_EST = { "claude-code": 18, ollama: 12, subscription: 15,
  anthropic: 8, openai: 8, openrouter: 9, mock: 1 };

function makeThinking(provider) {
  const est = THINK_EST[provider] || 12;
  const el = addMsg("assistant", "");
  el.classList.add("thinking");
  el.innerHTML =
    `<div class="think-row"><span class="think-dot"></span>
       <span class="think-msg">Thinking…</span><span class="think-time"></span></div>
     <div class="think-bar"><div class="think-fill"></div></div>`;
  const msgEl = el.querySelector(".think-msg");
  const timeEl = el.querySelector(".think-time");
  const fill = el.querySelector(".think-fill");
  const t0 = performance.now();
  let pi = -1;
  const tick = () => {
    const elapsed = (performance.now() - t0) / 1000;
    // asymptotic progress: approaches ~97% but never completes until the reply lands
    fill.style.width = Math.min(97, 100 * (1 - Math.exp(-elapsed / est))).toFixed(1) + "%";
    const remain = est - elapsed;
    timeEl.textContent = remain > 0.5 ? `~${Math.ceil(remain)}s` : "almost there…";
    const want = Math.min(THINK_PHRASES.length - 1, Math.floor(elapsed / 2.5));
    if (want !== pi) { pi = want; msgEl.textContent = THINK_PHRASES[pi]; }
  };
  tick();
  const timer = setInterval(tick, 150);
  return { el, done: () => { clearInterval(timer); el.remove(); } };
}

async function send(text) {
  if (busy) return;             // guard: ignore sends while a turn is running
  setBusy(true);
  controller = new AbortController();
  addMsg("user", text);
  const curAgent = agents.find((x) => x.id === current);
  const thinkProv = (curAgent && curAgent.model_provider) || $("#provider").value;
  const think = makeThinking(thinkProv);
  try {
    const res = await api(`/api/agents/${current}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
      signal: controller.signal,
    });
    think.done();
    addTrace(res.trace || []);
    addMsg("assistant", res.reply);
    loadBrain();
    loadTasks();       // an agent may have added/completed a task this turn
    loadReminders();   // …or set a reminder
  } catch (e) {
    think.done();
    if (controller && controller.signal.aborted) addMsg("assistant", "■ stopped");
    else addMsg("assistant", "△ " + e);
  }
  finally { controller = null; setBusy(false); }
}

function autoGrow() {
  const t = $("#input"); if (!t) return;
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 140) + "px";
}

async function loadBrain() {
  const s = await api("/api/brain/stats");
  $("#brainStats").innerHTML = `
    <div class="b"><div class="num">${s.total}</div><div class="lbl">memories</div></div>
    <div class="b"><div class="num">${s.graph.entities}</div><div class="lbl">entities</div></div>
    <div class="b"><div class="num">${s.graph.relations}</div><div class="lbl">facts</div></div>`;
  if ($("#ctxMem")) $("#ctxMem").textContent = s.total > 0 ? "On" : "Empty";
  if ($("#ctxEntities")) $("#ctxEntities").textContent = (s.graph.entities || 0).toLocaleString();
  const { entities } = await api("/api/brain/entities?limit=20");
  $("#entities").innerHTML = entities.length ? entities.map((e) =>
    `<div class="ent" data-entity="${e.id}" title="click for facts"><span class="etype ${e.type}">${e.type}</span> ${esc(e.name)} <span class="t">${e.mentions}×</span></div>`).join("")
    : `<div class="ent t">empty — add notes or sync a connector</div>`;
  document.querySelectorAll("[data-entity]").forEach((el) =>
    el.onclick = () => openEntity(el.dataset.entity));
  const { connectors } = await api("/api/connectors");
  CONNECTORS = connectors;
  if ($("#ctxSources")) $("#ctxSources").textContent = connectors.filter((c) => c.ready).length;
  const staleAfterMin = Math.max(120, (SYNC_INTERVAL_MIN || 30) * 4);
  $("#connectors").innerHTML = connectors.map((c) => {
    const ls = c.state?.last_sync ? new Date(c.state.last_sync) : null;
    const ageMin = ls ? (Date.now() - ls.getTime()) / 60000 : null;
    const stale = c.ready && ageMin !== null && ageMin > staleAfterMin;
    const last = ls ? ls.toLocaleDateString() : "";
    const dot = !c.ready ? "off" : stale ? "stale" : "ok";
    const sub = !c.ready ? (c.reason || "not configured")
      : !last ? "ready · not synced yet"
      : stale ? `stale · last ${last}` : `synced ${last}`;
    const sync = c.ready ? `<button class="tiny ghost" data-sync="${esc(c.name)}">sync</button>` : "";
    const setup = c.custom
      ? `<button class="tiny ghost" data-editapp="${esc(c.name)}">edit</button>`
      : (c.ready ? "" : `<button class="tiny" data-setup="${esc(c.name)}">setup</button>`);
    const del = c.custom ? `<button class="tiny ghost" data-delapp="${esc(c.name)}" title="remove">✕</button>` : "";
    return `<div class="conn" data-conn="${esc(c.name)}">
      <span class="conn-meta"><span class="dot ${dot}"></span>
        <span><span class="conn-name">${esc(c.label)}</span><span class="conn-sub">${esc(sub)}</span></span></span>
      <span style="display:flex;gap:4px">${sync}${setup}${del}</span></div>`;
  }).join("");
  document.querySelectorAll("[data-sync]").forEach((b) => b.onclick = () => syncConn(b.dataset.sync));
  document.querySelectorAll("[data-setup]").forEach((b) => b.onclick = () => connectorHelp(b.dataset.setup));
  document.querySelectorAll("[data-editapp]").forEach((b) => b.onclick = () =>
    customAppForm(CONNECTORS.find((x) => x.name === b.dataset.editapp)?.config));
  document.querySelectorAll("[data-delapp]").forEach((b) => b.onclick = async () => {
    const id = b.dataset.delapp.split(":")[1];
    if (!confirm("Remove this custom app? (synced records stay in the brain.)")) return;
    await api(`/api/custom-apps/${id}`, { method: "DELETE" });
    toast("custom app removed"); loadBrain();
  });
  loadSyncStatus();
  try { renderGoogleCard(await api("/api/google/status")); } catch (_) {}
}

// ── polished Google connect flow (local backend, Turnstone-grade UX) ────────
function renderGoogleCard(s) {
  const el = $("#googleCard");
  if (!el) return;
  if (!s.client_configured) { el.hidden = true; return; }
  el.hidden = false;
  if (s.connected) {
    const chips = (s.services || []).map((x) => `<span class="gchip">${esc(x)}</span>`).join("");
    el.className = "google-card connected";
    el.innerHTML =
      `<div class="gc-row"><span class="gc-ic">✓</span>
         <div class="gc-txt"><b>Google connected</b>
           <span class="gc-sub">${esc(s.account || "signed in")}</span></div>
         <button class="tiny ghost" id="gcDisconnect">Disconnect</button></div>
       <div class="gchips">${chips}</div>
       <div class="gc-note">Token stays on your Mac — not sent to any third party.</div>`;
    $("#gcDisconnect").onclick = disconnectGoogle;
  } else {
    el.className = "google-card";
    el.innerHTML =
      `<div class="gc-txt"><b>Connect Google</b>
         <span class="gc-sub">Gmail · Calendar · Drive — read-only</span></div>
       <button class="gsignin" id="gcConnect"><span class="g-logo">G</span>Sign in with Google</button>
       <div class="gc-note">One click. Token stays on your Mac.</div>`;
    $("#gcConnect").onclick = connectGoogle;
  }
}
async function connectGoogle() {
  const el = $("#googleCard");
  el.className = "google-card connecting";
  el.innerHTML =
    `<div class="gc-row"><span class="gc-spin"></span>
       <div class="gc-txt"><b>Waiting for approval…</b>
         <span class="gc-sub">Approve access in the browser window that opened.</span></div></div>
     <button class="tiny ghost" id="gcReopen">Reopen browser sign-in</button>`;
  const open = () => api("/api/google/reconnect", { method: "POST" }).catch(() => {});
  $("#gcReopen").onclick = open;
  await open();
  let tries = 0;
  const poll = setInterval(async () => {
    let g; try { g = await api("/api/google/status"); } catch { return; }
    if (g.connected) { clearInterval(poll); toast("Google connected ✓"); renderGoogleCard(g); loadBrain(); }
    else if (++tries > 60) { clearInterval(poll); renderGoogleCard(g); toast("Didn't finish — try again"); }
  }, 3000);
}
async function disconnectGoogle() {
  if (!confirm("Disconnect Google? You can reconnect anytime.")) return;
  await api("/api/google/disconnect", { method: "POST" });
  toast("Google disconnected");
  renderGoogleCard(await api("/api/google/status")); loadBrain();
}

let SYNC_INTERVAL_MIN = 30;
async function loadSyncStatus() {
  try {
    const s = await api("/api/sync/status");
    if (s.interval_minutes) SYNC_INTERVAL_MIN = s.interval_minutes;
    const last = s.last_run ? new Date(s.last_run).toLocaleTimeString() : "not yet";
    $("#syncStatus").textContent = s.syncing ? "syncing now…"
      : (s.enabled ? `auto every ${s.interval_minutes}m · last ${last}` : "auto-sync off");
    $("#syncAll").textContent = s.syncing ? "syncing…" : "sync all";
    $("#syncAll").disabled = !!s.syncing;
  } catch (_) {}
}
$("#syncAll").onclick = async () => {
  const r = await api("/api/sync/now", { method: "POST" });
  if (!r.started) { toast(r.reason || "already syncing"); return; }
  toast("syncing all connectors…");
  const poll = setInterval(async () => {
    const s = await api("/api/sync/status");
    loadSyncStatus();
    if (!s.syncing) { clearInterval(poll); toast("sync complete"); loadBrain(); }
  }, 3000);
};

async function syncConn(name) {
  if (name === "files") { openPicker(); return; }   // folder picker for local files
  const row = document.querySelector(`.conn[data-conn="${CSS.escape(name)}"]`);
  const subEl = row?.querySelector(".conn-sub");
  const dotEl = row?.querySelector(".dot");
  const btn = row?.querySelector(`[data-sync="${CSS.escape(name)}"]`);
  if (subEl) subEl.textContent = "syncing…";
  if (dotEl) { dotEl.className = "dot syncing"; }
  if (btn) btn.disabled = true;
  try {
    const r = await api(`/api/connectors/${name}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ params: {} }) });
    if (r.errors?.length) {
      toast(`${name}: ${r.errors[0]}`);
      if (subEl) subEl.textContent = "error — see setup";
      if (dotEl) dotEl.className = "dot off";
    } else {
      toast(`${name}: +${r.added} added${r.skipped ? ` · ${r.skipped} skipped` : ""}`);
      loadBrain();          // re-render with fresh state (green dot, "synced today")
    }
  } catch (e) {
    toast(String(e));
    if (subEl) subEl.textContent = "sync failed";
    if (dotEl) dotEl.className = "dot off";
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── brain detail modal (entity facts / memory search) ──────────────────────
function openBrainModal(title, bodyHtml) {
  $("#bmTitle").textContent = title;
  $("#bmBody").innerHTML = bodyHtml;
  $("#brainModal").hidden = false;
}
$("#bmClose").onclick = () => $("#brainModal").hidden = true;
$("#brainModal").onclick = (e) => { if (e.target.id === "brainModal") $("#brainModal").hidden = true; };

async function openEntity(id) {
  const d = await api(`/api/brain/entities/${id}/facts`);
  const e = d.entity;
  const facts = d.facts.length
    ? d.facts.map((f) => `<li>${esc(f)}</li>`).join("")
    : "<li class='t'>no facts recorded</li>";
  openBrainModal(`${e.name}`,
    `<div class="bm-sub"><span class="etype ${e.type}">${e.type}</span> · ${e.mentions} mentions</div>
     ${e.summary ? `<p>${esc(e.summary)}</p>` : ""}
     <ul class="bm-facts">${facts}</ul>`);
}

async function searchBrain(q) {
  const d = await api(`/api/brain/search?q=${encodeURIComponent(q)}`);
  if (!d.memories.length) { openBrainModal(`Search: "${q}"`, `<p class="t">No matches.</p>`); return; }
  const rows = d.memories.map((m) =>
    `<div class="bm-mem">
       <div class="bm-mem-head"><b>${esc(m.title || m.source)}</b>
         <span><span class="bm-score">${m.score}</span>
         <button class="tiny ghost" data-delmem="${m.id}">✕</button></span></div>
       <div class="bm-mem-body">${esc(m.text)}</div>
     </div>`).join("");
  openBrainModal(`Search: "${q}"`, rows);
  document.querySelectorAll("[data-delmem]").forEach((b) => b.onclick = async () => {
    await api(`/api/memories/${b.dataset.delmem}`, { method: "DELETE" });
    toast("Deleted"); b.closest(".bm-mem").remove(); loadBrain();
  });
}
$("#brainSearch").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) searchBrain(e.target.value.trim());
});

const CONNECTOR_HELP = {
  gmail: `<p>Read-only access to your Gmail.</p><ol>
    <li>In <b>Google Cloud Console</b> → APIs & Services → Credentials, create an
        <b>OAuth client ID</b> of type <b>Desktop app</b>.</li>
    <li>Download the <code>client_secret.json</code>.</li>
    <li>Set <code>GOOGLE_CLIENT_SECRETS</code> to its path, or drop it at
        <code>~/Library/Lodestone/google_client_secret.json</code>.</li>
    <li>Run a sync — a browser opens once to authorize (read-only).</li></ol>`,
  gdrive: `<p>Read-only access to your Google Drive (Docs, text, PDFs).</p>
    <p>Uses the <b>same Google OAuth Desktop client</b> as Gmail — set it up once
    (see the Gmail setup) and Drive works too.</p>`,
  gcal: `<p>Read-only access to your Google Calendar events.</p>
    <p>Uses the <b>same Google OAuth Desktop client</b> as Gmail — set it up once
    (see the Gmail setup). Then re-authorize once so Calendar scope is granted.</p>`,
  apple_mail: `<p>Reads mail straight off your Mac — <b>no Google sign-in</b>.
    Works if you have your account in the <b>Mail app</b>.</p><ol>
    <li>Add your email account in <b>Mail</b> (if not already).</li>
    <li><b>System Settings → Privacy & Security → Full Disk Access</b> → add your
        terminal / Lodestone → enable.</li>
    <li>Restart Lodestone, then click sync.</li></ol>`,
  apple_calendar: `<p>Reads events off your Mac — <b>no sign-in</b>. Works with any
    calendar in the <b>Calendar app</b>.</p><ol>
    <li>Enable <b>Full Disk Access</b> for your terminal / Lodestone.</li>
    <li>Restart Lodestone, then click sync.</li></ol>`,
  imessage: `<p>Reads your local iMessages (fully on-device, no cloud).</p><ol>
    <li>Open <b>System Settings → Privacy & Security → Full Disk Access</b>.</li>
    <li>Add your <b>Terminal</b> (or whatever runs Lodestone) and enable it.</li>
    <li>Restart Lodestone, then click sync.</li></ol>
    <p class="t">macOS only. Lodestone only reads, never sends.</p>`,
  notion: `Read-only access to the Notion pages you share with an integration.`,
  linear: `Read-only access to your Linear issues (status, priority, team).`,
  github: `Read-only access to the GitHub issues & PRs you're involved in.`,
};
function connectorHelp(name) {
  const c = CONNECTORS.find((x) => x.name === name);
  const f = c?.secret_field;
  if (f) {
    // Connectors that authenticate with a single pasted token: show steps +
    // an in-app field (no .env editing, no restart needed).
    const steps = (f.steps || []).map((s) => `<li>${s}</li>`).join("");
    const link = f.help_url
      ? `<p style="margin:6px 0 12px"><a href="${f.help_url}" target="_blank" rel="noopener">Open ${c.label} to get your key →</a></p>` : "";
    openBrainModal(`Connect ${c.label}`,
      `<p>${CONNECTOR_HELP[name] || ""}</p>
       ${steps ? `<ol>${steps}</ol>` : ""}${link}
       <label class="t" style="display:block;margin-bottom:4px">${esc(f.label)}</label>
       <div style="display:flex;gap:8px">
         <input id="secretInput" type="password" autocomplete="off" spellcheck="false"
                placeholder="${esc(f.placeholder || "")}"
                style="flex:1;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font-family:monospace" />
         <button id="secretSave" class="tiny">Save</button>
       </div>
       <p class="t" style="margin-top:8px">Stored locally on your Mac only
         (<code>~/Library/Lodestone/secrets.json</code>) — never uploaded.</p>`);
    const input = $("#secretInput");
    input.focus();
    $("#secretSave").onclick = async () => {
      const value = input.value.trim();
      if (!value) { toast("paste your key first"); return; }
      $("#secretSave").disabled = true; $("#secretSave").textContent = "Saving…";
      try {
        const r = await api(`/api/connectors/${name}/secret`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value }) });
        if (r.ready) {
          toast(`${c.label} connected ✓ — syncing…`);
          $("#brainModal").hidden = true;
          await syncConn(name);
        } else {
          toast(r.reason || "saved, but not ready yet");
        }
        loadBrain();
      } catch (e) { toast(String(e)); }
      finally { $("#secretSave").disabled = false; $("#secretSave").textContent = "Save"; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#secretSave").click(); });
    return;
  }
  openBrainModal(`Set up ${name}`, (CONNECTOR_HELP[name] || "<p>No setup needed.</p>")
    + `<p class="t" style="margin-top:10px">Add the value to your <code>.env</code> and restart Lodestone.</p>`);
}

// ── custom API app: connect any REST app, no code ──────────────────────────
function customAppForm(app) {
  app = app || {};
  const row = (label, id, val, ph) =>
    `<label class="t" style="display:block;margin:8px 0 3px">${label}</label>
     <input id="${id}" value="${esc(val || "")}" placeholder="${esc(ph || "")}" spellcheck="false"
       style="width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)" />`;
  const at = app.auth_type || "none";
  const opt = (v, t) => `<option value="${v}"${at === v ? " selected" : ""}>${t}</option>`;
  openBrainModal(app.id ? `Edit ${app.name}` : "Connect a custom app",
    `<p class="t">Point Lodestone at any REST API that returns JSON. It fetches the
       endpoint and adds each record to your brain. Stays on your Mac.</p>
     ${row("App name", "ca_name", app.name, "My CRM")}
     ${row("Base URL", "ca_base", app.base_url, "https://api.myapp.com/v1")}
     ${row("Endpoint", "ca_ep", app.endpoint, "/contacts")}
     <label class="t" style="display:block;margin:8px 0 3px">Auth</label>
     <select id="ca_auth" style="width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)">
       ${opt("none", "None")}${opt("bearer", "Bearer token")}${opt("header", "Custom header")}${opt("query", "Query parameter")}</select>
     ${row("Header / param name (for custom header or query)", "ca_authname", app.auth_name, "X-API-Key")}
     ${row("Token (leave blank to keep current)", "ca_token", "", "•••••••• stored locally, chmod 600")}
     <hr style="border:none;border-top:1px solid var(--line);margin:12px 0">
     <p class="t">Map the JSON (dot-paths, e.g. <code>data.results</code>):</p>
     ${row("Items path — where the list lives", "ca_items", app.items_path, "data.results")}
     ${row("Title field", "ca_title", app.title_field, "name")}
     ${row("Body field", "ca_body", app.body_field, "notes")}
     <div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end">
       <button id="ca_save" class="tiny">${app.id ? "Save changes" : "Save & sync"}</button></div>`);
  $("#ca_name").focus();
  $("#ca_save").onclick = async () => {
    const payload = {
      id: app.id || null,
      name: $("#ca_name").value.trim() || "Custom app",
      base_url: $("#ca_base").value.trim(),
      endpoint: $("#ca_ep").value.trim(),
      auth_type: $("#ca_auth").value,
      auth_name: $("#ca_authname").value.trim(),
      items_path: $("#ca_items").value.trim(),
      title_field: $("#ca_title").value.trim(),
      body_field: $("#ca_body").value.trim(),
    };
    const tok = $("#ca_token").value.trim();
    if (tok) payload.token = tok;
    if (!payload.base_url) { toast("base URL is required"); return; }
    $("#ca_save").disabled = true; $("#ca_save").textContent = "Saving…";
    try {
      const r = await api("/api/custom-apps", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload) });
      $("#brainModal").hidden = true;
      toast("custom app saved — syncing…");
      await syncConn(r.name);
      loadBrain();
    } catch (e) { toast(String(e)); $("#ca_save").disabled = false; $("#ca_save").textContent = "Save"; }
  };
}
$("#addCustomApp").onclick = () => customAppForm();

// ── tasks ────────────────────────────────────────────────────────────────
function dueLabel(iso) {
  if (!iso) return { text: "", cls: "" };
  const today = new Date().toISOString().slice(0, 10);
  const d = new Date(iso + "T00:00:00");
  const nice = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  if (iso < today) return { text: "overdue · " + nice, cls: "over" };
  if (iso === today) return { text: "today", cls: "today" };
  return { text: nice, cls: "" };
}

async function loadTasks() {
  const d = await api("/api/tasks");
  const n = d.stats.today, o = d.stats.overdue;
  $("#taskCount").textContent =
    d.tasks.length ? `· ${n} today${o ? ", " + o + " overdue" : ""}` : "";
  if (!d.tasks.length) {
    $("#taskList").innerHTML = `<div class="tasks-empty">No open tasks. Add one, or ask an agent.</div>`;
    return;
  }
  $("#taskList").innerHTML = d.tasks.map((t) => {
    const due = dueLabel(t.due);
    return `<div class="task">
      <span class="check" data-done="${t.id}">✓</span>
      <div class="body">
        <div class="ttl">${esc(t.title)}</div>
        ${due.text ? `<div class="due ${due.cls}">${due.text}</div>` : ""}
      </div>
      <span class="del" data-del-task="${t.id}">✕</span>
    </div>`;
  }).join("");
  document.querySelectorAll("[data-done]").forEach((el) => el.onclick = async () => {
    await api(`/api/tasks/${el.dataset.done}/complete`, { method: "POST" });
    toast("Done ✓"); loadTasks();
  });
  document.querySelectorAll("[data-del-task]").forEach((el) => el.onclick = async () => {
    await api(`/api/tasks/${el.dataset.delTask}`, { method: "DELETE" });
    loadTasks();
  });
}

async function loadReminders() {
  try {
    const { reminders } = await api("/api/reminders");
    $("#reminderWrap").hidden = reminders.length === 0;
    $("#reminderList").innerHTML = reminders.map((r) => {
      const when = new Date(r.fire_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      return `<div class="task"><div class="body"><div class="ttl">${esc(r.label || r.message)}</div>
        <div class="due today">${esc(when)}${r.agent_id ? " · " + esc(r.agent_id) : ""}</div></div>
        <span class="del" data-del-rem="${r.id}">✕</span></div>`;
    }).join("");
    document.querySelectorAll("[data-del-rem]").forEach((b) => b.onclick = async () => {
      await api(`/api/reminders/${b.dataset.delRem}`, { method: "DELETE" });
      toast("Reminder removed"); loadReminders();
    });
  } catch (_) {}
}

async function addTask() {
  const title = $("#taskInput").value.trim();
  if (!title) return;
  await api("/api/tasks", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  $("#taskInput").value = "";
  toast("Task added"); loadTasks();
}
$("#taskAdd").onclick = addTask;
$("#taskInput").addEventListener("keydown", (e) => { if (e.key === "Enter") addTask(); });

// ── folder picker ──────────────────────────────────────────────────────────
let pickPath = null;
async function openPicker(path) {
  const d = await api("/api/fs/browse" + (path ? `?path=${encodeURIComponent(path)}` : ""));
  pickPath = d.path;
  $("#picker").hidden = false;
  $("#pickPath").textContent = d.path;
  $("#pickInfo").textContent = d.ingestible_here
    ? `${d.ingestible_here} ingestible file(s) directly here` : "no text files directly here (subfolders may still have them)";
  let rows = "";
  if (d.parent) rows += `<div class="pick-row up" data-go="${esc(d.parent)}">⤴  ..</div>`;
  rows += d.dirs.map((name) => `<div class="pick-row" data-go="${esc(d.path.replace(/\/$/, "") + "/" + name)}">${esc(name)}</div>`).join("");
  $("#pickList").innerHTML = rows || `<div class="pick-row up">(no subfolders)</div>`;
  document.querySelectorAll("#pickList [data-go]").forEach((el) => el.onclick = () => openPicker(el.dataset.go));
}
$("#pickClose").onclick = () => $("#picker").hidden = true;
$("#pickIngest").onclick = async () => {
  $("#picker").hidden = true;
  toast(`ingesting ${pickPath.split("/").pop()}…`);
  try {
    const r = await api(`/api/connectors/files/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params: { path: pickPath } }) });
    toast(r.errors?.length ? `files: ${r.errors[0]}` : `files: +${r.added} added from ${r.detail}`);
    loadBrain();
  } catch (e) { toast(String(e)); }
};

$("#composer").onsubmit = (e) => {
  e.preventDefault();
  if (busy) { if (controller) controller.abort(); return; }   // Stop
  const v = $("#input").value.trim();
  if (v && current) { $("#input").value = ""; autoGrow(); send(v); }
};
$("#input").addEventListener("input", autoGrow);
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#clearBtn").onclick = async () => { await api(`/api/agents/${current}/clear`, { method: "POST" }); selectAgent(current); toast("chat cleared"); };
$("#ingestBtn").onclick = async () => {
  const t = $("#ingestText").value.trim(); if (!t) return;
  await api("/api/brain/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) });
  $("#ingestText").value = ""; toast("added to brain"); loadBrain();
};

// ── automations / routines ─────────────────────────────────────────────────
async function loadRoutines() {
  try {
    const { routines } = await api("/api/routines");
    $("#routineList").innerHTML = routines.length ? routines.map((r) => {
      const trig = r.trigger === "new_email" ? "on new email" : `every ${r.interval_min}m`;
      return `<div class="task"><div class="body">
        <div class="ttl">${esc(r.name)} ${r.enabled ? "" : "<span class='t'>(off)</span>"}</div>
        <div class="due">${trig} · ${esc(r.agent_id)}</div></div>
        <span><span class="check" data-toggle-r="${r.id}" data-on="${r.enabled}" title="${r.enabled ? "disable" : "enable"}">${r.enabled ? "‖" : "▶"}</span>
        <span class="del" data-del-r="${r.id}">✕</span></span></div>`;
    }).join("") : `<div class="tasks-empty">No automations yet.</div>`;
    document.querySelectorAll("[data-toggle-r]").forEach((b) => b.onclick = async () => {
      await api(`/api/routines/${b.dataset.toggleR}/toggle?on=${b.dataset.on !== "1"}`, { method: "POST" });
      loadRoutines();
    });
    document.querySelectorAll("[data-del-r]").forEach((b) => b.onclick = async () => {
      await api(`/api/routines/${b.dataset.delR}`, { method: "DELETE" }); toast("Automation removed"); loadRoutines();
    });
  } catch (_) {}
}
$("#newRoutineBtn").onclick = async () => {
  const { agents } = await api("/api/agents");
  $("#rmAgent").innerHTML = agents.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  $("#rmName").value = ""; $("#rmInstruction").value = ""; $("#rmInterval").value = "60";
  $("#routineModal").hidden = false;
};
$("#rmTrigger").onchange = () => { $("#rmIntervalWrap").hidden = $("#rmTrigger").value !== "schedule"; };
$("#rmClose").onclick = () => $("#routineModal").hidden = true;
$("#rmCreate").onclick = async () => {
  const name = $("#rmName").value.trim(), instruction = $("#rmInstruction").value.trim();
  if (!name || !instruction) { toast("Name & instruction required"); return; }
  await api("/api/routines", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, agent_id: $("#rmAgent").value, trigger: $("#rmTrigger").value,
      instruction, interval_min: parseInt($("#rmInterval").value) || 60 }) });
  $("#routineModal").hidden = true; toast("Automation created"); loadRoutines();
};

// ── create custom agent ─────────────────────────────────────────────────
async function openAgentModal() {
  const { tools } = await api("/api/agents/tools");
  $("#amTools").innerHTML = tools.map((t) =>
    `<label class="am-tool"><input type="checkbox" value="${t.name}" ${["search_brain", "remember", "web_search"].includes(t.name) ? "checked" : ""}/> ${t.name}</label>`).join("");
  $("#amName").value = ""; $("#amRole").value = ""; $("#amPrompt").value = "";
  $("#agentModal").hidden = false;
}
$("#newAgentBtn").onclick = openAgentModal;
$("#amClose").onclick = () => $("#agentModal").hidden = true;
$("#amCreate").onclick = async () => {
  const name = $("#amName").value.trim();
  if (!name) { toast("Name required"); return; }
  const chosen = [...document.querySelectorAll("#amTools input:checked")].map((c) => c.value);
  const a = await api("/api/agents/custom", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role: $("#amRole").value.trim(),
      system_prompt: $("#amPrompt").value.trim(), tools: chosen }) });
  $("#agentModal").hidden = true; toast("Agent created");
  await loadAgents(); selectAgent(a.id);
};

// ── onboarding ───────────────────────────────────────────────────────────
function openOnboard() { $("#onboard").hidden = false; }
function closeOnboard() {
  $("#onboard").hidden = true;
  localStorage.setItem("lodestone_onboarded", "1");
}
function flashConnectors() {
  const el = $("#connectors");
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
}
$("#obSkip").onclick = closeOnboard;
$("#obDone").onclick = closeOnboard;
$("#obGoogle").onclick = () => { closeOnboard(); flashConnectors(); connectGoogle(); };
$("#obLocal").onclick = () => { closeOnboard(); flashConnectors();
  toast("Pick Files, Apple Mail, Calendar or iMessage below → click setup"); };
$("#obApps").onclick = () => { closeOnboard(); flashConnectors();
  toast("Notion · Linear · GitHub — or + Connect a custom app"); };
$("#obFact").onclick = () => { closeOnboard(); $("#ingestText").focus();
  $("#ingestText").scrollIntoView({ behavior: "smooth" }); };
$("#helpBtn").onclick = openOnboard;

// ── brain export / import (you own your data) ──────────────────────────────
$("#brainExport").onclick = async () => {
  try {
    const r = await fetch("/api/brain/export");
    if (!r.ok) throw new Error("export failed");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `lodestone-brain-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    toast("Brain exported ✓");
  } catch (e) { toast(String(e)); }
};
$("#brainImport").onclick = () => $("#brainImportFile").click();
$("#brainImportFile").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const r = await api("/api/brain/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data) });
    toast(`Imported ${r.added} memories${r.skipped ? ` · ${r.skipped} already had` : ""}`);
    loadBrain();
  } catch (err) { toast("Import failed — is it a Lodestone backup?"); }
  finally { e.target.value = ""; }
};

async function maybeOnboard() {
  // Onboarded state lives on the SERVER (survives the desktop app's per-launch
  // port, which resets localStorage). Only a genuine first run goes to onboarding.
  try {
    const s = await api("/api/onboarded");
    if (s.onboarded) return false;
  } catch (_) {}
  if (localStorage.getItem("lodestone_onboarded")) return false;   // legacy fallback
  window.location.href = "/onboarding";
  return true;
}

// ── first entry: meet + name your lead agent, who then teaches the app ──────
async function maybeWelcome() {
  if (!localStorage.getItem("lodestone_onboarded")) return;
  if (localStorage.getItem("lodestone_lead_agent")) return;   // already have a lead
  const wrap = $("#welcome"); if (!wrap) return;
  wrap.hidden = false;
  const inp = $("#wName"); inp.focus(); inp.select();
  const go = () => createLead(inp.value.trim());
  $("#wCreate").onclick = go;
  inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
  $("#wSkip").onclick = () => { wrap.hidden = true; localStorage.setItem("lodestone_lead_agent", "skipped"); };
}
async function createLead(name) {
  name = (name || "Atlas").trim() || "Atlas";
  const btn = $("#wCreate"), note = $("#wNote");
  btn.disabled = true; btn.textContent = "Creating…"; note.textContent = `Building ${name} from your brain…`;
  try {
    const r = await api("/api/agents/lead", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }) });
    localStorage.setItem("lodestone_lead_agent", r.id);
    $("#welcome").hidden = true;
    await loadAgents();
    await selectAgent(r.id);
    agentWelcome(r.id);           // the agent introduces itself + teaches the app
  } catch (e) {
    btn.disabled = false; btn.textContent = "Create →"; toast(String(e));
    note.textContent = "Couldn't create the agent — try again.";
  }
}
async function agentWelcome(id) {
  if (busy) return;
  setBusy(true);
  const think = makeThinking($("#provider").value);
  try {
    const res = await api(`/api/agents/${id}/welcome`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "welcome", provider: $("#provider").value,
        model: $("#modelName").value.trim() || null }) });
    think.done();
    addMsg("assistant", res.reply);
  } catch (e) { think.done(); addMsg("assistant", "△ " + e); }
  finally { setBusy(false); }
}

// ── live brain-building status ─────────────────────────────────────────────
// Sync started in onboarding keeps running here; this pill shows how the brain
// is filling in real time. Click to kick a fresh sync.
let _wasSyncing = false;
async function updateBrainStatus() {
  const el = $("#brainStatus");
  if (!el) return;
  try {
    const [s, st] = await Promise.all([
      api("/api/sync/status"), api("/api/brain/stats"),
    ]);
    const mem = (st.total || 0).toLocaleString();
    const ent = (st.graph?.entities || 0).toLocaleString();
    if (s.syncing) {
      el.classList.add("syncing");
      el.innerHTML = `<span class="bs-dot"></span>Building your brain… <b>${mem}</b> memories`;
    } else {
      el.classList.remove("syncing");
      el.innerHTML = `<span class="bs-dot"></span>Brain ready · <b>${mem}</b> memories · <b>${ent}</b> entities`;
      if (_wasSyncing) loadBrain();   // refresh panels when a sync just finished
    }
    _wasSyncing = s.syncing;
  } catch (_) {}
}
// clicking the header status (or the sidebar Brain nav) opens the full brain screen
{ const el = $("#brainStatus"); if (el) el.onclick = () => openBrainScreen(); }

// ── full-screen "Your Brain" view: live neural viz + real building status ────
let _bsPoll = null, _bsRaf = null, _bsNodes = null, _bsRot = 0, _bsDensity = 0.15;
let _bsVisible = 520, _bsVisTarget = 520;   // how many nodes light up — grows with entities
// mouse interaction state for the brain viz
let _bsMX = 0, _bsMY = 0, _bsTMX = 0, _bsTMY = 0;       // eased vs target parallax
let _bsHoverX = -9999, _bsHoverY = -9999;               // cursor in canvas px
let _bsDrag = false, _bsDragRot = 0, _bsSpin = 1, _bsLastX = 0, _bsWired = false;
function _bsWire() {
  if (_bsWired) return; _bsWired = true;
  const cv = $("#bsCanvas"); if (!cv) return;
  cv.style.cursor = "grab";
  cv.addEventListener("pointermove", (e) => {
    const r = cv.getBoundingClientRect();
    _bsHoverX = e.clientX - r.left; _bsHoverY = e.clientY - r.top;
    _bsTMX = (_bsHoverX / r.width) * 2 - 1; _bsTMY = (_bsHoverY / r.height) * 2 - 1;
    if (_bsDrag) { _bsDragRot += (e.clientX - _bsLastX) * 0.006; _bsLastX = e.clientX; }
  });
  cv.addEventListener("pointerleave", () => { _bsHoverX = -9999; _bsHoverY = -9999; _bsTMX = 0; _bsTMY = 0; });
  cv.addEventListener("pointerdown", (e) => { _bsDrag = true; _bsLastX = e.clientX; _bsSpin = 0.15; cv.style.cursor = "grabbing"; try { cv.setPointerCapture(e.pointerId); } catch (_) {} });
  const end = () => { _bsDrag = false; _bsSpin = 1; cv.style.cursor = "grab"; };
  cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
}
function _bsBuildNodes() {
  // a pool of points on a jittered sphere → reads as a neural cluster. We render a
  // growing slice of it (_bsVisible) so the cloud visibly fills in as the knowledge
  // graph grows (more entities → more nodes light up during enrichment).
  const N = 1100, pts = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
    const jit = 0.12;
    pts.push({ x: Math.cos(th) * r + (Math.random() - 0.5) * jit, y: y + (Math.random() - 0.5) * jit,
      z: Math.sin(th) * r + (Math.random() - 0.5) * jit, p: Math.random() * 6.28 });
  }
  _bsNodes = pts;
}
function _bsDraw() {
  const cv = $("#bsCanvas"); if (!cv || $("#brainScreen").hidden) return;
  const dpr = Math.min(devicePixelRatio || 1, 2), W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  _bsMX += (_bsTMX - _bsMX) * 0.06; _bsMY += (_bsTMY - _bsMY) * 0.06;   // ease parallax
  _bsRot += 0.0016 * _bsSpin;
  // centre the sphere in the space to the right of the tools panel
  const cx = Math.min(W / 2 + 180, W - 60), cy = H * 0.46, R = Math.min(W * 0.5, H) * 0.34;
  // rotation = auto-spin + drag + mouse parallax; tilt up/down with the cursor
  const ay = _bsRot + _bsDragRot + _bsMX * 0.5, tilt = -_bsMY * 0.4;
  const sy = Math.sin(ay), cyr = Math.cos(ay), st = Math.sin(tilt), ct = Math.cos(tilt), t = Date.now() / 1000;
  const bright = 0.5 + 0.5 * _bsDensity;   // fuller/brighter as the brain grows
  _bsVisible += (_bsVisTarget - _bsVisible) * 0.05;   // ease node count toward target
  const vis = Math.max(60, Math.min(_bsNodes.length, Math.round(_bsVisible)));
  const HOV = 130, proj = [];
  for (let i = 0; i < vis; i++) {   // render a growing slice as the graph fills in
    const n = _bsNodes[i];
    const x1 = n.x * cyr + n.z * sy, z1 = -n.x * sy + n.z * cyr, y1 = n.y;
    const y2 = y1 * ct - z1 * st, z2 = y1 * st + z1 * ct;
    const sx = cx + x1 * R, sYy = cy - y2 * R, depth = (z2 + 1) / 2;
    const hd = Math.hypot(sx - _bsHoverX, sYy - _bsHoverY);
    proj.push({ sx, sy: sYy, depth, p: n.p, near: hd < HOV ? 1 - hd / HOV : 0 });
  }
  // synapse links between nearby points (brighter near the cursor)
  ctx.lineWidth = 0.6;
  for (let i = 0; i < proj.length; i += 1) {
    for (let j = i + 1; j < Math.min(i + 8, proj.length); j++) {
      const dx = proj[i].sx - proj[j].sx, dy = proj[i].sy - proj[j].sy, d = dx * dx + dy * dy;
      const nearBoost = Math.max(proj[i].near, proj[j].near);
      if (d < (52 + nearBoost * 40) * (52 + nearBoost * 40) && (proj[i].depth > 0.3 || nearBoost > 0)) {
        const la = 0.04 + 0.08 * proj[i].depth * bright + nearBoost * 0.35;
        ctx.strokeStyle = `rgba(${120 + nearBoost * 70 | 0},${160 + nearBoost * 40 | 0},255,${la.toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(proj[i].sx, proj[i].sy); ctx.lineTo(proj[j].sx, proj[j].sy); ctx.stroke();
      }
    }
  }
  // probe lines from the cursor to the nodes it's hovering
  if (_bsHoverX > -9000) {
    for (const p of proj) {
      if (p.near > 0.15) {
        ctx.strokeStyle = `rgba(150,190,255,${(p.near * 0.4).toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(_bsHoverX, _bsHoverY); ctx.lineTo(p.sx, p.sy); ctx.stroke();
      }
    }
  }
  for (const p of proj) {
    const pulse = 0.5 + 0.5 * Math.sin(t * 1.5 + p.p);
    const a = Math.min(1, (0.22 + 0.62 * p.depth) * (0.6 + 0.4 * pulse) * bright + p.near * 0.6);
    const rad = 0.7 + 1.8 * p.depth + p.near * 2.4;
    const g = 195 + 40 * p.depth + p.near * 20;
    ctx.fillStyle = `rgba(${170 + 60 * p.depth + p.near * 15 | 0},${g | 0},255,${a.toFixed(3)})`;
    ctx.beginPath(); ctx.arc(p.sx, p.sy, rad, 0, 6.283); ctx.fill();
  }
  _bsRaf = requestAnimationFrame(_bsDraw);
}
async function _bsRefresh() {
  try {
    const [s, st] = await Promise.all([api("/api/sync/status"), api("/api/brain/stats")]);
    const mem = st.total || 0, ent = st.graph?.entities || 0, rel = st.graph?.relations || 0;
    $("#bsMem").textContent = mem.toLocaleString();
    $("#bsEnt").textContent = ent.toLocaleString();
    $("#bsRel").textContent = rel.toLocaleString();
    _bsDensity = Math.min(1, 0.15 + mem / 4000 + ent / 2500);
    // node count grows with the knowledge graph so the cloud visibly fills in while
    // enrichment runs (memories are static; entities are what climb).
    _bsVisTarget = Math.round(260 + Math.min(1, ent / 1600) * 840);
    const state = $("#bsState");
    if (s.syncing) { state.textContent = "Building your brain…"; state.classList.remove("done"); }
    else { state.textContent = "Brain ready"; state.classList.add("done"); }
  } catch (_) {}
}
function openBrainScreen() {
  const m = $("#brainScreen"); if (!m) return;
  m.hidden = false;
  if (!_bsNodes) _bsBuildNodes();
  _bsWire();                          // mouse: parallax tilt, hover glow, drag-rotate
  try { loadBrain(); } catch (_) {}   // fill the side panel (stats, entities)
  _bsRefresh(); clearInterval(_bsPoll); _bsPoll = setInterval(_bsRefresh, 2500);
  cancelAnimationFrame(_bsRaf); _bsRaf = requestAnimationFrame(_bsDraw);
}
function closeBrainScreen() {
  $("#brainScreen").hidden = true;
  clearInterval(_bsPoll); _bsPoll = null; cancelAnimationFrame(_bsRaf); _bsRaf = null;
}
$("#bsClose").onclick = closeBrainScreen;
{ const rb = $("#rebuildBtn"); if (rb) rb.onclick = async () => {
  // Prune = remove junk entities, KEEP all the good (LLM/heuristic) graph work.
  // Alt/Option-click = full rebuild from scratch (wipes the graph, re-extracts).
  rb.disabled = true;
  try {
    if (window.event && (window.event.altKey)) {
      if (!confirm("Rebuild the knowledge graph from scratch? This WIPES the current graph (including AI enrichment) and re-extracts with the free offline extractor. Memories are kept.")) { rb.disabled = false; return; }
      rb.textContent = "Rebuilding…";
      await api("/api/brain/rebuild", { method: "POST" });
      toast("Rebuilding graph in the background…");
    } else {
      rb.textContent = "Cleaning…";
      const r = await api("/api/brain/prune", { method: "POST" });
      toast(r.removed_entities ? `Removed ${r.removed_entities} junk ${r.removed_entities === 1 ? "entity" : "entities"}` : "Graph is already clean");
    }
    loadBrain(); _bsRefresh();
  } catch (e) { toast(String(e)); }
  finally { rb.disabled = false; rb.textContent = "Clean up"; }
}; }

// Enrich with AI — loop the LLM enricher (uses the connected model) until the
// queue drains, showing live progress. General across any connector's content.
let _enriching = false;
function fmtTokens(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
function fmtEta(sec) { sec = Math.round(sec); if (sec < 60) return sec + "s"; const m = Math.round(sec / 60); return m < 60 ? m + "m" : Math.round(m / 60) + "h"; }
const ENRICH_TIPS = [
  "Entities are pulled from your emails, docs, notes & calendar.",
  "Click any entity in the list to see the facts behind it.",
  "Bounce emails, boilerplate & encoded junk are filtered out.",
  "The model types every entity — person, org, project or tool.",
  "Extraction is simple — a small model (Haiku, gpt-4o-mini) is plenty.",
  "Local models (Ollama) or your Claude subscription do this for free.",
  "It runs batch by batch — you can Stop anytime and resume later.",
];
// providers with no per-token API cost (free to enrich with)
const FREE_PROVIDERS = { ollama: 1, "claude-code": 1, subscription: 1, mock: 1 };
// ── model token usage (persisted server-side) ──────────────────────────────
async function updateUsage() {
  const box = $("#usageBox"); if (!box) return;
  let u; try { u = await api("/api/usage"); } catch (e) { return; }
  const a = u.active || {}, tin = a.in || 0, tout = a.out || 0, calls = a.calls || 0;
  const local = u.locality === "local";
  const limit = local ? "local · no API limit"
    : (u.context_window ? `~${Math.round(u.context_window / 1000)}K context/call` : "—");
  box.innerHTML = `
    <div class="usage-row"><span>Active model</span><b>${esc(u.active_provider || "—")}${a.model ? " · " + esc(a.model) : ""}</b></div>
    <div class="usage-row"><span>Tokens used</span><b>${(tin + tout).toLocaleString()}</b></div>
    <div class="usage-row"><span>In / Out</span><b>${tin.toLocaleString()} / ${tout.toLocaleString()}</b></div>
    <div class="usage-row"><span>Calls</span><b>${calls.toLocaleString()}</b></div>
    <div class="usage-row"><span>Limit</span><b>${limit}</b></div>`;
}
{ const rb = $("#usageReset"); if (rb) rb.onclick = async () => {
  try { await api("/api/usage/reset", { method: "POST" }); updateUsage(); } catch (e) {}
}; }

// Enrichment runs SERVER-SIDE (a background job) — the UI just starts/stops it and
// polls status, so a refresh reconnects to the running job instead of killing it.
let _enrichPoll = null, _enrichTip = 0;
function renderEnrich(s) {
  const eb = $("#enrichBtn"), panel = $("#enrichPanel"), bar = panel && panel.querySelector(".ep-bar");
  const fill = $("#epFill"), state = $("#epState"), pctEl = $("#epPct"),
        meta = $("#epMeta"), foundEl = $("#epFound"), tipEl = $("#epTip");
  if (panel) panel.hidden = false;
  const LOCAL = { ollama: 1, "claude-code": 1, subscription: 1, mock: 1 };
  const total = (s.processed || 0) + (s.remaining || 0);
  const pct = total ? Math.min(100, Math.round(s.processed / total * 100)) : (s.running ? 0 : 100);
  if (fill) fill.style.width = pct + "%"; if (pctEl) pctEl.textContent = pct + "%";
  if (eb) eb.style.setProperty("--p", pct + "%");
  if (s.running) {
    if (eb) { eb.classList.add("running"); eb.textContent = `Stop · ${pct}%`; }
    if (bar) bar.classList.add("working");
    if (state) { state.textContent = `Enriching with ${s.provider || "AI"}`; state.classList.remove("done"); }
    if (tipEl) tipEl.textContent = "Tip — " + ENRICH_TIPS[_enrichTip++ % ENRICH_TIPS.length];
  } else {
    if (eb) { eb.classList.remove("running"); eb.style.setProperty("--p", "0%"); eb.textContent = "Enrich with AI"; }
    if (bar) bar.classList.remove("working");
    if (state) {
      state.textContent = (s.remaining === 0 && s.processed > 0) ? `Fully enriched · +${s.entities} entities`
        : s.processed > 0 ? `Stopped · +${s.entities} entities · +${s.facts} facts` : "Ready to enrich";
      state.classList.add("done");
    }
  }
  const rate = s.elapsed > 0 ? s.processed / s.elapsed : 0;
  const eta = s.running && s.remaining > 0 && rate > 0 ? ` · ~${fmtEta(s.remaining / rate)} left` : "";
  const tok = LOCAL[s.provider] ? "local · free"
    : (s.tokens ? `${fmtTokens(s.tokens_in)}↑ ${fmtTokens(s.tokens_out)}↓ tokens${s.estimated ? " (est)" : ""}` : "");
  const capNote = s.cap ? ` · recent ${s.cap}/bulk source` : "";
  if (meta) meta.innerHTML =
    `${(s.processed || 0).toLocaleString()} of ${total.toLocaleString()} memories${capNote} · +${s.entities || 0} entities · +${s.facts || 0} facts${eta}` + (tok ? `<br>${tok}` : "");
  if (foundEl && s.found && s.found.length)
    foundEl.innerHTML = s.found.map((f) => `<span class="ep-chip ${f.type}">${esc(f.name)}</span>`).join("");
}
function pollEnrich() {
  clearInterval(_enrichPoll);
  const tick = async () => {
    let s; try { s = await api("/api/brain/enrich/status"); } catch (e) { return; }
    renderEnrich(s); loadBrain(); _bsRefresh(); updateUsage();
    if (!s.running) { clearInterval(_enrichPoll); _enrichPoll = null; }
  };
  tick(); _enrichPoll = setInterval(tick, 2000);
}
{ const eb = $("#enrichBtn"); if (eb) eb.onclick = async () => {
  if (eb.classList.contains("running")) {
    eb.textContent = "Stopping…";
    try { await api("/api/brain/enrich/stop", { method: "POST" }); } catch (e) {}
    return;
  }
  // Warn before spending real tokens on a big queue with a metered cloud model.
  const em = enrichModel();
  const prov = em.provider;
  if (!FREE_PROVIDERS[prov]) {
    let remaining = 0;
    try { remaining = (await api("/api/brain/enrich/status")).remaining || 0; } catch (_) {}
    if (remaining > 150) {
      const estTok = remaining * 500;   // rough: ~0.5k tokens per memory
      const ok = confirm(
        `Enrich ~${remaining.toLocaleString()} memories with “${prov}” (a metered cloud model)?\n\n`
        + `This can use a LOT of tokens — very roughly ~${fmtTokens(estTok)} — and may cost money.\n\n`
        + `Extraction is a simple task, so this is a better fit for a FREE model:\n`
        + `  • a local model (Ollama), or your Claude subscription/CLI — free\n`
        + `  • or a small cheap model (Haiku, gpt-4o-mini)\n\n`
        + `You can Stop anytime. Continue with ${prov}?`);
      if (!ok) return;
    }
  }
  eb.classList.add("running"); eb.textContent = "Starting…"; eb.style.setProperty("--p", "3%");
  if ($("#enrichPanel")) $("#enrichPanel").hidden = false;
  if ($("#epTip")) $("#epTip").textContent = "Tip — " + ENRICH_TIPS[0];
  try {
    await api("/api/brain/enrich/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: em.provider, model: em.model }) });
  } catch (e) {
    const st = $("#epState"); if (st) { st.textContent = "Couldn't start — check Model."; st.classList.add("done"); }
    eb.classList.remove("running"); eb.textContent = "Enrich with AI"; return;
  }
  pollEnrich();
}; }
// resume on load: if the server job is running, reconnect the UI
(async () => { try { const s = await api("/api/brain/enrich/status"); if (s.running) { pollEnrich(); } } catch (_) {} })();
$("#bsSync").onclick = async () => {
  try { const r = await api("/api/sync/now", { method: "POST" });
    toast(r.started ? "syncing your sources…" : (r.reason || "already syncing"));
    _bsRefresh(); updateBrainStatus();
  } catch (e) { toast(String(e)); }
};
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#brainScreen").hidden) closeBrainScreen(); });

// ── slide-over drawers opened from the left nav ─────────────────────────────
const DRAWER_TITLES = { sources: "Connectors", tasks: "Tasks", model: "AI model", tools: "Tools & skills" };
async function loadTools() {
  const box = $("#toolList"); if (!box) return;
  box.innerHTML = `<div class="tasks-empty">loading…</div>`;
  try {
    const { tools } = await api("/api/agents/tools");
    box.innerHTML = tools.map((t) =>
      `<div class="tool"><div class="tool-nm">${esc(t.name)}</div><div class="tool-ds">${esc(t.description || "")}</div></div>`).join("")
      || `<div class="tasks-empty">no tools</div>`;
  } catch (e) { box.innerHTML = `<div class="tasks-empty">couldn't load tools</div>`; }
}
function openDrawer(name) {
  const bg = $("#drawerBg"); if (!bg) return;
  $("#drawerTitle").textContent = DRAWER_TITLES[name] || name;
  document.querySelectorAll(".dpanel").forEach((p) => p.hidden = p.dataset.d !== name);
  bg.hidden = false;
  if (name === "sources") loadBrain();
  if (name === "tasks") { loadTasks(); loadReminders(); loadRoutines(); }
  if (name === "model") { loadProviders(); updateUsage(); }
  if (name === "tools") loadTools();
}
function closeDrawer() { const bg = $("#drawerBg"); if (bg) bg.hidden = true; }
document.querySelectorAll(".snav").forEach((b) => b.onclick = () => {
  if (b.id === "helpBtn") { window.location.href = "/onboarding?replay=1"; return; }  // re-experience onboarding (won't wipe)
  if (b.dataset.nav === "brain") return openBrainScreen();   // Brain → full-screen viz + tools
  openDrawer(b.dataset.nav);
});
$("#drawerClose").onclick = closeDrawer;
$("#drawerBg").onclick = (e) => { if (e.target.id === "drawerBg") closeDrawer(); };
{ const v = $("#viewBrainBtn"); if (v) v.onclick = () => { closeDrawer(); openBrainScreen(); }; }
{ const nr = $("#newAgentRow"); if (nr) nr.onclick = () => $("#newAgentBtn").click(); }
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#drawerBg") && !$("#drawerBg").hidden) closeDrawer(); });

// composer slash-style hint chips
{
  const hints = [["/catch me up", "Catch me up — what's new since yesterday?"],
    ["/tasks", "What should I focus on today? Show my open tasks."],
    ["/find", "Find "], ["/plan", "Help me plan my day and week."]];
  const box = $("#cmpHints");
  if (box) box.innerHTML = hints.map((h, i) => `<span data-i="${i}">${esc(h[0])}</span>`).join("");
  if (box) box.querySelectorAll("span").forEach((s) => s.onclick = () => {
    const [, q] = hints[+s.dataset.i];
    if (q.endsWith(" ")) { $("#input").value = q; $("#input").focus(); autoGrow(); } else send(q);
  });
}

// Cmd/Ctrl+R → refresh the workspace in place (picks up new code — assets are
// served no-cache). The desktop app runs in a webview where the browser's reload
// shortcut isn't wired, so we bind it ourselves. Note: it reloads "/", NOT the
// onboarding — a reload here should never restart onboarding.
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && (e.key === "r" || e.key === "R" || e.code === "KeyR")) {
    e.preventDefault();
    window.location.reload();
  }
}, true);

(async () => {
  if (await maybeOnboard()) return;   // redirecting to onboarding — stop here
  applyIcons();
  loadAgents(); loadProviders(); loadBrain(); loadTasks(); loadReminders(); loadRoutines();
  updateBrainStatus(); maybeWelcome();
  // poll the brain status often while it's building, and keep time-based panels fresh
  setInterval(updateBrainStatus, 5000);
  setInterval(() => { loadReminders(); loadRoutines(); }, 45000);
})();
