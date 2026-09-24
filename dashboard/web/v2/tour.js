// ── guidance tour: first-visit walkthrough ──────────────────────────────────────
//    Home-grown overlay highlight, no dependencies. The transcript always starts at the "standard" level (store.js default);
//    one stop of the tour explains the three levels and shows they can be switched anytime — no questionnaire to guess the user's preference.
import { S, getVerbosity, isLocal } from "./store.js";
import { getLang } from "./i18n.js";
import { el, escHtml } from "./ui.js";
import { apiUrl } from "./api.js";

// id of the "tour seen" marker. The hosted form records it on the account (via the per-user read mechanism of /api/notices);
// the local zero-dependency form has no such endpoint and falls back to localStorage.
export const TOUR_NOTICE = "tour-v1";
const HOMEPAGE_DEMO = "https://socioverse.fudan-disc.com/#demo";

const ZH = getLangText("zh"), EN = getLangText("en");
function getLangText(l){
  const zh = l === "zh";
  return {
    skip: zh ? "跳过导览" : "Skip",
    next: zh ? "下一步" : "Next",
    prev: zh ? "上一步" : "Back",
    done: zh ? "开始使用" : "Get started",
    stepN: zh ? "第 %1 / %2 步" : "Step %1 / %2",
    steps: [
      { t: zh ? "👋 欢迎来到研究驾驶舱" : "👋 Welcome to the research workbench",
        b: zh ? "用一句话描述研究问题，agent 会替你立项、建模、跑推演、写报告。这趟导览带你认一遍界面，大约一分钟。"
              : "Describe a research question in one sentence and the agent sets it up, builds it, runs it and writes it up. This tour walks the interface in about a minute." },
      { t: zh ? "什么是 agent？预测从哪来？" : "What is an agent? Where do predictions come from?",
        b: zh ? "一个 agent = 模拟世界里的一个「个体」——消费者信心案例里是一位受访家庭，汽车案例里是一位购车者。系统固定一批有身份的 agent，让世界逐步演化：每一步每个 agent 依据自己的处境做决策。你看到的预测和指标曲线，就是全体 agent 逐步行为的聚合。本案例还能逐月和官方后来公布的真实指数对答案。"
              : "An agent is one individual in the simulated world — a surveyed household in the consumer-confidence case, a car buyer in the auto-market case. A fixed, persistent population of agents lives through a step-by-step evolving world; every metric or forecast you see is the aggregation of their per-step decisions. This case also scores itself month by month against the index published afterwards." },
      { t: zh ? "左侧导航：七个页面" : "The left rail: seven pages",
        sel: "#nav",
        b: zh ? "总览=研究全貌与关键结果;环境建构=世界如何演化(事件/信息);目标人群=agent 是谁;数据集=本研究全部数据;分析实验=推演曲线、版本与反事实分支对比;论文撰写与文献分析=研究成果。徽标表示各阶段状态(✓完成/⏸待确认/!需重跑)。"
              : "Overview = the study at a glance; Environment = how the world evolves; Population = who the agents are; Dataset = all data assets; Experiments = trajectories, versions and counterfactual branches; Paper & Literature = research outputs. Badges show stage status (✓ done / ⏸ awaiting you / ! stale)." },
      { t: zh ? "研究管线:六个阶段的输入与输出" : "The pipeline: six stages, inputs → outputs",
        sel: ".pipe", tab: "overview",
        b: zh ? "立项:你的问题→研究设定(study.yaml);建模:设定→模拟内核;环境:检索真实事实→逐步事件与广播;人群:真实人口分布→有身份的 agent 名册;推演:以上全部→逐步面板数据;报告:数据→分析报告与图表。每个阶段完成后都会停下来等你确认,再进入下一阶段。"
              : "Setup: your question → the study spec; Model: spec → simulation kernel; Environment: retrieved real-world facts → per-step events; Population: real demographics → a roster of persistent agents; Simulate: all of the above → step-by-step panel data; Report: data → analysis & figures. Each stage pauses for your confirmation before the next." },
      { t: zh ? "在 Claude Code 里驱动研究" : "Drive it from Claude Code",
        need: "local",
        b: zh ? "本地形态没有对话栏:在仓库根目录打开 Claude Code,输入 /sv-init 加一句研究问题即可开始,改动已有研究用 /sv-iterate。每个阶段写出的产物都会实时出现在这里;Claude Code 停下来等你确认时,浏览器标签页标题会提醒你。"
              : "Locally there is no chat dock: open Claude Code at the repo root and run /sv-init with your research question (/sv-iterate changes an existing study). Every artifact a stage writes shows up here live, and the tab title flags when Claude Code is waiting for you." },
      { t: zh ? "右侧对话:你的控制台" : "The chat dock: your control surface",
        sel: "#chatDock", need: "dock",
        b: zh ? "用自然语言发起研究、修改任何阶段的产物。立项前 agent 会先问你几个问题对齐意图(步长含义、人群规模、关注指标、数据来源)。需要你拍板时会弹出琥珀色确认卡,页面顶部和浏览器标签页都会提醒你。"
              : "Drive everything in natural language — start studies, revise any stage. Before planning, the agent asks a few questions to align intent (step meaning, scale, metrics, sources). When a decision is yours, an amber confirmation card appears — pinned banner and tab title will nudge you." },
      { t: zh ? "信息详细度,随时可调" : "Detail level — adjustable anytime",
        sel: "#vseg", need: "chat",
        b: (zh ? "当前是「%V」档。简=只看最终结论与提问,中间过程一概不显示;标=过程叙述加每步操作摘要;详=再把每次工具调用的完整参数折叠在旁边,点开即看。在这里随时切换,切换后历史消息会按新档重新展示。"
               : "You're on “%V”. Simple = just the closing answer and any questions, no intermediate steps; Std = narration plus a one-line summary per step; Dev = adds each tool call's full parameters, folded open on click. Switch here anytime — history re-renders at the new level.") },
      { t: zh ? "指标卡与自选展示集" : "Metric tiles & your displayed set",
        sel: ".vgrid.g4", fallbackSel: ".mrow", tab: "overview",
        b: zh ? "总览的指标卡可以直接点击——跳到分析实验并聚焦该指标的曲线(横轴=推演步,悬停可读逐步数值与干预标记)。在「模型设计」卡里点任意指标行,可自选要展示哪些指标(有色圆点=当前展示集)。"
              : "Metric tiles are clickable — they open that metric's curve in Experiments (x-axis = simulation step; hover for per-step values & intervention markers). In the Model-design card, click any metric row to customize which metrics are displayed (colored dots = the displayed set)." },
      { t: zh ? "🎉 就绪!" : "🎉 You're set!",
        b: zh ? "每个页面顶部都有一条说明,讲这一页的输入与输出。想看完整走一遍的示例,SocioVerse2 主页有介绍视频。随时在左下角 ？ 重看本导览。"
              : "Every page carries a one-line intro of its inputs & outputs. For a full worked example, watch the intro video on the SocioVerse2 homepage. Reopen this tour anytime via the ？ button, bottom-left.",
        video: true },
    ],
    videoLink: zh ? "▶ 观看介绍视频" : "▶ Watch the intro video",
  };
}

