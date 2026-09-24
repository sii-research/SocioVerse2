// ── workbench conductor: shell, router, state loading, SSE, theme/lang ──────
import { S, bus, emit, on, isLocal } from "./store.js";
import { T, ST, loc, setLang, getLang } from "./i18n.js";
import { el, escHtml, escAttr, cssv, toast, openLightbox, withTransition, debounce } from "./ui.js";
import * as api from "./api.js";
import { initChat, chatSubscribe, applyNewGlow, CHAT, updateGatePin, renderQuickActions, renderVseg } from "./chat.js";
import { startTour, tourDone, TOUR_NOTICE, onTourEnd } from "./tour.js";
import * as tabOverview from "./tabs/overview.js";
import * as tabEnvironment from "./tabs/environment.js";
import * as tabPopulation from "./tabs/population.js";
import * as tabDataset from "./tabs/dataset.js";
import * as tabExperiments from "./tabs/experiments.js";
import * as tabPaper from "./tabs/paper.js";
import * as tabLiterature from "./tabs/literature.js";
import { intentHtml } from "./tabs/common.js";

window.__lightbox = openLightbox;   // md.js figure onclick hook

// ── tabs registry ───────────────────────────────────────────────────────────
const TABS = {
  overview: tabOverview, environment: tabEnvironment, population: tabPopulation,
  dataset: tabDataset, experiments: tabExperiments, paper: tabPaper, literature: tabLiterature,
};
const TAB_ORDER = ["overview","environment","population","dataset","experiments","paper","literature"];
export const STAGE_TAB = { "sv-init":"overview", "sv-build-model":"overview",
  "sv-build-environment":"environment", "sv-build-population":"population",
  "sv-run":"experiments", "sv-report":"paper" };
const TAB_STAGES = { overview:["sv-init","sv-build-model"], environment:["sv-build-environment"],
  population:["sv-build-population"], experiments:["sv-run"], paper:["sv-report"] };

const ICONS = {
  overview: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/></svg>',
  environment: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.3 4 5.2 4 8.5s-1.4 6.2-4 8.5c-2.6-2.3-4-5.2-4-8.5s1.4-6.2 4-8.5z"/></svg>',
  population: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8.5" r="3.5"/><path d="M3 19.5c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9.5" r="2.6"/><path d="M15.6 13.7c2.9.4 5.1 2.6 5.4 5.4"/></svg>',
  dataset: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/></svg>',
  experiments: '<svg viewBox="0 0 24 24"><path d="M9.5 3.5h5M10.5 3.5v5.2L5 18a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5.5-9.3V3.5M7.5 14.5h9"/></svg>',
  paper: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4v13a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 20.5v-15A1.5 1.5 0 0 1 6.5 3.5zM14 3.5V8h4.5M8.5 12.5h7M8.5 16h7"/></svg>',
  literature: '<svg viewBox="0 0 24 24"><path d="M12 6.5c-1.5-1.6-3.7-2.5-6-2.5-1 0-2 .2-3 .5v15c1-.3 2-.5 3-.5 2.3 0 4.5.9 6 2.5 1.5-1.6 3.7-2.5 6-2.5 1 0 2 .2 3 .5V4.5c-1-.3-2-.5-3-.5-2.3 0-4.5.9-6 2.5zM12 6.5v15"/></svg>',
};

// ── persisted prefs ─────────────────────────────────────────────────────────
let THEME = "light";
try {
  setLang(localStorage.getItem("sv_lang") || (((navigator.language||"").toLowerCase().startsWith("zh")) ? "zh" : "en"));
  THEME = localStorage.getItem("sv_theme") || "light";
} catch(e){}

export function applyChrome(){
  document.documentElement.classList.toggle("dark", THEME === "dark");
  document.documentElement.lang = getLang() === "zh" ? "zh" : "en";
  document.querySelectorAll("[data-i18n]").forEach(n => { n.textContent = T(n.dataset.i18n); });
  // data-tip uses our own hover label (instant, themeable); a native title shows after ~1s and cannot be styled
  document.querySelectorAll("[data-i18n-title]").forEach(n => {
    n.dataset.tip = T(n.dataset.i18nTitle);
    n.removeAttribute("title");
  });
  el("themeBtn").textContent = THEME === "dark" ? "☀" : "☾";
  el("themeBtn").dataset.tip = T(THEME === "dark" ? "theme_to_light" : "theme_to_dark");
  el("langBtn").textContent = getLang() === "zh" ? "EN" : "中";
  // the tip is written in the target language, so the result of switching is obvious
  el("langBtn").dataset.tip = getLang() === "zh" ? "Switch to English" : "切换为中文";
  try { if (S.chatEnabled){ el("chatInput").placeholder = T(inCompose() ? "cp_ph" : "chat_placeholder"); } } catch(e){}
  try { if (inCompose()) renderCompose(); } catch(e){}
  renderNav();
  updateTitleBar();
  syncAwaitTitle();
}

