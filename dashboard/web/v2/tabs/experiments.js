// ── Experiments tab: main-line run + versions / counterfactual branches + metric comparison + per-agent drill-down + figure gallery ──
//    Concepts: the main line is the study's dynamic long-horizon run. A version = a snapshot for any change to the study state (P·E·f·Θ), run cold;
//    a branch = only adds interventions to the environment, replays the parent's history before the fork step, and pays only for the steps after it.
//    Both kinds of node work the same way, have independent results and can be compared on one chart anytime; a branch and its source version read as a control/treatment pair.
import { S, displayPick } from "../store.js";
import { T, ST, getLang } from "../i18n.js";
import { el, escHtml, escAttr, cssv, fmtVal, fmtNum } from "../ui.js";
import * as api from "../api.js";
import { PALETTE, lineChart } from "../charts.js";
import { chatPrefill } from "../chat.js";
import { card, lblRow, emptyState, stagePill, stageNotes, stageNarrative, chip, metricsBlock } from "./common.js";
import { loadStudy } from "../app.js";

const HIDDEN = new Set();
let hiddenFor = null;
let FIG = 0, figFor = null;
let AG = null;

export function render(v){
  const d = S.detail;
  const s = d.stages.find(x => x.name === "sv-run");
  const key = S.cur + "@" + (d.viewing_version || "v1");
  if (hiddenFor !== key){ HIDDEN.clear(); hiddenFor = key; }
  if (figFor !== S.cur){ FIG = 0; figFor = S.cur; }

  const rows = (d.metrics_rows && d.metrics_rows.length) ? d.metrics_rows : (d.progress_rows || []);
  const hasRun = rows.length > 0 || (s && s.status === "done") || d.progress;

  let html = "";

  // ── run status card (the special case for an external pipeline's run_note is kept) ──
  const rn = d.run_note && (d.run_note[getLang()] || d.run_note.zh || d.run_note.en);
  if (rn && !(s && s.status === "done")){
    html += card(`${lblRow("ex_main", stagePill(d, "sv-run"))}<div class="note amber">⚙ ${escHtml(rn)}</div>`, { i: 0 });
  } else if (!hasRun){
    const act = S.chatEnabled ? `<button class="btn primary" id="exStart">▶ ${escHtml(T("stage_run"))}</button>` : "";
    html += card(emptyState("🧪", "ex_empty_t", "ex_empty_s", act), { i: 0 });
  } else {
    const sim = d.simulation, runDone = s && s.status === "done", prog = d.progress, live = prog && !runDone;
    let cur, tot, last;
    if (live){ cur = prog.step || 0; tot = prog.n_steps || d.n_steps || 1; last = (d.progress_rows || []).slice(-1)[0]; }
    else { cur = rows.length ? Math.max(...rows.map(r => r.step)) : 0; tot = d.n_steps || 1; last = rows[rows.length - 1]; }
    const frac = tot ? Math.min(1, cur / tot) : 0;
    html += card(`${lblRow("ex_main", stagePill(d, "sv-run"))}
      <div class="chips">${chip((sim?.n_steps ?? d.n_steps ?? "?") + " steps")}${sim?.decision_ref ? chip("decision: " + escHtml(sim.decision_ref)) : ""}${sim?.collector_ref ? chip("collector: " + escHtml(sim.collector_ref)) : ""}${chip("seed: " + (d.seed ?? "?"))}</div>
      <div style="margin-top:12px"><div style="display:flex;justify-content:space-between;font-size:11px;color:var(--faint)">
        <span>${live ? `<span class="dot pulse" style="background:var(--accent);margin-right:4px"></span>${escHtml(T("running"))} · ` : ""}step ${cur} / ${tot}</span><span>${escHtml(T("min_per_step"))}</span></div>
      <div class="track"><div class="fill" style="width:${Math.round(frac * 100)}%"></div></div></div>
      ${last ? `<div class="kv" style="margin-top:10px">${escHtml(T("latest_tick"))} · ${(d.metrics || []).slice(0, 3).map(m => `${escHtml(m)} <b>${fmtVal(last[m])}</b>`).join(" · ")}</div>` : `<div class="kv muted" style="margin-top:10px">${escHtml(T("no_metrics"))}</div>`}
      ${stageNotes(d, "sv-run")}${stageNarrative(d, "sv-run")}`, { i: 0 });
  }

  // ── list of versions and branches ──
  const vs = d.versions && d.versions.length ? d.versions : [{ id: "v1", note: "", current: true }];
  const viewing = d.viewing_version || "v1";
  const expCards = vs.map((x, i) => {
    const isView = x.id === viewing, isCmp = S.cmp === x.id;
    const label = x.id === "v1" && !x.parent ? T("ex_main") : (x.note || T("ex_note_empty"));
    // kind badge: a branch only changes the environment and replays the parent run; everything else is a version that runs cold.
    // kind comes from the server (old manifests are backfilled from warm_start); if it is ever missing, show it as a version.
    const isBranch = x.kind === "branch";
    const kindPill = `<span class="pill" style="font-size:9.5px;padding:1px 8px;margin-left:6px;${isBranch
      ? "background:var(--purple-bg);color:var(--purple)" : "background:var(--surface-2);color:var(--faint)"}">${
      escHtml(T(isBranch ? "ex_kind_branch" : "ex_kind_version"))}</span>`;
    const origin = (isBranch && x.branch_of && x.fork_step != null)
      ? `<div class="e-ax" style="font-size:10.5px;color:var(--faint);margin:-3px 0 5px">${
          escHtml(T("ex_branched_at").replace("%1", String(x.branch_of)).replace("%2", String(x.fork_step)))}</div>` : "";
    const down = x.downgraded === true
      ? `<span class="chip" title="${escAttr(T("ex_downgraded_hint"))}" style="font-size:9.5px;padding:1px 6px;color:var(--amber)">⚠ ${escHtml(T("ex_downgraded"))}</span>` : "";
    return `<div class="exp ${isView ? "on" : ""}" data-v="${escAttr(x.id)}" style="--i:${i}">
      <div class="e-id">${escHtml(x.id)}${x.parent ? ` · ${escHtml(T("ex_parent"))} ${escHtml(x.parent)}` : ""}${kindPill}</div>
      <div class="e-nm">${escHtml(label)}</div>
      ${origin}
      <div class="e-meta">${x.ts ? `<span>${x.ts}</span>` : ""}${down}${x.resume_from_stage ? `<span class="chip" style="font-size:9.5px;padding:1px 6px">${escHtml(T("resume_at"))} ${escHtml(x.resume_from_stage)}</span>` : ""}</div>
      <span class="e-tag">${x.current ? `<span class="pill" style="background:var(--teal-bg);color:var(--teal)">${escHtml(T("ex_cur"))}</span>` : ""}</span>
      <div class="chips" style="margin-top:9px">
        ${!isView ? `<button class="btn sm" data-act="view" data-v="${escAttr(x.id)}">👁 ${escHtml(T("ex_view"))}</button>` : ""}
        ${!isView ? `<button class="btn sm" data-act="cmp" data-v="${escAttr(x.id)}" ${isCmp ? `style="border-color:var(--accent);color:var(--accent)"` : ""}>⇄ ${escHtml(isCmp ? T("ex_uncompare") : T("ex_compare"))}</button>` : ""}
      </div></div>`;
  }).join("");
  html += card(`${lblRow("ex_list", S.chatEnabled ? `<button class="btn sm primary" id="exNew">${escHtml(T("ex_new"))}</button>` : "")}
    <div class="kv muted" style="margin:-2px 0 10px;font-size:12px">${escHtml(T("ex_concept"))}</div>
    <div class="vgrid g3">${expCards}</div>`, { i: 1, cls: "flat" });

  // ── metric timeline ──
  if (hasRun){
    html += card(`${lblRow("ex_metric", `<span class="lbl-r muted" style="font-size:10.5px">${escHtml(T("ex_metric_hint"))}</span>`)}
      <div class="chartbox" id="exChart" style="height:clamp(230px,34vh,430px)"></div>
      <div class="legend" id="exLegend"></div><div id="exDiff"></div>`, { i: 2 });
  }

  // ── figure gallery ──
  const figs = d.figures || [];
  if (figs.length){
    html += card(`${lblRow("figures", `<span id="figNav"></span>`)}<div id="exFig" class="figwrap"></div>`, { i: 3 });
  }

  // ── per-agent drill-down ──
  const ag = S.agents;
  if (ag && ag.count){
    html += card(`${lblRow("ex_agents", `<span class="chip">${ag.count} ${escHtml(T("ex_agents_n"))}</span><span id="agPhase" class="lbl-r muted" style="font-size:10.5px"></span>`)}
      <div class="aggrid"><div class="aglist" id="agList"></div><div class="agdetail" id="agDetail"></div></div>`, { i: 4 });
  }

  v.innerHTML = html;

  // wire
  const exStart = el("exStart");
  if (exStart) exStart.onclick = () => chatPrefill(getLang() === "zh" ? "开始运行主线推演。" : "Start the main simulation run.");
  const exNew = el("exNew");
  if (exNew) exNew.onclick = () => chatPrefill((QA_FORK[getLang()] || QA_FORK.zh));
  v.querySelectorAll("[data-act=view]").forEach(b => b.onclick = e => { e.stopPropagation();
    S.ver = (b.dataset.v === d.current_version) ? null : b.dataset.v; loadStudy(S.cur); });
  v.querySelectorAll("[data-act=cmp]").forEach(b => b.onclick = e => { e.stopPropagation();
    S.cmp = S.cmp === b.dataset.v ? null : b.dataset.v; loadStudy(S.cur); });

  if (hasRun) drawChart(d);
  if (figs.length) drawFig(d, figs);
  if (ag && ag.count) drawAgents(d, ag);
}

