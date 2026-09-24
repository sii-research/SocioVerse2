"""opinion_diffusion — a FROM-SCRATCH SocioVerse2 study (Path B reference template).

No legacy simulator, no engine-seam: this is the four abc implementations written natively
against Core, plus a `make_opinion_bundles()` artifact factory. It is the template a
`sv-build-model` run mirrors when a user's query matches no already-adapted study.

The model is bounded-confidence opinion dynamics on a ring network, which exercises every
SocioVerse2 feature a real study needs:
  - P: a FIXED pool of agents with persistent ids (`od-000`, ...), tracked across steps.
  - E (4 quadrants): neighbours' opinions (local_physical), a scheduled media-pressure scalar
    (macro_physical, via ScheduledEvent), and a macro campaign message (macro_information, via
    Broadcast).
  - B: each step every agent nudges its opinion toward like-minded neighbours, plus media/campaign
    pull. The loop folds B back into E (apply) so opinions evolve E_t -> B_t -> E_{t+1}.

Wiring is generic: each provider takes only its bundle, so `socioverse.engine.build_simulator`
assembles the study from the registry with zero per-study glue (see tests/test_opinion_diffusion.py).
The DecisionModel has TWO modes behind one registered ref (`opinion.decision`):
  - `llm_kind="scripted"` (DEFAULT) — the deterministic bounded-confidence rule (free + reproducible),
    the parity baseline every from-scratch template ships with;
  - `llm_kind="openai"` — each agent role-plays in its own LLM call over the SV_LLM channel
    (gpt-4o family); a step's calls go out together on a bounded thread pool, and the SAME
    bounded-confidence arithmetic is applied, per agent, as a guaranteed fallback whenever that
    agent's reply doesn't parse (the raw reply is logged). Selected at run time via `decision_args={"llm_kind": ...}`
    — no code change, same registered provider. `prompt_lang` ("en" default, or "zh") picks the
    prompt's language; the shipped reference run used "zh". See studies/campus_dining_choice/model.py for the
    sibling pattern and studies/chicago_schelling/adapter/decision.py for a legacy-seam LLM decision.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Callable

from socioverse.abc import (
    DecisionModel,
    EnvironmentProvider,
    MetricCollector,
    PopulationProvider,
)
from socioverse.engine import register
from socioverse.schemas import (
    Action,
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    InteractionStructure,
    Observation,
    Persona,
    PopulationBundle,
    PropagationMode,
    ScheduledEvent,
    SimulationConfig,
    StudySpec,
)

# --- shared, PURE seed functions (no mutable shared state -> generic cls(bundle) wiring works) ---

def agent_id(i: int) -> str:
    return f"od-{i:03d}"


def initial_opinion(i: int, n: int) -> float:
    """Deterministic spread across [0, 1] so the population starts maximally dispersed."""
    return round((i + 0.5) / n, 4)


def ring_neighbors(i: int, n: int) -> list[int]:
    """Each agent talks to its two ring neighbours (a tiny explicit network)."""
    return [(i - 1) % n, (i + 1) % n]


def ring_edges(n: int) -> list[tuple[str, str]]:
    return [(agent_id(i), agent_id((i + 1) % n)) for i in range(n)]


# --- P: the fixed population pool ---------------------------------------------------------------

@register("population", "opinion.pop")
class OpinionPopulationProvider(PopulationProvider):
    def __init__(self, bundle: PopulationBundle):
        self.bundle = bundle
        self.n = int(bundle.provider_args.get("n_agents", 12))

    def build(self, seed: int) -> list[Persona]:
        out = []
        for i in range(self.n):
            x0 = initial_opinion(i, self.n)
            out.append(Persona(
                agent_id=agent_id(i),
                group_key="high" if x0 >= 0.5 else "low",   # batching/interaction cohort
                attributes={"opinion0": x0},
                init_state={"opinion": x0},
            ))
        return out

    def neighbors(self, aid: str) -> list[str]:
        i = int(aid.split("-")[1])
        return [agent_id(j) for j in ring_neighbors(i, self.n)]


# --- E: the dynamic environment (owns the mutable opinion state) --------------------------------

@register("environment", "opinion.env")
class OpinionEnvironmentProvider(EnvironmentProvider):
    def __init__(self, bundle: EnvironmentBundle):
        self.bundle = bundle
        self.n = int(bundle.provider_args.get("n_agents", 12))
        self.opinions: dict[str, float] = {}
        self.media: float = 0.0                # macro-physical scalar, ramped by a ScheduledEvent
        self.campaign: str | None = None       # macro-information, activated by a Broadcast
        self._fired: set[int] = set()

    def reset(self, seed: int) -> None:
        self.opinions = {agent_id(i): initial_opinion(i, self.n) for i in range(self.n)}
        self.media = 0.0
        self.campaign = None
        self._fired = set()

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        fired: list[ScheduledEvent] = []
        for ev in self.bundle.scheduled_events:
            if ev.at_step == t and id(ev) not in self._fired:
                if ev.target_layer == "media_pressure":
                    self.media = float(ev.value) if ev.op == "set" else self.media + float(ev.value)
                self._fired.add(id(ev))
                fired.append(ev)
        # activate/expire macro-information broadcasts (audience='all') within their ttl window
        active = [b for b in self.bundle.information_program.broadcasts
                  if b.is_macro and b.at_step <= t < b.at_step + b.ttl]
        self.campaign = active[-1].content if active else None
        return fired

    def apply(self, actions: list[Action]) -> None:
        for a in actions:                      # endogenous feedback E_{t+1} = f(E_t, B_t)
            if a.kind == "update_opinion":
                self.opinions[a.agent_id] = float(a.payload["opinion"])

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        out = []
        for aid in agent_ids:
            i = int(aid.split("-")[1])
            neigh = [self.opinions[agent_id(j)] for j in ring_neighbors(i, self.n)]
            out.append(Observation(
                agent_id=aid, step=t,
                local_physical={"own_opinion": self.opinions[aid], "neighbor_opinions": neigh},
                macro_physical={"media_pressure": self.media},
                macro_information={"campaign": self.campaign} if self.campaign else {},
            ))
        return out

    def agent_state(self, aid: str) -> dict:
        return {"opinion": self.opinions[aid]}

    def snapshot(self) -> dict:
        return {"media_pressure": self.media, "campaign_active": self.campaign is not None}


# --- B: the decision model (bounded-confidence rule + opt-in per-agent LLM behind one ref) ------

_log = logging.getLogger(__name__)


def _load_dotenv(root: Path | None = None) -> None:
    """Hydrate SV_LLM_* from `.env` without overriding the process env: `root/.env` when
    given, else the documented lookup order ($SV_HOME/.env, ./.env, then the repo root)."""
    from socioverse.external_events import _load_dotenv as load

    load(root)


class _OpenAILLM:
    """Thin OpenAI-compatible client over the SV_LLM channel (gpt-4o family), lazily connected."""

    def __init__(self, model: str | None = None, temperature: float = 0.5, max_tokens: int = 120):
        _load_dotenv()
        self.model = model or os.environ.get("SV_LLM_MODEL", "gpt-4o")
        self.temperature, self.max_tokens = temperature, max_tokens
        self._client = None

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("SV_LLM_BASE_URL", "https://api.openai.com/v1"))
        return self._client

    def __call__(self, prompt: str) -> str:
        resp = self._ensure().chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""


def _make_llm(kind: str, **kw) -> Callable[[str], str] | None:
    if kind == "scripted":
        return None
    if kind == "openai":
        return _OpenAILLM(**kw)
    raise ValueError(f"unknown llm_kind: {kind!r}")


# The prompt in each supported language. `prompt_lang` in decision_args picks one; the shipped
# reference run used "zh" (recorded in its simulation.json), new studies default to "en".
_PROMPTS: dict[str, dict[str, Any]] = {
    "en": {
        "head": ["You are one person in a public-opinion survey. On a continuous scale from 0 to 1, "
                 "rate how much you support adopting a new policy right now",
                 "(0 = fully against, 0.5 = neutral, 1 = fully for). Weigh the information below "
                 "and give your updated stance:"],
        "own": "- Your current stance: {x}",
        "neigh": "- The current stances of your two neighbours: {n}",
        "media": "- Current media pressure (0 = none, 1 = strongest): {m}",
        "campaign": '- You just saw a campaign message: "{c}"',
        "tail": ["How you behave: you move toward neighbours whose stance is close to yours "
                 "(you ignore opinions that are too far from yours);",
                 "media pressure and campaign messages gently push you toward support (closer to 1), "
                 "but you never change all at once.",
                 'Output one line of JSON only: {"opinion": <a number from 0 to 1>, '
                 '"reason": "<a reason of at most 10 words>"}'],
    },
    "zh": {
        "head": ["你是一次社会意见调查中的一个人。用 0 到 1 的连续数值表示你此刻对“采纳一项新政策”的支持程度",
                 "(0=完全反对, 0.5=中立, 1=完全支持)。请综合以下信息，给出你更新后的立场:"],
        "own": "- 你当前的立场: {x}",
        "neigh": "- 你两位邻居当前的立场: {n}",
        "media": "- 当前的媒体宣传压力(0=无, 1=最强): {m}",
        "campaign": "- 你刚看到一条宣传信息: “{c}”",
        "tail": ["行为准则: 你倾向于向与自己立场接近的邻居靠拢(差距过大的意见会被你忽略);",
                 "媒体压力与宣传信息会温和地把你往支持(更接近1)推动，但你不会瞬间改变。",
                 '只输出一行 JSON: {"opinion": <0到1的数值>, "reason": "<不超过15字的理由>"}'],
    },
}
PROMPT_LANGS = tuple(_PROMPTS)


def build_opinion_prompt(ob: Observation, lang: str = "en") -> str:
    """Ask the agent to role-play its next stance on a 0–1 scale from its own + neighbours' opinions
    plus the macro media pressure / campaign message, in `lang` ("en" or "zh"). Kept short +
    numeric for cheap, parseable replies."""
    t = _PROMPTS[lang]
    x = ob.local_physical["own_opinion"]
    neigh = ob.local_physical["neighbor_opinions"]
    media = ob.macro_physical.get("media_pressure", 0.0)
    campaign = ob.macro_information.get("campaign")
    lines = [
        *t["head"],
        t["own"].format(x=round(float(x), 3)),
        t["neigh"].format(n=[round(float(o), 3) for o in neigh]),
        t["media"].format(m=round(float(media), 3)),
    ]
    if campaign:
        lines.append(t["campaign"].format(c=campaign))
    lines += t["tail"]
    return "\n".join(lines)


_NUM_RE = re.compile(r'"opinion"\s*:\s*([0-9]*\.?[0-9]+)')
_REASON_RE = re.compile(r'"reason"\s*:\s*"([^"]*)"')


def parse_opinion_reply(resp: str) -> dict | None:
    """Pull {opinion, reason} out of the model's reply; None when no usable number is present."""
    if not resp:
        return None
    m = _NUM_RE.search(resp)
    if m is None:                                             # last-ditch: first bare float in the text
        m = re.search(r'\b(0?\.\d+|1(?:\.0+)?|0)\b', resp)
    if m is None:
        return None
    try:
        val = float(m.group(1))
    except (TypeError, ValueError):
        return None
    r = _REASON_RE.search(resp)
    return {"opinion": min(1.0, max(0.0, val)), "reason": (r.group(1) if r else "").strip()}


