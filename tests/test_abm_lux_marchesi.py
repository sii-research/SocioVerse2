"""End-to-end + parity for abm_lux_marchesi (umbrella).

The herding rule draws a per-trader sigmoid coin (module RNG), so the parity reference
consumes that RNG in the runtime's persistent-agent-id order (sort obs by agent_id).
"""
from __future__ import annotations

import importlib

import pytest

import studies.abm_lux_marchesi as study  # noqa: F401  (registers abm.* providers)
from socioverse.engine import build_simulator
from studies._abm_common import abm_available, load_task

pytestmark = pytest.mark.skipif(
    not abm_available(), reason="SocioVerse-ABM sibling or its deps (numpy, networkx) not available"
)

TASK = "lux_marchesi"
KEYS = ("price", "value", "opinion_index", "log_return")


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
                          store_path=tmp_path / "abm_lux.duckdb")
    return s, sim, sim.run()


def test_runs_and_fluctuates(tmp_path):
    s, _sim, hist = _run_sv(50, 42, tmp_path)
    assert len(hist.rows) == 51
    assert hist.covers(s.metrics) == []
    prices = [r["price"] for r in hist.rows]
    assert max(prices) > min(prices)                       # the price actually moves


def test_persistent_ids(tmp_path):
    _, sim, _ = _run_sv(3, 42, tmp_path)
    personas = sim.population.build(seed=42)
    assert personas[0].agent_id == "lux_marchesi-0000"
    assert len({p.agent_id for p in personas}) == len(personas)


def test_parity_with_native(tmp_path):
    _, _, hist = _run_sv(50, 42, tmp_path)
    native = _native_trajectory(50, 42)
    assert len(hist.rows) == len(native)
    for t, (sv_row, nat) in enumerate(zip(hist.rows, native)):
        for key in KEYS:
            assert sv_row[key] == pytest.approx(nat[key]), f"step {t} {key} drift"