const QA_FORK = { zh: "在当前研究上添加一条干预并分支：（说明干预，例如 第 5 步加入政策 X）。分支重放分叉步之前的历史，跑完后与来源版本同图做对照/处理对比；若本研究不支持重放，或改动超出环境范围，请改建新版本。",
                  en: "Add an intervention to the current study and branch it: (describe the intervention, e.g. policy X at step 5). The branch replays the history before the branch step; afterwards compare control vs treatment on one chart. If this study cannot replay history, or the edit goes beyond the environment, create a version instead." };

// when a branch is paired with its source version, the legend/readout says control / treatment; without the pairing, fall back to generic wording.
function cmpPair(d, base){
  if (!base) return null;
  const a = d.viewing_version, b = base.viewing_version;
  if (!a || !b || a === b) return null;
  const vs = d.versions || [];
  const A = vs.find(x => x && x.id === a), B = vs.find(x => x && x.id === b);
  if (!A || !B) return null;
  if (A.kind === "branch" && A.branch_of === b) return { treatment: a, control: b };
  if (B.kind === "branch" && B.branch_of === a) return { treatment: b, control: a };
  return null;
}
const pairLabel = (pair, id, fallback) => (pair && id)
  ? `${id} · ${T(pair.treatment === id ? "ex_treatment" : "ex_control")}` : (id || fallback);

