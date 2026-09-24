"""reporting.py — render the hisim_roe hybrid social-movement longitudinal result.

No map (this is a Twitter-like opinion-dynamics panel, not a geo study): the report centers on
the OPINION TRAJECTORY after the trigger news (Roe v. Wade overturn) — the population `bias`
(mean attitude − neutral) and `diversity` (attitude variance) paths, split by the two hybrid
cohorts (LLM-driven `core` vs ABM-driven `ordinary` users), plus the platform-activity counts
(`n_active` / `n_post`) that show the mobilization spike when the news fires.

Everything is reconstructed from the DuckDB `metrics` + `panel` + `events` tables via SQL/JSON,
so it can be re-rendered any time without re-running the LLM. Mirrors the opinion_diffusion
reporting shape (figures + analytical findings / deeper-insights / recommendations sections + a grounding section).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import mean, pvariance

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

# --- CJK font so Chinese labels render (not tofu) ------------------------------------------------
for _fp in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/STHeiti Medium.ttc"]:
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

C_BIAS, C_DIV = "#3b7dd8", "#b5482e"
C_CORE, C_ORD = "#4a3f8f", "#e8833a"
C_ACT, C_POST = "#2e8b57", "#c78a2e"


# ================================================================================================
# data loading
# ================================================================================================
def _load_metrics(con) -> list[dict]:
    cols = [d[0] for d in con.execute("SELECT * FROM metrics LIMIT 0").description]
    rows = con.execute("SELECT * FROM metrics ORDER BY step").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def _panel_at(con, step) -> dict[str, dict]:
    rows = con.execute("SELECT agent_id, state FROM panel WHERE step=? ORDER BY agent_id",
                       [step]).fetchall()
    out = {}
    for aid, state in rows:
        d = state if isinstance(state, dict) else json.loads(state)
        out[aid] = d
    return out


def _events(con) -> dict[int, list[str]]:
    rows = con.execute("SELECT step, note FROM events ORDER BY step").fetchall()
    out: dict[int, list[str]] = {}
    for step, note in rows:
        out.setdefault(step, []).append(note)
    return out


def _is_core(aid: str) -> bool:
    return aid.startswith("core-")


def _cohort_paths(con, max_step) -> tuple[dict, dict]:
    """Follow each hybrid cohort's mean opinion (core LLM users vs ordinary ABM users)."""
    base = _panel_at(con, 0)
    core_ids = {a for a in base if _is_core(a)}
    ord_ids = {a for a in base if not _is_core(a)}
    core_path, ord_path = {}, {}
    for t in range(max_step + 1):
        p = _panel_at(con, t)
        core_path[t] = round(mean([float(p[a]["opinion"]) for a in core_ids]), 4) if core_ids else None
        ord_path[t] = round(mean([float(p[a]["opinion"]) for a in ord_ids]), 4) if ord_ids else None
    return core_path, ord_path


# ================================================================================================
# figures
# ================================================================================================
def _mark_events(ax, event_steps):
    for s in event_steps:
        ax.axvline(s, color="#c7ccd1", ls="--", lw=1, alpha=0.9, zorder=0)


