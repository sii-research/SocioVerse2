"""Generic, study-agnostic PopulationProviders (scenario 3: user data / tool / MCP).

These let any study draw its population P from sources other than a bespoke builder:
  - FilePopulationProvider    : a user-uploaded CSV/Parquet of personas
  - McpPopulationProvider     : a SocioVerse-1.0-style population-pool MCP tool
Both yield Personas with persistent ids (the longitudinal key).
"""

from __future__ import annotations

import json
import math
from typing import Any, Callable

from .abc.population import PopulationProvider
from .engine.registry import register
from .schemas.population import InteractionStructure, Persona, PopulationBundle

_RESERVED = {"agent_id", "group_key", "weight"}


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _row_to_persona(rec: dict[str, Any]) -> Persona:
    rec = dict(rec)
    raw_id = rec.pop("agent_id", None)
    if raw_id is None or _is_nan(raw_id) or str(raw_id).strip() == "":
        raise ValueError("Persona row is missing a valid 'agent_id'")
    aid = str(raw_id)

    gk = rec.pop("group_key", None)
    gk_str = None if (gk is None or _is_nan(gk)) else str(gk)

    raw_w = rec.pop("weight", 1.0)
    weight = 1.0 if (raw_w is None or _is_nan(raw_w) or raw_w == "") else float(raw_w)

    raw_init = rec.pop("init_state", {})
    if isinstance(raw_init, dict):
        init_state = raw_init
    elif isinstance(raw_init, str) and raw_init.strip():
        try:
            parsed = json.loads(raw_init)
            init_state = parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            init_state = {}
    else:
        init_state = {}

    attrs = {k: (None if _is_nan(v) else v) for k, v in rec.items()}
    return Persona(agent_id=aid, group_key=gk_str, weight=weight,
                   attributes=attrs, init_state=init_state)


@register("population", "file.personas")
class FilePopulationProvider(PopulationProvider):
    """Read personas from a user-uploaded file. provider_args: {"path": ..., "format"?}.
    The file must have an `agent_id` column; `group_key`/`weight` optional; the rest
    become persona attributes."""

    def __init__(self, bundle: PopulationBundle):
        self.bundle = bundle

    def build(self, seed: int) -> list[Persona]:
        import pandas as pd

        path = str(self.bundle.provider_args["path"])
        fmt = self.bundle.provider_args.get("format")
        if fmt == "parquet" or path.endswith(".parquet"):
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        if "agent_id" not in df.columns:
            raise ValueError("FilePopulationProvider: uploaded file must have an 'agent_id' column")
        return [_row_to_persona(r) for r in df.to_dict(orient="records")]

    def interaction_structure(self) -> InteractionStructure:
        return self.bundle.interaction


@register("population", "mcp.socioverse_pool")
class McpPopulationProvider(PopulationProvider):
    """Draw personas from a population-pool MCP (SocioVerse 1.0). Reference implementation:
    inject `fetch_fn(provider_args) -> list[dict]` that performs the MCP tool call (the skill
    wires it from ResourceManifest.mcp_servers). Each record needs an `agent_id`."""

    def __init__(self, bundle: PopulationBundle, fetch_fn: Callable[[dict], list[dict]] | None = None):
        self.bundle = bundle
        self.fetch_fn = fetch_fn

    def build(self, seed: int) -> list[Persona]:
        if self.fetch_fn is None:
            raise NotImplementedError(
                "McpPopulationProvider needs a fetch_fn (the population-pool MCP tool call). "
                "Wire it from the study's ResourceManifest.mcp_servers declaration, e.g.\n"
                "    McpPopulationProvider(bundle, fetch_fn=lambda args: mcp_call('pool.sample', args))"
            )
        records = self.fetch_fn(dict(self.bundle.provider_args))
        return [_row_to_persona(r) for r in records]

    def interaction_structure(self) -> InteractionStructure:
        return self.bundle.interaction