function drawChart(d){
  const box = el("exChart"), leg = el("exLegend");
  if (!box) return;
  const rows = (d.metrics_rows && d.metrics_rows.length) ? d.metrics_rows : (d.progress_rows || []);
  const base = S.cmpDetail;
  const baseRows = base ? ((base.metrics_rows && base.metrics_rows.length) ? base.metrics_rows : (base.progress_rows || [])) : [];
  const pair = cmpPair(d, base);
  const pick = displayPick(d);   // the user's displayed set > the study's declaration (pickable on the overview model card)
  // arriving from an overview metric tile → focus that metric once (the others are hidden; the legend can bring them back anytime)
  if (S.focusMetric){
    if (pick.includes(S.focusMetric)){
      HIDDEN.clear();
      pick.slice(0, 5).forEach(m => { if (m !== S.focusMetric) HIDDEN.add(m); });
    }
    S.focusMetric = null;
  }
  // the event text of intervention nodes → shown explicitly in the hover readout card (collaborator feedback: turning points need a marker)
  const ivNotes = {};
  (d.environment?.scheduled_events || []).forEach(e => {
    if (e.at_step != null) ivNotes[e.at_step] = ((ivNotes[e.at_step] ? ivNotes[e.at_step] + " / " : "") + (e.note || "")).slice(0, 90);
  });
  (d.environment?.broadcasts || []).forEach(b => {
    if (b.at_step != null && !ivNotes[b.at_step]) ivNotes[b.at_step] = (T("broadcast") + ": " + (b.content || "")).slice(0, 90);
  });
  const ok = lineChart(box, leg, {
    rows, baseRows, pick, hidden: HIDDEN,
    onToggle: m => { if (HIDDEN.has(m)) HIDDEN.delete(m); else HIDDEN.add(m); drawChart(d); },
    descriptions: d.metric_descriptions || {},
    interventions: d.interventions || [],
    interventionNotes: ivNotes,
    baseInterventions: base ? (base.interventions || []) : [],
    curLabel: pairLabel(pair, d.viewing_version, "current"),
    baseLabel: base ? pairLabel(pair, base.viewing_version, "baseline") : "",
  });
  if (!ok) box.innerHTML = `<div class="kv muted" style="padding:26px 0;text-align:center">${escHtml(T("chart_empty"))}</div>`;
  renderDiff(d, base, pair);
}

