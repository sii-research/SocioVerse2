# SocioVerse2 — developer / contributor guide

How to **wrap an existing legacy simulator** into SocioVerse2 (e.g. **HiSim**, **ElectionSim**,
consumer-confidence) — routing **Path C**. If you only want to *run* studies, see [`README.md`](README.md).

> **From-scratch study (Path B — nothing to wrap)?** Skip the seam/adapter machinery here. Use the
> `sv-build-model` skill to write the four abc natively on Core; `socioverse.engine.build_simulator`
> runs them. Template: [`studies/opinion_diffusion/`](studies/opinion_diffusion/model.py). This guide
> is the legacy-wrap path.

## Architecture: Core (reused) vs Study (you write)

```
socioverse/            CORE RUNTIME — reused, you don't touch it
  schemas/             typed contracts (StudySpec, EnvironmentBundle, PopulationBundle,
                       SimulationConfig, Observation, Action, TrajectoryRecord, MetricsHistory, …)
  abc/                 the interfaces a study implements (EnvironmentProvider, PopulationProvider,
                       DecisionModel, MetricCollector) + Simulator / TrajectoryStore / Reporter / MessageBus
  engine/              LongitudinalSimulator (the loop), AgentMemory, registry, InMemoryMessageBus
  io/duckdb_store.py   the queryable panel/metrics/events/messages store
  env_layers/          information-axis helpers (Broadcast delivery, neighbour feed)
  providers.py         generic File/Mcp PopulationProviders (scenario 3)
  validation.py        validate_handoff — the strict skill-boundary guard
.claude/skills/        the sv-* workflow skills (usage layer; report fans out into lit/paper)
studies/chicago_schelling/   reference study (template for migrations)
```

**Core defines the contract; a study supplies the implementations.** The Engine drives the loop and
*calls into* your implementations through the abc; you never modify the Engine.

> Name clash to internalize: **Core `Engine`** = the reused `LongitudinalSimulator`.
> **`engine-seam`** = study-internal **glue** wrapping a *legacy* simulator — Core never calls it; only
> your own providers reference it.

## The runtime flow + data contract

Every step runs the same **five phases**, in this order (the names on the left are the ones used
throughout the docs; on the right, what `socioverse/engine/loop.py` actually calls):

```
build() -> Persona[]                        # P: built once, persistent ids, fixed thereafter
reset()                                     # E_0
loop t=1..N:
  1 exogenous update   env.advance_to(t)                    # scheduled events + info broadcasts mutate E
  2 observe            env.observe_batch() -> Observation[] # 4-quadrant per-agent view (macro/local × physical/info)
  3 decide             decision.decide_batch() -> Action[]  (= B)   # whole step in, one Action per agent out
  4 apply              env.apply(actions)                   # endogenous feedback E -> E_{t+1}
  5 record             store.record(panel rows) + _collect() -> metrics -> DuckDB
```

An **intervention** (a `ScheduledEvent` or a `Broadcast`) fires in phase 1, before any agent
observes, so the whole round is decided on one and the same state.

Each object's **type lives in `socioverse/schemas/`** — Schemas is a type/contract layer everything
references, not a stage data flows through. The hand-offs are `Persona[] → Observation[] → Action[] → metrics`.

## Migration playbook — implement `4 abc impls + (optional) engine-seam + 4 artifacts`

Mirror `studies/chicago_schelling/adapter/`:

1. **Stand up the seam (only if wrapping legacy code).** A context manager that injects the
   workspace config paths and constructs the legacy engine *inside* it — never edit the original `src/`.
   (From-scratch studies skip this.)
2. **`EnvironmentProvider`** — map the world state; `observe_batch` (tag pieces macro/local × physical/
   information), `apply` (endogenous), `advance_to(t)` (exogenous events + broadcasts).
3. **`PopulationProvider`** — project agents → `Persona` with **deterministic persistent ids**;
   `group_key` = the batching cohort; encode the neighbour/network relation as `InteractionStructure`.
4. **`DecisionModel.decide_batch`** — receives the whole step at once; call the wrapped engine's own
   decision, keep its call pattern (e.g. Chicago's archetype-grouped LLM phases) and project the
   result to typed `Action`s. That rule is for legacy wraps only: a from-scratch study calls the LLM
   once per agent, sending the step's calls concurrently (see the `sv-build-model` skill), and never
   asks for one JSON reply covering the whole population.
5. **`MetricCollector`** — wrap the existing metrics → the DuckDB store (reused from Core).
6. **4 artifacts** (`study/env/pop/sim.json`) + register classes via `socioverse.engine.registry`.
   Fill `study.yaml`'s **discovery fields** (`domain`, `tags`, `legacy_simulator`/`"from_scratch"`,
   `provider_refs`, `adjustable_params`, `status`) so your study joins the **catalog** that
   `sv-init` Step 0 routes against (`skills.sv_workspace.catalog_view()` lists everything adapted).
   First check that catalog — if an existing study fits and your changes are artifact-level, adjust it
   instead of writing a new one.
7. **Parity test**: with `DeterministicLLMClient`, assert your adapter reproduces the legacy
   trajectory on the same seed (see `tests/test_chicago_parity.py`).

**To support branches** (counterfactual versions that replay the parent's steps instead of paying
for them again): `env.apply(actions)` must be a **pure function of the actions passed in** (fold the
whole decision into the Action payload — never stash it on the agents inside `decide_batch`) and the
study must run with `interaction_rounds == 1`. Otherwise the engine refuses to replay and every edit
runs cold as a new version.

Deliverable per migration is fixed; the original simulator stays untouched.

## Scenario hooks already in Core

- **Audience-scoped information** — `Broadcast`/`InformationProgram` (`env_layers/information.py`):
  `audience="all"` → everyone's macro_information; a selector dict → matching agents' local_information.
- **Large-scale agent interaction** — `MessageBus` + `interaction_rounds` (mediated, not O(N²));
  posts land on the bus, neighbours read via `InteractionStructure`. See `engine/messaging.py`,
  `env_layers/neighbor_feed.py`.
- **User data / MCP / tools** — `ResourceManifest`; `FilePopulationProvider` / `McpPopulationProvider`
  (`socioverse/providers.py`); bring-your-own data dir for an env provider.

## Dev conventions & gotchas

- **Never edit** the legacy Chicago `src/`, `config/`, `processed_data/`, `run_prototype.py` (vendored in
  SocioVerse-ABM under `tasks/organization/chicago_segregation/legacy/`) — wrap via the seam.
- **Step-counter coupling** (Chicago): the legacy cascade reads `len(metrics_history)` and `__init__`
  pre-seeds step 0 — the collector appends for t≥1 and returns step-0 at t=0, or the cascade desyncs.
- **`engine-seam` carries no abc** and is not called by Core; it's shared internal glue.
- **Pin `mesa==3.3.1`** for Chicago-derived studies; Core has no Mesa dependency.
- **Parity uses `DeterministicLLMClient`** (temp 0.7 → live runs non-reproducible); reserve real LLM for demos.
- **One study per process** (monkey-patch globals aren't parallel-safe).
- **Secrets** via env/`.env` (gitignored) — never hard-code; rotate the old key still embedded in
  legacy `run_prototype.py` before any public push.

## Where to read in the code
`socioverse/abc/*` (interfaces) → `socioverse/engine/loop.py` (the loop) → `socioverse/schemas/*`
(contracts) → `studies/chicago_schelling/adapter/*` (the worked example).
