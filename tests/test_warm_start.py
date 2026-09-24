"""Warm-start: a new version inherits a parent version's already-run steps.

Mechanism = REPLAY the parent's stored actions for steps 1..K (no decide_batch, no LLM), which
both reproduces the parent trajectory exactly and rehydrates env state to E_K, then run K+1..N
with real decisions. Supported for from-scratch / Path-B studies (pure ``env.apply``) with
``interaction_rounds == 1``; legacy-wrap studies (chicago) re-run from 0. See loop._replay_inherited.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import studies.opinion_diffusion  # noqa: F401 — registers opinion.* refs
from skills.sv_workspace import (
    create_version,
    load_manifest,
    save_study_yaml,
    scaffold,
    study_paths,
    version_trajectory_db,
)
from socioverse.engine import build_simulator
from socioverse.io.duckdb_store import open_readonly
from socioverse.schemas import ScheduledEvent, SimulationConfig, StudySpec, WarmStartSpec
from studies.opinion_diffusion.model import make_opinion_bundles


def _cfg(n_steps, *, warm_start=None):
    return SimulationConfig(
        study_id="opinion_diffusion", n_steps=n_steps, seed=42,
        decision_ref="opinion.decision", decision_args={"confidence": 0.3},
        collector_ref="opinion.collector", interaction_rounds=1, warm_start=warm_start)


def _panel(db):
    con = open_readonly(str(db))
    try:
        return con.execute("SELECT agent_id, step, state, action_kind, action_payload "
                           "FROM panel ORDER BY step, agent_id").fetchall()
    finally:
        con.close()


def _metrics(db):
    con = open_readonly(str(db))
    try:
        return con.execute("SELECT * FROM metrics ORDER BY step").fetchall()
    finally:
        con.close()


def test_warm_start_replays_parent_exactly_and_skips_llm(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=12, n_steps=6)

    parent_db = tmp_path / "parent.duckdb"
    build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=_cfg(6),
                    store_path=parent_db).run()
    p_panel, p_metrics = _panel(parent_db), _metrics(parent_db)

    child_db = tmp_path / "child.duckdb"
    ws = WarmStartSpec(source_version="v1", source_trajectory=str(parent_db), resume_from=6)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=_cfg(8, warm_start=ws),
                          store_path=child_db)
    # spy: which steps actually invoked the decision model?
    decided, orig = [], sim.decision.decide_batch
    sim.decision.decide_batch = lambda obs, mem: (decided.append(obs[0].step if obs else None)
                                                  or orig(obs, mem))
    sim.run()
    c_panel = _panel(child_db)

    # inherited region reproduced byte-for-byte (replay is exact)
    assert [r for r in c_panel if r[1] <= 6] == p_panel
    assert _metrics(child_db)[:7] == p_metrics
    # extended to 0..8, and ONLY the new steps ran the decision model (LLM budget saved)
    assert sorted({r[1] for r in c_panel}) == list(range(0, 9))
    assert decided == [7, 8]


def test_warm_start_new_intervention_takes_effect_after_resume(tmp_path):
    # parent: campaign at step 2 only, N=4
    _, env_p, pop_b, _ = make_opinion_bundles(n_agents=12, n_steps=4, campaign_step=2)
    parent_db = tmp_path / "parent.duckdb"
    build_simulator(env_bundle=env_p, pop_bundle=pop_b, sim_config=_cfg(4),
                    store_path=parent_db).run()
    p_by_step = {r[0]: r[1] for r in _metrics_named(parent_db)}

    # child: same, PLUS a new media bump at step 3 → inherit 0..2 (resume_from=2), diverge at 3
    _, env_c, pop_c, _ = make_opinion_bundles(n_agents=12, n_steps=4, campaign_step=2)
    env_c.scheduled_events.append(ScheduledEvent(
        at_step=3, target_layer="media_pressure", op="add", property_name="level", value=1.0,
        note="new media bump at step 3"))
    child_db = tmp_path / "child.duckdb"
    ws = WarmStartSpec(source_version="v1", source_trajectory=str(parent_db), resume_from=2)
    build_simulator(env_bundle=env_c, pop_bundle=pop_c, sim_config=_cfg(4, warm_start=ws),
                    store_path=child_db).run()
    c_by_step = {r[0]: r[1] for r in _metrics_named(child_db)}

    # inherited region identical; the new step-3 intervention changed the trajectory afterward
    assert c_by_step[0] == p_by_step[0] and c_by_step[1] == p_by_step[1] and c_by_step[2] == p_by_step[2]
    assert c_by_step[3] != p_by_step[3]


def _metrics_named(db):
    """(step, mean_opinion) per row — column order is step-first (see MetricsHistory)."""
    con = open_readonly(str(db))
    try:
        return con.execute("SELECT step, mean_opinion FROM metrics ORDER BY step").fetchall()
    finally:
        con.close()


def test_warm_start_rejects_multi_round(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=8, n_steps=3)
    parent_db = tmp_path / "parent.duckdb"
    build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=_cfg(3),
                    store_path=parent_db).run()

    cfg = _cfg(5, warm_start=WarmStartSpec(source_version="v1",
                                           source_trajectory=str(parent_db), resume_from=3))
    cfg.interaction_rounds = 2   # multi-round: the panel keeps only the last round → no exact replay
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=cfg,
                          store_path=tmp_path / "child.duckdb")
    with pytest.raises(ValueError, match="interaction_rounds"):
        sim.run()


def test_create_version_records_warm_start_provenance(tmp_path):
    root = scaffold(tmp_path, "s1")
    save_study_yaml(study_paths(root)["study"], StudySpec(study_id="s1"))
    time.sleep(0.02)

    new = create_version(root, "extend +2 with warm start",
                         warm_start={"source": "v1", "resume_from": 6})
    entry = {v["id"]: v for v in load_manifest(root)["versions"]}[new]
    assert entry["warm_start"] == {"source": "v1", "resume_from": 6}
    # the parent's archived store is where sv-run replays from
    assert version_trajectory_db(root, "v1") == root / "versions" / "v1" / "trajectory" / "study.duckdb"


def test_load_parent_panel_accepts_panel_live_jsonl(tmp_path):
    """Groundwork for resuming a run: the warm-start action source supports the panel_live.jsonl left by an interrupted run."""
    import json
    from socioverse.engine.loop import LongitudinalSimulator
    f = tmp_path / "panel_live.jsonl"
    rows = []
    for step in (0, 1, 1, 2, 2, 3):
        rows.append({"agent_id": f"a-{len(rows)%2}", "step": step,
                     "action_kind": "act", "action_payload": {"v": step}})
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    by = LongitudinalSimulator._load_parent_panel(str(f), 2)
    assert set(by) == {1, 2}                      # step 0 (the initial state) and steps > upto are not replayed
    assert len(by[1]) == 2 and by[2][0]["action_payload"] == {"v": 2}
