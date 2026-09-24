// ── Paper tab: stage report + paper draft (outline / per-section rewrite / export) ──
import { S } from "../store.js";
import { T, getLang } from "../i18n.js";
import { el, escHtml, escAttr } from "../ui.js";
import * as api from "../api.js";
import { mdToHtml } from "../md.js";
import { chatPrefill } from "../chat.js";
import { card, lblRow, emptyState, stagePill, stageNotes, stageNarrative } from "./common.js";

let paperCache = null, paperFor = null;

export async function render(v){
  const d = S.detail;
  const figSrc = name => api.figureUrl(S.cur, S.ver, name);

  let html = "";

  // ── paper draft ──
  const key = S.cur + "@" + (S.ver || "") + "@" + (d.paper_info?.ts || "");
  if (d.paper_info?.exists){
    if (paperFor !== key){ paperCache = null; }
    const pexp = S.chatEnabled && !S.ver
      ? `<a class="btn sm" href="${api.paperExportUrl(S.cur, "docx")}" target="_blank">📄 ${escHtml(T("pp_word"))}</a>
         <a class="btn sm" href="${api.paperExportUrl(S.cur, "latex")}" target="_blank">🧾 ${escHtml(T("pp_latex"))}</a>` : "";
    html += card(`${lblRow("pp_paper", `${pexp}<span class="chip">${escHtml(d.paper_info.ts || "")}</span>`)}
      <div id="ppBody"><div class="skel" style="height:120px"></div></div>`, { i: 0 });
  } else if (!window.__SV_STATIC){   // static gallery: drafting is impossible, so the empty-state card does not take the first screen
    const hasReport = !!d.report_md;
    const act = (S.chatEnabled && hasReport) ? `<button class="btn primary" id="ppDraft">✍️ ${escHtml(T("pp_write"))}</button>` : "";
    html += card(emptyState("📝", hasReport ? "pp_empty_t" : "pp_no_report_t", hasReport ? "pp_empty_s" : "pp_no_report_s", act), { i: 0 });
  }

  // ── stage report ──
  const s = d.stages.find(x => x.name === "sv-report");
  const canExport = S.chatEnabled && d.report_md && s && s.status === "done" && !S.ver;
  const expBar = canExport ? `<span class="lbl-r"><a class="btn sm" href="${api.exportUrl(S.cur, "docx")}" target="_blank">📄 ${escHtml(T("pp_word"))}</a>
      <a class="btn sm" href="${api.exportUrl(S.cur, "latex")}" target="_blank">🧾 ${escHtml(T("pp_latex"))}</a>
      <a class="btn sm" href="${api.exportUrl(S.cur, "all")}" target="_blank">🗃 ${escHtml(T("pp_all"))}</a></span>` : "";
  html += card(`${lblRow("pp_report", `${expBar}`)}${stagePill(d, "sv-report")}
    ${d.report_md ? `<div class="md" style="margin-top:8px">${mdToHtml(d.report_md, figSrc)}</div>` : `<div class="kv muted">report.md ${escHtml(T("not_built"))}</div>`}
    ${stageNotes(d, "sv-report")}${stageNarrative(d, "sv-report")}`, { i: 1 });

  v.innerHTML = html;

  const b = el("ppDraft");
  if (b) b.onclick = () => chatPrefill(getLang() === "zh"
    ? "请先做一轮文献调研（若尚未做过），再基于本研究的报告与数据起草完整论文（摘要/引言/相关工作/方法/结果/讨论），落到 paper/paper.md；图表引用本研究 figures，参考文献只用 literature/references.bib 里的条目。"
    : "Survey the related work first (if not done yet), then draft the full paper (abstract/intro/related work/methods/results/discussion) from this study's report and data into paper/paper.md; cite this study's figures and only bibkeys that exist in literature/references.bib.");

  if (d.paper_info?.exists){
    if (!paperCache || paperFor !== key){
      try { paperCache = await api.getPaper(S.cur, S.ver); paperFor = key; } catch(e){ paperCache = null; }
    }
    const box = el("ppBody"); if (!box) return;
    if (!paperCache || !paperCache.exists){ box.innerHTML = `<div class="kv muted">paper/paper.md ${escHtml(T("not_built"))}</div>`; return; }
    const secs = (paperCache.sections || []).filter(x => x.level <= 2);
    const outline = secs.length ? `<div style="flex:0 0 200px;max-width:200px;position:sticky;top:0;align-self:flex-start">
        <div style="font-size:11px;color:var(--faint);font-family:var(--mono);margin-bottom:5px">${escHtml(T("pp_outline"))}</div>
        ${secs.map((x, i) => `<div class="frow" style="padding:4px 8px"><span class="f-nm" style="font-size:12px;${x.level === 1 ? "font-weight:650" : "color:var(--muted)"}" data-sec="${i}">${escHtml(x.title)}</span>
          ${S.chatEnabled ? `<span class="f-act"><button class="btn sm" data-rw="${escAttr(x.title)}" title="rewrite">✍️</button></span>` : ""}</div>`).join("")}
      </div>` : "";
    box.innerHTML = `<div style="display:flex;gap:18px;align-items:flex-start">
      ${outline}
      <div class="md" style="flex:1 1 auto;min-width:0" id="ppMd">${mdToHtml(paperCache.md, figSrc)}</div></div>`;
    // outline click → scroll to heading; ✍️ → chat prefill rewrite
    const heads = box.querySelectorAll("#ppMd h1, #ppMd h2");
    box.querySelectorAll("[data-sec]").forEach((n, i) => n.onclick = () => { const h = heads[i]; if (h) h.scrollIntoView({ behavior: "smooth", block: "start" }); });
    box.querySelectorAll("[data-rw]").forEach(bb => bb.onclick = e => { e.stopPropagation();
      chatPrefill(getLang() === "zh" ? `请重写论文的「${bb.dataset.rw}」一节：（说明修改方向）` : `Rewrite the paper section “${bb.dataset.rw}”: (describe the change)`); });
  }
}
