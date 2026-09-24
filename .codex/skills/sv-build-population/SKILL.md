---
name: sv-build-population
description: Build the fixed population pool P for a SocioVerse2 study — personas with persistent ids, interaction structure, and propagation mode. Use after sv-build-environment, before sv-run. Supports census, MCP population pools (single or composed across several), and user-uploaded sources.
---

# sv-build-population — construct P (the tracked population)

Produce a validated `PopulationBundle` **and actually instantiate the agents**. P is **fixed with persistent `agent_id`s** — the same households are tracked across every step (this is what makes the study longitudinal). Besides personas, declare the **interaction structure** (who is adjacent / networked) and the **propagation mode** (how influence flows).

**This stage MATERIALIZES the pool — it is not a declaration-only pass.** After choosing the provider you run it (the same `population.build(seed)` + `env.reset(seed)` the run does at t=0), so the artifact carries the real personas and the dashboard shows every initialized agent + its initial state **before** `/sv-run` spends a token. (Previously personas were left empty and only materialized at run start — that made this stage a no-op.)

## Strict contract
- **Read** `study.yaml` (`StudySpec`) **and** `environment/environment.json` (`EnvironmentBundle`) via `validate_handoff` — materializing each agent's initial state needs E_0.
- **Write** `population/population.json` (`PopulationBundle`) **and** `population/roster.jsonl` (the materialized t=0 roster, via `write_roster`).
- **Materialize, then record it:** set `materialized_count`, and embed the materialized `personas` into `population.json` when the pool is modest (≤ ~1000; above that leave `personas=[]` — the full roster lives in `roster.jsonl` + the count).
- The validator enforces the persistent-id invariant (unique `agent_id`). Materialization is deterministic in `seed`, so it reproduces exactly what `/sv-run` builds at t=0.
- **Agent naming — simple by default.** Unless the user asked for named personas or the study
  clearly needs them, id agents as `agent-001`-style sequential ids or a SINGLE-word name — never
  long generated names, and never overload the id with attributes (attributes live in state).
  A short domain prefix (`pm-`, `stu-`) is fine when it aids reading.
- **Declare the study's key attributes.** Pick the **1-3 per-agent state attributes most tied to
  the research question** (the ones a reader would scan the roster by — e.g. `stance` for an
  opinion study, `monthly_spend` for a consumption study) and write them to `study.yaml`'s
  `key_attributes`. The dashboard's agent list shows them beside each agent id; without them the
  list falls back to arbitrary dims.