def _fig_opinion(metrics, event_steps, out_png):
    steps = [m["step"] for m in metrics]
    bias = [m["bias"] for m in metrics]
    div = [m["diversity"] for m in metrics]
    fig, ax1 = plt.subplots(figsize=(8.6, 4.6))
    ax1.plot(steps, bias, "-o", color=C_BIAS, lw=2.4, ms=5, label="群体偏移 bias (平均态度−中性)")
    ax1.axhline(0, color="#999", ls=":", lw=1, alpha=0.7)
    ax1.set_xlabel("步 (0=初始，虚线=trigger news 触发步)")
    ax1.set_ylabel("bias (−1…+1，正=偏支持)")
    ax1.set_ylim(-1, 1)
    ax2 = ax1.twinx()
    ax2.plot(steps, div, "-s", color=C_DIV, lw=2.4, ms=5, label="态度多样性 diversity (方差)")
    ax2.set_ylabel("diversity 方差 (越低=越收敛)", color=C_DIV)
    ax2.tick_params(axis="y", labelcolor=C_DIV)
    ax2.set_ylim(0, max(div) * 1.25 if any(div) else 1)
    ax1.set_title("舆论轨迹：群体偏移 bias 与态度多样性 diversity")
    lines = ax1.get_lines()[:1] + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="best", framealpha=0.9, fontsize=9)
    ax1.grid(alpha=0.2)
    _mark_events(ax1, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _fig_cohorts(core_path, ord_path, event_steps, out_png):
    steps = sorted(core_path)
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    ax.plot(steps, [core_path[t] for t in steps], "-s", color=C_CORE, lw=2.4, ms=5,
            label="核心用户 core (LLM 驱动)")
    ax.plot(steps, [ord_path[t] for t in steps], "-o", color=C_ORD, lw=2.4, ms=5,
            label="普通用户 ordinary (ABM 有界信心)")
    ax.axhline(0, color="#999", ls=":", lw=1, alpha=0.7)
    ax.set_xlabel("步 (虚线=trigger news 触发步)")
    ax.set_ylabel("组内平均态度 (−1…+1)")
    ax.set_ylim(-1, 1)
    ax.set_title("两类用户的态度轨迹：LLM 核心 vs ABM 普通")
    ax.legend(loc="best", framealpha=0.9)
    ax.grid(alpha=0.25)
    _mark_events(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _fig_activity(metrics, event_steps, out_png):
    steps = [m["step"] for m in metrics]
    n_active = [m["n_active"] for m in metrics]
    n_post = [m["n_post"] for m in metrics]
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    w = 0.38
    ax.bar([s - w / 2 for s in steps], n_active, width=w, color=C_ACT, label="活跃核心用户 n_active")
    ax.bar([s + w / 2 for s in steps], n_post, width=w, color=C_POST, label="原创/转推数 n_post")
    ax.set_xlabel("步 (虚线=trigger news 触发步)")
    ax.set_ylabel("计数")
    ax.set_title("平台活跃度：news 触发前后的动员")
    ax.set_xticks(steps)
    ax.legend(loc="best", framealpha=0.9)
    ax.grid(alpha=0.2, axis="y")
    _mark_events(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ================================================================================================
# grounding section  (the report's data-basis-and-sources section)
# ================================================================================================
_BASIS_CN = {"sourced": "实证", "proxy": "代理", "assumed": "假设"}


def _grounding_section(study_dir) -> list[str]:
    try:
        from skills import sv_grounding
        g = sv_grounding.load(study_dir)
    except Exception:
        g = None
    if not g:
        return []
    lines = ["\n## 数据基础与参考来源\n"]
    facts = g.get("facts", [])
    if facts:
        lines.append("| 事实 | 值 | 依据 | 来源 |")
        lines.append("|---|---|---|---|")
        for f in facts:
            val, unit = f.get("value", ""), f.get("unit", "")
            val_s = f"{val} {unit}".strip() if val != "" else "—"
            basis = _BASIS_CN.get(f.get("basis", ""), f.get("basis", ""))
            src = f.get("source", {}) or {}
            src_s = src.get("title", "") or "—"
            if src.get("url"):
                src_s = f"{src_s} ({src['url']})"
            lines.append(f"| {f.get('claim', f.get('id', ''))} | {val_s} | {basis} | {src_s} |")
    refs = g.get("implementation_refs") or []
    if refs:
        lines.append("\n**建模参考**\n")
        for r in refs:
            t = r.get("title", r.get("id", ""))
            tk = r.get("takeaway", "")
            lines.append(f"- {t}" + (f" — {tk}" if tk else ""))
    assumptions = g.get("assumptions", [])
    if assumptions:
        lines.append("\n**声明的假设**\n")
        for a in assumptions:
            claim, why = a.get("claim", a.get("id", "")), a.get("rationale", "")
            lines.append(f"- {claim}" + (f" — {why}" if why else ""))
    if g.get("method_notes") == "stylized" and not facts:
        lines.append("\n风格化模型，无真实世界锚点。")
    return lines


# ================================================================================================
# report.md
# ================================================================================================
def _metric_table(metrics, events) -> str:
    lines = ["| 步 | bias | diversity | mean_core | mean_ordinary | n_active | n_post | 事件 |",
             "|---|---|---|---|---|---|---|---|"]
    for m in metrics:
        tag = "（初始）" if m["step"] == 0 else ""
        ev = "；".join(events.get(m["step"], [])) or ""
        lines.append(f"| {m['step']}{tag} | {m['bias']:+.4f} | {m['diversity']:.5f} | "
                     f"{m['mean_core']:+.4f} | {m['mean_ordinary']:+.4f} | "
                     f"{m['n_active']} | {m['n_post']} | {ev} |")
    return "\n".join(lines)


def _count_agents(duckdb_path) -> tuple[int, int, int]:
    con = duckdb.connect(str(duckdb_path), read_only=True)
    ids = [r[0] for r in con.execute("SELECT DISTINCT agent_id FROM panel").fetchall()]
    con.close()
    n_core = sum(1 for a in ids if _is_core(a))
    return len(ids), n_core, len(ids) - n_core


def generate_report(duckdb_path, out_dir, *, study_dir, study_title="",
                    event_steps=None, run_mode="", version=""):
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(duckdb_path), read_only=True)
    metrics = _load_metrics(con)
    max_step = max(m["step"] for m in metrics)
    events = _events(con)
    core_path, ord_path = _cohort_paths(con, max_step)
    con.close()

    event_steps = event_steps or sorted(s for s in events if s > 0)
    first, last = metrics[0], metrics[-1]
    n_all, n_core, n_ord = _count_agents(duckdb_path)

    _fig_opinion(metrics, event_steps, fig_dir / "opinion_trajectory.png")
    _fig_cohorts(core_path, ord_path, event_steps, fig_dir / "cohort_paths.png")
    _fig_activity(metrics, event_steps, fig_dir / "activity.png")

    # pre/post-news deltas for the findings
    nstep = event_steps[0] if event_steps else 2
    pre = next((m for m in metrics if m["step"] == nstep - 1), first)
    at = next((m for m in metrics if m["step"] == nstep), last)
    by_step = {m["step"]: m for m in metrics}
    d_bias_total = last["bias"] - first["bias"]
    d_bias_atstep = at["bias"] - pre["bias"]
    d_div_total = last["diversity"] - first["diversity"]
    core_gain = (core_path[max_step] - core_path[0]) if core_path[0] is not None else 0
    ord_gain = (ord_path[max_step] - ord_path[0]) if ord_path[0] is not None else 0
    peak_active = max(m["n_active"] for m in metrics)
    peak_active_step = next(m["step"] for m in metrics if m["n_active"] == peak_active)
    # step-by-step |bias| moves so the report names the REAL inflection (data, not assumed = nstep)
    bias_moves = {m["step"]: m["bias"] - by_step[m["step"] - 1]["bias"]
                  for m in metrics if m["step"] - 1 in by_step}
    biggest_step = max(bias_moves, key=lambda s: abs(bias_moves[s])) if bias_moves else nstep
    biggest_move = bias_moves.get(biggest_step, 0.0)
    news_is_inflection = biggest_step == nstep
    # first decision step (t=1) and whether core users were already active before the news fired
    first_dec = by_step.get(1, at)
    pre_news_active = any(by_step[s]["n_active"] > 0 for s in by_step if 0 < s < nstep)

    lines = [f"# {study_title or 'hisim_roe'}"]
    tags = []
    if version:
        tags.append(version)
    if run_mode:
        tags.append(run_mode)
    if tags:
        lines.append(f"\n> 版本/模式：**{' · '.join(tags)}**")

    lines.append("\n## 结论速览\n")
    lines.append(f"- 追踪 **{n_all} 个**固定 agent（**{n_core} 核心 LLM 用户 + {n_ord} 普通 ABM 用户**，"
                 f"Twitter 式平台，面板数据），共 **{max_step} 步**（step 0 为初始，第 {nstep} 步触发新闻"
                 f"「最高法院推翻 Roe v. Wade」）。")
    lines.append(f"- **群体偏移 bias {first['bias']:+.4f}→{last['bias']:+.4f}（{d_bias_total:+.4f}）**："
                 f"触发新闻当步变动 {d_bias_atstep:+.4f}。bias>0 偏支持、<0 偏反对。")
    lines.append(f"- **态度多样性 diversity {first['diversity']:.5f}→{last['diversity']:.5f}"
                 f"（{d_div_total:+.5f}）**：{'下降=群体收敛' if d_div_total < 0 else '上升=群体分化'}。")
    lines.append(f"- **两类用户分道**：核心(LLM) 均值 {core_path[0]:+.4f}→{core_path[max_step]:+.4f}"
                 f"（{core_gain:+.4f}），普通(ABM) 均值 {ord_path[0]:+.4f}→{ord_path[max_step]:+.4f}"
                 f"（{ord_gain:+.4f}）。")
    lines.append(f"- **平台动员**：核心用户活跃数在第 {peak_active_step} 步达峰 {peak_active}/{n_core}。")
    if run_mode:
        lines.append(f"- 决策层：{run_mode}（每核心用户每步一次 LLM 角色扮演→Thought/Action/Stance→"
                     f"att 镜像；普通用户走有界信心规则，无 API）。")

    lines.append("\n## 舆论轨迹（bias 群体偏移 / diversity 态度多样性）\n")
    lines.append("![opinion](figures/opinion_trajectory.png)\n")
    lines.append(_metric_table(metrics, events))

    lines.append("\n## 两类用户的态度轨迹（LLM 核心 vs ABM 普通）\n")
    lines.append("![cohorts](figures/cohort_paths.png)\n")
    lines.append("| 组 | 初始均值 | 期末均值 | 变动 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 核心用户 core (LLM) | {core_path[0]:+.4f} | {core_path[max_step]:+.4f} | {core_gain:+.4f} |")
    lines.append(f"| 普通用户 ordinary (ABM) | {ord_path[0]:+.4f} | {ord_path[max_step]:+.4f} | {ord_gain:+.4f} |")

    lines.append("\n## 平台活跃度（触发新闻前后的动员）\n")
    lines.append("![activity](figures/activity.png)\n")

    # --- analytical sections (required by sv-report) --------------------------------------------
    lines.append("\n## 发现与解读 (Findings)\n")
    lines.append(
        f"1. **核心(LLM)与普通(ABM)用户走的是两套动力学。** 期末核心均值 {core_path[max_step]:+.4f}、"
        f"普通均值 {ord_path[max_step]:+.4f}，两组变动分别为 {core_gain:+.4f} / {ord_gain:+.4f}。"
        f"机制：核心用户的态度每步被「镜像」重写为其所发推文的 att=sign(stance)·|sentiment|（LLM 即时表达，"
        f"可大幅跳变甚至反号）；普通用户则按有界信心规则 new=x+α·(peer−x)（α=0.3）向 |Δ|<0.1 的同温层邻居"
        f"缓慢靠拢——所以核心波动大、普通平滑，二者不必同向。")
    if news_is_inflection:
        lines.append(
            f"2. **触发新闻是活跃度与 bias 的拐点。** 第 {nstep} 步新闻广播生效当步，bias 变动 {d_bias_atstep:+.4f}"
            f"（全程最大单步移动），核心活跃数达峰 {peak_active}/{n_core}。机制：新闻作为 macro-information 注入"
            f"每个核心用户的 prompt，促使沉默者（do_nothing→att=0）转为表态发帖（att≠0），"
            f"既抬高活跃度、又把新的 stance 写进 bias。")
    else:
        lines.append(
            f"2. **核心用户在首个决策步(step 1)就已被激活，最大的 bias 移动发生在 news 之前而非当步。** "
            f"bias 的全程最大单步移动是第 {biggest_step} 步的 {biggest_move:+.4f}"
            f"{'（早于第 %d 步 news）' % nstep if biggest_step < nstep else ''}；"
            f"到第 {nstep} 步 news 广播生效当步，bias 仅变动 {d_bias_atstep:+.4f}，核心活跃数在第 {peak_active_step} 步"
            f"达峰 {peak_active}/{n_core}"
            f"{'（第 1 步已有 %d 人活跃）' % first_dec['n_active'] if pre_news_active else ''}。"
            f"机制：本 demo 的 target（“堕胎权保护”）已在核心用户的 role/prompt 里长期在场，故 LLM 从 step 1 起"
            f"就大量表态、bias 迅速偏移；step 2 的一次性新闻只是把已经高企的活跃度维持在峰值、边际再抬 bias 极小。"
            f"→ 提示：要让 news 成为真正的拐点，应把它当作对“此前无此议题”人群的首次冲击"
            f"（见改进建议：真实 init_att + 先于 news 的中性 prompt）。")
    lines.append(
        f"3. **多样性方向揭示收敛/分化。** diversity {first['diversity']:.5f}→{last['diversity']:.5f}"
        f"（{d_div_total:+.5f}）。机制：普通用户的有界信心同化是收缩算子（拉近同温层），单独会降方差；"
        f"但核心用户的 LLM 表态每步重写态度、可跨号跳变，是方差的注入源。净方向由二者力量对比决定，"
        f"本次为{'收敛占优' if d_div_total < 0 else '分化/表态扰动占优'}。")

    lines.append("\n## 深层洞察 (Deeper insights)\n")
    lines.append(
        "- **混合架构的价值恰在两条曲线的背离**：若只跑纯 ABM，普通用户会平滑收敛到一个共识；混入 LLM 核心后，"
        "核心的即时表态持续向系统注入新态度与话题，使群体 bias 不再是单调收敛的结果，而是"
        "「沉默多数缓慢同化 + 活跃少数跳变引领」的叠加——这正是 HiSim「核心用户驱动、普通用户跟随」命题的可视化。")
    lines.append(
        f"- **高活跃度 ≠ 大幅 bias 移动**：核心活跃数从 step {peak_active_step} 起即满格 {peak_active}/{n_core}，"
        f"但 bias 的净移动很小且随后趋平（step 2→4 几乎横盘）——因为 {n_core} 个核心 att 有正有负相互抵消，"
        f"且普通用户（占 {n_ord}/{n_all}、期末 {ord_path[max_step]:+.4f}）几乎不动、把群体 bias 牢牢拉向其初始水平。"
        f"用「发帖量满格」判断「舆论已翻转」会严重高估转向——真正的锚是沉默多数，不是活跃少数。")
    lines.append(
        "- **真实世界锚点提示量级须谨慎**：grounding 记录 Dobbs 后 Pew 民调为 57% 反对 / 41% 支持（净负），"
        "而本 demo 用 seed=42 的 [-1,1] 均匀初值、非真实 init_att，故 bias 的绝对水平不可直接对标民调；"
        "应把它当作机制演示的相对轨迹，而非校准后的舆论预测。")

    lines.append("\n## 改进建议与下一步 (Recommendations & next steps)\n")
    lines.append(
        "- **接入真实 HiSim ROE 数据**：把 HiSim/data/user_data/roe 的 role_desc / follower_dict / init_att "
        "落到本机后，用 model.make_hisim_bundles_from_data 重建 P（真实核心用户画像 + 关注图 + init_att≈0.9 的"
        "强支持先验），/sv-iterate 出新版对照 —— 检验「真实强支持先验」下轨迹是否复现 Pew 的净态度。")
    lines.append(
        "- **scripted vs LLM parity 对照**：/sv-iterate 复制一版把 decision_args.mode 设为 llm_kind=scripted "
        "（确定性桩，无 API）做 parity 基线，量化 LLM 角色扮演相比纯规则桩是否引入系统性偏移（更强/更弱表态）。"
        "（注：run-mode 切换须新版本，勿覆盖本次真实 LLM 结果。）")
    lines.append(
        "- **放大规模与横跨事件**：把 n_core/n_ord 提到接近 HiSim 的 1000 量级、n_steps 拉到 14，并复现 news[11]"
        "（抗议者被捕）第二波冲击；观察多轮新闻下 bias 是否出现二次拐点。")
    lines.append(
        "- **扫 bc_bound 阈值**：当前 0.1 偏窄。扫 0.1→0.5 观察普通用户从「多簇分裂」到「单一共识」的经典有界信心相变，"
        "并看核心 LLM 注入是否改变相变临界点。")

    lines += _grounding_section(study_dir)

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
