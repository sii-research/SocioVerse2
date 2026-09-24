"""Runtime contracts exchanged inside the simulation loop: Observation and Action.

Observation is where the two-axis environment materializes into a concrete per-agent
view (the 4 quadrants). Action is the agent's behavior B handed back to the engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """The assembled 4-quadrant view handed to the DecisionModel for one agent at one step."""

    agent_id: str
    step: int
    macro_physical: dict[str, Any] = Field(default_factory=dict)
    local_physical: dict[str, Any] = Field(default_factory=dict)
    macro_information: dict[str, Any] = Field(default_factory=dict)
    local_information: dict[str, Any] = Field(default_factory=dict)
    rendered: str | None = None   # optional pre-rendered prompt text (perf)

    def quadrants_nonempty(self) -> dict[str, bool]:
        """Helper for tests/audits: which of the 4 quadrants carry content."""
        return {
            "macro_physical": bool(self.macro_physical),
            "local_physical": bool(self.local_physical),
            "macro_information": bool(self.macro_information),
            "local_information": bool(self.local_information),
        }


class Action(BaseModel):
    """The behavior B_t emitted by a DecisionModel for one agent."""

    agent_id: str
    step: int
    kind: str                                       # move | stay | post | reply | adopt_opinion | ...
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    source: Literal["llm", "rule", "fallback", "replay"] = "llm"  # replay = branch replay (inherited from the parent version)