function renderDiff(a, b, pair){
  const box = el("exDiff"); if (!box) return;
  if (!b){ box.innerHTML = ""; return; }
  const chips = [];
  const nsteps = x => (x.simulation && x.simulation.n_steps != null) ? x.simulation.n_steps : x.n_steps;
  const seed = x => (x.simulation && x.simulation.seed != null) ? x.simulation.seed : x.seed;
  if (nsteps(a) !== nsteps(b)) chips.push(["muted", `n_steps ${nsteps(b)} → ${nsteps(a)}`]);
  if (seed(a) !== seed(b)) chips.push(["muted", `seed ${seed(b)} → ${seed(a)}`]);
  const evKey = e => `step ${e.at_step} · ${e.note || ""}`;
  const ae = (a.environment?.scheduled_events || []).map(evKey), be = (b.environment?.scheduled_events || []).map(evKey);
  ae.filter(x => !be.includes(x)).forEach(x => chips.push(["teal", "+ " + x]));
  be.filter(x => !ae.includes(x)).forEach(x => chips.push(["coral", "− " + x]));
  const bKey = e => `step ${e.at_step} · ${T("broadcast")} ${(e.content || "").slice(0, 36)}`;
  const ab = (a.environment?.broadcasts || []).map(bKey), bb = (b.environment?.broadcasts || []).map(bKey);
  ab.filter(x => !bb.includes(x)).forEach(x => chips.push(["teal", "+ " + x]));
  bb.filter(x => !ab.includes(x)).forEach(x => chips.push(["coral", "− " + x]));
  if (a.population && b.population && a.population.persona_count !== b.population.persona_count)
    chips.push(["muted", `personas ${b.population.persona_count} → ${a.population.persona_count}`]);
  const vsCtl = (pair && pair.control === b.viewing_version) ? ` · ${escHtml(T("ex_vs_control"))}` : "";
  box.innerHTML = `<div class="lbl" style="margin:10px 0 4px">${escHtml(T("delta_config"))} · ${b.viewing_version} → ${a.viewing_version}${vsCtl}</div>`
    + (chips.length ? `<div class="chips">${chips.map(([c, t]) => `<span class="chip" style="color:var(--${c})">${escHtml(t)}</span>`).join("")}</div>`
                    : `<div class="kv muted">${escHtml(T("no_diff"))}</div>`);
}

