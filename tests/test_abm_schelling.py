"""Pilot end-to-end + parity for the SocioVerse-ABM umbrella (Path C).

Proves the generic umbrella adapter (abm.* providers) drives a real SocioVerse-ABM task
through Core's LongitudinalSimulator, and that the wrapped rule trajectory exactly
reproduces the native socioverse_abm rule trajectory on the same seed (the adapter adds
no behavioral drift — the parity guarantee the migration playbook requires).
"""
from __future__ import annotations

import importlib

import pytest

import studies.abm_schelling as study  # noqa: F401  (registers abm.* providers via umbrella)
from socioverse.engine import build_simulator
from studies._abm_common import abm_available, load_task

pytestmark = pytest.mark.skipif(
    not abm_available(), reason="SocioVerse-ABM sibling or its deps (numpy, networkx) not available"
)


def _native_trajectory(n_steps: int, seed: int) -> list[dict]:
    """Step the SocioVerse-ABM Schelling task directly (no SocioVerse2) for n_steps."""
    spec = load_task("schelling")                      # ensures SocioVerse-ABM on sys.path
    sm = importlib.import_module(spec.run.__module__)
    rf = importlib.import_module(spec.rule_f.__module__)
    cfg = sm.load_config()
    cfg["seed"] = seed
    if hasattr(rf, "seed"):
        rf.seed(seed)
    env, _ = sm.build(cfg, seed)
    snaps = [env.snapshot()]
    for _t in range(1, n_steps + 1):
        actions = spec.rule_f(env.observe_batch())
        env.apply(actions)
        if hasattr(env, "advance"):
            env.advance()
        snaps.append(env.snapshot())
    return snaps


def _run_sv(n_steps: int, seed: int, tmp_path):
    study_spec, env_b, pop_b, sim_c = study.make_bundles(n_steps=n_steps, seed=seed)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "abm_schelling.duckdb")
    return study_spec, sim, sim.run()


def test_runs_and_segregates(tmp_path):
    study_spec, sim, hist = _run_sv(n_steps=12, seed=42, tmp_path=tmp_path)
    assert len(hist.rows) == 13                          # step 0..12
    assert hist.covers(study_spec.metrics) == []         # every declared metric emitted
    # Schelling's signature: segregation rises far above the 50/50 baseline.
    assert hist.rows[-1]["segregation"] > hist.rows[0]["segregation"]
    assert hist.rows[-1]["segregation"] > 0.6


def test_persistent_ids_stable(tmp_path):
    _, sim, _ = _run_sv(n_steps=3, seed=42, tmp_path=tmp_path)
    personas = sim.population.build(seed=42)
    assert personas[0].agent_id == "schelling-0000"
    assert len({p.agent_id for p in personas}) == len(personas)   # unique persistent ids


def test_parity_with_native(tmp_path):
    n_steps, seed = 12, 42
    _, _, hist = _run_sv(n_steps=n_steps, seed=seed, tmp_path=tmp_path)
    native = _native_trajectory(n_steps, seed)
    assert len(hist.rows) == len(native) == n_steps + 1
    for t, (sv_row, nat) in enumerate(zip(hist.rows, native)):
        for key in ("segregation", "happy_fraction"):
            assert sv_row[key] == pytest.approx(nat[key]), f"step {t} {key} drift"
