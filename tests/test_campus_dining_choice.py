"""Path B (from-scratch) end-to-end: the campus_dining_choice study assembled by the GENERIC
Core builder from registry refs — no engine-seam, no per-study wiring, no LLM tokens.

Students choose among canteen / delivery / cooking for themselves each month while canteen & delivery prices ramp up.
The scripted (deterministic) decision exercises the real prompt→parse→apply path for free, so
these tests double as a regression guard on the choice parser (a reason string that mentions
another mode must not flip the parsed choice).
"""

from __future__ import annotations

import os

import pytest

# campus_dining_choice is local scratch (studies/ gitignore-whitelist: not shipped), so unlike
# the abm_* shells the study package itself may be absent in a fresh clone / release package —
# skip at import, before the module-level imports below can fail collection.
pytest.importorskip(
    "studies.campus_dining_choice",
    reason="campus_dining_choice is local scratch (not in the gitignore whitelist)",
)

import studies.campus_dining_choice  # noqa: F401,E402  (side effect: registers campus_dining_choice.*)
from skills.sv_workspace import study_paths
from socioverse.engine import build_simulator
from socioverse.schemas import (
    EnvironmentBundle,
    PopulationBundle,
    SimulationConfig,
    StudySpec,
)
from socioverse.validation import validate_handoff
from studies.campus_dining_choice.model import make_campus_dining_choice_bundles, parse_decision


def test_generic_builder_runs_from_bundles(tmp_path):
    study, env_b, pop_b, sim_c = make_campus_dining_choice_bundles(n_agents=150, n_steps=4)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "cdc.duckdb")
    hist = sim.run()

    assert len(hist.rows) == 5                              # step 0..4 (baseline + 4 months)
    assert hist.covers(study.metrics) == []                # every declared metric emitted
    for r in hist.rows:                                     # the three shares always partition the pool
        assert abs(r["share_canteen"] + r["share_delivery"] + r["share_cook"] - 1.0) < 1e-6
    # rising eat-out prices push students toward cooking, and satisfaction erodes over time
    assert hist.rows[-1]["share_cook"] > hist.rows[0]["share_cook"]
    assert hist.rows[-1]["share_delivery"] < hist.rows[0]["share_delivery"]
    assert hist.rows[-1]["mean_satisfaction"] < hist.rows[0]["mean_satisfaction"]


def test_choice_parser_ignores_other_modes_in_reason():
    """Regression: the reason text mentions the canteen & delivery (in Chinese) but the JSON choice is cook — must parse cook."""
    resp = '{"choice": "cook", "satisfaction": 0.7, "reason": "外卖食堂都在涨，自己做饭最省钱"}'
    assert parse_decision(resp)["choice"] == "cook"
    resp2 = '{"choice": "delivery", "satisfaction": 0.6, "reason": "懒得去食堂也不想做饭"}'
    assert parse_decision(resp2)["choice"] == "delivery"


def test_persistent_ids_stable_across_steps(tmp_path):
    _, env_b, pop_b, sim_c = make_campus_dining_choice_bundles(n_agents=20, n_steps=3)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "cdc.duckdb")
    sim.run()
    personas = sim.population.build(seed=42)
    assert [p.agent_id for p in personas] == [f"stu-{i:03d}" for i in range(20)]


def test_shipped_artifacts_assemble_and_run(tmp_path):
    """Once sv-build-* has written the bundles, the committed *.json must validate + run."""
    p = study_paths("studies/campus_dining_choice")
    if not all(os.path.exists(p[k]) for k in ("environment", "population", "simulation")):
        pytest.skip("environment/population/simulation bundles not authored yet (pre sv-build-*)")
    study = validate_handoff(p["study"], StudySpec)
    env_b = validate_handoff(p["environment"], EnvironmentBundle)
    pop_b = validate_handoff(p["population"], PopulationBundle)
    sim_c = validate_handoff(p["simulation"], SimulationConfig)
    sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "scripted"}  # never spend tokens in tests
    sim_c.warm_start = None                                                # exercise a cold assemble+run
    assert study.legacy_simulator == "from_scratch"
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "cdc.duckdb")
    hist = sim.run()
    assert hist.covers(study.metrics) == []
