---
name: sv-build-environment
description: Build the dynamic environment E for a SocioVerse2 study — the two-axis layers (physical/information × macro/local), scheduled interventions, and audience-scoped information broadcasts. Use after sv-init, before sv-build-population. This is the "information retriever / environment builder" stage.
---

# sv-build-environment — construct E (the dynamic environment)

Produce a validated `EnvironmentBundle`. E is decomposed on two axes — **modality** (`physical` vs `information`) and **scope** (`macro` vs `local`) — plus a **dynamics** tag (`static` / `endogenous` / `scheduled`). This is where you make E *dynamic*: scheduled numeric interventions and audience-scoped information broadcasts over time.

**An intervention is one entry in this bundle** — a `ScheduledEvent` (a numeric change to a declared
layer) or a `Broadcast` (information delivered to an audience). Nothing else counts as an intervention.
Each one fires in the **exogenous update** phase of its `at_step`, the first of the step's five phases
(`exogenous update → observe → decide → apply → record`), so it lands **before any agent observes** and
every agent in that step faces the same updated E.

## Strict contract
- **Read** `study.yaml` via `validate_handoff(path, StudySpec)`.
- **Write** `environment/environment.json` validated as `socioverse.schemas.EnvironmentBundle`.
- Every layer MUST carry `(modality, scope, dynamics)`. Scheduled events must target a declared layer; broadcasts require ≥1 `information` layer (the validators enforce both).

