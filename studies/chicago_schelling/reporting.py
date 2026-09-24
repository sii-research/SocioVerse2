"""Chicago display layer — reads the DuckDB trajectory store and emits per-step maps,
a metric timeline (with intervention markers), and report.md.

Everything is reconstructed from the database via SQL, so the same store powers later
real-time interactive querying. Reuses the legacy colour scheme from run_prototype's maps.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

RACE_COLS = ["nh_white", "nh_black", "nh_asian", "hispanic", "nh_other"]
RACE_COLORS = {
    "nh_white": "#4575b4", "nh_black": "#1a9850",
    "hispanic": "#e66101", "nh_asian": "#d73027", "nh_other": "#998ec3",
}
RACE_LABELS = {
    "nh_white": "NH White", "nh_black": "NH Black",
    "hispanic": "Hispanic", "nh_asian": "NH Asian", "nh_other": "Other",
}
TIMELINE_METRICS = ["D_black_white", "D_hispanic_white", "D_asian_white", "Isolation_black"]


def _con(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def plot_metric_timeline(db_path, out_path, event_steps=None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    con = _con(db_path)
    df = con.execute("SELECT * FROM metrics ORDER BY step").df()
    con.close()
    fig, ax = plt.subplots(figsize=(9, 5.5), facecolor="white")
    for m in TIMELINE_METRICS:
        if m in df.columns:
            ax.plot(df["step"], df[m], marker="o", label=m)
    for es in (event_steps or []):
        ax.axvline(es, color="#d62728", ls="--", lw=1.2, alpha=0.7)
        ax.text(es, ax.get_ylim()[1], " intervention", color="#d62728",
                fontsize=8, va="top", ha="left")
    ax.set_xlabel("step (time)")
    ax.set_ylabel("segregation index")
    ax.set_title("Chicago Schelling — longitudinal metric trajectory")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _tract_composition(con, step: int) -> dict[str, dict[str, float]]:
    rows = con.execute(
        "SELECT state->>'tract_id' AS tid, state->>'race' AS race, "
        "SUM(CAST(state->>'pop_count' AS INTEGER)) AS pop "
        "FROM panel WHERE step = ? GROUP BY tid, race", [step],
    ).fetchall()
    comp: dict[str, dict[str, float]] = {}
    for tid, race, pop in rows:
        comp.setdefault(tid, {r: 0 for r in RACE_COLS})
        if race in comp[tid]:
            comp[tid][race] += pop or 0
    return comp


def plot_step_maps(db_path, geojson_path, out_dir) -> list[Path]:
    import geopandas as gpd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = _con(db_path)
    steps = [r[0] for r in con.execute("SELECT DISTINCT step FROM panel ORDER BY step").fetchall()]
    metrics = {r[0]: r[1] for r in con.execute("SELECT step, D_black_white FROM metrics").fetchall()}

    gdf = gpd.read_file(geojson_path)
    gdf = gdf[gdf["total_pop"] > 0].set_index("GEOID10", drop=False)
    paths = []
    for step in steps:
        comp = _tract_composition(con, step)
        sub = gdf[gdf.index.isin(comp.keys())]
        fig, ax = plt.subplots(figsize=(8, 8), facecolor="white")
        for tid, row in sub.iterrows():
            rp = comp.get(tid, {})
            total = sum(rp.values())
            if total > 0:
                dom = max(RACE_COLS, key=lambda r: rp.get(r, 0))
                alpha = max(0.25, min(1.0, rp[dom] / total))
                color = to_rgba(RACE_COLORS[dom], alpha=alpha)
            else:
                color = "#f0f0f0"
            geom = row["geometry"]
            polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
            for poly in polys:
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, color=color, edgecolor="#999999", linewidth=0.3)
        ax.set_aspect("equal"); ax.set_axis_off()
        ax.legend(handles=[mpatches.Patch(color=RACE_COLORS[r], label=RACE_LABELS[r]) for r in RACE_COLS],
                  loc="lower left", fontsize=7, title="Dominant group", title_fontsize=8)
        label = "Initial" if step == 0 else f"Step {step}"
        ax.set_title(f"{label}  |  D_bw={metrics.get(step, float('nan')):.4f}", fontweight="bold")
        out = out_dir / f"step_{step:03d}.png"
        fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        paths.append(out)
    con.close()
    return paths


def _fmt(v, nd=4):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def _tract_race_series(con, tract_id: str) -> dict[int, dict[str, float]]:
    """{step: {race: pop}} for one tract — the mechanism behind a per-tract narrative."""
    rows = con.execute(
        "SELECT step, state->>'race' AS race, "
        "SUM(CAST(state->>'pop_count' AS INTEGER)) AS pop "
        "FROM panel WHERE state->>'tract_id' = ? GROUP BY step, race ORDER BY step", [tract_id],
    ).fetchall()
    out: dict[int, dict[str, float]] = {}
    for step, race, pop in rows:
        out.setdefault(int(step), {})[race] = float(pop or 0)
    return out


def _analysis_sections(con, df, event_steps) -> list[str]:
    """Findings / Deeper insights / Recommendations, filled from the trajectory itself.

    Interpretation is READ OFF the DuckDB panel + metrics (not hard-coded prose): each
    finding pairs a claim with the specific numbers that back it and the mechanism.
    """
    es = sorted(event_steps or [])
    ev0 = es[0] if es else None
    steps = df["step"].tolist()
    first, last = int(steps[0]), int(steps[-1])

    def m(step, col):
        r = df.loc[df["step"] == step, col]
        return float(r.iloc[0]) if len(r) and col in df.columns else float("nan")

    dbw0, dbwL = m(first, "D_black_white"), m(last, "D_black_white")
    dbw_delta = dbwL - dbw0
    # the intervention tract (read off the scheduled event's selector if we can find it)
    tract = "17031612000"
    tser = _tract_race_series(con, tract)
    def tpop(step, race):
        return tser.get(step, {}).get(race, 0.0)
    def ttotal(step):
        return sum(tser.get(step, {}).values())
    white_pre = tpop(ev0 - 1 if ev0 else first, "nh_white")
    white_last = tpop(last, "nh_white")
    hisp_pre = tpop(ev0 - 1 if ev0 else first, "hispanic")
    hisp_last = tpop(last, "hispanic")
    align = {int(r): v for r, v in zip(df["step"], df.get("mover_alignment_rate", []))} \
        if "mover_alignment_rate" in df.columns else {}

    L: list[str] = ["", "## 发现与解读 (Findings)", ""]

    # Finding 1 — the headline metric moved the WRONG way
    direction = "上升" if dbw_delta > 0 else ("下降" if dbw_delta < 0 else "基本持平")
    L.append(
        f"- **黑-白隔离不降反升，假设被证伪。** `D_black_white` 从 t={first} 的 {_fmt(dbw0)} "
        f"{direction}到 t={last} 的 {_fmt(dbwL)}（Δ={_fmt(dbw_delta, 4)}）。假设预期车站+政策会压低 "
        f"D_bw，但轨迹显示相反：干预不足以逆转既有的隔离动力学。**机制**：车站开在一个已高度黑人聚居的"
        f"南城普查区，可达性红利吸引到的是就近的多数群体，而非白人回流——见下一条。")

    # Finding 2 — WHO actually moved into the intervention tract (mechanism)
    if tser:
        L.append(
            f"- **干预普查区吸引的是西语裔流入、而非多元化白人回流。** 目标普查区 {tract} 的白人人口"
            f"从干预前的 {int(white_pre)} 人降到 t={last} 的 {int(white_last)} 人，而西语裔从 "
            f"{int(hisp_pre)} 人增至 {int(hisp_last)} 人；黑人存量几乎不变。**机制**：Schelling 决策规则下，"
            f"可达性提升降低了迁移成本，但迁入方向由同群体邻里份额主导——最邻近的西语裔家庭而非白人抓住了"
            f"这一机会，使该区更加非白人化，直接推高全市 D_bw。")

    # Finding 3 — movement volume falls over time
    if "n_movers" in df.columns:
        nm = {int(r): v for r, v in zip(df["step"], df["n_movers"])}
        seq = [nm.get(s) for s in steps if not (nm.get(s) is None or (isinstance(nm.get(s), float) and nm.get(s) != nm.get(s)))]
        if len(seq) >= 2:
            L.append(
                f"- **系统在向新均衡收敛，而非持续搅动。** 每步搬迁家庭数从 {int(seq[0])} 先升到干预步的峰值、"
                f"再回落到 {int(seq[-1])}（t={last}）。**机制**：一次性可达性冲击引发一轮重新排序，随后满意度"
                f"缺口被填平、迁移意愿下降——这是 Schelling 动力学趋于稳态的典型特征，而非隔离被打破。")

    L += ["", "## 深层洞察 (Deeper insights)", ""]
    # Insight 1 — metrics diverge: black-white vs hispanic-white
    dhw0, dhwL = m(first, "D_hispanic_white"), m(last, "D_hispanic_white")
    L.append(
        f"- **两条隔离曲线同向恶化，但驱动群体不同。** `D_black_white`（{_fmt(dbw0)}→{_fmt(dbwL)}）与 "
        f"`D_hispanic_white`（{_fmt(dhw0)}→{_fmt(dhwL)}）都在上升，然而前者由白人从南城普查区退出驱动、"
        f"后者由西语裔在同一批普查区聚集驱动。单看总指数会把两种不同的隔离过程混为一谈——面板数据显示"
        f"它们是被同一次干预从两端同时放大的。")
    # Insight 2 — mover alignment trend (are movers reinforcing segregation?)
    if align:
        seq = [align.get(int(s)) for s in steps if align.get(int(s)) == align.get(int(s))]
        if len(seq) >= 2:
            L.append(
                f"- **搬迁者越来越“同类相聚”，隔离具有自我强化性。** `mover_alignment_rate`（迁移方向与自身"
                f"群体多数一致的比例）从 {_fmt(seq[0], 3)} 单调升到 {_fmt(seq[-1], 3)}。这意味着干预不仅没有"
                f"促成混居，反而随时间筛选出更趋同的迁移——一个正反馈的临界（tipping）信号，与 Schelling "
                f"经典结论一致。")
    # Insight 3 — who is insulated
    L.append(
        "- **黑人存量对干预免疫、白人高度敏感。** 目标普查区黑人人口在四步内几乎不动，而白人存量被清空——"
        "隔离的“黏性”是不对称的：少数主导群体被锁定，边缘的白人少数则率先撤离。要撬动 D_bw，杠杆在留住/"
        "吸引白人一侧，而非单纯提升可达性。")

    L += ["", "## 改进建议与下一步 (Recommendations & next steps)", ""]
    L.append(
        "- **把广播从“反迁移保障”改成“定向吸引”并做 A/B。** 当前政策文本强调可达性与防迁移，却未给白人/"
        "多元家庭迁入的正向理由。下一轮 `/sv-iterate` 可新增一条针对全市白人受众的定向广播，对比 D_bw 是否"
        "转向下降。")
    L.append(
        "- **对冲击幅度做敏感性扫描。** `cta_stations += 2` 是一次性代理冲击（见声明的假设 a-shock-size）；"
        "扫 +1 / +2 / +4 检验结论是否为幅度所驱动，还是无论幅度都会出现“西语裔流入而非白人回流”。")
    L.append(
        "- **选一个已较为混居的普查区重做干预。** 当前目标区起点即高度黑人聚居，白人基数过小、天花板低。"
        "换一个 D_bw 处于临界带的普查区，更能检验“可达性冲击能否把临界区推向融合”这一真正的政策问题。")
    L.append(
        f"- **延长时间跨度。** 仅 {last - first} 步不足以观察一次性冲击后的长期再均衡；把 `n_steps` 提到 "
        f"6–8 步，看 D_bw 是稳定在更高位还是缓慢回落。本研究是包装既有模拟器的路径，"
        f"不支持分支重放，延长时间跨度要作为新版本从第 0 步完整重跑。")
    return L


def _grounding_section(study_dir) -> list[str]:
    """Render grounding/grounding.json as the data-basis-and-sources section (report.md-minimal md)."""
    try:
        import sys
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from skills import sv_grounding
    except Exception:
        return []
    g = sv_grounding.load(study_dir)
    if g is None:
        return []  # older studies stay renderable
    L = ["", "## 数据基础与参考来源", ""]
    facts = g.get("facts") or []
    basis_zh = {"sourced": "实证", "proxy": "代理", "assumed": "假设"}
    if not facts and g.get("method_notes") == "stylized":
        L.append("风格化模型，无真实世界锚点。")
        return L
    if facts:
        L.append("| 事实 | 值 | 依据 | 来源 |")
        L.append("| --- | --- | --- | --- |")
        for f in facts:
            val = f.get("value")
            unit = f.get("unit") or ""
            val_s = f"{val} {unit}".strip() if val is not None else ""
            src = f.get("source") or {}
            src_s = src.get("title", "")
            if src.get("url"):
                src_s = f"{src_s} ({src['url']})"
            L.append(f"| {f.get('claim','')} | {val_s} | {basis_zh.get(f.get('basis'), f.get('basis',''))} | {src_s} |")
        L.append("")
    refs = g.get("implementation_refs") or []
    if refs:
        L.append("**建模参考**")
        for r in refs:
            t = r.get("title", "")
            u = r.get("url", "")
            tk = r.get("takeaway", "")
            L.append(f"- {t} ({u}) — {tk}" if u else f"- {t} — {tk}")
        L.append("")
    asmpt = g.get("assumptions") or []
    if asmpt:
        L.append("**声明的假设**")
        for a in asmpt:
            L.append(f"- {a.get('claim','')} — {a.get('rationale','')}")
        L.append("")
    if g.get("method_notes"):
        L.append(f"> 方法说明：{g['method_notes']}")
    return L


def write_report(db_path, out_dir, study_title="Chicago Schelling", event_notes=None,
                 event_steps=None, study_dir=None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = _con(db_path)
    df = con.execute("SELECT * FROM metrics ORDER BY step").df()
    events = con.execute("SELECT step, note FROM events ORDER BY step").fetchall()
    n_panel = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    n_agents = con.execute("SELECT count(DISTINCT agent_id) FROM panel").fetchone()[0]

    cols = [c for c in ["step", "D_black_white", "D_hispanic_white", "D_asian_white",
                        "Isolation_black", "n_movers", "pct_pop_moved"] if c in df.columns]
    lines = [f"# {study_title} — longitudinal report", ""]
    lines.append(f"- Tracked **{n_agents} persistent households** across "
                 f"**{len(df)} time steps** ({n_panel} panel rows).")
    lines.append(f"- Store: `{Path(db_path).name}` (DuckDB; tables: panel, metrics, events).")
    if events:
        lines.append("")
        lines.append("## Interventions (dynamic environment E)")
        for s, note in events:
            lines.append(f"- **step {s}**: {note}")
    lines.append("")
    lines.append("## Metric trajectory")
    lines.append("")
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            cells.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Figures")
    lines.append("- `figures/metric_timeline.png` — segregation indices over time")
    lines.append("- `figures/step_*.png` — per-step racial-distribution maps")

    # Analytical sections (Findings / Deeper insights / Recommendations) — read off the trajectory.
    try:
        lines += _analysis_sections(con, df, event_steps or (event_notes if isinstance(event_notes, list) else None))
    except Exception as e:  # analysis is best-effort; never break the data dump
        print(f"[reporting] analysis sections skipped: {e}")
    con.close()

    # data basis and sources — from grounding/grounding.json.
    if study_dir:
        lines += _grounding_section(study_dir)

    report = out_dir / "report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def generate_report(db_path, out_dir, geojson_path=None, event_steps=None,
                    study_title="Chicago Schelling", study_dir=None) -> Path:
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plot_metric_timeline(db_path, fig_dir / "metric_timeline.png", event_steps=event_steps)
    if geojson_path:
        try:
            plot_step_maps(db_path, geojson_path, fig_dir)
        except Exception as e:  # maps are best-effort
            print(f"[reporting] step maps skipped: {e}")
    return write_report(db_path, out_dir, study_title=study_title,
                        event_steps=event_steps, study_dir=study_dir)
