"""Branch vs version — the two edit domains of the controllable research loop.

A **branch** is a counterfactual: it inherits its parent's realized history up to a fork step
(replayed from the parent's stored actions, no LLM) and changes ONLY the environment from that
step on, so what differs afterwards is attributable to the declared intervention alone. A
**version** may change any artifact and runs cold; it compares one study design with another.

``versions.json`` records which is which (``kind`` + ``fork_step``). These tests pin:
(a) what each constructor writes, (b) that pre-``kind`` manifests still classify correctly,
(c) that a workspace which breaks the branch contract is DOWNGRADED to a version rather than
rejected, with the reason kept for the audit trail, and (d) that the downgrade reaches the run
path through ``resolve_warm_start`` and the dashboard projection.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from skills.sv_workspace import (
    check_branch_invariant,
    create_branch,
    create_version,
    current_version,
    init_manifest,
    load_manifest,
    resolve_warm_start,
    save_study_yaml,
    scaffold,
    study_paths,
    version_entry,
    version_fork_step,
    version_kind,
)
from socioverse.schemas import StudySpec

ENV_V1 = {
    "study_id": "s1",
    "provider_ref": "demo.env",
    "provider_args": {"scale": "small"},
    "layers": [
        {"name": "tract_local", "modality": "physical", "scope": "local", "dynamics": "endogenous"},
        {"name": "city_news", "modality": "information", "scope": "macro", "dynamics": "scheduled"},
    ],
    "scheduled_events": [
        {"at_step": 2, "target_layer": "tract_local", "op": "add", "property_name": "stations",
         "value": 2, "selector": {"tract": "17031612000"}, "note": "baseline transit works"},
    ],
    "information_program": {
        "broadcasts": [
            {"message_id": "A", "channel": "news", "content": "citywide notice", "at_step": 2,
             "ttl": 3, "audience": "all"},
        ]
    },
}
SIM_V1 = {
    "study_id": "s1", "n_steps": 6, "seed": 42, "decision_ref": "demo.decision",
    "decision_args": {"temperature": 0.7}, "collector_ref": "demo.collector",
    "collector_args": {}, "interaction_rounds": 1, "store_ref": "duckdb", "store_args": {},
    "engine_args": {"memory_window": 8},
}
POP_V1 = {"study_id": "s1", "provider_ref": "demo.pop", "n_agents": 24,
          "generated_at": "2026-09-01T00:00:00Z"}


def _seed(root: Path, sid: str = "s1") -> Path:
    """A ran-to-completion study with realistic P / E / Θ artifacts and a trajectory store."""
    save_study_yaml(root / "study.yaml", StudySpec(study_id=sid, domain="opinion-dynamics"))
    p = study_paths(root)
    for key, payload in (("environment", ENV_V1), ("population", POP_V1), ("simulation", SIM_V1)):
        p[key].parent.mkdir(parents=True, exist_ok=True)
        p[key].write_text(json.dumps({**payload, "study_id": sid}, indent=2), encoding="utf-8")
    (root / "population" / "roster.jsonl").write_text(
        '{"agent_id": "a1"}\n{"agent_id": "a2"}\n', encoding="utf-8")
    (root / "model.py").write_text("# v1 behaviour function\n", encoding="utf-8")
    p["duckdb"].parent.mkdir(parents=True, exist_ok=True)
    p["duckdb"].write_text("RUN-V1", encoding="utf-8")
    p["metrics"].write_text(json.dumps({"study_id": sid, "rows": [{"step": 0}]}), encoding="utf-8")
    init_manifest(root)
    return root


def _env(root: Path) -> dict:
    return json.loads(study_paths(root)["environment"].read_text(encoding="utf-8"))


def _write_env(root: Path, env: dict) -> None:
    study_paths(root)["environment"].write_text(json.dumps(env, indent=2), encoding="utf-8")


def _add_broadcast(root: Path, *, at_step: int, mid: str = "CAMPAIGN") -> None:
    """The textbook branch edit: one more broadcast, authored at/after the fork step."""
    env = _env(root)
    env["information_program"]["broadcasts"].append(
        {"message_id": mid, "channel": "news", "content": "media campaign", "at_step": at_step,
         "ttl": 2, "audience": "all"})
    _write_env(root, env)


# ── what the two constructors record ────────────────────────────────────────────────────
def test_v1_is_a_plain_version_not_a_special_root(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    v1 = version_entry(root)
    assert v1["kind"] == "version" and v1["fork_step"] is None
    assert v1["parent"] is None               # parent=None IS the root marker; no "root" kind
    assert version_kind(v1) == "version"


def test_create_version_is_a_version_with_no_fork_step(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_version(root, "swap in the open-pool population", resume_from_stage="sv-build-population")
    e = version_entry(root)
    assert e["id"] == "v2" and e["kind"] == "version"
    assert e["fork_step"] is None and e["warm_start"] is None


def test_create_branch_records_fork_step_and_replay_provenance(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    new = create_branch(root, "media campaign at step 5", fork_step=5)
    assert new == "v2" and current_version(root) == "v2"
    e = version_entry(root)
    assert e["kind"] == "branch" and e["fork_step"] == 5
    assert e["warm_start"] == {"source": "v1", "resume_from": 4}   # inherit 0..4, compute 5..T
    assert e["parent"] == "v1"
    # a branch only re-authors E, so it re-enters the pipeline there (not at sv-init)
    assert e["resume_from_stage"] == "sv-build-environment"
    # the parent's run was frozen first — that store is what sv-run replays
    assert (root / "versions" / "v1" / "trajectory" / "study.duckdb").read_text() == "RUN-V1"


def test_create_branch_rejects_step_zero(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    with pytest.raises(ValueError):
        create_branch(root, "nonsense", fork_step=0)


def test_create_branch_from_an_older_version_restores_its_artifacts(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_version(root, "v2: different design")           # live is v2 now
    (root / "model.py").write_text("# v2 behaviour function\n", encoding="utf-8")
    create_branch(root, "branch the v1 design instead", fork_step=3, source="v1")
    e = version_entry(root)
    assert e["kind"] == "branch" and e["fork_step"] == 3 and e["warm_start"]["source"] == "v1"
    assert (root / "model.py").read_text() == "# v1 behaviour function\n"   # v1's design restored


# ── reading manifests written before `kind` existed ─────────────────────────────────────
def test_pre_kind_manifests_classify_by_warm_start(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_version(root, "v2")
    man = load_manifest(root)
    legacy_branch = {"id": "v3", "parent": "v2", "note": "old-style", "created_at": 0,
                     "snapshot": None, "warm_start": {"source": "v2", "resume_from": 3}}
    legacy_version = {"id": "v4", "parent": "v2", "note": "old-style", "created_at": 0,
                      "snapshot": None, "warm_start": None}
    assert version_kind(legacy_branch) == "branch"        # no "kind" key at all
    assert version_fork_step(legacy_branch) == 4          # derived from resume_from
    assert version_kind(legacy_version) == "version"
    assert version_fork_step(legacy_version) is None
    assert version_kind(man["versions"][0]) == "version"


# ── the E-only invariant: violations downgrade, they do not raise ───────────────────────
def test_post_fork_intervention_is_a_valid_branch(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "media campaign at step 5", fork_step=5)
    _add_broadcast(root, at_step=5)                      # the intervention itself
    rep = check_branch_invariant(root)
    assert rep["ok"] and rep["kind"] == "branch" and not rep["downgraded"]
    assert rep["violations"] == [] and rep["fork_step"] == 5
    assert version_entry(root)["kind"] == "branch"       # untouched


def test_branch_may_add_a_layer_to_carry_its_broadcast(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    env = _env(root)
    env["layers"].append({"name": "campaign_feed", "modality": "information", "scope": "local",
                          "dynamics": "scheduled"})
    _write_env(root, env)
    _add_broadcast(root, at_step=5)
    assert check_branch_invariant(root)["ok"]            # adding a layer is allowed


def test_changing_an_existing_layer_downgrades(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    env = _env(root)
    env["layers"][0]["dynamics"] = "static"              # rewrote a layer the parent had
    _write_env(root, env)
    rep = check_branch_invariant(root)
    assert not rep["ok"] and rep["downgraded"] and any("environment layer" in v for v in rep["violations"])


def test_pre_fork_intervention_downgrades(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    _add_broadcast(root, at_step=3, mid="TOO-EARLY")     # bites inside the inherited history
    rep = check_branch_invariant(root)
    assert not rep["ok"] and rep["downgraded"]
    assert any("environment before step" in v for v in rep["violations"])


def test_population_change_downgrades_and_is_recorded(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    p = study_paths(root)["population"]
    p.write_text(json.dumps({**POP_V1, "study_id": "s1", "n_agents": 500}, indent=2),
                 encoding="utf-8")
    rep = check_branch_invariant(root)

    assert not rep["ok"] and rep["downgraded"] and rep["kind"] == "version"
    assert any("population P" in v for v in rep["violations"])
    e = version_entry(root)
    assert e["kind"] == "version" and e["warm_start"] is None and e["fork_step"] is None
    audit = e["downgraded_from_branch"]                  # the reason survives for the audit trail
    assert audit["source"] == "v1" and audit["fork_step"] == 5 and audit["violations"]


def test_volatile_population_keys_are_not_a_violation(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    p = study_paths(root)["population"]
    p.write_text(json.dumps({**POP_V1, "study_id": "s1",
                             "generated_at": "2026-09-22T12:00:00Z"}, indent=2), encoding="utf-8")
    assert check_branch_invariant(root)["ok"]            # re-serialized, same content


def test_behaviour_function_change_downgrades(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    (root / "model.py").write_text("# rewritten decision rule\n", encoding="utf-8")
    rep = check_branch_invariant(root)
    assert not rep["ok"] and any("behavior function f" in v for v in rep["violations"])


def test_seed_change_downgrades_but_longer_horizon_does_not(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    sim_p = study_paths(root)["simulation"]
    sim_p.write_text(json.dumps({**SIM_V1, "study_id": "s1", "n_steps": 12}, indent=2),
                     encoding="utf-8")
    assert check_branch_invariant(root)["ok"]            # extending the horizon is fine

    sim_p.write_text(json.dumps({**SIM_V1, "study_id": "s1", "n_steps": 12, "seed": 7}, indent=2),
                     encoding="utf-8")
    rep = check_branch_invariant(root)
    assert not rep["ok"] and any("seed" in v for v in rep["violations"])


def test_missing_parent_snapshot_downgrades(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    import shutil
    shutil.rmtree(root / "versions" / "v1")
    rep = check_branch_invariant(root)
    assert not rep["ok"] and rep["downgraded"]


def test_a_version_is_never_checked(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_version(root, "v2: new population", resume_from_stage="sv-build-population")
    study_paths(root)["population"].write_text('{"n_agents": 500}', encoding="utf-8")
    rep = check_branch_invariant(root)
    assert rep["ok"] and rep["kind"] == "version" and rep["violations"] == []


def test_downgrade_can_be_previewed_without_mutating(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    (root / "model.py").write_text("# rewritten\n", encoding="utf-8")
    rep = check_branch_invariant(root, downgrade=False)
    assert not rep["ok"] and rep["downgraded"] is False
    assert version_entry(root)["kind"] == "branch"       # manifest untouched


# ── the run path honours the verdict ────────────────────────────────────────────────────
def test_resolve_warm_start_serves_a_valid_branch(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    _add_broadcast(root, at_step=5)
    ws = resolve_warm_start(root)
    assert ws["source_version"] == "v1" and ws["resume_from"] == 4
    assert ws["source_trajectory"].endswith("versions/v1/trajectory/study.duckdb")


def test_resolve_warm_start_returns_none_after_a_downgrade(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 5", fork_step=5)
    (root / "model.py").write_text("# rewritten decision rule\n", encoding="utf-8")
    assert resolve_warm_start(root) is None              # cold run from step 0
    assert version_entry(root)["kind"] == "version"      # and the manifest says why


# ── the dashboard projection ────────────────────────────────────────────────────────────
def _load_dashboard_app():
    path = Path(__file__).resolve().parent.parent / "dashboard" / "server" / "app.py"
    spec = importlib.util.spec_from_file_location("sv_dashboard_app_branch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = _load_dashboard_app()


def test_dashboard_versions_view_labels_branches(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_version(root, "v2: rule-f ablation", resume_from_stage="sv-build-model")
    create_branch(root, "campaign at 4", fork_step=4)
    versions, cur = APP.versions_view(root)
    by_id = {v["id"]: v for v in versions}
    assert cur == "v3"
    assert by_id["v1"]["kind"] == "version" and by_id["v1"]["fork_step"] is None
    assert by_id["v2"]["kind"] == "version"
    assert by_id["v3"]["kind"] == "branch" and by_id["v3"]["fork_step"] == 4
    assert by_id["v3"]["branch_of"] == "v2"
    assert by_id["v3"]["downgraded"] is False


def test_dashboard_versions_view_reads_pre_kind_manifests(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 4", fork_step=4)
    man = load_manifest(root)
    for v in man["versions"]:                            # simulate a manifest from before `kind`
        v.pop("kind", None)
        v.pop("fork_step", None)
    (root / "versions.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    by_id = {v["id"]: v for v in APP.versions_view(root)[0]}
    assert by_id["v1"]["kind"] == "version"
    assert by_id["v2"]["kind"] == "branch" and by_id["v2"]["fork_step"] == 4


def test_dashboard_marks_a_downgraded_branch(tmp_path):
    root = _seed(scaffold(tmp_path, "s1"))
    create_branch(root, "campaign at 4", fork_step=4)
    (root / "model.py").write_text("# rewritten\n", encoding="utf-8")
    check_branch_invariant(root)
    by_id = {v["id"]: v for v in APP.versions_view(root)[0]}
    assert by_id["v2"]["kind"] == "version" and by_id["v2"]["downgraded"] is True
