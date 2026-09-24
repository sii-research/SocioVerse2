# `_abm_common` — the SocioVerse-ABM umbrella adapter

One adapter, many studies. The refactored **SocioVerse-ABM** project (sibling repo) is the
behavioral backend; this package wraps *any* of its tasks into SocioVerse2's four abc with **zero
per-task code**. The 11 `abm_*` studies differ only by data (`provider_args["abm_task"]`).

## How it works (Path C, but generic)

| file | role |
|------|------|
| `seam.py` | locate SocioVerse-ABM (`$SV_ABM_ROOT`, else the sibling clone `../SocioVerse-ABM` from https://github.com/Lishi905/SocioVerse-ABM), check its deps (numpy, networkx: `pip install -e ".[abm]"`), put it on `sys.path`, load a task via its own registry. The ABM kernel is package `socioverse_abm` (renamed from `socioverse` to avoid clashing with this repo's `socioverse`). |
| `providers.py` | the four generic abc — `abm.env / abm.pop / abm.decision / abm.collector` — that translate between SocioVerse-ABM's (int-id, context-dict) Observation/Action and SocioVerse2's (str-id, 4-quadrant) schemas. |
| `bundles.py` | `make_abm_bundles(task, ...)` → the four SocioVerse2 artifacts pointing at the shared providers. |
| `manifest.yaml` | the catalog of 11 `abm_*` studies. |

The **uniform agent interface** is every ABM task's `env.observe_batch()` (yields one
Observation per agent). Because each ABM `build(cfg, seed)` is deterministic, the population
and environment providers each build independently from the seed (Path-B style) — no shared
engine object (unlike Chicago). Agent ids are `f"{task}-{i:04d}"`.

## Adding / running a study

```python
import studies.abm_schelling as s          # registers the abm.* providers
study, env_b, pop_b, sim_c = s.make_bundles(n_steps=12, seed=42, mode="rule")
from socioverse.engine import build_simulator
hist = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                       store_path="run.duckdb").run()
```

Each `abm_<task>/__init__.py` is ~10 lines calling `make_abm_bundles`. **Parity guarantee**
(tested per study): the wrapped rule trajectory exactly reproduces the native socioverse_abm
rule trajectory on the same seed.

## Modes and the LLM model

`mode` takes the same three values as `sv-abm run --mode` in SocioVerse-ABM:

| mode | what `abm.decision` does |
|------|--------------------------|
| `rule` | the task's `rule_f` for every agent; no token, no key |
| `llm` | the task's `llm_f` for every agent (a client injected via `llm=`, else SocioVerse-ABM's OpenAI helper) |
| `hybrid` | SocioVerse-ABM's `hybrid_decide`, per agent. Its default policy routes **every agent to the rule**, as the native `--mode hybrid` does today, so a plain hybrid run equals the rule run and makes no LLM call. Pass `llm_fraction=0.3` (to `make_bundles`; a SocioVerse2-side knob, native `sv-abm` has no such option) to route a fixed, seed-determined ~30% of agents to `llm_f` at every step, or `route_to_llm=` (any `Observation -> bool`) to `AbmDecisionModel`; each action's `source` says which path it took. |

In `llm` and `hybrid` mode the LLM layer is configured the way the native `model.run` does it:
the task's `llm_f.configure(...)` receives `behavior.llm_model` from the task's `config.yaml`
(and `behavior.llm_behavior` for `schelling` and `civil_violence`). `config_overrides` are
merged in first, so `make_bundles(mode="llm", config_overrides={"behavior": {"llm_model":
"gpt-4o-mini"}})` sends every call as `gpt-4o-mini`. The config wins over an exported
`SV_LLM_MODEL`, which only seeds the `llm_f` module's default before configure runs.

## Requirements

SocioVerse-ABM's runtime deps must be importable in the SocioVerse2 env (`pip install -e ".[abm]"`): `pyyaml`, `numpy`,
`networkx` (sir), and `openai` only for live `mode="llm"`. Task discovery is defensive, so a
missing optional dep only disables that one task.
