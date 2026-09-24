---
name: sv-build-model
description: Implement a NEW from-scratch SocioVerse2 study's functional code on the Core kernel — the four abc implementations (EnvironmentProvider, PopulationProvider, DecisionModel, MetricCollector) written natively, no legacy wrap, no engine-seam. Use only on Path B (sv-init found no matching existing study). Skip for Path A (reuse) and for collaborators wrapping a legacy simulator (that is the CLAUDE-dev.md adapter path).
---

# sv-build-model — write the from-scratch study code (Path B)

`sv-init` chose **Path B**: the query matches no already-adapted study, so there is nothing to reuse and no legacy simulator to wrap. You implement the study's dynamics directly on Core with **high freedom** — concrete Python for the four abc — then the normal `sv-build-environment → sv-build-population → sv-run → sv-report` skills author the artifacts and run it.

> This is NOT the collaborator/adapter path. If the user has an existing simulator to wrap (seam + reuse its validated dynamics), that is `CLAUDE-dev.md` (Path C), not this skill.

## Set expectations first (long stage)
Building the model is the slowest authoring stage (typically 3–8 minutes of code +
self-tests). BEFORE starting the heavy work, tell the user in one line: roughly how
long this will take, that they can ask “how is it going?” in the chat at any time, and that
refreshing the page is safe — the build continues in the background either way.

## Strict contract
- **Write** `studies/<study_id>/model.py` implementing + registering the four abc.
- Each provider MUST follow the **generic-wiring convention** so `socioverse.engine.build_simulator` can assemble it from the registry with zero glue:
  - `EnvironmentProvider` / `PopulationProvider` → `__init__(self, bundle)` (sole arg is its bundle).
  - `DecisionModel` → `__init__(self, **decision_args)`; `MetricCollector` → `__init__(self, **collector_args)`.
- Register each class: `@register("environment"|"population"|"decision"|"collector", "<id>.<name>")`.
- Have `studies/<study_id>/__init__.py` do `from . import model` so importing the package registers everything.

## Capability check (external services — stable hook)
```python
from skills.sv_workspace import capability_view
for c in capability_view(stage="sv-build-model"):   # resources/capabilities.yaml
    print(c["name"], "| available:", c["available"], "| use_when:", c["use_when"])
```
An empty list means proceed. For a matching entry: probe `health`, honor `confirm: true`
(ask before spending/sending), fetch at build time only, record provenance in
`grounding/grounding.json`, pin by NAME in `resources.json`; unavailable → its `fallback`.
The per-service how-to lives in the registry entry, not here.

## Steps
1. **Model the loop in your head** (`E_t → B_t → E_{t+1}`): what is the per-agent state, what does each step change, which of the 4 quadrants (macro/local × physical/information) the agent sees, and what metric tells the longitudinal story.
   **Anchor a step to real time.** Decide what ONE step *means* for THIS research question — a day, a week, a month, a quarter, a year — and set `StudySpec.time_unit` (`"day"|"week"|"month"|"quarter"|"year"`) accordingly, plus a one-line `step_meaning` tying it to the question (e.g. `"each step = one monthly consumption-decision cycle"`). Pick the scale the real behavior actually unfolds on (a school-canteen choice is monthly; an election-opinion shift is weekly; a housing move is yearly) and make the per-step magnitudes (price drift, decay, budget) consistent with that unit. **Only when no calendar mapping is meaningful** (the step is a pure abstract decision round) leave `time_unit="abstract"` and say so in `step_meaning`. Don't silently default to abstract — justify the choice.