// Without the chat dock (local server) the tab title is the only "Claude Code is waiting for
// you" signal: the Stop / AskUserQuestion hooks set /api/state.awaiting, the reply clears it.
// With chat enabled, chat.js updateGatePin owns the title (gate cards win over this).
function syncAwaitTitle(){
  if (S.chatEnabled || S.newmode) return;
  document.title = S.awaiting ? T("await_title") : T("doc_title");
}

// ── hover labels: every element with data-tip gets one automatically ─────────────
// A fixed overlay instead of ::after — #rail has backdrop-filter, which creates a stacking context,
// so a pseudo-element bubble would be covered by the main area or clipped at the rail edge. Events are
// delegated to document, so buttons injected later (the hosted side's feedback entry) work without extra wiring.
function initTips(){
  const tip = document.createElement("div");
  tip.id = "tipBox";
  document.body.appendChild(tip);
  const hide = () => tip.classList.remove("on");
  document.addEventListener("mouseover", e => {
    const n = e.target.closest && e.target.closest("[data-tip]");
    if (!n || !n.dataset.tip){ hide(); return; }
    tip.textContent = n.dataset.tip;
    tip.classList.add("on");
    const r = n.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    // centered horizontally on the button but clamped to the viewport; above by default, flipped below when there is no room on top
    tip.style.left = Math.max(6, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 6)) + "px";
    tip.style.top = (r.top - h - 8 >= 6 ? r.top - h - 8 : r.bottom + 8) + "px";
  });
  document.addEventListener("mouseout", e => {
    if (e.target.closest && e.target.closest("[data-tip]")) hide();
  });
  addEventListener("scroll", hide, true);
  addEventListener("blur", hide);
}

// ── nav rail ────────────────────────────────────────────────────────────────
function tabBadge(t){
  const d = S.detail;
  // live chat signals win: awaiting gate / running stage on this tab
  if (S.chatEnabled && CHAT.liveStage && STAGE_TAB[CHAT.liveStage] === t){
    if (CHAT.gatePending) return `<span class="nb await">⏸</span>`;
    if (CHAT.liveRunning) return `<span class="nb run"></span>`;
  }
  if (!d) return "";
  const names = TAB_STAGES[t];
  if (names){
    const ss = d.stages.filter(s => names.includes(s.name) && s.status !== "skipped");
    if (!ss.length) return "";
    if (ss.some(s => s.status === "stale"))  return `<span class="nb stale">!</span>`;
    if (ss.some(s => s.status === "review")) return `<span class="nb review">·</span>`;
    if (ss.every(s => ["done","inherited"].includes(s.status)))
      return `<span class="nb done"><svg width="9" height="9" viewBox="0 0 18 18"><path d="M4 9.5l3.2 3.2L14 5.8" stroke="#fff" stroke-width="2.6" fill="none" stroke-linecap="round"/></svg></span>`;
    if (ss.some(s => s.active)) return `<span class="nb run"></span>`;
    return `<span class="nb pend"></span>`;
  }
  if (t === "dataset")    return (d.stages.find(s => s.name === "sv-run")?.status === "done") ? `<span class="nb dot"></span>` : "";
  if (t === "literature") return d.literature_info?.exists ? `<span class="nb dot"></span>` : "";
  return "";
}
function renderNav(){
  const nav = el("nav");
  const items = TAB_ORDER.map(t =>
    `<div class="nav-it ${S.tab === t ? "on" : ""}" data-tab="${t}" title="${escAttr(T("nav_" + t))}">
       <span class="ic">${ICONS[t]}</span><span class="nm">${escHtml(T("nav_" + t))}</span>
       <span class="bdg">${tabBadge(t)}</span></div>`).join("");
  nav.innerHTML = `<div class="nav-ind" id="navInd"></div>` + items;
  nav.querySelectorAll(".nav-it").forEach(n => n.onclick = () => switchTab(n.dataset.tab));
  requestAnimationFrame(moveNavInd);
}
function moveNavInd(){
  const ind = el("navInd"), act = document.querySelector(`.nav-it[data-tab="${S.tab}"]`);
  if (!ind || !act) return;
  ind.style.transform = `translateY(${act.offsetTop - 2}px)`;
  ind.style.height = act.offsetHeight + "px";
  ind.classList.add("show");
}

