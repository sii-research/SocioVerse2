// ── conversation dock (service mode; feature-detected via /api/chat/ping; ────
//    never probed on the local server, where the dock is hidden — see store.js isLocal) ──
//    Ported from the battle-tested v1 pane: SSE replay, optimistic send, gates
//    with pinned reminder + tab-title flip, uploads, auto URL fetch, quota.
import { S, emit, getVerbosity, setVerbosity, isLocal } from "./store.js";
import { T, TF, getLang } from "./i18n.js";
import { el, escHtml, escAttr, cssv, toast } from "./ui.js";
import { mdToHtml } from "./md.js";
import * as api from "./api.js";
import { STAGE_TAB, switchTab, stageName, setCompose, inCompose } from "./app.js";

// started = whether this session has sent (or replayed) a user message — the only exit condition of the compose state (centered input box)
export const CHAT = { enabled:false, es:null, study:null, live:null, liveBuf:"", liveT:null,
  busy:false, stopping:false, optimistic:null, stage:null, act:null,
  liveStage:null, liveRunning:false, replayDone:false, gatePending:false, lastText:"", started:false };

function chatScroll(force){ const log = el("chatLog"); const near = log.scrollHeight - log.scrollTop - log.clientHeight < 160; if (force || near) log.scrollTop = log.scrollHeight; }
function chatLine(html, cls){ const d = document.createElement("div"); d.className = cls; d.innerHTML = html; el("chatLog").appendChild(d); return d; }
function clearTyping(){ const t = el("chatLog").querySelector(".typing-row"); if (t) t.remove(); }

const TY_STAGE = {"sv-init":"ty_init","sv-build-model":"ty_model","sv-build-environment":"ty_env",
                  "sv-build-population":"ty_pop","sv-run":"ty_run","sv-report":"ty_report","sv-iterate":"ty_iter"};
const TY_TOOL = {WebSearch:"ty_search",WebFetch:"ty_search",Write:"ty_code",Edit:"ty_code",NotebookEdit:"ty_code",
                 Bash:"ty_exec",Read:"ty_read",Grep:"ty_read",Glob:"ty_read"};

function finalizeLive(){
  if (CHAT.liveT){ clearTimeout(CHAT.liveT); CHAT.liveT = null; }
  if (CHAT.live){
    if (CHAT.liveBuf.includes('<invoke name="') && CHAT.liveBuf.includes('<parameter name="')){
      CHAT.live.remove(); CHAT.live = null; CHAT.liveBuf = ""; return;   // fake tool-call text: drop it entirely
    }
    try { const m = CHAT.live.querySelector(".md"); if (m && CHAT.liveBuf) m.innerHTML = mdToHtml(CHAT.liveBuf); } catch(e){}
    CHAT.live.className = "cmsg assistant"; CHAT.live = null;
  }
  CHAT.liveBuf = "";
}
function typingHtml(){
  const key = CHAT.act || CHAT.stage || "ty_think";
  const hint = (CHAT.stage === "ty_model" || CHAT.stage === "ty_run") ? ` <span class="muted" style="font-size:10.5px">· ${escHtml(T("ty_long"))}</span>` : "";
  return `<span class="typing"><i></i><i></i><i></i></span> <span style="font-size:11.5px;color:var(--muted)">${escHtml(T(key))}</span>${hint}`;
}
function showTyping(){
  if (CHAT.live) return;
  const t = el("chatLog").querySelector(".typing-row");
  if (t){ t.innerHTML = typingHtml(); return; }
  chatLine(typingHtml(), "cline typing-row"); chatScroll(true);
}

