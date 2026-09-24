"""P6: extensibility seams — scenario 3 (file/MCP population, BYO geojson) + scenario 2 (rounds)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from socioverse.abc import DecisionModel, EnvironmentProvider, MetricCollector, PopulationProvider
from socioverse.engine import LongitudinalSimulator
from socioverse.io import DuckDbTrajectoryStore
from socioverse.providers import FilePopulationProvider, McpPopulationProvider
from socioverse.schemas import (
    Action,
    EnvironmentBundle,
    Observation,
    Persona,
    PopulationBundle,
)

from studies.chicago_schelling.adapter.engine_seam import CHICAGO_LEGACY_DEFAULT as ABM_ROOT
from studies.chicago_schelling.adapter.engine_seam import chicago_missing


# ── scenario 3a: user-uploaded personas + MCP population pool ──

def test_file_population_provider(tmp_path):
    csv = tmp_path / "people.csv"
    csv.write_text("agent_id,group_key,weight,age,party\n"
                   "u1,young,2.0,24,Dem\nu2,old,1.0,71,Rep\n", encoding="utf-8")
    bundle = PopulationBundle(study_id="s", provider_ref="file.personas",
                              provider_args={"path": str(csv)})
    personas = FilePopulationProvider(bundle).build(seed=0)
    assert [p.agent_id for p in personas] == ["u1", "u2"]
    assert personas[0].group_key == "young" and personas[0].weight == 2.0
    assert personas[0].attributes["party"] == "Dem"
    # the unique-id invariant is enforceable on the materialized bundle
    PopulationBundle(study_id="s", provider_ref="file.personas", personas=personas)


def test_mcp_population_provider():
    bundle = PopulationBundle(study_id="s", provider_ref="mcp.socioverse_pool",
                              provider_args={"pool": "rednote_v2", "n": 2})

    def fake_pool(args):  # stands in for the SocioVerse-1.0 pool MCP tool
        return [{"agent_id": f"pool-{i}", "group_key": "g", "age": 30 + i} for i in range(args["n"])]

    personas = McpPopulationProvider(bundle, fetch_fn=fake_pool).build(seed=0)
    assert [p.agent_id for p in personas] == ["pool-0", "pool-1"]
    assert personas[1].attributes["age"] == 31
    # without a wired MCP tool, fail loudly with guidance
    with pytest.raises(NotImplementedError, match="fetch_fn"):
        McpPopulationProvider(bundle).build(seed=0)


# ── scenario 2: intra-step interaction rounds ──

def test_interaction_rounds_drive_multiple_exchanges(tmp_path):
    class _Env(EnvironmentProvider):
        bundle = EnvironmentBundle(study_id="s", provider_ref="x",
                                   layers=[])  # no layers needed for the counter
        def reset(self, seed): self.applied = 0
        def advance_to(self, t): return []
        def apply(self, actions): self.applied += 1
        def observe_batch(self, ids, t, round_idx=0):
            return [Observation(agent_id=i, step=t, local_information={"round": round_idx}) for i in ids]
        def agent_state(self, aid): return {"x": 1}

    class _Pop(PopulationProvider):
        bundle = PopulationBundle(study_id="s", provider_ref="x")
        def build(self, seed): return [Persona(agent_id="a"), Persona(agent_id="b")]

    class _Decide(DecisionModel):
        def __init__(self): self.rounds_seen = []
        def decide_batch(self, obs, mem):
            self.rounds_seen.append(obs[0].local_information["round"])
            return [Action(agent_id=o.agent_id, step=o.step, kind="post", source="rule") for o in obs]

    class _Coll(MetricCollector):
        def collect(self, env, actions, t): return {"applied": env.applied}

    env, pop, dec = _Env(), _Pop(), _Decide()
    sim = LongitudinalSimulator(env=env, population=pop, decision=dec,
                                store=DuckDbTrajectoryStore(tmp_path / "s.duckdb"),
                                collector=_Coll(), n_steps=2, interaction_rounds=3, study_id="s")
    sim.run()
    # 2 steps x 3 rounds = 6 decide/apply cycles; rounds cycle 0,1,2 each step
    assert dec.rounds_seen == [0, 1, 2, 0, 1, 2]
    assert env.applied == 6


# ── scenario 3b: bring-your-own city GeoJSON initializes Chicago env ──

@pytest.mark.skipif(bool(chicago_missing()),
                    reason=f"Chicago legacy not available: {', '.join(chicago_missing())}")
def test_bring_your_own_geojson(tmp_path):
    from socioverse.schemas import SimulationConfig
    from studies.chicago_schelling.adapter import (
        DeterministicLLMClient,
        build_chicago_simulator,
        make_chicago_bundles,
    )

    if str(ABM_ROOT) not in sys.path:
        sys.path.insert(0, str(ABM_ROOT))
    from run_prototype import select_prototype_tracts

    tract_ids = select_prototype_tracts(scale="small")

    # User supplies their own data directory containing the city GeoJSON.
    byo = tmp_path / "byo_data"
    byo.mkdir()
    shutil.copy(ABM_ROOT / "processed_data" / "chicago_tracts.geojson",
                byo / "chicago_tracts.geojson")

    study, env_bundle, pop_bundle = make_chicago_bundles(scale="small")
    sim_cfg = SimulationConfig(study_id="chi_byo", n_steps=1, decision_ref="chicago.schelling")
    sim, engine = build_chicago_simulator(
        env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_cfg,
        store_path=tmp_path / "byo.duckdb", scale="small", tract_ids=tract_ids, seed=42,
        model_kwargs={"max_archetypes": 241}, llm_client=DeterministicLLMClient(),
        config_dir=ABM_ROOT / "config", data_dir=byo,    # <-- initialized from user data dir
    )
    hist = sim.run()
    assert len(hist.rows) == 2  # step 0 + 1
    assert "D_black_white" in hist.rows[0] and len(engine._agent_by_id) > 0