window.__svSwitchTab = (t, o) => switchTab(t, o);   // bridge for tour.js to switch stops
export function switchTab(t, opts = {}){
  if (!TABS[t]) return;
  const changed = S.tab !== t;
  S.tab = t;
  try { history.replaceState(null, "", `${location.pathname}${location.search}#/${t}`); } catch(e){}
  document.querySelectorAll(".nav-it").forEach(n => n.classList.toggle("on", n.dataset.tab === t));
  moveNavInd();
  if (changed) pulseAnim();
  const doRender = () => { renderView(); el("view").scrollTop = 0; };
  if (changed && !opts.instant) withTransition(doRender); else doRender();
  renderQuickActions();
}

function renderView(){
  const v = el("view");
  if (S.newmode){ renderNewMode(v); return; }
  delete v.dataset.mode;
  if (!S.detail){ v.innerHTML = `<div class="card"><div class="skel" style="height:130px"></div></div>`; return; }
  try { TABS[S.tab].render(v); } catch(err){ console.error(err); v.innerHTML = `<div class="card note coral">render error: ${escHtml(String(err))}</div>`; }
  injectTabIntro(v);
}

// ── one-line intro at the top of each tab (what this step does, input → output); dismissible and remembered ──
function injectTabIntro(v){
  const t = S.tab;
  let off = false; try { off = localStorage.getItem("sv2_intro_" + t) === "0"; } catch(e){}
  if (off) return;
  const key = "intro_" + t;
  const txt = T(key);
  if (txt === key) return;
  v.insertAdjacentHTML("afterbegin",
    `<div class="tabintro">💡 <span>${escHtml(txt)}</span><i class="ti-x" title="${escAttr(T("close"))}">✕</i></div>`);
  v.querySelector(".ti-x").onclick = () => {
    try { localStorage.setItem("sv2_intro_" + t, "0"); } catch(e){}
    v.querySelector(".tabintro").remove();
  };
}

// The live intent checklist before a study is set up: as soon as sv-init Step −1 starts asking, the center pane switches
// from the blank canvas to checklist cards, and follows every item the agent updates — the user sees "what is aligned, what is still open".
function intentLive(){
  const it = S.state && S.state.intent;
  if (!it || !Array.isArray(it.items) || !it.items.length) return null;
  if (it.ts && Date.now() / 1000 - it.ts > 6 * 3600) return null;   // do not render stale leftovers
  return it;
}
function renderNewMode(v){
  const intent = intentLive();
  // the signature covers the whole checklist (minus ts — it changes on every resend; unchanged content should not replay the animation):
  // do not rebuild when nothing changed (repeated rebuilds during SSE replay flicker)
  const key = "new" + getLang() + (intent ? "§" + JSON.stringify({ ...intent, ts: 0 }) : "");
  if (v.dataset.mode === key) return;
  v.dataset.mode = key;
  if (intent){
    v.innerHTML = `<div class="card rise" style="margin-top:4vh;max-width:640px;margin-left:auto;margin-right:auto">
      ${intentHtml(intent, "live")}</div>`;
    return;
  }
  v.innerHTML = `<div class="empty card rise" style="margin-top:8vh;max-width:560px;margin-left:auto;margin-right:auto">
    <div class="e-ic">✨</div>
    <div class="e-t">${escHtml(T("new_study_title"))}</div>
    <div class="e-s">${escHtml(T("new_study_rq"))}</div></div>`;
}

// ── compose state: before a new study sends its first message, the center + right panes merge into one centered input box ──
//    It exits on the first message sent (or on any user message replayed over SSE), back to the three-pane layout.
//    Only one class on body is toggled: #chatDock itself stays put; subscriptions / uploads / gates work as before.
export function setCompose(on){
  const now = document.body.classList.contains("compose");
  if (on === now) return;
  document.body.classList.toggle("compose", on);
  try { if (S.chatEnabled) el("chatInput").placeholder = T(on ? "cp_ph" : "chat_placeholder"); } catch(e){}
  if (on){
    document.body.classList.remove("chat-hidden");
    el("chatFab").style.display = "none";
    renderCompose();
    setTimeout(() => { try { el("chatInput").focus(); } catch(e){} }, 60);
  }
  setTimeout(() => renderView(), 320);   // column width changed → redraw charts at the new width
}
export const inCompose = () => document.body.classList.contains("compose");

