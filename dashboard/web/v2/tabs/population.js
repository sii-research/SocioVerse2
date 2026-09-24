// ── Population tab: sampling config, population composition, searchable roster, persona cards ──
import { S } from "../store.js";
import { T, getLang } from "../i18n.js";
import { el, escHtml, escAttr, fmtVal } from "../ui.js";
import { popDistHtml } from "../charts.js";
import { CHAT, chatPrefill } from "../chat.js";
import { card, lblRow, emptyState, stagePill, stageNotes, stageNarrative, chip } from "./common.js";

let filter = "";

export function render(v){
  const d = S.detail;
  const p = d.population;

  if (!p){
    const act = S.chatEnabled ? `<button class="btn primary" id="popStart">💬 ${escHtml(T("qa_pop_adjust"))}</button>` : "";
    v.innerHTML = card(emptyState("👥", "pop_empty_t", "pop_empty_s", act), { i: 0 });
    const b = el("popStart"); if (b) b.onclick = () => chatPrefill(getLang() === "zh"
      ? "请构建本研究的目标人群：说明人群规模、结构与真实数据对齐方式。"
      : "Please build this study's target population: size, structure and how it aligns to real demographics.");
    return;
  }

  const head = `<div class="chips">${chip("provider: " + escHtml(p.provider_ref || "?"))}${chip("propagation: " + escHtml(p.propagation || "?"))}${chip("interaction: " + escHtml(p.interaction_kind || "?"))}${p.provider_args && p.provider_args.scale ? chip("scale: " + p.provider_args.scale) : ""}</div>
    <div class="kv">${p.persona_count ? `<b>${p.persona_count}</b> ${escHtml(T("agents_word"))} · ${escHtml(T("explicit_personas"))}` : escHtml(T("census_gen"))}</div>`;

  let html = card(`${lblRow("nav_population", stagePill(d, "sv-build-population"))}${head}${stageNotes(d, "sv-build-population")}${stageNarrative(d, "sv-build-population")}`, { i: 0 });

  if (p.distribution)
    html += card(`${lblRow("pop_composition", `<span class="chip"><b>${p.distribution.n_agents}</b> ${escHtml(T("agents_word"))}</span>`)}${popDistHtml(p.distribution)}`, { i: 1 });

  // roster (the roster is the pre-run form of the agents endpoint; after a run it holds the latest state)
  const ag = S.agents;
  if (ag && ag.count){
    html += card(`${lblRow("pop_roster", `<span class="chip">${ag.count}</span>`)}
      <input id="popFilter" type="text" placeholder="${escAttr(T("pop_search"))}" value="${escAttr(filter)}"
        style="width:100%;font:12.5px var(--font);border:1px solid var(--border);border-radius:9px;padding:6px 10px;background:var(--surface);color:var(--text);margin-bottom:9px"/>
      <div id="popRoster" style="max-height:380px;overflow:auto"></div>`, { i: 2 });
  }
  v.innerHTML = html;

  if (ag && ag.count){
    const paint = () => {
      const q = filter.trim().toLowerCase();
      const scalarDim = dd => dd !== "group" && dd !== "last_action" && dd !== "reason" && dd !== "rationale"
        && ag.agents.every(a => { const x = (a.state || {})[dd]; return x == null || typeof x !== "object"; });
      const declared = ((d.key_attributes) || []).filter(k => (ag.dims || []).includes(k) && scalarDim(k));
      const keyDims = (declared.length ? declared : (ag.dims || []).filter(scalarDim)).slice(0, 3);
      const list = ag.agents.filter(a => !q || a.agent_id.toLowerCase().includes(q)
        || keyDims.some(k => String((a.state || {})[k] ?? "").toLowerCase().includes(q))).slice(0, 400);
      el("popRoster").innerHTML = list.map(a => {
        const kvs = keyDims.map(k => (a.state && a.state[k] != null) ? `${escHtml(k)}: <b>${escHtml(fmtVal(a.state[k]))}</b>` : null).filter(Boolean).join(" · ");
        const grp = a.state && a.state.group != null ? `<span class="chip" style="font-size:9.5px;padding:1px 7px">${escHtml(String(a.state.group))}</span>` : "";
        return `<div class="frow"><span class="f-ic">🧑</span>
          <span class="f-nm mono" style="font-size:11.5px">${escHtml(a.agent_id)} ${grp}</span>
          <span class="f-meta" style="font-family:var(--font)">${kvs}</span></div>`;
      }).join("") || `<div class="kv muted">${escHtml(T("none"))}</div>`;
    };
    paint();
    const fi = el("popFilter");
    fi.oninput = () => { filter = fi.value; paint(); };
  }
}
