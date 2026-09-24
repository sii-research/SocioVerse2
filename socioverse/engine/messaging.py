"""InMemoryMessageBus — reference inter-agent communication medium (scenario 2).

A study's EnvironmentProvider (e.g. HiSim) owns one of these: `post` lands an agent's
message; `visible_to` returns the messages a recipient sees from its network neighbours
in the current (step, round). The core simulation loop never touches the bus directly —
agent communication is just how a study's env implements its local-information layer.
"""

from __future__ import annotations

from typing import Any

from ..abc.messaging import MessageBus


class InMemoryMessageBus(MessageBus):
    def __init__(self, carry_previous_step: bool = True):
        self.carry_previous_step = carry_previous_step
        self._messages: list[dict[str, Any]] = []
        self._round_buffer: list[dict[str, Any]] = []

    def post(self, message: dict[str, Any]) -> None:
        msg = dict(message)
        msg.setdefault("round", 0)
        msg.setdefault("channel", "chat")
        self._messages.append(msg)
        self._round_buffer.append(msg)

    def fetch(self, recipient_id: str, t: int, neighbors: list[str]) -> list[dict[str, Any]]:
        return self.visible_to(recipient_id, neighbors, step=t, round_idx=0)

    def visible_to(
        self, recipient_id: str, neighbors: list[str], step: int, round_idx: int = 0
    ) -> list[dict[str, Any]]:
        """Messages from `neighbors` posted earlier this step (round < round_idx) and,
        optionally, the previous step's messages."""
        nb = set(neighbors)
        out = []
        for m in self._messages:
            if m.get("author_id") not in nb:
                continue
            same_step_earlier_round = m.get("step") == step and m.get("round", 0) < round_idx
            prev_step = self.carry_previous_step and m.get("step") == step - 1
            if same_step_earlier_round or prev_step:
                out.append(m)
        return out

    def drain(self) -> list[dict[str, Any]]:
        buf, self._round_buffer = self._round_buffer, []
        return buf