const STARTERS = ["cp_s1", "cp_s2", "cp_s3"];
function renderCompose(){
  el("composeHero").innerHTML = `<div class="ch-hero">
    <div class="chh-logo">S</div>
    <h2>${escHtml(T("cp_title"))}</h2>
    <p>${escHtml(T("cp_sub"))}</p></div>`;
  const st = el("composeStarters");
  st.innerHTML = `<div class="cs-lbl">${escHtml(T("cp_starters"))}</div>
    <div class="cs-grid">${STARTERS.map(k =>
      `<div class="cs-card" data-k="${k}"><b>${escHtml(T(k + "_t"))}</b>${escHtml(T(k))}</div>`).join("")}</div>`;
  st.querySelectorAll(".cs-card").forEach(n => n.onclick = () => {
    const ta = el("chatInput");
    ta.value = T(n.dataset.k);
    ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
  });
}

// ── drag to resize the chat column ─────────────────────────────────────────────
//    Written to the inline --chat-w on :root (overriding the clamp default in styles.css) and saved to localStorage.
//    Double-clicking the handle clears the inline value and restores the default. Charts are not redrawn while dragging (too costly), only on release.
const CHATW_KEY = "sv2_chatw";
const clampChatW = px => Math.max(320, Math.min(px, Math.round(innerWidth * 0.62)));
function applyChatW(px){ document.documentElement.style.setProperty("--chat-w", px + "px"); }
function initChatResize(){
  let saved = NaN; try { saved = parseInt(localStorage.getItem(CHATW_KEY) || "", 10); } catch(e){}
  if (saved > 0) applyChatW(clampChatW(saved));
  const h = el("chatResize"); if (!h) return;
  h.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    h.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing");
    const move = ev => applyChatW(clampChatW(Math.round(innerWidth - ev.clientX)));
    const up = () => {
      h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing");
      const w = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--chat-w"), 10);
      if (w > 0){ try { localStorage.setItem(CHATW_KEY, String(w)); } catch(e){} }
      renderView();
    };
    h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
  });
  h.addEventListener("dblclick", () => {
    document.documentElement.style.removeProperty("--chat-w");
    try { localStorage.removeItem(CHATW_KEY); } catch(e){}
    setTimeout(() => renderView(), 320);
  });
}

// ── topbar ──────────────────────────────────────────────────────────────────
function updateTitleBar(){
  const d = S.detail;
  if (S.newmode || !d){
    el("title").textContent = S.newmode ? T("new_study_title") : "—";
    el("badges").innerHTML = "";
    el("statusPill").textContent = S.newmode ? T("pending_init") : "";
    el("live").innerHTML = "";
    el("verswitcher").style.display = "none"; el("cmpswitcher").style.display = "none";
    document.title = T("doc_title");
    return;
  }
  el("title").textContent = loc(d.title_i18n, d.title);
  el("title").title = loc(d.research_question_i18n, d.research_question) || "";
  const badges = [];
  badges.push(`<span class="pill" style="background:var(--accent-bg);color:var(--accent)">${escHtml(d.path_label || "")}</span>`);
  if (d.forked_from) badges.push(`<span class="pill" style="background:var(--amber-bg);color:var(--amber)">${escHtml(T("forked"))} · ${escHtml(d.forked_from)}</span>`);
  if (d.archived) badges.push(`<span class="pill" style="background:var(--purple-bg);color:var(--purple)">${escHtml(d.viewing_version)} · ${escHtml(T("archived_ro"))}</span>`);
  el("badges").innerHTML = badges.join("");
  renderStatusPill(d);
  renderVersionSelects(d);
}

