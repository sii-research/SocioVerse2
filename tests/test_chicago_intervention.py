"""P4 mechanics (deterministic, no tokens): scheduled intervention + scenario-1 broadcasts.

Verifies, through the real Chicago environment:
  - a ScheduledEvent mutates the live GeoDataFrame at its step (subway: cta_stations += 2),
  - a macro Broadcast (policy A) reaches EVERY agent's macro_information,
  - a local Broadcast (policy B, geoid-scoped) reaches ONLY the target tract's agents,
  - both are spliced into the LLM tract description (info injection for the reused phases),
  - the event is logged to the DuckDB events table during a full run.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

from studies.chicago_schelling.adapter.engine_seam import CHICAGO_LEGACY_DEFAULT as ABM_ROOT

# The legacy model needs the `chicago` extra; skip (not fail) when it is not installed.
for _mod in ("geopandas", "mesa", "openai"):
    pytest.importorskip(_mod)
pytestmark = pytest.mark.skipif(
    not (ABM_ROOT / "processed_data" / "chicago_tracts.geojson").exists(),
    reason="Chicago legacy data not available (clone SocioVerse-ABM as a sibling)",
)
MODEL_KWARGS = dict(max_archetypes=241)


def _resolve_tracts():
    if str(ABM_ROOT) not in sys.path:
        sys.path.insert(0, str(ABM_ROOT))
    from run_prototype import select_prototype_tracts

    return select_prototype_tracts(scale="small")


def test_intervention_and_audience_scoped_broadcasts(tmp_path):
    from socioverse.io import open_readonly
    from socioverse.schemas import Broadcast, ScheduledEvent, SimulationConfig
    from studies.chicago_schelling.adapter import (
        DeterministicLLMClient,
        build_chicago_simulator,
        make_chicago_bundles,
    )

    tract_ids = _resolve_tracts()

    # Probe build to pick a target tract that actually has households.
    from studies.chicago_schelling.adapter import ChicagoEngine

    probe = ChicagoEngine(scale="small", tract_ids=tract_ids, seed=42,
                          model_kwargs=MODEL_KWARGS, llm_client=DeterministicLLMClient())
    probe.ensure_built()
    target = Counter(a.tract_id for a in probe.model.agents).most_common(1)[0][0]
    other = next(t for t in tract_ids if t != target)

    STEP = 2
    events = [ScheduledEvent(
        at_step=STEP, target_layer="tract_local", op="add", property_name="cta_stations",
        value=2, selector={"geoid_list": [target]}, note="open subway in target tract at step 2",
    )]
    broadcasts = [
        Broadcast(message_id="A", channel="news", content="POLICYA citywide transit expansion",
                  at_step=STEP, ttl=5, audience="all"),
        Broadcast(message_id="B", channel="ward_notice", content="POLICYB local rezoning notice",
                  at_step=STEP, ttl=5, audience={"geoid_list": [target]}),
    ]
    study, env_bundle, pop_bundle = make_chicago_bundles(
        scale="small", scheduled_events=events, broadcasts=broadcasts)
    sim_cfg = SimulationConfig(study_id=study.study_id, n_steps=3, decision_ref="chicago.schelling")
    db = tmp_path / "chi_intervention.duckdb"
    sim, engine = build_chicago_simulator(
        env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_cfg, store_path=db,
        scale="small", tract_ids=tract_ids, seed=42, model_kwargs=MODEL_KWARGS,
        llm_client=DeterministicLLMClient(),
    )

    # Drive the environment manually (no decide/apply) to inspect observations.
    personas = sim.population.build(0)
    sim.env.reset(0)
    ids = [p.agent_id for p in personas]
    env = sim.env
    gdf = env.model.environment.gdf
    cta_before = float(gdf.at[target, "cta_stations"])

    # Step 1: nothing active yet.
    env.advance_to(1)
    obs1 = env.observe_batch(ids, 1)
    assert all(not o.macro_information and not o.local_information for o in obs1)

    # Step 2: intervention fires.
    fired = env.advance_to(STEP)
    assert any("subway" in (e.note or "") for e in fired)
    assert float(gdf.at[target, "cta_stations"]) == cta_before + 2  # physical change

    obs2 = env.observe_batch(ids, STEP)
    assert all(o.macro_information for o in obs2)  # policy A broadcast to everyone
    tgt_obs = [o for o in obs2 if engine._agent_by_id[o.agent_id].tract_id == target]
    oth_obs = [o for o in obs2 if engine._agent_by_id[o.agent_id].tract_id == other]
    assert tgt_obs and all(o.local_information for o in tgt_obs)   # policy B only in target
    assert oth_obs and all(not o.local_information for o in oth_obs)

    # Info injection into the LLM-facing description (what the reused phases read).
    desc_t = env.model.environment.describe_tract_with_context_for_llm(target)
    assert "POLICYA" in desc_t and "POLICYB" in desc_t
    desc_o = env.model.environment.describe_tract_with_context_for_llm(other)
    assert "POLICYA" in desc_o and "POLICYB" not in desc_o

    # A full run logs the intervention to the DuckDB events table.
    hist = sim.run()
    con = open_readonly(db)
    notes = [r[0] for r in con.execute("SELECT note FROM events").fetchall()]
    con.close()
    assert any("subway" in n for n in notes)
    assert any("POLICYA" in n for n in notes)
