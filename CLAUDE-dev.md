# SocioVerse2 — developer guide for Claude

> Audience: a collaborator (and their Claude) **wrapping an EXISTING legacy simulator** into
> SocioVerse2 — e.g. migrating **HiSim** / **ElectionSim** (this is routing **Path C**). If you only want
> to *run* existing studies, read `CLAUDE.md`.
>
> **Building a study FROM SCRATCH (Path B — no legacy simulator to wrap)? You do NOT need this guide
> or an engine-seam.** Use the `sv-build-model` skill: implement the four abc natively on Core and let
> `socioverse.engine.build_simulator` assemble them. The worked template is `studies/opinion_diffusion/`
> (+ `tests/test_opinion_diffusion.py`). This guide is specifically the legacy-wrap (seam + adapter) path.

## Mental model: Core (reused) vs Study (you write)

`B = f(P, E)`: fixed population `P` (persistent ids) under a dynamic environment `E`
(physical/information × macro/local), looped `E_t → B_t → E_{t+1}` so the same agents are tracked.

- **Core (`socioverse/`, reused — you DON'T touch it)** defines the **abc interfaces**, the
  **Engine** (`LongitudinalSimulator`), the **DuckDB store**, and the **Schemas** (typed contracts).
- **A study (you write)** = concrete implementations of the abc + (optional) an `engine-seam` +
  4 JSON artifacts. The Engine drives the loop and *calls into* your implementations.

Crucial distinction (the names collide): **Core `Engine`** = the reused `LongitudinalSimulator`.
**`engine-seam`** = study-internal **glue** that wraps a *legacy* simulator (e.g. Chicago's Mesa
model). The Core Engine never sees the engine-seam; only your own providers reference it.

## Core internals — the runtime flow (what the Engine does each step)

`socioverse/engine/loop.py` — every step runs the same **five phases**, in this order
(phase name → the call in `run()`):
```
build()           -> Persona[]            # P, built once, persistent ids, fixed thereafter
reset()                                   # E_0
for t in 1..N:                            # the longitudinal loop
  1 exogenous update  env.advance_to(t)   # scheduled events + info broadcasts change E;
                                          #   an intervention lands here, before anyone observes
  2 observe           env.observe_batch()      -> Observation[]  # each agent's 4-quadrant view
  3 decide            decision.decide_batch()  -> Action[] (= B) # batched LLM/rule decision
  4 apply             env.apply(actions)       # endogenous feedback: E -> E_{t+1}
  5 record            store.record(panel rows) + _collect() -> metrics -> DuckDB (panel/metrics/events)
```
**Data contract across the loop:** `Persona[] → Observation[] → Action[] → metrics → DuckDB`. Every
object's type is defined in `socioverse/schemas/` — Schemas is a **type/contract layer everything
references**, NOT a stage data flows *through*. `interaction_rounds > 1` hosts intra-step
agent-to-agent message exchange (HiSim); `= 1` for move-based models (Schelling).

## Before you build: check the catalog (don't reinvent an adapted study)

Run `python -c "from skills.sv_workspace import catalog_view; print(catalog_view())"` (or just `/sv-init`,
which does this in Step 0) to see every already-adapted study. If one shares your `domain` /
`legacy_simulator` and your changes are artifact-level (within its `adjustable_params`), you don't write
a new study at all — **fork it to a new `study_id`** (`fork_study(...)`) and edit the *fork's*
`environment.json` / `population.json` / `simulation.json`, then re-run (leave the matched study
untouched — never edit a reference template in place). Build a new study from scratch only when the
dynamics / simulator / interaction mode genuinely differ.

## What you implement (the migration recipe)

A study = **4 abc implementations + (optional) engine-seam + 4 artifacts**. Mirror
`studies/chicago_schelling/adapter/`:

1. **`EnvironmentProvider`** — `reset / advance_to(t) / apply(actions) / observe_batch / agent_state`.
   Tag every layer macro/local × physical/information; route scheduled change through `advance_to`,
   endogenous feedback through `apply`. **Branch contract:** make `apply(actions)` a **pure
   function of the passed actions + current env state** (fold the whole decision into the Action
   payload — see `opinion.env.apply` reading `a.payload["opinion"]`) and keep `interaction_rounds == 1`.
   Only then can `/sv-iterate` offer a **branch** — a version that adds interventions at `at_step >= t*`
   and *inherits* the parent's steps `0..t*-1` by replaying its stored actions (no LLM, no budget;
   warm start is the replay spec behind it). Studies that stash decision state elsewhere (chicago sets
   move-intent on legacy agents inside `decide_batch`, so its `apply` isn't action-pure) and
   multi-round studies can't be replayed: every edit there is a new version, run cold from step 0.
2. **`PopulationProvider`** — `build(seed) -> Persona[]` with **deterministic persistent ids** (so
   sv-build-population's pre-run materialization matches what sv-run rebuilds at t=0);
   `neighbors()` for local-information propagation.
3. **`DecisionModel`** — `decide_batch(obs, memories) -> Action[]`. Call your engine's *batched*
   decision; KEEP batching (never per-agent LLM).
4. **`MetricCollector`** — `collect(env, actions, t) -> dict`, wrapping the existing metrics.
5. **(optional) `engine-seam`** — a config-injection context manager that builds + holds a *legacy*
   engine WITHOUT editing its source. A from-scratch study skips this (then it's just the 4 abc impls).
6. Author the **4 artifacts** (`study.yaml`, `environment.json`, `population.json`, `simulation.json`)
   and register the classes via `socioverse.engine.registry`. **Fill `study.yaml`'s discovery fields**
   (`domain`, `tags`, `legacy_simulator` or `"from_scratch"`, `provider_refs`, `adjustable_params`,
   `status`, `maintainer`) — this is what puts your study in the catalog so `sv-init` Step 0 can route
   future queries to it. A study with empty discovery fields is invisible to routing.

`TrajectoryStore` / `Simulator` / `Reporter` are provided by Core — do not reimplement.

## Reference template: `studies/chicago_schelling/adapter/`

- `engine_seam.py` — `ChicagoEngine` + the **CONFIG_DIR/DATA_DIR monkey-patch** (the ONLY code that
  touches the legacy `src/`, vendored in the SocioVerse-ABM sibling clone under
  `tasks/organization/chicago_segregation/legacy/`; override with `SV_CHICAGO_LEGACY`). One shared
  engine instance is referenced by all four impls.
- `providers.py` / `decision.py` / `metrics.py` — the four abc impls; they **reuse the legacy
  model's own validated phase methods** (hybrid wrap), never re-deriving the dynamics.
- `build.py` — `make_chicago_bundles` + `build_chicago_simulator` wiring.
- `fake_llm.py` — `DeterministicLLMClient` for no-token parity tests.

## Dev gotchas (IMPORTANT)

- **Never edit the legacy Chicago `src/`, `config/`, `processed_data/`, `run_prototype.py`** (in
  SocioVerse-ABM's `tasks/organization/chicago_segregation/legacy/`). Wrap via the monkey-patch seam.
- **Step-counter coupling**: the legacy model's 3-step cascade reads `len(metrics_history)`, and its
  `__init__` pre-seeds a step-0 row. The collector appends to `model.metrics_history` for each
  move-step (t≥1) and returns the existing step-0 row at t=0 — preserve this or the cascade desyncs.
- **`engine-seam` ≠ Core `Engine`** (see above). It carries no abc; it's shared *internal* glue.
- **Pin `mesa==3.3.1`** for studies wrapping Chicago (its shuffle RNG is part of the calibration).
  Core itself has no Mesa dependency.
- **Persistent ids must be deterministic** (e.g. `chi-{archetype}-{init_tract}-{clone_idx}`) so panels
  join across runs/resumes.
- **One study per process** (monkey-patch globals aren't parallel-safe).

## Testing a new study

Prove your adapter re-drives the original dynamics with **`DeterministicLLMClient`** (temp 0.7 makes
live runs non-reproducible): run the legacy path and your adapter on the same seed and assert the
metric trajectories match (see `tests/test_chicago_parity.py`). Use the deterministic client for all
plumbing/CI; reserve real LLM for demos.

## Scenario hooks (for HiSim / ElectionSim / consumer-confidence)

- **Agent-to-agent interaction** (HiSim): set `interaction_rounds = K`; your EnvironmentProvider owns a
  `MessageBus` (`socioverse/engine/messaging.py` + `env_layers/neighbor_feed.py`). Mediated, not O(N²).
- **Information environment** (news/policy): `Broadcast` + `InformationProgram`, audience-scoped
  (`audience="all"` → macro; selector dict → local). See `env_layers/information.py`.
- **External data / MCP / tools**: declare them in `ResourceManifest`; draw population from
  `FilePopulationProvider` / `McpPopulationProvider` (`socioverse/providers.py`), or point an env
  provider at a user-supplied data dir.

## Key files (for development)
- `socioverse/abc/*` — the interfaces you implement.
- `socioverse/engine/loop.py` — the loop you plug into (read it once).
- `socioverse/schemas/*` — the typed contracts (Observation/Action/Persona/...).
- `socioverse/io/duckdb_store.py` — the trajectory store you write into.
- `studies/chicago_schelling/adapter/*` — the end-to-end template.

See `README-dev.md` for the architecture diagram-in-prose and the full migration playbook.
