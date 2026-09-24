"""reporting.py — render the opinion_diffusion longitudinal result.

No map (this is an opinion-dynamics panel on a ring network, not a geo study): the report
centers on the OPINION TRAJECTORY — the mean_opinion / opinion_std / frac_above_0_5 paths
against the step-2 media campaign, plus the per-cohort split (agents that started low vs high
opinion) showing who the campaign pulled up.

Everything is reconstructed from the DuckDB `metrics` + `panel` + `events` tables via SQL/JSON,
so it can be re-rendered any time without re-running the LLM. Mirrors the campus_dining_choice
reporting shape (figures + analytical findings / deeper-insights / recommendations sections + a grounding section).

Language: English by default, so the figures need no CJK font. ``generate_report(..., lang="zh")``
or ``SV_REPORT_LANG=zh`` renders the report in Chinese, the language of the shipped reference
report in ``reports/``; its figures use a CJK font when one is installed (``cjk_font()``).

The qualitative sentences are written from the data (monotone or not, majority or not), and
the mechanism sentences follow the decision layer: the bounded-confidence rule for scripted
runs, the LLM prompt for ``llm_kind="openai"`` runs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import mean

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

plt.rcParams["axes.unicode_minus"] = False

C_MEAN, C_STD, C_FRAC = "#3b7dd8", "#b5482e", "#2e8b57"
C_LOW, C_HIGH = "#e8833a", "#4a3f8f"

# --- CJK font so Chinese labels render (not tofu); only used for lang="zh" -----------------------
_CJK_FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
              "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
              "/System/Library/Fonts/STHeiti Medium.ttc"]


_CJK_NAME_HINTS = ("CJK", "WenQuanYi", "Source Han", "Heiti", "PingFang", "SimHei", "YaHei")


def cjk_font() -> str | None:
    """Path of a font matplotlib can use for Chinese labels, or None when none is installed
    (then the zh figures show boxes; e.g. ``apt install fonts-noto-cjk`` fixes it)."""
    for fp in _CJK_FONTS:
        if os.path.exists(fp):
            return fp
    for f in fm.fontManager.ttflist:
        if any(h in f.name for h in _CJK_NAME_HINTS):
            return f.fname
    return None


def _font_rc(lang: str) -> dict:
    """rc overrides for one figure: a CJK font family for the Chinese report, none for English."""
    if lang != "zh":
        return {}
    fp = cjk_font()
    if fp:
        fm.fontManager.addfont(fp)
        return {"font.family": fm.FontProperties(fname=fp).get_name()}
    return {}


def resolve_lang(lang: str | None = None) -> str:
    """``"zh"`` or ``"en"``: the explicit argument, else ``$SV_REPORT_LANG``, else English."""
    v = (lang or os.environ.get("SV_REPORT_LANG") or "en").strip().lower()
    return "zh" if v.startswith("zh") else "en"


# Figure text per language (the zh strings are the ones the shipped reference report used).
_FIG = {
    "en": {
        "mean": "Mean opinion (mean_opinion)",
        "frac": "Share at or above 0.5 (frac_above_0_5)",
        "std": "Opinion std (opinion_std)",
        "op_x": "Step (0 = initial; dashed line = step-2 media campaign)",
        "op_y": "Mean opinion / share at or above 0.5 (0–1)",
        "op_y2": "Opinion std (lower = more convergence)",
        "op_title": "Opinion trajectory: the mean rises and the spread narrows, faster after the campaign",
        "low": "Initially low (t0 < 0.5)",
        "high": "Initially high (t0 ≥ 0.5)",
        "co_x": "Step (dashed line = step-2 media campaign)",
        "co_y": "Cohort mean opinion (0–1)",
        "co_title": "The two cohorts converge: whom the campaign moved most",
    },
    "zh": {
        "mean": "平均意见 mean_opinion",
        "frac": "支持占比 frac_above_0_5",
        "std": "意见标准差 opinion_std",
        "op_x": "步 (0=初始，虚线=第2步媒体campaign)",
        "op_y": "平均意见 / 支持占比 (0–1)",
        "op_y2": "意见标准差 (越低=越收敛)",
        "op_title": "意见轨迹：均值↑与收敛↓，campaign后加速",
        "low": "初始低意见组 (t0<0.5)",
        "high": "初始高意见组 (t0≥0.5)",
        "co_x": "步 (虚线=第2步媒体campaign)",
        "co_y": "组内平均意见 (0–1)",
        "co_title": "两组意见收拢：谁被campaign拉动最多",
    },
}


# ================================================================================================
# data loading
# ================================================================================================
def _load_metrics(con) -> list[dict]:
    cols = [d[0] for d in con.execute("SELECT * FROM metrics LIMIT 0").description]
    rows = con.execute("SELECT * FROM metrics ORDER BY step").fetchall()
    return [dict(zip(cols, r)) for r in rows]


def _panel_at(con, step) -> dict[str, float]:
    rows = con.execute("SELECT agent_id, state FROM panel WHERE step=? ORDER BY agent_id",
                       [step]).fetchall()
    out = {}
    for aid, state in rows:
        d = state if isinstance(state, dict) else json.loads(state)
        out[aid] = float(d["opinion"])
    return out


def _events(con) -> dict[int, list[str]]:
    rows = con.execute("SELECT step, note FROM events ORDER BY step").fetchall()
    out: dict[int, list[str]] = {}
    for step, note in rows:
        out.setdefault(step, []).append(note)
    return out


def _cohort_paths(con, max_step) -> tuple[dict, dict]:
    """Split agents by their t=0 opinion (low <0.5 vs high >=0.5) and follow each cohort's mean."""
    base = _panel_at(con, 0)
    low_ids = {a for a, v in base.items() if v < 0.5}
    high_ids = {a for a, v in base.items() if v >= 0.5}
    low_path, high_path = {}, {}
    for t in range(max_step + 1):
        p = _panel_at(con, t)
        low_path[t] = round(mean([p[a] for a in low_ids]), 4) if low_ids else None
        high_path[t] = round(mean([p[a] for a in high_ids]), 4) if high_ids else None
    return low_path, high_path


