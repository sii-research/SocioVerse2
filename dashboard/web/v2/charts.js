// ── chart library (dataviz-spec compliant: crosshair+unified tooltip, legend-as-
//    filter-chips, solid hairline grid, ≤3-series area wash, % axis for shares) ──
import { T } from "./i18n.js";
import { escHtml, escAttr, cssv, fmtNum } from "./ui.js";

export const PALETTE = ["#378ADD","#1d9e75","#d85a30","#534ab7","#d4537e"];   // validated (light+dark)

const svPath = P => "M" + P.map(p => p.join(",")).join(" L");

// ── multi-series step/line chart with baseline overlay ──────────────────────
// box: container element (needs CSS height). legendEl: element for legend chips.
// opts: {rows, baseRows, pick, hidden(Set), onToggle(fn), descriptions, interventions,
//        baseInterventions, curLabel, baseLabel}
export function lineChart(box, legendEl, opts){
  const { rows = [], baseRows = [], pick = [], hidden = new Set(),
          onToggle = null, descriptions = {}, interventions = [],
          interventionNotes = {}, baseInterventions = [], curLabel = "", baseLabel = "" } = opts;
  const all = pick.slice(0, 5).filter(m => rows.some(r => r[m] != null) || baseRows.some(r => r[m] != null));
  if ((!rows.length && !baseRows.length) || !all.length){ box.innerHTML = ""; if (legendEl) legendEl.innerHTML = ""; return false; }

  const colorOf = m => PALETTE[all.indexOf(m) % PALETTE.length];
  const ext = {};
  all.forEach(m => {
    let vs = []; rows.forEach(r => { if (r[m] != null) vs.push(r[m]); }); baseRows.forEach(r => { if (r[m] != null) vs.push(r[m]); });
    const rr = rows.filter(r => r[m] != null);
    ext[m] = { mn: vs.length ? Math.min(...vs) : 0, mx: vs.length ? Math.max(...vs) : 1, last: rr.length ? rr[rr.length-1][m] : null };
    ext[m].rng = (ext[m].mx - ext[m].mn) || 1;
  });
  const metrics = all.filter(m => !hidden.has(m));
  const mags = metrics.map(m => Math.max(Math.abs(ext[m].mn), Math.abs(ext[m].mx))).filter(v => v > 1e-9);
  const NORM = mags.length > 1 && Math.max(...mags) / Math.min(...mags) > 20;
  const PCT = all.length && all.every(m => ext[m].mn >= -0.001 && ext[m].mx <= 1.05);
  const fmtV = v => (v == null || isNaN(v)) ? "—" : (PCT ? (v*100).toFixed(1) + "%" : fmtNum(v));

  if (legendEl){
    legendEl.innerHTML = all.map(m => { const h = hidden.has(m), e = ext[m];
      const valTxt = (e && e.last != null) ? ` <span class="mono" style="font-size:10px">${fmtV(e.last)}</span>` : "";
      const dot = `<span class="ldot" style="${h ? `border:1.5px solid ${colorOf(m)}` : `background:${colorOf(m)}`}"></span>`;
      return `<span class="legitem" role="button" aria-pressed="${!h}" data-m="${escAttr(m)}" title="${escAttr((descriptions[m] ? descriptions[m] + " — " : "") + T("range") + " " + fmtV(e.mn) + "–" + fmtV(e.mx) + " · " + (h ? T("click_show") : T("click_hide")))}" style="${h ? "opacity:.55" : ""}">${dot}<span class="muted" style="${h ? "text-decoration:line-through" : ""}">${escHtml(m)}</span>${valTxt}</span>`; }).join("")
      + (NORM ? `<span class="muted" style="font-size:10px">· ${escHtml(T("normalized"))}</span>` : "")
      + (baseRows.length ? `<span class="muted" style="margin-left:auto">— ${escHtml(curLabel)} &nbsp;·&nbsp; ┅ ${escHtml(baseLabel)}</span>` : "");
    if (onToggle) legendEl.querySelectorAll(".legitem").forEach(n => n.onclick = () => onToggle(n.dataset.m));
  }
  if (!metrics.length){ box.innerHTML = `<div class="muted" style="font-size:12px;padding:20px 0">${escHtml(T("all_hidden"))}</div>`; return true; }

  const _cw = box.clientWidth, _chh = box.clientHeight;
  const W = _cw > 60 ? _cw : 560, H = _chh > 60 ? _chh : 220, pl = 42, pr = 12, pt = 12, pb = 26;
  const steps = [...new Set([...rows.map(r => r.step), ...baseRows.map(r => r.step)])].sort((a,b) => a-b);
  const xmin = Math.min(...steps), xmax = Math.max(...steps);
  let ymin = 0, ymax = 1, yr = 1;
  if (!NORM){ let vals = []; metrics.forEach(m => { rows.forEach(r => { if (r[m] != null) vals.push(r[m]); }); baseRows.forEach(r => { if (r[m] != null) vals.push(r[m]); }); });
    ymin = Math.min(...vals); ymax = Math.max(...vals); yr = (ymax - ymin) || 1; }
  const X = s => pl + (xmax === xmin ? 0 : (s - xmin) / (xmax - xmin)) * (W - pl - pr);
  const Y = (v,m) => NORM ? pt + (1 - (v - ext[m].mn) / ext[m].rng) * (H - pt - pb) : pt + (1 - (v - ymin) / yr) * (H - pt - pb);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" style="width:100%;height:${H}px">`;
  svg += `<line x1="${pl}" y1="${H-pb}" x2="${W-pr}" y2="${H-pb}" stroke="${cssv("--border")}"/>`;
  const grid = y => { svg += `<line x1="${pl}" y1="${y}" x2="${W-pr}" y2="${y}" stroke="${cssv("--border")}" opacity="0.55"/>`; };
  const tickTxt = v => PCT ? (v*100).toFixed(0) + "%" : (Math.abs(v) >= 1000 ? fmtNum(v) : v.toFixed(2));
  if (NORM){
    [pt, (pt + H - pb) / 2].forEach(grid);
    svg += `<text x="${pl-6}" y="${pt+8}" text-anchor="end" font-size="9" fill="${cssv("--faint")}">${escHtml(T("norm_hi"))}</text>`;
    svg += `<text x="${pl-6}" y="${H-pb+3}" text-anchor="end" font-size="9" fill="${cssv("--faint")}">${escHtml(T("norm_lo"))}</text>`;
  } else {
    [ymin, (ymin+ymax)/2, ymax].forEach(v => { if (v !== ymin) grid(Y(v));
      svg += `<text x="${pl-6}" y="${Y(v)+3}" text-anchor="end" font-size="10" fill="${cssv("--faint")}" style="font-variant-numeric:tabular-nums">${tickTxt(v)}</text>`; });
  }
  interventions.forEach(s => { const xs = X(s), near = xs > W-pr-44;
    svg += `<line x1="${xs}" y1="${pt}" x2="${xs}" y2="${H-pb}" stroke="${cssv("--border")}" stroke-dasharray="3 3"/><text x="${near?xs-4:xs+3}" y="${pt+10}" font-size="10" text-anchor="${near?"end":"start"}" fill="${cssv("--faint")}">step ${s}</text>`; });
  if (baseRows.length) baseInterventions.filter(s => !interventions.includes(s)).forEach(s => { const xs = X(s), near = xs > W-pr-58;
    svg += `<line x1="${xs}" y1="${pt}" x2="${xs}" y2="${H-pb}" stroke="${cssv("--faint")}" stroke-dasharray="1 3"/><text x="${near?xs-4:xs+3}" y="${pt+22}" font-size="10" text-anchor="${near?"end":"start"}" fill="${cssv("--faint")}">step ${s} · ${escHtml(baseLabel)}</text>`; });
  if (baseRows.length) metrics.forEach(m => {
    const c = colorOf(m);
    const P = baseRows.filter(r => r[m] != null).map(r => [X(r.step), Y(r[m], m)]);
    if (P.length) svg += `<path d="${svPath(P)}" fill="none" stroke="${c}" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.55"/>`;
  });
  metrics.forEach((m, mi) => {
    const c = colorOf(m);
    const P = rows.filter(r => r[m] != null).map(r => [X(r.step), Y(r[m], m)]);
    if (!P.length) return;
    if (metrics.length <= 3){
      svg += `<defs><linearGradient id="af${mi}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="${metrics.length === 1 ? 0.22 : 0.10}"/><stop offset="1" stop-color="${c}" stop-opacity="0.01"/></linearGradient></defs>`;
      svg += `<path d="${svPath(P)} L${P[P.length-1][0]},${H-pb} L${P[0][0]},${H-pb} Z" fill="url(#af${mi})" stroke="none"/>`;
    }
    svg += `<path d="${svPath(P)}" fill="none" stroke="${c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`;
    const dots = P.length > 40 ? [P[0], P[P.length-1]] : P;
    dots.forEach(p => svg += `<circle cx="${p[0]}" cy="${p[1]}" r="2.6" fill="${c}" stroke="${cssv("--surface")}" stroke-width="1.3"/>`);
  });
  const xstep = Math.max(1, Math.ceil(steps.length / 12));
  steps.forEach((s, si) => { if (si % xstep === 0 || si === steps.length-1) svg += `<text x="${X(s)}" y="${H-pb+15}" text-anchor="middle" font-size="10" fill="${cssv("--faint")}" style="font-variant-numeric:tabular-nums">${s}</text>`; });
  svg += `<line class="xhair" x1="0" y1="${pt}" x2="0" y2="${H-pb}" stroke="${cssv("--accent")}" stroke-width="1" opacity="0" pointer-events="none"/>`;
  svg += `</svg>`;
  box.innerHTML = svg + `<div class="charttt"></div>`;
  hookHover(box, { steps, X, metrics, colorOf, rows, baseRows, fmtV, pl, pr, W,
                   hasBase: !!baseRows.length, ivNotes: interventionNotes });
  return true;
}

