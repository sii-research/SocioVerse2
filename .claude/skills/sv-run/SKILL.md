---
name: sv-run
description: Execute the longitudinal simulation run for a SocioVerse2 study — bind P + E + decision model + schedule, run the E_t→B_t→E_{t+1} loop, and persist the panel + metrics to DuckDB. Use after the environment and population bundles exist.
---

# sv-run — the longitudinal simulation run

Bind the study's bundles into a `SimulationConfig`, wire the providers + decision model, and run the `LongitudinalSimulator`. The loop tracks the same persistent population over `n_steps`, firing scheduled events / broadcasts each step and recording one panel row per agent per step into a DuckDB store.

## Strict contract
- **Read** `study.yaml` (StudySpec), `environment/environment.json` (EnvironmentBundle), `population/population.json` (PopulationBundle) — each via `validate_handoff`.
- **Write** `simulation/simulation.json` (SimulationConfig), `trajectory/study.duckdb`, and `trajectory/metrics_history.json` (MetricsHistory).
- Assert `MetricsHistory.covers(study.metrics) == []` (the run must emit every metric the study declared).
- **Availability gate — check before binding.** Look the study up in the catalog:
  ```python
  from skills.sv_workspace import catalog_view
  row = next(c for c in catalog_view("studies") if c["study_id"] == "<study_id>")
  ```
  If `row["available"]` is false, do NOT run: tell the user the study needs `row["missing"]` and
  give the `row["setup"]` command(s) (e.g. `git clone https://github.com/Lishi905/SocioVerse-ABM
  ../SocioVerse-ABM`, then `pip install -e ".[abm]"` for the abm_* studies or `".[chicago]"` for
  chicago_schelling). If `row["rerunnable"]` is false, the study is an imported reference (a
  published trajectory, not a run of this loop): don't re-run it — offer to show it, or to start a
  new study that uses it as a template.
- **Capabilities are already materialized — the loop never fetches.** Cross-check `resources.json` before binding: every pinned `McpServerDecl` must have its build-time product in place (a materialized artifact + grounding provenance — e.g. `environment/external_events.json`, or a pool-sourced roster). A pin with no materialized product means a build stage skipped its capability check — route back to that stage; never fetch from here.

## Execution model
- **Run it in the FOREGROUND — NEVER `run_in_background`.** A real-LLM run takes minutes; execute the
  Bash cell with an explicit generous timeout (**`timeout: 600000`** — the 10-min max) and let it
  **BLOCK to completion**, then continue straight into the trajectory summary (and, when the flow
  asked, `/sv-report` or a v-vs-v comparison). The run dashboard streams per-step progress while it
  blocks, so waiting is not "blind". **Do NOT background the run** (`run_in_background`, `&`, `nohup`):
  in a **headless** (non-interactive) session nothing re-invokes you when a background task finishes, so a
  backgrounded run silently STALLS the whole automated flow — you would say "wait for it to finish, then I'll compare"
  and then never wake, and you must not read its output early and hallucinate completion. If a run is
  genuinely expected to exceed ~10 min (very large scale / many steps), say so BEFORE running and
  either cut the scale or tell the user plainly that the run will PAUSE the flow and they should send
  a message when they want you to fetch the results — never promise an automatic follow-up you cannot
  deliver.
- `interaction_rounds = 1` for move-based models (Schelling). For agent-to-agent message exchange (hybrid opinion dynamics, scenario 2) set `interaction_rounds = K`; the env's MessageBus carries posts between rounds.
- Large scale: the decision model batches LLM calls internally (per cohort), not per agent.
- **Branch replay (honored automatically).** When the live version is a **branch** (`kind == "branch"` in
  `versions.json` — written by `/sv-iterate` when the user only added interventions at `at_step >= fork_step`),
  `resolve_warm_start` first runs `check_branch_invariant`, which checks that this version differs from its
  parent in E **at/after the fork step only** (population, the study's own code, seed and the other run
  settings unchanged — only `n_steps` may grow; layers may be ADDED but not rewritten or deleted).
  - **Invariant holds** → the replay spec is bound to `simulation.json` and the engine **replays** the
    parent's stored actions for steps `0..fork_step-1` (no LLM — reproduces the parent exactly and
    rehydrates state), then runs only `fork_step..n_steps` with real decisions. Only the new steps cost
    budget.
  - **Invariant violated** → that version has **already been downgraded to a plain version** (`kind` →
    `"version"`, `warm_start` cleared, `downgraded_from_branch` kept for audit), `resolve_warm_start`
    returns `None`, and the study **cold-runs from step 0**. This is not an error, but you MUST relay the
    downgrade and its reason (the recorded `violations`) to the user before spending — the cost is now the
    full horizon.
  - **Eligibility** is unchanged: from-scratch / Path-B studies with `interaction_rounds == 1`. Chicago
    (legacy-wrap) and multi-round studies cannot replay (the engine raises if misused), so they always
    cold-run as versions.