function drawFig(d, figs){
  FIG = ((FIG % figs.length) + figs.length) % figs.length;
  const src = api.figureUrl(S.cur, S.ver, figs[FIG]);
  el("exFig").innerHTML = `<img src="${src}" alt="${escAttr(figs[FIG])}" title="${escAttr(T("click_enlarge"))}"/>
    <div class="muted" style="font-size:11px;margin-top:6px">figures/${escHtml(figs[FIG])} · ${escHtml(T("click_enlarge"))}</div>`;
  el("exFig").querySelector("img").onclick = () => window.__lightbox(src, "figures/" + figs[FIG]);
  el("figNav").innerHTML = `<button class="btn sm" id="figPrev">‹</button> <span class="muted mono" style="font-size:11px">${FIG + 1}/${figs.length}</span> <button class="btn sm" id="figNext">›</button>`;
  el("figPrev").onclick = () => { FIG--; drawFig(d, figs); };
  el("figNext").onclick = () => { FIG++; drawFig(d, figs); };
}

// ── agent drill-down (ported from the v1 logic) ───────────────────────────────
function agReason(r){ const p = r.action_payload || {}, s = r.state || {}; return p.reason || p.rationale || s.reason || s.rationale || ""; }
function agIsNum(rows, k){ let any = false; for (const r of rows){ const x = (r.state || {})[k]; if (x == null) continue; if (typeof x !== "number") return false; any = true; } return any; }
function agFlat(state){
  const out = {};
  for (const [k, x] of Object.entries(state || {})){
    if (k === "reason" || k === "rationale") continue;
    if (x && typeof x === "object" && !Array.isArray(x)){
      for (const [k2, v2] of Object.entries(x)) if (v2 == null || typeof v2 !== "object") out[k + "." + k2] = v2;
    } else if (!(x && typeof x === "object")){ out[k] = x; }
  }
  return out;
}
function agAction(r){
  if (!r.action_kind) return `<span class="muted" style="font-size:11px">${escHtml(T("no_action"))}</span>`;
  const p = r.action_payload || {}, txt = p.text || p.content || "";
  const rest = Object.entries(p).filter(([k]) => !["text","content","reason","rationale"].includes(k)).map(([k, x]) => `${escHtml(k)}: ${escHtml(fmtVal(x))}`).join(" · ");
  return `<span style="font-size:11px;color:var(--accent);font-weight:500">${escHtml(r.action_kind)}</span>${rest ? ` <span class="muted" style="font-size:11px">${rest}</span>` : ""}${txt ? `<div style="font-size:12px;margin-top:3px;color:var(--text)">“${escHtml(txt)}”</div>` : ""}`;
}
const svP = P => "M" + P.map(p => p.join(",")).join(" L");
function agentChart(rows, keys){
  const steps = rows.map(r => r.step), xmin = Math.min(...steps), xmax = Math.max(...steps);
  const ext = {}; keys.forEach(k => { const vs = rows.map(r => (r.state || {})[k]).filter(x => typeof x === "number");
    ext[k] = { mn: Math.min(...vs), mx: Math.max(...vs), last: vs[vs.length - 1] }; ext[k].rng = (ext[k].mx - ext[k].mn) || 1; });
  const col = k => PALETTE[keys.indexOf(k) % PALETTE.length];
  const cw = el("agDetail").clientWidth || 300, W = cw > 60 ? cw : 300, H = 150, pl = 6, pr = 6, pt = 10, pb = 17;
  const X = s => pl + (xmax === xmin ? 0 : (s - xmin) / (xmax - xmin)) * (W - pl - pr);
  const Y = (x, k) => pt + (1 - (x - ext[k].mn) / ext[k].rng) * (H - pt - pb);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="width:100%;height:${H}px" role="img">`;
  svg += `<line x1="${pl}" y1="${H-pb}" x2="${W-pr}" y2="${H-pb}" stroke="${cssv("--border")}"/>`;
  svg += `<line x1="${pl}" y1="${pt + (H-pt-pb)/2}" x2="${W-pr}" y2="${pt + (H-pt-pb)/2}" stroke="${cssv("--border")}" opacity="0.55"/>`;
  keys.forEach(k => { const c = col(k), rr = rows.filter(r => typeof (r.state || {})[k] === "number");
    const P = rr.map(r => [X(r.step), Y(r.state[k], k)]);
    if (P.length) svg += `<path d="${svP(P)}" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round"/>`;
    const dots = P.length > 40 ? [P[0], P[P.length - 1]] : P;
    dots.forEach(p => svg += `<circle cx="${p[0]}" cy="${p[1]}" r="2.4" fill="${c}" stroke="${cssv("--surface")}" stroke-width="1.1"/>`); });
  const xstep = Math.max(1, Math.ceil(steps.length / 10));
  steps.forEach((s, i) => { if (i % xstep === 0 || i === steps.length - 1) svg += `<text x="${X(s)}" y="${H-pb+13}" text-anchor="middle" font-size="9" fill="${cssv("--faint")}">${s}</text>`; });
  svg += `</svg>`;
  const leg = keys.map(k => `<span style="white-space:nowrap"><span style="color:${col(k)}">■</span> ${escHtml(k)} <span class="mono" style="font-size:10px">${escHtml(fmtVal(ext[k].last))}</span> <span class="faint" style="font-size:9px">(${escHtml(fmtVal(ext[k].mn))}–${escHtml(fmtVal(ext[k].mx))})</span></span>`).join("");
  return `<div style="margin:2px 0 3px">${svg}</div><div class="agleg">${leg}<span class="faint" style="font-size:9px">· ${escHtml(T("agent_norm"))}</span></div>`;
}
function agTrack(rows, k){
  const cats = [...new Set(rows.map(r => (r.state || {})[k]).filter(x => x != null).map(String))];
  const col = i => PALETTE[i % PALETTE.length];
  const cells = rows.map(r => { const x = (r.state || {})[k], i = cats.indexOf(String(x));
    return `<span class="agtrack-cell" style="background:${x == null ? "var(--surface-2)" : col(i)}" title="step ${r.step}: ${escAttr(String(x))}"></span>`; }).join("");
  const leg = cats.slice(0, 6).map((c, i) => `<span class="faint"><span style="color:${col(i)}">■</span> ${escHtml(c)}</span>`).join("");
  return `<div class="agtrack-row"><div class="agtrack-lbl">${escHtml(k)}</div><div class="agtrack">${cells}</div></div><div class="agtrack-leg">${leg}</div>`;
}

