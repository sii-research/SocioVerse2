"""ConsumerSim adapter tests.

The adapter must keep ConsumerSim's monthly forecast pipeline intact while replacing
ConsumerSim's population construction with SocioVerse personas.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from socioverse.schemas import EnvironmentBundle, PopulationBundle, SimulationConfig
from studies.consumer_confidence.adapter import (
    build_consumer_confidence_simulator,
    make_consumer_confidence_bundles,
)
from studies.consumer_confidence.adapter.engine_seam import (
    ConsumerSimEngine,
    _resolve_consumersim_root,
)

# The seam's own resolver: SV_CONSUMERSIM_ROOT from the process env or `.env`, else the
# sibling clone next to this repo.
CONSUMERSIM_ROOT = _resolve_consumersim_root()

pytestmark = pytest.mark.skipif(
    not (CONSUMERSIM_ROOT / "consumer_pipeline" / "orchestrator.py").exists(),
    reason="ConsumerSim checkout not available",
)


def _population_csv(path: Path, n: int = 120) -> Path:
    age = ["18-34", "35-54", "55+"]
    income = ["low", "middle", "high"]
    education = ["secondary", "tertiary"]
    location = ["Northeast", "Midwest", "South", "West"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "consumer_id",
                "age_group",
                "income_group",
                "education_group",
                "location_group",
                "weight",
            ],
        )
        writer.writeheader()
        for i in range(n):
            writer.writerow(
                {
                    "consumer_id": f"pool-{i + 1:04d}",
                    "age_group": age[i % len(age)],
                    "income_group": income[(i // 3) % len(income)],
                    "education_group": education[(i // 9) % len(education)],
                    "location_group": location[(i // 18) % len(location)],
                    "weight": "1.0",
                }
            )
    return path


def _load_external_pipeline():
    if str(CONSUMERSIM_ROOT) not in sys.path:
        sys.path.insert(0, str(CONSUMERSIM_ROOT))
    from consumer_pipeline.config import load_config
    from consumer_pipeline.orchestrator import ConsumerPipeline

    return load_config, ConsumerPipeline


def test_adapter_uses_sociverse_population_ids(tmp_path):
    population_csv = _population_csv(tmp_path / "population.csv", n=40)
    _, env_bundle, pop_bundle, sim_config, _ = make_consumer_confidence_bundles(
        region="US",
        target_months=["2026-06"],
        as_of_dates=["2026-06-20"],
        consumersim_root=CONSUMERSIM_ROOT,
    )
    pop_bundle = PopulationBundle.model_validate(
        {
            **pop_bundle.model_dump(),
            "personas": [],
            "provider_args": {"source_csv": str(population_csv)},
        }
    )
    sim, engine = build_consumer_confidence_simulator(
        env_bundle=env_bundle,
        pop_bundle=pop_bundle,
        sim_config=sim_config,
        store_path=tmp_path / "adapter.duckdb",
        consumersim_root=CONSUMERSIM_ROOT,
    )

    sim.run()

    assert len(engine.population) == 40
    assert set(engine.population_by_id) == {f"pool-{i + 1:04d}" for i in range(40)}
    assert all(not consumer.consumer_id.startswith("us-") for consumer in engine.population)


def test_adapter_matches_consumersim_pipeline_for_same_population(tmp_path):
    load_config, ConsumerPipeline = _load_external_pipeline()
    population_csv = _population_csv(tmp_path / "population.csv", n=120)

    config = load_config(CONSUMERSIM_ROOT / "configs" / "us.yaml")
    config["population"]["size"] = 120
    config["population"]["source_csv"] = str(population_csv)
    config["output"]["directory"] = str(tmp_path / "legacy_output")
    expected, _ = ConsumerPipeline(config).run("2026-06", "2026-06-20")

    _, env_bundle, pop_bundle, sim_config, _ = make_consumer_confidence_bundles(
        region="US",
        target_months=["2026-06"],
        as_of_dates=["2026-06-20"],
        consumersim_root=CONSUMERSIM_ROOT,
    )
    pop_bundle = PopulationBundle.model_validate(
        {
            **pop_bundle.model_dump(),
            "personas": [],
            "provider_args": {"source_csv": str(population_csv)},
        }
    )
    env_bundle = EnvironmentBundle.model_validate(env_bundle.model_dump())
    sim_config = SimulationConfig.model_validate(sim_config.model_dump())

    sim, engine = build_consumer_confidence_simulator(
        env_bundle=env_bundle,
        pop_bundle=pop_bundle,
        sim_config=sim_config,
        store_path=tmp_path / "adapter.duckdb",
        consumersim_root=CONSUMERSIM_ROOT,
    )
    history = sim.run()
    actual = history.rows[1]

    assert actual["population_size"] == expected.population_size == 120
    assert actual["core_size"] == expected.core_size
    assert actual["raw_score"] == expected.raw_score
    assert actual["corrected_score"] == expected.corrected_score
    for question, score in expected.question_scores.items():
        assert actual[f"score_{question}"] == score
    assert engine.results[1]["group_posteriors"] == expected.group_posteriors


def test_predictor_takes_key_and_endpoint_from_dotenv(tmp_path, monkeypatch):
    """The real ConsumerSim predictor sees SV_LLM_API_KEY / SV_LLM_BASE_URL kept only in `.env`."""
    from socioverse import external_events

    for name in ("SV_LLM_API_KEY", "SV_LLM_BASE_URL"):
        monkeypatch.setenv(name, "unset-by-test")    # recorded, so the teardown restores it
        monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "SV_LLM_API_KEY=sk-from-dotenv\nSV_LLM_BASE_URL=http://127.0.0.1:18791/v1\n",
        encoding="utf-8")
    monkeypatch.setenv("SV_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(external_events, "_REPO_ROOT", tmp_path / "not-a-checkout")

    engine = ConsumerSimEngine(
        consumersim_root=CONSUMERSIM_ROOT,
        config_overrides={
            "prediction": {"provider": "openai_compatible", "model": "test-model",
                           "endpoint": "https://api.openai.com/v1/chat/completions"},
            "credentials": {"model_api_key": "SV_LLM_API_KEY"},
        },
    )
    engine.ensure_loaded()
    predictor = engine._build_predictor()
    assert predictor.endpoint == "http://127.0.0.1:18791/v1/chat/completions"
    assert predictor.api_key == "sk-from-dotenv"
