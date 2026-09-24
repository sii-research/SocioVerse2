"""reporting.py — render the campus_dining_choice longitudinal result.

No map (this is a consumer-behavior panel, not a geo study): the report centers on the
CHOICE TRAJECTORY — the monthly share of canteen / delivery / home cooking, the mean-satisfaction and per-capita
monthly food-spend paths against the month-by-month price-increase treatment, and the per-archetype migration (who switched, who stayed).

Everything is reconstructed from the DuckDB `metrics` + `panel` + `events` tables via SQL/JSON,
plus the authored price schedule in `environment.json` (prices aren't stored in the trajectory),
so it can be re-rendered any time without re-running the LLM.
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

from .model import ARCHETYPES, MODE_LABEL, MODES

# --- CJK font so Chinese labels render (not tofu) ------------------------------------------------
for _fp in ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/STHeiti Medium.ttc"]:
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

# mode -> color (consistent across every figure)
MODE_COLOR = {"canteen": "#3b7dd8", "delivery": "#e8833a", "cook": "#2e8b57"}
ARCH_LABEL = {a["key"]: a["label"] for a in ARCHETYPES}
ARCH_ORDER = [a["key"] for a in ARCHETYPES]


# ================================================================================================
# data loading
# ================================================================================================
def _load_metrics(con) -> list[dict]:
    cols = [d[0] for d in con.execute("SELECT * FROM metrics LIMIT 0").description]
    rows = con.execute("SELECT * FROM metrics ORDER BY step").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def _panel_at(con, step) -> list[dict]:
    rows = con.execute("SELECT agent_id, state FROM panel WHERE step=? ORDER BY agent_id",
                       [step]).fetchall()
    out = []
    for aid, state in rows:
        d = state if isinstance(state, dict) else json.loads(state)
        d["agent_id"] = aid
        out.append(d)
    return out


def _events(con) -> dict[int, list[str]]:
    rows = con.execute("SELECT step, note FROM events ORDER BY step").fetchall()
    out: dict[int, list[str]] = {}
    for step, note in rows:
        out.setdefault(step, []).append(note)
    return out


def _reconstruct_prices(env_path, n_steps) -> dict[str, list[float]]:
    """Prices aren't in the trajectory; rebuild the per-meal path from environment.json's
    base prices × the monthly multiply events (step 0 = base)."""
    env = json.loads(Path(env_path).read_text(encoding="utf-8"))
    pa = env["provider_args"]
    base = {"canteen": pa["base_canteen"], "delivery": pa["base_delivery"], "cook": pa["base_cook"]}
    layer2mode = {"canteen_price": "canteen", "delivery_price": "delivery", "cook_cost": "cook"}
    path = {m: [base[m]] for m in MODES}
    cur = dict(base)
    for t in range(1, n_steps + 1):
        for ev in env.get("scheduled_events", []):
            if ev["at_step"] == t and ev["target_layer"] in layer2mode and ev["op"] == "multiply":
                m = layer2mode[ev["target_layer"]]
                cur[m] = round(cur[m] * float(ev["value"]), 3)
        for m in MODES:
            path[m].append(cur[m])
    return path


# ================================================================================================
# figures
# ================================================================================================
def _mark_hikes(ax, event_steps):
    for s in event_steps:
        ax.axvline(s, color="#c7ccd1", ls="--", lw=1, alpha=0.8, zorder=0)


def _fig_shares(metrics, event_steps, out_png):
    steps = [m["step"] for m in metrics]
    canteen = [m["share_canteen"] * 100 for m in metrics]
    delivery = [m["share_delivery"] * 100 for m in metrics]
    cook = [m["share_cook"] * 100 for m in metrics]
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.stackplot(steps, canteen, delivery, cook,
                 labels=[MODE_LABEL["canteen"], MODE_LABEL["delivery"], MODE_LABEL["cook"]],
                 colors=[MODE_COLOR["canteen"], MODE_COLOR["delivery"], MODE_COLOR["cook"]],
                 alpha=0.88)
    ax.set_xlabel("月（0=涨价前基线）")
    ax.set_ylabel("学生占比 (%)")
    ax.set_ylim(0, 100)
    ax.set_xlim(0, steps[-1])
    ax.set_title("主要就餐方式占比逐月演化（虚线=当月涨价）")
    ax.legend(loc="upper center", ncol=3, framealpha=0.9)
    _mark_hikes(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _fig_prices(prices, event_steps, out_png):
    steps = list(range(len(prices["canteen"])))
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    for m in MODES:
        ax.plot(steps, prices[m], "-o", color=MODE_COLOR[m], lw=2.2, ms=4,
                label=f"{MODE_LABEL[m]}（{prices[m][0]:.0f}→{prices[m][-1]:.1f} 元）")
    ax.set_xlabel("月")
    ax.set_ylabel("单餐花费（元）")
    ax.set_title("三种就餐方式单餐价格路径（外生处理：食堂+8%/外卖+6%/自炊+2% 每月）")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left")
    _mark_hikes(ax, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _fig_spend_satisfaction(metrics, event_steps, out_png):
    steps = [m["step"] for m in metrics]
    spend = [m["mean_food_spend"] for m in metrics]
    sat = [m["mean_satisfaction"] for m in metrics]
    fig, ax1 = plt.subplots(figsize=(8.6, 4.4))
    c_spend, c_sat = "#b5482e", "#4a3f8f"
    ax1.plot(steps, spend, "-o", color=c_spend, lw=2.4, ms=5, label="人均月餐费（元）")
    ax1.set_xlabel("月")
    ax1.set_ylabel("人均月餐费（元）", color=c_spend)
    ax1.tick_params(axis="y", labelcolor=c_spend)
    ax2 = ax1.twinx()
    ax2.plot(steps, sat, "-s", color=c_sat, lw=2.4, ms=5, label="平均满意度")
    ax2.set_ylabel("平均消费满意度 (0–1)", color=c_sat)
    ax2.tick_params(axis="y", labelcolor=c_sat)
    ax2.set_ylim(0.5, 0.75)
    ax1.set_title("钱包压力↑ 与 满意度↓（逐月涨价的双重挤压）")
    ax1.grid(alpha=0.2)
    _mark_hikes(ax1, event_steps)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _cohort_mix(panel) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {k: {m: 0 for m in MODES} for k in ARCH_ORDER}
    for p in panel:
        a = p.get("archetype")
        c = p.get("choice")
        if a in out and c in out[a]:
            out[a][c] += 1
    return out


def _fig_migration(panel0, panelN, out_png):
    """Per-archetype baseline→end-of-period choice mix — who switched, who stayed (paired stacked bars)."""
    mix0, mixN = _cohort_mix(panel0), _cohort_mix(panelN)
    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    x = range(len(ARCH_ORDER))
    w = 0.36
    for off, mix, tag in [(-w / 2 - 0.02, mix0, "基线"), (w / 2 + 0.02, mixN, "期末")]:
        bottoms = [0] * len(ARCH_ORDER)
        for m in MODES:
            vals = [mix[k][m] for k in ARCH_ORDER]
            ax.bar([i + off for i in x], vals, w, bottom=bottoms, color=MODE_COLOR[m],
                   edgecolor="white", linewidth=0.5)
            bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_xticks(list(x))
    ax.set_xticklabels([ARCH_LABEL[k].split("（")[0] for k in ARCH_ORDER], fontsize=9)
    ax.set_ylabel("人数")
    ax.set_title("分画像就餐方式迁移：每组 左=基线 右=期末（色块=食堂/外卖/自炊）")
    handles = [plt.Rectangle((0, 0), 1, 1, color=MODE_COLOR[m]) for m in MODES]
    ax.legend(handles, [MODE_LABEL[m] for m in MODES], loc="upper right", ncol=3, fontsize=8)
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
            val = f.get("value", "")
            unit = f.get("unit", "")
            val_s = f"{val} {unit}".strip() if val != "" else "—"
            basis = _BASIS_CN.get(f.get("basis", ""), f.get("basis", ""))
            src = f.get("source", {}) or {}
            src_s = src.get("title", "") or "—"
            if src.get("url"):
                src_s = f"{src_s} ({src['url']})"
            lines.append(f"| {f.get('claim', f.get('id', ''))} | {val_s} | {basis} | {src_s} |")
    refs = g.get("implementation_refs") or g.get("modeling_refs") or []
    if refs:
        lines.append("\n**建模参考**\n")
        for r in refs:
            lines.append(f"- {r.get('claim', r.get('title', r.get('id', '')))}")
    assumptions = g.get("assumptions", [])
    if assumptions:
        lines.append("\n**声明的假设**\n")
        for a in assumptions:
            claim = a.get("claim", a.get("id", ""))
            why = a.get("rationale", "")
            lines.append(f"- {claim}" + (f" — {why}" if why else ""))
    if g.get("method_notes") == "stylized" and not facts:
        lines.append("\n风格化模型，无真实世界锚点。")
    return lines


# ================================================================================================
# report.md
# ================================================================================================
def _share_table(metrics) -> str:
    lines = ["| 月 | 食堂 | 外卖 | 自炊 | 平均满意度 | 人均月餐费(元) |", "|---|---|---|---|---|---|"]
    for m in metrics:
        tag = "（基线）" if m["step"] == 0 else ""
        lines.append(f"| {m['step']}{tag} | {m['share_canteen'] * 100:.0f}% | "
                     f"{m['share_delivery'] * 100:.0f}% | {m['share_cook'] * 100:.0f}% | "
                     f"{m['mean_satisfaction']:.3f} | {m['mean_food_spend']:.0f} |")
    return "\n".join(lines)


def _migration_table(panel0, panelN) -> str:
    mix0, mixN = _cohort_mix(panel0), _cohort_mix(panelN)
    lines = ["| 画像 | 基线(食堂/外卖/自炊) | 期末(食堂/外卖/自炊) |", "|---|---|---|"]
    for k in ARCH_ORDER:
        a, b = mix0[k], mixN[k]
        lines.append(f"| {ARCH_LABEL[k]} | {a['canteen']}/{a['delivery']}/{a['cook']} | "
                     f"{b['canteen']}/{b['delivery']}/{b['cook']} |")
    return "\n".join(lines)


def generate_report(duckdb_path, out_dir, *, env_path, study_dir, study_title="",
                    event_steps=None, version=""):
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

    event_steps = event_steps or sorted(s for s in events if s > 0)
    prices = _reconstruct_prices(env_path, max_step)

    _fig_shares(metrics, event_steps, fig_dir / "shares.png")
    _fig_prices(prices, event_steps, fig_dir / "prices.png")
    _fig_spend_satisfaction(metrics, event_steps, fig_dir / "spend_satisfaction.png")
    _fig_migration(panel0, panelN, fig_dir / "migration.png")

    first, last = metrics[0], metrics[-1]
    spend_chg = (last["mean_food_spend"] / first["mean_food_spend"] - 1) * 100
    d_cook = (last["share_cook"] - first["share_cook"]) * 100
    d_del = (last["share_delivery"] - first["share_delivery"]) * 100

    lines = [f"# {study_title or 'campus_dining_choice'}"]
    if version:
        lines.append(f"\n> 版本：**{version}**")
    lines.append("\n## 结论速览\n")
    lines.append(f"- 追踪 **{len(panelN)} 名**固定学生（面板），共 **{max_step} 个月**（step 0 为涨价前基线）。")
    lines.append(f"- 就餐方式占比：食堂 {first['share_canteen'] * 100:.0f}%→{last['share_canteen'] * 100:.0f}%、"
                 f"外卖 {first['share_delivery'] * 100:.0f}%→{last['share_delivery'] * 100:.0f}%"
                 f"（{d_del:+.0f}pp）、自炊 {first['share_cook'] * 100:.0f}%→{last['share_cook'] * 100:.0f}%"
                 f"（{d_cook:+.0f}pp）。")
    lines.append(f"- **人均月餐费 {first['mean_food_spend']:.0f}→{last['mean_food_spend']:.0f} 元"
                 f"（{spend_chg:+.0f}%）**，平均满意度 {first['mean_satisfaction']:.3f}→"
                 f"{last['mean_satisfaction']:.3f}（{(last['mean_satisfaction'] - first['mean_satisfaction']):+.3f}）。")
    lines.append(f"- 4 个月累计涨价：食堂 {prices['canteen'][0]:.0f}→{prices['canteen'][-1]:.1f} 元、"
                 f"外卖 {prices['delivery'][0]:.0f}→{prices['delivery'][-1]:.1f} 元、"
                 f"自炊 {prices['cook'][0]:.0f}→{prices['cook'][-1]:.1f} 元。")

    lines.append("\n## 主要就餐方式占比演化\n")
    lines.append("![shares](figures/shares.png)\n")
    lines.append(_share_table(metrics))

    lines.append("\n## 价格环境（外生处理）\n")
    lines.append("![prices](figures/prices.png)\n")

    lines.append("\n## 钱包压力与满意度\n")
    lines.append("![spend_satisfaction](figures/spend_satisfaction.png)\n")

    lines.append("\n## 分画像就餐迁移（谁转了、谁没转）\n")
    lines.append("![migration](figures/migration.png)\n")
    lines.append(_migration_table(panel0, panelN))

    lines.append("\n## 逐月涨价事件\n")
    for step in sorted(s for s in events if s > 0):
        for note in events[step]:
            lines.append(f"- **t{step}**：{note}")

    lines += _grounding_section(study_dir)

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
