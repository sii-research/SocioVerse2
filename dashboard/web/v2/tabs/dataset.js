// ── Dataset tab: all of this study's data assets — DuckDB table browser, file list, download/export ──
import { S } from "../store.js";
import { T, getLang } from "../i18n.js";
import { el, escHtml, escAttr, fmtSize, toast } from "../ui.js";
import * as api from "../api.js";
import { chatPrefill } from "../chat.js";
import { card, lblRow, emptyState } from "./common.js";

let tablesCache = null, tablesFor = null;
let curTable = null, page = 0;
const PAGE = 50;
let filesCache = null, filesFor = null;

const KIND_IC = { db:"🗄", parquet:"🧱", image:"🖼", table:"📊", data:"🧾", doc:"📄", code:"🐍", file:"📁" };

export async function render(v){
  const d = S.detail;
  const key = S.cur + "@" + (S.ver || "");
  if (tablesFor !== key){ tablesCache = null; curTable = null; page = 0; }
  if (filesFor !== key) filesCache = null;

  let html = card(`${lblRow("ds_tables")}<div id="dsTables"><div class="skel" style="height:60px"></div></div>
    <div id="dsPreview" style="margin-top:12px"></div>`, { i: 0 });
  html += card(`${lblRow("ds_files", S.chatEnabled ? `<button class="btn sm" id="dsUpload">📎 ${escHtml(T("ds_upload"))}</button>` : "")}
    <div id="dsFiles"><div class="skel" style="height:60px"></div></div>`, { i: 1 });

  const canExport = S.chatEnabled && d.report_md && !S.ver;
  if (canExport){
    html += card(`${lblRow("export_lbl")}<div class="chips">
      <a class="btn sm" href="${api.exportUrl(S.cur, "docx")}" target="_blank">📄 Word</a>
      <a class="btn sm" href="${api.exportUrl(S.cur, "latex")}" target="_blank">🧾 LaTeX</a>
      <a class="btn sm" href="${api.exportUrl(S.cur, "all")}" target="_blank">🗃 ${escHtml(T("pp_all"))}</a>
    </div>`, { i: 2, cls: "flat" });
  }
  v.innerHTML = html;

  const up = el("dsUpload");
  if (up) up.onclick = () => el("fileInput").click();

  renderTables(key, d);
  renderFiles(key);
}

async function renderTables(key, d){
  const box = el("dsTables"); if (!box) return;
  if (!tablesCache || tablesFor !== key){
    try { tablesCache = await api.getTables(S.cur, S.ver); tablesFor = key; } catch(e){ tablesCache = { tables: [] }; }
  }
  const ts = tablesCache.tables || [];
  if (!ts.length){
    box.innerHTML = emptyState("🗄", "ds_empty_t", "ds_empty_s");
    el("dsPreview").innerHTML = "";
    return;
  }
  if (!curTable || !ts.some(t => t.name === curTable)){ curTable = (ts.find(t => t.name === "metrics") || ts[0]).name; page = 0; }
  const dsNote = d.metrics_downsampled ? `<div class="note muted" style="margin-top:8px">📉 ${escHtml(T("ds_downsampled"))} (stride ${d.metrics_downsampled.stride}, ${d.metrics_downsampled.full_rows} ${escHtml(T("ds_rows"))})</div>` : "";
  box.innerHTML = `<div class="chips">` + ts.map(t =>
    `<span class="legitem ${t.name === curTable ? "" : ""}" data-t="${escAttr(t.name)}" style="${t.name === curTable ? "border-color:var(--accent);background:var(--accent-bg)" : ""}">
       <span class="ldot" style="background:${t.name === curTable ? "var(--accent)" : "var(--faint)"}"></span>
       <b>${escHtml(t.name)}</b>&nbsp;<span class="muted mono" style="font-size:10px">${t.rows.toLocaleString()} ${escHtml(T("ds_rows"))} · ${t.columns.length} ${escHtml(T("ds_cols"))}</span></span>`).join("") + `</div>` + dsNote;
  box.querySelectorAll("[data-t]").forEach(n => n.onclick = () => { curTable = n.dataset.t; page = 0; renderTables(key, d); });
  renderPreview();
}