# ================================================================================================
# figures
# ================================================================================================
def _mark_events(ax, event_steps):
    for s in event_steps:
        ax.axvline(s, color="#c7ccd1", ls="--", lw=1, alpha=0.9, zorder=0)


def _fig_opinion(metrics, event_steps, out_png, lang="en"):
    t = _FIG[lang]
    steps = [m["step"] for m in metrics]
    mean_op = [m["mean_opinion"] for m in metrics]
    std = [m["opinion_std"] for m in metrics]
    frac = [m["frac_above_0_5"] for m in metrics]
    with plt.rc_context(_font_rc(lang)):
        fig, ax1 = plt.subplots(figsize=(8.6, 4.6))
        ax1.plot(steps, mean_op, "-o", color=C_MEAN, lw=2.4, ms=5, label=t["mean"])
        ax1.plot(steps, frac, "-^", color=C_FRAC, lw=2.0, ms=5, label=t["frac"])
        ax1.set_xlabel(t["op_x"])
        ax1.set_ylabel(t["op_y"])
        ax1.set_ylim(0, 1)
        ax2 = ax1.twinx()
        ax2.plot(steps, std, "-s", color=C_STD, lw=2.4, ms=5, label=t["std"])
        ax2.set_ylabel(t["op_y2"], color=C_STD)
        ax2.tick_params(axis="y", labelcolor=C_STD)
        ax2.set_ylim(0, max(std) * 1.25)
        ax1.set_title(t["op_title"])
        ax1.xaxis.set_major_locator(MaxNLocator(integer=True))     # steps are whole numbers
        lines = ax1.get_lines() + ax2.get_lines()
        # below the plot, so it never covers a series (loc="best" only sees one of the twin axes)
        ax1.legend(lines, [l.get_label() for l in lines], loc="upper center",
                   bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False, fontsize=8.5)
        ax1.grid(alpha=0.2)
        _mark_events(ax1, event_steps)
        fig.tight_layout()
        fig.savefig(out_png, dpi=130, bbox_inches="tight")
        plt.close(fig)


def _fig_cohorts(low_path, high_path, event_steps, out_png, lang="en"):
    t = _FIG[lang]
    steps = sorted(low_path)
    with plt.rc_context(_font_rc(lang)):
        fig, ax = plt.subplots(figsize=(8.6, 4.4))
        ax.plot(steps, [low_path[s] for s in steps], "-o", color=C_LOW, lw=2.4, ms=5,
                label=t["low"])
        ax.plot(steps, [high_path[s] for s in steps], "-s", color=C_HIGH, lw=2.4, ms=5,
                label=t["high"])
        ax.axhline(0.5, color="#999", ls=":", lw=1, alpha=0.7)
        ax.set_xlabel(t["co_x"])
        ax.set_ylabel(t["co_y"])
        ax.set_ylim(0, 1)
        ax.set_title(t["co_title"])
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))      # steps are whole numbers
        ax.legend(loc="best", framealpha=0.9)
        ax.grid(alpha=0.25)
        _mark_events(ax, event_steps)
        fig.tight_layout()
        fig.savefig(out_png, dpi=130)
        plt.close(fig)


# ================================================================================================
# grounding section  (the report's data-basis-and-sources section)
# ================================================================================================
_BASIS = {"zh": {"sourced": "实证", "proxy": "代理", "assumed": "假设"},
          "en": {"sourced": "sourced", "proxy": "proxy", "assumed": "assumed"}}
_GROUNDING_TEXT = {
    "zh": {"head": "\n## 数据基础与参考来源\n", "cols": "| 事实 | 值 | 依据 | 来源 |",
           "refs": "\n**建模参考**\n", "assumptions": "\n**声明的假设**\n",
           "stylized": "\n风格化模型，无真实世界锚点。"},
    "en": {"head": "\n## Data basis and sources\n", "cols": "| Fact | Value | Basis | Source |",
           "refs": "\n**Modelling references**\n", "assumptions": "\n**Declared assumptions**\n",
           "stylized": "\nStylized model with no real-world anchors."},
}


