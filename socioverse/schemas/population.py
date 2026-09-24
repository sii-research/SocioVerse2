"""Population P schemas: personas with persistent ids + interaction + propagation.

The persistent `agent_id` is the longitudinal primary key — the same persona is
tracked across all steps. PopulationBundle.personas may be empty when the bundle
only declares a provider (e.g. census/mcp) that materializes personas at runtime.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PropagationMode(str, Enum):
    """How influence flows among agents."""

    INDEPENDENT = "independent"            # agents act on E only (Schelling)
    CONTAGION = "contagion"                # neighbor states influence the agent (HiSim)
    BROADCAST_THEN_LOCAL = "broadcast_then_local"  # macro-info shock then local diffusion


class Persona(BaseModel):
    agent_id: str                          # PERSISTENT across the whole study; never reused
    attributes: dict[str, Any] = Field(default_factory=dict)
    group_key: str | None = None           # batched-decision / interaction cohort (archetype)
    weight: float = 1.0                    # one persona may represent `weight` real units
    init_state: dict[str, Any] = Field(default_factory=dict)


class InteractionStructure(BaseModel):
    kind: Literal["spatial_adjacency", "explicit_network", "none"] = "none"
    edges: list[tuple[str, str]] | None = None   # explicit_network: agent_id pairs
    adjacency_ref: str | None = None             # spatial: provider computes (e.g. Queen contiguity)


class PopulationBundle(BaseModel):
    """The validated artifact written by `sv-build-population`."""

    study_id: str
    personas: list[Persona] = Field(default_factory=list)
    interaction: InteractionStructure = Field(default_factory=InteractionStructure)
    propagation: PropagationMode = PropagationMode.INDEPENDENT
    provider_ref: str
    provider_args: dict[str, Any] = Field(default_factory=dict)
    # Set by sv-build-population once it MATERIALIZES the pool (runs provider.build): the true
    # agent count, authoritative even when `personas` is left empty for very large pools (the
    # full roster then lives in population/roster.jsonl). None = not yet materialized.
    materialized_count: int | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "PopulationBundle":
        ids = [p.agent_id for p in self.personas]
        if len(ids) != len(set(ids)):
            seen, dupes = set(), set()
            for i in ids:
                (dupes if i in seen else seen).add(i)
            raise ValueError(
                "agent_id must be unique (persistent-id invariant). "
                f"Duplicates (first 5): {sorted(dupes)[:5]}"
            )
        return self
