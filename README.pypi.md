# SocioVerse2

**Social evolution, visible and testable.** SocioVerse2 is a longitudinal social-simulation
runtime: a fixed population of agents with persistent ids lives through an environment that
keeps changing, interventions fire at chosen steps, and every step is stored as panel data in
DuckDB.

[Repository](https://github.com/sii-research/SocioVerse2) ·
[User manual](https://socioverse.fudan-disc.com/docs/) ·
[Technical report](https://arxiv.org/abs/2609.24911) ·
[Homepage](https://socioverse.fudan-disc.com/)

This package is the runtime library (`import socioverse`): the typed schemas, the interfaces a
study implements, the longitudinal loop and the DuckDB trajectory store. The `/sv-*` workflow
skills for Claude Code and Codex, the research dashboard and the reference studies come with a
clone of the [GitHub repository](https://github.com/sii-research/SocioVerse2); its README has
the full quickstart.

## Install

```bash
pip install socioverse2
```

Python 3.11 or later. Extras: `llm` (OpenAI-compatible client), `viz` (matplotlib).

## A study in one file

A study implements four interfaces: the environment (what each agent observes), the population
(who the agents are), the decision model (what they do) and a metric collector. The loop runs
`observe, decide, apply` for each step and records one panel row per agent.

```python
from statistics import mean

import duckdb
from socioverse.abc import DecisionModel, EnvironmentProvider, MetricCollector, PopulationProvider
from socioverse.engine import LongitudinalSimulator
from socioverse.io import DuckDbTrajectoryStore
from socioverse.schemas import (Action, EnvironmentBundle, EnvironmentLayer, Observation,
                                Persona, PopulationBundle, ScheduledEvent)

N = 10  # agents on a ring, with persistent ids a0..a9


class Town(EnvironmentProvider):
    """E: each agent sees its own and its two neighbours' opinions, plus a media-pressure level."""

    def __init__(self, bundle):
        self.bundle = bundle

    def reset(self, seed):
        self.opinion = {f"a{i}": i / (N - 1) for i in range(N)}
        self.pressure = 0.0

    def advance_to(self, t):  # fire the scheduled interventions of step t
        fired = [ev for ev in self.bundle.scheduled_events if ev.at_step == t]
        for ev in fired:
            self.pressure = float(ev.value)
        return fired

    def apply(self, actions):
        for a in actions:
            self.opinion[a.agent_id] = a.payload["opinion"]

    def observe_batch(self, agent_ids, t, round_idx=0):
        obs = []
        for aid in agent_ids:
            i = int(aid[1:])
            peers = [self.opinion[f"a{(i + d) % N}"] for d in (-1, 1)]
            obs.append(Observation(agent_id=aid, step=t,
                                   macro_physical={"pressure": self.pressure},
                                   local_physical={"own": self.opinion[aid], "peers": peers}))
        return obs

    def agent_state(self, aid):
        return {"opinion": round(self.opinion[aid], 3)}

    def snapshot(self):
        return dict(self.opinion)


class People(PopulationProvider):
    """P: a fixed population."""

    def __init__(self, bundle):
        self.bundle = bundle

    def build(self, seed):
        return [Persona(agent_id=f"a{i}") for i in range(N)]


class Rule(DecisionModel):
    """B: move halfway to the neighbours' mean; media pressure pulls toward 1."""

    def decide_batch(self, obs, memories):
        actions = []
        for ob in obs:
            x = ob.local_physical["own"]
            x += 0.5 * (mean(ob.local_physical["peers"]) - x)
            x += 0.2 * ob.macro_physical["pressure"] * (1 - x)
            actions.append(Action(agent_id=ob.agent_id, step=ob.step, kind="update",
                                  payload={"opinion": x}, source="rule"))
        return actions


class Metrics(MetricCollector):
    def collect(self, env, actions, t):
        return {"mean_opinion": round(mean(env.snapshot().values()), 3)}


env_bundle = EnvironmentBundle(
    study_id="town", provider_ref="town.env",
    layers=[EnvironmentLayer(name="media", modality="physical", scope="macro")],
    scheduled_events=[ScheduledEvent(at_step=2, target_layer="media", op="set",
                                     property_name="pressure", value=1.0, note="media campaign")],
)
sim = LongitudinalSimulator(
    env=Town(env_bundle),
    population=People(PopulationBundle(study_id="town", provider_ref="town.pop")),
    decision=Rule(), collector=Metrics(),
    store=DuckDbTrajectoryStore("town.duckdb", study_id="town"),
    n_steps=4, study_id="town",
)
for row in sim.run().rows:
    print(row)

con = duckdb.connect("town.duckdb", read_only=True)
con.sql("SELECT step, state->>'opinion' AS opinion FROM panel WHERE agent_id = 'a0' ORDER BY step").show()
con.sql("SELECT step, note FROM events").show()
```

Swap `Rule` for a decision model that prompts an LLM and the same loop runs LLM agents. The
repository's reference studies show that pattern, plus information broadcasts, multi-round
discussion, counterfactual branches and wrapping an existing simulator.

## Citation

```bibtex
@misc{zhang2026socioverse2,
  title         = {SocioVerse2: A Longitudinal Dynamic Social Simulation Framework under a Human-AI Co-evolutionary Paradigm},
  author        = {Xinnong Zhang and Jiayu Lin and Jia Wang and Yixu Huang and Xinyi Mou and Yingqian Wu and Jingcong Liang and Shijun Lei and Jianing Shi and Guanying Li and Siyuan Wang and Hanjia Lyu and Zhenfei Yin and Yunlu Yin and Siming Chen and Yulan He and Jiebo Luo and Xuanjing Huang and Liyin Jin and Baohua Zhou and Hanqi Yan and Zhongyu Wei},
  year          = {2026},
  eprint        = {2609.24911},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/2609.24911}
}
```

## License

Apache License 2.0. See [LICENSE](https://github.com/sii-research/SocioVerse2/blob/main/LICENSE)
and [NOTICE](https://github.com/sii-research/SocioVerse2/blob/main/NOTICE).
