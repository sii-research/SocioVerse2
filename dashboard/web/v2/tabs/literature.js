// ── Literature tab: related-paper cards (per-paper relevance notes), themes, references.bib ──
import { S } from "../store.js";
import { T, getLang } from "../i18n.js";
import { el, escHtml, escAttr } from "../ui.js";
import * as api from "../api.js";
import { chatPrefill } from "../chat.js";
import { card, lblRow, emptyState } from "./common.js";

let litCache = null, litFor = null;

export async function render(v){
  const d = S.detail;
  const info = d.literature_info || {};

  if (!info.exists){
    const act = S.chatEnabled ? `<button class="btn primary" id="litStart">🔍 ${escHtml(T("lit_start"))}</button>` : "";
    v.innerHTML = card(emptyState("📚", "lit_empty_t", "lit_empty_s", act), { i: 0 });
    const b = el("litStart");
    if (b) b.onclick = () => chatPrefill(getLang() === "zh"
      ? "请围绕本研究的研究问题做一轮文献调研：检索真实论文，逐篇写相关性笔记，生成 literature/literature.json 与 references.bib。"
      : "Survey related work for this study's research question: retrieve real papers, write per-paper relevance notes, produce literature/literature.json and references.bib.");
    return;
  }

  const key = S.cur + "@" + (S.ver || "") + "@" + (info.ts || "");
  if (litFor !== key) litCache = null;
  v.innerHTML = card(`${lblRow("lit_papers", `<span class="chip">${info.ts || ""}</span>${S.chatEnabled ? ` <button class="btn sm" id="litMore">🔍 ${escHtml(T("lit_more"))}</button>` : ""}`)}
    <div id="litBody"><div class="skel" style="height:120px"></div></div>`, { i: 0 });
  const more = el("litMore");
  if (more) more.onclick = () => chatPrefill(getLang() === "zh"
    ? "在现有文献调研基础上继续检索：（说明补充方向，例如 某个方法分支 / 更近期的工作）"
    : "Extend the literature survey: (what to add, e.g. a method branch / more recent work)");

  if (!litCache){
    try { litCache = await api.getLiterature(S.cur, S.ver); litFor = key; } catch(e){ litCache = null; }
  }
  const box = el("litBody"); if (!box) return;
  if (!litCache || !litCache.exists){ box.innerHTML = `<div class="kv muted">${escHtml(T("none"))}</div>`; return; }
  const data = litCache.data || {};
  const papers = data.papers || [];
  const themes = data.themes || [];

  let html = "";
  if (data.summary) html += `<div class="kv" style="margin:0 0 12px">${escHtml(data.summary)}</div>`;
  if (themes.length){
    html += `<div style="font-size:11px;color:var(--faint);font-family:var(--mono);margin:0 0 6px">${escHtml(T("lit_themes"))}</div>
      <div class="chips" style="margin-bottom:14px">${themes.map(t => `<span class="chip"><b>${escHtml(typeof t === "string" ? t : t.name || "")}</b>${t.n ? ` · ${t.n}` : ""}</span>`).join("")}</div>`;
  }
  html += `<div class="vgrid g2">` + papers.map((p, i) => {
    const link = p.url ? `<a href="${escAttr(p.url)}" target="_blank" rel="noopener" style="text-decoration:none">${escHtml(p.title || "")}</a>` : escHtml(p.title || "");
    const meta = [p.venue, p.year, p.citations != null ? `${p.citations} ${T("lit_cites")}` : null].filter(Boolean).join(" · ");
    const rel = p.relevance != null ? `<span class="pill" style="background:var(--teal-bg);color:var(--teal)">${escHtml(T("lit_rel"))} ${typeof p.relevance === "number" ? (p.relevance * (p.relevance <= 1 ? 100 : 1)).toFixed(0) + "%" : escHtml(String(p.relevance))}</span>` : "";
    return `<div class="card flat rise" style="--i:${i % 8}">
      <div style="display:flex;gap:8px;align-items:flex-start;justify-content:space-between">
        <div style="font-weight:600;font-size:13px;line-height:1.45;min-width:0">${link}</div>${rel}</div>
      <div class="muted" style="font-size:11px;margin:3px 0 6px">${escHtml((p.authors || []).slice(0, 4).join(", "))}${(p.authors || []).length > 4 ? " et al." : ""}${meta ? ` · ${escHtml(meta)}` : ""}</div>
      ${p.note ? `<div class="kv" style="font-size:12.5px;margin:0">${escHtml(p.note)}</div>` : (p.abstract ? `<div class="kv muted" style="font-size:12px;margin:0">${escHtml(String(p.abstract).slice(0, 220))}…</div>` : "")}
    </div>`;
  }).join("") + `</div>`;

  if (litCache.bib){
    html += `<details style="margin-top:14px"><summary style="font-size:12px;color:var(--muted);cursor:pointer">${escHtml(T("lit_bib"))} <a class="btn sm" style="margin-left:8px" href="${api.fileUrl(S.cur, S.ver, "literature/references.bib")}" download>⬇ ${escHtml(T("lit_dl"))}</a></summary>
      <pre class="md" style="background:var(--surface-2);border-radius:9px;padding:10px 12px;font-size:11px;overflow-x:auto;font-family:var(--mono)">${escHtml(litCache.bib.slice(0, 20000))}</pre></details>`;
  }
  box.innerHTML = html;
}