// ── tool rows rendered per transcript level ──
// The simple level never gets here (tool steps are not shown at all; see the level gate in renderChatEvent);
// the standard level shows a one-line summary; the detailed level folds the full input into the same row, expandable on click.
function renderToolLine(ev){
  const head = `⚙ <span class="mono">${escHtml(ev.name)}</span> <span>${escHtml(ev.summary || "")}</span>`;
  if (getVerbosity() !== "dev" || !ev.detail){ chatLine(head, "cline"); return; }
  const d = document.createElement("div");
  d.className = "cline tooldetail";
  d.innerHTML = `<details><summary>${head}</summary><pre></pre></details>`;
  d.querySelector("pre").textContent = ev.detail;   // textContent: the input is model output, never parse it as HTML
  el("chatLog").appendChild(d);
}
function renderChatEvent(ev){
  // Level gate. The simple level keeps only: user messages, question cards, errors, and the **last** text of the turn (the brief).
  // Intermediate narration is recognized by event order, not content: a text followed by another tool
  // is process narration; the text right before the result is the conclusion. So the simple level holds the text back (pendingFinal)
  // and renders it only at result time; text superseded by a later tool call simply never shows.
  const simple = getVerbosity() === "simple";
  if (ev.type === "user"){
    CHAT.pendingFinal = null;                       // a new turn starts: clear the brief held from the previous turn
    CHAT.started = true; setCompose(false);         // there is a conversation now → leave the compose state, back to three panes
    if (CHAT.optimistic === ev.text){ CHAT.optimistic = null; return; }
    clearTyping(); chatLine(escHtml(ev.text).replace(/\n/g,"<br/>"), "cmsg user"); showTyping(); chatScroll(true);
  }
  else if (ev.type === "delta"){
    if (simple) return;                             // the simple level does not stream process text
    clearTyping();
    CHAT.liveBuf = (CHAT.liveBuf || "") + ev.text;
    if (!CHAT.live){ CHAT.live = chatLine('<div class="md"></div>', "cmsg assistant live"); }
    if (!CHAT.liveT){ const iv = CHAT.liveBuf.length > 3000 ? 450 : 150;
      CHAT.liveT = setTimeout(() => { CHAT.liveT = null;
        try { const m = CHAT.live && CHAT.live.querySelector(".md"); if (m) m.innerHTML = mdToHtml(CHAT.liveBuf); } catch(e){}
        chatScroll(false); }, iv); }
  }
  else if (ev.type === "text"){
    clearTyping();
    CHAT.lastText = ev.text || "";
    if (simple){ CHAT.pendingFinal = ev.text || ""; return; }   // hold it; decide at result time
    const html = `<div class="md">${mdToHtml(ev.text)}</div>`;
    if (CHAT.liveT){ clearTimeout(CHAT.liveT); CHAT.liveT = null; }
    CHAT.liveBuf = "";
    if (CHAT.live){ CHAT.live.className = "cmsg assistant"; CHAT.live.innerHTML = html; CHAT.live = null; }
    else chatLine(html, "cmsg assistant");
    chatScroll(false);
  }
  else if (ev.type === "tool"){ finalizeLive(); clearTyping();
    if (ev.name === "Skill"){ const m = (ev.summary || "").match(/^\/(sv-[a-z-]+)/); CHAT.stage = m ? TY_STAGE[m[1]] || null : null; CHAT.act = null;
      if (m && m[1] !== "sv-iterate"){ CHAT.liveStage = m[1]; CHAT.liveRunning = true; emit("chatlive"); } }
    else CHAT.act = TY_TOOL[ev.name] || null;
    // The side effects above (stage, nav badges, typing hint) are kept at every level — the simple level relies on them for a sense of progress;
    // only the visible tool row itself is suppressed. Also clear the held text: a tool follows it, so it was process narration.
    if (simple) CHAT.pendingFinal = null;
    else renderToolLine(ev);
    if (CHAT.busy) showTyping(); chatScroll(false);
  }
  else if (ev.type === "stage"){
    if (simple) return;
    const tab = STAGE_TAB[ev.stage];
    const d = chatLine(`● ${escHtml(stageName(ev.stage))} · <span style="color:var(--accent)">${escHtml(T("chat_view_stage"))}</span>`, "cchip");
    d.style.background = cssv("--accent-bg"); d.style.color = cssv("--accent");
    d.onclick = () => { if (tab) switchTab(tab); };
    chatScroll(false);
  }
  else if (ev.type === "adopted"){
    const ns = ev.new_study;
    if (CHAT.study !== ns){
      CHAT.study = "__switching__";     // break chatSubscribe's same-name guard (see the v1 infinite-resubscribe fix)
      chatSubscribe(ns);
      emit("adopted", ns);
    }
  }
  else if (ev.type === "sysnote"){ if (simple) return;
    chatLine(`⏱ ${escHtml(ev.text || "")}`, "cline"); chatScroll(false); }
  else if (ev.type === "gate"){ clearTyping(); renderGateCard(ev); }
  else if (ev.type === "gate_answered"){ const g = document.getElementById("gate-" + ev.gate_id); if (g && !g.classList.contains("done")) finishGateCard(g, ev.answers); }
  else if (ev.type === "result"){ clearTyping(); finalizeLive(); CHAT.stage = null; CHAT.act = null;
    // simple level: the turn is over, so the held text is the final brief (no later tool can supersede it)
    if (simple && CHAT.pendingFinal){
      chatLine(`<div class="md">${mdToHtml(CHAT.pendingFinal)}</div>`, "cmsg assistant");
      CHAT.pendingFinal = null;
    }
    if (CHAT.liveRunning){ CHAT.liveRunning = false; emit("chatlive"); }
    const stopped = CHAT.stopping; CHAT.stopping = false;
    const tc = (ev.turn_cost_usd != null) ? ev.turn_cost_usd : (ev.cost_usd || 0);
    const line = chatLine(stopped ? `✕ ${escHtml(T("chat_stopped"))}` : `${ev.is_error ? "✕" : "✓"} ${escHtml(T("chat_done"))} · ${ev.num_turns} turns · $${tc.toFixed(2)}`, "cline" + ((ev.is_error || stopped) ? " err" : ""));
    if (ev.turn_cost_usd != null && ev.cost_usd != null)
      line.title = TF("cost_tip", ev.turn_cost_usd.toFixed(4), (ev.cost_usd || 0).toFixed(2));
    chatScroll(false); emit("turn-done");
    // every old result passes through here during history replay; the quota refreshes only once after a real turn end (the status branch refreshes it when replay completes)
    if (CHAT.replayDone) refreshQuota();
    const rh = el("replyHint");
    if (rh && CHAT.replayDone && !CHAT.gatePending && !ev.is_error && /[?？]\s*(\**)?\s*$/.test((CHAT.lastText || "").trim().slice(-80)))
      rh.style.display = "block";
  }
  else if (ev.type === "error"){ clearTyping(); chatLine(`✕ ${escHtml(T("chat_error"))}: ${escHtml(ev.message || "")}`, "cline err"); chatScroll(false); }
  else if (ev.type === "status"){ CHAT.busy = !!ev.busy; updateSendBtn();
    if (CHAT.busy){ showTyping(); const rh = el("replyHint"); if (rh) rh.style.display = "none"; }
    else { clearTyping(); finalizeLive(); CHAT.stage = null; CHAT.act = null; if (CHAT.liveRunning){ CHAT.liveRunning = false; emit("chatlive"); } }
    if (!CHAT.replayDone){ CHAT.replayDone = true; refreshQuota(); chatScroll(true); setTimeout(() => chatScroll(true), 120); setTimeout(() => chatScroll(true), 600); updateGatePin(); }
  }
}

