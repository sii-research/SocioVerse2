// ── Overview tab: research-question hero, key-result stat tiles, pipeline, model design, grounding, activity ──
import { S, getDispSel, setDispSel, displayPick } from "../store.js";
import { T, ST, loc, getLang } from "../i18n.js";
import { el, escHtml, escAttr, cssv, fmtNum, countUp, toast } from "../ui.js";
import { PALETTE, sparkline } from "../charts.js";
import { STAGE_META, stageName, STAGE_TAB, switchTab } from "../app.js";
import { CHAT } from "../chat.js";
import { card, lblRow, groundingHtml, wireGrounding, chip, intentHtml } from "./common.js";

const STAGE_COLOR = { "sv-init":"purple", "sv-build-model":"faint", "sv-build-environment":"teal",
                      "sv-build-population":"amber", "sv-run":"accent", "sv-report":"pink" };

const CHECK_SVG = `<svg width="15" height="15" viewBox="0 0 20 20"><path d="M5.2 10.8l3.3 3.3 6.3-7.6" stroke="#fff" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function stageNodeHtml(s, activeFlag, running, awaitG, i){
  const num = STAGE_META[s.name] ? STAGE_META[s.name].n : "·";
  if (awaitG)  return `<span class="snode sn-await">⏸</span>`;
  if (running) return `<span class="snode sn-run ring-pulse"><span class="dot pulse" style="background:#fff;width:8px;height:8px"></span></span>`;
  if (s.status === "done")      return `<span class="snode sn-done" style="--i:${i}">${CHECK_SVG}</span>`;
  if (s.status === "stale")     return `<span class="snode sn-stale">!</span>`;
  if (s.status === "review")    return `<span class="snode sn-review">${num}</span>`;
  if (s.status === "inherited") return `<span class="snode sn-inherit">${num}</span>`;
  if (s.status === "skipped")   return `<span class="snode sn-skip">–</span>`;
  if (activeFlag)               return `<span class="snode sn-active ring-pulse">${num}</span>`;
  return `<span class="snode sn-pend">${num}</span>`;
}

export function pipelineHtml(d){
  const live = S.chatEnabled && CHAT.liveStage;
  const parts = [];
  d.stages.forEach((s, i) => {
    const isLive = live && s.name === CHAT.liveStage;
    const activeFlag = live ? isLive : s.active;
    const running = isLive && CHAT.liveRunning;
    const awaitG = isLive && CHAT.gatePending;
    // Quiet copy: the done state does not say "done" (the check mark carries it) and shows a faint completion time instead; pending stays blank.
    // Only states that need action/attention (awaiting confirmation / running / stale / needs review / inherited / skipped) take up text.
    const sub = awaitG ? T("gate_head") : running ? T("running")
      : s.status === "review" ? T("st_review")
      : s.status === "stale" ? T("stale_rerun")
      : s.status === "inherited" ? T("st_inherited")
      : s.status === "skipped" ? T("st_skipped")
      : s.status === "done" ? (s.ts || "")
      : "";
    const cls = ["pnode", "st-" + s.status, activeFlag ? "on" : "", running ? "running" : "", awaitG ? "await" : ""].join(" ");
    if (i > 0) parts.push(`<span class="pconn ${["done","skipped","inherited"].includes(d.stages[i-1].status) ? "done" : ""}"></span>`);
    const tip = `${s.name}${s.artifact ? " · " + s.artifact : ""}${s.carried_from ? " · " + T("from") + " " + s.carried_from : ""}`;
    parts.push(`<div class="${cls}" data-stage="${s.name}" title="${escAttr(tip)}">
      ${stageNodeHtml(s, activeFlag, running, awaitG, i)}
      <span class="nm">${escHtml(stageName(s.name))}</span><span class="sub">${escHtml(sub)}</span></div>`);
  });
  return `<div class="pipe">${parts.join("")}</div>`;
}

function statTiles(d){
  const md = d.metric_descriptions || {};
  const rows = (d.metrics_rows && d.metrics_rows.length) ? d.metrics_rows : (d.progress_rows || []);
  const tiles = [];
  const isFinal = !!d.final_metrics;
  const pickAll = displayPick(d);
  const src = (getDispSel(d.study_id) && rows.length)
    ? Object.fromEntries(pickAll.slice(0, 4).map(m => [m, rows[rows.length - 1][m]]).filter(([, v]) => v != null))
    : (d.final_metrics
       || (rows.length ? Object.fromEntries(pickAll.slice(0, 4)
           .map(m => [m, rows[rows.length - 1][m]]).filter(([, v]) => v != null)) : null));
  if (src){
    const keys = Object.keys(src).slice(0, 4);
    keys.forEach((m, i) => {
      const v = src[m];
      // % only for metrics whose name looks like a ratio and whose whole series lies in 0–1 — a continuous 0.068 must not be labeled 6.8%
      const series = rows.map(r => r[m]).filter(x => x != null);
      const nameHint = /share|rate|ratio|accuracy|pct|percent|prob|frac/i.test(m);
      const inUnit = (series.length ? series : [v]).every(x => typeof x === "number" && x >= -0.001 && x <= 1.05);
      const pct = typeof v === "number" && nameHint && inUnit;
      tiles.push({ label: m, metric: m, value: v, pct, color: PALETTE[i % PALETTE.length],
                   desc: md[m] || "", spark: series.length > 2 ? series : null,
                   tag: isFinal ? T("ov_final") : T("ov_latest") });
    });
  }
  const run = d.stages.find(s => s.name === "sv-run");
  const stepsDone = rows.length ? Math.max(...rows.map(r => r.step || 0)) : (d.progress ? d.progress.step : 0);
  if (run && (stepsDone || d.n_steps)) tiles.push({ label: T("ov_steps"), value: stepsDone,
    sub: (d.n_steps && stepsDone <= d.n_steps) ? `/ ${d.n_steps}` : "", color: cssv("--accent") });
  const nAgents = d.population && d.population.persona_count;
  if (nAgents) tiles.push({ label: T("ov_agents_n"), value: nAgents, color: cssv("--teal") });
  if ((d.versions || []).length > 1) tiles.push({ label: T("ov_versions"), value: d.versions.length, color: cssv("--purple") });
  if (!tiles.length) return "";
  const cells = tiles.map((t, i) => {
    const fmt = v => t.pct ? (v * 100).toFixed(1) + "%" : fmtNum(v);
    return `<div class="card stat rise ${t.metric ? "stat-link" : ""}" ${t.metric ? `data-goto="${escAttr(t.metric)}" title="${escAttr(T("tile_goto"))}"` : ""} style="--i:${i}">
      <div class="sl"><span class="skey" style="background:${t.color}"></span><span class="sname" title="${escAttr(t.desc || t.label)}">${escHtml(t.label)}</span>${t.tag ? `<span class="chip" style="margin-left:auto;font-size:9.5px;padding:1px 7px">${escHtml(t.tag)}</span>` : ""}</div>
      <div class="sv"><span class="cnt mono" data-v="${t.value}" data-k="${escAttr(t.label)}" data-pct="${t.pct ? 1 : 0}">${fmt(t.value)}</span>${t.sub ? `<span class="unit">${escHtml(t.sub)}</span>` : ""}</div>
      ${t.spark ? `<div class="spark">${sparkline(t.spark, t.color)}</div>` : (t.desc ? `<div class="sd" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escAttr(t.desc)}">${escHtml(t.desc)}</div>` : "")}
    </div>`;
  }).join("");
  return `<div class="vgrid g4" style="margin-top:14px">${cells}</div>`;
}

// number roll dedupe: the same value does not animate (SSE rebuilds do not replay); a change rolls smoothly from the old to the new value
const PREV_STAT = new Map();

export function render(v){
  const d = S.detail;
  const rq = loc(d.research_question_i18n, d.research_question);
  const hyp = loc(d.hypothesis_i18n, d.hypothesis);
  const md = d.metric_descriptions || {};
  let html = "";

  html += card(`
    ${lblRow("ov_rq", d.domain ? `<span class="chip">${escHtml(d.domain)}</span>` : "")}
    <div style="font-size:15.5px;font-weight:650;line-height:1.55;letter-spacing:-.1px">${escHtml(rq || "—")}</div>
    ${hyp ? `<div class="kv" style="margin-top:8px"><b>${escHtml(T("ov_hypo"))}</b> · ${escHtml(hyp)}</div>` : ""}
    <div class="chips" style="margin-top:10px">
      ${chip("type: " + escHtml(d.study_type || "?"))}${chip((d.n_steps ?? "?") + " steps")}${chip("seed: " + (d.seed ?? "?"))}
      ${(d.metrics || []).slice(0, 6).map(m => `<span class="chip" title="${escAttr(md[m] || "")}">${escHtml(m)}</span>`).join("")}
    </div>`, { i: 0 });

  html += card(`${lblRow("ov_pipeline")}${pipelineHtml(d)}`, { i: 1, cls: "flat" });

  const stats = statTiles(d);
  html += stats || card(`<div class="kv muted" style="text-align:center;padding:8px 0">${escHtml(T("ov_no_stats"))}</div>`, { i: 2, cls: "flat" });

  // model design: the B=f(P,E) visual formula + metric rows (colored dot = in the current displayed set, same color as the timeline legend;
  // clicking any metric row picks the displayed set; the choice is saved locally and drives the metric tiles and experiment charts)
  const pick = displayPick(d).slice(0, 5);
  const mrows = (d.metrics || []).map(m => {
    const ci = pick.indexOf(m);
    const inSel = ci >= 0;
    const key = inSel ? `style="background:${PALETTE[ci % PALETTE.length]}"` : `style="border:1.5px solid var(--border-strong)"`;
    return `<div class="mrow msel" data-m="${escAttr(m)}" role="button" aria-pressed="${inSel}"
      title="${escAttr(inSel ? T("msel_off") : T("msel_on"))}"><span class="mkey" ${key}></span><span class="mname" ${inSel ? "" : 'style="color:var(--muted)"'}>${escHtml(m)}</span>
      <span class="mdesc">${md[m] ? "— " + escHtml(md[m]) : `<span style="font-size:11px">${escHtml(T("no_meaning"))}</span>`}</span></div>`;
  }).join("");
  const mselHint = `<div class="kv muted" style="font-size:10.5px;margin:6px 0 0">${escHtml(T("msel_hint"))}${getDispSel(d.study_id) ? ` · <span class="msel-reset" style="color:var(--accent);cursor:pointer">${escHtml(T("msel_reset"))}</span>` : ""}</div>`;
  const modelBody = `
    <div class="bfpe"><span class="bt b">B</span> = <span style="margin:0 1px">f(</span><span class="bt p">P</span><span>,</span><span class="bt e">E</span><span>)</span></div>
    <div class="bfpe-leg">
      <span data-go="experiments"><i style="background:var(--accent)"></i>${escHtml(T("kw_b"))}</span>
      <span data-go="population"><i style="background:var(--amber)"></i>${escHtml(T("kw_p"))}</span>
      <span data-go="environment"><i style="background:var(--teal)"></i>${escHtml(T("kw_e"))}</span>
    </div>
    <div class="kv muted" style="margin:0 0 6px;font-size:12px">${escHtml(d.is_path_b ? T("pathb_model") : T("skipped_model"))}</div>
    ${mrows ? `<div style="font-size:10.5px;color:var(--faint);font-family:var(--mono);letter-spacing:.8px;text-transform:uppercase;margin:10px 0 4px">${escHtml(T("metrics_meaning"))}</div>${mrows}${mselHint}` : ""}`;
  html += `<div class="vgrid g2" style="margin-top:14px">`
       + card(`${lblRow("ov_model", `<span class="chip">${escHtml(d.path_label || "")}</span>`)}${modelBody}`, { i: 3 })
       + card(d.grounding ? groundingHtml(d.grounding, 12) : `${lblRow("ov_grounding")}<div class="kv muted">${escHtml(T("none"))}</div>`, { i: 4, cls: "scrollcard" })
       + `</div>`;

  // archived intent-checklist card: the task understanding aligned in Step −1 before setup (shown only when intent.json exists)
  const icHtml = intentHtml(d.intent, "archived");
  if (icHtml) html += card(icHtml, { i: 5, cls: "flat" });

  const items = (d.events || []).slice(0, 10).map(e => {
    if (e.kind === "version")
      return `<div class="fe"><span class="t">${e.t || "—"}</span><span class="pill" style="background:var(--purple-bg);color:var(--purple)">version</span><span class="muted">${escHtml(e.version || "")} ${escHtml(T("created"))}${e.label ? ` · ${escHtml(e.label)}` : ""}</span></div>`;
    const c = STAGE_COLOR[e.stage] || "muted";
    const col = cssv("--" + c) || cssv("--muted"), bg = cssv("--" + c + "-bg") || "var(--surface-2)";
    return `<div class="fe"><span class="t">${e.t || "—"}</span>
      <span class="pill" style="background:${bg};color:${col}">${escHtml(stageName(e.stage))}</span>
      <span class="muted" ${e.kind === "narrative" ? 'style="font-style:italic"' : ""}>${e.version ? `${escHtml(e.version)} · ` : ""}${escHtml((e.label || "").slice(0, 120))}</span></div>`;
  }).join("");
  html += card(`${lblRow("ov_activity")}${items || `<div class="kv muted">${escHtml(T("no_activity"))}</div>`}`, { i: 5, cls: "flat" });

  v.innerHTML = html;
  // wire: pipeline node clicks → jump to the owning tab
  v.querySelectorAll(".pnode").forEach(n => n.onclick = () => {
    const t = STAGE_TAB[n.dataset.stage]; if (t && t !== "overview") switchTab(t);
  });
  wireGrounding(v);
  v.querySelectorAll(".bfpe-leg [data-go]").forEach(n => n.onclick = () => switchTab(n.dataset.go));
  // metric rows pick the displayed set (saved locally → drives the metric tiles / experiment charts)
  v.querySelectorAll(".mrow.msel").forEach(n => n.onclick = () => {
    const m = n.dataset.m;
    const cur = getDispSel(d.study_id) || displayPick(d).slice(0, 5);
    if (!cur.includes(m) && cur.length >= 5){ toast(T("msel_max"), "err"); return; }   // the palette has at most 5 colors
    const next = cur.includes(m) ? cur.filter(x => x !== m) : [...cur, m];
    if (!next.length) return;                      // keep at least one
    setDispSel(d.study_id, next);
    render(v);
  });
  const rst = v.querySelector(".msel-reset");
  if (rst) rst.onclick = e => { e.stopPropagation(); setDispSel(d.study_id, null); render(v); };
  // metric tile click → the Experiments tab, focused on that metric
  v.querySelectorAll(".stat-link").forEach(n => n.onclick = () => {
    S.focusMetric = n.dataset.goto;
    switchTab("experiments");
  });
  // stat tile count-up: animate only when the value changes or on a real switch (body.anim)
  v.querySelectorAll(".cnt").forEach(n => {
    const val = parseFloat(n.dataset.v);
    if (!isFinite(val)) return;
    const pct = n.dataset.pct === "1";
    const fmt = x => pct ? (x * 100).toFixed(1) + "%" : fmtNum(x);
    const key = S.cur + "@" + (d.viewing_version || "") + "|" + n.dataset.k;
    const prev = PREV_STAT.get(key);
    PREV_STAT.set(key, val);
    if (prev === val && !document.body.classList.contains("anim")) return;   // at rest: innerHTML already holds the right value
    countUp(n, val, fmt, (prev != null && prev !== val) ? prev : 0);
  });
}
