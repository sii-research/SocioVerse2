"""abm.decision follows native SocioVerse-ABM for the LLM model and for hybrid mode.

- llm / hybrid: the task's llm_f is configured from its config.yaml (with the bundle's config
  overrides), so ``behavior.llm_model`` (and ``llm_behavior`` for schelling / civil_violence)
  reaches the LLM calls, as in the native ``model.run``.
- hybrid: SocioVerse-ABM's ``hybrid_decide``; the default policy routes every agent to the rule
  (no LLM call, identical to a rule run); ``llm_fraction`` routes a fixed share of agents to llm_f.
"""
from __future__ import annotations

import importlib
from collections import Counter

import pytest

import studies.abm_hegselmann_krause as hk_study  # noqa: F401  (registers abm.* providers)
from socioverse.engine import build_simulator
from studies._abm_common import abm_available, load_task
from studies._abm_common.providers import AbmDecisionModel

pytestmark = pytest.mark.skipif(
    not abm_available(), reason="SocioVerse-ABM sibling or its deps (numpy, networkx) not available"
)

SMALL = {"population": {"n": 20}}


class FakeLLM:
    """Stands in for socioverse_abm.behavior_engine.llm_f: records the model of every call."""

    def __init__(self, reply: str = "0.5"):
        self.reply = reply
        self.models: list[str] = []

    def generate(self, model, prompt, **_kw):
        self.models.append(model)
        return self.reply


def _llm_module(task: str):
    return importlib.import_module(load_task(task).llm_f.__module__)


@pytest.fixture(autouse=True)
def _restore_llm_globals():
    """configure() sets module globals in the task's llm_f; put them back after each test."""
    saved = {}
    for task in ("hegselmann_krause", "schelling"):
        mod = _llm_module(task)
        saved[task] = {k: getattr(mod, k) for k in ("_MODEL", "_BEHAVIOR") if hasattr(mod, k)}
    yield
    for task, attrs in saved.items():
        for k, v in attrs.items():
            setattr(_llm_module(task), k, v)


def _run(tmp_path, *, mode, llm=None, config=None, n_steps=2, **kw):
    overrides = {**SMALL, **(config or {})}
    _s, env_b, pop_b, sim_c = hk_study.make_bundles(n_steps=n_steps, seed=7, mode=mode,
                                                    config_overrides=overrides, **kw)
    sim_c.decision_args["llm"] = llm
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / f"{mode}.duckdb")
    per_step: list[dict[str, str]] = []
    decide = sim.decision.decide_batch

    def counted(obs, memories):
        actions = decide(obs, memories)
        per_step.append({a.agent_id: a.source for a in actions})
        return actions

    sim.decision.decide_batch = counted
    return sim.run(), per_step


def test_configure_receives_the_config_model(monkeypatch):
    calls = []
    monkeypatch.setattr(_llm_module("hegselmann_krause"), "configure",
                        lambda model: calls.append((model,)))
    AbmDecisionModel("hegselmann_krause", mode="rule")
    assert calls == []                                   # rule mode never touches the LLM layer
    AbmDecisionModel("hegselmann_krause", mode="llm")
    AbmDecisionModel("hegselmann_krause", mode="hybrid",
                     config={"behavior": {"llm_model": "gpt-4o-mini"}})
    assert calls == [("gpt-4o",), ("gpt-4o-mini",)]      # config.yaml default, then the override


def test_configure_receives_llm_behavior_where_the_task_takes_it(monkeypatch):
    calls = []
    monkeypatch.setattr(_llm_module("schelling"), "configure",
                        lambda model, llm_behavior="tbf": calls.append((model, llm_behavior)))
    dec = AbmDecisionModel("schelling", mode="llm",
                           config={"behavior": {"llm_model": "m-small", "llm_behavior": "lbf"}})
    assert calls == [("m-small", "lbf")] and dec.llm_model == "m-small"


def test_llm_calls_use_the_configured_model_not_the_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SV_LLM_MODEL", "from-env")      # config.yaml wins, as in native sv-abm run
    fake = FakeLLM()
    _hist, per_step = _run(tmp_path, mode="llm", llm=fake,
                           config={"behavior": {"llm_model": "gpt-4o-mini"}})
    assert len(fake.models) == 20 * 2
    assert set(fake.models) == {"gpt-4o-mini"}
    assert all(src == "llm" for step in per_step for src in step.values())


def test_hybrid_defaults_to_the_rule_for_every_agent(tmp_path):
    fake = FakeLLM()
    hyb, hyb_src = _run(tmp_path, mode="hybrid", llm=fake, n_steps=4)
    rule, _ = _run(tmp_path, mode="rule", n_steps=4)
    assert fake.models == []                             # no LLM call, like native --mode hybrid
    assert all(src == "rule" for step in hyb_src for src in step.values())
    for h, r in zip(hyb.rows, rule.rows):
        assert h == r


def test_hybrid_llm_fraction_routes_a_fixed_share(tmp_path):
    fake = FakeLLM()
    _hist, per_step = _run(tmp_path, mode="hybrid", llm=fake, llm_fraction=0.5, n_steps=3)
    llm_ids = [frozenset(a for a, s in step.items() if s == "llm") for step in per_step]
    assert len(set(llm_ids)) == 1                        # the same agents at every step
    n_llm = len(llm_ids[0])
    assert 0 < n_llm < 20
    assert len(fake.models) == n_llm * 3
    assert Counter(per_step[0].values()) == {"llm": n_llm, "rule": 20 - n_llm}

    fake_all = FakeLLM()
    _h, all_src = _run(tmp_path, mode="hybrid", llm=fake_all, llm_fraction=1.0, n_steps=1)
    assert set(all_src[0].values()) == {"llm"} and len(fake_all.models) == 20


def test_unknown_mode_and_bad_fraction_are_rejected():
    with pytest.raises(ValueError):
        AbmDecisionModel("hegselmann_krause", mode="mixed")
    with pytest.raises(ValueError):
        AbmDecisionModel("hegselmann_krause", mode="hybrid", llm_fraction=1.5)