function drawAgents(d, ag){
  el("agPhase").innerHTML = ag.phase === "live"
    ? `<span class="dot pulse" style="background:var(--teal);width:7px;height:7px"></span> ${escHtml(T("live"))}`
    : ag.phase === "initial" ? escHtml(T("initial_roster")) : escHtml(T("post_run"));
  if (!AG || !ag.agents.some(a => a.agent_id === AG)) AG = ag.agents[0].agent_id;
  const scalarDim = k => k !== "group" && k !== "last_action" && k !== "reason" && k !== "rationale"
    && ag.agents.every(a => { const x = (a.state || {})[k]; return x == null || typeof x !== "object"; });
  const declared = ((d.key_attributes) || []).filter(k => (ag.dims || []).includes(k) && scalarDim(k));
  const keyDims = (declared.length ? declared : (ag.dims || []).filter(scalarDim)).slice(0, 2);
  el("agList").innerHTML = ag.agents.map(a => {
    const grp = a.state && a.state.group != null ? `<span class="muted" style="font-size:10px">${escHtml(String(a.state.group))}</span>` : "";
    const kvs = keyDims.map(k => (a.state && a.state[k] != null) ? fmtVal(a.state[k]) : null).filter(Boolean);
    const kv = kvs.length ? `<span class="ag-kv" title="${escAttr(keyDims.join(" · "))}">${kvs.map(escHtml).join(" · ")}</span>` : "";
    return `<div class="ag ${a.agent_id === AG ? "sel" : ""}" data-a="${escAttr(a.agent_id)}"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${escHtml(a.agent_id)} ${grp}</span>${kv}</div>`;
  }).join("");
  el("agList").querySelectorAll(".ag").forEach(n => n.onclick = () => { AG = n.dataset.a; drawAgents(d, ag); });
  loadAgentDetail();
}

