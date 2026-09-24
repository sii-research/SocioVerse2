"""DecisionModel ABC — computes behavior B_t.

decide_batch is the primary method: implementations are free to internally group/dedup
agents (e.g. by archetype) before issuing LLM calls. This keeps the Chicago model's
archetype-batched LLM strategy (one batch per phase) instead of ~N per-agent calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..schemas.runtime import Action, Observation


class DecisionModel(ABC):
    @abstractmethod
    def decide_batch(
        self, obs: list[Observation], memories: dict[str, Any]
    ) -> list[Action]:
        """Compute B_t for many agents at once. `memories` maps agent_id -> AgentMemory
        (per-agent rolling history) for genuinely longitudinal behavior."""

    def decide(self, ob: Observation, memory: Any) -> Action:
        return self.decide_batch([ob], {ob.agent_id: memory})[0]
