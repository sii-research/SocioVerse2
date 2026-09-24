"""Rebuild this study's trajectory from the HiSim case in the SocioVerse2 tech report.

The case shown here is the tech report's §5.7 social-movement case
(https://arxiv.org/abs/2609.24911): a hybrid LLM+ABM simulation of the Roe v. Wade
overturn, scored **against the real Twitter sentiment trajectory** over 14 rounds. Both
series were digitized from the report's trajectory figure (itself from Figure 6 of the
HiSim paper), together with the news-injection windows; the accuracy numbers come from
the report's HiSim case tables.

Three things this script is deliberate about:

* **It is an import, not a run.** The trajectory is the published HiSim run, not
  something this workbench executed (the study is marked ``rerunnable: false``). A 4-step
  live LLM port (20 agents, 8 core + 12 ordinary) was run during development; its
  headline numbers are preserved in the report, and ``model.py`` / ``reporting.py`` — the
  actual port — stay as the template for a real run.
* **Digitized ≠ published.** Pearson recomputed on the digitized points is 0.783,
  while the paper reports 0.758 for this configuration. The gap is digitization
  error and both numbers are reported; nothing here silently claims the paper's.
* **Normalized, not absolute.** Each series is min–max normalized to [0,1] — that
  is the tech report's own convention, because the two curves' absolute ranges do
  not overlap and the evaluation is trajectory-shape based. Absolute-level
  agreement is a separate number (ΔBias), taken from the paper's table.

Inputs: the displayed scenario is read from the tracked
``environment/sources/techreport_case.json``; the other two scenarios' digitized series
live in ``SERIES`` below (the script checks that both agree). Maintainers with the report's
LaTeX source can pass ``--tikz <path to fig_hisim_trajectories.tikz>`` to cross-check every
coordinate against the figure source.

Usage:  python studies/hisim_roe/build_from_techreport.py [metoo|roe|blm] [--tikz PATH]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics

STUDY_ID = "hisim_roe"
HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CASE_JSON = HERE / "environment" / "sources" / "techreport_case.json"

# Provenance written into techreport_case.json (citations, not filesystem paths).
SOURCE = {
    "report": "https://arxiv.org/abs/2609.24911",
    "figure": "figures/src/fig_hisim_trajectories.tikz (tech report LaTeX source)",
    "tex": "sections/cases/case_hisim.tex (tech report LaTeX source)",
    "upstream_paper": "Mou et al., Unveiling the Truth and Facilitating Change (ACL 2024 Findings)",
}

# ── digitized series (14 rounds, min-max normalized to [0,1]) ──────────────────────
# Point-for-point identical to the \addplot coordinates in the tech report's figure source; with --tikz they are read back and
# checked, so changing either side raises an error.
SERIES = {
    "metoo": {
        "label_zh": "MeToo", "label_en": "MeToo",
        "sim": [0.387, 0.348, 1.000, 0.619, 0.619, 0.608, 0.354, 0.287, 0.171, 0.000, 0.166, 0.641, 0.624, 0.663],
        "gt":  [0.279, 0.254, 0.625, 1.000, 0.854, 0.667, 0.440, 0.309, 0.000, 0.121, 0.200, 0.217, 0.615, 0.637],
        "events": [(0, 2, "触发新闻：Moore 案 / 金球奖颁奖礼")],
        "paper": {"corr_best_hybrid": 0.724, "hybrid_model": "relative agreement (RA)",
                  "dbias_best_hybrid": 0.008, "corr_best_abm": 0.509, "dbias_best_abm": 0.019},
        "micro": {"stance_acc": 0.968, "stance_f1": 0.340, "content_acc": 0.701,
                  "content_sim": 0.806, "behavior_acc": 0.731, "behavior_f1": 0.521},
    },
    "roe": {
        "label_zh": "Roe v. Wade 推翻", "label_en": "Roe v. Wade overturn",
        "sim": [0.000, 0.095, 0.121, 0.145, 0.256, 0.553, 0.456, 0.628, 0.648, 0.568, 0.558, 0.771, 1.000, 0.982],
        "gt":  [0.000, 0.221, 0.208, 0.093, 0.328, 0.347, 0.449, 0.372, 0.405, 0.217, 0.243, 0.325, 0.561, 1.000],
        "events": [(0, 0, "触发事件：最高法院推翻 Roe v. Wade"),
                   (10, 11, "后续新闻：华盛顿特区抗议与逮捕")],
        "paper": {"corr_best_hybrid": 0.758, "hybrid_model": "Lorenz",
                  "dbias_best_hybrid": 0.009, "corr_best_abm": 0.475, "dbias_best_abm": 0.033},
        "micro": {"stance_acc": 0.943, "stance_f1": 0.336, "content_acc": 0.642,
                  "content_sim": 0.809, "behavior_acc": 0.667, "behavior_f1": 0.469},
    },
    "blm": {
        "label_zh": "Black Lives Matter", "label_en": "Black Lives Matter",
        "sim": [0.321, 0.000, 0.538, 0.462, 0.154, 0.090, 1.000, 0.731, 0.731, 0.218, 0.667, 0.897, 0.269, 0.218],
        "gt":  [0.295, 0.332, 0.409, 0.151, 0.240, 0.505, 0.286, 0.422, 0.425, 0.369, 0.622, 1.000, 0.717, 0.000],
        "events": [(0, 0, "触发事件：Floyd 之死"), (2, 2, "谋杀指控成立"), (6, 6, "锁喉禁令"),
                   (8, 8, "全国性抗议"), (11, 11, "市议会表态支持")],
        "paper": {"corr_best_hybrid": 0.605, "hybrid_model": "relative agreement (RA)",
                  "dbias_best_hybrid": 0.009, "corr_best_abm": 0.393, "dbias_best_abm": 0.040},
        "micro": {"stance_acc": 0.899, "stance_f1": 0.374, "content_acc": 0.735,
                  "content_sim": 0.841, "behavior_acc": 0.780, "behavior_f1": 0.576},
    },
}


def load_scenario(scenario: str) -> dict:
    """The scenario's series. The tracked techreport_case.json is authoritative for the
    scenario it records; SERIES must agree with it (a drift on either side is an error)."""
    s = dict(SERIES[scenario])
    if CASE_JSON.is_file():
        case = json.loads(CASE_JSON.read_text(encoding="utf-8"))
        if case.get("scenario") == scenario:
            tracked = {
                "sim": case["series"]["sim"], "gt": case["series"]["gt"],
                "events": [tuple(e) for e in case["events"]],
                "paper": case["paper_metrics"], "micro": case["micro_metrics"],
            }
            drift = [k for k, v in tracked.items() if v != s[k]]
            if drift:
                raise SystemExit(f"{CASE_JSON.name} and SERIES[{scenario!r}] disagree on {drift}")
            s.update(tracked)
            print(f"  ✓ read {CASE_JSON.relative_to(REPO_ROOT)} (matches the embedded series)")
    return s


def verify_against_tikz(s: dict, tikz: pathlib.Path) -> None:
    """Read back the tech report's tikz and confirm the coordinates copied above match exactly (for maintainers; needs the report's LaTeX source).

    This is not a formality: if either side changes and the other does not follow, the numbers shown in the gallery would no longer
    match the tech report — and the whole value of this case is that it "matches the real data".
    """
    if not tikz.is_file():
        raise SystemExit(f"tikz not found: {tikz}")
    flat = " ".join(tikz.read_text(encoding="utf-8").split())
    for key in ("sim", "gt"):
        missing = [f"({i},{v:.3f})" for i, v in enumerate(s[key]) if f"({i},{v:.3f})" not in flat]
        if missing:
            raise SystemExit(f"tikz cross-check failed for {key}: {missing[:4]} not in the figure source")
    print(f"  ✓ tikz cross-check: all {len(s['sim'])*2} coordinates match the tech report figure")


def pearson(xs, ys) -> float:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs) ** 0.5
    dy = sum((b - my) ** 2 for b in ys) ** 0.5
    return cov / (dx * dy)


def w(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("  wrote", path.relative_to(REPO_ROOT))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenario", nargs="?", default="roe", choices=sorted(SERIES))
    ap.add_argument("--tikz", type=pathlib.Path, default=None,
                    help="maintainers: the report's fig_hisim_trajectories.tikz to cross-check against")
    args = ap.parse_args(argv)
    scenario = args.scenario.lower()

    s = load_scenario(scenario)
    print(f"scenario = {scenario} ({s['label_en']})")
    if args.tikz is not None:
        verify_against_tikz(s, args.tikz)

    sim, gt = s["sim"], s["gt"]
    n = len(sim)
    r_digitized = pearson(sim, gt)
    mae = statistics.fmean(abs(a - b) for a, b in zip(sim, gt))
    # round-over-round direction hits: trajectory evaluation is about shape, and whether each round moves in the same direction is the plainest shape metric
    hits = sum(1 for i in range(1, n) if (sim[i] - sim[i-1] > 0) == (gt[i] - gt[i-1] > 0))

    ev_by_step = {}
    for a, b, note in s["events"]:
        for i in range(a, b + 1):
            ev_by_step[i] = note

    rows = []
    for i in range(n):
        run_r = pearson(sim[:i+1], gt[:i+1]) if i >= 2 else None
        rows.append({"step": i, "sim_sentiment": round(sim[i], 3), "gt_sentiment": round(gt[i], 3),
                     "abs_gap": round(abs(sim[i] - gt[i]), 3),
                     "cum_corr": round(run_r, 3) if run_r is not None else None,
                     "news_event": 1 if i in ev_by_step else 0})

    w(HERE / "trajectory" / "metrics_history.json", {
        "study_id": STUDY_ID, "rows": rows,
        "schema_columns": ["sim_sentiment", "gt_sentiment", "abs_gap", "cum_corr", "news_event"],
        "final_metrics": {"sim_sentiment": rows[-1]["sim_sentiment"], "gt_sentiment": rows[-1]["gt_sentiment"],
                          "abs_gap": rows[-1]["abs_gap"], "cum_corr": rows[-1]["cum_corr"]},
    })

    import duckdb
    db = HERE / "trajectory" / "study.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    con.execute("create table metrics(step BIGINT, sim_sentiment DOUBLE, gt_sentiment DOUBLE, "
                "abs_gap DOUBLE, cum_corr DOUBLE, news_event BIGINT, events VARCHAR)")
    con.executemany("insert into metrics values (?,?,?,?,?,?,?)",
                    [(r["step"], r["sim_sentiment"], r["gt_sentiment"], r["abs_gap"],
                      r["cum_corr"], r["news_event"], ev_by_step.get(r["step"])) for r in rows])
    con.execute("create table events(step INTEGER, note VARCHAR)")
    con.executemany("insert into events values (?,?)", sorted(ev_by_step.items()))
    # panel: the paper only publishes the aggregate trajectory, no per-person series — an empty table instead of made-up rows
    con.execute("create table panel(agent_id VARCHAR, step INTEGER, state JSON, "
                "action_kind VARCHAR, action_payload JSON)")
    con.close()
    print("  wrote", db.relative_to(REPO_ROOT), f"({len(rows)} metric rows, {len(ev_by_step)} event steps)")

    w(CASE_JSON, {
        "scenario": scenario, "label": s["label_en"],
        "source": dict(SOURCE),
        "series": {"sim": sim, "gt": gt}, "events": [list(e) for e in s["events"]],
        "paper_metrics": s["paper"], "micro_metrics": s["micro"],
        "recomputed_on_digitized": {"pearson": round(r_digitized, 4), "mae": round(mae, 4),
                                    "direction_hits": hits, "direction_total": n - 1},
        "all_scenarios": {k: {"corr_best_hybrid": v["paper"]["corr_best_hybrid"],
                              "corr_best_abm": v["paper"]["corr_best_abm"]} for k, v in SERIES.items()},
    })
    print(f"\n  digitized: Pearson {r_digitized:.4f} / MAE {mae:.4f} / direction {hits}/{n-1}"
          f"   |   paper: Corr {s['paper']['corr_best_hybrid']} (hybrid w/ {s['paper']['hybrid_model']})"
          f" vs {s['paper']['corr_best_abm']} (best pure-ABM)")


if __name__ == "__main__":
    main()