function hookHover(box, cx){
  const tt = box.querySelector(".charttt"), sv = box.querySelector("svg"), xh = box.querySelector(".xhair");
  if (!sv || !tt) return;
  const byStep = {}; cx.rows.forEach(r => { byStep[r.step] = r; });
  const baseBy = {}; (cx.baseRows || []).forEach(r => { baseBy[r.step] = r; });
  const move = ev => {
    const rect = sv.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (sv.viewBox.baseVal.width / rect.width);
    if (mx < cx.pl - 8 || mx > cx.W - cx.pr + 8){ leave(); return; }
    let best = null, bd = 1e9;
    cx.steps.forEach(s => { const d2 = Math.abs(cx.X(s) - mx); if (d2 < bd){ bd = d2; best = s; } });
    if (best == null) return;
    const sx = cx.X(best);
    xh.setAttribute("x1", sx); xh.setAttribute("x2", sx); xh.setAttribute("opacity", "0.5");
    const r = byStep[best] || {}, br = baseBy[best] || {};
    const evNote = (cx.ivNotes || {})[best];
    tt.innerHTML = `<div class="tstep">step ${best}</div>`
      + (evNote ? `<div class="tevent">⚡ ${escHtml(evNote)}</div>` : "")
      + cx.metrics.map(m => {
      const v = r[m], bv = cx.hasBase ? br[m] : null;
      if (v == null && bv == null) return "";
      return `<div class="trow"><span class="tkey" style="background:${cx.colorOf(m)}"></span><span class="tname">${escHtml(m)}</span><span class="tval">${cx.fmtV(v)}${cx.hasBase && bv != null ? ` <span style="color:var(--faint);font-weight:400">┅${cx.fmtV(bv)}</span>` : ""}</span></div>`;
    }).join("");
    tt.style.display = "block";
    const bw = box.clientWidth, twd = tt.offsetWidth, sxpx = sx * (rect.width / sv.viewBox.baseVal.width);
    tt.style.left = Math.min(Math.max(4, sxpx + 12), bw - twd - 4) + "px";
    if (sxpx + 12 + twd > bw - 8) tt.style.left = (sxpx - twd - 12) + "px";
    tt.style.top = "8px";
  };
  const leave = () => { tt.style.display = "none"; xh.setAttribute("opacity", "0"); };
  sv.addEventListener("pointermove", move); sv.addEventListener("pointerleave", leave);
}