function renderStatusPill(d){
  const st = el("statusPill");
  const run = d.stages.find(s => s.name === "sv-run");
  const active = d.stages.find(s => s.active);
  const set = (html, bg, col) => { st.innerHTML = html; st.style.background = cssv(bg); st.style.color = cssv(col); };
  if (S.chatEnabled && CHAT.gatePending){ set(`⏸ ${escHtml(T("gate_head"))}`, "--amber-bg", "--amber"); return; }
  if (d.archived){
    if (run.status === "done" && !active) set(escHtml(T("complete")) + " · " + d.viewing_version, "--teal-bg", "--teal");
    else set(`${d.viewing_version} · ${escHtml(T("archived_at"))} ${active ? stageName(active.name) : "—"}`, "--purple-bg", "--purple");
    return;
  }
  if (run.status === "done" && !active) set(escHtml(T("complete")), "--teal-bg", "--teal");
  else if (active && active.status === "stale") set(escHtml(T("stale_rerun")) + " " + stageName(active.name), "--surface-2", "--coral");
  else if (active && active.status === "inherited") set(`${escHtml(T("forked"))} · ${escHtml(T("resume_at"))} ${stageName(active.name)}`, "--amber-bg", "--amber");
  else if (active && active.status === "review") set(`${d.current_version} · ${escHtml(ST("review"))} ${stageName(active.name)}`, "--amber-bg", "--amber");
  else if (active){
    const liveRun = active.name === "sv-run" && d.progress;
    if (!liveRun && d.current_version && d.current_version !== "v1")
      set(`${d.current_version} · ${escHtml(T("resume_at"))} ${stageName(active.name)}`, "--accent-bg", "--accent");
    else {
      const ex = (active.name === "sv-run" && d.progress) ? ` · step ${d.progress.step}/${d.progress.n_steps || d.n_steps}` : "";
      set(`<span class="dot pulse" style="background:${cssv("--accent")}"></span> ${escHtml(T("running"))} · ${stageName(active.name)}${ex}`, "--accent-bg", "--accent");
    }
  }
  else set(escHtml(T("idle")), "--surface-2", "--muted");
  el("live").innerHTML = (S.state && S.state.session_active) ? `<span class="dot pulse" title="session active" style="background:var(--teal)"></span>` : "";
}

export const STAGE_META = {
  "sv-init":{n:1,k:"stage_init"}, "sv-build-model":{n:2,k:"stage_model"},
  "sv-build-environment":{n:3,k:"stage_env"}, "sv-build-population":{n:4,k:"stage_pop"},
  "sv-run":{n:5,k:"stage_run"}, "sv-report":{n:6,k:"stage_report"},
  "sv-lit":{n:"·",k:"nav_literature"}, "sv-paper":{n:"·",k:"nav_paper"},   // extension stages: friendly names for the event feed / chips
};
export const stageName = n => STAGE_META[n] ? T(STAGE_META[n].k) : n;

function renderVersionSelects(d){
  const vs = d.versions && d.versions.length ? d.versions : [{id:"v1", note:"", current:true}];
  const sw = el("verswitcher");
  sw.style.display = "";
  sw.innerHTML = vs.map(v => {
    const label = v.id + (v.note ? " · " + v.note.slice(0, 30) : "") + (v.current ? T("current_tag") : "");
    return `<option value="${v.id}">${escHtml(label)}</option>`;
  }).join("");
  sw.value = d.viewing_version || "v1";
  sw.disabled = vs.length <= 1;
  const cs = el("cmpswitcher");
  cs.style.display = "";
  const others = vs.filter(v => v.id !== (d.viewing_version || "v1"));
  cs.innerHTML = `<option value="">${escHtml(T("cmp_none"))}</option>` +
    others.map(v => `<option value="${v.id}">${escHtml(T("cmp") + v.id + (v.note ? " · " + v.note.slice(0, 22) : ""))}</option>`).join("");
  cs.value = S.cmp || "";
  cs.disabled = others.length === 0;
}

// ── state / study loading (port of the battle-tested v1 flow) ───────────────
export async function loadState(){
  let s;
  try { s = await api.getState(); } catch(e){ return; }
  S.state = s;
  S.awaiting = !!s.awaiting;
  if (isLocal()) document.body.classList.add("sv-local");   // normally already stamped by the server
  syncAwaitTitle();
  if (S.newmode){
    // the only way out of NEWMODE = the adopted event (a study was really set up in this session) — see the v1 hijack fix
    el("switcher").innerHTML = `<option>${escHtml(T("new_study_title"))}</option>`;
    updateTitleBar(); renderNav();
    try { if (S.chatEnabled) chatSubscribe("__new__"); } catch(e){}
    // no first message sent yet → compose state (centered input box); CHAT.started is set by chat.js.
    // Must come before applyNewGlow: the compose state has its own guidance, so the old popup layer gives way.
    setCompose(S.chatEnabled && !CHAT.started);
    try { if (S.chatEnabled) applyNewGlow(); } catch(e){}
    renderView();
    return;
  }
  setCompose(false);
  const sw = el("switcher");
  const swSig = getLang() + "§" + JSON.stringify(s.studies.map(x => [x.study_id, x.title, x.progress, x.version]));
  if (swSig !== S.swSig){   // do not rebuild when the list is unchanged (a rebuild would collapse an open dropdown)
    S.swSig = swSig;
    sw.innerHTML = s.studies.map(x =>
      `<option value="${x.study_id}">${escHtml(loc(x.title_i18n, x.title))} (${x.progress.done}/${x.progress.total}${x.version && x.version.count > 1 ? ` · ${x.version.current}` : ""})</option>`).join("");
  }
  if (!S.cur){
    let saved = null; try { saved = localStorage.getItem("sv_study"); } catch(e){}
    if (saved === "__new__"){
      try { localStorage.removeItem("sv_study"); } catch(e){}
      // a new study is composed in the hosted chat; locally /sv-init in Claude Code creates it
      if (!isLocal()){ S.newmode = true; return loadState(); }
      saved = null;
    }
    S.cur = (saved && s.studies.some(x => x.study_id === saved)) ? saved : s.current_id;
  }
  sw.value = S.cur;
  await loadStudy(S.cur);
}

