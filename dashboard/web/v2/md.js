// ── minimal markdown renderer (headings, bold, code, hr, lists, tables, figures) ──
import { T } from "./i18n.js";
import { escHtml, escAttr } from "./ui.js";

// missing-figure placeholder: when a referenced figure 404s, show an explicit "figure missing" card instead of a broken icon
window.__figmiss = img => {
  const box = img.closest(".mdfig");
  if (!box) return;
  const alt = img.alt || (box.querySelector(".cap")?.textContent || "figure");
  const d = document.createElement("div");
  d.className = "figmiss";
  d.textContent = "🖼 " + alt + " — " + T("fig_missing");
  box.replaceWith(d);
};

// ── math: $…$ / \(…\) inline, $$…$$ / \[…\] display (may span lines). KaTeX is self-hosted in vendor/katex ──
// Formulas are first pulled out into placeholders before the line-by-line rendering below (otherwise a multi-line \[…\] would be split into several <p> and | would cut tables),
// emitting <span class="mtex" data-tex>source</span>; once KaTeX is ready they are typeset together, and if it failed to load the source is shown.
// The inline $ rule avoids hitting amounts of money: no whitespace after the opening $, none before the closing $, and no digit right after it ($5, $2-$3 are not formulas).
const MATH_RE = /(`[^`\n]*`)|\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\d)/g;
function stashMath(md, bag){
  return md.split(/(```[\s\S]*?```)/).map((part, k) => k % 2 ? part :      // code fences as-is
    part.replace(MATH_RE, (m, code, dd, db, ip, id) => {
      if (code) return m;                                                  // inline code as-is
      const display = dd !== undefined || db !== undefined;
      bag.push({ tex: (dd ?? db ?? ip ?? id).trim(), display, raw: m });
      return `\u0001${bag.length - 1}\u0002`;
    })).join("");
}
let _katexReq = false, _typesetQueued = false;
function typesetMath(){
  _typesetQueued = false;
  if (!window.katex) return;
  document.querySelectorAll("span.mtex:not([data-done])").forEach(el => {
    el.dataset.done = "1";
    try {
      el.innerHTML = window.katex.renderToString(el.dataset.tex, {
        displayMode: el.classList.contains("mtex-d"), throwOnError: false, strict: "ignore", output: "html" });
    } catch(e){}
  });
}
function queueTypeset(){
  if (!_katexReq){                                                         // load KaTeX only when the first formula appears
    _katexReq = true;
    const base = new URL("./vendor/katex/", import.meta.url).href;
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = base + "katex.min.css";
    const js = document.createElement("script"); js.src = base + "katex.min.js"; js.onload = typesetMath;
    document.head.append(css, js);
    // render points are scattered (chat streaming, report/paper tabs) and all replace innerHTML: watch the DOM for newly added formula nodes
    new MutationObserver(() => { if (!_typesetQueued){ _typesetQueued = true; requestAnimationFrame(typesetMath); } })
      .observe(document.body, { childList: true, subtree: true });
  }
  if (!_typesetQueued){ _typesetQueued = true; requestAnimationFrame(typesetMath); }
}

// figSrc: resolve the file name of ![alt](path) to an image URL; null → keep the source text
export function mdToHtml(md, figSrc = null){
  if (!md) return "";
  const bag = [];
  md = stashMath(md, bag);
  const html = mdBlocks(md, figSrc);
  if (!bag.length) return html;
  queueTypeset();
  const escT = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  return html.replace(/\u0001(\d+)\u0002/g, (_, n) => {
    const m = bag[+n];
    return m ? `<span class="mtex${m.display ? " mtex-d" : ""}" data-tex="${escAttr(m.tex)}">${escT(m.raw)}</span>` : "";
  });
}

function mdBlocks(md, figSrc){
  const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const b = s => esc(s).replace(/\*\*(.+?)\*\*/g,"<b>$1</b>").replace(/`(.+?)`/g,"<code>$1</code>");
  const lines = md.split("\n"); let out = [], i = 0;
  while (i < lines.length){
    let l = lines[i];
    if (/^```/.test(l)){                                     // fenced code
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])){ buf.push(lines[i]); i++; }
      i++; out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`); continue;
    }
    if (/^\|.*\|/.test(l)){
      const tbl = []; while (i < lines.length && /^\|.*\|/.test(lines[i])){ tbl.push(lines[i]); i++; }
      const cells = r => r.split("|").slice(1,-1).map(c => c.trim());
      let t = "<table>"; tbl.forEach((r,ri) => { if (/^\|[\s:|-]+\|$/.test(r)) return;
        const tag = ri === 0 ? "th" : "td"; t += "<tr>" + cells(r).map(c => `<${tag}>${b(c)}</${tag}>`).join("") + "</tr>"; });
      out.push(t + "</table>"); continue;
    }
    const imgm = l.match(/^!\[([^\]]*)\]\(([^)]+)\)\s*$/);
    if (imgm && figSrc){
      const alt = imgm[1] || "", name = (imgm[2] || "").split("/").pop();
      const src = figSrc(name);
      const capJs = (alt || name).replace(/[\\'"]/g, " ");
      out.push(`<div class="mdfig" onclick="window.__lightbox('${src}','${capJs}')"><img src="${src}" alt="${escAttr(alt)}" loading="lazy" onerror="window.__figmiss&&window.__figmiss(this)"/><div class="cap">${escHtml(alt || name)} · ${escHtml(T("click_enlarge"))}</div></div>`);
      i++; continue;
    }
    if (/^>\s?/.test(l)){ const qs = []; while (i < lines.length && /^>\s?/.test(lines[i])){ qs.push(b(lines[i].replace(/^>\s?/, ""))); i++; } out.push(`<blockquote>${qs.join("<br/>")}</blockquote>`); continue; }
    if (/^#{1,4}\s/.test(l)){ const n = Math.min(3, l.match(/^#+/)[0].length); out.push(`<h${n}>${b(l.replace(/^#+\s/,""))}</h${n}>`); }
    else if (/^---+$/.test(l)){ out.push("<hr/>"); }
    else if (/^[-*]\s/.test(l)){ const items=[]; while (i < lines.length && /^[-*]\s/.test(lines[i])){ items.push(`<li>${b(lines[i].replace(/^[-*]\s/,""))}</li>`); i++; } out.push("<ul>" + items.join("") + "</ul>"); continue; }
    else if (/^\d+\.\s/.test(l)){ const start = parseInt(l, 10); const items=[]; while (i < lines.length && /^\d+\.\s/.test(lines[i])){ items.push(`<li>${b(lines[i].replace(/^\d+\.\s/,""))}</li>`); i++; }
      out.push((start > 1 ? `<ol start="${start}">` : "<ol>") + items.join("") + "</ol>"); continue; }   // numbered lists split by paragraphs/formulas keep counting instead of restarting at 1 in every segment
    else if (l.trim()) out.push(`<p>${b(l)}</p>`);
    i++;
  }
  return out.join("");
}
