"""consumer_confidence_us_backtest: the import defaults to the pinned publish it was built from.

Offline: no download happens here. A plain `build_from_source.py` run must rebuild the
tracked files byte-for-byte, so the tracked source record has to name the default source,
and the stats it records have to follow from the series it records.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1] / "studies" / "consumer_confidence_us_backtest"


def _builder():
    spec = importlib.util.spec_from_file_location("cc_backtest_build", STUDY / "build_from_source.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_source_is_the_pinned_snapshot(tmp_path, monkeypatch):
    b = _builder()
    monkeypatch.setenv("SV_CONSUMERSIM_ROOT", str(tmp_path))      # never picked up implicitly
    assert b.resolve_source() == b.SNAPSHOT_URL
    assert b.resolve_source(latest=True) == b.SOURCE_URL
    assert b.resolve_source("https://example.org/x.csv", latest=True) == "https://example.org/x.csv"
    # a ConsumerSim checkout directory resolves to its site-data file
    assert b.resolve_source(str(tmp_path)) == str(tmp_path / "data" / "consumersim_site_data.csv")
    assert b.source_label(b.SNAPSHOT_URL) == b.SNAPSHOT_URL


def test_tracked_source_record_matches_a_default_rebuild():
    b = _builder()
    src = json.loads((STUDY / "environment" / "sources" / "backtest_source.json").read_text("utf-8"))
    assert src["source_csv"] == b.SNAPSHOT_URL
    res = json.loads((STUDY / "resources.json").read_text("utf-8"))
    assert res["datasets"][0]["path"] == b.SNAPSHOT_URL
    ser = src["series"]
    assert [p["label"] for p in ser] == b.MONTH_LABELS
    errs = [abs(p["forecast"] - p["actual"]) for p in ser]
    stats = src["study_window_stats"]
    assert stats["mae"] == round(statistics.fmean(errs), 3)
    assert stats["rmse"] == round(statistics.fmean(e ** 2 for e in errs) ** 0.5, 3)
    assert stats["pearson"] == round(b.pearson([p["forecast"] for p in ser], [p["actual"] for p in ser]), 4)


def test_run_note_points_at_the_runnable_study():
    spec = json.loads((STUDY / "study.yaml").read_text("utf-8"))
    assert spec["rerunnable"] is False
    for lang in ("en", "zh"):
        note = spec["run_note"][lang]
        assert "`consumer_confidence`" in note and "--latest" in note
        assert "/sv-iterate" not in note          # an imported reference is never forked
