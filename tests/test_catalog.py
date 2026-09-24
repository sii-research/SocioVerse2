"""Catalog / routing tests: StudySpec discovery fields + discover_studies/catalog_view.

These back the sv-init Step-0 routing (reuse vs build-new). The catalog is just a glob over
``studies/*/study.yaml``, so it has to (a) round-trip the new discovery fields, (b) find real
studies, and (c) skip malformed study.yaml without raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.sv_workspace import (
    catalog_view,
    discover_studies,
    fork_study,
    load_study_yaml,
    save_study_yaml,
    scaffold,
    study_paths,
)
from socioverse.schemas import StudySpec

REPO_STUDIES = Path(__file__).resolve().parent.parent / "studies"


def test_studyspec_discovery_fields_default_empty():
    s = StudySpec(study_id="x")
    assert s.domain == "" and s.tags == [] and s.provider_refs == []
    assert s.adjustable_params == [] and s.status == "draft"
    assert s.legacy_simulator == "" and s.maintainer == ""
    assert s.metric_descriptions == {}   # optional — old study.yaml files stay valid
    assert s.demonstrates == [] and s.teaches == "" and s.reference is False


def test_studyspec_discovery_fields_roundtrip(tmp_path):
    spec = StudySpec(
        study_id="demo", domain="urban-segregation", tags=["ABM", "Schelling"],
        legacy_simulator="some/src", provider_refs=["demo.env"],
        adjustable_params=["n_steps"], status="parity-tested",
        metrics=["D_bw"], metric_descriptions={"D_bw": "黑白隔离指数（0–1，越低越混居）"},
    )
    save_study_yaml(tmp_path / "study.yaml", spec)
    loaded = StudySpec.model_validate(json.loads((tmp_path / "study.yaml").read_text()))
    assert loaded.domain == "urban-segregation"
    assert loaded.provider_refs == ["demo.env"]
    assert loaded.status == "parity-tested"
    assert loaded.metric_descriptions["D_bw"].startswith("黑白隔离指数")


def test_discover_studies_globs_workspace(tmp_path):
    for sid, dom in [("alpha", "housing"), ("bravo", "elections")]:
        root = scaffold(tmp_path, sid)
        save_study_yaml(root / "study.yaml", StudySpec(study_id=sid, domain=dom))
    found = {s.study_id: s for s in discover_studies(tmp_path)}
    assert set(found) == {"alpha", "bravo"}
    assert found["bravo"].domain == "elections"


def test_discover_studies_skips_malformed(tmp_path):
    good = scaffold(tmp_path, "good")
    save_study_yaml(good / "study.yaml", StudySpec(study_id="good"))
    bad = scaffold(tmp_path, "bad")
    (bad / "study.yaml").write_text("{ not valid json", encoding="utf-8")
    offcontract = scaffold(tmp_path, "offcontract")
    (offcontract / "study.yaml").write_text(json.dumps({"no": "study_id"}), encoding="utf-8")
    found = {s.study_id for s in discover_studies(tmp_path)}
    assert found == {"good"}  # malformed + off-contract silently skipped


def test_catalog_view_projection(tmp_path):
    root = scaffold(tmp_path, "alpha")
    save_study_yaml(root / "study.yaml",
                    StudySpec(study_id="alpha", domain="housing", metrics=["m1"]))
    view = catalog_view(tmp_path)
    assert len(view) == 1
    row = view[0]
    assert row["study_id"] == "alpha" and row["domain"] == "housing"
    assert row["metrics"] == ["m1"] and "adjustable_params" in row
    assert row["reference"] is False and row["demonstrates"] == []   # routing fields projected


def _seed_study(root, sid, *, status="parity-tested"):
    """A source study with all five artifacts + stale run outputs, for fork tests."""
    save_study_yaml(root / "study.yaml",
                    StudySpec(study_id=sid, domain="urban-segregation",
                              provider_refs=[f"{sid}.env"], status=status))
    p = study_paths(root)
    for key in ("resources", "environment", "population", "simulation"):
        p[key].parent.mkdir(parents=True, exist_ok=True)
        p[key].write_text(json.dumps({"artifact": key, "owner": sid}), encoding="utf-8")
    p["duckdb"].write_text("STALE-RUN", encoding="utf-8")          # stale trajectory output
    p["report"].write_text("# stale report", encoding="utf-8")    # stale report output


def test_fork_study_copies_artifacts_and_resets_identity(tmp_path):
    src = scaffold(tmp_path, "chicago_schelling")
    _seed_study(src, "chicago_schelling")

    fork = fork_study(tmp_path, "chicago_schelling", "chicago_sez")

    fp = study_paths(fork)
    # identity is rewritten on the fork, not inherited from the source
    forked_spec = load_study_yaml(fp["study"])
    assert forked_spec.study_id == "chicago_sez"
    assert forked_spec.status == "draft"                          # reset, not "parity-tested"
    assert "fork of chicago_schelling" in forked_spec.created_by
    assert forked_spec.provider_refs == ["chicago_schelling.env"]  # reuses source's refs (no new code)
    # editable artifacts are copied across
    for key in ("resources", "environment", "population", "simulation"):
        assert json.loads(fp[key].read_text())["artifact"] == key
    # stale run outputs are dropped so the fork re-runs clean
    assert not fp["duckdb"].exists()
    assert not fp["report"].exists()
    # both studies are now in the catalog
    assert {"chicago_schelling", "chicago_sez"} <= {s.study_id for s in discover_studies(tmp_path)}


def test_fork_study_leaves_source_untouched(tmp_path):
    src = scaffold(tmp_path, "src")
    _seed_study(src, "src")
    fork = fork_study(tmp_path, "src", "variant")

    # mutate the fork's environment; the source copy must not change
    study_paths(fork)["environment"].write_text(json.dumps({"artifact": "environment", "owner": "variant"}),
                                                encoding="utf-8")
    src_spec = load_study_yaml(study_paths(src)["study"])
    assert src_spec.study_id == "src" and src_spec.status == "parity-tested"
    assert json.loads(study_paths(src)["environment"].read_text())["owner"] == "src"
    assert study_paths(src)["duckdb"].read_text() == "STALE-RUN"   # source run output intact


def test_fork_study_refuses_to_overwrite(tmp_path):
    _seed_study(scaffold(tmp_path, "src"), "src")
    scaffold(tmp_path, "taken")
    with pytest.raises(FileExistsError):
        fork_study(tmp_path, "src", "taken")


def test_fork_study_requires_existing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        fork_study(tmp_path, "ghost", "new")


def test_fork_study_rewrites_embedded_study_id_in_all_artifacts(tmp_path):
    # real artifacts each embed `study_id` (resources/env/pop/sim); a fork must rewrite ALL of them,
    # else the fork's trajectory store is mis-tagged with the SOURCE id and binds onto it.
    src = scaffold(tmp_path, "src")
    save_study_yaml(src / "study.yaml", StudySpec(study_id="src", domain="d"))
    p = study_paths(src)
    for key in ("resources", "environment", "population", "simulation"):
        p[key].parent.mkdir(parents=True, exist_ok=True)
        p[key].write_text(json.dumps({"study_id": "src", "artifact": key}), encoding="utf-8")

    fork = fork_study(tmp_path, "src", "src_v2")
    fp = study_paths(fork)
    for key in ("resources", "environment", "population", "simulation"):
        assert json.loads(fp[key].read_text())["study_id"] == "src_v2", f"{key} kept the source id"
    assert load_study_yaml(fp["study"]).study_id == "src_v2"


def test_fork_study_clears_reference_flag(tmp_path):
    # forking a reference template yields a WORKING study — never another read-only template
    src = scaffold(tmp_path, "ref_demo")
    save_study_yaml(src / "study.yaml",
                    StudySpec(study_id="ref_demo", reference=True, demonstrates=["path-c-adapter"]))
    fork = fork_study(tmp_path, "ref_demo", "ref_demo_work")
    assert load_study_yaml(study_paths(fork)["study"]).reference is False
    assert load_study_yaml(study_paths(src)["study"]).reference is True   # source stays a pristine template


def test_real_chicago_study_is_discoverable():
    """The shipped reference study must be in the catalog with its card filled (no ABM data needed)."""
    found = {s.study_id: s for s in discover_studies(REPO_STUDIES)}
    assert "chicago_schelling" in found
    chi = found["chicago_schelling"]
    assert chi.domain == "urban-segregation"
    assert chi.legacy_simulator == "SocioVerse-ABM/tasks/organization/chicago_segregation/legacy/src"
    assert chi.requires == ["legacy:chicago", "extra:chicago"]
    assert "chicago.env" in chi.provider_refs
    assert chi.status == "parity-tested"
    assert chi.reference is True and "legacy-seam" in chi.demonstrates


def test_from_scratch_reference_template_findable():
    """sv-build-model finds its template by catalog query, not by a hard-coded name — so at
    least one shipped study must always carry reference + from-scratch-core. If the demo set
    changes and this fails, designate a new template study instead of re-hard-coding."""
    view = catalog_view(REPO_STUDIES)
    templates = [c for c in view if c["reference"] and "from-scratch-core" in c["demonstrates"]]
    assert templates, "no reference study demonstrates 'from-scratch-core'"


# ── availability metadata: requires / rerunnable → catalog_view available / missing ──

ABM_STUDIES = ["abm_axelrod", "abm_boids", "abm_civil_violence", "abm_hegselmann_krause",
               "abm_lux_marchesi", "abm_minority_game", "abm_nasch", "abm_schelling", "abm_sir",
               "abm_social_force", "abm_sugarscape"]


def test_studyspec_availability_defaults():
    s = StudySpec(study_id="x")
    assert s.requires is None and s.rerunnable is True   # old study.yaml files stay valid


def _row(view, sid):
    return next(r for r in view if r["study_id"] == sid)


def test_catalog_view_reports_availability(tmp_path, monkeypatch):
    studies = tmp_path / "studies"
    save_study_yaml(scaffold(studies, "plain") / "study.yaml", StudySpec(study_id="plain"))
    save_study_yaml(scaffold(studies, "needs_abm") / "study.yaml",
                    StudySpec(study_id="needs_abm", requires=["sibling:SocioVerse-ABM"]))
    save_study_yaml(scaffold(studies, "imported") / "study.yaml",
                    StudySpec(study_id="imported", rerunnable=False))
    save_study_yaml(scaffold(studies, "typo") / "study.yaml",
                    StudySpec(study_id="typo", requires=["sibbling:SocioVerse-ABM"]))
    abm = tmp_path / "abm"
    abm.mkdir()
    monkeypatch.setenv("SV_ABM_ROOT", str(abm))            # an empty dir = sibling absent

    view = catalog_view(studies)
    plain = _row(view, "plain")
    assert plain["requires"] == [] and plain["available"] is True
    assert plain["missing"] == [] and plain["rerunnable"] is True
    needs = _row(view, "needs_abm")
    assert needs["requires"] == ["sibling:SocioVerse-ABM"]
    assert needs["available"] is False and needs["missing"] == ["sibling:SocioVerse-ABM"]
    assert "git clone https://github.com/Lishi905/SocioVerse-ABM ../SocioVerse-ABM" in needs["setup"][0]
    assert _row(view, "imported")["rerunnable"] is False
    assert _row(view, "imported")["available"] is True
    assert _row(view, "typo")["available"] is False        # unknown kinds never count as met

    (abm / "socioverse_abm").mkdir()
    (abm / "tasks").mkdir()                                 # the markers the ABM seam needs
    needs = _row(catalog_view(studies), "needs_abm")
    assert needs["available"] is True and needs["missing"] == [] and needs["setup"] == []


def test_shipped_studies_declare_availability():
    view = {r["study_id"]: r for r in catalog_view(REPO_STUDIES)}
    for sid in ABM_STUDIES:
        assert view[sid]["requires"] == ["sibling:SocioVerse-ABM", "extra:abm"], sid
    assert view["chicago_schelling"]["requires"] == ["legacy:chicago", "extra:chicago"]
    assert view["consumer_confidence"]["requires"] == ["sibling:ConsumerSim-Consumer-Confidence-Forecast"]
    for sid in ("hisim_roe", "consumer_confidence_us_backtest"):
        assert view[sid]["rerunnable"] is False, sid        # imported references
    for sid in ("opinion_diffusion", "campus_dining_choice"):
        assert view[sid]["requires"] == [] and view[sid]["available"] is True, sid
        assert view[sid]["rerunnable"] is True, sid
    from studies.germany_auto_market import model as germany
    germany_row = view["germany_auto_market"]                # samples P from an .xlsx workbook
    assert germany_row["requires"] == ["extra:workbench"]
    assert germany_row["available"] is (not germany.workbook_missing_deps())
    assert germany_row["rerunnable"] is True


def _no_dotenv(monkeypatch, *files):
    """Make `files` (default: none) the only `.env` files the resolvers see."""
    import socioverse.external_events as ee
    monkeypatch.setattr(ee, "dotenv_candidates", lambda: list(files))


def test_sibling_resolution_matches_the_seams(tmp_path, monkeypatch):
    """catalog availability and the seams must look in the same place."""
    from skills.sv_workspace import sibling_root
    from studies._abm_common.seam import abm_root
    from studies.chicago_schelling.adapter.engine_seam import resolve_chicago_legacy

    _no_dotenv(monkeypatch)
    monkeypatch.delenv("SV_ABM_ROOT", raising=False)
    monkeypatch.delenv("SV_CHICAGO_LEGACY", raising=False)
    assert sibling_root("SocioVerse-ABM") == abm_root()
    assert abm_root().name == "SocioVerse-ABM"
    assert resolve_chicago_legacy() == (abm_root() / "tasks" / "organization"
                                        / "chicago_segregation" / "legacy")

    monkeypatch.setenv("SV_ABM_ROOT", str(tmp_path / "abm"))
    assert sibling_root("SocioVerse-ABM") == abm_root() == tmp_path / "abm"
    assert resolve_chicago_legacy() == (tmp_path / "abm" / "tasks" / "organization"
                                        / "chicago_segregation" / "legacy")

    monkeypatch.setenv("SV_CHICAGO_LEGACY", str(tmp_path / "legacy"))
    assert resolve_chicago_legacy() == tmp_path / "legacy"   # explicit legacy dir wins


def test_companion_locations_are_read_from_dotenv(tmp_path, monkeypatch):
    """SV_ABM_ROOT & co. work from `.env` (as .env.example documents); the process env wins."""
    from skills.sv_workspace import requirement_status, sibling_root
    from studies._abm_common.seam import abm_root
    from studies.chicago_schelling.adapter.engine_seam import resolve_chicago_legacy
    from studies.consumer_confidence.adapter.engine_seam import _resolve_consumersim_root

    for k in ("SV_ABM_ROOT", "SV_CHICAGO_LEGACY", "SV_CONSUMERSIM_ROOT"):
        monkeypatch.delenv(k, raising=False)
    abm = tmp_path / "abm"
    (abm / "socioverse_abm").mkdir(parents=True)
    (abm / "tasks").mkdir()
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"SV_ABM_ROOT={abm}\nSV_CONSUMERSIM_ROOT='{tmp_path / 'cs'}'\n", encoding="utf-8")
    _no_dotenv(monkeypatch, dotenv)
    assert abm_root() == sibling_root("SocioVerse-ABM") == abm
    assert requirement_status("sibling:SocioVerse-ABM")["ok"] is True
    assert resolve_chicago_legacy() == abm / "tasks" / "organization" / "chicago_segregation" / "legacy"
    assert _resolve_consumersim_root() == tmp_path / "cs"
    import os
    assert "SV_ABM_ROOT" not in os.environ          # a lookup never exports the .env keys
    monkeypatch.setenv("SV_ABM_ROOT", str(tmp_path / "env-wins"))
    assert abm_root() == tmp_path / "env-wins"


def test_extra_and_legacy_requirements_follow_the_seams(tmp_path, monkeypatch):
    """A sibling on disk is not enough: the seam's Python deps count too, and the Chicago data
    is found wherever the chicago seam finds it (SV_CHICAGO_LEGACY alone is enough)."""
    import importlib.util

    from skills.sv_workspace import requirement_status
    from studies._abm_common import seam as abm_seam
    from studies.chicago_schelling.adapter import engine_seam as chi_seam
    from studies.germany_auto_market import model as germany

    real = importlib.util.find_spec
    hidden = {"networkx", "mesa", "openpyxl"}
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name in hidden else real(name, *a, **k))
    st = requirement_status("extra:abm")
    assert st["ok"] is False and "networkx" in st["setup"] and '".[abm]"' in st["setup"]
    st = requirement_status("extra:chicago")
    assert st["ok"] is False and "mesa" in st["setup"] and '".[chicago]"' in st["setup"]
    st = requirement_status("extra:workbench")
    assert st["ok"] is False and "openpyxl" in st["setup"] and '".[workbench]"' in st["setup"]
    hidden.clear()
    assert requirement_status("extra:abm")["ok"] is (not abm_seam.abm_missing_deps())
    assert requirement_status("extra:chicago")["ok"] is (not chi_seam.chicago_missing_deps())
    assert requirement_status("extra:workbench")["ok"] is (not germany.workbook_missing_deps())
    assert requirement_status("extra:nope")["ok"] is False

    _no_dotenv(monkeypatch)
    monkeypatch.setenv("SV_ABM_ROOT", str(tmp_path / "no-abm-here"))
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("SV_CHICAGO_LEGACY", str(legacy))
    assert requirement_status("legacy:chicago")["ok"] is False
    (legacy / "processed_data").mkdir(parents=True)
    (legacy / "processed_data" / "chicago_tracts.geojson").write_text("{}", encoding="utf-8")
    st = requirement_status("legacy:chicago")
    assert st["ok"] is True and st["where"] == str(legacy)
