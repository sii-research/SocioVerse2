"""SchellingDecisionModel — reuses the model's validated LLM phases as B_t.

decide_batch calls the model's OWN _assess_archetype_satisfaction + _evaluate_move_candidates
(the two batched-LLM phases of legacy step()), then projects the resulting intent into typed
Actions. The actual move execution happens later in EnvironmentProvider.apply (budget + shuffle_do).
No validated dynamic is re-implemented.
"""

from __future__ import annotations

from typing import Any

from socioverse.abc import DecisionModel
from socioverse.schemas import Action, Observation


class SchellingDecisionModel(DecisionModel):
    def __init__(self, engine):
        self.engine = engine

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        m = self.engine.model
        # Phase 1 + 2 of legacy step() — batched LLM calls, write group_would_move/move_targets.
        m._assess_archetype_satisfaction()
        m._evaluate_move_candidates()

        actions = []
        for ob in obs:
            agent = self.engine._agent_by_id[ob.agent_id]
            key = (agent.archetype_key, agent.tract_id)
            wants = m.group_would_move.get(key, agent.archetype.would_move)
            targets = m.move_targets.get(key, [])
            kind = "move" if (wants and targets) else "stay"
            actions.append(Action(
                agent_id=ob.agent_id,
                step=ob.step,
                kind=kind,
                payload={"ranked_targets": targets} if targets else {},
                rationale=list(getattr(agent.archetype, "key_reasons", []) or []),
                source="llm",
            ))
        return actions
