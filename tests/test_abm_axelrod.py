"""End-to-end + parity for abm_axelrod (umbrella).

Each action carries a nested per-opponent move dict ({"moves": {opp_id: "C"/"D"}}),
exercising non-flat Action payloads through the adapter. The random strategy uses the
module RNG, so the parity reference consumes it in the runtime's agent-id order.
"""
from __future__ import annotations

import importlib

import pytest

import studies.abm_axelrod as study  # noqa: F401  (registers abm.* providers via umbrella)
from socioverse.engine import build_simulator
from studies._abm_common import abm_available, load_task

pytestmark = pytest.mark.skipif(
    not abm_available(), reason="SocioVerse-ABM sibling or its deps (numpy, networkx) not available"
)

TASK = "axelrod"
KEYS = ("cooperation_rate", "mean_score")


def _native_trajectory(n_steps: int, seed: int) -> list[dict]:
    spec = load_task(TASK)
    sm = importlib.import_module(spec.run.__module__)
    rf = importlib.import_module(spec.rule_f.__module__)
    cfg = sm.load_config()
    cfg["seed"] = seed
    if hasattr(rf, "seed"):
        rf.seed(seed)
    env, _ = sm.build(cfg, seed)
    snaps = [env.snapshot()]
    for _t in range(1, n_steps + 1):
        obs = sorted(env.observe_batch(), key=lambda o: o.agent_id)
        env.apply(spec.rule_f(obs))
        if hasattr(env, "advance"):
            env.advance()
        snaps.append(env.snapshot())
    return snaps


def _run_sv(n_steps: int, seed: int, tmp_path):
    s, env_b, pop_b, sim_c = study.make_bundles(n_steps=n_steps, seed=seed)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "abm_axelrod.duckdb")
    return s, sim, sim.run()


def test_runs(tmp_path):
    s, _sim, hist = _run_sv(20, 42, tmp_path)
    assert len(hist.rows) == 21
    assert hist.covers(s.metrics) == []
    assert 0.0 <= hist.rows[-1]["cooperation_rate"] <= 1.0
    assert hist.rows[-1]["mean_score"] > 0.0


def test_persistent_ids(tmp_path):
    _, sim, _ = _run_sv(3, 42, tmp_path)
    personas = sim.population.build(seed=42)
    assert personas[0].agent_id == "axelrod-0000"
    assert personas[0].group_key is not None             # group_field="strategy"
    assert len({p.agent_id for p in personas}) == len(personas)


def test_parity_with_native(tmp_path):
    _, _, hist = _run_sv(20, 42, tmp_path)
    native = _native_trajectory(20, 42)
    assert len(hist.rows) == len(native)
    for t, (sv_row, nat) in enumerate(zip(hist.rows, native)):
        for key in KEYS:
            assert sv_row[key] == pytest.approx(nat[key]), f"step {t} {key} drift"
