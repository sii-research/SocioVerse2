"""EnvironmentProvider ABC — the dynamic environment E.

Implementations own the world state and expose the two time channels:
  - advance_to(t): SCHEDULED/exogenous change (numeric events + information broadcasts)
  - apply(actions): ENDOGENOUS feedback  E_{t+1} = f(E_t, B_t)
and the per-agent view assembly observe_batch() that materializes the 4 quadrants.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas.environment import EnvironmentBundle, ScheduledEvent
from ..schemas.runtime import Action, Observation


class EnvironmentProvider(ABC):
    bundle: EnvironmentBundle

    @abstractmethod
    def reset(self, seed: int) -> None:
        """Build initial state for t=0 (load geo/info layers, adjacency, dynamic state)."""

    @abstractmethod
    def advance_to(self, t: int) -> list[ScheduledEvent]:
        """Apply scheduled numeric events + activate information broadcasts whose
        at_step <= t and that haven't fired. Returns the events that fired (for logging)."""

    @abstractmethod
    def apply(self, actions: list[Action]) -> None:
        """Fold agents' behavior back into env state (endogenous feedback)."""

    @abstractmethod
    def observe_batch(
        self, agent_ids: list[str], t: int, round_idx: int = 0
    ) -> list[Observation]:
        """Assemble the 4-quadrant Observation per agent. Macro layers are shared
        verbatim; local layers are filtered by each agent's position/network."""

    def observe(self, agent_id: str, t: int, round_idx: int = 0) -> Observation:
        return self.observe_batch([agent_id], t, round_idx)[0]

    @abstractmethod
    def agent_state(self, agent_id: str) -> dict:
        """Current per-agent state for the panel store (tract_id, satisfaction, ...)."""

    def snapshot(self) -> dict:
        """Optional global env state for env-scale metrics. Default empty."""
        return {}
