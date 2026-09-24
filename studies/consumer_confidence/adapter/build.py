"""Factory wiring for the ConsumerSim confidence study."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from socioverse.engine import LongitudinalSimulator
from socioverse.io import DuckDbTrajectoryStore
from socioverse.schemas import (
    EnvironmentBundle,
    EnvironmentLayer,
    InteractionStructure,
    Persona,
    PopulationBundle,
    ResourceManifest,
    SimulationConfig,
    StudySpec,
)

from .decision import ConsumerConfidenceDecisionModel
from .engine_seam import ConsumerSimEngine
from .metrics import CONSUMER_CONFIDENCE_METRICS, ConsumerConfidenceMetricCollector
from .providers import ConsumerConfidenceEnvironmentProvider, ConsumerConfidencePopulationProvider


def make_consumer_confidence_bundles(
    study_id: str = "consumer_confidence",
    *,
    region: str = "US",
    target_months: list[str] | None = None,
    as_of_dates: list[str] | None = None,
    personas: list[Persona] | None = None,
    consumersim_root: str | Path | None = None,
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig, ResourceManifest]:
    months = list(target_months or ["2026-06"])
    as_of = list(as_of_dates or [f"{months[0]}-20"])
    provider_args = {
        "region": region.upper(),
        "target_months": months,
        "as_of_dates": as_of,
    }
    if consumersim_root is not None:
        provider_args["consumersim_root"] = str(consumersim_root)

    study = StudySpec(
        study_id=study_id,
        title=f"{region.upper()} Consumer Confidence Forecast via ConsumerSim",
        research_question="Forecast monthly consumer confidence from a fixed SocioVerse population and point-in-time information.",
        hypothesis="Consumer confidence responds to contemporaneous news and indicators, with group-level uncertainty propagated through Bayesian expansion.",
        study_type="longitudinal",
        n_steps=len(months),
        seed=42,
        metrics=CONSUMER_CONFIDENCE_METRICS,
        domain="consumer-confidence",
        tags=["ConsumerSim", "forecast", "survey", "Bayesian", "population-pool"],
        legacy_simulator="ConsumerSim-Consumer-Confidence-Forecast/consumer_pipeline",
        provider_refs=["consumersim.env", "socioverse.population", "consumersim.decision", "consumersim.collector"],
        adjustable_params=["region", "target_months", "as_of_dates", "news/indicator/history inputs", "core_ratio", "prediction provider"],
        status="draft",
    )
    env_bundle = EnvironmentBundle(
        study_id=study_id,
        provider_ref="consumersim.env",
        provider_args=dict(provider_args),
        layers=[
            EnvironmentLayer(
                name="consumer_information",
                modality="information",
                scope="macro",
                dynamics="scheduled",
                description="Point-in-time news and indicator snapshot for the target month.",
            ),
            EnvironmentLayer(
                name="consumer_demographics",
                modality="physical",
                scope="local",
                dynamics="static",
                description="SocioVerse persona demographics used by ConsumerSim.",
            ),
        ],
    )
    pop_bundle = PopulationBundle(
        study_id=study_id,
        provider_ref="socioverse.population",
        personas=list(personas or []),
        interaction=InteractionStructure(kind="none"),
        provider_args={},
    )
    sim_config = SimulationConfig(
        study_id=study_id,
        n_steps=len(months),
        seed=42,
        decision_ref="consumersim.decision",
        collector_ref="consumersim.collector",
        interaction_rounds=1,
    )
    resources = ResourceManifest(
        study_id=study_id,
        datasets=[],
        tools=[
            {
                "name": "ConsumerSim external checkout",
                "description": "Resolved from SV_CONSUMERSIM_ROOT or a sibling ConsumerSim-Consumer-Confidence-Forecast directory.",
                "spec": {"default_region": region.upper()},
            }
        ],
    )
    return study, env_bundle, pop_bundle, sim_config, resources


def build_consumer_confidence_simulator(
    *,
    env_bundle: EnvironmentBundle,
    pop_bundle: PopulationBundle,
    sim_config: SimulationConfig,
    store_path: str | Path,
    region: str | None = None,
    target_months: list[str] | None = None,
    as_of_dates: list[str] | None = None,
    consumersim_root: str | Path | None = None,
    config_path: str | Path | None = None,
    config_overrides: dict[str, Any] | None = None,
    seed: int | None = None,
    on_step: Any = None,
) -> tuple[LongitudinalSimulator, ConsumerSimEngine]:
    args = dict(env_bundle.provider_args)
    engine = ConsumerSimEngine(
        region=region or args.get("region", "US"),
        target_months=target_months or args.get("target_months") or [f"2026-06"],
        as_of_dates=as_of_dates or args.get("as_of_dates") or [],
        consumersim_root=consumersim_root or args.get("consumersim_root"),
        config_path=config_path or args.get("config_path"),
        config_overrides=config_overrides or args.get("config_overrides") or {},
        seed=seed if seed is not None else sim_config.seed,
    )
    env = ConsumerConfidenceEnvironmentProvider(engine, env_bundle)
    pop = ConsumerConfidencePopulationProvider(engine, pop_bundle)
    decision = ConsumerConfidenceDecisionModel(engine)
    collector = ConsumerConfidenceMetricCollector(engine)
    store = DuckDbTrajectoryStore(store_path, study_id=sim_config.study_id)
    sim = LongitudinalSimulator(
        env=env,
        population=pop,
        decision=decision,
        store=store,
        collector=collector,
        n_steps=sim_config.n_steps,
        seed=sim_config.seed,
        interaction_rounds=sim_config.interaction_rounds,
        metric_columns=CONSUMER_CONFIDENCE_METRICS + ["step", "events"],
        study_id=sim_config.study_id,
        on_step=on_step,
    )
    return sim, engine