// the entry animation plays only on a real switch: body.anim is added briefly, so SSE-driven rebuilds do not flicker
let ANIMT = null;
export function pulseAnim(){
  document.body.classList.add("anim");
  clearTimeout(ANIMT);
  ANIMT = setTimeout(() => document.body.classList.remove("anim"), 750);
}

// During an SSE storm loadStudy is re-entered concurrently (turn-done / obs-event / the 15s poll each trigger it).
// In the old implementation every instance first set S.cmpDetail to null and filled it back asynchronously, so interleaved
// runs made the render flip back and forth between "comparison dashed line / no dashed line". Sequence guard: only the latest call lands.
let LOADSEQ = 0;
export async function loadStudy(id){
  if (!id) return;
  const seq = ++LOADSEQ;
  const changed = S.cur !== id;
  S.cur = id;
  try { localStorage.setItem("sv_study", id); } catch(e){}
  try { if (S.chatEnabled) chatSubscribe(id); } catch(e){}
  if (changed){ S.ver = null; S.cmp = null; S.cmpDetail = null; S.agentSel = null; }
  let d;
  try { d = await api.getDetail(id, S.ver); } catch(e){ return; }
  if (seq !== LOADSEQ) return;   // a newer load is already running; drop this one
  S.detail = d;
  const cv = d.current_version || "v1";
  const prev = S.lastVer[id];
  S.lastVer[id] = cv;
  if (prev && prev !== cv && S.ver && S.ver === prev){ S.ver = null; return loadStudy(id); }   // auto-jump to a freshly created version
  if (S.ver === cv) S.ver = null;
  if (S.cmp && (S.cmp === d.viewing_version || !(d.versions || []).some(v => v.id === S.cmp))) S.cmp = null;
  // comparison baseline is stale-while-revalidate: keep the old value until new data arrives, do not clear it first (if the
  // clear → refetch window ever gets rendered, the user sees "the dashed line blinked out")
  if (!S.cmp) S.cmpDetail = null;
  else {
    try {
      const cd = await api.getDetail(id, S.cmp === d.current_version ? null : S.cmp);
      if (seq !== LOADSEQ) return;
      S.cmpDetail = cd;
    } catch(e){ S.cmpDetail = null; }
  }
  // agents snapshot rides along (tabs decide whether to show)
  try { S.agents = await api.getAgents(id, S.ver); } catch(e){ S.agents = null; }
  if (seq !== LOADSEQ) return;
  const view = id + "@" + (d.viewing_version || "v1");
  const viewChanged = S.lastView !== view;
  if (viewChanged){ S.lastView = view; }
  // ── the core of flicker prevention: skip re-rendering entirely when the data has not changed ──
  // SSE changed/ingest broadcasts cover every study, so writes to other studies and lifecycle signals all land here;
  // a full rebuild replays animations / refetches images and looks like "abnormal flicker". Signature = this study's full detail +
  // a light agents summary + the comparison state; when it matches, only the in-memory references are updated and the DOM is left alone.
  const ag = S.agents;
  const sig = JSON.stringify(d) + "§" + (ag ? `${ag.count}|${(ag.steps || []).length}|${ag.phase}` : "") +
    "§" + (S.cmp || "") + (S.cmpDetail ? "|" + ((S.cmpDetail.metrics_rows || []).length) : "");
  if (!changed && !viewChanged && sig === S.lastSig) return;
  S.lastSig = sig;
  if (changed || viewChanged) pulseAnim();
  emit("detail", d);
  updateTitleBar(); renderNav();
  const keep = el("view").scrollTop;
  renderView();
  if (!changed) el("view").scrollTop = keep;   // an SSE refresh does not disturb the reading position
}

