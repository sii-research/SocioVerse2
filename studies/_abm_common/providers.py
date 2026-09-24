"""The umbrella adapter: four GENERIC abc providers that wrap ANY SocioVerse-ABM task.

Registered once (abm.env / abm.pop / abm.decision / abm.collector). A study selects its
task purely by data — `provider_args["abm_task"]` — so all 11 ABM studies share this one
adapter with zero per-task code. The providers translate between SocioVerse-ABM's
(int-id, context-dict) Observation/Action and SocioVerse2's (str-id, 4-quadrant) schemas.

Uniform agent interface: every ABM task's `env.observe_batch()` yields one Observation
per agent (with `agent_id`, `state`, `context`, `rendered`) — that is what we map to
SocioVerse2 Personas and Observations. Because each ABM `build(cfg, seed)` is deterministic,
the population and environment providers can each build independently from the seed
(Path-B style) and stay consistent — no shared engine object needed (unlike Chicago).
"""
from __future__ import annotations

import zlib
from typing import Any

from socioverse.abc import (
    DecisionModel,
    EnvironmentProvider,
    MetricCollector,
    PopulationProvider,
)
from socioverse.engine import register
from socioverse.schemas import Action, Observation, Persona

from . import seam


def _sid(task: str, i: int) -> str:
    return f"{task}-{int(i):04d}"


def _iid(agent_id: str) -> int:
    return int(agent_id.rsplit("-", 1)[1])


def _scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


# --- P -----------------------------------------------------------------------------------------

@register("population", "abm.pop")
class AbmPopulationProvider(PopulationProvider):
    def __init__(self, bundle):
        self.bundle = bundle
        self.task = bundle.provider_args["abm_task"]
        self._overrides = bundle.provider_args.get("config")
        self._group_field = bundle.provider_args.get("group_field")

    def build(self, seed: int) -> list[Persona]:
        spec = seam.load_task(self.task)
        cfg = seam.task_config(self.task, self._overrides, seed=seed)
        env, _pop = spec.build(cfg, seed)
        personas = []
        for o in env.observe_batch():
            group = None
            if self._group_field and self._group_field in o.context:
                group = str(o.context[self._group_field])
            personas.append(Persona(
                agent_id=_sid(self.task, o.agent_id),
                group_key=group,
                attributes={k: v for k, v in o.context.items() if _scalar(v)},
                init_state={k: v for k, v in dict(o.state).items() if _scalar(v)},
            ))
        return personas


# --- E -----------------------------------------------------------------------------------------

@register("environment", "abm.env")
class AbmEnvironmentProvider(EnvironmentProvider):
    def __init__(self, bundle):
        self.bundle = bundle
        self.task = bundle.provider_args["abm_task"]
        self._overrides = bundle.provider_args.get("config")
        self.env = None
        self._states: dict[int, dict] = {}

    def reset(self, seed: int) -> None:
        spec = seam.load_task(self.task)
        cfg = seam.task_config(self.task, self._overrides, seed=seed)
        self.env, _pop = spec.build(cfg, seed)
        self._refresh_states()

    def advance_to(self, t: int) -> list:
        return []  # base ABM tasks have no exogenous scheduled events (yet)

    def apply(self, actions: list[Action]) -> None:
        from socioverse_abm.behavior_engine.action import Action as AbmAction
        my = [AbmAction(agent_id=_iid(a.agent_id), kind=a.kind, payload=dict(a.payload))
              for a in actions]
        self.env.apply(my)
        if hasattr(self.env, "advance"):
            self.env.advance()
        self._refresh_states()

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        by_id = {o.agent_id: o for o in self.env.observe_batch()}
        out = []
        for aid in agent_ids:
            o = by_id.get(_iid(aid))
            if o is None:                      # agent currently not active (jailed/evacuated)
                out.append(Observation(agent_id=aid, step=t))
                continue
            out.append(Observation(agent_id=aid, step=t,
                                   local_physical=dict(o.context),
                                   rendered=(o.rendered or None)))
        return out

    def _refresh_states(self) -> None:
        self._states = {o.agent_id: {k: v for k, v in dict(o.state).items() if _scalar(v)}
                        for o in self.env.observe_batch()}

    def agent_state(self, agent_id: str) -> dict:
        return self._states.get(_iid(agent_id), {})

    def snapshot(self) -> dict:
        s = dict(self.env.snapshot())
        s.pop("t", None)
        return s