let CUR = 0, OV = null;
const END_HOOKS = [];
// What to do once the tour wraps up (currently: light up the "New study" entry). It lives here rather than polling in app.js
// because "skip" and "finish" are two different exit paths, and only endTour sees both.
export function onTourEnd(fn){ END_HOOKS.push(fn); }

function txt(){ return getLang() === "zh" ? ZH : EN; }

// Stops tied to one deployment form: the chat dock is hidden on the local server, the
// transcript-detail switch exists only once the chat plane is detected, and the local server
// gets a stop about driving the workflow from Claude Code instead.
function stepOn(st){
  if (st.need === "local") return isLocal();
  if (st.need === "dock") return !isLocal();
  if (st.need === "chat") return !!S.chatEnabled;
  return true;
}
function steps(){ return txt().steps.filter(stepOn); }

export function tourDone(){
  try { return localStorage.getItem("sv2_tour_done") === "1"; } catch(e){ return false; }
}

export function startTour(opts = {}){
  if (OV) return;
  CUR = 0;
  OV = document.createElement("div");
  OV.id = "tourOv";
  document.body.appendChild(OV);
  renderStep(opts);
}

// Only "skip" and finishing the last stop reach here — a refresh / leaving midway does not count as seen, so it pops up again next time.
function endTour(){
  try { localStorage.setItem("sv2_tour_done", "1"); } catch(e){}
  // Recorded on the account: switching browser or device does not re-show it; another account in the same browser still gets it.
  // The local form has no such endpoint (the localStorage above already covers it), so no request is sent.
  if (!isLocal()) fetch(apiUrl("api/notices/ack"), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: TOUR_NOTICE }),
  }).catch(() => {});
  if (OV){ OV.remove(); OV = null; }
  END_HOOKS.forEach(fn => { try { fn(); } catch(e){} });
}

