"""Standard information-layer declarations + convenience constructors.

The two-axis system means a "macro news broadcast" and a "local ward notice" are the
SAME mechanism (an audience-scoped Broadcast) differing only in `audience`. These helpers
give studies ready-made EnvironmentLayer declarations and Broadcast builders so the
information axis is one import away.
"""

from __future__ import annotations

from typing import Any

from ..schemas.environment import Broadcast, EnvironmentLayer


def default_information_layers() -> list[EnvironmentLayer]:
    """A macro news channel + a local neighbour/ward channel."""
    return [
        EnvironmentLayer(
            name="news", modality="information", scope="macro",
            description="city-wide news / policy broadcasts, seen by all agents",
        ),
        EnvironmentLayer(
            name="neighbor_feed", modality="information", scope="local",
            description="local ward notices + neighbour word-of-mouth, audience-scoped",
        ),
    ]


def macro_news(message_id: str, content: str, at_step: int, ttl: int = 1,
               channel: str = "news") -> Broadcast:
    """A broadcast delivered to EVERY agent's macro_information."""
    return Broadcast(message_id=message_id, content=content, channel=channel,
                     at_step=at_step, ttl=ttl, audience="all")


def local_notice(message_id: str, content: str, at_step: int, audience: dict[str, Any],
                 ttl: int = 1, channel: str = "neighbor_feed") -> Broadcast:
    """A broadcast delivered only to agents matching `audience` (local_information)."""
    return Broadcast(message_id=message_id, content=content, channel=channel,
                     at_step=at_step, ttl=ttl, audience=audience)
