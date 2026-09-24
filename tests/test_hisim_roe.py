"""hisim_roe (Path B, from-scratch HiSim port) — no-API end-to-end, via the generic Core builder.

Proves the four abc + committed artifacts assemble and run the longitudinal loop with zero LLM
tokens (core DecisionModel in deterministic mode="fake"). Real LLM decision = milestone 2.
"""

from __future__ import annotations

import studies.hisim_roe  # noqa: F401  (registers hisim.* providers)
from skills.sv_workspace import study_paths
from socioverse.engine import build_simulator
from socioverse.schemas import (
    EnvironmentBundle,
    PopulationBundle,
    SimulationConfig,
    StudySpec,
)
from socioverse.validation import validate_handoff
from studies.hisim_roe.model import HISIM_METRICS, is_core, make_hisim_bundles


def test_generic_builder_runs_from_bundles(tmp_path):
    study, env_b, pop_b, sim_c = make_hisim_bundles(n_core=8, n_ord=12, n_steps=4, bc_bound=0.3)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "hisim.duckdb")
    hist = sim.run()

    assert len(hist.rows) == 5                       # steps 0..4 (longitudinal panel)
    assert hist.covers(study.metrics) == []          # every declared metric emitted
    # ordinary BCM assimilation must not *increase* opinion dispersion
    assert hist.rows[-1]["diversity"] <= hist.rows[0]["diversity"] + 1e-9


def test_hybrid_population_split_and_mirror(tmp_path):
    _, env_b, pop_b, sim_c = make_hisim_bundles(n_core=8, n_ord=12, n_steps=3)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "hisim.duckdb")
    personas = sim.population.build(seed=42)
    assert sum(1 for p in personas if is_core(p.agent_id)) == 8       # core LLM users
    assert sum(1 for p in personas if not is_core(p.agent_id)) == 12  # ordinary ABM users
    # persistent ids stable across rebuilds (the longitudinal key)
    assert [p.agent_id for p in personas] == [p.agent_id for p in sim.population.build(seed=42)]


def test_shipped_artifacts_assemble_and_run(tmp_path):
    """The committed studies/hisim_roe/*.json must validate + run via the generic path."""
    p = study_paths("studies/hisim_roe")
    study = validate_handoff(p["study"], StudySpec)
    env_b = validate_handoff(p["environment"], EnvironmentBundle)
    pop_b = validate_handoff(p["population"], PopulationBundle)
    sim_c = validate_handoff(p["simulation"], SimulationConfig)
    sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "scripted"}  # never spend tokens in tests
    assert study.legacy_simulator == "from_scratch"   # it's a Path-B study
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "hisim.duckdb")
    hist = sim.run()
    # The shipped trajectory is external data (the digitized aggregate series of tech report §5.7; study.metrics describes that
    # data: sim_sentiment/gt_sentiment/…); the live engine path must cover the collector's own contract columns —
    # the two sets of metric names serve different purposes, see build_from_techreport.py.
    assert hist.covers(list(HISIM_METRICS)) == []