# --- f / B -------------------------------------------------------------------------------------

@register("decision", "abm.decision")
class AbmDecisionModel(DecisionModel):
    """f for any SocioVerse-ABM task, in the task's own three modes.

    - ``rule``: the task's rule_f for every agent.
    - ``llm``: the task's llm_f for every agent.
    - ``hybrid``: SocioVerse-ABM's ``hybrid_decide`` routes each agent to rule_f or llm_f, as the
      native ``model.run`` does. The native default policy sends every agent to the rule, so
      hybrid equals rule and makes no LLM call unless ``llm_fraction`` (0-1) is set: then a
      fixed, seed-determined subset of about that share of agents uses llm_f at every step.
      ``route_to_llm`` (Python only) replaces the policy with any ``Observation -> bool``.

    In llm and hybrid mode the task's LLM layer is set up from its config.yaml (with the
    bundle's ``config`` overrides), as the native run does: ``llm_f.configure`` receives
    ``behavior.llm_model`` and, for tasks whose configure takes it (schelling,
    civil_violence), ``behavior.llm_behavior``.
    """

    MODES = ("rule", "llm", "hybrid")

    def __init__(self, abm_task: str, mode: str = "rule", seed: int = 42, llm: Any = None,
                 config: dict | None = None, llm_fraction: float | None = None,
                 route_to_llm: Any = None):
        if mode not in self.MODES:
            raise ValueError(f"unknown mode {mode!r} ({'|'.join(self.MODES)})")
        self.task = abm_task
        self.mode = mode
        self.seed = seed
        self._spec = seam.load_task(abm_task)
        self._llm = llm                        # injected client (fake for parity, real for live)
        seam.seed_decision(self._spec, seed)
        self.llm_model: str | None = None
        if mode != "rule":
            cfg = seam.task_config(abm_task, config, seed=seed)
            self.llm_model = seam.configure_llm(self._spec, cfg)
        if llm_fraction is not None and not 0.0 <= float(llm_fraction) <= 1.0:
            raise ValueError(f"llm_fraction must be in [0, 1], got {llm_fraction!r}")
        self.llm_fraction = None if llm_fraction is None else float(llm_fraction)
        self._route = route_to_llm or self._default_route()

    def _default_route(self):
        from socioverse_abm.behavior_engine.hybrid import always_rule

        if not self.llm_fraction:
            return always_rule                 # the native hybrid default
        frac, seed = self.llm_fraction, self.seed

        def by_fraction(o) -> bool:            # stable per agent and seed, across steps and runs
            h = zlib.crc32(f"{seed}:{self.task}:{int(o.agent_id)}".encode()) / 2 ** 32
            return h < frac
        return by_fraction

    def _llm_f(self, my_obs):
        return self._spec.llm_f(my_obs, llm=self._llm)

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        from socioverse_abm.behavior_engine.action import Observation as AbmObs
        my_obs = [AbmObs(agent_id=_iid(o.agent_id), state={}, context=dict(o.local_physical),
                         rendered=(o.rendered or ""))
                  for o in obs if o.local_physical]
        if self.mode == "rule":
            my_actions, srcs = list(self._spec.rule_f(my_obs)), None
        elif self.mode == "llm":
            my_actions, srcs = list(self._llm_f(my_obs)), None
        else:
            from socioverse_abm.behavior_engine.hybrid import hybrid_decide
            dec = hybrid_decide(my_obs, self._spec.rule_f, self._llm_f, self._route)
            my_actions, srcs = list(dec.actions), list(dec.source)
        step = obs[0].step if obs else 0
        if srcs is None or len(srcs) != len(my_actions):
            srcs = ["llm" if self.mode == "llm" else "rule"] * len(my_actions)
        return [Action(agent_id=_sid(self.task, a.agent_id), step=step, kind=a.kind,
                       payload=dict(a.payload), source=src)
                for a, src in zip(my_actions, srcs)]


# --- metrics -----------------------------------------------------------------------------------

@register("collector", "abm.collector")
class AbmMetricCollector(MetricCollector):
    def __init__(self, abm_task: str | None = None):
        self.task = abm_task

    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        # env is AbmEnvironmentProvider; snapshot() already strips 't'. Keep only scalar
        # metrics (a task may also expose nested diagnostics, e.g. axelrod's strategy_scores).
        return {k: v for k, v in env.snapshot().items() if isinstance(v, (int, float, bool))}
