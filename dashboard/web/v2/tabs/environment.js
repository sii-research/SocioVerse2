// ── Environment tab: environment layers, the intervention timeline (scheduled events / broadcasts), uploaded materials, grounding facts ──
import { S } from "../store.js";
import { T, getLang } from "../i18n.js";
import { el, escHtml, escAttr, fmtSize } from "../ui.js";
import * as api from "../api.js";
import { CHAT, chatPrefill } from "../chat.js";
import { card, lblRow, emptyState, stagePill, stageNotes, stageNarrative } from "./common.js";

const LAYER_IC = { information:"📰", physical:"🌍", macro:"🏛", local:"📍" };

let filesCache = null, filesFor = null;

export async function render(v){
  const d = S.detail;
  const e = d.environment;
  const s = d.stages.find(x => x.name === "sv-build-environment");

  if (!e){
    const act = S.chatEnabled ? `<button class="btn primary" id="envStart">💬 ${escHtml(T("qa_env_event"))}</button>` : "";
    v.innerHTML = card(emptyState("🌍", "env_empty_t", "env_empty_s", act), { i: 0 });
    const b = el("envStart"); if (b) b.onclick = () => chatPrefill(getLang() === "zh"
      ? "请构建本研究的环境：描述 agent 所处的世界、需要检索的真实事件与背景信息。"
      : "Please build this study's environment: the world the agents live in, with real-world events and context to retrieve.");
    return;
  }

  const layers = (e.layers || []).map(L => {
    const ic = LAYER_IC[(L.axis || "").split("/")[0]] || "🧭";
    return `<div class="layer"><span class="l-ic">${ic}</span>
      <span style="min-width:0"><div class="l-nm">${escHtml(L.name || "")}</div>
      <div class="l-ax">${escHtml(L.axis || "")}${L.dynamics ? " · " + escHtml(String(L.dynamics).slice(0, 60)) : ""}</div></span></div>`;
  }).join("");

  const evs = (e.scheduled_events || []).map(x => ({ step: x.at_step, kind: "iv", txt: x.note || "" }));
  const bcs = (e.broadcasts || []).map(x => ({ step: x.at_step, kind: "bc", txt: x.content || "", sub: (x.audience || "") + (x.channel ? " · " + x.channel : "") }));
  const timeline = [...evs, ...bcs].sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
  // In a branch view, interventions before the fork step are inherited from the parent by replay — grey them out and mark them "inherited".
  // Without a fork_step (a version node, or the server did not provide one) everything is shown at full strength as usual.
  const ventry = (d.versions || []).find(x => x && x.id === (d.viewing_version || ""));
  const forkStep = (ventry && ventry.kind === "branch" && ventry.fork_step != null) ? ventry.fork_step : null;
  const tlHtml = timeline.length ? `<div class="tl">` + timeline.map(t => {
    const inh = forkStep != null && t.step != null && t.step < forkStep;
    return `<div class="tl-it ${t.kind === "bc" ? "bc" : ""}"${inh ? ` style="opacity:.55"` : ""}>
       <span class="t-step">step ${t.step ?? "?"} · ${escHtml(t.kind === "bc" ? T("env_bc") : T("env_interv"))}</span>${
         inh ? ` <span class="chip" title="${escAttr(T("env_iv_inherited_t"))}" style="font-size:9.5px;padding:1px 6px">${escHtml(T("env_iv_inherited"))}</span>` : ""}
       <div class="t-txt">${escHtml(t.txt)}</div>
       ${t.sub ? `<div class="t-sub">${escHtml(t.sub)}</div>` : ""}</div>`; }).join("") + `</div>`
    : `<div class="kv muted">${escHtml(T("env_none"))}</div>`;

  let html = `<div class="vgrid g2">`
    + card(`${lblRow("env_layers", stagePill(d, "sv-build-environment"))}${layers || `<div class="kv muted">${escHtml(T("none"))}</div>`}${stageNotes(d, "sv-build-environment")}${stageNarrative(d, "sv-build-environment")}`, { i: 0 })
    + card(`${lblRow("env_timeline", `<span class="chip">${evs.length} ${escHtml(T("interventions"))}</span> <span class="chip">${bcs.length} ${escHtml(T("broadcasts"))}</span>`)}${tlHtml}`, { i: 1 })
    + `</div>`;

  html += card(`${lblRow("env_uploads")}<div id="envUploads"><div class="skel" style="height:34px"></div></div>`, { i: 2, cls: "flat" });
  v.innerHTML = html;
  renderUploads(el("envUploads"));
}

async function renderUploads(box){
  if (!box) return;
  const key = S.cur + "@" + (S.ver || "");
  if (filesFor !== key || !filesCache){
    try { filesCache = await api.getFiles(S.cur, S.ver); filesFor = key; } catch(e){ filesCache = null; }
  }
  const ups = (filesCache?.groups || []).find(g => g.dir === "uploads");
  if (!ups || !ups.files.length){
    box.innerHTML = `<div class="kv muted">${escHtml(T("none"))} — ${escHtml(getLang() === "zh" ? "在右侧对话栏用 ＋ 上传，或直接拖拽文件进对话" : "upload via ＋ in the chat dock, or drag a file into the conversation")}</div>`;
    return;
  }
  box.innerHTML = ups.files.map(f =>
    `<div class="frow"><span class="f-ic">📎</span><span class="f-nm">${escHtml(f.name)}</span>
       <span class="f-meta">${fmtSize(f.size)} · ${f.ts}</span>
       ${S.chatEnabled ? `<span class="f-act"><button class="btn sm" data-rel="${escAttr(f.rel)}">💬 ${escHtml(T("env_add"))}</button></span>` : ""}</div>`).join("");
  box.querySelectorAll("[data-rel]").forEach(b => b.onclick = () => chatPrefill(getLang() === "zh"
    ? `请读取 ${b.dataset.rel}，把其中的相关信息纳入环境构建（说明用途：作为事实来源/事件依据/背景资料）。`
    : `Please read ${b.dataset.rel} and incorporate the relevant information into the environment (state how: facts / event basis / background).`));
}

// refresh the list right after an upload completes
import { on } from "../store.js";
on("uploaded", () => { filesCache = null; const b = el("envUploads"); if (b && S.tab === "environment") renderUploads(b); });
