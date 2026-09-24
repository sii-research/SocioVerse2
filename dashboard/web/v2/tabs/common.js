// ── shared fragments for tab modules ────────────────────────────────────────
import { T, ST, loc } from "../i18n.js";
import { escHtml, escAttr } from "../ui.js";
import { S } from "../store.js";

export const card = (inner, opts = {}) =>
  `<div class="card rise ${opts.cls || ""}" ${opts.i != null ? `style="--i:${opts.i}"` : ""}>${inner}</div>`;

export const lblRow = (key, right = "") =>
  `<div class="lbl">${escHtml(T(key))}${right ? `<span class="lbl-r">${right}</span>` : ""}</div>`;

export const emptyState = (icon, titleKey, subKey, actionsHtml = "") =>
  `<div class="empty"><div class="e-ic">${icon}</div>
     <div class="e-t">${escHtml(T(titleKey))}</div>
     <div class="e-s">${escHtml(T(subKey))}</div>${actionsHtml}</div>`;

// stage status badge (used in tab headers)
export function stagePill(d, name){
  const s = d.stages.find(x => x.name === name);
  if (!s) return "";
  return `<span class="pill">${escHtml(ST(s.status))}${s.carried_from ? " · " + escHtml(T("from")) + " " + escHtml(s.carried_from) : ""}${s.ts ? " · " + s.ts : ""}</span>`;
}

// inherited / stale / carried / needs-review notice bar (v1 semantics kept as-is)
export function stageNotes(d, name){
  const s = d.stages.find(x => x.name === name);
  if (!s) return "";
  let out = "";
  if (s.status === "inherited") out += `<div class="note amber"><b>${escHtml(T("inherited_head"))} ${escHtml(d.forked_from || "")}.</b> ${escHtml(T("inherited_body"))} <code>/${name}</code></div>`;
  if (s.status === "stale") out += `<div class="note coral"><b>${escHtml(T("stale_head"))}</b> ${escHtml(T("stale_body"))} <code>/${name}</code></div>`;
  if (s.status === "done" && s.carried_from) out += `<div class="note muted"><b>${escHtml(T("carried_head"))} ${escHtml(s.carried_from)}.</b> ${escHtml(T("carried_body"))}</div>`;
  if (s.status === "review") out += `<div class="note amber"><b>${escHtml(T("review_head"))}${s.carried_from ? " " + escHtml(s.carried_from) : ""}.</b> ${escHtml(T("review_body"))} <code>/${name}</code></div>`;
  return out;
}
export function stageNarrative(d, name){
  const s = d.stages.find(x => x.name === name);
  return (s && s.narrative)
    ? `<div class="note muted" style="background:var(--surface-2)"><span class="lbl" style="margin-bottom:3px">${escHtml(T("cc_reasoning"))}</span>${s.narrative}</div>`
    : "";
}

export function metricsBlock(d){
  const md = d.metric_descriptions || {};
  const rows = (d.metrics || []).map(m =>
    `<div class="kv" style="margin:3px 0"><b>${escHtml(m)}</b>${md[m] ? ` — <span class="muted">${escHtml(md[m])}</span>` : ` <span class="muted" style="font-size:11px">${escHtml(T("no_meaning"))}</span>`}</div>`).join("");
  return rows ? `${lblRow("metrics_meaning")}${rows}` : "";
}

const GROUND_VIA = { event_service:["event","--purple"], web_search:["web","--accent"],
                     provider:["provider","--teal"], user:["user","--amber"] };
