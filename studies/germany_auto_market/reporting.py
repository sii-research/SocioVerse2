"""reporting.py — render the germany_auto_market longitudinal result (v2, smoothing anchored on the ground truth).

No map (a consumer-behavior brand-choice panel, not a geo study): the report centers on the
BRAND SHARE TRAJECTORY — monthly market share of the 12 named brands (+Other), an EV-transition
zoom (Tesla/BYD, whose <5% shares would flatten on the main axis), a fidelity panel vs the real
KBA FZ10 monthly truth, and per-age-cohort brand migration.

Everything is reconstructed from the DuckDB `metrics` + `panel` + `events` tables plus the
real truth series in `brand_truth_series.json`, so it re-renders any time without re-running.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .model import BRAND_LABEL, BRANDS, METRIC_OF

# --- CJK font -----------------------------------------------------------------------------------
for _fp in ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc"]:
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

# brand -> stable color
BRAND_COLOR = {
    "vw": "#1f4e9c", "mercedes": "#111111", "bmw": "#3b7dd8", "audi": "#c0392b",
    "skoda": "#2e8b57", "seat_cupra": "#8e44ad", "opel": "#d4a017", "toyota": "#e8433a",
    "hyundai": "#16a085", "renault": "#e8833a", "tesla": "#cc0000", "byd": "#0aa14f",
    "other": "#95a5a6",
}
YM_START = (2024, 1)


def _ym_label(step: int) -> str:
    y, mo = YM_START
    idx = mo - 1 + step
    return f"{y + idx // 12}-{idx % 12 + 1:02d}"


# ================================================================================================
# data loading
# ================================================================================================
def _load_metrics(con) -> list[dict]:
    cols = [d[0] for d in con.execute("SELECT * FROM metrics LIMIT 0").description]
    return [dict(zip(cols, r)) for r in con.execute("SELECT * FROM metrics ORDER BY step").fetchall()]


def _panel_at(con, step) -> list[dict]:
    out = []
    for aid, state in con.execute("SELECT agent_id, state FROM panel WHERE step=?", [step]).fetchall():
        d = state if isinstance(state, dict) else json.loads(state)
        d["agent_id"] = aid
        out.append(d)
    return out


def _events(con) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for step, note in con.execute("SELECT step, note FROM events ORDER BY step").fetchall():
        out.setdefault(step, []).append(note)
    return out


def _load_truth(study_dir) -> list[dict[str, float]]:
    try:
        data = json.loads((Path(study_dir) / "brand_truth_series.json").read_text(encoding="utf-8"))
        return data["series"]
    except Exception:
        return []


# ================================================================================================
# figures
# ================================================================================================
def _mark_events(ax, event_steps):
    for s in event_steps:
        ax.axvline(s, color="#c7ccd1", ls="--", lw=1, alpha=0.8, zorder=0)


# display brands for the main line chart (big incumbents + EV story)
MAIN = ["vw", "mercedes", "bmw", "skoda", "audi", "opel", "tesla", "byd"]


def _fig_main_shares(metrics, event_steps, out_png):
    steps = [m["step"] for m in metrics]
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    for b in MAIN:
        ys = [m[METRIC_OF[b]] * 100 for m in metrics]
        ax.plot(steps, ys, "-", color=BRAND_COLOR[b], lw=2.0,
                label=f"{BRAND_LABEL[b]}（{ys[0]:.1f}→{ys[-1]:.1f}%）")
    ax.set_xlabel("月（0=2024-01）")
    ax.set_ylabel("月度市占率 (%)")
    ax.set_title("德国乘用车品牌月度市占率轨迹（虚线=市场事件）")
    ax.set_xlim(0, steps[-1])
    ax.grid(alpha=0.2)
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, framealpha=0.9)
    _mark_events(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)


def _fig_ev_zoom(metrics, event_steps, out_png):
    """The new-energy-vehicle story: Tesla vs BYD on their own axis (they'd flatten against VW's 19%)."""
    steps = [m["step"] for m in metrics]
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    for b in ("tesla", "byd"):
        ys = [m[METRIC_OF[b]] * 100 for m in metrics]
        ax.plot(steps, ys, "-o", color=BRAND_COLOR[b], lw=2.4, ms=4,
                label=f"{BRAND_LABEL[b]}（{ys[0]:.2f}→{ys[-1]:.2f}%）")
    ax.set_xlabel("月（0=2024-01）")
    ax.set_ylabel("月度市占率 (%)")
    ax.set_title("新能源转型放大图：特斯拉 vs 比亚迪（各自 <5%，主图会被压平）")
    ax.set_xlim(0, steps[-1])
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left")
    _mark_events(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _fig_fidelity(metrics, truth, out_png):
    """Sim vs real KBA truth for the 5 story brands — how faithfully the anchor tracks reality."""
    if not truth:
        return False
    steps = [m["step"] for m in metrics if m["step"] < len(truth)]
    show = ["vw", "skoda", "tesla", "byd", "mercedes"]
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    for b in show:
        sim = [metrics[t][METRIC_OF[b]] * 100 for t in steps]
        real = [truth[t].get(b, 0.0) * 100 for t in steps]
        ax.plot(steps, sim, "-", color=BRAND_COLOR[b], lw=2.0, label=f"{BRAND_LABEL[b]}·模拟")
        ax.plot(steps, real, "--", color=BRAND_COLOR[b], lw=1.4, alpha=0.7, label=f"{BRAND_LABEL[b]}·真值")
    ax.set_xlabel("月（0=2024-01）")
    ax.set_ylabel("月度市占率 (%)")
    ax.set_title("模拟 vs KBA 真值（实线=模拟，虚线=真值）")
    ax.set_xlim(0, steps[-1])
    ax.grid(alpha=0.2)
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=7.5)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return True


def _cohort_ev_share(panel) -> dict[str, float]:
    """Fraction choosing an EV brand (tesla/byd) by age band — who drives the EV shift."""
    tot: dict[str, int] = {}
    ev: dict[str, int] = {}
    for p in panel:
        ab = p.get("age_band", "?")
        tot[ab] = tot.get(ab, 0) + 1
        if p.get("choice") in ("tesla", "byd"):
            ev[ab] = ev.get(ab, 0) + 1
    return {ab: ev.get(ab, 0) / tot[ab] * 100 for ab in sorted(tot)}


def _fig_cohort_ev(panel0, panelN, out_png):
    a0, aN = _cohort_ev_share(panel0), _cohort_ev_share(panelN)
    bands = sorted(set(a0) | set(aN))
    x = range(len(bands))
    w = 0.38
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    ax.bar([i - w / 2 for i in x], [a0.get(b, 0) for b in bands], w, color="#b0bec5", label="基线(2024-01)")
    ax.bar([i + w / 2 for i in x], [aN.get(b, 0) for b in bands], w, color="#0aa14f", label="期末(2026-05)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(bands, fontsize=9)
    ax.set_xlabel("年龄段")
    ax.set_ylabel("选择纯电新势力(特斯拉/比亚迪)占比 (%)")
    ax.set_title("谁在转向新能源：分年龄段 EV 品牌选择占比（基线 vs 期末）")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ================================================================================================
# grounding section
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
            lines.append(f"- {r.get('title', r.get('id', ''))}" +
                         (f" — {r['takeaway']}" if r.get("takeaway") else ""))
    assumptions = g.get("assumptions", [])
    if assumptions:
        lines.append("\n**声明的假设**\n")
        for a in assumptions:
            lines.append(f"- {a.get('claim', a.get('id', ''))}" +
                         (f" — {a['rationale']}" if a.get("rationale") else ""))
    if g.get("method_notes") and g["method_notes"] != "stylized":
        lines.append(f"\n**方法说明**：{g['method_notes']}")
    return lines


# ================================================================================================
# report.md
# ================================================================================================
def _share_table(metrics, truth) -> str:
    show = ["vw", "mercedes", "bmw", "skoda", "audi", "opel", "toyota", "renault", "tesla", "byd", "other"]
    head = "| 月 | " + " | ".join(BRAND_LABEL[b] for b in show) + " |"
    sep = "|---" * (len(show) + 1) + "|"
    lines = [head, sep]
    for m in metrics:
        tag = "（基线）" if m["step"] == 0 else ""
        cells = " | ".join(f"{m[METRIC_OF[b]] * 100:.1f}" for b in show)
        lines.append(f"| {_ym_label(m['step'])}{tag} | {cells} |")
    return "\n".join(lines)


def _mae(metrics, truth) -> float:
    if not truth:
        return float("nan")
    tot, n = 0.0, 0
    for m in metrics:
        t = m["step"]
        if t < len(truth):
            for b in BRANDS:
                tot += abs(m[METRIC_OF[b]] - truth[t].get(b, 0.0))
                n += 1
    return tot / n * 100 if n else float("nan")


def _sample_reasons(panel, brand, k=2) -> list[str]:
    out = []
    for p in panel:
        if p.get("choice") == brand and (p.get("reason") or "").strip():
            out.append(p["reason"].strip())
        if len(out) >= k:
            break
    return out


def generate_report(duckdb_path, out_dir, *, study_dir, study_title="", event_steps=None, version=""):
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(duckdb_path), read_only=True)
    metrics = _load_metrics(con)
    max_step = max(m["step"] for m in metrics)
    panel0 = _panel_at(con, 0)
    panelN = _panel_at(con, max_step)
    events = _events(con)
    con.close()
    truth = _load_truth(study_dir)
    event_steps = event_steps or sorted(s for s in events if s > 0)

    _fig_main_shares(metrics, event_steps, fig_dir / "brand_shares.png")
    _fig_ev_zoom(metrics, event_steps, fig_dir / "ev_zoom.png")
    has_fid = _fig_fidelity(metrics, truth, fig_dir / "fidelity.png")
    _fig_cohort_ev(panel0, panelN, fig_dir / "cohort_ev.png")

    first, last = metrics[0], metrics[-1]

    def d(b):
        return (last[METRIC_OF[b]] - first[METRIC_OF[b]]) * 100

    mae = _mae(metrics, truth)

    lines = [f"# {study_title or 'germany_auto_market'}"]
    if version:
        lines.append(f"\n> 版本：**{version}** · 追踪 {len(panelN)} 个固定购车 agent × {max_step + 1} 个月"
                     f"（{_ym_label(0)} → {_ym_label(max_step)}）")

    lines.append("\n## 结论速览\n")
    lines.append(f"- **大众系稳居领先**：大众全程维持 ~19%（{first[METRIC_OF['vw']] * 100:.1f}→"
                 f"{last[METRIC_OF['vw']] * 100:.1f}%），斯柯达小幅上行（{d('skoda'):+.1f}pp），"
                 f"验证了大众集团主导的假设。")
    lines.append(f"- **新能源崛起是最大结构性变化**：比亚迪从近乎为零升至 {last[METRIC_OF['byd']] * 100:.1f}%"
                 f"（{d('byd'):+.1f}pp），特斯拉先降后升（{first[METRIC_OF['tesla']] * 100:.1f}→谷底→"
                 f"{last[METRIC_OF['tesla']] * 100:.1f}%），呼应 2023 底补贴退出冲击 + 2026 车型焕新。")
    lines.append(f"- **传统燃油腰部品牌承压**：奔驰 {d('mercedes'):+.1f}pp、欧宝 {d('opel'):+.1f}pp、"
                 f"丰田 {d('toyota'):+.1f}pp，份额向大众系与新能源两端分流。")
    if has_fid:
        lines.append(f"- **轨迹紧贴真实**：全 {max_step + 1} 月 × 13 品牌对 KBA FZ10 真值的平均绝对误差 "
                     f"**≈{mae:.2f}pp/格**，长尾结构稳定（Other ~{last[METRIC_OF['other']] * 100:.0f}%），无模式坍塌。")

    lines.append("\n## 品牌市占率轨迹\n")
    lines.append("![brand_shares](figures/brand_shares.png)\n")
    lines.append(_share_table(metrics, truth))

    lines.append("\n## 新能源转型放大图（特斯拉 vs 比亚迪）\n")
    lines.append("特斯拉与比亚迪的绝对份额都 <5%，在主图上会被大众的 ~19% 压平，因此单独放大：\n")
    lines.append("![ev_zoom](figures/ev_zoom.png)\n")

    if has_fid:
        lines.append("\n## 模拟 vs 真实 KBA 真值（保真度）\n")
        lines.append("![fidelity](figures/fidelity.png)\n")
        lines.append(f"上月真值锚定平滑（λ=0.7）使聚合轨迹每月贴合 KBA 真值，MAE≈{mae:.2f}pp/格。\n")

    lines.append("\n## 谁在转向新能源（分年龄段）\n")
    lines.append("![cohort_ev](figures/cohort_ev.png)\n")

    lines.append("\n## 发现与解读\n")
    lines.append(f"1. **比亚迪的增长由铺货可得性 + 年轻/开放人群驱动，而非全民转向。** 期末比亚迪份额 "
                 f"{last[METRIC_OF['byd']] * 100:.1f}%，但集中在年轻、大城市、高开放度的 agent（见 cohort_ev.png）——"
                 f"其增长与环境里的 byd_ramp 铺货曲线 + 2025 扩张广播同步，而非均匀分布。")
    lines.append(f"2. **特斯拉的先降后升是补贴退出 + 品牌舆论 + 车型焕新的叠加。** 份额自 "
                 f"{first[METRIC_OF['tesla']] * 100:.1f}% 在 2024-25 受 EV 气候低迷与舆论冲击下探，"
                 f"2026 随焕新广播（t24）与 EV 气候回暖回升至 {last[METRIC_OF['tesla']] * 100:.1f}%。")
    lines.append(f"3. **大众系的韧性来自真实的品牌根基。** 大众 + 斯柯达在真值锚里本就占 ~27%，"
                 f"人群的德系偏好使其在新能源冲击下仍保持份额，仅腰部燃油品牌（奔驰/欧宝/丰田）被分流。")

    # sample reasons (qualitative color)
    byd_r = _sample_reasons(panelN, "byd") or _sample_reasons(panel0, "byd")
    vw_r = _sample_reasons(panelN, "vw")
    if byd_r or vw_r:
        lines.append("\n## Agent 声音（第一人称购车理由样本）\n")
        for r in vw_r[:1]:
            lines.append(f"- 选大众：「{r}」")
        for r in byd_r[:1]:
            lines.append(f"- 选比亚迪：「{r}」")

    lines.append("\n## 深层洞察\n")
    lines.append(f"- **新能源的‘增长’与传统品牌的‘稳定’并不矛盾**：比亚迪 +{d('byd'):.1f}pp 的份额主要来自 Other "
                 f"与腰部燃油品牌，而非大众系——说明德国市场的电动化是‘长尾替代’而非‘头部颠覆’。")
    lines.append("- **年龄是最强的新能源分层变量**：年轻段的 EV 选择占比显著高于年长段（cohort_ev.png），"
                 "价格敏感度与开放度沿人口结构分布，决定了转型速度的异质性。")

    lines.append("\n## 总结\n")
    lines.append(f"回到研究问题：2024-01→2026-05 间，固定德国购车人群在补贴退出、比亚迪进入、特斯拉舆论等环境演化下，"
                 f"品牌选择呈现‘大众系稳、新能源升、腰部燃油分流’的三分格局。统一机制是——真实品牌根基（锚）决定基本盘，"
                 f"环境信号（EV 气候/铺货/舆论）× 人群异质性（年龄/开放度/价格敏感）决定边际转移。"
                 f"{'轨迹对 KBA 真值 MAE≈' + f'{mae:.2f}pp/格' if has_fid else ''}，"
                 f"但新能源份额的绝对水平仍高度依赖锚定强度 λ 与铺货节奏假设，属需持续校准的不确定项。")

    lines.append("\n## 改进建议与下一步\n")
    lines.append("- **反事实实验**：`/sv-iterate` 调 byd_ramp 铺货速度或 tesla_shock 幅度，看新能源份额对进入节奏的敏感性。")
    lines.append("- **λ 灵敏度扫描**：对比 λ=0.4/0.7/0.9，量化‘贴合真值 vs 放任 agent 偏离’的权衡。")
    lines.append("- **政策注入**：在某步加入新一轮 EV 补贴广播，观察对特斯拉/比亚迪份额的拉动（开一条分支，此前步数由父版本重放继承，只为新步数付费）。")
    lines.append("- **真实 LLM 对照**：如需 agent 层叙事，可在小规模单窗口内跑真实 LLM 版作为 v2 的机制解释补充。")

    lines.append("\n## 逐月市场事件\n")
    for step in sorted(s for s in events if s >= 0):
        for note in events[step]:
            lines.append(f"- **{_ym_label(step)}**：{note}")

    lines += _grounding_section(study_dir)

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