export function updateGatePin(){
  const pending = !!document.querySelector("#chatLog .cgate:not(.done)");
  const pin = el("gatePin"); if (pin) pin.style.display = pending ? "flex" : "none";
  if (CHAT.gatePending !== pending){ CHAT.gatePending = pending; emit("chatlive"); }
  document.title = pending ? "⏸ " + T("gate_title") : (S.awaiting ? T("await_title") : T("doc_title"));
  const fb = el("fabBadge");
  if (fb){ fb.style.display = pending ? "flex" : "none"; fb.textContent = "⏸"; }
  if (pending){ const rh = el("replyHint"); if (rh) rh.style.display = "none"; }
}
function jumpToGate(){
  const g = document.querySelector("#chatLog .cgate:not(.done)");
  if (g){ document.body.classList.remove("chat-hidden"); el("chatFab").style.display = "none"; g.scrollIntoView({behavior:"smooth", block:"center"}); }
}

function renderGateCard(ev){
  const card = document.createElement("div"); card.className = "cgate"; card.id = "gate-" + ev.gate_id;
  card.innerHTML = `<div class="gatehead">⏸ <span>${escHtml(T("gate_head"))}</span><span class="gsub">${escHtml(T("gate_head_sub"))}</span></div>`
   + ev.questions.map((q, qi) => {
    const multi = !!q.multiSelect, name = `g${ev.gate_id}q${qi}`, t = multi ? "checkbox" : "radio";
    return `<div class="q">${q.header ? `<span class="pill" style="background:var(--surface);color:var(--amber);margin-right:6px">${escHtml(q.header)}</span>` : ""}${escHtml(q.question)}</div>`
      + (q.options || []).map((o, oi) => `<label><input type="${t}" name="${name}" value="${escAttr(o.label)}" ${oi === 0 && !multi ? "checked" : ""}/><span>${escHtml(o.label)}${o.description ? `<div class="desc">${escHtml(o.description)}</div>` : ""}</span></label>`).join("")
      + `<label><input type="${t}" name="${name}" value="__other__"/><span style="flex:1;min-width:0">${escHtml(T("chat_other"))}<textarea rows="1" id="${name}other" oninput="const r=document.getElementsByName('${name}');[...r].find(x=>x.value==='__other__').checked=true;this.style.height='auto';this.style.height=Math.min(this.scrollHeight,140)+'px'"></textarea></span></label>`;
  }).join("")
  + `<button class="sub" data-gate="${escAttr(ev.gate_id)}">${escHtml(T("chat_gate_submit"))}</button>`;
  card.dataset.questions = JSON.stringify(ev.questions);
  card.querySelector(".sub").onclick = () => submitGate(ev.gate_id);
  el("chatLog").appendChild(card); chatScroll(true); updateGatePin();
}
function finishGateCard(card, answers){
  if (card.classList.contains("done")) return;   // dedupe the race between the local submit and the SSE gate_answered echo
  card.classList.add("done");
  card.querySelectorAll("input,button").forEach(n => n.disabled = true);
  const done = document.createElement("div"); done.className = "cline";
  done.textContent = `✓ ${T("chat_gate_answered")}` + (answers ? " · " + Object.values(answers).join(" / ") : "");
  card.appendChild(done); updateGatePin();
}
async function submitGate(gateId){
  const card = document.getElementById("gate-" + gateId); if (!card || card.classList.contains("done")) return;
  const questions = JSON.parse(card.dataset.questions || "[]"); const answers = {};
  questions.forEach((q, qi) => {
    const name = `g${gateId}q${qi}`;
    const picked = [...document.getElementsByName(name)].filter(x => x.checked).map(x => {
      if (x.value === "__other__"){ const o = el(name + "other"); return o && o.value.trim() ? o.value.trim() : null; }
      return x.value;
    }).filter(Boolean);
    if (picked.length) answers[q.question] = picked.join(", ");
  });
  if (!Object.keys(answers).length) return;
  const r = await api.chatAnswer(CHAT.study, gateId, answers);
  if (r.ok) finishGateCard(card, answers);
}

