"""P3 parity: the adapter re-drives the legacy SegregationModel dynamics identically.

Both paths use a DeterministicLLMClient (no network), the same seed, and the same tract
set, so the per-step segregation-metric trajectories must match exactly — proving the
hybrid adapter splits step() into observe/decide/apply without altering the dynamics.

Skipped automatically if the Chicago data / conda deps are unavailable.
"""

from __future__ import annotations

import sys
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

N_STEPS = 3
SEED = 42
MODEL_KWARGS = dict(max_archetypes=241)


def _resolve_tracts():
    if str(ABM_ROOT) not in sys.path:
        sys.path.insert(0, str(ABM_ROOT))
    from run_prototype import select_prototype_tracts

    return select_prototype_tracts(scale="small")


def _build_legacy(tract_ids, fake):
    from studies.chicago_schelling.adapter.engine_seam import (
        CHICAGO_LEGACY_DEFAULT,
        default_llm_config,
        patched_paths,
    )

    with patched_paths(CHICAGO_LEGACY_DEFAULT, None, None):
        from src.model import SegregationModel

        model = SegregationModel(
            llm_config=default_llm_config(), tract_ids=tract_ids, seed=SEED,
            init_mode="census", **MODEL_KWARGS,
        )
    model.llm = fake
    return model


def test_adapter_matches_legacy_trajectory(tmp_path, monkeypatch):
    # _build_legacy needs default_llm_config() only as constructor plumbing — model.llm is
    # replaced with the fake before any call. A dummy key keeps the test hermetic (no .env
    # required — a fresh clone/package with siblings but no key must still pass parity).
    monkeypatch.setenv("SV_LLM_API_KEY", "sk-parity-dummy-never-called")
    from studies.chicago_schelling.adapter import (
        DeterministicLLMClient,
        build_chicago_simulator,
        make_chicago_bundles,
    )
    from socioverse.io import open_readonly
    from socioverse.schemas import SimulationConfig

    tract_ids = _resolve_tracts()

    # --- legacy reference path: model.step() x N ---
    legacy = _build_legacy(tract_ids, DeterministicLLMClient())
    for _ in range(N_STEPS):
        legacy.step()
    legacy_D = [round(m["D_black_white"], 9) for m in legacy.metrics_history]
    legacy_iso = [round(m["Isolation_black"], 9) for m in legacy.metrics_history]
    n_agents_legacy = len(list(legacy.agents))

    # --- adapter path: LongitudinalSimulator ---
    study, env_bundle, pop_bundle = make_chicago_bundles(scale="small")
    sim_cfg = SimulationConfig(study_id=study.study_id, n_steps=N_STEPS, seed=SEED,
                               decision_ref="chicago.schelling")
    db = tmp_path / "chi.duckdb"
    sim, engine = build_chicago_simulator(
        env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_cfg,
        store_path=db, scale="small", tract_ids=tract_ids, init_mode="census",
        seed=SEED, model_kwargs=MODEL_KWARGS, llm_client=DeterministicLLMClient(),
    )
    hist = sim.run()
    adapter_D = [round(r["D_black_white"], 9) for r in hist.rows]
    n_agents_adapter = len(engine._agent_by_id)

    # structural parity
    assert n_agents_adapter == n_agents_legacy
    assert len(adapter_D) == len(legacy_D) == N_STEPS + 1  # step 0 (init) + N move-steps

    # trajectory parity (exact, deterministic LLM)
    assert adapter_D == legacy_D, f"D_bw mismatch:\n legacy={legacy_D}\n adapter={adapter_D}"
    adapter_iso = [round(r["Isolation_black"], 9) for r in hist.rows]
    assert adapter_iso == legacy_iso

    # DuckDB store is populated + queryable per-field
    con = open_readonly(db)
    panel_n = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    assert panel_n == (N_STEPS + 1) * n_agents_adapter
    # a single household's tract trajectory is recoverable (longitudinal panel)
    any_id = next(iter(engine._agent_by_id))
    traj = con.execute(
        "SELECT step, state->>'tract_id' FROM panel WHERE agent_id = ? ORDER BY step", [any_id]
    ).fetchall()
    assert len(traj) == N_STEPS + 1
    con.close()
