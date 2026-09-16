/**
 * The conversation: sending a turn, and everything that renders one.
 *
 * Agent selection and the empty state, the message list and tool trace, action
 * cards, the thinking indicator, and the two ways a turn runs — streamed, or in
 * one piece.
 *
 * **Streaming reassembles SSE frames across chunk boundaries.** One network
 * chunk is not one frame. A reader that assumes it does passes every hand test
 * and drops tokens against a real model, so `streamTurn` buffers and splits on
 * the frame delimiter rather than on whatever arrives.
 *
 * **Action cards are rendered from text a stranger may have written.** The
 * model's reply can quote an email, so everything here goes through `esc()`
 * before any markup — `md()` in core.js escapes first for the same reason.
 * Confirming an action is a deliberate tap; the agent never sends one unasked.
 *
 * One turn at a time for the whole workspace (`busy`), with an AbortController
 * so the user can stop it. Anything the user starts, they can stop.
 */

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
    else if (a.type === "mcp_action") {
      // A connector tool takes an object, and attributes are flat strings — so
      // the arguments are the body, as JSON. Mirrors `actions.parse_actions`.
      a.params.server_id = a.params.server || a.params.server_id || "";
      delete a.params.server;
      try {
        let body = inner.trim();
        if (body.startsWith("```")) body = body.replace(/^```[a-z]*\n?/i, "").replace(/```$/, "").trim();
        a.params.arguments = body ? JSON.parse(body) : {};
      } catch {
        // Malformed JSON is dropped, never guessed at — the same rule the
        // server applies, so the card and the execution agree about what
        // exists. Returning here leaves the tag stripped and no card shown.
        return "";
      }
    }
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
    // Model-written attribute: force it to a number rather than trusting it.
    const mins = Number.parseInt(p.interval_min, 10);
    const trig = p.trigger === "schedule"
      ? `every ${Number.isFinite(mins) && mins > 0 ? mins : 60} min` : "on every new email";
    rows = `<div class="ac-row"><b>Name</b> ${esc(p.name || "Automation")}</div>
       <div class="ac-row"><b>Runs</b> ${trig} · ${esc(p.agent || p.agent_id || "personal")}</div>
       <div class="ac-body">${esc(p.instruction || "")}</div>`;
  } else if (a.type === "mcp_action") {
    // Previously this fell through to the calendar branch, so a connector
    // action would have been presented as "Create calendar event" — a card
    // describing something other than what the button runs.
    title = `Run this in ${esc(p.connector || p.server_id || "a connector")}`;
    verb = "run";
    const args = p.arguments && typeof p.arguments === "object" ? p.arguments : {};
    const shown = Object.keys(args).map((k) => {
      const v = typeof args[k] === "string" ? args[k] : JSON.stringify(args[k]);
      return `<div class="ac-row"><b>${esc(k)}</b> ${esc(String(v).slice(0, 400))}</div>`;
    }).join("");
    rows = `<div class="ac-row"><b>Action</b> <code>${esc(p.tool || "")}</code></div>`
      + (shown || `<div class="ac-row"><b>Arguments</b> none</div>`);
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

// ── image attachments ──────────────────────────────────────────────────────
// #attachBtn had an icon and no click handler — a control that could not work,
// which is the one thing the product rules here are most explicit about. It
// picks files now, and the same three checks guard every way in: the button,
// a paste, and a drop.
//
// The vision check happens HERE, before the request, because we already know
// the answer: the catalog says whether the chosen model can see. Sending it
// anyway would bill the user for a failure we predicted. The server repeats
// the check — the client is a convenience, never the guard.
const IMG_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const IMG_MAX_BYTES = 5 * 1024 * 1024;     // decoded; the wire cap is larger
const IMG_MAX = 4;
let attachments = [];                       // {name, dataUrl, size}
let sentImages = [];                        // the set belonging to the turn in flight

function modelSeesImages() {
  const pid = ($("#provider") && $("#provider").value) || localStorage.getItem("lodestone_provider") || "";
  const mid = localStorage.getItem("lodestone_model") || "";
  const prov = (MODEL_CATALOG || []).find((p) => p.id === pid);
  if (!prov) return { ok: true };           // unknown is not "no"
  // No model chosen means Auto, which resolves to the best one available —
  // refusing there would refuse a model that can probably see.
  if (!mid) return { ok: true };
  const m = (prov.models || []).find((x) => (x.id || x.name) === mid);
  if (!m) return { ok: true };
  if (m.vision) return { ok: true };
  const alts = (prov.models || []).filter((x) => x.vision && !x.locked)
    .slice(0, 3).map((x) => x.name || x.id);
  return {
    ok: false,
    why: `${m.name || mid} can't read images.` +
         (alts.length ? ` Try ${alts.join(", ")}.`
                      : " Pick a model marked vision in Model settings."),
  };
}

function renderAttachments() {
  const box = $("#cmpAttachments");
  if (!box) return;
  box.hidden = attachments.length === 0;
  box.innerHTML = attachments.map((a, i) => `
    <div class="cmp-att" title="${esc(a.name || "image")}">
      <img src="${a.dataUrl}" alt="${esc(a.name || "attached image")}" />
      <button type="button" class="cmp-att-x" data-i="${i}" aria-label="Remove ${esc(a.name || "image")}">✕</button>
    </div>`).join("");
  box.querySelectorAll(".cmp-att-x").forEach((b) => {
    b.onclick = () => { attachments.splice(+b.dataset.i, 1); renderAttachments(); };
  });
}

function addImageFiles(files) {
  const list = Array.from(files || []).filter((f) => f && f.type.startsWith("image/"));
  if (!list.length) return;

  const seeing = modelSeesImages();
  if (!seeing.ok) { toast(`🔒 ${seeing.why}`); return; }

  for (const f of list) {
    if (attachments.length >= IMG_MAX) { toast(`Up to ${IMG_MAX} images at a time.`); break; }
    if (!IMG_TYPES.includes(f.type)) {
      toast(`${(f.type.split("/")[1] || f.type).toUpperCase()} isn't supported — use PNG, JPEG, GIF or WebP.`);
      continue;
    }
    if (f.size > IMG_MAX_BYTES) {
      toast(`"${f.name || "That image"}" is too large — images need to be under ${IMG_MAX_BYTES / (1024 * 1024)}MB.`);
      continue;
    }
    const reader = new FileReader();
    reader.onload = () => {
      attachments.push({ name: f.name || "", dataUrl: String(reader.result), size: f.size });
      renderAttachments();
    };
    reader.onerror = () => toast(`Couldn't read "${f.name || "that image"}".`);
    reader.readAsDataURL(f);
  }
}

{
  const btn = $("#attachBtn"), file = $("#cmpFile");
  if (btn && file) {
    btn.onclick = () => file.click();
    file.onchange = () => { addImageFiles(file.files); file.value = ""; };
  }
  // Paste: a screenshot in the clipboard is the most common way an image gets
  // into a chat, and it arrives as a file on the paste event, not as text.
  const input = $("#input");
  if (input) input.addEventListener("paste", (e) => {
    const items = (e.clipboardData && e.clipboardData.files) || [];
    if (items.length) { e.preventDefault(); addImageFiles(items); }
  });
  // Drop anywhere on the conversation, not just on the button.
  const zone = document.querySelector(".chat");
  if (zone) {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => {
      if (!(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files"))) return;
      stop(e); zone.classList.add("drop-target");
    }));
    ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => {
      if (t === "drop") { stop(e); addImageFiles(e.dataTransfer.files); }
      zone.classList.remove("drop-target");
    }));
  }
}

