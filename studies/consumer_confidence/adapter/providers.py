"""Population and environment providers for the ConsumerSim confidence adapter."""

from __future__ import annotations

from typing import Any

from socioverse.abc import EnvironmentProvider, PopulationProvider
from socioverse.schemas import Action, EnvironmentBundle, Observation, Persona, PopulationBundle, ScheduledEvent


class ConsumerConfidencePopulationProvider(PopulationProvider):
    """Builds ConsumerSim's population from SocioVerse Personas."""

    def __init__(self, engine, bundle: PopulationBundle):
        self.engine = engine
        self.bundle = bundle

    def build(self, seed: int) -> list[Persona]:
        personas = list(self.bundle.personas)
        source_csv = self.bundle.provider_args.get("source_csv")
        if source_csv:
            personas = self.engine.read_personas_csv(source_csv)
        if not personas:
            raise ValueError(
                "consumer_confidence population requires SocioVerse personas or "
                "provider_args.source_csv; ConsumerSim synthetic population is intentionally not used."
            )
        self.engine.load_personas(personas)
        return personas


class ConsumerConfidenceEnvironmentProvider(EnvironmentProvider):
    """Owns the month-specific information environment and response state."""

    def __init__(self, engine, bundle: EnvironmentBundle):
        self.engine = engine
        self.bundle = bundle

    def reset(self, seed: int) -> None:
        self.engine.ensure_loaded()
        self.engine.current_step = 0
        self.engine.current_month = None
        self.engine.current_as_of = None
        self.engine.current_environment = None
        self.engine.last_result = None
        self.engine.results = {}

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        self.engine.begin_step(t)
        month = self.engine.current_month
        if not month:
            return []
        return [
            ScheduledEvent(
                at_step=t,
                target_layer="consumer_information",
                op="replace_source",
                note=f"Consumer confidence forecast for {month} as of {self.engine.current_as_of}",
            )
        ]

    def apply(self, actions: list[Action]) -> None:
        result = self.engine.finalize_step(actions)
        for action in actions:
            consumer = self.engine.population_by_id.get(action.agent_id)
            if consumer is not None and consumer.response is not None:
                action.payload["response"] = dict(consumer.response)
                action.payload["target_month"] = self.engine.current_month
                action.payload["is_core"] = bool(consumer.is_core)
        for action in actions:
            if action.kind == "not_sampled":
                action.kind = "expanded_response"
        if result.get("target_month"):
            for action in actions:
                action.payload.setdefault("forecast_score", result.get("corrected_score"))

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        env = self.engine.current_environment
        macro_information: dict[str, Any] = {}
        macro_physical: dict[str, Any] = {
            "region": self.engine.region,
            "target_month": self.engine.current_month,
            "as_of": self.engine.current_as_of,
        }
        if env is not None:
            macro_information = {
                "news_score": env.news_score,
                "indicator_score": env.indicator_score,
                "combined_score": env.combined_score,
                "headlines": [item.title for item in env.news_items[:8]],
                "indicators": [item.name for item in env.indicators[:8]],
            }
        out = []
        for agent_id in agent_ids:
            consumer = self.engine.population_by_id[agent_id]
            out.append(
                Observation(
                    agent_id=agent_id,
                    step=t,
                    macro_physical=dict(macro_physical),
                    local_physical={
                        "age_group": consumer.age_group,
                        "income_group": consumer.income_group,
                        "education_group": consumer.education_group,
                        "location_group": consumer.location_group,
                        "weight": consumer.weight,
                        "is_core": consumer.is_core,
                    },
                    macro_information=dict(macro_information),
                    local_information={"group_key": consumer.group_key(self.engine.group_fields)},
                )
            )
        return out

    def agent_state(self, agent_id: str) -> dict:
        return self.engine.agent_state(agent_id)

    def snapshot(self) -> dict:
        return {
            "region": self.engine.region,
            "target_month": self.engine.current_month,
            "as_of": self.engine.current_as_of,
            "population_size": len(self.engine.population),
            "core_size": len(self.engine.core),
        }
