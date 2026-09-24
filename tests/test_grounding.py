"""Grounding sidecar tests: skills/sv_grounding.py + its workspace/dashboard wiring.

Three layers: (1) the module itself (merge semantics, atomic write, summary lines);
(2) sv_workspace integration (scaffold dir, fork copies grounding, version snapshots
keep per-version copies); (3) dashboard reconstruction (no phantom stage, detail
payload carries grounding, archived versions render their own frozen copy).
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

from skills import sv_grounding
from skills.sv_workspace import (
    create_version,
    fork_study,
    save_study_yaml,
    scaffold,
    study_paths,
)
from socioverse.schemas import StudySpec


def _fact(fid, basis="sourced", **kw):
    f = {"id": fid, "claim": f"claim {fid}", "value": 1.0, "unit": "u", "basis": basis,
         "source": {"title": f"src {fid}", "url": f"https://example.com/{fid}",
                    "via": "web_search", "accessed": "2026-07-06"}}
    f.update(kw)
    return f


# ── the module itself ────────────────────────────────────────────────────────
def test_merge_creates_file_and_skeleton(tmp_path):
    root = tmp_path / "s1"
    root.mkdir()                                  # no grounding/ subdir yet — merge mkdirs it
    p = sv_grounding.merge(root, facts=[_fact("f-a")], query="q")
    assert p == root / "grounding" / "grounding.json"
    doc = json.loads(p.read_text())
    assert doc["study_id"] == "s1" and doc["query"] == "q"
    assert doc["updated_at"] and doc["method_notes"] is None
    assert [f["id"] for f in doc["facts"]] == ["f-a"]
    assert not list(p.parent.glob("*.tmp"))       # atomic write leaves no tmp behind


def test_merge_by_id_replaces_and_appends(tmp_path):
    sv_grounding.merge(tmp_path, facts=[_fact("f-a", value=1.0), _fact("f-b")])
    sv_grounding.merge(tmp_path, facts=[_fact("f-a", value=9.9), _fact("f-c")])
    doc = sv_grounding.load(tmp_path)
    assert [f["id"] for f in doc["facts"]] == ["f-a", "f-b", "f-c"]   # order preserved
    assert doc["facts"][0]["value"] == 9.9                            # replaced in place


def test_merge_assigns_missing_ids_without_collision(tmp_path):
    sv_grounding.merge(tmp_path, facts=[{"claim": "x", "basis": "assumed"},
                                        {"id": "f2", "claim": "y", "basis": "assumed"},
                                        {"claim": "z", "basis": "assumed"}])
    ids = [f["id"] for f in sv_grounding.load(tmp_path)["facts"]]
    assert ids[1] == "f2" and len(set(ids)) == 3   # auto ids skip the taken "f2"


def test_refs_dedupe_by_url(tmp_path):
    sv_grounding.merge(tmp_path, implementation_refs=[
        {"title": "old", "url": "https://a"}, {"title": "keep", "url": "https://b"}])
    sv_grounding.merge(tmp_path, implementation_refs=[{"title": "new", "url": "https://a"}])
    refs = sv_grounding.load(tmp_path)["implementation_refs"]
    assert len(refs) == 2 and refs[0]["title"] == "new"


def test_method_notes_and_query_overwrite_only_when_given(tmp_path):
    sv_grounding.merge(tmp_path, method_notes="stylized", query="q0")
    sv_grounding.merge(tmp_path, facts=[_fact("f-a")])     # no notes/query passed
    doc = sv_grounding.load(tmp_path)
    assert doc["method_notes"] == "stylized" and doc["query"] == "q0"


def test_summary_lines(tmp_path):
    assert sv_grounding.summary(tmp_path) == "no grounding recorded"
    sv_grounding.merge(tmp_path, method_notes="stylized")
    assert sv_grounding.summary(tmp_path) == "stylized model, no real-world anchors"
    sv_grounding.merge(tmp_path,
                       facts=[_fact("f-a"), _fact("f-b", basis="proxy"),
                              _fact("f-c", basis="assumed")],
                       implementation_refs=[{"title": "r", "url": "https://r"}],
                       assumptions=[{"id": "a-x", "claim": "c", "rationale": "r"}])
    assert sv_grounding.summary(tmp_path) == \
        "3 facts: 1 sourced / 1 proxy / 1 assumed · 1 refs · 1 assumptions"


def test_load_missing_or_corrupt_returns_none(tmp_path):
    assert sv_grounding.load(tmp_path) is None
    p = sv_grounding.grounding_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("{ torn", encoding="utf-8")
    assert sv_grounding.load(tmp_path) is None


# ── workspace integration ────────────────────────────────────────────────────
def _seed_study(root: Path, sid: str):
    save_study_yaml(root / "study.yaml", StudySpec(study_id=sid, domain="housing"))
    p = study_paths(root)
    for key in ("resources", "environment", "population", "simulation"):
        p[key].parent.mkdir(parents=True, exist_ok=True)
        p[key].write_text(json.dumps({"artifact": key}), encoding="utf-8")


def test_scaffold_creates_grounding_dir(tmp_path):
    root = scaffold(tmp_path, "s1")
    assert (root / "grounding").is_dir()


def test_fork_copies_grounding(tmp_path):
    src = scaffold(tmp_path, "src")
    _seed_study(src, "src")
    sv_grounding.merge(src, facts=[_fact("f-a")])

    fork = fork_study(tmp_path, "src", "variant")
    assert [f["id"] for f in sv_grounding.load(fork)["facts"]] == ["f-a"]

    sv_grounding.merge(fork, facts=[_fact("f-a", value=5.0)])     # refresh on the fork…
    assert sv_grounding.load(src)["facts"][0]["value"] == 1.0     # …source untouched


def test_fork_without_source_grounding_still_works(tmp_path):
    src = scaffold(tmp_path, "src")
    _seed_study(src, "src")
    fork = fork_study(tmp_path, "src", "variant")
    assert sv_grounding.load(fork) is None                        # nothing to copy — fine


def test_create_version_snapshots_and_keeps_live_grounding(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    sv_grounding.merge(root, facts=[_fact("f-a")])
    time.sleep(0.02)
    create_version(root, "v2: refreshed anchors")

    live = sv_grounding.load(root)
    assert live and [f["id"] for f in live["facts"]] == ["f-a"]   # carries into new version
    snap = json.loads((root / "versions" / "v1" / "grounding" / "grounding.json").read_text())
    assert [f["id"] for f in snap["facts"]] == ["f-a"]

    sv_grounding.merge(root, facts=[_fact("f-b")])                # live moves on…
    snap = json.loads((root / "versions" / "v1" / "grounding" / "grounding.json").read_text())
    assert [f["id"] for f in snap["facts"]] == ["f-a"]            # …snapshot frozen


# ── dashboard reconstruction (stdlib app.py loaded by path — no server) ──────
def _load_dashboard_app():
    path = Path(__file__).resolve().parent.parent / "dashboard" / "server" / "app.py"
    spec = importlib.util.spec_from_file_location("sv_dashboard_app_grounding", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = _load_dashboard_app()


def test_dashboard_no_phantom_stage_and_stale_unaffected(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    before = APP.build_detail(root)
    sv_grounding.merge(root, facts=[_fact("f-a")])
    after = APP.build_detail(root)
    assert len(after["stages"]) == len(before["stages"]) == 6
    assert [(s["name"], s["status"]) for s in after["stages"]] == \
           [(s["name"], s["status"]) for s in before["stages"]]


def test_dashboard_detail_carries_grounding(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    assert APP.build_detail(root)["grounding"] is None            # no file → card hidden
    sv_grounding.merge(root,
                       facts=[_fact("f-a"), _fact("f-b", basis="assumed")],
                       implementation_refs=[{"title": "r", "url": "https://r"}],
                       assumptions=[{"id": "a-x", "claim": "c"}])
    g = APP.build_detail(root)["grounding"]
    # since ebd10dd, declared assumptions also count as assumed (1 fact with basis=assumed + 1 declared assumption)
    assert g["counts"] == {"sourced": 1, "proxy": 0, "assumed": 2}
    assert g["facts"][0]["source"]["url"] == "https://example.com/f-a"
    assert len(g["implementation_refs"]) == 1 and len(g["assumptions"]) == 1


def test_dashboard_archived_version_has_its_own_grounding(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    sv_grounding.merge(root, facts=[_fact("f-old")])
    create_version(root, "v2")
    sv_grounding.merge(root, facts=[_fact("f-new")])              # live diverges from v1

    vd, arch = APP.version_dir(root, "v1")
    detail = APP.build_detail(vd, study_root=root, viewing="v1", archived=True)
    assert [f["id"] for f in detail["grounding"]["facts"]] == ["f-old"]
    live = APP.build_detail(root)
    assert {f["id"] for f in live["grounding"]["facts"]} == {"f-old", "f-new"}
