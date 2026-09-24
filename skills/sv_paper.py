"""Figure helpers for /sv-paper (and any stage that draws ad-hoc visualizations).

The hard problem these solve: papers citing figures that don't exist. Two causes
seen in the wild — (a) the agent "remembers" a figure from an earlier version's
report (version-iterate wipes live ``reports/``; the old figure lives only in the
``versions/vN`` snapshot and depicts THAT version's data), (b) the agent invents
a figure name while writing. Both are caught by :func:`missing_figures`, and
:func:`mpl_setup` + :func:`fig_dir` make drawing the missing figure from the
CURRENT trajectory a one-screen job.

Figure resolution order everywhere (dashboard, pandoc export, this module):
``reports/figures/<name>`` (sv-report's set) then ``paper/figures/<name>``
(paper-stage additions).
"""
from __future__ import annotations

import re
from pathlib import Path

FIG_RE = re.compile(r"!\[[^\]]*\]\(\s*(?:\./)?figures/([^)\s]+)\s*\)")


def fig_dir(study_dir: str | Path) -> Path:
    """paper/figures/ (created) — where paper-stage visualizations land."""
    d = Path(study_dir) / "paper" / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def referenced_figures(study_dir: str | Path) -> list[str]:
    """Figure names cited as ``![...](figures/<name>)`` in paper/paper.md."""
    p = Path(study_dir) / "paper" / "paper.md"
    if not p.exists():
        return []
    return list(dict.fromkeys(FIG_RE.findall(p.read_text())))


def available_figures(study_dir: str | Path) -> dict[str, Path]:
    """name → path across reports/figures and paper/figures (reports wins)."""
    out: dict[str, Path] = {}
    for base in (Path(study_dir) / "paper" / "figures",
                 Path(study_dir) / "reports" / "figures"):
        if base.is_dir():
            for f in base.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    out[f.name] = f
    return out

def missing_figures(study_dir: str | Path) -> list[str]:
    """Cited-but-absent figure names. THE final gate for /sv-paper: must be []."""
    have = available_figures(study_dir)
    return [n for n in referenced_figures(study_dir) if n not in have]


def mpl_setup(figsize: tuple = (9, 5), dpi: int = 130):
    """Matplotlib configured for this stack: headless backend, CJK-safe fonts,
    quiet grid. Returns ``plt``. Typical use::

        from skills import sv_paper
        plt = sv_paper.mpl_setup()
        import duckdb
        con = duckdb.connect("studies/<id>/trajectory/study.duckdb", read_only=True)
        rows = con.execute("SELECT step, mean_x FROM metrics ORDER BY step").fetchall()
        plt.plot([r[0] for r in rows], [r[1] for r in rows], marker="o")
        plt.title("..."); plt.xlabel("step"); plt.tight_layout()
        plt.savefig(sv_paper.fig_dir("studies/<id>") / "my_figure.png")
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams.update({
        "font.sans-serif": ["Noto Sans CJK SC", "Noto Sans CJK sc", "WenQuanYi Zen Hei",
                            "PingFang SC", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.figsize": figsize, "figure.dpi": dpi, "savefig.dpi": dpi,
        "axes.grid": True, "grid.alpha": 0.3, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False,
        "font.size": 11,
    })
    return plt


def check(study_dir: str | Path) -> bool:
    """Print the citation↔existence audit; True = clean (safe to finish)."""
    refs = referenced_figures(study_dir)
    have = available_figures(study_dir)
    miss = [n for n in refs if n not in have]
    for n in refs:
        print(("OK   " if n in have else "MISS ") + n
              + (f"  ({have[n].parent.relative_to(Path(study_dir))})" if n in have else ""))
    if miss:
        print(f"→ {len(miss)} referenced figure(s) DO NOT EXIST — draw them from the "
              "current trajectory (sv_paper.mpl_setup) or remove the references.")
    return not miss
