"""Study versioning tests: versions.json manifest + live-workspace/frozen-snapshot flow.

These back /sv-iterate's version gate. The live study dir always carries the CURRENT
version (python imports pin the code there); ``create_version`` freezes it into
``versions/v<N>/`` and iterates in place — so (a) the snapshot must be a faithful,
render-able archive (authored artifacts + code + run outputs, minus transient files),
(b) the live dir must restart at "built, not yet run" with mtimes preserved (the
dashboard's carried-from-parent detection keys off them), and (c) branching from any
older version must restore its authored state exactly.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from skills.sv_workspace import (
    create_version,
    current_version,
    fork_study,
    init_manifest,
    load_manifest,
    save_study_yaml,
    scaffold,
    study_paths,
)
from socioverse.schemas import StudySpec


def _seed_study(root: Path, sid: str, *, created_by: str = "sv-init") -> None:
    """A ran-to-completion study: artifacts + code + run outputs + transient/scratch files."""
    save_study_yaml(root / "study.yaml",
                    StudySpec(study_id=sid, domain="urban-segregation", created_by=created_by))
    p = study_paths(root)
    for key in ("resources", "environment", "population", "simulation"):
        p[key].parent.mkdir(parents=True, exist_ok=True)
        p[key].write_text(json.dumps({"artifact": key, "owner": "v1"}), encoding="utf-8")
    (root / "model.py").write_text("# v1 code", encoding="utf-8")
    (root / "adapter").mkdir(exist_ok=True)
    (root / "adapter" / "decision.py").write_text("# v1 adapter", encoding="utf-8")
    p["duckdb"].parent.mkdir(parents=True, exist_ok=True)
    p["duckdb"].write_text("RUN-V1", encoding="utf-8")
    p["metrics"].write_text(json.dumps({"study_id": sid, "rows": [{"step": 0}]}), encoding="utf-8")
    (p["duckdb"].parent / "progress.jsonl").write_text('{"step": 1}\n', encoding="utf-8")
    (p["duckdb"].parent / "panel_live.jsonl").write_text('{"agent_id": "a"}\n', encoding="utf-8")
    p["report"].parent.mkdir(parents=True, exist_ok=True)
    p["report"].write_text("# report v1", encoding="utf-8")
    (root / "runs").mkdir(exist_ok=True)
    (root / "runs" / "scratch.txt").write_text("demo scratch", encoding="utf-8")
    (root / "__pycache__").mkdir(exist_ok=True)
    (root / "__pycache__" / "x.pyc").write_bytes(b"")


def test_init_manifest_registers_v1_and_is_idempotent(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    man = init_manifest(root)
    assert man["current"] == "v1"
    v1 = man["versions"][0]
    assert v1["parent"] is None and v1["snapshot"] is None and v1["warm_start"] is None
    again = init_manifest(root, note="ignored — already versioned")
    assert again["versions"][0]["created_at"] == v1["created_at"]
    assert current_version(root) == "v1"


def test_current_version_is_implicit_v1_without_manifest(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    assert current_version(root) == "v1"   # pre-versioning studies read as v1


def test_create_version_freezes_current_and_cleans_outputs(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    time.sleep(0.05)                        # artifact mtimes must precede v2's created_at

    new = create_version(root, "step-4 housing-policy broadcast, run one more step")

    assert new == "v2" and current_version(root) == "v2"
    ids = {v["id"]: v for v in load_manifest(root)["versions"]}
    assert ids["v1"]["snapshot"] == "versions/v1"
    assert ids["v2"]["parent"] == "v1" and ids["v2"]["snapshot"] is None
    assert ids["v2"]["warm_start"] is None          # reserved for the engine-resume follow-up

    snap = root / "versions" / "v1"
    # frozen archive: authored artifacts + code + run outputs all preserved
    assert json.loads((snap / "environment" / "environment.json").read_text())["owner"] == "v1"
    assert (snap / "model.py").read_text() == "# v1 code"
    assert (snap / "adapter" / "decision.py").exists()
    assert (snap / "trajectory" / "study.duckdb").read_text() == "RUN-V1"
    assert (snap / "trajectory" / "metrics_history.json").exists()
    assert (snap / "reports" / "report.md").read_text() == "# report v1"
    # excluded: scratch, caches, the snapshot tree itself, the manifest, transient run files
    for name in ("runs", "__pycache__", "versions", "versions.json"):
        assert not (snap / name).exists()
    assert not (snap / "trajectory" / "progress.jsonl").exists()
    assert not (snap / "trajectory" / "panel_live.jsonl").exists()

    # live dir: outputs cleared, authored artifacts carried with their ORIGINAL mtimes
    p = study_paths(root)
    for gone in (p["duckdb"], p["metrics"], p["report"]):
        assert not gone.exists()
    assert p["environment"].exists()
    assert p["environment"].stat().st_mtime < ids["v2"]["created_at"]   # carried threshold holds
    assert (root / "trajectory" / "steps").is_dir()                     # empty layout restored
    assert (root / "runs" / "scratch.txt").exists()                     # live scratch untouched


def test_create_version_branches_from_any_older_version(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    create_version(root, "v2: policy variant")           # live is now v2
    p = study_paths(root)
    p["environment"].write_text(json.dumps({"artifact": "environment", "owner": "v2"}),
                                encoding="utf-8")
    (root / "model.py").write_text("# v2 code", encoding="utf-8")
    p["duckdb"].write_text("RUN-V2", encoding="utf-8")

    new = create_version(root, "v3: retry from the untouched baseline", base="v1")

    assert new == "v3" and current_version(root) == "v3"
    ids = {v["id"]: v for v in load_manifest(root)["versions"]}
    assert ids["v3"]["parent"] == "v1"                   # cross-version branch recorded
    # v2's state was archived intact before the restore
    snap2 = root / "versions" / "v2"
    assert json.loads((snap2 / "environment" / "environment.json").read_text())["owner"] == "v2"
    assert (snap2 / "model.py").read_text() == "# v2 code"
    assert (snap2 / "trajectory" / "study.duckdb").read_text() == "RUN-V2"
    assert not (snap2 / "versions").exists()             # no snapshot recursion
    # live == v1's authored state again (code included), outputs empty
    assert json.loads(p["environment"].read_text())["owner"] == "v1"
    assert (root / "model.py").read_text() == "# v1 code"
    assert (root / "adapter" / "decision.py").read_text() == "# v1 adapter"
    assert not p["duckdb"].exists()


def test_create_version_refuses_unknown_base(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    with pytest.raises(ValueError):
        create_version(root, "x", base="v9")


def test_create_version_requires_existing_study(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_version(tmp_path / "ghost", "x")


def test_fork_does_not_carry_version_history(tmp_path):
    src = scaffold(tmp_path, "src")
    _seed_study(src, "src")
    create_version(src, "v2 on the source")
    fork = fork_study(tmp_path, "src", "variant")
    assert not (fork / "versions.json").exists()
    assert not (fork / "versions").exists()
    man = init_manifest(fork)                # sv-init re-registers the fork as its own v1
    assert man["current"] == "v1" and len(man["versions"]) == 1


def test_manifest_writes_are_atomic_and_leave_no_tmp(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    init_manifest(root)
    create_version(root, "v2")
    assert not list(root.glob("versions.json*.tmp"))
    assert load_manifest(root)["current"] == "v2"


# ── dashboard-side reconstruction (stdlib app.py loaded by path — no server) ──────
def _load_dashboard_app():
    path = Path(__file__).resolve().parent.parent / "dashboard" / "server" / "app.py"
    spec = importlib.util.spec_from_file_location("sv_dashboard_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = _load_dashboard_app()


def test_dashboard_versions_view_implicit_v1(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    versions, cur = APP.versions_view(root)   # no manifest yet → implicit, single, current
    assert cur == "v1" and len(versions) == 1 and versions[0]["current"] is True


def test_dashboard_live_v2_carried_before_resume_then_resumes_at_run(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    time.sleep(0.05)
    # a change that only re-runs (re-entry at sv-run) → every build stage is BEFORE the re-entry
    create_version(root, "v2: re-run only", resume_from_stage="sv-run")

    detail = APP.build_detail(root)
    assert detail["current_version"] == "v2" and detail["viewing_version"] == "v2"
    assert detail["archived"] is False
    assert [v["id"] for v in detail["versions"]] == ["v1", "v2"]
    st = {s["name"]: s for s in detail["stages"]}
    # build stages sit BEFORE the re-entry point → carried-done (done + neutral tag), NOT gated for review
    assert st["sv-build-environment"]["status"] == "done"
    assert st["sv-build-environment"].get("carried_from") == "v1"
    assert st["sv-build-population"].get("carried_from") == "v1"
    # outputs were cleared → the pointer lands exactly on sv-run
    assert st["sv-run"]["status"] == "pending" and st["sv-run"]["active"]
    assert st["sv-report"]["status"] == "pending"


def test_dashboard_review_gate_holds_then_clears(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    time.sleep(0.05)
    # same-line new version re-entering at build-environment (e.g. a new policy broadcast)
    create_version(root, "v2: policy", resume_from_stage="sv-build-environment")

    st = {s["name"]: s for s in APP.build_detail(root)["stages"]}
    # carried stages AT/AFTER the re-entry are "needs review" and hold the pointer; earlier ones stay done,
    # so the pipeline can't look finished and skip to sv-run with the parent's unreviewed artifacts.
    assert st["sv-build-environment"]["status"] == "review" and st["sv-build-environment"]["active"]
    assert st["sv-build-environment"].get("carried_from") == "v1"       # still tagged carried, just unreviewed
    assert st["sv-build-population"]["status"] == "review"
    assert st["sv-init"]["status"] == "done"                            # before the re-entry point → not gated
    assert st["sv-run"]["active"] is False

    # verify+skip env = post a THIS-version narrative (no artifact rewrite) → clears its review; pointer → population
    _write_narrative(root, "sv-build-environment", "env unchanged, validated, skipped")
    st2 = {s["name"]: s for s in APP.build_detail(root)["stages"]}
    assert st2["sv-build-environment"]["status"] == "done" and not st2["sv-build-environment"]["active"]
    assert st2["sv-build-population"]["status"] == "review" and st2["sv-build-population"]["active"]

    # re-author population (artifact rewrite, mtime bump) → clears its review too; pointer advances to run
    time.sleep(0.05)
    study_paths(root)["population"].write_text(
        json.dumps({"artifact": "population", "owner": "v2"}), encoding="utf-8")
    st3 = {s["name"]: s for s in APP.build_detail(root)["stages"]}
    assert st3["sv-build-population"]["status"] == "done" and not st3["sv-build-population"]["active"]
    assert st3["sv-run"]["status"] == "pending" and st3["sv-run"]["active"]


def test_dashboard_review_gate_failsafe_parks_at_init_not_run(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    time.sleep(0.05)
    create_version(root, "v2")             # same-line, resume_from_stage OMITTED (the skill-hole case)
    st = {s["name"]: s for s in APP.build_detail(root)["stages"]}
    # missing resume must fail SAFE to the first carried stage (review from the start), never run
    assert st["sv-init"]["status"] == "review" and st["sv-init"]["active"]
    assert st["sv-run"]["active"] is False


def test_create_version_branch_defaults_resume_to_init(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    create_version(root, "v2")                       # same-line: resume left to the caller
    create_version(root, "v3 from v1", base="v1")    # branch: a big context switch
    v = {x["id"]: x for x in load_manifest(root)["versions"]}
    assert v["v2"]["resume_from_stage"] is None
    assert v["v3"]["resume_from_stage"] == "sv-init"  # branch defaults to review-from-init


def test_dashboard_archived_version_has_no_review_gate(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    create_version(root, "v2")             # parent v1
    create_version(root, "v3")             # parent v2 → v2 is now archived history
    vd, arch = APP.version_dir(root, "v2")
    assert arch is True
    st = {s["name"]: s for s in APP.build_detail(vd, study_root=root, viewing="v2", archived=True)["stages"]}
    # a frozen snapshot is settled history — never "needs review" even though it has carried stages + predates narratives
    assert all(s["status"] != "review" for s in st.values())


def _write_narrative(d: Path, stage: str, text: str) -> None:
    """Simulate sv_emit writing a durable, version-scoped narrative file into a version dir."""
    nd = Path(d) / "narrative"
    nd.mkdir(parents=True, exist_ok=True)
    (nd / f"{stage}.json").write_text(
        json.dumps({"stage": stage, "narrative": text, "ts": time.time()}), encoding="utf-8")


def test_dashboard_archived_version_shows_own_narrative_not_live(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    create_version(root, "v2")

    vd, arch = APP.version_dir(root, "v1")
    assert arch is True and vd == root / "versions" / "v1"
    # Narratives are durable, version-scoped files now: v2 (live) records its own reasoning for
    # sv-run, v1's frozen snapshot keeps its own, different text. Each view must show ITS version's.
    _write_narrative(root, "sv-run", "v2 live reasoning")     # live dir == current version v2
    _write_narrative(vd, "sv-run", "v1 archived reasoning")   # the frozen v1 snapshot
    detail = APP.build_detail(vd, study_root=root, viewing="v1", archived=True)
    assert detail["archived"] is True and detail["viewing_version"] == "v1"
    assert detail["current_version"] == "v2"
    st = {s["name"]: s for s in detail["stages"]}
    assert st["sv-run"]["status"] == "done"                   # the frozen archive keeps its finished run
    assert st["sv-run"]["narrative"] == "v1 archived reasoning"   # its OWN, never v2's live text
    assert st["sv-report"]["status"] == "done"
    assert "carried_from" not in st["sv-build-environment"]   # v1 has no parent to carry from
    # ...and the live v2 view shows v2's reasoning, proving no cross-version bleed either way.
    live = {s["name"]: s for s in APP.build_detail(root)["stages"]}
    assert live["sv-run"]["narrative"] == "v2 live reasoning"


def test_dashboard_version_dir_resolution(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    create_version(root, "v2")
    assert APP.version_dir(root, "v2") == (root, False)   # current version = the live dir
    assert APP.version_dir(root, "v9")[0] is None


def test_dashboard_event_log_keeps_history_across_versions(tmp_path):
    root = scaffold(tmp_path, "s1")
    _seed_study(root, "s1")
    time.sleep(0.05)
    create_version(root, "v2: policy")
    time.sleep(0.05)
    study_paths(root)["environment"].write_text(              # v2 rebuilds E
        json.dumps({"artifact": "environment", "owner": "v2"}), encoding="utf-8")

    evts = APP.build_events(root, "s1")
    env_evts = [e for e in evts if e.get("stage") == "sv-build-environment"]
    # log semantics: v1's original env build AND v2's rebuild are BOTH in the feed
    assert {e["version"] for e in env_evts} == {"v1", "v2"}
    # v1's finished run stays in the log even though v2 cleared the live outputs
    assert any(e.get("stage") == "sv-run" and e["version"] == "v1" for e in evts)
    # carried population is reported once, by the version that authored it
    assert [e["version"] for e in evts if e.get("stage") == "sv-build-population"] == ["v1"]
    # version-created entries come from the manifest
    assert any(e["kind"] == "version" and e["version"] == "v2" for e in evts)
    # newest first
    assert all(evts[i]["ts"] >= evts[i + 1]["ts"] for i in range(len(evts) - 1))


def test_dashboard_fork_inherited_wins_over_carried(tmp_path):
    src = scaffold(tmp_path, "src")
    _seed_study(src, "src")
    time.sleep(0.05)
    fork = fork_study(tmp_path, "src", "variant")   # rewrites study.yaml → artifacts read older
    init_manifest(fork)
    time.sleep(0.05)
    create_version(fork, "v2 on the fork")

    st = {s["name"]: s for s in APP.build_detail(fork)["stages"]}
    # fork semantics stay amber "inherited" (re-author me), never downgraded to carried
    assert st["sv-build-environment"]["status"] == "inherited"
    assert "carried_from" not in st["sv-build-environment"]


def test_shipped_version_manifests_point_only_at_shipped_files():
    """`studies/*/versions/` is gitignored, so a committed manifest must not name a snapshot:
    a fresh clone would list versions that cannot be viewed, branched from or restored."""
    studies = Path(__file__).resolve().parents[1] / "studies"
    for mf in sorted(studies.glob("*/versions.json")):
        man = json.loads(mf.read_text(encoding="utf-8"))
        ids = [v["id"] for v in man["versions"]]
        assert man["current"] in ids, mf
        snaps = {v["id"]: v.get("snapshot") for v in man["versions"]}
        for v in man["versions"]:
            snap = v.get("snapshot")
            assert snap is None or (mf.parent / snap).is_dir(), f"{mf}: {v['id']} -> {snap}"
            src = (v.get("warm_start") or {}).get("source")
            assert src is None or (snaps.get(src) and (mf.parent / snaps[src]).is_dir()), \
                f"{mf}: {v['id']} replays {src}, whose snapshot is not on disk"
