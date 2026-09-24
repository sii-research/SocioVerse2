"""make_abm_bundles — one factory that turns ANY SocioVerse-ABM task into the four SocioVerse2
artifacts (StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig) pointing at
the shared umbrella providers. An `abm_<task>` study is then just a call to this — the
"11 studies share one adapter" payoff.
"""
from __future__ import annotations

from typing import Any

from socioverse.schemas import (
    EnvironmentBundle,
    InteractionStructure,
    PopulationBundle,
    PropagationMode,
    SimulationConfig,
    StudySpec,
)

from . import seam

_REFS = ["abm.env", "abm.pop", "abm.decision", "abm.collector"]


def task_metrics(task: str, seed: int = 42, overrides: dict | None = None) -> list[str]:
    """Derive the per-step metric columns from one snapshot of the task's env."""
    spec = seam.load_task(task)
    env, _pop = spec.build(seam.task_config(task, overrides, seed=seed), seed)
    return [k for k, v in env.snapshot().items() if k != "t" and isinstance(v, (int, float, bool))]


def make_abm_bundles(
    task: str,
    *,
    study_id: str | None = None,
    n_steps: int = 20,
    seed: int = 42,
    mode: str = "rule",
    config_overrides: dict | None = None,
    llm_fraction: float | None = None,
    group_field: str | None = None,
    propagation: PropagationMode = PropagationMode.INDEPENDENT,
    title: str = "",
    research_question: str = "",
    hypothesis: str = "",
    domain: str = "abm",
    tags: list[str] | None = None,
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    """``mode``: rule | llm | hybrid (see ``AbmDecisionModel``). ``config_overrides`` are deep-merged
    into the task's config.yaml for P, E and the LLM layer (e.g. ``{"behavior": {"llm_model":
    "gpt-4o-mini"}}``). ``llm_fraction`` only matters in hybrid mode: the share of agents routed
    to the LLM (default none, i.e. every agent follows the rule, as in native SocioVerse-ABM)."""
    study_id = study_id or f"abm_{task}"
    spec = seam.load_task(task)
    metrics = task_metrics(task, seed, config_overrides)

    study = StudySpec(
        study_id=study_id,
        title=title or f"{spec.source_abm} (SocioVerse-ABM via umbrella)",
        research_question=research_question or f"Does the LLM behavior function reproduce the rule-based {task}?",
        hypothesis=hypothesis,
        study_type="longitudinal", n_steps=n_steps, seed=seed, metrics=metrics,
        domain=domain, tags=tags or ["abm", task, "umbrella"],
        legacy_simulator="socioverse_abm",
        provider_refs=list(_REFS),
        adjustable_params=["n_steps", "seed", "mode (rule|llm|hybrid)", "config_overrides"],
        status="demo",
    )
    env_args: dict[str, Any] = {"abm_task": task}
    pop_args: dict[str, Any] = {"abm_task": task}
    if config_overrides:
        env_args["config"] = pop_args["config"] = config_overrides
    if group_field:
        pop_args["group_field"] = group_field

    decision_args: dict[str, Any] = {"abm_task": task, "mode": mode, "seed": seed}
    if config_overrides:
        decision_args["config"] = config_overrides
    if llm_fraction is not None:
        decision_args["llm_fraction"] = llm_fraction

    env_bundle = EnvironmentBundle(study_id=study_id, provider_ref="abm.env", provider_args=env_args)
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="abm.pop", provider_args=pop_args,
        interaction=InteractionStructure(kind="none"), propagation=propagation,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed,
        decision_ref="abm.decision",
        decision_args=decision_args,
        collector_ref="abm.collector", collector_args={"abm_task": task},
        interaction_rounds=1,
    )
    return study, env_bundle, pop_bundle, sim_config