@register("decision", "opinion.decision")
class BoundedConfidenceDecision(DecisionModel):
    """Bounded-confidence opinion update. `llm_kind="scripted"` (default) runs the deterministic
    rule; `llm_kind="openai"` role-plays each agent in its own LLM call (one concurrent fan-out per
    step), falling back to the identical rule arithmetic for any agent whose reply doesn't parse — so
    the metric columns are always filled."""

    def __init__(self, confidence: float = 0.3, peer_rate: float = 0.5,
                 media_gain: float = 0.1, campaign_gain: float = 0.15,
                 llm_kind: str = "scripted", model: str | None = None,
                 temperature: float = 0.5, max_tokens: int = 120, max_workers: int = 8,
                 prompt_lang: str = "en"):
        if prompt_lang not in PROMPT_LANGS:
            raise ValueError(f"prompt_lang must be one of {PROMPT_LANGS}, got {prompt_lang!r}")
        self.prompt_lang = prompt_lang
        self.confidence = confidence
        self.peer_rate = peer_rate
        self.media_gain = media_gain
        self.campaign_gain = campaign_gain
        self.llm_kind = llm_kind
        self.max_workers = max(1, int(max_workers))
        self.llm = _make_llm(llm_kind, model=model, temperature=temperature, max_tokens=max_tokens)

    def _rule_opinion(self, ob: Observation) -> tuple[float, float]:
        """The deterministic bounded-confidence update; returns (new_opinion, peer_target)."""
        x = ob.local_physical["own_opinion"]
        within = [o for o in ob.local_physical["neighbor_opinions"] if abs(o - x) <= self.confidence]
        target = mean([x] + within)
        new = x + self.peer_rate * (target - x)                       # move toward like-minded peers
        media = ob.macro_physical.get("media_pressure", 0.0)
        new += self.media_gain * media * (1.0 - new)                  # macro-physical pull toward 1
        if ob.macro_information.get("campaign"):
            new += self.campaign_gain * (1.0 - new)                   # macro-information pull toward 1
        return round(min(1.0, max(0.0, new)), 4), target

    def _ask(self, ob: Observation) -> tuple[Observation, str]:
        if self.llm is None:
            return ob, ""
        try:
            return ob, self.llm(build_opinion_prompt(ob, self.prompt_lang))
        except Exception as exc:
            _log.warning("LLM call failed for %s: %s", ob.agent_id, exc)
            return ob, ""

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        if self.llm_kind == "openai" and len(obs) > 1:
            from concurrent.futures import ThreadPoolExecutor
            if hasattr(self.llm, "_ensure"):
                self.llm._ensure()
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(obs))) as ex:
                results = list(ex.map(self._ask, obs))
        else:
            results = [self._ask(ob) for ob in obs]

        actions = []
        for ob, resp in results:
            rule_new, target = self._rule_opinion(ob)
            media = ob.macro_physical.get("media_pressure", 0.0)
            has_campaign = bool(ob.macro_information.get("campaign"))
            payload_extra: dict[str, Any] = {}
            if self.llm_kind == "openai":
                dec = parse_opinion_reply(resp)
                if dec is not None:
                    new = round(dec["opinion"], 4)
                    source = "llm"
                    rationale = [dec.get("reason") or f"llm~{new}"]
                    # the model's one-line reason reaches the panel (action_payload), as in
                    # campus_dining_choice, so SQL and the dashboard drill-down can show it
                    payload_extra = {"reason": dec.get("reason", "")}
                else:                                          # unparsed reply → guaranteed rule fallback
                    _log.warning("unparsed reply from %s, using the rule: %r", ob.agent_id, resp[:300])
                    new = rule_new
                    source = "fallback"
                    rationale = [f"peers~{round(target, 2)}", f"media={media}", f"campaign={has_campaign}"]
            else:
                new = rule_new
                source = "rule"
                rationale = [f"peers~{round(target, 2)}", f"media={media}", f"campaign={has_campaign}"]
            actions.append(Action(
                agent_id=ob.agent_id, step=ob.step, kind="update_opinion",
                payload={"opinion": new, **payload_extra}, source=source, rationale=rationale,
            ))
        return actions