// ── sparkline for stat tiles ────────────────────────────────────────────────
export function sparkline(values, color, w = 96, h = 26){
  const vs = values.filter(v => v != null && !isNaN(v));
  if (vs.length < 2) return "";
  const mn = Math.min(...vs), mx = Math.max(...vs), rng = (mx - mn) || 1;
  const P = vs.map((v, i) => [2 + i / (vs.length - 1) * (w - 4), 2 + (1 - (v - mn) / rng) * (h - 4)]);
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" class="spark">
    <path d="${svPath(P)}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>
    <circle cx="${P[P.length-1][0]}" cy="${P[P.length-1][1]}" r="2.3" fill="${color}" stroke="${cssv("--surface")}" stroke-width="1.2"/></svg>`;
}

// ── population composition (numeric hist + categorical stacked bars) ────────
export function popNum(v){ const a = Math.abs(v); return (a >= 100 || Number.isInteger(v)) ? Math.round(v).toLocaleString() : (+v.toFixed(a < 1 ? 2 : 1)); }
export function popDistHtml(dist, cap = 16){
  if (!dist || !dist.attrs || !dist.attrs.length) return "";
  const rows = dist.attrs.slice(0, cap).map(a => {
    if (a.kind === "num"){
      if (a.min === a.max)
        return `<div class="pd-row"><div class="pd-attr">${escHtml(a.attr)}</div><div class="pd-num"><div class="pd-const">= <b>${popNum(a.min)}</b> <span class="muted">${escHtml(T("pop_const"))}</span></div></div></div>`;
      const mx = Math.max(1, ...a.hist);
      const bars = a.hist.map(h => `<span class="pd-bar" style="height:${Math.round(3 + 27 * h / mx)}px" title="${h}"></span>`).join("");
      return `<div class="pd-row"><div class="pd-attr">${escHtml(a.attr)}</div><div class="pd-num">`
        + `<div class="pd-hist">${bars}</div>`
        + `<div class="pd-scale"><span>${popNum(a.min)}</span><span class="pd-med">${popNum(a.median)}</span><span>${popNum(a.max)}</span></div></div></div>`;
    }
    const segs = a.top.map((c,i) => `<span class="pd-seg" style="width:${(c.pct*100).toFixed(1)}%;opacity:${(1 - 0.12*i).toFixed(2)}" title="${escAttr(c.v)} · ${(c.pct*100).toFixed(0)}%"></span>`).join("");
    const otherPct = a.other > 0 ? a.other / a.n * 100 : 0;
    const other = otherPct > 0 ? `<span class="pd-seg pd-other" style="width:${otherPct.toFixed(1)}%" title="other ${otherPct.toFixed(0)}%"></span>` : "";
    const legend = a.top.slice(0,4).map(c => `<span class="pd-leg"><b>${escHtml(c.v)}</b> ${(c.pct*100).toFixed(0)}%</span>`).join("");
    const more = a.distinct > a.top.length ? `<span class="pd-leg muted">+${a.distinct - a.top.length}</span>` : "";
    return `<div class="pd-row"><div class="pd-attr">${escHtml(a.attr)}</div><div class="pd-cat">`
      + `<div class="pd-stack">${segs}${other}</div><div class="pd-legend">${legend}${more}</div></div></div>`;
  }).join("");
  return `<div class="popdist">${rows}</div>`;
}