def _grounding_section(study_dir, lang="en") -> list[str]:
    try:
        from skills import sv_grounding
        g = sv_grounding.load(study_dir)
    except Exception:
        g = None
    if not g:
        return []
    t, basis_names = _GROUNDING_TEXT[lang], _BASIS[lang]
    lines = [t["head"]]
    facts = g.get("facts", [])
    if facts:
        lines.append(t["cols"])
        lines.append("|---|---|---|---|")
        for f in facts:
            val, unit = f.get("value", ""), f.get("unit", "")
            val_s = f"{val} {unit}".strip() if val != "" else "—"
            basis = basis_names.get(f.get("basis", ""), f.get("basis", ""))
            src = f.get("source", {}) or {}
            src_s = src.get("title", "") or "—"
            if src.get("url"):
                src_s = f"{src_s} ({src['url']})"
            lines.append(f"| {f.get('claim', f.get('id', ''))} | {val_s} | {basis} | {src_s} |")
    refs = g.get("implementation_refs") or []
    if refs:
        lines.append(t["refs"])
        for r in refs:
            title = r.get("title", r.get("id", ""))
            tk = r.get("takeaway", "")
            lines.append(f"- {title}" + (f" — {tk}" if tk else ""))
    assumptions = g.get("assumptions", [])
    if assumptions:
        lines.append(t["assumptions"])
        for a in assumptions:
            claim, why = a.get("claim", a.get("id", "")), a.get("rationale", "")
            lines.append(f"- {claim}" + (f" — {why}" if why else ""))
    if g.get("method_notes") == "stylized" and not facts:
        lines.append(t["stylized"])
    return lines


# ================================================================================================
# report.md
# ================================================================================================
def _metric_table(metrics, events, lang="en") -> str:
    if lang == "zh":
        head = "| 步 | 平均意见 | 意见标准差 | 支持占比(≥0.5) | 事件 |"
        initial, sep = "（初始）", "；"
    else:
        head = "| Step | Mean opinion | Opinion std | Share ≥ 0.5 | Events |"
        initial, sep = " (initial)", "; "
    lines = [head, "|---|---|---|---|---|"]
    for m in metrics:
        tag = initial if m["step"] == 0 else ""
        ev = sep.join(events.get(m["step"], [])) or ""
        lines.append(f"| {m['step']}{tag} | {m['mean_opinion']:.3f} | {m['opinion_std']:.3f} | "
                     f"{m['frac_above_0_5'] * 100:.0f}% | {ev} |")
    return "\n".join(lines)


def _shape(metrics, cstep) -> dict:
    """What the data actually did, so each qualitative sentence is only written when it holds."""
    mean_ = [m["mean_opinion"] for m in metrics]
    std = [m["opinion_std"] for m in metrics]
    steps = [m["step"] for m in metrics]
    post = [v for s_, v in zip(steps, mean_) if s_ >= cstep]
    first_frac, last_frac = metrics[0]["frac_above_0_5"], metrics[-1]["frac_above_0_5"]
    d1_mean = mean_[1] - mean_[0] if len(mean_) > 1 else 0.0
    d1_std = std[1] - std[0] if len(std) > 1 else 0.0
    return {
        "std_monotone": all(b <= a for a, b in zip(std, std[1:])) and std[-1] < std[0],
        "std_falls": std[-1] < std[0],
        "std_falls_early": cstep > 1 and d1_std < 0,
        "mean_rises_after": len(post) > 1 and all(b >= a for a, b in zip(post, post[1:]))
                            and post[-1] > post[0],
        "mean_up_after": len(post) > 1 and post[-1] > post[0],
        "frac_majority": last_frac > 0.5 and last_frac > first_frac,
        "frac_up": last_frac > first_frac,
        "frac_down": last_frac < first_frac,
        "separable": cstep > 1 and d1_std < 0 and abs(d1_mean) < 0.02,
        "d1_mean": d1_mean, "d1_std": d1_std,
    }


def _llm_kind_of(llm_kind, run_mode) -> str:
    if llm_kind:
        return llm_kind
    return "openai" if "llm_kind=openai" in (run_mode or "") else "scripted"