// ── boot ────────────────────────────────────────────────────────────────────
function initShell(){
  // deep link: ?study= → selection; #/tab → tab
  try { const q = new URLSearchParams(location.search).get("study"); if (q) localStorage.setItem("sv_study", q); } catch(e){}
  const m = (location.hash || "").match(/^#\/(\w+)/);
  if (m && TABS[m[1]]) S.tab = m[1];
  window.addEventListener("hashchange", () => {
    const mm = (location.hash || "").match(/^#\/(\w+)/);
    if (mm && TABS[mm[1]] && mm[1] !== S.tab) switchTab(mm[1], { instant: true });
  });

  el("switcher").onchange = e => { S.agentSel = null; loadStudy(e.target.value); };
  el("verswitcher").onchange = e => {
    const v = e.target.value;
    S.ver = (S.detail && v === S.detail.current_version) ? null : v;
    loadStudy(S.cur);
  };
  el("cmpswitcher").onchange = e => { S.cmp = e.target.value || null; loadStudy(S.cur); };
  el("themeBtn").onclick = () => {
    THEME = THEME === "dark" ? "light" : "dark";
    try { localStorage.setItem("sv_theme", THEME); } catch(e){}
    pulseAnim(); applyChrome(); renderView();
  };
  el("langBtn").onclick = () => {
    setLang(getLang() === "zh" ? "en" : "zh");
    try { localStorage.setItem("sv_lang", getLang()); } catch(e){}
    pulseAnim(); applyChrome(); renderView(); renderQuickActions();
  };
  el("brandHome").onclick = () => location.href = "/";
  el("tourBtn").onclick = () => startTour({ force: true });   // the classic v1 view is still reachable at /app/v1; it just no longer takes a rail slot
  initTips();
  initChatResize();
  onTourEnd(spotlightNewStudy);

  // chat collapse / fab
  const setChat = hidden => {
    document.body.classList.toggle("chat-hidden", hidden);
    el("chatFab").style.display = hidden ? "flex" : "none";
    try { localStorage.setItem("sv2_chat", hidden ? "0" : "1"); } catch(e){}
    setTimeout(() => renderView(), 300);   // column width changed → redraw charts at the new width
  };
  el("chatCollapse").onclick = () => setChat(true);
  el("chatToggle").onclick  = () => setChat(!document.body.classList.contains("chat-hidden"));
  el("chatFab").onclick     = () => setChat(false);
  let chatPref = "1"; try { chatPref = localStorage.getItem("sv2_chat") ?? "1"; } catch(e){}
  if (chatPref === "0" || window.innerWidth < 980) setChat(true);

  window.addEventListener("resize", debounce(() => renderView(), 200));
  document.addEventListener("keydown", e => {
    if (e.altKey && !e.ctrlKey && !e.metaKey){
      const i = parseInt(e.key, 10);
      if (i >= 1 && i <= TAB_ORDER.length){ e.preventDefault(); switchTab(TAB_ORDER[i-1]); }
    }
  });
}

on("chatlive", () => { renderNav(); if (S.detail) renderStatusPill(S.detail); });
on("adopted", ns => {   // sv-init set up a study: the session has moved to the new study
  S.newmode = false; S.cur = ns;
  try { localStorage.setItem("sv_study", ns); } catch(e){}
  try { history.replaceState(null, "", `/app/v2/?study=${encodeURIComponent(ns)}${location.hash || ""}`); } catch(e){}
  loadState();
});
on("turn-done", () => loadState());

// ── one-time UI upgrade notice (the server records read state per user; the local cache only suppresses quickly) ──
const NOTICE_ID = "ui-v2-cockpit-202608";
async function checkNotices(){
  // Whether the tour pops up follows the server's per-user read state — localStorage is per browser,
  // so switching accounts on the same machine would be misread as "already seen", and new users would never see the tour.
  // Fall back to localStorage only when that endpoint is unavailable (the local zero-dependency form).
  // The local server has no per-user notices endpoint: go straight to the localStorage path.
  if (isLocal()){ maybeTourLocal(); return; }
  let unread = null;
  try {
    const r = await fetch(api.apiUrl("api/notices"));
    if (r.ok) unread = (await r.json()).unread || [];
  } catch(e){ /* offline / no endpoint */ }

  if (unread === null){ maybeTourLocal(); return; }
  const wantTour = unread.includes(TOUR_NOTICE);
  if (unread.includes(NOTICE_ID)){ showUpgradeNotice(wantTour); return; }  // start the tour after the notice is closed
  if (wantTour) launchTour();
}
function showUpgradeNotice(thenTour){
  if (el("noticeOverlay")) return;
  const ov = document.createElement("div");
  ov.id = "noticeOverlay";
  ov.innerHTML = `<div class="guide-card" style="max-width:470px">
    <h3>🎉 ${escHtml(T("notice_title"))}</h3>
    <p>${escHtml(T("notice_body"))}</p>
    <p style="font-size:12px;color:var(--faint);margin-top:-8px">${escHtml(T("notice_v1"))}</p>
    <div class="guide-row"><span></span>
      <button class="guide-ok" id="noticeOk">${escHtml(T("notice_ok"))}</button>
    </div></div>`;
  document.body.appendChild(ov);
  const close = () => {
    ov.remove();
    try { localStorage.setItem("sv_notice_" + NOTICE_ID, "1"); } catch(e){}
    fetch(api.apiUrl("api/notices/ack"), { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: NOTICE_ID }) }).catch(() => {});
    if (thenTour) launchTour();
    if (S.newmode && S.chatEnabled) applyNewGlow();   // new-study guidance gives way to the upgrade notice and resumes after it is closed
  };
  ov.querySelector("#noticeOk").onclick = close;
}
// The tour needs something to point at: the new-study page is a blank canvas, and all eight stops would land on nothing.
// So when it is triggered on the new-study page, first jump to a finished template study and start there.
// The consumer-confidence backtest comes first: it is the only template whose every month can be checked against the real index published afterwards —
// a new user's first impression should not be "the simulation drew a curve" but "how accurate is this curve, and by how much is it off".
const TOUR_PREFERRED = ["consumer_confidence_us_backtest", "germany_auto_market", "chicago_schelling"];
const TOUR_REDIRECTED = new URLSearchParams(location.search).has("tour");   // jump only once, to rule out loops

