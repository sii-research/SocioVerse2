"""Path B (from-scratch) end-to-end: the opinion_diffusion template assembled by the GENERIC
Core builder from registry refs — no engine-seam, no per-study wiring, no LLM tokens.

This is the proof that a query matching no adapted study can still be implemented from zero and
run along the normal workflow: register 4 abc impls -> author bundles -> engine.build_simulator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import studies.opinion_diffusion  # noqa: F401  (side effect: registers opinion.* providers)
from skills.sv_workspace import study_paths
from socioverse.engine import build_simulator
from socioverse.schemas import (
    EnvironmentBundle,
    PopulationBundle,
    SimulationConfig,
    StudySpec,
)
from socioverse.validation import validate_handoff
from studies.opinion_diffusion.model import make_opinion_bundles

STUDY_DIR = Path(__file__).resolve().parents[1] / "studies" / "opinion_diffusion"


def test_generic_builder_runs_from_bundles(tmp_path):
    study, env_b, pop_b, sim_c = make_opinion_bundles(n_agents=12, n_steps=4, campaign_step=2)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "od.duckdb")
    hist = sim.run()

    assert len(hist.rows) == 5                              # step 0..4 (longitudinal panel)
    assert hist.covers(study.metrics) == []                # every declared metric emitted
    # bounded-confidence peer averaging -> opinions converge (dispersion shrinks)
    assert hist.rows[-1]["opinion_std"] < hist.rows[0]["opinion_std"]
    # the step-2 campaign + media pull lifts the mean above its starting point
    assert hist.rows[-1]["mean_opinion"] > hist.rows[0]["mean_opinion"]


def test_persistent_ids_stable_across_steps(tmp_path):
    _, env_b, pop_b, sim_c = make_opinion_bundles(n_agents=8, n_steps=3)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "od.duckdb")
    sim.run()
    # the same persistent ids are tracked every step (the longitudinal key)
    personas = sim.population.build(seed=42)
    assert [p.agent_id for p in personas] == [f"od-{i:03d}" for i in range(8)]


def _shipped(llm_kind: str | None = None):
    p = study_paths(STUDY_DIR)
    study = validate_handoff(p["study"], StudySpec)
    env_b = validate_handoff(p["environment"], EnvironmentBundle)
    pop_b = validate_handoff(p["population"], PopulationBundle)
    sim_c = validate_handoff(p["simulation"], SimulationConfig)
    if llm_kind is not None:
        sim_c.decision_args = {**sim_c.decision_args, "llm_kind": llm_kind}
    return study, env_b, pop_b, sim_c


def test_shipped_artifacts_assemble_and_run(tmp_path):
    """The committed studies/opinion_diffusion/*.json must validate + run via the generic path.

    The shipped simulation.json selects the real LLM; the test forces the deterministic
    `scripted` decision so it needs no key and makes no network call."""
    study, env_b, pop_b, sim_c = _shipped(llm_kind="scripted")
    assert study.legacy_simulator == "from_scratch"        # it's a Path-B study
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "od.duckdb")
    hist = sim.run()
    assert hist.covers(study.metrics) == []


@pytest.mark.llm
def test_shipped_artifacts_run_on_live_llm(tmp_path):
    """Same artifacts, unmodified (the real LLM decision). Opt-in: SV_RUN_LLM_TESTS=1 plus
    SV_LLM_API_KEY (and SV_LLM_BASE_URL for a non-OpenAI endpoint)."""
    pytest.importorskip("openai")
    study, env_b, pop_b, sim_c = _shipped()
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "od.duckdb")
    hist = sim.run()
    assert hist.covers(study.metrics) == []


def test_prompt_language_is_selectable():
    """The template prompts in English by default; the shipped run records its Chinese prompt."""
    import re

    from socioverse.schemas import Observation
    from studies.opinion_diffusion.model import BoundedConfidenceDecision, build_opinion_prompt

    ob = Observation(agent_id="od-000", step=2,
                     local_physical={"own_opinion": 0.4, "neighbor_opinions": [0.3, 0.55]},
                     macro_physical={"media_pressure": 0.25}, macro_information={"campaign": "go"})
    cjk = re.compile(r"[一-鿿]")
    assert not cjk.search(build_opinion_prompt(ob)) and '"opinion"' in build_opinion_prompt(ob)
    assert cjk.search(build_opinion_prompt(ob, "zh"))

    seen = []
    dec = BoundedConfidenceDecision()
    assert dec.prompt_lang == "en"
    dec.llm_kind, dec.llm = "openai", lambda prompt: seen.append(prompt) or '{"opinion": 0.6, "reason": "ok"}'
    (act,) = dec.decide_batch([ob], {})
    assert act.source == "llm" and act.payload["opinion"] == 0.6 and not cjk.search(seen[0])
    with pytest.raises(ValueError):
        BoundedConfidenceDecision(prompt_lang="fr")
    assert _shipped()[3].decision_args["prompt_lang"] == "zh"


def test_llm_reason_reaches_the_panel_and_scripted_payload_is_unchanged(tmp_path):
    """In LLM mode the model's reason is stored in action_payload (panel / dashboard drill-down);
    a reply that does not parse falls back to the rule without one, and scripted mode keeps
    {"opinion": x} only."""
    import duckdb

    replies = iter(['{"opinion": 0.61, "reason": "neighbours lean for"}', "no number here"] * 100)
    study, env_b, pop_b, sim_c = make_opinion_bundles(n_agents=4, n_steps=1, campaign_step=1)
    sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "scripted"}
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "llm.duckdb")
    sim.decision.llm_kind, sim.decision.llm = "openai", lambda prompt: next(replies)
    sim.run()
    con = duckdb.connect(str(tmp_path / "llm.duckdb"), read_only=True)
    rows = con.execute("SELECT agent_id, action_payload FROM panel WHERE step = 1 "
                       "ORDER BY agent_id").fetchall()
    con.close()
    import json
    payloads = [json.loads(p) for _a, p in rows]
    assert {"opinion": 0.61, "reason": "neighbours lean for"} in payloads
    assert any(set(p) == {"opinion"} for p in payloads)          # the rule fallback

    s2, env2, pop2, sim2 = make_opinion_bundles(n_agents=4, n_steps=1, campaign_step=1)
    sim_s = build_simulator(env_bundle=env2, pop_bundle=pop2, sim_config=sim2,
                            store_path=tmp_path / "scripted.duckdb")
    sim_s.run()
    con = duckdb.connect(str(tmp_path / "scripted.duckdb"), read_only=True)
    keys = {tuple(sorted(json.loads(p))) for (p,) in
            con.execute("SELECT action_payload FROM panel WHERE step = 1").fetchall()}
    con.close()
    assert keys == {("opinion",)}