### Chicago
```python
from socioverse.validation import validate_handoff, write_artifact
from socioverse.schemas import StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig
from skills.sv_workspace import study_paths
from studies.chicago_schelling.adapter import build_chicago_simulator
from studies.chicago_schelling.adapter.engine_seam import default_llm_config

p = study_paths("studies/chicago_schelling")
study = validate_handoff(p["study"], StudySpec)
env_bundle = validate_handoff(p["environment"], EnvironmentBundle)
pop_bundle = validate_handoff(p["population"], PopulationBundle)

sim_cfg = SimulationConfig(study_id=study.study_id, n_steps=study.n_steps, seed=study.seed,
                           decision_ref="chicago.schelling", interaction_rounds=1)
write_artifact(p["simulation"], sim_cfg)

sim, engine = build_chicago_simulator(
    env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_cfg,
    store_path=p["duckdb"], scale=env_bundle.provider_args.get("scale", "small"),
    init_mode=env_bundle.provider_args.get("init_mode", "census"), seed=study.seed,
    model_kwargs={"max_archetypes": 241}, llm_config=default_llm_config())
hist = sim.run()
write_artifact(p["metrics"], hist)
assert hist.covers(study.metrics) == [], f"missing metrics: {hist.covers(study.metrics)}"
```

- **Cost note**: small scale ≈ 1–2 min/step (real LLM). For a no-cost plumbing check, pass a `DeterministicLLMClient` as `llm_client=`.

### Generic (from-scratch / Path B — registry-assembled, no per-study builder)
A `sv-build-model` study runs through the **generic Core assembler** `socioverse.engine.build_simulator`, which resolves the `*_ref`s from the registry — no `build_<study>_simulator` to write. Set `decision_ref` **and** `collector_ref` in the `SimulationConfig`. Importing the study package runs its `@register` decorators.
```python
import studies.opinion_diffusion          # side effect: registers opinion.* refs
from socioverse.engine import build_simulator
from socioverse.validation import validate_handoff, write_artifact
from socioverse.schemas import StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig, WarmStartSpec
from skills.sv_workspace import study_paths, resolve_warm_start

p = study_paths("studies/opinion_diffusion")
study   = validate_handoff(p["study"], StudySpec)
env_b   = validate_handoff(p["environment"], EnvironmentBundle)
pop_b   = validate_handoff(p["population"], PopulationBundle)
sim_cfg = validate_handoff(p["simulation"], SimulationConfig)   # has decision_ref + collector_ref

# branch replay: if this version is a branch, resolve_warm_start validates the E-only invariant
# and returns the replay spec (engine replays the parent's steps 0..fork_step-1 with no LLM, then
# runs only fork_step..n_steps). None → this is a version (or a downgraded branch) → cold run.
ws = resolve_warm_start("studies/opinion_diffusion")
sim_cfg.warm_start = WarmStartSpec(**ws) if ws else None
write_artifact(p["simulation"], sim_cfg)

sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_cfg, store_path=p["duckdb"])
hist = sim.run()
write_artifact(p["metrics"], hist)
assert hist.covers(study.metrics) == [], f"missing metrics: {hist.covers(study.metrics)}"
```

## Switching the simulation model (user asks for a different LLM)
1. **Connectivity-test FIRST, report the result.** Before promising anything, probe the requested
   model with a 1-token chat completion through the configured base URL (`SV_LLM_BASE_URL`,
   default the official OpenAI API):
   ```bash
   source .env 2>/dev/null; curl -sS -m 30 "${SV_LLM_BASE_URL:-https://api.openai.com/v1}/chat/completions" \
     -H "Content-Type: application/json" -H "Authorization: Bearer $SV_LLM_API_KEY" \
     -d '{"model":"<requested-model>","max_tokens":4,"messages":[{"role":"user","content":"hi"}]}'
   ```
   A 200 with a completion → supported: tell the user it works (mention observed latency). An
   error → relay the provider's message honestly (unsupported model / no access / etc.) and stay
   on the current model.
2. **Re-estimate cost for THAT model** before running — different models price differently; if
   the user set a budget (or the provider reports a spend limit) and the estimate exceeds it, say
   so and do not start.