- **Panel state = FLAT SCALARS.** Every attribute in an agent's state (roster + `agent_state()`)
  must be a flat scalar (str/number/bool) — no nested dicts/lists (`reports: {...}` renders as
  noise and can't be charted). Split a composite into `report_new_orders`, `report_production`, …
  scalar keys instead.

## Capability check (external services — stable hook)
List the registry entries anchored to this stage; the registry — not this skill — carries the
per-service details, so adding/removing a service never edits this text:
```python
from skills.sv_workspace import capability_view
for c in capability_view(stage="sv-build-population"):   # resources/capabilities.yaml
    print(c["name"], "| available:", c["available"], f"({c['availability_note']})",
          "\n   use_when:", c["use_when"])
```
For each entry whose `use_when` matches this study — or that `sv-init` already pinned in
`resources.json`: probe its `health`; honor `confirm: true` (ask before a call that spends
budget or sends data out; free/read-only entries are just reported at this stage's gate);
fetch at **build time only**; materialize the result into this stage's artifacts (personas +
roster, like every other provider); record provenance in `grounding/grounding.json`; and make
sure the service is pinned by NAME in `resources.json` (`McpServerDecl` — endpoints stay in
`.mcp.json`/`.env`). Unavailable → follow the entry's `fallback` and record that instead.
Per-service how-to lives in each entry's `howto`, not here — this skill stays service-agnostic.

## Choosing the provider (scenario 3a)
- `provider_ref="chicago.census"` — build from Census archetype×tract mapping (the Chicago default).
- `provider_ref="mcp.socioverse_pool"` + `provider_args={"server": <name from ResourceManifest>, "query": ...}` — retrieve personas from a SocioVerse 1.0 population-pool MCP. Persistent ids come from the pool.
- `provider_ref="file.personas"` + `provider_args={"path": <uploaded csv/parquet>}` — user-uploaded personas.

## Composing P from multiple sources (routing + fusion)

A study often needs persona fields that **no single pool carries** (e.g. demographics from a
pool, plus a study-specific `dining_budget`). Don't reject the pools or fully synthesize —
**compose**: one pool anchors each persona, the other sources fill in fields. Skip this
section when a single provider covers every field the model consumes.

1. **Route first.** If a population-pool service is attached (capability check above), use its
   field-coverage/routing tool (see the registry entry's `howto`) with the model's required
   fields: it reports which pool covers what, suggests an **anchor pool**, lists **complement
   pools** per uncovered field, and flags fields no pool has. Probe the exact category labels
   too — label vocabularies differ across pools, and sampling matches strings exactly.
2. **Fill each field by priority**, recording the choice per field in a composition plan:
   - **anchor pool** — sample base personas (identity, demographics, behavioral text) to the
     study's target distributions; prefer a joint-preserving sampling mode when cross-field
     correlations matter, and never let silent virtual/synthetic stand-ins pass as real users.
   - **complement pool (statistical matching)** — for a field only another pool has: query
     that pool filtered on the fields it SHARES with the anchor persona (e.g. AGE×GENDER) and
     copy the field value from a matching real user. This preserves the field's conditional
     distribution given the shared keys — an approximation, so record `method:
     statistical_matching` + the keys matched on.
   - **user-uploaded dimensions** — an uploaded cross-tab becomes extra `distributions`
     constraints for the anchor sampling; uploaded record-level profiles join by explicit key
     (or stand alone as `file.personas`).
   - **conditioned synthesis** — fields still unresolved (the study-specific ones) are
     generated per persona **conditioned on the anchor's real attributes/text**, or set by a
     user-stated rule from the conversation. Grounding-first rules apply exactly as in the
     synthesis section below — a searched anchor or a declared assumption per distribution.
3. **Record the fusion.** Put the composition plan in
   `provider_args["composition"]` — per field: `{source, method, matched_on?}` — plus an
   `attributions` list; copy any `attribution` blocks returned by pool services into
   `grounding/grounding.json` (open-data pools MUST be credited — project/author/license/url;
   `sv-report` surfaces them in the report's data sources / acknowledgements). Achieved-vs-target sampling
   marginals are grounding facts too.
4. **No pool service available?** The plan degrades gracefully: uploads + grounded synthesis
   only (the registry entry's `fallback`), with the same per-field provenance.

```python
from socioverse.validation import validate_handoff, write_artifact
from socioverse.schemas import StudySpec, EnvironmentBundle
from skills.sv_workspace import study_paths, write_roster
from studies.chicago_schelling.adapter import make_chicago_bundles, materialize_chicago_initial, DeterministicLLMClient

paths = study_paths("studies/chicago_schelling")
study  = validate_handoff(paths["study"], StudySpec)
env_b  = validate_handoff(paths["environment"], EnvironmentBundle)
_, _, pop_bundle = make_chicago_bundles(scale="small")   # provider_ref="chicago.census", spatial adjacency

# INSTANTIATE the agents (shared ChicagoEngine; no token spend — model build doesn't call the LLM)
personas, rows, _ = materialize_chicago_initial(
    env_bundle=env_b, pop_bundle=pop_bundle, seed=study.seed,
    scale=env_b.provider_args.get("scale", "small"),
    init_mode=env_b.provider_args.get("init_mode", "census"),
    llm_client=DeterministicLLMClient())

pop_bundle.materialized_count = len(personas)
if len(personas) <= 1000:
    pop_bundle.personas = personas         # embed the roster into the artifact when modest
write_artifact(paths["population"], pop_bundle)
write_roster(paths["roster"], rows)        # population/roster.jsonl — the dashboard reads this
```

For a non-Chicago study, set `interaction` (`spatial_adjacency` / `explicit_network` / `none`) and `propagation` (`independent` for Schelling; `contagion` / `broadcast_then_local` for opinion/diffusion models).

### Generic example (from-scratch / Path B — no Chicago)
For a `sv-build-model`-authored study, the `provider_ref` is the study's own registered `PopulationProvider`; the generic `socioverse.engine.materialize_initial` resolves the env + pop providers from the registry (no `SimulationConfig` needed) and instantiates t=0. Import the study package first so its `@register` decorators ran:
```python
import studies.opinion_diffusion                 # side effect: registers opinion.* refs
from socioverse.validation import validate_handoff, write_artifact
from socioverse.schemas import StudySpec, EnvironmentBundle
from socioverse.engine import materialize_initial
from skills.sv_workspace import study_paths, write_roster
from studies.opinion_diffusion.model import make_opinion_bundles

p = study_paths("studies/opinion_diffusion")
study = validate_handoff(p["study"], StudySpec)
env_b = validate_handoff(p["environment"], EnvironmentBundle)
_, _, pop_bundle, _ = make_opinion_bundles(n_agents=12)   # provider_ref="opinion.pop", ring network

personas, rows = materialize_initial(env_b, pop_bundle, seed=study.seed)   # INSTANTIATE the agents
pop_bundle.materialized_count = len(personas)
if len(personas) <= 1000:
    pop_bundle.personas = personas
write_artifact(p["population"], pop_bundle)
write_roster(p["roster"], rows)
```

## Grounding — distributions before synthesis

P's shape is a claim about the world; ground it in `grounding/grounding.json`
(helper `skills/sv_grounding.py`) before synthesizing:
- **census / MCP-pool / file providers**: the pool IS the source — merge one fact per
  load-bearing distribution it fixes (`via="provider"`, `source.title` = the
  provider_ref + query/path). No search needed; real data gets accounted for too.
- **synthesized personas (typical Path B)**: every load-bearing distribution (archetype
  shares, income/budget ranges, ownership splits) needs EITHER a searched anchor —
  quick WebSearch first (≤3 targeted queries), `via="web_search"`, url + accessed;
  `basis="proxy"` when e.g. a city-level number stands in for district-level (say so
  in `note`) — OR an `assumptions` entry with a rationale. "22 kid-buyers / 8 investors"
  with no recorded basis is not acceptable output.
- A real distribution table (census age×income extract etc., MB-scale) may be downloaded
  to `grounding/data/` — the fact records url + accessed + `source.local_path`, and the
  provider consumes it via `provider_args` (e.g. `{"table": "grounding/data/….csv"}`).
  Heavy ETL / large datasets stay out (external distribution instead).
- Cosmetic flavor fields (names, quote text) need nothing — but declare them stylized
  in a `note` when they could read as real.
Append `sv_grounding.summary("studies/<id>")` to this stage's narrative.

## Re-entry (iteration mode — arriving from /sv-iterate)
A post-run change routed here means the version gate already ran (new version / in-place / branch):
- **P is affected** → author + re-**materialize** + `write_artifact` + `write_roster` as above,
  overwriting the live `population.json` **and** `roster.jsonl` (when the user chose a new version,
  the previous one is safe in its `versions/vN/` snapshot), and refresh the grounding entries
  the change touches (`sv_grounding.merge` by id — leave the untouched entries alone).
- **P is NOT affected** (the common case — the population pool stays fixed across iterations) →
  `validate_handoff(path, PopulationBundle)` only, report "population.json unchanged, validation passed,
  rebuild skipped" (+ narrative), and do **not** rewrite `population.json` **or** `roster.jsonl` — an
  identical rewrite bumps their mtime and corrupts the dashboard's carried/stale detection.
Then hand back to the iteration flow (next affected stage, or `/sv-run`'s spend gate).

## Pause & confirm (default: stop between stages)
Pausing here is the **default**, and it yields to an explicit user instruction about the flow.
1. **By default, stop and wait.** After writing `population.json`, don't invoke `/sv-run` (or any later skill) on your own. Advance only on an explicit go-ahead; silence or an ambiguous reply is not confirmation.
2. **Follow the user's flow when they've set one.** If the user said how far to run or where to pause (e.g. "build everything, prompt me before the run", "do the whole pipeline"), honor it — chain the stages to the point they named instead of stopping here.
3. **Either way, surface the intermediate product:** the provider + **materialized** agent count + interaction/propagation in one line, plus the artifact paths (`population.json` + `roster.jsonl`), and note the dashboard now shows the initialized roster.
4. **Be rollback-ready.** If the user asks for changes — including ones that revise an earlier step's decision — revise `population.json` in place, re-summarize, and stop again. Treat a change request as "redo this step", never "skip ahead".

## Hand-off
`sv-run` reads this `population.json` via `validate_handoff(path, PopulationBundle)`.

## Dashboard narrative (optional, non-blocking — L2)
If the local run dashboard is up, after writing the artifact post a 1–2 sentence
plain-language summary of *what you decided and why*. It shows on this stage's card
+ event feed (files already carry the state; this is the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-build-population \
  --text "Materialized 570 census households (roster viewable now), spatial adjacency, independent propagation."
```
Exits 0 / prints nothing, so it never blocks; skip in headless or offline runs.
