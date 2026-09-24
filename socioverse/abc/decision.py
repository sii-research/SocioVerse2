"""DecisionModel ABC — computes behavior B_t.

decide_batch is the primary method: the engine hands it the WHOLE step (every agent's
Observation) at once and expects one Action per agent back. "Batch" describes that interface,
not how the LLM is called; the implementation decides the call pattern:

- From-scratch studies (sv-build-model) call the LLM once per agent, sending the step's
  per-agent calls concurrently on a bounded thread pool, and parse / fall back per agent
  (see ``studies/opinion_diffusion/model.py``). Do not ask for one JSON reply covering the
  whole population: long structured replies get truncated and one bad reply fails the step.
- Legacy adapters keep the wrapped engine's own call pattern (e.g. the Chicago model's
  archetype-grouped calls in its two LLM phases) so its validated dynamics are unchanged.
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
        """Compute B_t for every agent of the step; return one Action per agent. `memories`
        maps agent_id -> AgentMemory (per-agent rolling history) for genuinely longitudinal
        behavior. How the LLM is called inside is up to the model (see the module docstring)."""

    def decide(self, ob: Observation, memory: Any) -> Action:
        return self.decide_batch([ob], {ob.agent_id: memory})[0]