# --- metrics ------------------------------------------------------------------------------------

@register("collector", "opinion.collector")
class OpinionMetricCollector(MetricCollector):
    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        vals = list(env.opinions.values())
        return {
            "mean_opinion": round(mean(vals), 4),
            "opinion_std": round(pstdev(vals), 4),          # drops over time = convergence
            "frac_above_0_5": round(sum(v >= 0.5 for v in vals) / len(vals), 4),
        }

    def columns(self) -> list[str]:
        return ["mean_opinion", "opinion_std", "frac_above_0_5"]


# --- artifact factory (what sv-build-* would write to disk) -------------------------------------

OD_METRICS = ["mean_opinion", "opinion_std", "frac_above_0_5"]


def make_opinion_bundles(
    study_id: str = "opinion_diffusion",
    *,
    n_agents: int = 12,
    n_steps: int = 4,
    campaign_step: int = 2,
    seed: int = 42,
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    study = StudySpec(
        study_id=study_id,
        title="Opinion diffusion under a media campaign (from-scratch template)",
        research_question="Does a step-2 media campaign accelerate opinion convergence and shift the mean upward?",
        hypothesis="Bounded-confidence peer averaging shrinks opinion_std over time; the campaign lifts mean_opinion at/after step 2.",
        study_type="longitudinal", n_steps=n_steps, seed=seed, metrics=OD_METRICS,
        domain="opinion-dynamics",
        tags=["opinion-dynamics", "bounded-confidence", "network", "from-scratch"],
        legacy_simulator="from_scratch",
        provider_refs=["opinion.env", "opinion.pop", "opinion.decision", "opinion.collector"],
        adjustable_params=["n_agents", "n_steps", "confidence threshold", "campaign step & content",
                           "media_pressure schedule"],
        status="demo-only",
    )
    env_bundle = EnvironmentBundle(
        study_id=study_id, provider_ref="opinion.env",
        provider_args={"n_agents": n_agents},
        layers=[
            EnvironmentLayer(name="peer_opinions", modality="physical", scope="local",
                             dynamics="endogenous", description="ring neighbours' current opinions"),
            EnvironmentLayer(name="media_pressure", modality="physical", scope="macro",
                             dynamics="scheduled", description="city-wide media pressure scalar"),
            EnvironmentLayer(name="campaign", modality="information", scope="macro",
                             dynamics="scheduled", description="broadcast campaign message"),
        ],
        scheduled_events=[ScheduledEvent(at_step=campaign_step, target_layer="media_pressure",
                                         op="set", property_name="level", value=1.0,
                                         note="media pressure ramps up at the campaign step")],
        information_program=InformationProgram(broadcasts=[
            Broadcast(message_id="C1", channel="campaign", at_step=campaign_step, ttl=2,
                      audience="all", content="Adopt the new policy — it benefits everyone."),
        ]),
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="opinion.pop", provider_args={"n_agents": n_agents},
        interaction=InteractionStructure(kind="explicit_network", edges=ring_edges(n_agents)),
        propagation=PropagationMode.CONTAGION,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed,
        decision_ref="opinion.decision", decision_args={"confidence": 0.3},
        collector_ref="opinion.collector", interaction_rounds=1,
    )
    return study, env_bundle, pop_bundle, sim_config