async function renderPreview(){
  const box = el("dsPreview"); if (!box || !curTable) return;
  box.innerHTML = `<div class="skel" style="height:120px"></div>`;
  let r;
  try { r = await api.getTableRows(S.cur, curTable, PAGE, page * PAGE, S.ver); } catch(e){ box.innerHTML = ""; return; }
  if (r.error){ box.innerHTML = `<div class="kv muted">${escHtml(r.error)}</div>`; return; }
  const isNum = ci => r.rows.every(row => row[ci] == null || typeof row[ci] === "number");
  const fmtCell = x => x == null ? "—" : (typeof x === "number" ? (Number.isInteger(x) ? x.toLocaleString() : x.toFixed(4).replace(/\.?0+$/, "")) : String(x).slice(0, 120));
  const pages = Math.max(1, Math.ceil(r.total / PAGE));
  const isStatic = !!window.__SV_STATIC;   // static gallery: only the first page of data, no CSV endpoint
  box.innerHTML = `<div class="dtable-wrap"><table class="dtable">
      <thead><tr>${r.columns.map(c => `<th>${escHtml(c)}</th>`).join("")}</tr></thead>
      <tbody>${r.rows.map(row => `<tr>${row.map((x, ci) => `<td class="${isNum(ci) ? "num" : ""}" title="${escAttr(String(x ?? ""))}">${escHtml(fmtCell(x))}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>
    <div style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:11.5px;color:var(--muted)">
      ${isStatic ? "" : `<button class="btn sm" id="dsPrev" ${page <= 0 ? "disabled" : ""}>‹</button>
      <span class="mono">${page + 1}/${pages}</span>
      <button class="btn sm" id="dsNext" ${page >= pages - 1 ? "disabled" : ""}>›</button>`}
      <span>${escHtml(T("ds_total"))} ${r.total.toLocaleString()} ${escHtml(T("ds_rows"))}${isStatic && r.total > r.rows.length ? ` · ${escHtml(T("ds_preview"))} ${r.rows.length}` : ""}</span>
      ${isStatic ? "" : `<a class="btn sm" style="margin-left:auto" href="${api.tableCsvUrl(S.cur, curTable)}" download>⬇ ${escHtml(T("ds_download"))}</a>`}
    </div>`;
  if (!isStatic){
    el("dsPrev").onclick = () => { if (page > 0){ page--; renderPreview(); } };
    el("dsNext").onclick = () => { page++; renderPreview(); };
  }
}

async function renderFiles(key){
  const box = el("dsFiles"); if (!box) return;
  if (!filesCache || filesFor !== key){
    try { filesCache = await api.getFiles(S.cur, S.ver); filesFor = key; } catch(e){ filesCache = { groups: [] }; }
  }
  const gs = (filesCache.groups || []).filter(g => g.files.length);
  if (!gs.length){ box.innerHTML = `<div class="kv muted">${escHtml(T("none"))}</div>`; return; }
  const openable = f => ["table","data","doc","code","image"].includes(f.kind) && f.size < 5 * 1024 * 1024;
  const localOpen = !!(S.state && S.state.local_open);   // self-hosted form: open with the system default app / show in folder
  box.innerHTML = gs.map(g => `
    <div style="font-size:11px;color:var(--faint);font-family:var(--mono);margin:10px 0 3px">${escHtml(g.dir)}/</div>`
    + g.files.map(f => `<div class="frow"><span class="f-ic">${KIND_IC[f.kind] || "📁"}</span>
        <span class="f-nm">${escHtml(f.name)}</span><span class="f-meta">${fmtSize(f.size)} · ${f.ts}</span>
        <span class="f-act">${openable(f) ? `<a class="btn sm" target="_blank" href="${api.fileUrl(S.cur, S.ver, f.rel)}">${escHtml(T("ds_open"))}</a>` : ""}${localOpen ? `
          <button class="btn sm" data-lopen="${escAttr(f.rel)}" title="${escAttr(T("ds_sysopen_t"))}">↗ ${escHtml(T("ds_sysopen"))}</button>
          <button class="btn sm" data-lreveal="${escAttr(f.rel)}" title="${escAttr(T("ds_reveal_t"))}">📂</button>` : ""}</span>
      </div>`).join("")).join("")
    + (filesCache.truncated ? `<div class="kv muted" style="font-size:11px">…</div>` : "")
    + (!localOpen && S.chatEnabled ? `<div class="kv" style="font-size:10.5px;color:var(--faint);margin-top:12px">${escHtml(T("ds_selfdeploy"))} <a href="https://github.com/sii-research/SocioVerse2" target="_blank" rel="noopener" style="font-size:10.5px">GitHub ↗</a></div>` : "");
  const doOpen = (rel, mode) => fetch(api.apiUrl(`api/study/${encodeURIComponent(S.cur)}/open-file`), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rel, mode }) })
    .then(r => r.json()).then(d => toast(d.ok ? T("ds_opened") : (d.error || "error"), d.ok ? "ok" : "err"))
    .catch(() => toast("error", "err"));
  box.querySelectorAll("[data-lopen]").forEach(b => b.onclick = () => doOpen(b.dataset.lopen, "open"));
  box.querySelectorAll("[data-lreveal]").forEach(b => b.onclick = () => doOpen(b.dataset.lreveal, "reveal"));
}

import { on } from "../store.js";
on("uploaded", () => { filesCache = null; if (S.tab === "dataset"){ const b = el("dsFiles"); if (b) renderFiles(S.cur + "@" + (S.ver || "")); } });
