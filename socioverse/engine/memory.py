"""AgentMemory — a per-agent rolling history that makes behavior genuinely longitudinal.

Each persistent agent keeps its own bounded trace of (step, action, observation summary)
so a DecisionModel can condition on the agent's own past ("I already moved twice; I'll
stay"). Optional for Schelling; essential for opinion-dynamics models (HiSim).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..schemas.runtime import Action


class AgentMemory:
    def __init__(self, agent_id: str, window: int = 8):
        self.agent_id = agent_id
        self.window = window
        self.history: deque[dict[str, Any]] = deque(maxlen=window)

    def push(self, t: int, action: Action | None = None, observation_summary: Any = None) -> None:
        self.history.append(
            {
                "t": t,
                "action_kind": getattr(action, "kind", None),
                "payload": getattr(action, "payload", {}) or {},
                "summary": observation_summary,
            }
        )

    def recent(self, n: int | None = None) -> list[dict[str, Any]]:
        items = list(self.history)
        return items[-n:] if n else items

    def last_action_kind(self) -> str | None:
        return self.history[-1]["action_kind"] if self.history else None

    def count_action(self, kind: str) -> int:
        return sum(1 for h in self.history if h["action_kind"] == kind)

    def __len__(self) -> int:
        return len(self.history)