function addMsg(role, text, images) {
  const box = $("#messages");
  const he = box.querySelector(".hero-empty"); if (he) he.remove();
  if (role === "assistant") {
    const { clean, actions } = parseActions(text);
    const el = document.createElement("div");
    el.className = "msg assistant";
    // No avatar on each turn. Which agent is answering is already said by the
    // chat header and the rail; repeating it beside every message spent a
    // 34px column on it and pushed the prose off the column's left edge.
    // The MARKDOWN is what gets copied, not the rendered text: pasting a
    // reply into a note or an issue should keep its lists and its code, and
    // innerText would flatten all of it.
    el.innerHTML = `<div class="a-body">${md(clean)}</div>
      <div class="msg-tools"><button type="button" class="msg-copy" title="Copy reply"
        aria-label="Copy reply">${IC.copy}<span>Copy</span></button></div>`;
    const copyBtn = el.querySelector(".msg-copy");
    if (copyBtn) copyBtn.onclick = async () => {
      const ok = await copyToClipboard(clean);
      if (!ok) { toast("Could not copy that"); return; }
      // Confirm on the button itself. A toast says "something happened";
      // the button saying it says "this is the thing that happened".
      copyBtn.innerHTML = `${IC.tick}<span>Copied</span>`;
      copyBtn.classList.add("is-done");
      setTimeout(() => {
        copyBtn.innerHTML = `${IC.copy}<span>Copy</span>`;
        copyBtn.classList.remove("is-done");
      }, 1400);
    };
    box.appendChild(el);
    for (const a of actions) box.appendChild(actionCard(a));
    box.scrollTop = 1e9; return el;
  }
  const el = document.createElement("div");
  el.className = "msg " + role;
  if (images && images.length) {
    // textContent for the words, built nodes for the pictures: the message is
    // user input, so it must never be interpolated into innerHTML.
    const strip = document.createElement("div");
    strip.className = "msg-images";
    for (const a of images) {
      const im = document.createElement("img");
      im.src = a.dataUrl; im.alt = a.name || "attached image";
      strip.appendChild(im);
    }
    el.appendChild(strip);
    if (text) {
      const t = document.createElement("div");
      t.textContent = text;
      el.appendChild(t);
    }
  } else {
    el.textContent = text;
  }
  box.appendChild(el); box.scrollTop = 1e9; return el;
}
function addTrace(steps) {
  if (!steps.length) return;
  const calls = steps.filter((s) => s.kind === "tool_call");
  if (!calls.length) return;
  // Folded away by default. What an agent actually ran is worth being able to
  // check — it is the difference between trusting the answer and taking it on
  // faith — but it is not the answer, and a screenful of raw tool arguments
  // between two replies buries the thing the user came for.
  //
  // <details> rather than a button and a class: it is open/closed state the
  // browser already owns, it is keyboard-operable for free, and it cannot get
  // out of step with a re-render the way a toggle flag can.
  const el = document.createElement("details");
  el.className = "trace";
  // Name the tools in the summary, so the fold still says what happened.
  const names = [...new Set(calls.map((c) => c.name))];
  const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? `, +${names.length - 3} more` : "");
  el.innerHTML = `<summary class="trace-sum">
      <span class="trace-chev" aria-hidden="true"></span>
      <span>Show thinking</span>
      <span class="trace-n">${calls.length} step${calls.length === 1 ? "" : "s"} · ${esc(shown)}</span>
    </summary>
    <div class="trace-body">` + calls.map((s) => {
    const res = (steps.find((r) => r.kind === "tool_result" && r.name === s.name) || {}).result || "";
    return `<div class="step"><span class="tname">${esc(s.name)}</span>(${esc(JSON.stringify(s.arguments))})<span class="res">${esc(res.slice(0, 160))}</span></div>`;
  }).join("") + `</div>`;
  $("#messages").appendChild(el); $("#messages").scrollTop = 1e9;
}