def generate_report(duckdb_path, out_dir, *, study_dir, study_title="",
                    event_steps=None, run_mode="", version="", lang=None, llm_kind=None):
    """Render report.md + figures/ into ``out_dir`` from a finished run's DuckDB store.

    ``lang``: "en" (default) or "zh"; when omitted, ``$SV_REPORT_LANG`` decides.
    ``llm_kind``: the decision layer the run used ("scripted" or "openai"); when omitted it is
    read from ``run_mode`` ("llm_kind=openai" in it means an LLM run). The mechanism sentences
    describe the bounded-confidence rule for scripted runs and the LLM layer for LLM runs."""
    lang = resolve_lang(lang)
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(duckdb_path), read_only=True)
    metrics = _load_metrics(con)
    max_step = max(m["step"] for m in metrics)
    events = _events(con)
    low_path, high_path = _cohort_paths(con, max_step)
    con.close()

    event_steps = event_steps or sorted(s for s in events if s > 0)
    first, last = metrics[0], metrics[-1]

    _fig_opinion(metrics, event_steps, fig_dir / "opinion_trajectory.png", lang)
    _fig_cohorts(low_path, high_path, event_steps, fig_dir / "cohort_paths.png", lang)

    # pre/post-campaign deltas for the findings
    cstep = event_steps[0] if event_steps else 2
    pre = next((m for m in metrics if m["step"] == cstep - 1), first)
    at = next((m for m in metrics if m["step"] == cstep), last)
    ctx = {
        "study_title": study_title, "run_mode": run_mode, "version": version,
        "metrics": metrics, "events": events, "first": first, "last": last,
        "max_step": max_step, "cstep": cstep,
        "low_path": low_path, "high_path": high_path,
        "d_mean_pre": pre["mean_opinion"] - first["mean_opinion"],
        "d_mean_total": last["mean_opinion"] - first["mean_opinion"],
        "d_std_total": last["opinion_std"] - first["opinion_std"],
        "d_mean_atstep": at["mean_opinion"] - pre["mean_opinion"],
        "low_gain": (low_path[max_step] - low_path[0]) if low_path[0] is not None else 0,
        "high_gain": (high_path[max_step] - high_path[0]) if high_path[0] is not None else 0,
        "n_agents": _count_agents(duckdb_path),
        "llm": _llm_kind_of(llm_kind, run_mode) == "openai",
        **_shape(metrics, cstep),
    }
    lines = _report_zh(ctx) if lang == "zh" else _report_en(ctx)
    lines += _grounding_section(study_dir, lang)

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _report_en(c: dict) -> list[str]:
    first, last, cstep, max_step = c["first"], c["last"], c["cstep"], c["max_step"]
    low_path, high_path = c["low_path"], c["high_path"]
    low_gain, high_gain = c["low_gain"], c["high_gain"]
    d_mean_pre, d_mean_atstep = c["d_mean_pre"], c["d_mean_atstep"]
    run_mode = c["run_mode"]
    pre_steps = f"{cstep - 1} step" + ("" if cstep - 1 == 1 else "s")

    lines = [f"# {c['study_title'] or 'opinion_diffusion'}"]
    tags = [x for x in (c["version"], run_mode) if x]
    if tags:
        lines.append(f"\n> Version / mode: **{' · '.join(tags)}**")

    lines.append("\n## Summary\n")
    lines.append(f"- Tracks **{c['n_agents']} fixed agents** (ring network, panel data) over "
                 f"**{max_step} steps** (step 0 is the initial state; the media campaign starts at "
                 f"step {cstep}).")
    if c["mean_rises_after"]:
        after = "then a steady rise"
    elif c["mean_up_after"]:
        after = "then an uneven rise"
    else:
        after = "and no further rise after it"
    lines.append(f"- **Mean opinion {first['mean_opinion']:.3f}→{last['mean_opinion']:.3f}"
                 f" ({c['d_mean_total']:+.3f})**: {d_mean_pre:+.3f} over the {pre_steps} before "
                 f"the campaign, {d_mean_atstep:+.3f} at the campaign step, {after}.")
    if c["std_monotone"]:
        std_s = "a monotone decline, i.e. the population keeps converging towards consensus."
    elif c["std_falls"]:
        std_s = "a net decline that is not monotone, i.e. the population converges overall."
    else:
        std_s = "no decline, i.e. the population does not converge."
    lines.append(f"- **Opinion std {first['opinion_std']:.3f}→{last['opinion_std']:.3f}"
                 f" ({c['d_std_total']:+.3f})**: {std_s}")
    if c["frac_majority"]:
        frac_s = "the majority moves to the supporting side."
    elif c["frac_up"]:
        frac_s = "more agents are at or above 0.5, but not a majority."
    elif c["frac_down"]:
        frac_s = "fewer agents are at or above 0.5."
    else:
        frac_s = "unchanged."
    lines.append(f"- **Share at or above 0.5: {first['frac_above_0_5'] * 100:.0f}%→"
                 f"{last['frac_above_0_5'] * 100:.0f}%**: {frac_s}")
    if run_mode and c["llm"]:
        lines.append(f"- Decision layer: {run_mode} (one LLM role-play call per agent per step; "
                     f"replies that do not parse fall back to the bounded-confidence rule).")

    lines.append("\n## Opinion trajectory (mean, spread, share at or above 0.5)\n")
    lines.append("![opinion](figures/opinion_trajectory.png)\n")
    lines.append(_metric_table(c["metrics"], c["events"], "en"))

    lines.append("\n## The two cohorts converge (grouped by initial opinion)\n")
    lines.append("![cohorts](figures/cohort_paths.png)\n")
    lines.append("| Cohort | Initial mean | Final mean | Change |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Initially low (t0 < 0.5) | {low_path[0]:.3f} | {low_path[max_step]:.3f} | "
                 f"{low_gain:+.3f} |")
    lines.append(f"| Initially high (t0 ≥ 0.5) | {high_path[0]:.3f} | {high_path[max_step]:.3f} | "
                 f"{high_gain:+.3f} |")

    # --- analytical sections (required by sv-report) --------------------------------------------
    lines.append("\n## Findings\n")
    llm = c["llm"]
    turning = d_mean_atstep > 0 and d_mean_atstep > 2 * abs(d_mean_pre)
    if turning:
        f1 = (f"1. **The campaign is the turning point of the rise, not a steady drift.** The mean "
              f"opinion barely moves over the {pre_steps} before the campaign ({d_mean_pre:+.3f}). "
              f"At step {cstep}, when the media pressure (macro-physical) and the campaign broadcast "
              f"(macro-information) take effect together, it jumps {d_mean_atstep:+.3f} in one step, ")
    else:
        f1 = (f"1. **The campaign step does not stand out from the drift before it.** The mean "
              f"opinion moves {d_mean_pre:+.3f} over the {pre_steps} before the campaign and "
              f"{d_mean_atstep:+.3f} at step {cstep}, when the media pressure (macro-physical) and "
              f"the campaign broadcast (macro-information) take effect together, ")
    f1 += (f"then keeps climbing to {last['mean_opinion']:.3f}. " if c["mean_up_after"]
           else f"and ends at {last['mean_opinion']:.3f}. ")
    if llm:
        f1 += (f"Mechanism: each agent's new opinion is the LLM's reply to a prompt that shows its "
               f"own stance, its neighbours' stances, the media pressure and, from step {cstep}, the "
               f"campaign message. The prompt describes the pull towards support but does not "
               f"enforce it, so the size of the jump is the model's response to these cues.")
    else:
        f1 += ("Mechanism: in `decide_batch` the media and campaign terms pull every agent towards "
               "1, and the pull shrinks with the remaining room (1−opinion), so the rise is fast at "
               "first and slower later.")
    lines.append(f1)
    if c["std_monotone"] and c["std_falls_early"]:
        f2 = (f"2. **Convergence (falling variance) runs through the whole run and does not depend "
              f"on the campaign.** opinion_std falls monotonically from {first['opinion_std']:.3f} "
              f"to {last['opinion_std']:.3f} ({c['d_std_total']:+.3f}) and is already falling at "
              f"step 1, before the campaign. ")
    elif c["std_falls"]:
        f2 = (f"2. **The variance falls over the run, though not steadily.** opinion_std goes from "
              f"{first['opinion_std']:.3f} to {last['opinion_std']:.3f} ({c['d_std_total']:+.3f}), "
              f"{'monotonically' if c['std_monotone'] else 'not monotonically'}, and moves "
              f"{c['d1_std']:+.3f} at step 1. ")
    else:
        f2 = (f"2. **The variance does not fall.** opinion_std goes from {first['opinion_std']:.3f} "
              f"to {last['opinion_std']:.3f} ({c['d_std_total']:+.3f}). ")
    if llm:
        f2 += ("Mechanism: the prompt asks each agent to move towards neighbours whose stance is "
               "close to its own and to ignore distant ones; how closely the LLM follows that "
               "instruction sets the pace of convergence.")
    else:
        f2 += ("Mechanism: bounded-confidence neighbour averaging, in which each agent moves "
               "towards neighbours whose opinion differs by at most 0.3, is itself a contraction. "
               "The campaign adds a common upward shift; the convergence comes from peer averaging.")
    lines.append(f2)
    f3_head = ("The initially low cohort is pulled further." if low_gain > high_gain
               else "The initially low cohort is not pulled further.")
    f3 = (f"3. **{f3_head}** Its mean rises {low_gain:+.3f}, "
          f"against {high_gain:+.3f} for the initially high cohort "
          f"({'the low cohort moves more' if low_gain > high_gain else 'the two are close'}). ")
    if llm:
        f3 += ("Mechanism: the LLM decision layer has no explicit (1−opinion) term; the gap shows "
               "how the model weighs the campaign against each agent's starting stance.")
    else:
        f3 += ("Mechanism: the external-pull term (1−opinion) leaves more room to rise for agents "
               "who start low, so the campaign's marginal pull is stronger on those who do not yet "
               "support the policy, and the two cohorts close in on the upper-middle range.")
    lines.append(f3)

    lines.append("\n## Deeper insights\n")
    if c["separable"]:
        lines.append("- **The two dynamics can be separated.** Convergence (std falling) is driven by "
                     "*local* neighbour averaging and the rise (mean rising) by *macro* media and "
                     "campaign pressure. In this report they add up in the same direction, but step 1 "
                     "(std already falling, mean almost unchanged) shows that the two mechanisms are "
                     "independent. This is what the P/E four-quadrant design (local_physical vs "
                     "macro_physical/information) is meant to show: local assimilation and macro "
                     "pressure can be observed separately.")
    else:
        lines.append(f"- **This run does not separate the two dynamics.** The P/E four-quadrant design "
                     f"(local_physical vs macro_physical/information) lets local assimilation and macro "
                     f"pressure be observed separately, but step 1, before the campaign, moves the std "
                     f"{c['d1_std']:+.3f} and the mean {c['d1_mean']:+.3f}, so it does not isolate "
                     f"either one.")
    lines.append(f"- **The share of supporters is a lagging, stepwise indicator.** mean_opinion "
                 f"rises continuously, but frac_above_0_5 moves only when an individual agent crosses "
                 f"0.5 ({first['frac_above_0_5'] * 100:.0f}%→{last['frac_above_0_5'] * 100:.0f}%). A "
                 f"majority flip happens later than the shift in the average attitude, so judging a "
                 f"turn in opinion by the mean overstates how fast the majority flips.")
    if llm:
        lines.append("- **Real persuasion effects are far smaller than this run may suggest.** The "
                     "grounding records an empirical single-exposure persuasion effect of about 0.012 "
                     "(normalized). Nothing calibrates the LLM's response to one campaign message to "
                     "that size, so read the magnitudes as stylized.")
    else:
        lines.append("- **Real persuasion effects are far smaller than in this demo.** The grounding "
                     "records an empirical single-exposure persuasion effect of about 0.012 "
                     "(normalized). This demo amplifies media_gain and campaign_gain roughly 8–12 "
                     "times so that the bend shows within 4 steps; at a realistic size the same "
                     "campaign's curve would be much flatter, so read the magnitudes as stylized.")

    lines.append("\n## Recommendations and next steps\n")
    lines.append("- **Control run.** Use /sv-iterate to make a version with the campaign switched off "
                 "(remove the step-2 broadcast and the media event) and compare mean_opinion. That "
                 "measures the campaign's net effect directly; this run has no counterfactual baseline.")
    if llm:
        lines.append("- **Calibrate to real effect sizes.** Compare the LLM's per-step response to the "
                     "campaign with the ~0.012 scale in the grounding, for example against a scripted "
                     "run with media_gain and campaign_gain at that scale and a longer n_steps.")
    else:
        lines.append("- **Calibrate to real effect sizes.** Set media_gain and campaign_gain to the "
                     "~0.012 scale in the grounding and lengthen n_steps, to test whether weak but "
                     "sustained campaigning eventually changes the majority, which is closer to "
                     "reality than the demo's amplified values.")
    lines.append("- **Sweep the confidence threshold.** The current 0.3 is below the consensus "
                 "threshold of 0.5 (see the grounding). Sweep 0.1–0.5 and watch when opinion splits "
                 "into several clusters instead of one consensus, the classic phase transition of "
                 "bounded-confidence models.")
    if llm:
        lines.append("- **Scripted vs LLM.** This run used the LLM decision layer. Use /sv-iterate to "
                     "make a scripted (deterministic rule) version for a parity comparison, and check "
                     "whether LLM role-play shifts the result systematically against the plain rule "
                     "(for example stronger or weaker conformity).")
    else:
        lines.append("- **Scripted vs LLM.** This run used the scripted (deterministic rule) decision "
                     "layer. Use /sv-iterate to make an LLM version (`llm_kind: \"openai\"`) for a "
                     "parity comparison, and check whether LLM role-play shifts the result "
                     "systematically against the plain rule (for example stronger or weaker "
                     "conformity).")
    return lines


