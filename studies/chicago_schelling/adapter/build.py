"""Wire the Chicago study into a LongitudinalSimulator with one shared ChicagoEngine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from socioverse.engine import LongitudinalSimulator
from socioverse.env_layers import InformationEnvironment
from socioverse.io import DuckDbTrajectoryStore
from socioverse.schemas import (
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    PopulationBundle,
    ScheduledEvent,
    SimulationConfig,
    StudySpec,
)

from .decision import SchellingDecisionModel
from .engine_seam import ChicagoEngine
from .metrics import SegregationMetricCollector
from .providers import (
    ChicagoEnvironmentProvider,
    ChicagoPopulationProvider,
    chicago_audience_matcher,
)

CHI_METRICS = [
    "D_black_white", "D_hispanic_white", "D_asian_white",
    "Isolation_black", "Isolation_white", "Isolation_hispanic",
    "n_movers", "pct_pop_moved", "gap_reduction_pct", "mover_alignment_rate",
]


def make_chicago_bundles(
    study_id: str = "chicago_schelling",
    *,
    scale: str = "small",
    init_mode: str = "census",
    scheduled_events: list[ScheduledEvent] | None = None,
    broadcasts: list[Broadcast] | None = None,
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle]:
    """Author the three validated artifacts for the Chicago study."""
    layers = [
        EnvironmentLayer(name="city_race_share", modality="physical", scope="macro",
                         dynamics="endogenous", description="city-wide racial shares"),
        EnvironmentLayer(name="tract_local", modality="physical", scope="local",
                         dynamics="endogenous",
                         description="per-tract demographics + 1-hop Queen surrounding area"),
    ]
    if broadcasts:
        layers += [
            EnvironmentLayer(name="news", modality="information", scope="macro",
                             dynamics="scheduled", description="city news / policy broadcasts"),
            EnvironmentLayer(name="ward_notice", modality="information", scope="local",
                             dynamics="scheduled", description="tract-scoped notices"),
        ]
    env_bundle = EnvironmentBundle(
        study_id=study_id,
        provider_ref="chicago.env",
        provider_args={"scale": scale, "init_mode": init_mode},
        layers=layers,
        scheduled_events=scheduled_events or [],
        information_program=InformationProgram(broadcasts=broadcasts or []),
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="chicago.census",
        provider_args={"scale": scale},
    )
    study = StudySpec(study_id=study_id, title="Chicago Schelling segregation",
                      study_type="longitudinal", metrics=CHI_METRICS)
    return study, env_bundle, pop_bundle


def build_chicago_simulator(
    *,
    env_bundle: EnvironmentBundle,
    pop_bundle: PopulationBundle,
    sim_config: SimulationConfig,
    store_path: str | Path,
    scale: str = "small",
    tract_ids: list[str] | None = None,
    init_mode: str = "census",
    seed: int = 42,
    model_kwargs: dict | None = None,
    llm_client: Any = None,
    llm_config: Any = None,
    abm_root: str | Path | None = None,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    on_step: Any = None,
) -> tuple[LongitudinalSimulator, ChicagoEngine]:
    info_env = None
    if env_bundle.information_program.broadcasts:
        info_env = InformationEnvironment(
            env_bundle.information_program, matcher=chicago_audience_matcher
        )

    engine = ChicagoEngine(
        scale=scale, tract_ids=tract_ids, init_mode=init_mode, seed=seed,
        model_kwargs=model_kwargs, llm_client=llm_client, llm_config=llm_config,
        information_env=info_env, abm_root=abm_root,
        config_dir=config_dir, data_dir=data_dir,
    )
    env = ChicagoEnvironmentProvider(engine, env_bundle)
    pop = ChicagoPopulationProvider(engine, pop_bundle)
    decision = SchellingDecisionModel(engine)
    collector = SegregationMetricCollector(engine)
    store = DuckDbTrajectoryStore(store_path, study_id=sim_config.study_id)

    sim = LongitudinalSimulator(
        env=env, population=pop, decision=decision, store=store, collector=collector,
        n_steps=sim_config.n_steps, seed=seed,
        interaction_rounds=sim_config.interaction_rounds,
        study_id=sim_config.study_id, metric_columns=CHI_METRICS + ["step", "events"],
        on_step=on_step,
    )
    return sim, engine


def materialize_chicago_initial(
    *,
    env_bundle: EnvironmentBundle,
    pop_bundle: PopulationBundle,
    seed: int = 42,
    scale: str = "small",
    init_mode: str = "census",
    model_kwargs: dict | None = None,
    llm_client: Any = None,
    llm_config: Any = None,
    **engine_kwargs: Any,
) -> tuple[list, list, ChicagoEngine]:
    """Instantiate P + E_0 for the Chicago study via ONE shared ChicagoEngine and return
    ``(personas, t0_panel_rows, engine)`` — no run, no LLM spend (model construction never
    calls the LLM; the decision phases are skipped). This is chicago's own materializer
    because its env + pop providers must share a single engine — the generic
    ``socioverse.engine.materialize_initial`` would build two. sv-build-population calls this
    to write the roster; pass ``llm_client=DeterministicLLMClient()`` to avoid needing a key."""
    sim_config = SimulationConfig(
        study_id=pop_bundle.study_id, n_steps=0, seed=seed,
        decision_ref="chicago.schelling", interaction_rounds=1,
    )
    sim, engine = build_chicago_simulator(
        env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_config,
        store_path=Path("__materialize_unused__.duckdb"),  # never opened by materialize_initial
        scale=scale, init_mode=init_mode, seed=seed,
        model_kwargs=model_kwargs, llm_client=llm_client, llm_config=llm_config,
        **engine_kwargs,
    )
    personas, rows = sim.materialize_initial()
    return personas, rows, engine