let busy = false;               // one turn at a time per the whole workspace
let controller = null;          // AbortController for the in-flight turn
let turnId = null;              // the name this turn answers to, for Stop

// Stop the running turn. The server is told first and the fetch is left alone,
// because the turn keeps whatever it had already written and sends it back —
// aborting here would throw that away and, worse, leave the model calls running
// on the user's own key with the screen saying the work had ended.
async function stopTurn() {
  if (!turnId) { if (controller) controller.abort(); return; }
  const id = turnId;
  try {
    await api(`/api/agents/turns/${encodeURIComponent(id)}/stop`, { method: "POST" });
  } catch (_) {
    if (controller) controller.abort();   // could not reach it; end it locally
  }
}

function setBusy(on) {
  busy = on;
  $("#input").disabled = on;
  const b = $("#send");
  // Swap the ICON. This wrote textContent, which did two things at once: it
  // crammed the word "Stop" into a 34px circle, and — because textContent
  // replaces the element's children — it destroyed the arrow SVG that
  // applyIcons had put there, so the send button was the word "Send" for the
  // rest of the session. The label the assistive tech reads is set alongside,
  // since a glyph on its own says nothing to a screen reader.
  b.innerHTML = IC[on ? "stop" : "arrowUp"] || "";
  b.title = on ? "Stop" : "Send";
  b.setAttribute("aria-label", on ? "Stop generating" : "Send message");
  b.classList.toggle("stopbtn", on);
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
  let timer = setInterval(tick, 150);
  let body = null;
  // Once anything real arrives, stop guessing. The phrases and the countdown
  // exist only to fill silence, and there is no longer any silence to fill.
  const stopGuessing = () => {
    if (timer) { clearInterval(timer); timer = null; }
    if (fill) fill.style.width = "100%";
    if (timeEl) timeEl.textContent = "";
  };
  return {
    el,
    note: (label) => { stopGuessing(); if (msgEl) msgEl.textContent = label; },
    preview: (textSoFar) => {
      stopGuessing();
      if (!body) {
        body = document.createElement("div");
        body.className = "think-preview";
        el.appendChild(body);
      }
      body.textContent = textSoFar;
      const wrap = $("#messages");
      if (wrap) wrap.scrollTop = wrap.scrollHeight;
    },
    done: () => { if (timer) clearInterval(timer); el.remove(); },
  };
}

