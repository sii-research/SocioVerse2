# opinion_diffusion — from-scratch study (Path B template)

The reference for building a study **from zero on Core** (no legacy simulator, no engine-seam) — what
the `sv-build-model` skill produces when a query matches no already-adapted study.

Bounded-confidence opinion dynamics on a ring network: agents nudge their opinion toward like-minded
neighbours each step, while a step-2 media-pressure `ScheduledEvent` (macro-physical) and a campaign
`Broadcast` (macro-information) pull opinions upward. It exercises every SocioVerse2 feature — persistent ids,
all four observation quadrants, exogenous events + broadcasts, endogenous feedback, longitudinal metrics.

## Files
- `model.py` — the four abc (`opinion.env / opinion.pop / opinion.decision / opinion.collector`) +
  `make_opinion_bundles()`. The `DecisionModel` is a deterministic rule (free + reproducible); swap
  `decide_batch` for a **batched** LLM call to make it LLM-native (see chicago's `adapter/decision.py`).
- `study.yaml`, `environment/`, `population/`, `simulation/`, `resources.json` — the validated artifacts.

## Run it (no tokens)
```python
import studies.opinion_diffusion                      # registers opinion.* refs
from socioverse.engine import build_simulator
from studies.opinion_diffusion.model import make_opinion_bundles

study, env_b, pop_b, sim_c = make_opinion_bundles()
sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c, store_path="/tmp/od.duckdb")
hist = sim.run()                                       # opinion_std falls (convergence); mean rises after step 2
```
Wiring is generic: each provider takes only its bundle, so `build_simulator` resolves everything from the
registry — no per-study builder. See `tests/test_opinion_diffusion.py`.
