"""PopulationProvider ABC — the fixed population pool P with persistent ids."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas.population import InteractionStructure, Persona, PopulationBundle


class PopulationProvider(ABC):
    bundle: PopulationBundle

    @abstractmethod
    def build(self, seed: int) -> list[Persona]:
        """Materialize the persona pool with PERSISTENT, deterministic agent_ids."""

    def interaction_structure(self) -> InteractionStructure:
        return self.bundle.interaction

    def neighbors(self, agent_id: str) -> list[str]:
        """Agent_ids reachable for local-information propagation. Default: none."""
        return []
