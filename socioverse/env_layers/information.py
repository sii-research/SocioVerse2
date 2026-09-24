"""InformationEnvironment — reusable machinery for the information axis of E.

Activates audience-scoped Broadcasts over time and renders them into the
macro_information / local_information quadrants. A study's EnvironmentProvider composes
one of these and supplies a `matcher(selector, agent_ctx) -> bool` for local audiences
(Chicago: a TractSelector-aware matcher; default: a generic attribute matcher).

Scenario 1 (policy A to all + policy B to a tract at step n) is two Broadcasts:
  Broadcast(content=A, audience="all", at_step=n)          -> macro_information for everyone
  Broadcast(content=B, audience={...tract...}, at_step=n)  -> local_information for matches
"""

from __future__ import annotations

from typing import Any, Callable

from ..schemas.environment import Broadcast, InformationProgram


def match_selector(selector: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Generic audience matcher over an agent context dict. Supported selector keys:
      - "<attr>": exact equality              -> ctx["<attr>"] == value
      - "<attr>_in": membership               -> ctx["<attr>"] in value
      - "<attr>_below"/"<attr>_above": numeric
      - "geoid_list": ctx['geoid'|'tract_id'] in value
      - "index_below": ctx['index'] < value
    Empty selector matches nobody (a broadcast must scope its local audience).
    """
    if not selector:
        return False
    for key, val in selector.items():
        if key.endswith("_in"):
            if ctx.get(key[:-3]) not in val:
                return False
        elif key.endswith("_below"):
            v = ctx.get(key[:-6])
            if v is None or not (v < val):
                return False
        elif key.endswith("_above"):
            v = ctx.get(key[:-6])
            if v is None or not (v > val):
                return False
        elif key == "geoid_list":
            if ctx.get("geoid") not in val and ctx.get("tract_id") not in val:
                return False
        elif key == "index_below":
            if not (ctx.get("index", float("inf")) < val):
                return False
        else:
            if ctx.get(key) != val:
                return False
    return True


def _collapse(buckets: dict[str, list[str]]) -> dict[str, Any]:
    return {k: (v[0] if len(v) == 1 else v) for k, v in buckets.items()}


class InformationEnvironment:
    def __init__(
        self,
        program: InformationProgram | None = None,
        matcher: Callable[[dict, dict], bool] | None = None,
    ):
        self.program = program or InformationProgram()
        self.matcher = matcher or match_selector
        self._active: list[Broadcast] = []

    def reset(self) -> None:
        self._active = []

    def advance_to(self, t: int) -> list[Broadcast]:
        """Activate broadcasts firing at t, expire those past their ttl. Returns the
        newly-activated broadcasts (for event logging)."""
        newly = [b for b in self.program.broadcasts if b.at_step == t]
        self._active.extend(newly)
        self._active = [b for b in self._active if b.at_step + b.ttl > t]
        return newly

    def macro(self) -> dict[str, Any]:
        buckets: dict[str, list[str]] = {}
        for b in self._active:
            if b.is_macro:
                buckets.setdefault(b.channel, []).append(b.content)
        return _collapse(buckets)

    def local_for(self, agent_ctx: dict[str, Any]) -> dict[str, Any]:
        buckets: dict[str, list[str]] = {}
        for b in self._active:
            if not b.is_macro and isinstance(b.audience, dict) and self.matcher(b.audience, agent_ctx):
                buckets.setdefault(b.channel, []).append(b.content)
        return _collapse(buckets)

    def rendered_lines(self, agent_ctx: dict[str, Any]) -> list[str]:
        """Flat text lines visible to an agent (macro + matching local) for LLM prompts."""
        lines = []
        for b in self._active:
            visible = b.is_macro or (
                isinstance(b.audience, dict) and self.matcher(b.audience, agent_ctx)
            )
            if visible:
                lines.append(f"[{b.channel}] {b.content}")
        return lines

    @property
    def active(self) -> list[Broadcast]:
        return list(self._active)
