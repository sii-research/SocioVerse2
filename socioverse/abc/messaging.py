"""MessageBus ABC — the inter-agent communication medium (scenario 2, HiSim).

Agent communication is mediated, NOT O(N^2) direct calls: a `post`/`reply` action
lands on the bus (a local-information channel); the next observation delivers it to
the author's network neighbours. A simple in-memory implementation lives in
engine/messaging.py; large-scale backends (DuckDB/Redis) can subclass this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MessageBus(ABC):
    @abstractmethod
    def post(self, message: dict[str, Any]) -> None:
        """Publish a message. Expected keys: author_id, content, step, channel, audience?"""

    @abstractmethod
    def fetch(self, recipient_id: str, t: int, neighbors: list[str]) -> list[dict[str, Any]]:
        """Return messages visible to `recipient_id` at step t (from its neighbours)."""

    def drain(self) -> list[dict[str, Any]]:
        """Return + clear messages posted this round (for persistence). Optional."""
        return []
