"""Decision model for ConsumerSim five-question core prediction."""

from __future__ import annotations

from typing import Any

from socioverse.abc import DecisionModel
from socioverse.schemas import Action, Observation


class ConsumerConfidenceDecisionModel(DecisionModel):
    def __init__(self, engine):
        self.engine = engine

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        self.engine.predict_core()
        actions: list[Action] = []
        for ob in obs:
            consumer = self.engine.population_by_id[ob.agent_id]
            if consumer.response is not None:
                actions.append(
                    Action(
                        agent_id=ob.agent_id,
                        step=ob.step,
                        kind="survey_response",
                        payload={
                            "target_month": self.engine.current_month,
                            "response": dict(consumer.response),
                        },
                        source=self._source(),
                    )
                )
            else:
                actions.append(
                    Action(
                        agent_id=ob.agent_id,
                        step=ob.step,
                        kind="not_sampled",
                        payload={"target_month": self.engine.current_month},
                        source="rule",
                    )
                )
        return actions

    def _source(self) -> str:
        provider = str(self.engine.config["prediction"].get("provider", "local")).lower()
        return "llm" if provider == "openai_compatible" else "rule"
