"""Chicago environment + population providers (wrap the legacy model, zero src edits)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from socioverse.abc import EnvironmentProvider, PopulationProvider
from socioverse.schemas import (
    Action,
    EnvironmentBundle,
    InteractionStructure,
    Observation,
    Persona,
    PopulationBundle,
    ScheduledEvent,
)

RACE_COLS = ["nh_white", "nh_black", "nh_asian", "hispanic", "nh_other"]


# ── Audience / selector resolution (reuses the customize TractSelector vocabulary) ──

def chicago_audience_matcher(selector: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Match a broadcast's local audience against a tract context (scenario 1)."""
    if not selector:
        return False
    if selector.get("all_tracts"):
        return True
    if "geoid_list" in selector:
        if ctx.get("geoid") in set(selector["geoid_list"]):
            return True
        return False
    if "community_areas" in selector:
        if ctx.get("community_area") not in set(selector["community_areas"]):
            return False
    if "dominant_race" in selector:
        if ctx.get("dominant_race") != selector["dominant_race"]:
            return False
    if "hardship_above" in selector and not (ctx.get("hardship", 0) > selector["hardship_above"]):
        return False
    if "hardship_below" in selector and not (ctx.get("hardship", 1e9) < selector["hardship_below"]):
        return False
    if "income_below" in selector and not (ctx.get("income", 1e18) < selector["income_below"]):
        return False
    if "income_above" in selector and not (ctx.get("income", 0) > selector["income_above"]):
        return False
    return True


def resolve_geoids(env, selector: dict[str, Any]) -> list[str]:
    """Resolve a TractSelector-style dict to a list of tract GEOIDs in the env."""
    gdf = env.gdf
    if not selector or selector.get("all_tracts"):
        return list(gdf.index)
    if "geoid_list" in selector:
        return [g for g in selector["geoid_list"] if g in gdf.index]
    mask = gdf.index == gdf.index  # all True
    if "community_areas" in selector:
        mask = mask & gdf["community_area_num"].isin(selector["community_areas"]).values
    if "dominant_race" in selector:
        race = {"white": "pct_nh_white", "black": "pct_nh_black", "asian": "pct_nh_asian",
                "hispanic": "pct_hispanic", "other": "pct_nh_other"}[selector["dominant_race"]]
        mask = mask & (gdf[race].values >= 50)
    if "hardship_above" in selector:
        mask = mask & (gdf["hardship_index"].values > selector["hardship_above"])
    if "hardship_below" in selector:
        mask = mask & (gdf["hardship_index"].values < selector["hardship_below"])
    if "income_below" in selector:
        mask = mask & (gdf["per_capita_income"].values < selector["income_below"])
    if "income_above" in selector:
        mask = mask & (gdf["per_capita_income"].values > selector["income_above"])
    return list(gdf.index[mask])


def _apply_event(env, event: ScheduledEvent) -> None:
    """Apply a numeric scheduled event to the live GeoDataFrame in place (amenity/demographic)."""
    if event.property_name is None:
        return
    geoids = resolve_geoids(env, event.selector)
    col = event.property_name
    if col not in env.gdf.columns:
        return
    for g in geoids:
        old = env.gdf.at[g, col]
        if event.op == "set":
            new = event.value
        elif event.op == "add":
            new = old + event.value
        elif event.op == "multiply":
            new = old * event.value
        elif event.op == "add_pct":
            new = old * (1 + event.value / 100.0)
        else:
            continue
        env.gdf.at[g, col] = new