function groundLink(s){
  if (!s) return "";
  const ok = s.url && /^https?:\/\//i.test(s.url);
  if (ok) return `<a href="${escAttr(s.url)}" target="_blank" rel="noopener" style="text-decoration:none">${escHtml(s.title || s.url)}</a>`;
  return s.title ? `<span class="muted">${escHtml(s.title)}</span>` : "";
}
function groundVia(s){
  const v = s && GROUND_VIA[s.via];
  return v ? `<span class="chip" style="color:var(${v[1]})">${v[0]}</span>` : "";
}
export function groundingHtml(g, cap = 40){
  if (!g) return "";
  const c = g.counts || {};
  const total = (c.sourced || 0) + (c.proxy || 0) + (c.assumed || 0);
  // basis composition bar (teal sourced / amber proxy / grey assumed) — easier to read at a glance than three pills
  const seg = (n, col) => n > 0 ? `<i style="flex:${n};background:${col}" title="${n}"></i>` : "";
  const ratio = total > 0 ? `<span class="gratio" title="${c.sourced || 0} ${escHtml(T("g_sourced"))} · ${c.proxy || 0} ${escHtml(T("g_proxy"))} · ${c.assumed || 0} ${escHtml(T("g_assumed"))}">
      <span class="grbar">${seg(c.sourced, "var(--teal)")}${seg(c.proxy, "var(--amber)")}${seg(c.assumed, "var(--border-strong)")}</span>
      <span class="grn">${c.sourced || 0}·${c.proxy || 0}·${c.assumed || 0}</span></span>` : "";
  if (g.method_notes === "stylized" && !(g.facts || []).length)
    return `${lblRow("ov_grounding", ratio)}<div class="kv muted">${escHtml(T("g_stylized"))}</div>`;
  const basisLabel = b => { const t = T("g_" + b); return t === "g_" + b ? b : t; };

  const facts = (g.facts || []).slice(0, cap).map(f => {
    const val = f.value != null ? ` <span class="gf-val">${escHtml(String(f.value))}${f.unit ? " " + escHtml(f.unit) : ""}</span>` : "";
    const asOf = f.as_of ? ` <span class="gf-asof">(${escHtml(f.as_of)})</span>` : "";
    const src = groundLink(f.source);
    return `<div class="gfact b-${escAttr(f.basis || "assumed")}">
      <div class="gf-main">${escHtml(f.claim || f.id || "")} —${val}${asOf}</div>
      <div class="gf-meta">${f.basis ? `<span class="gf-basis">${escHtml(basisLabel(f.basis))}</span>` : ""}${groundVia(f.source)}${src ? `<span class="gf-src">${src}</span>` : ""}</div>
      ${f.note ? `<div class="gf-note">${escHtml(f.note)}</div>` : ""}</div>`;
  }).join("");
  const refs = (g.implementation_refs || []).map(r =>
    `<div class="gref"><span class="gr-ic">📖</span><span style="min-width:0">${groundLink(r)}
      ${r.takeaway ? `<div class="gr-take">${escHtml(r.takeaway)}</div>` : ""}</span></div>`).join("");
  const asm = (g.assumptions || []).map(a =>
    `<div class="gasm">${escHtml(a.claim || "")}${a.rationale ? `<div class="ga-r">${escHtml(a.rationale)}</div>` : ""}</div>`).join("");

  // segmented switch (not shown when there is only one kind of content)
  const panes = [["facts", T("g_facts"), (g.facts || []).length, facts],
                 ["refs", T("g_refs"), (g.implementation_refs || []).length, refs],
                 ["asm", T("g_assumptions"), (g.assumptions || []).length, asm]].filter(p => p[2] > 0);
  if (!panes.length) return `${lblRow("ov_grounding", ratio)}<div class="kv muted">${escHtml(T("none"))}</div>`;
  const segsHtml = panes.length > 1
    ? `<div class="gseg">${panes.map((p, i) => `<span class="gs ${i === 0 ? "on" : ""}" data-gseg="${p[0]}">${escHtml(p[1])} <b>${p[2]}</b></span>`).join("")}</div>` : "";
  const panesHtml = panes.map((p, i) => `<div class="gpane" data-gpane="${p[0]}" ${i > 0 ? "hidden" : ""}>${p[3]}</div>`).join("");
  return `${lblRow("ov_grounding", ratio)}${segsHtml}${panesHtml}`;
}