export function chatSubscribe(study){
  if (!CHAT.enabled || CHAT.study === study) return;
  if (CHAT.es){ CHAT.es.close(); CHAT.es = null; }
  CHAT.study = study; CHAT.live = null; CHAT.liveBuf = ""; CHAT.pendingFinal = null; if (CHAT.liveT){ clearTimeout(CHAT.liveT); CHAT.liveT = null; }
  CHAT.busy = false; CHAT.stopping = false; CHAT.optimistic = null; CHAT.stage = null; CHAT.act = null;
  CHAT.liveStage = null; CHAT.liveRunning = false; CHAT.replayDone = false; CHAT.gatePending = false;
  CHAT.started = false;   // switching study re-attaches SSE; with history, the first replayed user event sets it back to true immediately
  el("chatStudy").textContent = study;
  el("chatLog").innerHTML = `<div class="cline" style="padding:8px 4px">${escHtml(T("chat_empty"))}</div>`;
  CHAT.es = api.chatStream(study);
  CHAT.es.onmessage = e => { try { renderChatEvent(JSON.parse(e.data)); } catch(err){} };
  emit("chatlive");
}

function updateSendBtn(){
  const btn = el("chatSend"); if (!btn) return;
  if (CHAT.busy){ btn.textContent = T("chat_stop"); btn.style.background = "var(--coral)"; btn.dataset.mode = "stop"; }
  else { btn.textContent = T("chat_send"); btn.style.background = ""; btn.dataset.mode = "send"; }
}
async function stopChat(){
  if (!CHAT.study) return;
  CHAT.stopping = true;
  await api.chatStopReq(CHAT.study);
}
async function sendChat(){
  if (el("chatSend")?.dataset.mode === "stop"){ return stopChat(); }
  const ta = el("chatInput"); const msg = ta.value.trim(); if (!msg || !CHAT.study) return;
  ta.value = "";
  CHAT.started = true; setCompose(false);   // the compose state ends here: the page switches back to the three-pane layout
  clearTyping(); chatLine(escHtml(msg).replace(/\n/g,"<br/>"), "cmsg user"); showTyping(); chatScroll(true);
  CHAT.optimistic = msg;
  { const rh = el("replyHint"); if (rh) rh.style.display = "none"; }
  autoFetchUrls(msg);
  try {
    const r = await api.chatSend(CHAT.study, msg);
    if (!r.ok){ const e = await r.json().catch(() => ({})); if (e.error) chatLine(`✕ ${escHtml(T("chat_error"))}: ${escHtml(e.error)}`, "cline err"); }
  } catch(err){ clearTyping(); chatLine(`✕ ${escHtml(T("chat_error"))}: ${escHtml(String(err))}`, "cline err"); chatScroll(false); }
}
// Called by the tab quick actions: prefill the input box (not sent automatically; the user reviews it first).
// Most quick-action templates carry a "(describe …)" placeholder; with the cursor at the end, the user easily hits Enter and
// sends the placeholder text as the message, and the agent can only ask back — a wasted turn. So select the placeholder: the first keystroke replaces it.
const PLACEHOLDER = /（[^（）]*(?:例如|说明|描述|填|如\s)[^（）]*）|\([^()]*(?:e\.g\.|describe|specify)[^()]*\)/;
export function chatPrefill(text){
  document.body.classList.remove("chat-hidden"); el("chatFab").style.display = "none";
  const ta = el("chatInput"); if (!ta) return;
  ta.value = text; ta.focus();
  const m = text.match(PLACEHOLDER);
  if (m) ta.setSelectionRange(m.index, m.index + m[0].length);
  else ta.setSelectionRange(text.length, text.length);
  ta.classList.add("glow"); ta.addEventListener("input", () => ta.classList.remove("glow"), { once:true });
  setTimeout(() => ta.classList.remove("glow"), 4000);
}