class ChicagoEnvironmentProvider(EnvironmentProvider):
    """Wraps TractEnvironment + the model. Physical layers (macro city_race_share,
    local tract neighbourhood) + scheduled numeric events + information broadcasts."""

    def __init__(self, engine, bundle: EnvironmentBundle):
        self.engine = engine
        self.bundle = bundle
        self._pending = sorted(bundle.scheduled_events, key=lambda e: e.at_step)
        self._fired: set[int] = set()
        self._prev_race_df = None
        self.info_env = engine.information_env  # may be None

    @property
    def model(self):
        return self.engine.model

    def reset(self, seed: int) -> None:
        self.engine.ensure_built()
        self._pending = sorted(self.bundle.scheduled_events, key=lambda e: e.at_step)
        self._fired = set()
        if self.info_env is not None:
            self.info_env.reset()

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        fired: list[ScheduledEvent] = []
        for i, ev in enumerate(self._pending):
            if ev.at_step <= t and i not in self._fired:
                _apply_event(self.model.environment, ev)
                self._fired.add(i)
                fired.append(ev)
        if self.info_env is not None:
            newly = self.info_env.advance_to(t)
            for b in newly:
                fired.append(ScheduledEvent(at_step=t, target_layer="information",
                                            op="set", note=f"broadcast: {b.content}"))
        return fired

    def apply(self, actions: list[Action]) -> None:
        m = self.model
        # Capture composition BEFORE this step's moves (for direction metrics).
        self._prev_race_df = m.environment.get_racial_composition_array().copy()
        m._step_inflow = defaultdict(int)
        m._apply_move_budget()          # validated per-race budget gate (reused)
        m.agents.shuffle_do("step")     # validated move execution (reused)
        # Annotate actions with the ACTUAL outcome (intent was set in decide_batch).
        for a in actions:
            agent = self.engine._agent_by_id.get(a.agent_id)
            if agent is not None:
                a.payload["moved"] = bool(agent.moved_this_step)
                if agent.moved_this_step:
                    a.payload["new_tract"] = agent.tract_id

    def observe_batch(self, agent_ids, t, round_idx: int = 0):
        m = self.model
        env = m.environment
        macro_phys = {"city_race_share": dict(m.city_race_share)}
        macro_info = self.info_env.macro() if self.info_env is not None else {}
        out = []
        for aid in agent_ids:
            agent = self.engine._agent_by_id[aid]
            tid = agent.tract_id
            local_info = self.info_env.local_for(self.engine.tract_ctx(tid)) if self.info_env else {}
            out.append(Observation(
                agent_id=aid, step=t,
                macro_physical=macro_phys,
                local_physical={
                    "tract_id": tid,
                    "surrounding": env.get_surrounding_area_summary(tid),
                },
                macro_information=dict(macro_info),
                local_information=local_info,
            ))
        return out

    def agent_state(self, agent_id: str) -> dict:
        a = self.engine._agent_by_id[agent_id]
        return {
            "tract_id": a.tract_id,
            "race": a.race,
            "pop_count": int(a.pop_count),
            "satisfaction": round(float(a.satisfaction), 3),
            "years_in_tract": int(a.years_in_tract),
            "moved_this_step": bool(a.moved_this_step),
        }

    def snapshot(self) -> dict:
        return {"race_df": self.model.environment.get_racial_composition_array()}


class ChicagoPopulationProvider(PopulationProvider):
    """Projects the model's HouseholdAgents into Personas with persistent ids."""

    def __init__(self, engine, bundle: PopulationBundle):
        self.engine = engine
        self.bundle = bundle

    def build(self, seed: int) -> list[Persona]:
        self.engine.ensure_built()
        personas = []
        for agent in self.model_agents():
            personas.append(Persona(
                agent_id=agent._sv_id,
                group_key=agent.archetype_key,
                weight=float(agent.pop_count),
                attributes={
                    "race": agent.race,
                    "income_bracket": agent.archetype.income_bracket,
                    "family_type": agent.archetype.family_type,
                    "neighborhood_type": agent.archetype.neighborhood_type,
                },
                init_state={"tract_id": agent.tract_id, "years_in_tract": int(agent.years_in_tract)},
            ))
        return personas

    def model_agents(self):
        return list(self.engine.model.agents)

    def interaction_structure(self) -> InteractionStructure:
        return InteractionStructure(kind="spatial_adjacency", adjacency_ref="queen_contiguity")

    def neighbors(self, agent_id: str) -> list[str]:
        # Spatial neighbours of an agent's tract (1-hop) — used if a local-info layer needs it.
        agent = self.engine._agent_by_id[agent_id]
        tids = set(self.engine.model.environment.get_neighbors(agent.tract_id, 1))
        return [aid for aid, a in self.engine._agent_by_id.items() if a.tract_id in tids]
