// ── shared state + event bus (imported by app/chat/tabs; avoids module cycles) ──
export const S = {
  state: null,          // /api/state payload
  cur: null,            // current study id
  ver: null,            // viewing version (null = follow current)
  cmp: null,            // comparison baseline version id (null = off)
  detail: null,         // /api/study/<cur> payload
  cmpDetail: null,
  agents: null,         // agents summary cache (per detail refresh)
  agentSel: null,
  tab: "overview",
  newmode: false,
  chatEnabled: false,
  awaiting: false,
  lastVer: {},          // study → last seen current version (auto-jump)
  lastView: null,
};

// ── deployment form ─────────────────────────────────────────────────────────
// "local" = served from a checkout by dashboard/server/app.py. That server stamps the page with
// <body class="sv-local"> (so styles.css hides hosted-only UI from the first paint) and its
// /api/state reports mode:"local". In local mode the cockpit never calls endpoints only the hosted
// workbench has (chat plane, /api/me, /api/notices). The hosted workbench and the static gallery
// serve the page by other means, carry no marker, and keep the full UI; there the chat dock is
// still feature-detected via /api/chat/ping. Unknown (state not loaded yet) counts as not local.
export function isLocal(){
  if (window.__SV_STATIC) return false;
  if (document.body && document.body.classList.contains("sv-local")) return true;
  return !!(S.state && S.state.mode === "local");
}

export const bus = new EventTarget();
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));
export const on = (name, fn) => bus.addEventListener(name, e => fn(e.detail));

// ── transcript detail levels (simple / standard / developer): onboarding sets the default, switchable anytime ──
export function getVerbosity(){
  try { return localStorage.getItem("sv2_verbosity") || "standard"; } catch(e){ return "standard"; }
}
export function setVerbosity(v){
  try { localStorage.setItem("sv2_verbosity", v); } catch(e){}
}

// ── the user's chosen set of displayed metrics (picked on the model design card; empty = follow the study's display_metrics) ──
const dispKey = sid => "sv2_disp_" + sid;
export function getDispSel(sid){
  try { const v = JSON.parse(localStorage.getItem(dispKey(sid)) || "null"); return Array.isArray(v) && v.length ? v : null; } catch(e){ return null; }
}
export function setDispSel(sid, arr){
  try { arr && arr.length ? localStorage.setItem(dispKey(sid), JSON.stringify(arr)) : localStorage.removeItem(dispKey(sid)); } catch(e){}
}
// charts / metric tiles all use the displayed set: the user's choice > the study's declaration > all metrics
export function displayPick(d){
  const own = getDispSel(d.study_id);
  if (own) return own.filter(m => (d.metrics || []).includes(m));
  return (d.display_metrics && d.display_metrics.length) ? d.display_metrics : (d.metrics || []);
}
