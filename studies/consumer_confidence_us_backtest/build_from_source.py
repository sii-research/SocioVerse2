"""Rebuild this study's artifacts from the ConsumerSim published outputs.

This study is a **backtest import**, not an in-workbench run: every number below is
read out of ConsumerSim's published site data (`data/consumersim_site_data.csv`), which
is what the public ConsumerSim dashboard renders. Nothing here is authored by hand.

By default the CSV is the pinned 2026-07-03 publish the shipped artifacts were built
from (SNAPSHOT_URL below), so a plain run regenerates the tracked files byte-for-byte
and leaves `git status` clean:

    python studies/consumer_confidence_us_backtest/build_from_source.py

The public CSV is re-published as ConsumerSim updates, and its latest months can be
revised. `--latest` pulls the current CSV from the public ConsumerSim site
(https://sii-research.github.io/ConsumerSim/data/consumersim_site_data.csv) instead;
its numbers can differ from the shipped report and figures. `--source` builds from any
other copy: a file path, an http(s) URL, or a ConsumerSim checkout directory (its
`data/consumersim_site_data.csv` is used, e.g. `--source "$SV_CONSUMERSIM_ROOT"`).

Two windows live in that source, and they are deliberately kept apart:

* the **aggregate backtest** — monthly ConsumerSim forecast vs the University of
  Michigan Index of Consumer Sentiment as later published. 11 clean month-pairs,
  2025-07 → 2026-05. This is the study's metric series.
* the **respondent panel** — 18 named synthetic respondents, monthly simulated
  response, 2026-01 → 2026-06. This is the study's panel.

The panel is on the respondent display scale and does **not** average to the
headline index (check it: 2026-01 respondents average ≈52.4 while the headline
forecast is 57.26). So the panel is stored as respondent state and never summed
into a metric. The scored window is the 11 aggregate months; the panel's 2026-06
row falls outside it and is dropped rather than half-used.

Usage:  python studies/consumer_confidence_us_backtest/build_from_source.py [--latest | --source PATH_OR_URL]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

STUDY_ID = "consumer_confidence_us_backtest"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Public ConsumerSim site data, re-published as ConsumerSim updates (--latest).
SOURCE_URL = "https://sii-research.github.io/ConsumerSim/data/consumersim_site_data.csv"
SOURCE_RELPATH = Path("data") / "consumersim_site_data.csv"   # inside a ConsumerSim checkout
# The exact publish the shipped artifacts were built from (as_of 2026-07-03): the default source.
SNAPSHOT_AS_OF = "2026-07-03"
SNAPSHOT_URL = ("https://raw.githubusercontent.com/RunRiotComeOn/"
                "ConsumerSim-Consumer-Confidence-Forecast/"
                "f018181eb105e6845993a5ba1f2ab2a5287608bd/data/consumersim_site_data.csv")

# The 11 months in the scoring window (the stretch of the source series where both the forecast and the later actual exist).
# The site-generation script has rewritten the 12th series point as the "next forecast to be published" and cleared its actual —
# that row stays out of this study; one month short beats a guess.
MONTH_LABELS = ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25",
                "Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26"]
MONTH_ISO = {"Jul-25": "2025-07", "Aug-25": "2025-08", "Sep-25": "2025-09",
             "Oct-25": "2025-10", "Nov-25": "2025-11", "Dec-25": "2025-12",
             "Jan-26": "2026-01", "Feb-26": "2026-02", "Mar-26": "2026-03",
             "Apr-26": "2026-04", "May-26": "2026-05"}


def num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def resolve_source(cli_source: str | None = None, latest: bool = False) -> str:
    """--source wins (a file, an http(s) URL, or a ConsumerSim checkout directory), then
    --latest (the live public CSV); the default is the pinned snapshot the shipped artifacts
    were built from, so a plain run is reproducible."""
    if cli_source:
        if not is_url(cli_source) and Path(cli_source).expanduser().is_dir():
            return str(Path(cli_source).expanduser() / SOURCE_RELPATH)
        return cli_source
    return SOURCE_URL if latest else SNAPSHOT_URL


def source_label(source: str) -> str:
    """How the source is recorded in backtest_source.json: URLs verbatim, local files
    relative to the repo root (so no machine-specific absolute path lands in the study)."""
    if is_url(source):
        return source
    try:
        rel = Path(os.path.relpath(Path(source).expanduser().resolve(), REPO_ROOT)).as_posix()
    except ValueError:            # e.g. a different drive on Windows
        rel = None
    # keep in-repo and sibling-checkout paths; anything further away is reduced to its name
    return rel if rel and not rel.startswith("../../") else Path(source).name


def read_source_text(source: str) -> str:
    if is_url(source):
        req = urllib.request.Request(source, headers={"User-Agent": "SocioVerse2-backtest-import"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SystemExit(f"Could not download ConsumerSim source data from {source}: {exc}\n"
                             "Pass --source with a local copy of consumersim_site_data.csv "
                             "or a ConsumerSim checkout directory.")
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            raise SystemExit(f"ConsumerSim source data not found: {path}\n"
                             "Pass --source with a file path, an http(s) URL or a "
                             "ConsumerSim checkout directory.")
        data = path.read_bytes()
    return data.decode("utf-8-sig")


def load_rows(source: str) -> list[dict]:
    return [dict(r) for r in csv.DictReader(io.StringIO(read_source_text(source), newline=""))]


def series(rows) -> list[dict]:
    """Aggregate backtest points, decoded exactly the way the ConsumerSim site decodes them.

    The CSV is a flattened export whose columns are reused per record_type, so the
    mapping is NOT the column names: for a series row the site reads
    `forecast = forecast ?? actual` and `actual = forecast ? actual : error`
    (see the upstream app.js). Rows 1-11 carry no `forecast`, hence
    forecast←`actual` column and actual←`error` column. Decoding by column name
    instead silently swaps the two curves.
    """
    out = []
    for r in sorted((x for x in rows if x["record_type"] == "series" and x["region"] == "us"),
                    key=lambda x: int(x["sort_order"])):
        label = r["week_label"] or r["period"]
        if label not in MONTH_ISO:
            continue
        fc = num(r["forecast"]) if num(r["forecast"]) is not None else num(r["actual"])
        ac = num(r["actual"]) if num(r["forecast"]) is not None else num(r["error"])
        if fc is None or ac is None:
            continue
        out.append({"label": label, "month": MONTH_ISO[label], "forecast": fc, "actual": ac})
    if [x["label"] for x in out] != MONTH_LABELS:
        raise SystemExit(f"unexpected series window: {[x['label'] for x in out]}")
    return out


def profiles(rows) -> list[dict]:
    out = []
    for r in sorted((x for x in rows if x["record_type"] == "agent_profile" and x["region"] == "us"),
                    key=lambda x: int(x["sort_order"])):
        out.append({
            "agent_id": r["key"], "name": r["label"], "state": r["market"],
            "city": r["week_label"], "age": int(num(r["cutoff_day"])),
            "role": r["target"], "education": r["method"], "income": r["family"],
            "employment": r["status"], "household": r["prior_period"],
            "stance": r["signal"], "rationale": r["interpretation"], "note": r["note"],
        })
    return out


def panel_values(rows) -> dict[tuple[str, str], float]:
    out = {}
    for r in rows:
        if r["record_type"] != "agent_monthly_prediction" or r["region"] != "us":
            continue
        v = num(r["value"]) if num(r["value"]) is not None else num(r["forecast"])
        if v is not None and r["period"] in MONTH_ISO:
            out[(r["key"], MONTH_ISO[r["period"]])] = v
    return out


def leaderboard(rows) -> list[dict]:
    out = []
    for r in sorted((x for x in rows if x["record_type"] == "leaderboard" and x["region"] == "us"),
                    key=lambda x: int(x["rank"] or 99)):
        out.append({"rank": int(r["rank"]), "method": r["label"], "family": r["period"],
                    "months": int(num(r["months"])), "mae": num(r["mae"]),
                    "rmse": num(r["rmse"]), "pearson": num(r["pearson"])})
    return out


def pearson(xs, ys) -> float:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs) ** 0.5
    dy = sum((b - my) ** 2 for b in ys) ** 0.5
    return cov / (dx * dy)


def w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(REPO_ROOT))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--latest", action="store_true",
                     help=f"build from the current public CSV ({SOURCE_URL}); ConsumerSim "
                          "revises its latest months, so the numbers can differ from the "
                          "shipped report")
    src.add_argument("--source", default=None,
                     help="consumersim_site_data.csv as a local path, an http(s) URL, or a "
                          f"ConsumerSim checkout directory (uses {SOURCE_RELPATH.as_posix()})")
    args = ap.parse_args(argv)
    source = resolve_source(args.source, latest=args.latest)
    print("source", source)
    rows = load_rows(source)
    as_of = rows[0].get("as_of", "") if rows else ""
    if as_of != SNAPSHOT_AS_OF:
        print(f"note: this source was published as_of {as_of or 'unknown'}; the shipped artifacts "
              f"were built from the {SNAPSHOT_AS_OF} publish, and ConsumerSim revises its latest "
              f"months, so the regenerated series can differ from the shipped report and figures. "
              f"Run without --latest/--source to rebuild them byte-for-byte.", file=sys.stderr)
    ser, profs, pan, board = series(rows), profiles(rows), panel_values(rows), leaderboard(rows)
    summary = next(x for x in rows if x["record_type"] == "region_summary" and x["region"] == "us")

    # ── metrics ────────────────────────────────────────────────────────────
    steps, run_err = [], []
    for i, p in enumerate(ser, start=1):
        err = abs(p["forecast"] - p["actual"])
        run_err.append(err)
        panel_n = sum(1 for a in profs if (a["agent_id"], p["month"]) in pan)
        steps.append({
            "step": i, "month": p["month"],
            "forecast_ics": round(p["forecast"], 2), "actual_ics": round(p["actual"], 2),
            "abs_error": round(err, 2),
            "cum_mae": round(statistics.fmean(run_err), 3),
            "panel_size": panel_n,
        })
    mae = statistics.fmean(run_err)
    r = pearson([p["forecast"] for p in ser], [p["actual"] for p in ser])
    rmse = (statistics.fmean(e ** 2 for e in run_err)) ** 0.5
    hits = sum(1 for a, b in zip(ser, ser[1:])
               if (b["forecast"] - a["forecast"] > 0) == (b["actual"] - a["actual"] > 0))
    print(f"window MAE={mae:.3f} RMSE={rmse:.3f} pearson={r:.4f} direction={hits}/{len(ser)-1}")

    # ── artifacts ──────────────────────────────────────────────────────────
    w(HERE / "trajectory" / "metrics_history.json", {
        "study_id": STUDY_ID, "rows": steps,
        "schema_columns": ["forecast_ics", "actual_ics", "abs_error", "cum_mae", "panel_size"],
        "final_metrics": {"forecast_ics": steps[-1]["forecast_ics"],
                          "actual_ics": steps[-1]["actual_ics"],
                          "abs_error": steps[-1]["abs_error"],
                          "cum_mae": steps[-1]["cum_mae"]},
    })
    w(HERE / "population" / "population.json", {
        "study_id": STUDY_ID,
        "personas": [{"agent_id": a["agent_id"], "attributes": {k: v for k, v in a.items()
                                                                if k != "agent_id"}} for a in profs],
        "interaction": {"kind": "none", "edges": None, "adjacency_ref": None},
        "propagation": "independent",
        "provider_ref": "consumersim.us_respondent_panel",
        "provider_args": {"region": "us", "n_agents": len(profs),
                          "source": "ConsumerSim published respondent panel"},
        "materialized_count": len(profs),
    })

    roster, panel_rows = [], []
    for a in profs:
        first = next((s for s in steps if (a["agent_id"], s["month"]) in pan), None)
        base = {k: v for k, v in a.items() if k != "agent_id"}
        roster.append({"agent_id": a["agent_id"], "step": 0,
                       "state": dict(base, respondent_score=pan.get((a["agent_id"], first["month"]))
                                     if first else None),
                       "action_kind": None, "action_payload": {}})
        for s in steps:
            v = pan.get((a["agent_id"], s["month"]))
            if v is None:
                continue          # the panel covers only the last 5 months of the scoring window; missing months are neither zero-filled nor extrapolated
            panel_rows.append({
                "agent_id": a["agent_id"], "step": s["step"],
                "state": dict(base, month=s["month"], respondent_score=v),
                "action_kind": "survey_response",
                "action_payload": {"month": s["month"], "respondent_score": v,
                                   "scale": "respondent display scale (not summable to the headline index)"},
            })
    rp = HERE / "population" / "roster.jsonl"
    rp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in roster), encoding="utf-8")
    print("wrote", rp.relative_to(REPO_ROOT), f"({len(roster)} agents)")

    # ── duckdb store ───────────────────────────────────────────────────────
    import duckdb
    db = HERE / "trajectory" / "study.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    con.execute("create table metrics(step BIGINT, forecast_ics DOUBLE, actual_ics DOUBLE, "
                "abs_error DOUBLE, cum_mae DOUBLE, panel_size BIGINT, events VARCHAR)")
    con.executemany("insert into metrics values (?,?,?,?,?,?,?)",
                    [(s["step"], s["forecast_ics"], s["actual_ics"], s["abs_error"],
                      s["cum_mae"], s["panel_size"], None) for s in steps])
    con.execute("create table panel(agent_id VARCHAR, step INTEGER, state JSON, "
                "action_kind VARCHAR, action_payload JSON)")
    con.executemany("insert into panel values (?,?,?,?,?)",
                    [(p["agent_id"], p["step"], json.dumps(p["state"], ensure_ascii=False),
                      p["action_kind"], json.dumps(p["action_payload"], ensure_ascii=False))
                     for p in roster + panel_rows])
    con.execute("create table events(step INTEGER, note VARCHAR)")
    con.executemany("insert into events values (?,?)",
                    [(s["step"], f"{s['month']} 调查窗关闭：ICS 实测公布 {s['actual_ics']}") for s in steps])
    con.close()
    print("wrote", db.relative_to(REPO_ROOT), f"({len(roster) + len(panel_rows)} panel rows)")

    # an intermediate product reused by report/grounding (not shown on the dashboard; it only makes the report's numbers traceable)
    w(HERE / "environment" / "sources" / "backtest_source.json", {
        "source_csv": source_label(source), "generated_from_record_types":
            ["series", "agent_profile", "agent_monthly_prediction", "leaderboard", "region_summary"],
        "target_index": summary["target"], "backtest_window": summary["window"],
        "method": summary["method"],
        "published_stats": {"months": int(num(summary["months"])), "mae": num(summary["mae"]),
                            "rmse": num(summary["rmse"]), "pearson": num(summary["pearson"])},
        "study_window_stats": {"months": len(ser), "mae": round(mae, 3), "rmse": round(rmse, 3),
                               "pearson": round(r, 4), "direction_hits": hits,
                               "direction_total": len(ser) - 1},
        "leaderboard": board,
        "series": ser,
    })

    # ── contract check ─────────────────────────────────────────────────────
    # The study's handoff artifacts must satisfy the same schemas as any other study, so a fork,
    # a template copy or /sv-iterate's verify-and-skip can load them. environment.json is not
    # written here (its layers describe ConsumerSim's information sources, not CSV rows), but
    # it is checked with the files this script writes.
    from socioverse.schemas import EnvironmentBundle, PopulationBundle
    from socioverse.validation import HandoffError, validate_handoff

    for rel, schema in (("population/population.json", PopulationBundle),
                        ("environment/environment.json", EnvironmentBundle)):
        try:
            validate_handoff(HERE / rel, schema)
        except HandoffError as exc:
            raise SystemExit(str(exc))
    print("validated population.json and environment.json")


if __name__ == "__main__":
    main()