3. Persist the choice in `simulation.json` (decision_args' llm/model field per the study's decision
   layer) — a provider/model switch on an already-run study is NEW-VERSION-ONLY (see /sv-iterate).

## Resuming an interrupted run (resume from a checkpoint)
A run that dies mid-way — **LLM budget exhausted (the provider starts returning quota errors
such as `insufficient_quota`), a crash, or a stop** — has NOT wasted the finished steps: every completed
step's per-agent actions are already on disk in `trajectory/panel_live.jsonl`. To resume instead
of re-running from step 0:
1. Find the last COMPLETE step `K`: the largest step in `panel_live.jsonl` whose row count equals
   the agent count (a partially-written step doesn't count).
2. Set the replay spec in `simulation.json` and re-run — the engine replays steps `1..K` from the jsonl
   (no LLM, free) and spends budget only on `K+1..n_steps`:
   ```python
   sim_cfg.warm_start = WarmStartSpec(source_version="interrupted",
       source_trajectory="studies/<id>/trajectory/panel_live.jsonl", resume_from=K)
   ```
   (`_load_parent_panel` accepts a `panel_live.jsonl` path exactly for this case.)
3. Same limits as any replay: from-scratch / Path-B with `interaction_rounds == 1`; multi-round
   studies must re-run from step 0 — say so honestly before spending.
4. If the interruption was budget exhaustion, confirm the provider budget has room again BEFORE
   resuming.

## Pause & confirm — the spend gate (default: confirm before running)
This stage **spends LLM budget and writes the trajectory store**, so confirming before the run is the default — even inside a "run the whole pipeline" flow, this is the natural place to check in.
1. **By default, confirm before running.** Write `simulation.json`, then show the bound `SimulationConfig` (n_steps, decision_ref, scale, real LLM vs no-token mode) and the rough cost (≈1–2 min/step at small scale on a real LLM). Don't call `sim.run()` until the user says go; silence is not confirmation. Offer a free dry-run: `llm_kind: "scripted"` in `decision_args` for from-scratch studies, `DeterministicLLMClient` for chicago.
2. **Honor a standing authorization.** If the user already told you to run through the simulation (e.g. "do the whole pipeline including the run"), you may proceed without re-asking — but still echo the config + expected cost first so the spend is visible.
3. **Be rollback-ready before spending.** If the user asks for changes — to `n_steps`, the LLM choice, or any earlier artifact — apply them and re-confirm the config; never run on a stale plan.
4. **While running:** stream per-step metrics. **After running:** summarize the trajectory (did the metrics move?), post the run narrative (last section) and stop; don't auto-invoke `/sv-report` unless the user's flow asked for it.
5. **After the run, changes go through `/sv-iterate` — never ad-hoc.** If the user's next request modifies this study (a new policy/broadcast, more steps, different parameters), invoke `/sv-iterate` (version gate + re-entry at the affected stage); do NOT edit artifacts and re-run from here. When an iteration extended the horizon or added a mid-trajectory intervention, restate the run cost before spending:
   - **branch (Path-B, `interaction_rounds==1`):** steps `0..fork_step-1` are **inherited from v<parent>** — replayed from its stored actions, reproduced exactly, **no LLM and not billed** — and only `fork_step..n_steps` spend budget;
   - **version (chicago, multi-round, a downgraded branch, or any global change such as seed / population / decision logic):** the **full horizon cold-runs from step 0**; under a real LLM the earlier steps won't exactly reproduce the parent (same seed included) and their cost is paid again.

## Hand-off
`sv-report` reads `trajectory/study.duckdb` + `metrics_history.json`.

## Dashboard narrative (required after every completed run, non-blocking — L2)
After **every** run that completes (a first run, a re-run, a branch or a resumed run), post a
1–2 sentence plain-language summary of *what happened and why* (did the metrics move?) plus the
run shape (LLM or scripted, steps run vs replayed, `decision_source` counts when there were
fallbacks). It is written to `studies/<id>/narrative/sv-run.json`, the record of this version's run
that the dashboard shows on this stage's card + event feed (files already carry the state; this is
the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-run \
  --text "Ran 6 steps on the real LLM; mean_belief climbed to 0.41 then bent down after the step-3 broadcast."
```
Exits 0 / prints nothing, so it never blocks. Do not skip it in a headless or offline run: prefix
the command with `SV_DASH_DISABLE=1` there, which writes the narrative file without starting or
contacting the dashboard.