def _report_zh(c: dict) -> list[str]:
    first, last, cstep, max_step = c["first"], c["last"], c["cstep"], c["max_step"]
    low_path, high_path = c["low_path"], c["high_path"]
    low_gain, high_gain = c["low_gain"], c["high_gain"]
    d_mean_pre, d_mean_total, d_std_total = c["d_mean_pre"], c["d_mean_total"], c["d_std_total"]
    d_mean_atstep, n_agents = c["d_mean_atstep"], c["n_agents"]
    run_mode, version = c["run_mode"], c["version"]

    lines = [f"# {c['study_title'] or 'opinion_diffusion'}"]
    tags = []
    if version:
        tags.append(version)
    if run_mode:
        tags.append(run_mode)
    if tags:
        lines.append(f"\n> 版本/模式：**{' · '.join(tags)}**")

    lines.append("\n## 结论速览\n")
    lines.append(f"- 追踪 **{n_agents} 个**固定 agent（环形网络，面板数据），共 **{max_step} 步**"
                 f"（step 0 为初始，第 {cstep} 步投放媒体campaign）。")
    after = ("之后持续抬升" if c["mean_rises_after"]
             else "之后起伏上升" if c["mean_up_after"] else "之后未再抬升")
    lines.append(f"- **平均意见 {first['mean_opinion']:.3f}→{last['mean_opinion']:.3f}"
                 f"（{d_mean_total:+.3f}）**：campaign前 {cstep-1} 步仅 {d_mean_pre:+.3f}，"
                 f"campaign当步跳 {d_mean_atstep:+.3f}，{after}。")
    std_s = ("单调下降 = 群体持续收敛（共识化）。" if c["std_monotone"]
             else "净下降但非单调 = 总体趋于收敛。" if c["std_falls"] else "未下降 = 群体没有收敛。")
    lines.append(f"- **意见标准差 {first['opinion_std']:.3f}→{last['opinion_std']:.3f}"
                 f"（{d_std_total:+.3f}）**：{std_s}")
    frac_s = ("多数派向“支持”一侧移动。" if c["frac_majority"]
              else "达到 0.5 及以上的占比上升，但尚未过半。" if c["frac_up"]
              else "达到 0.5 及以上的占比下降。" if c["frac_down"] else "占比不变。")
    lines.append(f"- **支持占比(≥0.5) {first['frac_above_0_5'] * 100:.0f}%→"
                 f"{last['frac_above_0_5'] * 100:.0f}%**：{frac_s}")
    if run_mode and c["llm"]:
        lines.append(f"- 决策层：{run_mode}（每 agent 每步一次 LLM 角色扮演，未解析回复回退到有界信心规则）。")

    lines.append("\n## 意见轨迹（均值 / 收敛 / 支持占比）\n")
    lines.append("![opinion](figures/opinion_trajectory.png)\n")
    lines.append(_metric_table(c["metrics"], c["events"], "zh"))

    lines.append("\n## 两组意见收拢（按初始意见分组）\n")
    lines.append("![cohorts](figures/cohort_paths.png)\n")
    lines.append(f"| 组 | 初始均值 | 期末均值 | 变动 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 初始低意见组 (t0<0.5) | {low_path[0]:.3f} | {low_path[max_step]:.3f} | {low_gain:+.3f} |")
    lines.append(f"| 初始高意见组 (t0≥0.5) | {high_path[0]:.3f} | {high_path[max_step]:.3f} | {high_gain:+.3f} |")

    # --- analytical sections (required by sv-report) --------------------------------------------
    lines.append("\n## 发现与解读 (Findings)\n")
    llm = c["llm"]
    if d_mean_atstep > 0 and d_mean_atstep > 2 * abs(d_mean_pre):
        f1 = (f"1. **campaign 是意见抬升的拐点，而非匀速漂移。** 平均意见在 campaign 前 {cstep-1} 步"
              f"几乎不动（{d_mean_pre:+.3f}），第 {cstep} 步媒体压力(macro-physical)与 campaign 广播"
              f"(macro-information)同时生效后单步跳升 {d_mean_atstep:+.3f}，")
    else:
        f1 = (f"1. **campaign 当步并未明显偏离此前的走势。** 平均意见在 campaign 前 {cstep-1} 步变动 "
              f"{d_mean_pre:+.3f}，第 {cstep} 步媒体压力(macro-physical)与 campaign 广播"
              f"(macro-information)同时生效时变动 {d_mean_atstep:+.3f}，")
    f1 += (f"其后仍逐步爬升到 {last['mean_opinion']:.3f}。" if c["mean_up_after"]
           else f"期末为 {last['mean_opinion']:.3f}。")
    if llm:
        f1 += (f"机制：每个 agent 的新意见是 LLM 对提示词的回答，提示词给出自身意见、邻居意见、媒体压力"
               f"以及（第 {cstep} 步起）campaign 信息；提示词描述了向“支持”的外推但并不强制，"
               f"跳升幅度是模型对这些线索的反应。")
    else:
        f1 += ("机制：`decide_batch` 里 media/campaign 两项"
               "外推力把每个 agent 往 1 拉，且拉力随剩余空间 (1−opinion) 递减，故先快后缓。")
    lines.append(f1)
    if c["std_monotone"] and c["std_falls_early"]:
        f2 = (f"2. **收敛(方差下降)贯穿全程，且不依赖 campaign。** opinion_std 从 {first['opinion_std']:.3f} "
              f"单调降到 {last['opinion_std']:.3f}（{d_std_total:+.3f}），第1步(campaign前)已在下降。")
    elif c["std_falls"]:
        f2 = (f"2. **方差总体下降，但并非平稳。** opinion_std 从 {first['opinion_std']:.3f} "
              f"{'单调' if c['std_monotone'] else '非单调地'}降到 {last['opinion_std']:.3f}"
              f"（{d_std_total:+.3f}），第1步变动 {c['d1_std']:+.3f}。")
    else:
        f2 = (f"2. **方差没有下降。** opinion_std 从 {first['opinion_std']:.3f} 变为 "
              f"{last['opinion_std']:.3f}（{d_std_total:+.3f}）。")
    if llm:
        f2 += "机制：提示词要求每个 agent 向意见相近的邻居靠拢、忽略相差太远的意见；LLM 遵循这一指令的程度决定收敛快慢。"
    else:
        f2 += ("机制：有界信心邻域平均——每个 agent 向意见差≤0.3 的邻居靠拢——本身就是收缩算子，"
               "campaign 叠加的是“共同上移”，收敛来自 peer averaging。")
    lines.append(f2)
    f3 = (f"3. **{'低意见组被拉动得更多' if low_gain > high_gain else '低意见组并未被拉动得更多'}。** "
          f"初始低意见组均值上移 {low_gain:+.3f}，高意见组 {high_gain:+.3f}"
          f"（{'低组更大' if low_gain>high_gain else '两组相近'}）。")
    if llm:
        f3 += "机制：LLM 决策层没有显式的 (1−opinion) 外推项，两组差距反映模型如何权衡 campaign 与各 agent 的初始立场。"
    else:
        f3 += ("机制：外推力项 (1−opinion) 对"
               "起点低者留有更大上升空间，故 campaign 对“尚未支持”人群的边际拉动更强，两组向中上区间收拢。")
    lines.append(f3)

    lines.append("\n## 深层洞察 (Deeper insights)\n")
    if c["separable"]:
        lines.append(f"- **两种动力学可分离**：收敛(std↓)由 *local* 邻居平均驱动、抬升(mean↑)由 *macro* 媒体/宣传驱动——"
                     f"报告里它们同向叠加，但第1步(std已降、mean几乎未动)证明二者机制独立。这正是 P/E 四象限设计"
                     f"（local_physical vs macro_physical/information）要展示的：局部同化与宏观推动可以解耦观察。")
    else:
        lines.append(f"- **本次运行未能分离两种动力学**：P/E 四象限设计（local_physical vs macro_physical/information）"
                     f"允许分别观察局部同化与宏观推动，但 campaign 前的第1步 std 变动 {c['d1_std']:+.3f}、"
                     f"mean 变动 {c['d1_mean']:+.3f}，不足以单独识别其中任何一种。")
    lines.append(f"- **支持占比是滞后、跳变的指标**：mean_opinion 连续爬升，但 frac_above_0_5 只在个别 agent 跨过 0.5 时"
                 f"阶跃（{first['frac_above_0_5']*100:.0f}%→{last['frac_above_0_5']*100:.0f}%），说明“多数翻转”比"
                 f"“平均态度移动”更晚发生——用平均值判断舆论转向会高估翻盘速度。")
    if llm:
        lines.append("- **真实说服效应远小于本次运行所示**：grounding 记录的实证单次说服效应约 0.012（归一化），"
                     "而 LLM 对一次 campaign 信息的反应没有按这一量级校准，读数时须把幅度当作风格化。")
    else:
        lines.append(f"- **真实说服效应远小于本 demo**：grounding 记录的实证单次说服效应约 0.012（归一化），"
                     f"本 demo 的 media_gain/campaign_gain 被放大约 8–12 倍才能在 4 步内看出弯折；真实量级下同一 campaign "
                     f"的曲线会平缓得多，读数时须把幅度当作风格化。")

    lines.append("\n## 改进建议与下一步 (Recommendations & next steps)\n")
    lines.append("- **对照组实验**：/sv-iterate 复制一版把 campaign 关闭（去掉 step-2 broadcast + media 事件），"
                 "对比 mean_opinion 差值，直接量化 campaign 的净效应（当前无反事实基线）。")
    if llm:
        lines.append("- **校准到真实效应量**：把 LLM 每步对 campaign 的反应与 grounding 的 ~0.012 量级对照，"
                     "例如与一版 media_gain/campaign_gain 取该量级、n_steps 更长的 scripted 运行比较。")
    else:
        lines.append("- **校准到真实效应量**：把 media_gain/campaign_gain 调到 grounding 的 ~0.012 量级并拉长 n_steps，"
                     "检验“弱但持续”的宣传能否最终改变多数派——比 demo 的放大值更接近现实。")
    lines.append(f"- **扫 confidence 阈值**：当前 0.3<共识临界值 0.5（见 grounding）。扫 0.1–0.5 观察何时出现"
                 "意见分裂(多簇)而非单一共识，复现有界信心模型的经典相变。")
    if llm:
        lines.append("- **scripted vs LLM 对照**：本次为 LLM 决策层，可 /sv-iterate 出一版 scripted(确定性规则)做 parity 对照，"
                     "看 LLM 角色扮演相比纯规则是否引入系统性偏移（如更强/更弱的从众）。")
    else:
        lines.append("- **scripted vs LLM 对照**：本次为 scripted(确定性规则)决策层，可 /sv-iterate 出一版 LLM "
                     "(`llm_kind: \"openai\"`) 做 parity 对照，看 LLM 角色扮演相比纯规则是否引入系统性偏移（如更强/更弱的从众）。")
    return lines


def _count_agents(duckdb_path) -> int:
    con = duckdb.connect(str(duckdb_path), read_only=True)
    n = con.execute("SELECT COUNT(DISTINCT agent_id) FROM panel").fetchone()[0]
    con.close()
    return n