async function loadAgentDetail(){
  const box = el("agDetail"); if (!box || !AG) return;
  box.innerHTML = `<div class="skel" style="height:120px"></div>`;
  let ad;
  try { ad = await api.getAgent(S.cur, AG, S.ver); } catch(e){ box.innerHTML = ""; return; }
  const rows = ad.rows || [], steps = rows.map(r => r.step);
  const frows = rows.map(r => ({ step: r.step, state: agFlat(r.state) }));
  const keys = []; frows.forEach(r => Object.keys(r.state).forEach(k => { if (!keys.includes(k)) keys.push(k); }));
  const numKeys = keys.filter(k => agIsNum(frows, k)), catKeys = keys.filter(k => !agIsNum(frows, k));
  const multi = steps.length >= 2;
  const head = `<div style="font-weight:600;font-size:13px;margin-bottom:2px">${escHtml(ad.agent_id)}</div>
    <div class="muted" style="font-size:11px;margin-bottom:10px">${rows.length}${ad.total_rows > rows.length ? "/" + ad.total_rows : ""} ${escHtml(T("steps_tracked"))}</div>`;
  const lastReason = [...rows].reverse().map(agReason).find(Boolean);
  const reasonHtml = lastReason ? `<div class="agreason">“${escHtml(lastReason)}”</div>` : "";
  const chartHtml = (multi && numKeys.length) ? agentChart(frows, numKeys) : "";
  let trackHtml = (multi && catKeys.length) ? catKeys.map(k => agTrack(frows, k)).join("") : "";
  if (trackHtml){
    const n = steps.length;
    const axis = steps.map((s, i) => `<span class="agtrack-cell agax-cell">${(n <= 14 || i % 2 === 0 || i === n - 1) ? s : ""}</span>`).join("");
    trackHtml += `<div class="agtrack-row"><div class="agtrack-lbl" style="font-size:9px">step →</div><div class="agtrack agax">${axis}</div></div>`;
  }
  const rawInner = rows.map(r => { const chips = Object.entries(r.state || {}).filter(([k]) => k !== "reason" && k !== "rationale").map(([k, x]) => `<span class="chip">${escHtml(k)}: <b>${escHtml(fmtVal(x))}</b></span>`).join("");
    const rsn = agReason(r);
    return `<div class="agstep"><div style="font-size:11px;color:var(--faint);margin-bottom:4px">step ${r.step}</div>
      <div class="chips" style="margin:0 0 5px">${chips}</div>
      ${rsn ? `<div class="agreason sm">“${escHtml(rsn)}”</div>` : ""}
      <div>${agAction(r)}</div></div>`; }).join("");
  const rawOpen = multi ? (window.AG_RAW_OPEN === true) : true;
  box.innerHTML = head + reasonHtml + chartHtml + trackHtml
    + `<details class="agraw"${rawOpen ? " open" : ""}><summary>${escHtml(T("agent_raw"))}</summary>${rawInner}</details>`;
  const det = box.querySelector(".agraw");
  if (det) det.addEventListener("toggle", () => { window.AG_RAW_OPEN = det.open; });
}
