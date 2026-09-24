"""NeighborFeed — local-information from agent-to-agent messages (scenario 2, HiSim).

Wraps a MessageBus + a neighbours() lookup to turn other agents' `post`/`reply` actions
into each agent's local_information quadrant. Mediated delivery (not O(N^2) direct calls):
posts land on the bus; observers read only their network neighbours' messages.
"""

from __future__ import annotations

from typing import Any, Callable

from ..abc.messaging import MessageBus
from ..engine.messaging import InMemoryMessageBus
from ..schemas.runtime import Action


class NeighborFeed:
    def __init__(
        self,
        neighbors_fn: Callable[[str], list[str]],
        bus: MessageBus | None = None,
    ):
        self.neighbors_fn = neighbors_fn
        self.bus: MessageBus = bus or InMemoryMessageBus()

    def ingest(self, actions: list[Action], step: int, round_idx: int = 0) -> list[dict[str, Any]]:
        """Route message-like actions (kind in {post, reply}) onto the bus. Returns the
        message dicts (for persistence in the DuckDB `messages` table)."""
        posted = []
        for a in actions:
            if a.kind in ("post", "reply"):
                msg = {
                    "author_id": a.agent_id,
                    "content": a.payload.get("content", ""),
                    "step": step,
                    "round": round_idx,
                    "channel": a.payload.get("channel", "chat"),
                    "audience": a.payload.get("audience", "neighbors"),
                }
                self.bus.post(msg)
                posted.append(msg)
        return posted

    def local_for(self, agent_id: str, t: int, round_idx: int = 0) -> dict[str, Any]:
        neighbors = self.neighbors_fn(agent_id)
        if hasattr(self.bus, "visible_to"):
            msgs = self.bus.visible_to(agent_id, neighbors, step=t, round_idx=round_idx)
        else:
            msgs = self.bus.fetch(agent_id, t, neighbors)
        if not msgs:
            return {}
        return {"feed": [{"from": m["author_id"], "content": m["content"]} for m in msgs]}