async function uploadFile(file){
  if (!CHAT.study) return;
  const line = chatLine(`📎 ${escHtml(file.name)} <span class="muted">…</span>`, "cline");
  try {
    const d = await api.chatUpload(CHAT.study, file);
    if (d.ok){
      line.innerHTML = `📎 ${escHtml(d.name)} <span style="color:var(--teal)">✓ ${escHtml(T("upl_ok"))}</span> <span class="muted mono" style="font-size:10px">${escHtml(d.path)}</span>`;
      const msg = TF("upl_msg", d.path, (d.size/1024).toFixed(1));
      clearTyping(); chatLine(escHtml(msg), "cmsg user"); showTyping(); chatScroll(true); CHAT.optimistic = msg;
      api.chatSend(CHAT.study, msg);
      emit("uploaded", d.path);
    } else { line.innerHTML = `📎 ${escHtml(file.name)} <span style="color:var(--coral)">✕ ${escHtml(T("upl_fail"))}: ${escHtml(d.error || "")}</span>`; }
  } catch(e){ line.innerHTML = `📎 ${escHtml(file.name)} <span style="color:var(--coral)">✕ ${escHtml(String(e))}</span>`; }
  chatScroll(false);
}
function autoFetchUrls(msg){
  const re = /https?:\/\/[^\s"'<>()]+\.(?:csv|tsv|json|jsonl|txt|md|xlsx|xls|parquet|ya?ml|pdf)(?=[\s"'<>()]|$)/gi;
  const urls = [...new Set((msg.match(re) || []))].slice(0, 3);
  urls.forEach(u => fetchUrl(u));
}
async function fetchUrl(url){
  if (!CHAT.study || !url) return;
  const line = chatLine(`🔗 ${escHtml(url.slice(0, 80))} …`, "cline");
  try {
    const d = await api.chatFetchUrl(CHAT.study, url);
    if (d.ok){
      line.innerHTML = `🔗 ${escHtml(d.name)} <span style="color:var(--teal)">✓ ${escHtml(T("upl_ok"))}</span> <span class="muted mono" style="font-size:10px">${escHtml(d.path)}</span>`;
      const msg = TF("url_msg", d.path, (d.size/1024).toFixed(1), url.slice(0, 120));
      clearTyping(); chatLine(escHtml(msg), "cmsg user"); showTyping(); chatScroll(true); CHAT.optimistic = msg;
      api.chatSend(CHAT.study, msg);
      emit("uploaded", d.path);
    } else { line.innerHTML = `🔗 <span style="color:var(--coral)">✕ ${escHtml(d.error || "")} ${escHtml(d.detail || "")}</span>`; }
  } catch(e){ line.innerHTML = `🔗 <span style="color:var(--coral)">✕ ${escHtml(String(e))}</span>`; }
  chatScroll(false);
}
function initUpload(){
  const fi = el("fileInput");
  el("attachBtn").onclick = () => fi.click();
  fi.onchange = () => { if (fi.files.length){ uploadFile(fi.files[0]); fi.value = ""; } };
  const pane = el("chatDock"); let dragDepth = 0;
  pane.addEventListener("dragenter", e => { e.preventDefault(); dragDepth++; pane.classList.add("dragging"); });
  pane.addEventListener("dragover", e => e.preventDefault());
  pane.addEventListener("dragleave", () => { if (--dragDepth <= 0){ dragDepth = 0; pane.classList.remove("dragging"); } });
  pane.addEventListener("drop", e => { e.preventDefault(); dragDepth = 0; pane.classList.remove("dragging");
    if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); });
}
export { uploadFile };

