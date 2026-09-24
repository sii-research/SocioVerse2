"""build_simulator — generic, registry-driven assembly of a from-scratch study.

This is the **Path B (build-new from Core)** wiring: given the three validated bundles it
resolves the ``*_ref`` strings against the registry and wires a ``LongitudinalSimulator`` with
no per-study boilerplate. A `sv-build-model`-authored study only has to register its four abc
implementations; `sv-run` then calls this to run them.

Construction convention for the resolved classes (what a from-scratch study must honour):
  - ``EnvironmentProvider`` / ``PopulationProvider`` -> ``cls(bundle)``  (sole arg is its bundle)
  - ``DecisionModel``                                -> ``cls(**sim.decision_args)``
  - ``MetricCollector``                              -> ``cls(**sim.collector_args)``
  - ``TrajectoryStore``                              -> built-in ``duckdb`` is special-cased;
    any other ``store_ref`` is ``resolve("store", ref)(store_path, study_id=...)``

Studies that wrap a *legacy* engine and need shared mutable state between providers
(e.g. chicago's ``ChicagoEngine``) keep their own ``build_*_simulator`` factory instead — Core
never calls those. See CLAUDE-dev.md for that (Path C) path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..abc.trajectory import MetricCollector
from ..io import DuckDbTrajectoryStore
from ..schemas import EnvironmentBundle, PopulationBundle, SimulationConfig
from ..schemas.population import Persona
from ..schemas.trajectory import TrajectoryRecord
from .loop import LongitudinalSimulator, build_panel_rows
from .registry import resolve


class _EmptyCollector(MetricCollector):
    """Fallback when a study declares no collector_ref — records only 'step'."""

    def collect(self, env: Any, actions: list, t: int) -> dict[str, Any]:
        return {}


def _resolve(ref: str, kind: str, key: str) -> type:
    """resolve() with a from-scratch-friendly hint for the #1 gotcha (study not imported)."""
    try:
        return resolve(kind, key)
    except KeyError as e:
        raise KeyError(
            f"{e}. Did you import the study module so its @register decorators ran? "
            f"(e.g. `import studies.<study_id>` before build_simulator)."
        ) from e


def build_providers(
    env_bundle: EnvironmentBundle, pop_bundle: PopulationBundle
) -> tuple[Any, Any]:
    """Resolve just the environment + population providers (the P and E of a study) from the
    registry — no decision model, collector, or store. Same ``cls(bundle)`` convention as
    build_simulator. Path-B only: studies whose providers share a mutable engine (chicago's
    ChicagoEngine) must use their own materializer so both providers see one engine."""
    env = _resolve(env_bundle.provider_ref, "environment", env_bundle.provider_ref)(env_bundle)
    population = _resolve(pop_bundle.provider_ref, "population", pop_bundle.provider_ref)(pop_bundle)
    return env, population


def materialize_initial(
    env_bundle: EnvironmentBundle, pop_bundle: PopulationBundle, seed: int = 42
) -> tuple[list[Persona], list[TrajectoryRecord]]:
    """Instantiate P + E_0 for a from-scratch (Path-B) study and return
    ``(personas, t0_panel_rows)`` — the "instantiate the agents" step, with no run and no
    SimulationConfig (decision/collector/store are irrelevant to t=0). sv-build-population calls
    this to write the initialized roster BEFORE sv-run exists. Deterministic in ``seed``."""
    env, population = build_providers(env_bundle, pop_bundle)
    personas = population.build(seed)
    env.reset(seed)
    return personas, build_panel_rows(env, personas, None, 0)


def build_simulator(
    *,
    env_bundle: EnvironmentBundle,
    pop_bundle: PopulationBundle,
    sim_config: SimulationConfig,
    store_path: str | Path,
    on_step: Any = None,
) -> LongitudinalSimulator:
    """Resolve refs from the registry and wire a runnable LongitudinalSimulator.

    The study's model module must already be imported so its `@register(...)` decorators have
    run (importing ``studies.<id>`` is enough if its ``__init__`` imports ``model``).
    """
    env = _resolve(env_bundle.provider_ref, "environment", env_bundle.provider_ref)(env_bundle)
    population = _resolve(pop_bundle.provider_ref, "population", pop_bundle.provider_ref)(pop_bundle)
    decision = _resolve(sim_config.decision_ref, "decision", sim_config.decision_ref)(**sim_config.decision_args)

    if sim_config.collector_ref:
        collector = _resolve(sim_config.collector_ref, "collector", sim_config.collector_ref)(**sim_config.collector_args)
    else:
        collector = _EmptyCollector()

    if sim_config.store_ref == "duckdb":
        store = DuckDbTrajectoryStore(store_path, study_id=sim_config.study_id)
    else:
        store = resolve("store", sim_config.store_ref)(store_path, study_id=sim_config.study_id)

    return LongitudinalSimulator(
        env=env,
        population=population,
        decision=decision,
        store=store,
        collector=collector,
        n_steps=sim_config.n_steps,
        seed=sim_config.seed,
        interaction_rounds=sim_config.interaction_rounds,
        memory_window=sim_config.engine_args.get("memory_window", 8),
        metric_columns=(collector.columns() or None),
        study_id=sim_config.study_id,
        on_step=on_step,
        warm_start=sim_config.warm_start,
    )
