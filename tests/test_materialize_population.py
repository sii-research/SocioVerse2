"""build-population now INSTANTIATES the agents (it used to be declaration-only).

These back the change that made sv-build-population materialize the pool (run
``population.build(seed)`` + ``env.reset(seed)``) at build time — so ``population.json``
carries the real personas + count, ``population/roster.jsonl`` holds the t=0 panel, and the
dashboard's agent inspector shows every initialized agent BEFORE any run (previously the card
stayed empty until sv-run produced panel data).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import studies.opinion_diffusion  # noqa: F401 — registers opinion.* refs
from skills.sv_workspace import scaffold, study_paths, write_roster
from socioverse.engine import materialize_initial
from socioverse.schemas import PopulationBundle
from socioverse.validation import validate_handoff, write_artifact
from studies.opinion_diffusion.model import make_opinion_bundles


def _load_dashboard_app():
    path = Path(__file__).resolve().parent.parent / "dashboard" / "server" / "app.py"
    spec = importlib.util.spec_from_file_location("sv_dashboard_app_mat", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = _load_dashboard_app()


def test_generic_materialize_initial_instantiates_pool():
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=10)
    personas, rows = materialize_initial(env_b, pop_b, seed=42)

    assert len(personas) == 10 and len(rows) == 10
    assert [p.agent_id for p in personas] == [f"od-{i:03d}" for i in range(10)]
    # t=0 rows carry the env-derived initial state (same shape a run's step-0 panel has)
    r0 = rows[0]
    assert r0.step == 0 and r0.action_kind is None
    assert r0.state == {"opinion": personas[0].attributes["opinion0"]}
    # deterministic in seed → matches what sv-run rebuilds at t=0
    again, _ = materialize_initial(env_b, pop_b, seed=42)
    assert [p.agent_id for p in again] == [p.agent_id for p in personas]


def test_write_roster_matches_panel_shape(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=6)
    _, rows = materialize_initial(env_b, pop_b, seed=42)
    p = write_roster(tmp_path / "roster.jsonl", rows)

    lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert len(lines) == 6
    assert sorted(lines[0]) == ["action_kind", "action_payload", "agent_id", "state", "step"]
    assert lines[0]["step"] == 0 and lines[0]["action_kind"] is None


def test_build_population_artifact_embeds_personas_and_count(tmp_path):
    root = scaffold(tmp_path, "od")
    p = study_paths(root)
    _, env_b, pop_b, _ = make_opinion_bundles(study_id="od", n_agents=12)
    write_artifact(p["environment"], env_b)

    personas, rows = materialize_initial(env_b, pop_b, seed=42)
    pop_b.materialized_count = len(personas)
    pop_b.personas = personas
    write_artifact(p["population"], pop_b)
    write_roster(p["roster"], rows)

    # population.json now carries substance and re-validates
    reloaded = validate_handoff(p["population"], PopulationBundle)
    assert reloaded.materialized_count == 12 and len(reloaded.personas) == 12
    # old artifacts (no materialized_count) still load — schema-safe optional field
    legacy = PopulationBundle(study_id="od", provider_ref="opinion.pop")
    assert legacy.materialized_count is None


def test_dashboard_shows_roster_before_run(tmp_path):
    """The user's concern: is the Agents card visible pre-run? With roster.jsonl, yes."""
    root = scaffold(tmp_path, "od")
    p = study_paths(root)
    _, env_b, pop_b, _ = make_opinion_bundles(study_id="od", n_agents=12)
    write_artifact(p["environment"], env_b)
    personas, rows = materialize_initial(env_b, pop_b, seed=42)
    pop_b.materialized_count = len(personas)
    write_artifact(p["population"], pop_b)   # personas left empty → count is authoritative
    write_roster(p["roster"], rows)
    assert not (root / "trajectory" / "study.duckdb").exists()   # NO run has happened

    # read_panel falls back to the roster; agents_summary flags the pre-run phase
    panel_rows, source = APP.read_panel(root)
    assert source == "roster" and len(panel_rows) == 12
    summary = APP.agents_summary(root)
    assert summary["count"] == 12 and summary["phase"] == "initial" and summary["live"] is False
    # the population card count comes from materialized_count even with personas=[]
    assert APP.pop_summary(p["population"])["persona_count"] == 12


def test_dashboard_run_panel_wins_over_roster(tmp_path):
    """Once a run writes panel_live.jsonl, it takes priority over the pre-run roster."""
    root = scaffold(tmp_path, "od")
    (root / "population").mkdir(parents=True, exist_ok=True)
    write_roster(root / "population" / "roster.jsonl",
                 [{"agent_id": "od-000", "step": 0, "state": {"opinion": 0.1}}])
    (root / "trajectory").mkdir(parents=True, exist_ok=True)
    (root / "trajectory" / "panel_live.jsonl").write_text(
        json.dumps({"agent_id": "od-000", "step": 3, "state": {"opinion": 0.7},
                    "action_kind": "update_opinion", "action_payload": {"opinion": 0.7}}) + "\n",
        encoding="utf-8")

    _, source = APP.read_panel(root)
    assert source == "live"
    assert APP.agents_summary(root)["phase"] == "live"


# ── chicago (legacy Path-C shared engine) — skips when the ABM data isn't present ──
from studies.chicago_schelling.adapter.engine_seam import chicago_missing  # noqa: E402

_CHI = pytest.mark.skipif(
    bool(chicago_missing()),
    reason=f"Chicago legacy not available: {', '.join(chicago_missing())}")


@_CHI
def test_chicago_materialize_uses_one_shared_engine():
    from studies.chicago_schelling.adapter import (
        DeterministicLLMClient,
        make_chicago_bundles,
        materialize_chicago_initial,
    )

    _, env_b, pop_b = make_chicago_bundles(scale="small")
    personas, rows, engine = materialize_chicago_initial(
        env_bundle=env_b, pop_bundle=pop_b, seed=42, scale="small",
        llm_client=DeterministicLLMClient())

    assert len(personas) > 0 and len(rows) == len(personas)
    # personas carry real census identity (not an empty declaration)
    assert set(personas[0].attributes) >= {"race", "income_bracket", "family_type"}
    # t=0 rows carry the env-derived initial state the inspector shows
    assert set(rows[0].state) >= {"tract_id", "race", "satisfaction"}
    # one shared engine indexed every agent (env + pop saw the same model)
    assert engine.model is not None