## Capability check (external services — stable hook)
List the registry entries anchored to this stage; the registry — not this skill — carries the
per-service details, so adding/removing a service never edits this text:
```python
from skills.sv_workspace import capability_view
for c in capability_view(stage="sv-build-environment"):   # resources/capabilities.yaml
    print(c["name"], "| available:", c["available"], f"({c['availability_note']})",
          "\n   use_when:", c["use_when"])
```
For each entry whose `use_when` matches this study — or that `sv-init` already pinned in
`resources.json`: probe its `health`; honor `confirm: true` (ask before a call that spends
budget or sends data out; free/read-only entries are just reported at this stage's gate);
fetch at **build time only**; materialize the result into this stage's artifact(s); record
provenance in `grounding/grounding.json`; and make sure the service is pinned by NAME in
`resources.json` (`McpServerDecl` — endpoints stay in `.mcp.json`/`.env`). Unavailable →
follow the entry's `fallback` and record that instead. Per-service how-to lives in each
entry's `howto` — `event_tool`'s points at the "External events" section below.

## Steps
1. Decide the layers across the 4 quadrants. Minimum for a physical study: a macro-physical aggregate + a local-physical neighbourhood. Add `information` layers if the study has news/social/broadcast content.
2. Encode **interventions** (one-shot policy geo-modifications, now time-scheduled):
   - numeric env change → `ScheduledEvent(at_step, target_layer, op, property_name, value, selector, note)`
   - information content → `Broadcast(content, at_step, ttl, audience)` where `audience="all"` (macro) or a selector dict (local). Scenario 1 = two broadcasts (policy A `audience="all"` + policy B `audience={...tract...}`).
3. Pick the `provider_ref` (registry key for the study's `EnvironmentProvider`) and `provider_args` (e.g. geo data path, scale). For **user-supplied data (scenario 3b)** set `provider_args["geojson"]` to the path from the ResourceManifest.

## Writing E for a branch (the environment bundle of a branch)

A **branch** is a counterfactual version that keeps the same individuals, the same behaviour function,
the same seed and the same history, and differs only in E from the fork step `t*` onward — which is why
its steps `0..t*-1` can be replayed from the parent instead of re-run. When `/sv-iterate` routes here as
a branch, the environment bundle is the only artifact you may touch, and only forward in time:
- **Allowed**: add `ScheduledEvent`s / `Broadcast`s with `at_step >= fork_step`; **add** a new
  `information` layer when a new broadcast needs a channel the parent doesn't have.
- **Not allowed**: change or delete any event/broadcast at `at_step < fork_step`, rewrite or remove a
  layer the parent already had, or touch `provider_ref` / `provider_args`.
- Everything outside E (population, the study's own `*.py`, seed, `interaction_rounds`, …) stays
  byte-identical — that is exactly what makes the parent's early steps replayable.
- **Moving an intervention** (both its old and new `at_step >= fork_step`): change only `at_step`
  and keep the original duration unless the user asked otherwise — a `Broadcast` stays visible for
  the same number of steps within the horizon (`ttl` kept, or shortened if the old window was
  clipped at `n_steps`), never stretched to reach the end. If the move still changes how long it
  acts (it now ends before the horizon, or a persisting `ScheduledEvent` fires earlier), say so in
  this stage's summary. The `/sv-iterate` classification section has the worked example.

Touch anything before the fork step and `check_branch_invariant` **downgrades this version to a plain
version** at run time: no error, but the full horizon cold-runs and the paired Δ_t against the parent is
lost. If the change genuinely belongs before `t*`, say so and let `/sv-iterate` record it as a **version**
instead.

## Grounding-first — layer baselines, provider_args, broadcast numbers

The external-events chain below covers EVENT context; this rule covers E's numbers. Any
load-bearing magnitude in `layers[*]` or `provider_args` (base prices, capacities, rates,
drifts) is grounded before invention — check `grounding/grounding.json` first
(`from skills import sv_grounding; g = sv_grounding.load("studies/<id>")`), and for
anything missing:
1. **always a quick live-search pass** (1–2 queries — also when the Event service is
   up: it covers what the structured sources don't, e.g. local-language news, policy and prices).
   The default route is the built-in **WebSearch** (+ WebFetch for the 1–2 load-bearing
   pages; `via="web_search"`). **Optional upgrade:** when the Event service is configured
   and its in-session **`search_web` MCP tool** is visible, use it for news/event/public-opinion
   queries (multilingual news search; `via="event_service"`), and switch to it instead of
   retrying when WebSearch fails (403 / "No links found"). Either way record url +
   accessed date;
2. served by the materialized external events (fred/census/monthly news) → merge a fact,
   `via="event_service"`, `source.title="<source> <month>"`;
3. nothing usable → an `assumptions` entry, or `basis="proxy"` when anchoring on a
   related quantity (say which in `note`).
Budget ≤3 targeted searches; ground only values that could change conclusions.
```python
from skills import sv_grounding
sv_grounding.merge("studies/<id>", facts=[{
    "id": "f-base-rent-d1", "claim": "Median asking rent for a one-bedroom flat in district D1", "value": 1450,
    "unit": "EUR/month", "as_of": "2026-05", "basis": "sourced",
    "source": {"title": "…", "url": "https://…", "via": "web_search", "accessed": "2026-07-06"},
    "applies_to": ["environment.provider_args.base (D1)"]}])
```
- A layer built on a grounded baseline may set its (otherwise unused) `source` field to
  `"grounding:<fact_id>"` — a machine-readable back-link, zero schema change.
- Broadcast text that quotes a real number quotes a fact in the file — never an
  unsourced figure.
- A small reference table (district price sheet, census extract; MB-scale) may be
  downloaded to `grounding/data/` with the fact recording url + accessed +
  `source.local_path` (+ `provider_args` pointing at it when a provider consumes it).
  Heavy ETL / large datasets stay out.
Append `sv_grounding.summary("studies/<id>")` to this stage's narrative.

## External events — retrieval priority & fallback

When the study's E needs real-world macro/news/market context (broadcast content, layer
baselines), retrieve it BEFORE authoring broadcasts, via `socioverse.external_events`.
The priority chain is implemented in the client — you only check the outcome:

1. **remote Event MCP** (optional service; `SV_EVENT_API_URL` = the full MCP endpoint,
   e.g. `https://your-event-host/event_mcp`, + `SV_EVENT_API_KEY` from env/`.env`) — used
   when configured. The service returns structured SourceResults only and has NO query
   parser, so always pass explicit `months=` (+ `sources=`); it fetches per source, so
   one slow upstream just becomes an error entry, not a lost batch;
2. **local cache dir** (`SV_EVENT_LOCAL_CACHE`, `<source>/<YYYY-MM>.json`) — offline/dev;
3. **unavailable** → YOU are the fallback: use Claude WebSearch for the events and
   author broadcasts by hand. Every number/claim used this way lands in
   `grounding/grounding.json` via `sv_grounding.merge` (`via="web_search"`, url +
   accessed date) — provenance needs a landing place, not a passing note.

Web evidence is never the service's job: pair the structured numbers with your own
WebSearch when the narrative needs events/context, and ground both.

```python
from socioverse import materialize_external_events, month_range
from skills.sv_workspace import study_paths

path, ev = materialize_external_events(
    "studies/<id>", "US tariff shock and consumer prices",
    months=month_range("2025-04", "2025-06"),      # from study.yaml's time horizon
    sources=["fred", "nyt_archive", "yahoo_market"],  # optional preference
)
if not ev.available:      # both tiers down -> WebSearch fallback (tier 3)
    ...
```

Rules:
- The evidence lands in `environment/external_events.json` (provenance: `provider`
  tells which tier served it). Keep it next to `environment.json`.
- **Author broadcasts from `ev.results` (typed per-source data), NEVER from `ev.summary`**
  (`summary`/`web_evidence` are legacy fields — the production MCP returns structured data
  only; service prose would contaminate B=f(P,E) attribution). Quote numbers with their
  source + month.
- A study pins the service by NAME in `resources.json` (`McpServerDecl(name="event_tool",
  transport="http")`; url + key stay in env/`.env` — set `url=` only for a genuinely public
  endpoint, never a private/dev IP in a committed artifact). `ExternalEventsClient.from_manifest(manifest)`
  uses a pinned url when present and falls back to the environment otherwise; pass it via
  `materialize_external_events(..., client=client)`.
- The runtime loop never fetches: if E must change mid-run, schedule it as
  `ScheduledEvent`/`Broadcast` built from this materialized file.
- Event-service numbers that E consumes directly (layer baselines, provider_args) also
  get a grounding fact (`via="event_service"`) — see the grounding-first section above.

### Chicago example (reuses the study's bundle factory)
```python
from socioverse.validation import validate_handoff, write_artifact
from socioverse.schemas import StudySpec, ScheduledEvent, Broadcast
from skills.sv_workspace import study_paths
from studies.chicago_schelling.adapter import make_chicago_bundles

study = validate_handoff(study_paths("studies/chicago_schelling")["study"], StudySpec)
events = [ScheduledEvent(at_step=2, target_layer="tract_local", op="add",
            property_name="cta_stations", value=2, selector={"geoid_list": ["17031842600"]},
            note="open CTA station at step 2")]
broadcasts = [
    Broadcast(message_id="A", channel="news", content="Citywide transit expansion", at_step=2, ttl=3, audience="all"),
    Broadcast(message_id="B", channel="ward_notice", content="New rail station in your tract",
              at_step=2, ttl=3, audience={"geoid_list": ["17031842600"]}),
]
_, env_bundle, _ = make_chicago_bundles(scale="small", scheduled_events=events, broadcasts=broadcasts)
write_artifact(study_paths("studies/chicago_schelling")["environment"], env_bundle)
```

### Generic example (from-scratch / Path B — no Chicago)
For a `sv-build-model`-authored study, take the bundle from its factory (or construct `EnvironmentBundle` directly with `provider_ref="<id>.env"` + your `layers`/`scheduled_events`/`information_program`). The `provider_ref` must match a class the study registered.
```python
from socioverse.validation import write_artifact
from skills.sv_workspace import study_paths
from studies.opinion_diffusion.model import make_opinion_bundles   # the from-scratch template

_, env_bundle, _, _ = make_opinion_bundles(n_agents=12, campaign_step=2)
write_artifact(study_paths("studies/opinion_diffusion")["environment"], env_bundle)
```

## Re-entry (iteration mode — arriving from /sv-iterate)
A post-run change routed here means the version gate already ran (new version / branch / in-place):
- **E is affected** → author + `write_artifact` as above, overwriting the live `environment.json`
  (when the user chose a new version, the previous one is safe in its `versions/vN/` snapshot).
  New real-world context (rates, indices, news) still goes through the retrieval chain above,
  and the grounding entries the change touches get refreshed (`sv_grounding.merge` by id —
  leave the untouched entries alone).
- **E is NOT affected** → `validate_handoff(path, EnvironmentBundle)` only, report
  "environment.json unchanged, validation passed, rebuild skipped" (+ narrative), and do **not** rewrite the file —
  an identical rewrite bumps its mtime and corrupts the dashboard's carried/stale detection.
Then hand back to the iteration flow (next affected stage, or `/sv-run`'s spend gate).

## Pause & confirm (default: stop between stages)
Pausing here is the **default**, and it yields to an explicit user instruction about the flow.
1. **By default, stop and wait.** After writing `environment.json`, don't invoke `/sv-build-population` (or any later skill) on your own. Advance only on an explicit go-ahead; silence or an ambiguous reply is not confirmation.
2. **Follow the user's flow when they've set one.** If the user said how far to run or where to pause (e.g. "run straight through to /sv-run", "do the whole pipeline"), honor it — chain the stages to the point they named instead of stopping here.
3. **Either way, surface the intermediate product:** the layers / scheduled events / broadcasts in one line, plus the artifact path.
4. **Be rollback-ready.** If the user asks for changes — including ones that revise an earlier step's decision — revise `environment.json` in place, re-summarize, and stop again. Treat a change request as "redo this step", never "skip ahead".

## Hand-off
`sv-build-population` reads `study.yaml`; `sv-run` reads this `environment.json` via `validate_handoff(path, EnvironmentBundle)`.

## Dashboard narrative (optional, non-blocking — L2)
If the local run dashboard is up, after writing the artifact post a 1–2 sentence
plain-language summary of *what you decided and why*. It shows on this stage's card
+ event feed (files already carry the state; this is the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-build-environment \
  --text "E = 3 layers (information × macro/local); scheduled a fact-check broadcast to all at step 3."
```
Exits 0 / prints nothing, so it never blocks; skip in headless or offline runs.