async function refreshQuota(){
  try {
    const me = await api.getMe();
    const q = me.quota; if (!q) return;
    const c = el("quotaChip");
    c.style.display = "";
    // "Chat plane" rather than "Agent plane": this is the model that drives the conversation,
    // not the thousands of agents in the simulation; sharing the name would suggest the quota is counted per agent.
    // (The backend field is still called quota.agent — only the display changes, not the interface.)
    c.textContent = `Chat $${q.agent.remaining.toFixed(2)} · Sim $${q.sim.remaining.toFixed(2)}`;
    c.dataset.tip = (getLang() === "zh")
      ? `剩余额度 — Chat 平面 $${q.agent.remaining.toFixed(2)}/$${q.agent.limit}，模拟平面 $${q.sim.remaining.toFixed(2)}/$${q.sim.limit}`
      : `Remaining — Chat $${q.agent.remaining.toFixed(2)}/$${q.agent.limit}, simulation $${q.sim.remaining.toFixed(2)}/$${q.sim.limit}`;
    if (q.agent.remaining <= 1 || q.sim.remaining <= 1){ c.style.color = cssv("--amber"); }
    refreshQuotaReqBtn();
  } catch(e){}
}

// ── quota request: entry at the bottom of the rail → popup card (plane × tier × note) → admin approval ──
async function refreshQuotaReqBtn(){
  const b = el("quotaReqBtn"); if (!b) return;
  b.style.display = "";
  let mine = null;
  try { mine = (await (await fetch(api.apiUrl("api/quota-request/mine"))).json()).request; } catch(e){}
  if (mine && mine.status === "pending"){
    b.textContent = "⏳ " + T("qr_pending");
    b.classList.add("dis");
    b.onclick = null;
  } else {
    b.textContent = "＋ " + T("qr_btn");
    b.classList.remove("dis");
    b.onclick = openQuotaCard;
  }
}
function openQuotaCard(){
  if (el("qrOverlay")) return;
  const ov = document.createElement("div");
  ov.id = "qrOverlay";
  const planes = [["both", T("qr_p_both")], ["agent", T("qr_p_agent")], ["sim", T("qr_p_sim")]];
  const amounts = [10, 25, 50];
  ov.innerHTML = `<div class="guide-card" style="max-width:420px">
    <h3>💳 ${escHtml(T("qr_title"))}</h3>
    <p style="margin-bottom:10px">${escHtml(T("qr_body"))}</p>
    <div class="tq-q">${escHtml(T("qr_plane"))}</div>
    <div class="tq-opts">${planes.map(([v, lab], i) => `<label><input type="radio" name="qrp" value="${v}" ${i === 0 ? "checked" : ""}/><span>${escHtml(lab)}</span></label>`).join("")}</div>
    <div class="tq-q">${escHtml(T("qr_amount"))}</div>
    <div class="tq-opts">${amounts.map((a, i) => `<label><input type="radio" name="qra" value="${a}" ${i === 0 ? "checked" : ""}/><span>+$${a}</span></label>`).join("")}</div>
    <textarea id="qrNote" rows="2" placeholder="${escAttr(T("qr_note_ph"))}" style="width:100%;margin-top:10px;font:12.5px var(--font);border:1px solid var(--border);border-radius:9px;padding:7px 10px;background:var(--surface);color:var(--text);resize:none"></textarea>
    <div class="guide-row" style="margin-top:12px">
      <button class="guide-never" id="qrCancel">${escHtml(T("close"))}</button>
      <button class="guide-ok" id="qrSubmit">${escHtml(T("qr_submit"))}</button>
    </div></div>`;
  document.body.appendChild(ov);
  ov.addEventListener("click", e => { if (e.target === ov) ov.remove(); });
  ov.querySelector("#qrCancel").onclick = () => ov.remove();
  ov.querySelector("#qrSubmit").onclick = async () => {
    const plane = ov.querySelector('input[name="qrp"]:checked').value;
    const amount = +ov.querySelector('input[name="qra"]:checked').value;
    const note = el("qrNote").value.trim();
    try {
      const r = await fetch(api.apiUrl("api/quota-request"), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plane, amount, note }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok){ toast(T("qr_ok"), "ok"); ov.remove(); refreshQuotaReqBtn(); }
      else toast(d.error === "pending_exists" ? T("qr_dup") : (d.error || "error"), "err");
    } catch(e){ toast("error", "err"); }
  };
}