async function send(text) {
  if (busy) return;             // guard: ignore sends while a turn is running
  setBusy(true);
  controller = new AbortController();
  // Named before the request leaves, so Stop works from the first frame the
  // button is visible rather than from whenever the server gets around to us.
  turnId = (crypto.randomUUID && crypto.randomUUID())
    || `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  // Detach the attachments the moment the turn starts: the user can type the
  // next message while this one runs, and anything still in the tray then
  // belongs to THAT message, not this one.
  sentImages = attachments;
  attachments = [];
  renderAttachments();
  addMsg("user", text, sentImages);
  const curAgent = agents.find((x) => x.id === current);
  const thinkProv = (curAgent && curAgent.model_provider) || $("#provider").value;
  const think = makeThinking(thinkProv);
  try {
    const res = await streamTurn(text, think);
    think.done();
    addTrace(res.trace || []);
    addMsg("assistant", res.reply);
    loadBrain();
    loadTasks();       // an agent may have added/completed a task this turn
    loadReminders();   // …or set a reminder
  } catch (e) {
    think.done();
    if (controller && controller.signal.aborted) addMsg("assistant", "■ Stopped.");
    else addMsg("assistant", "△ " + e);
  }
  finally { controller = null; turnId = null; setBusy(false); }
}

// Run one turn over Server-Sent Events, showing the reply as it is written and
// naming each tool as it runs. Falls back to the plain endpoint if streaming is
// unavailable for any reason — a user whose stream broke wants an answer, not a
// second kind of error.
// Which provider this turn runs on.
//
// This read `$("#provider").value`, a hidden <select> that is EMPTY until
// loadProviders() fills it — and loadProviders fetches the model catalog,
// measured cold at ~10s. For those ten seconds the composer showed the
// provider read from localStorage while the request carried nothing, the
// server fell back to settings.model_provider (`mock` on a fresh install),
// and the offline model answered in a real model's clothes. Two messages in a
// row came back as a truncated echo of the recall block.
//
// localStorage is the store the picker actually writes to (setActiveModel),
// and it is readable synchronously on the first paint. The select is a slow
// copy of it, kept only as a fallback for anything that still writes there.
function chosenProvider() {
  const saved = (localStorage.getItem("lodestone_provider") || "").trim();
  if (saved) return saved;
  const sel = $("#provider");
  return (sel && sel.value) || undefined;
}

async function streamTurn(text, think) {
  const body = JSON.stringify({
    message: text, provider: chosenProvider(),
    model: localStorage.getItem("lodestone_model") || undefined,
    effort: localStorage.getItem("lodestone_effort") || undefined,
    turn_id: turnId || undefined,
    images: sentImages.map((a) => ({ data_url: a.dataUrl, name: a.name })),
  });
  let resp;
  try {
    resp = await fetch(`/api/agents/${current}/chat/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body, signal: controller.signal,
    });
  } catch (e) {
    if (controller.signal.aborted) throw e;
    resp = null;
  }
  if (!resp || !resp.ok || !resp.body) return plainTurn(body);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", preview = "", result = null, failure = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line; a chunk can split one.
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      let ev; try { ev = JSON.parse(line.slice(5)); } catch (_) { continue; }
      if (ev.type === "token") {
        preview += ev.text;
        think.preview(preview);
      } else if (ev.type === "tool_call") {
        think.note(TOOL_LABELS[ev.name] || ev.name.replace(/_/g, " "));
      } else if (ev.type === "plan") {
        const next = (ev.steps || []).find((s) => !s.done);
        if (next) think.note(next.text);
      } else if (ev.type === "done") {
        result = ev.result;
      } else if (ev.type === "error") {
        failure = ev.message;
      }
    }
  }
  if (result) return result;
  if (failure) throw failure;
  return plainTurn(body);        // stream ended with nothing usable
}

async function plainTurn(body) {
  return api(`/api/agents/${current}/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body, signal: controller.signal,
  });
}

// What each tool is doing, in the user's words rather than ours.
const TOOL_LABELS = {
  search_brain: "Searching your brain…", remember: "Saving that…",
  list_entities: "Looking at who and what you work with…",
  web_search: "Searching the web…", gmail_search: "Reading your mail…",
  add_task: "Adding a task…", list_tasks: "Checking your tasks…",
  complete_task: "Ticking that off…", ask_agent: "Asking another agent…",
  update_plan: "Planning…", create_open_loop: "Noting a loose end…",
  list_open_loops: "Checking loose ends…", complete_open_loop: "Closing that off…",
};


function autoGrow() {
  const t = $("#input"); if (!t) return;
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 140) + "px";
}