// segmented-switch events for groundingHtml (call once on the card container after render)
export function wireGrounding(root){
  root.querySelectorAll("[data-gseg]").forEach(chip => chip.onclick = () => {
    const card = chip.closest(".card") || root;
    card.querySelectorAll("[data-gseg]").forEach(x => x.classList.toggle("on", x === chip));
    card.querySelectorAll("[data-gpane]").forEach(p => p.hidden = p.dataset.gpane !== chip.dataset.gseg);
  });
}

export const chip = t => `<span class="chip">${t}</span>`;

// ── intent checklist (the sv-init Step −1 clarification checklist) ─────────────────
//    live form: rendered in real time in the newmode center pane (while questions are open); archived form: the overview tab's
//    small "what was confirmed before setup" card. item = {id, status, value, q?, label?}; status ∈
//    pending (awaiting the user's answer) / inferred (inferred, awaiting confirmation) / answered (confirmed by the user) / default (delegated, default taken).
//    Titles of the seven canonical dimensions go through i18n (ic_<id>); extra dimensions the agent defines fall back to item.label.
const IC_CANON = ["rq", "form", "inter", "scope", "exp", "evidence", "success"];
const icLabel = it => {
  const k = "ic_" + it.id;
  const t = T(k);
  return t !== k ? t : (it.label || it.id || "");
};
const IC_ICON = {
  answered: `<span class="ic-dot ok"><svg width="9" height="9" viewBox="0 0 18 18"><path d="M4 9.5l3.2 3.2L14 5.8" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/></svg></span>`,
  default:  `<span class="ic-dot df"><svg width="9" height="9" viewBox="0 0 18 18"><path d="M4 9.5l3.2 3.2L14 5.8" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/></svg></span>`,
  inferred: `<span class="ic-dot inf">?</span>`,
  pending:  `<span class="ic-dot pd"></span>`,
};
export function intentHtml(intent, mode = "live"){
  if (!intent || !Array.isArray(intent.items) || !intent.items.length) return "";
  // canonical dimensions in a fixed order, the agent's extra dimensions after them (in the order sent)
  const items = [...intent.items].sort((a, b) => {
    const ia = IC_CANON.indexOf(a.id), ib = IC_CANON.indexOf(b.id);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  const settled = items.filter(x => x.status === "answered" || x.status === "default").length;
  const live = mode === "live";
  const rows = items.map(it => {
    const st = IC_ICON[it.status] ? it.status : "pending";
    const stTxt = T("ic_st_" + st);
    return `<div class="icrow st-${st}">
      ${IC_ICON[st]}
      <div class="ic-main">
        <div class="ic-h"><span class="ic-lbl">${escHtml(icLabel(it))}</span><span class="ic-st">${escHtml(stTxt)}</span></div>
        ${it.value ? `<div class="ic-val">${escHtml(String(it.value))}</div>` : ""}
        ${live && it.q && (st === "pending" || st === "inferred") ? `<div class="ic-q">${escHtml(String(it.q))}</div>` : ""}
      </div></div>`;
  }).join("");
  const prog = `<span class="chip" title="${escAttr(T("ic_ok"))}">${settled}/${items.length} ${escHtml(T("ic_ok"))}</span>`;
  const confirmed = intent.phase === "confirmed"
    ? `<div class="note teal" style="margin-top:10px">✓ ${escHtml(T("ic_confirmed"))}</div>` : "";
  return `${lblRow("ic_title", prog)}
    ${live ? `<div class="kv muted" style="margin:-2px 0 8px;font-size:12px">${escHtml(T("ic_sub"))}</div>` : ""}
    ${!live ? `<div class="kv muted" style="margin:-2px 0 8px;font-size:12px">${escHtml(T("ic_done_sub"))}</div>` : ""}
    <div class="iclist">${rows}</div>${live ? confirmed : ""}`;
}