function pickTourStudy(){
  const list = (S.state && S.state.studies) || [];
  if (!list.length) return null;
  const hit = TOUR_PREFERRED.find(id => list.some(x => x.study_id === id));
  if (hit) return hit;
  // a local install may not have the templates above: fall back to any fully run study, else the first one
  const done = list.find(x => x.progress && x.progress.total > 0 && x.progress.done === x.progress.total);
  return (done || list[0]).study_id;
}

// start one tick later: let the layout settle, otherwise the first stop's highlight box is measured off-position
function launchTour(){
  if (window.__SV_STATIC) return;
  if ((S.newmode || !S.cur) && !TOUR_REDIRECTED){
    const sid = pickTourStudy();
    if (sid){ location.href = `/app/v2/?study=${encodeURIComponent(sid)}&tour=1`; return; }
  }
  setTimeout(() => startTour(), 300);
}
function maybeTourLocal(){ if (!tourDone()) launchTour(); }

// Right after the tour ends, what the user most likely wants is to start their own first study — but the tour ran on a template study,
// so without a nudge they will not notice where the entry is. So at the end, light up the "New study" button and attach a bubble.
function spotlightNewStudy(){
  const btn = el("navNew");
  if (!btn || btn.offsetParent === null) return;   // hidden (local server): nothing to point at
  document.getElementById("newHint")?.remove();
  btn.classList.remove("hintpulse");
  void btn.offsetWidth;                 // restart the animation (when the tour is opened twice in a row)
  btn.classList.add("hintpulse");
  const b = document.createElement("div");
  b.id = "newHint";
  b.innerHTML = `${escHtml(T("new_hint"))}<span class="nh-x">${escHtml(T("new_hint_x"))}</span>`;
  document.body.appendChild(b);
  const r = btn.getBoundingClientRect();
  b.style.left = Math.min(r.right + 12, innerWidth - b.offsetWidth - 10) + "px";
  b.style.top = Math.max(8, r.top - 6) + "px";
  const kill = () => { b.remove(); btn.classList.remove("hintpulse"); };
  b.onclick = kill;
  btn.addEventListener("click", kill, { once: true });
  setTimeout(kill, 14000);
}
// noticeOverlay uses the same overlay style as guide
const _nstyle = document.createElement("style");
_nstyle.textContent = `#noticeOverlay{position:fixed;inset:0;background:rgba(0,0,0,.38);z-index:650;display:flex;align-items:center;justify-content:center;padding:20px}`;
document.head.appendChild(_nstyle);

initShell();
applyChrome();
loadState().then(() => initChat()).then(() => checkNotices());
setInterval(async () => { try { const s = await api.getState(); S.awaiting = !!s.awaiting; syncAwaitTitle(); } catch(e){} }, 15000);

// observation SSE → debounce reload (+ stage chips into chat handled in chat.js)
let DEB = null;
try {
  const es = api.obsStream();
  es.onmessage = ev => {
    clearTimeout(DEB); DEB = setTimeout(loadState, 250);
    try { const d = JSON.parse(ev.data); emit("obs-event", d); } catch(e){}
  };
} catch(e){ setInterval(loadState, 4000); }
