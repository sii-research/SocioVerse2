// ── tiny DOM / format helpers shared by every module ────────────────────────
export const el = id => document.getElementById(id);
export const escHtml = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
export const escAttr = s => escHtml(s).replace(/"/g, "&quot;");
export const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export function fmtNum(v){
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e6) return (v/1e6).toFixed(2).replace(/\.?0+$/,"") + "M";
  if (a >= 1e4) return (v/1e3).toFixed(1).replace(/\.0$/,"") + "k";
  if (a >= 100 || Number.isInteger(v)) return Math.round(v).toLocaleString();
  return a < 1 ? v.toFixed(3) : v.toFixed(2);
}
export function fmtVal(v){
  if (typeof v === "number") return Math.abs(v) < 1 && v !== 0 ? v.toFixed(3) : (Number.isInteger(v) ? String(v) : v.toFixed(2));
  if (v === null || v === undefined) return "—";
  if (typeof v === "object"){ try{ const s = JSON.stringify(v); return s.length > 80 ? s.slice(0,80)+"…" : s; }catch(e){ return "{…}"; } }
  return String(v);
}
export function fmtSize(n){
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024*1024) return (n/1024).toFixed(1) + " KB";
  return (n/1024/1024).toFixed(1) + " MB";
}

export function toast(msg, kind = ""){
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  el("toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, 2600);
  setTimeout(() => t.remove(), 3000);
}

export function openLightbox(src, cap){
  el("lightboxImg").src = src;
  el("lightboxCap").textContent = cap || "";
  el("lightbox").style.display = "flex";
}
el("lightbox")?.addEventListener("click", () => { el("lightbox").style.display = "none"; });

// view-transition wrapper: runs directly when unsupported (progressive enhancement)
export function withTransition(fn){
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (document.startViewTransition && !reduce) document.startViewTransition(fn);
  else fn();
}

// count-up number animation (stat tiles; from → target, settles immediately under reduced-motion)
export function countUp(node, target, fmt, from = 0){
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || !isFinite(target)){
    node.textContent = fmt(target); return;
  }
  const dur = 620, t0 = performance.now();
  const tick = now => {
    const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    node.textContent = fmt(from + (target - from) * e);
    if (p < 1) requestAnimationFrame(tick); else node.textContent = fmt(target);
  };
  requestAnimationFrame(tick);
}

// skeleton block helper
export const skel = (h, w = "100%", extra = "") =>
  `<div class="skel" style="height:${h}px;width:${w};${extra}"></div>`;

export function debounce(fn, ms){
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