2. **PopulationProvider** — `build(seed) -> Persona[]` with **deterministic persistent ids** (e.g. `f"<id>-{i:03d}"`); set `group_key` (batching cohort) and `init_state`. Override `neighbors()` if there is a local network. Keep initial state in **pure seed functions** shared with the env (no shared mutable object), so generic `cls(bundle)` wiring holds.
3. **EnvironmentProvider** — owns the mutable world state. `reset(seed)` builds `E_0`; `advance_to(t)` fires `ScheduledEvent`s + activates `Broadcast`s (exogenous); `apply(actions)` folds behavior back (endogenous); `observe_batch(ids, t, r)` assembles each agent's 4-quadrant `Observation`; `agent_state(id)` returns the per-agent panel row.
4. **DecisionModel.decide_batch(obs, memories) -> Action[]** — compute B for **all agents of the step** and return one `Action` per agent.
   **Always implement BOTH decision modes behind `decision_args["llm_kind"]`** — copy the `_load_dotenv` / `_OpenAILLM` / `_make_llm` trio from a `from-scratch-core` template:
   - `"scripted"` (the default) — a deterministic rule: free, reproducible, and what every smoke test and dry run uses.
   - `"openai"` — a real LLM over the OpenAI-compatible SV_LLM channel: call `socioverse.external_events._load_dotenv()` first (it reads `.env` without overriding the process env), then read `SV_LLM_API_KEY` (fallback `OPENAI_API_KEY`), `SV_LLM_BASE_URL` (default: the official OpenAI API) and the model from `decision_args["model"]` or `SV_LLM_MODEL`. Import `openai` lazily, so the scripted mode runs without the `llm` extra.
   **Never** ship a model that raises for `"openai"`, stubs it, or leaves it as a TODO: `/sv-run` offers the real-LLM run, and a scripted-only model fails right there.
   **The LLM call shape — one concurrent fan-out of per-agent calls per step.** This is what the shipped templates do (`BoundedConfidenceDecision.decide_batch` in `studies/opinion_diffusion/model.py`, `DiningDecision.decide_batch` in `studies/campus_dining_choice/model.py`); copy it:
   - build one short prompt per agent from its `Observation` and send the whole step's prompts at once through a `concurrent.futures.ThreadPoolExecutor` with a bounded worker count (`max_workers` in `decision_args`, default 8, capped at the number of agents). A call that raises becomes an empty reply, never a crashed step.
   - parse each reply on its own. A reply that does not parse falls back to the scripted rule **for that agent only** (campus_dining_choice instead keeps the agent's previous choice), and the raw reply (truncated) is logged, e.g. `logging.warning`, so a prompt the model keeps misreading is visible.
   - tag every action's `source` per agent: `"llm"` for a parsed reply, `"fallback"` for a rule fallback, `"rule"` in scripted mode. To see it in the panel as well, copy `act.source` into the agent's state as `decision_source` in `apply()` and return it from `agent_state(id)`.
   - acceptable alternative for small cohorts: one call per cohort of **at most 10 agents**, whose reply is a JSON object keyed by `agent_id`, parsed and fallen back per agent exactly as above.
   - **never** ask for one JSON array covering the whole population in a single call: long structured replies get truncated or miscounted, and one bad reply then fails the whole step.
   **When the decision is LLM-driven, require a one-sentence reason in the simulated person's own voice.** The decision prompt must make the model emit, alongside the action, a first-person `reason` — how *this persona* would explain the choice to a peer, in their register and language (not an analyst's summary). Persist it: put it in `payload["reason"]` **and** `Action.rationale=[reason]`, and include `reason` in `agent_state(id)` so it rides into `roster.jsonl`/`panel` (the dashboard's agent panel surfaces it per step). Cap it to one sentence. Precedent: `studies/campus_dining_choice/model.py` (`build_student_prompt` forces `{"choice", "satisfaction", "reason"}`; the reason is what the student would tell a roommate). For a rule/deterministic decision, a short templated rationale is fine — the field should never be empty for an LLM run.
   **The voice test — it must sound like the person TALKING, not a report.** Telegraphic
   analyst-style output fails the contract. Write the style requirement INTO the prompt, e.g.
   "the reason is one offhand sentence you would say to a peer: conversational, with a subject and some feeling, not report-speak or telegraphese".
   - ✗ bad: `"4 improved / 1 weakened, hiring leaning cautious"` (a metrics telegram; nobody talks like this)
   - ✓ good: `"Orders are up a bit, but I don't dare hire yet. Let's see how next quarter goes."` (first person, conversational, weighs a trade-off)
   If dry-run samples read like the bad example, tighten the prompt (add the good/bad pair as
   few-shot) before the real run.
5. **MetricCollector.collect(env, actions, t) -> dict** + `columns()` — the per-step aggregate metrics (must cover `study.metrics`). While you're here, make sure `study.yaml`'s **`metric_descriptions`** has a one-line meaning for every metric the collector emits (what it measures + unit/direction) — you just defined their semantics, and the dashboard renders these on the model/run cards + timeline tooltips.
6. **Add a `make_<id>_bundles()` factory** that returns the `(StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig)` — the next skills write these to disk. Set `SimulationConfig.collector_ref` and the discovery fields on `StudySpec` (`legacy_simulator="from_scratch"`, `provider_refs`, `adjustable_params`, …) so the study joins the catalog.

## Grounding — mechanism & constants

- Before designing the dynamics, read `grounding/grounding.json`
  (`from skills import sv_grounding; g = sv_grounding.load("studies/<id>")`) —
  `implementation_refs` records how similar phenomena are modeled; follow a precedent or
  diverge deliberately, and say which in model.py's header docstring.
- Every constant that claims a real-world magnitude (base prices, rates, elasticities,
  archetype counts) either cites a fact id in a trailing comment —
  `"base": 8.8,  # grounding: f-base-price` — or gets declared:
  `sv_grounding.merge("studies/<id>", assumptions=[{"id": "a-…", "claim": "…", "rationale": "…"}])`.
  Silent invention of a load-bearing number is not acceptable output.
- Missing load-bearing value → ≤3 targeted WebSearches for this stage → merge the fact
  (`via="web_search"`, url + accessed date); still nothing → an assumption, honestly.
- Purely stylized dynamics: `sv_grounding.merge("studies/<id>", method_notes="stylized")`
  once — plain constants then need no fact ids.

Append `sv_grounding.summary("studies/<id>")` to this stage's narrative.

## Reference templates — study the WHOLE reference set, then copy the closest code skeleton
The catalog's `reference: true` studies are the design precedents. **Read across ALL of them** for
mechanism ideas before you write `model.py` — do not default to one template. There are three kinds,
and each teaches something (`teaches` line says what):
```python
from skills.sv_workspace import catalog_view
refs = [c for c in catalog_view("studies") if c["reference"]]     # the full precedent set
# group by what they exemplify (c["demonstrates"] / c["teaches"]):
#   from-scratch-core  — the copyable CODE skeleton (opinion_diffusion=info-broadcast+branch-replay,
#                        hisim_roe=intra-step multi-round messaging, campus_dining_choice=dorm
#                        discussion + LLM one-line reason + scripted↔LLM dual mode)
#   abm-benchmark-seam — 11 classic ABMs by family (organization / diffusion / market / flow),
#                        each a rule-vs-LLM mechanism precedent (Schelling homophily, SIR contagion,
#                        HK bounded-confidence, Sugarscape foraging, Boids flocking, NaSch traffic …)
#   legacy-seam        — chicago (geo-spatial + policy intervention), consumer_confidence
#                        (cross-sectional survey) — how a real external model plugs into
#                        B=f(P,E); the DESIGN reference for adapted domains
```
**Pick the closest precedent by domain + mechanism, from the whole set** — an ABM benchmark or a
legacy-seam study is a perfectly good model to *reason from* (its dynamics, state, metric choices).
Then **copy the code shape from a `from-scratch-core` template** (all four abc + a `make_<id>_bundles()`
factory, assembled generically by `socioverse.engine.build_simulator`) — that is the only skeleton you
paste. `abm-benchmark-seam` and `legacy-seam` studies show you WHAT to build; a `from-scratch-core`
study shows you HOW to wire it on Core. Do NOT copy an `adapter/` engine-seam into a from-scratch study.
Mirror the chosen skeleton's `model.py` (+ its test under `tests/`) for structure.

## Exit check — smoke-test both decision modes
1. **Scripted smoke (no tokens) — always.**
```python
import tempfile
from pathlib import Path
from socioverse.engine import build_simulator
from studies.<study_id>.model import make_<id>_bundles
study, env_b, pop_b, sim_c = make_<id>_bundles()
sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "scripted"}
with tempfile.TemporaryDirectory() as tmp:
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=Path(tmp) / "smoke.duckdb")
    hist = sim.run(); assert hist.covers(study.metrics) == []
```
2. **Tiny real-LLM smoke — whenever an LLM key is configured** (3 agents × 1 step, a handful of
   calls). Size the population however your factory does it (`pop_b.provider_args["n_agents"]`
   in the templates):
```python
import os, tempfile
from collections import Counter
from pathlib import Path
from socioverse.external_events import _load_dotenv
_load_dotenv()
if os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"):
    study, env_b, pop_b, sim_c = make_<id>_bundles()
    pop_b.provider_args["n_agents"] = 3
    sim_c.n_steps = 1
    sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "openai"}
    with tempfile.TemporaryDirectory() as tmp:
        sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                              store_path=Path(tmp) / "smoke_llm.duckdb")
        sources, decide = Counter(), sim.decision.decide_batch
        def counted(obs, memories):
            acts = decide(obs, memories); sources.update(a.source for a in acts); return acts
        sim.decision.decide_batch = counted
        sim.run()
    print("decision_source counts:", dict(sources))
else:
    print("no LLM key configured: llm_kind 'openai' is untested")
```
   Show the user the `decision_source` counts. Mostly `"llm"` is a pass; mostly `"fallback"`
   means the prompt or the parser is broken — read the logged raw replies and fix it before
   `/sv-run`. **With no key configured, say explicitly that `llm_kind: "openai"` is untested**
   (never imply the real-LLM path works because the scripted smoke passed).

## Re-entry (iteration mode — arriving from /sv-iterate)
A post-run change routed here means the version gate already ran (new version / in-place / branch):
- **the dynamics/code are affected** → revise `model.py` as above, re-run the exit check (both
  modes), and re-post this stage's narrative so the dashboard note describes the current design,
  not the one it replaced (when the user chose a new version, the previous code is safe in its
  `versions/vN/` snapshot — versions capture code, not just artifacts).
- **NOT affected** → confirm the registered refs still import + register cleanly, report
  "model.py unchanged, rebuild skipped", and do **not** rewrite the file (mtime churn corrupts the
  dashboard's carried/stale detection).
Then hand back to the iteration flow (next affected stage, or `/sv-run`'s spend gate).

## Pause & confirm (default: stop between stages)
Pausing here is the **default**, and it yields to an explicit user instruction about the flow.
1. **By default, stop and wait.** After writing `model.py`, don't invoke `/sv-build-environment` (or any later skill) on your own. Advance only on an explicit go-ahead; silence or an ambiguous reply is not confirmation.
2. **Follow the user's flow when they've set one.** If the user said how far to run or where to pause (e.g. "build everything, prompt me before the run", "do the whole pipeline"), honor it — chain the stages to the point they named instead of stopping here.
3. **Either way, surface the intermediate product:** the four registered refs + the decision rule in one line, plus the exit-check results: the scripted smoke, and the real-LLM smoke's `decision_source` counts or the explicit note that `llm_kind: "openai"` is untested (no key).
4. **Be rollback-ready.** If the user asks for changes — including ones that revise the framing chosen in `sv-init` — revise `model.py` (or flag that `study.yaml` needs to change first), re-summarize, re-run the exit check, and stop again. Treat a change request as "redo this step", never "skip ahead".

## Hand-off
`sv-build-environment` / `sv-build-population` / `sv-run` author `environment.json` / `population.json` / `simulation.json` referencing your `<id>.*` refs (use their **generic** examples, not the Chicago factory). `sv-run` then assembles via `socioverse.engine.build_simulator`.

## Dashboard narrative (optional, non-blocking — L2)
If the local run dashboard is up, after writing the artifact post a 1–2 sentence
plain-language summary of *what you decided and why*. It shows on this stage's card
+ event feed (files already carry the state; this is the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-build-model \
  --text "Wrote model.py — four abc on Core; decision rule = peer contagion + a step-3 fact-check damping term."
```
Exits 0 / prints nothing, so it never blocks; skip in headless or offline runs.
