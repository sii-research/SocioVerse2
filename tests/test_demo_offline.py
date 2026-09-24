"""scripts/demo_offline.py: the Quickstart demo runs in its own local study and never writes
into the shipped reference study."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "studies" / "opinion_diffusion"

_spec = importlib.util.spec_from_file_location("demo_offline", REPO / "scripts" / "demo_offline.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def _studies(tmp_path: Path) -> Path:
    root = tmp_path / "studies"
    shutil.copytree(SOURCE, root / "opinion_diffusion",
                    ignore=shutil.ignore_patterns("__pycache__", "trajectory", "versions", "runs"))
    return root


def _digest(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


def test_demo_forks_a_local_study_and_leaves_the_reference_alone(tmp_path):
    root = _studies(tmp_path)
    before = _digest(root / "opinion_diffusion")

    assert demo.main(["--no-report"], studies_root=root) == 0

    assert _digest(root / "opinion_diffusion") == before
    d = root / demo.DEMO_ID
    spec = json.loads((d / "study.yaml").read_text(encoding="utf-8"))
    assert spec["study_id"] == demo.DEMO_ID
    assert spec["reference"] is False and spec["status"] == "local-demo"
    assert spec["created_by"].endswith("(fork of opinion_diffusion)")
    for rel in ("environment/environment.json", "population/population.json",
                "simulation/simulation.json", "resources.json"):
        assert json.loads((d / rel).read_text(encoding="utf-8"))["study_id"] == demo.DEMO_ID
    sim = json.loads((d / "simulation" / "simulation.json").read_text(encoding="utf-8"))
    assert sim["decision_args"]["llm_kind"] == "scripted"     # records how the demo actually ran
    rows = json.loads((d / "trajectory" / "metrics_history.json").read_text(encoding="utf-8"))["rows"]
    assert [r["step"] for r in rows] == [0, 1, 2, 3, 4]
    assert rows[-1]["mean_opinion"] == pytest.approx(0.7367, abs=1e-4)
    assert (d / "trajectory" / "study.duckdb").exists()

    # a second run replaces the demo study it made
    assert demo.main(["--no-report"], studies_root=root) == 0


def test_demo_refuses_to_replace_a_study_it_did_not_make(tmp_path):
    root = _studies(tmp_path)
    mine = root / demo.DEMO_ID
    mine.mkdir()
    (mine / "study.yaml").write_text(json.dumps({"study_id": demo.DEMO_ID, "status": "draft",
                                                 "created_by": "sv-init"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        demo.main(["--no-report"], studies_root=root)
    assert (mine / "study.yaml").exists()


def test_demo_report_is_english_and_matches_the_run(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")
    monkeypatch.delenv("SV_REPORT_LANG", raising=False)
    root = _studies(tmp_path)
    assert demo.main([], studies_root=root) == 0
    d = root / demo.DEMO_ID
    report = (d / "reports" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Opinion diffusion under a media campaign (local demo)")
    assert "## Summary" in report and "offline demo, llm_kind=scripted" in report
    assert "**Mean opinion 0.500→0.737" in report
    assert sorted(p.name for p in (d / "reports" / "figures").glob("*.png")) == [
        "cohort_paths.png", "opinion_trajectory.png"]


def test_report_language_switch(monkeypatch):
    pytest.importorskip("matplotlib")
    from studies.opinion_diffusion.reporting import resolve_lang

    monkeypatch.delenv("SV_REPORT_LANG", raising=False)
    assert resolve_lang() == "en" and resolve_lang("zh") == "zh"
    monkeypatch.setenv("SV_REPORT_LANG", "zh-CN")
    assert resolve_lang() == "zh" and resolve_lang("en") == "en"


def test_dashboard_marks_the_copied_stages_as_forked(tmp_path):
    spec = importlib.util.spec_from_file_location("sv_dash_app_for_demo",
                                                  REPO / "dashboard" / "server" / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)

    root = _studies(tmp_path)
    assert demo.main(["--no-report"], studies_root=root) == 0
    stages = {s["name"]: s["status"] for s in app.build_detail(root / demo.DEMO_ID)["stages"]}
    assert stages == {"sv-init": "done", "sv-build-model": "inherited",
                      "sv-build-environment": "inherited", "sv-build-population": "inherited",
                      "sv-run": "done", "sv-report": "pending"}


def test_zh_report_uses_the_zh_title_and_hints_at_a_missing_cjk_font(tmp_path, monkeypatch, capsys):
    pytest.importorskip("matplotlib")
    from studies.opinion_diffusion import reporting

    monkeypatch.setattr(reporting, "cjk_font", lambda: None)
    root = _studies(tmp_path)
    assert demo.main(["--report-lang", "zh"], studies_root=root) == 0
    assert "fonts-noto-cjk" in capsys.readouterr().out
    d = root / demo.DEMO_ID
    zh_title = json.loads((d / "study.yaml").read_text(encoding="utf-8"))["title_i18n"]["zh"]
    report = (d / "reports" / "report.md").read_text(encoding="utf-8")
    assert zh_title.endswith("（本地演示）") and report.startswith(f"# {zh_title}\n")
    assert "## 结论速览" in report and "本次为 scripted" in report


def _ctx(rows, *, llm, cstep=2):
    from studies.opinion_diffusion import reporting

    metrics = [{"step": i, "mean_opinion": m, "opinion_std": s, "frac_above_0_5": f}
               for i, (m, s, f) in enumerate(rows)]
    first, last = metrics[0], metrics[-1]
    pre, at = metrics[cstep - 1], metrics[cstep]
    n = len(metrics) - 1
    return {"study_title": "t", "run_mode": "LLM (m, llm_kind=openai)" if llm else "",
            "version": "", "metrics": metrics, "events": {}, "first": first, "last": last,
            "max_step": n, "cstep": cstep,
            "low_path": {0: 0.3, n: 0.35}, "high_path": {0: 0.7, n: 0.8},
            "d_mean_pre": pre["mean_opinion"] - first["mean_opinion"],
            "d_mean_total": last["mean_opinion"] - first["mean_opinion"],
            "d_std_total": last["opinion_std"] - first["opinion_std"],
            "d_mean_atstep": at["mean_opinion"] - pre["mean_opinion"],
            "low_gain": 0.05, "high_gain": 0.1, "n_agents": 12, "llm": llm,
            **reporting._shape(metrics, cstep)}


def test_report_sentences_follow_the_data_and_the_decision_layer():
    pytest.importorskip("matplotlib")
    from studies.opinion_diffusion import reporting

    # non-monotone std, the mean falls after the campaign, share rises but stays below half
    rows = [(0.40, 0.30, 0.25), (0.45, 0.32, 0.25), (0.50, 0.25, 0.33), (0.48, 0.27, 0.42)]
    for lang, fn in (("en", reporting._report_en), ("zh", reporting._report_zh)):
        text = "\n".join(fn(_ctx(rows, llm=True)))
        assert "decide_batch" not in text and "(1−opinion) leaves" not in text
        if lang == "en":
            assert "monotone decline" not in text and "majority moves" not in text
            assert "more agents are at or above 0.5, but not a majority" in text
            assert "a net decline that is not monotone" in text and "not steadily" in text
            assert "LLM's reply to a prompt" in text and "not pulled further" in text
        else:
            assert "单调下降" not in text and "多数派" not in text and "尚未过半" in text
            assert "净下降但非单调" in text
            assert "LLM 对提示词的回答" in text
    # the scripted wording is kept when the data fit it
    rows = [(0.50, 0.288, 0.5), (0.50, 0.282, 0.5), (0.618, 0.212, 0.67), (0.707, 0.16, 0.83)]
    text = "\n".join(reporting._report_en(_ctx(rows, llm=False)))
    assert "then a steady rise" in text and "a monotone decline" in text
    assert "the majority moves to the supporting side" in text and "`decide_batch`" in text