// ── quick actions (chat shortcuts that change with the current tab) ─────────────
const QA = {
  environment: [["qa_env_event", {zh:"在环境中新增一个事件：在第 N 步，（描述事件内容与影响范围）", en:"Add an event to the environment: at step N, (describe the event and its scope)"}],
                ["qa_env_upload", {zh:"请读取我在 uploads/ 里上传的文件，把其中的相关信息纳入环境构建。", en:"Please read the file(s) I uploaded under uploads/ and incorporate the relevant information into the environment."}]],
  population:  [["qa_pop_adjust", {zh:"调整人群抽样：（例如 把人数改为 200 / 提高某类画像的占比 / 换成某城市的真实人口分布）", en:"Adjust the population sampling: (e.g. set N to 200 / raise the share of a persona / align to city X demographics)"}]],
  experiments: [["qa_run_fork", {zh:"在当前研究上添加一条干预并分支：（说明干预，例如 在第 5 步加入政策 X），跑完后与来源版本同图做对照/处理对比。", en:"Add an intervention to the current study and branch it: (describe the intervention, e.g. policy X at step 5), then compare control vs treatment on one chart."}]],
  paper:       [["qa_paper_draft", {zh:"请先做一轮文献调研（若尚未做过），再基于本研究的报告与数据起草完整论文（摘要/引言/相关工作/方法/结果/讨论），落到 paper/paper.md。", en:"Survey the related work first (if not done yet), then draft the full paper (abstract/intro/related work/methods/results/discussion) from this study's report and data, into paper/paper.md."}],
                ["qa_report_redo", {zh:"请完善阶段报告：（说明想强化的部分，例如 增加对比分析 / 更多图表）", en:"Refine the stage report: (what to strengthen, e.g. more comparative analysis / figures)"}]],
  literature:  [["qa_lit_survey", {zh:"请围绕本研究的研究问题做一轮文献调研：检索真实论文，逐篇写相关性笔记，生成 literature/literature.json 与 references.bib。", en:"Survey related work for this study's research question: retrieve real papers, write per-paper relevance notes, produce literature/literature.json and references.bib."}]],
  dataset:     [],
  overview:    [],
};
export function renderQuickActions(){
  const row = el("quickRow"); if (!row || !CHAT.enabled) return;
  const items = QA[S.tab] || [];
  row.innerHTML = items.map(([k, tpl], i) => `<span class="qa" data-i="${i}">⚡ ${escHtml(T(k))}</span>`).join("");
  row.querySelectorAll(".qa").forEach(n => n.onclick = () => {
    const tpl = items[+n.dataset.i][1];
    chatPrefill(tpl[getLang()] || tpl.zh);
  });
}