function renderStep(opts){
  const st = steps()[CUR];
  // a stop that needs a specific tab: switch to it (instant)
  if (st.tab && window.__svSwitchTab) window.__svSwitchTab(st.tab, { instant: true });
  let target = st.sel ? document.querySelector(st.sel) : null;
  if (!target && st.fallbackSel) target = document.querySelector(st.fallbackSel);
  // the target may be outside the viewport (taking the rect after scrolling a long page frames the wrong spot) — scroll it to the center first, then draw
  if (target){
    OV.innerHTML = "";                              // clear the old highlight while scrolling to avoid ghosting
    try { target.scrollIntoView({ block: "center", behavior: "instant" }); } catch(e){ target.scrollIntoView(); }
    requestAnimationFrame(() => requestAnimationFrame(() => paintStep(st, target)));
    return;
  }
  paintStep(st, null);
}

function paintStep(st, target){
  const L = txt();
  const all = steps();
  const r = target ? target.getBoundingClientRect() : null;

  const hole = r ? `<div class="tour-hole" style="left:${r.left - 8}px;top:${r.top - 8}px;width:${r.width + 16}px;height:${r.height + 16}px"></div>`
                 : `<div class="tour-dim"></div>`;
  const body = (st.b || "").replace("%V", ({ simple: getLang() === "zh" ? "简洁" : "Simple",
    standard: getLang() === "zh" ? "标准" : "Standard", dev: "Dev" })[getVerbosity()] || getVerbosity());
  const video = st.video ? `<a class="tour-video" href="${HOMEPAGE_DEMO}" target="_blank" rel="noopener">${escHtml(L.videoLink)}</a>` : "";
  const last = CUR === all.length - 1;

  // card placement: with a target → below or above it; without → centered
  let cardPos = "left:50%;top:50%;transform:translate(-50%,-50%)";
  if (r){
    const below = r.bottom + 20 + 240 < innerHeight;
    const top = below ? r.bottom + 16 : Math.max(16, r.top - 16 - 250);
    const left = Math.min(Math.max(16, r.left + r.width / 2 - 190), innerWidth - 396);
    cardPos = `left:${left}px;top:${top}px`;
  }
  OV.innerHTML = `${hole}
    <div class="tour-card" style="${cardPos}">
      <div class="tour-n mono">${escHtml(L.stepN.replace("%1", String(CUR + 1)).replace("%2", String(all.length)))}</div>
      <h3>${escHtml(st.t)}</h3>
      <p>${escHtml(body)}</p>
      ${video}
      <div class="tour-row">
        <span class="tour-skip">${escHtml(L.skip)}</span>
        <span style="flex:1"></span>
        ${CUR > 0 ? `<button class="btn sm tour-prev">${escHtml(L.prev)}</button>` : ""}
        <button class="btn sm primary tour-next">${escHtml(last ? L.done : L.next)}</button>
      </div>
    </div>`;
  OV.querySelector(".tour-skip").onclick = endTour;
  const prev = OV.querySelector(".tour-prev");
  if (prev) prev.onclick = () => { CUR--; renderStep({}); };
  OV.querySelector(".tour-next").onclick = () => {
    if (last){ endTour(); return; }
    CUR++;
    renderStep({});
  };
}