// ── guide overlay (first visit to a new study) ──────────────────────────────
let GUIDE_SHOWN = false;
function showNewGuide(){
  if (GUIDE_SHOWN) return;
  if (el("noticeOverlay") || el("tourOv")) return;   // the upgrade notice / tour take priority; the SSE poll retries this guide after they end
  try { if (localStorage.getItem("sv_newguide_never") === "1") return; } catch(e){}
  if (el("guideOverlay")) return;
  GUIDE_SHOWN = true;
  const ov = document.createElement("div"); ov.id = "guideOverlay";
  ov.innerHTML = `<div class="guide-card">
    <h3>💡 ${escHtml(T("guide_title"))}</h3>
    <p>${escHtml(T("guide_body"))}</p>
    <div class="guide-row">
      <button class="guide-never" id="guideNever">${escHtml(T("guide_never"))}</button>
      <button class="guide-ok" id="guideOk">${escHtml(T("guide_ok"))}</button>
    </div></div>`;
  document.body.appendChild(ov);
  const close = () => { ov.remove(); try { el("chatInput")?.focus(); } catch(e){} };
  ov.querySelector("#guideOk").onclick = close;
  ov.querySelector("#guideNever").onclick = () => { try { localStorage.setItem("sv_newguide_never", "1"); } catch(e){} close(); };
  ov.addEventListener("click", e => { if (e.target === ov) close(); });
}
export function applyNewGlow(){
  if (inCompose()) return;   // the compose state has its own hero + example cards; do not stack a "how to start" popup on top
  // Also skip it once the first message is sent (compose state just ended, study not set up yet): the user has already "started",
  // and the popup would only appear after they typed, to teach them how to type — the center pane's intent checklist now does the guiding.
  if (CHAT.started) return;
  showNewGuide();
  document.body.classList.remove("chat-hidden"); el("chatFab").style.display = "none";
  const ci = el("chatInput"); if (!ci || !CHAT.enabled) return;
  ci.classList.add("glow");
  ci.addEventListener("input", () => ci.classList.remove("glow"), { once:true });
}

// transcript level switch: after a change, replay this study's history and re-render at the new level
window.__svChat = window.__svChat || {};
window.__svChat.renderVseg = () => renderVseg();
export function renderVseg(){
  const seg = el("vseg"); if (!seg) return;
  const v = getVerbosity();
  seg.title = T("verb_title");
  seg.innerHTML = [["simple","verb_s"],["standard","verb_m"],["dev","verb_d"]]
    .map(([k, lab]) => `<i class="${k === v ? "on" : ""}" data-v="${k}" title="${escAttr(T("verb_" + k))}">${escHtml(T(lab))}</i>`).join("");
  seg.querySelectorAll("i").forEach(n => n.onclick = () => {
    if (n.dataset.v === getVerbosity()) return;
    setVerbosity(n.dataset.v);
    renderVseg();
    const cur = CHAT.study;
    if (cur){ CHAT.study = "__switching__"; chatSubscribe(cur); }   // replay the history rendered at the new level
  });
}

export async function initChat(){
  el("gatePin").onclick = jumpToGate;
  try {
    // local server: no chat plane to probe (the dock is hidden by body.sv-local)
    if (isLocal()) throw 0;
    const jj = await api.chatPing();
    if (!jj.ok) throw 0;
  } catch(e){
    // local zero-dependency form / static gallery: no chat plane → the dock shows a note and disables input
    S.chatEnabled = false;
    el("chatLog").innerHTML = `<div class="cline" style="padding:8px 4px">${escHtml(T("local_mode"))}</div>`;
    el("chatInput").disabled = true; el("chatSend").disabled = true; el("attachBtn").disabled = true;
    return;
  }
  S.chatEnabled = true; CHAT.enabled = true;
  renderVseg();
  el("chatInput").placeholder = T("chat_placeholder");
  el("chatSend").onclick = sendChat;
  initUpload();
  el("chatInput").addEventListener("keydown", e => {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); sendChat(); } });
  if (S.cur) chatSubscribe(S.cur);
  else if (S.newmode) chatSubscribe("__new__");
  // On first paint the order is loadState → initChat; chatEnabled is still false then, so the compose check in loadState
  // always misses; do it once more here, otherwise the new-study page would first show the old three-pane layout.
  if (S.newmode){ setCompose(!CHAT.started); applyNewGlow(); }
  refreshQuota();
  renderQuickActions();
}
