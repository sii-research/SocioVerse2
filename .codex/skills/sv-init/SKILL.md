---
name: sv-init
description: Entry point for a NEW SocioVerse2 study from a user's research query. Use at the START of a simulation study — it FIRST routes the query against already-adapted studies (catalog of studies/*/study.yaml) to choose reuse/adjust (Path A) vs build-new, and only then parses the query into a validated StudySpec + ResourceManifest and scaffolds the standardized layout the other sv-* skills consume. NOT for changing a study that already exists — modify/extend/iterate requests on an existing study (especially one just run) route to /sv-iterate instead.
---

# sv-init — query → standardized study workspace

You are the first stage of the SocioVerse2 workflow (`query → environment → population → simulation → report`). Turn the user's natural-language research need into a **validated `StudySpec`** and scaffold the workspace. Do not build the environment or population here — later skills do that.

## Language rule — the study speaks the language of the user's query
Detect the language of the user's **query text** (the research question they typed), before
anything else. Write every user-facing display field in THAT language: the checklist `value`s and
`q`s, the research brief, `title`, `research_question`, `hypothesis`, `metric_descriptions`, and
the report (`/sv-report` and the stage narratives follow the same language). State it in the
brief ("Language: English"), so later stages and a resumed session keep it.
- **Never default to Chinese.** The shipped reference studies, their reports and grounding files
  are largely written in Chinese; that is their content, not a signal about this user. The same
  goes for the dashboard locale, the system locale and the language of these instructions.
- A mixed-language query → the language of most of its prose. Unclear (e.g. only a study name or
  a formula) → English, and say so in the brief. An explicit user instruction ("write it in
  German", "reply in Chinese") overrides all of this.
- `*_i18n` variants are extra translations for the dashboard, never the primary text: the plain
  field is always in the query's language.

## Step −1 — the intent checklist (clarify task understanding BEFORE planning)
A one-line query almost never pins down what the user actually wants, and "clarify while
executing" pollutes the study with re-runs. So **before Step 0** you run a structured
clarification pass over a FIXED checklist of seven dimensions — the questions that, answered
wrong, would change the study's architecture or its point. The checklist is also a live UI:
the cockpit renders it in the center pane while you clarify, each item flipping state as it
settles, so the user always sees what is aligned and what is still open.

### The seven dimensions (fixed ids — the cockpit maps them to bilingual labels)

| id | the question it settles | what it decides downstream | typical default |
|---|---|---|---|
| `rq` | the research question and the **shape of the conclusion**: what kind of conclusion the user wants — a descriptive trajectory / a predicted number (checkable against ground truth) / an intervention-vs-counterfactual causal comparison / a mechanism explanation | `research_question` / `hypothesis`; how the report and the paper argue | descriptive trajectory + a brief-style conclusion |
| `form` | **simulation form**: single-round cross-section or multi-step longitudinal; what one step means (day / week / month / event round); roughly how many steps | `study_type` / `n_steps`; the time index of the environment layers | longitudinal; step length = the phenomenon's natural rhythm; 6–12 steps |
| `inter` | **interaction structure**: independent individual decisions, or mutual influence over a neighbor network / information shared through a population-wide broadcast / market matching and clearing; one message round per step or several | the population's `interaction` / `propagation`; messaging config | independent decisions + macro broadcasts (the most robust); use a network only for contagion-type phenomena |
| `scope` | **study scope**: who the population is (identity + sources of heterogeneity), the size tier (small ≤50 / medium 100–500 / large 1000+), the space-time window | population sizing and sources; the environment's regional / period anchoring | small tier ≤50; the window the query implies |
| `exp` | **comparison design**: is a single-arm main line enough, or is a control arm / counterfactual branch / parameter sweep / backtest against a real series needed | version planning (main line + which branches / versions); `adjustable_params` | single-arm main line; note which comparison would most strengthen the conclusion and open that branch after the run |
| `evidence` | **evidence and grounding**: what the study may be grounded in — news search / academic literature / official statistics / user-uploaded data / purely stylized | grounding search scope; the capability pins in `resources.json` | real-world domain = search + official statistics; abstract proposition = declare stylized |
| `success` | **outputs and criteria**: the 2–4 metrics that matter most; the deliverables (report / forecast numbers / paper); what kind of result counts as informative | `metrics` / `display_metrics` / `metric_descriptions` | 2–4 metrics + a report |

### Protocol
1. **Bring the cockpit up first** (the session emit in the next section — it registers the
   query and resets any stale checklist), **then parse the query against all seven items.**
   Each item gets one of: `inferred` (readable from the user's own words → write your reading as the value) or `pending`
   (important but not readable → write one focused follow-up question as `q`). Every item ALSO gets a resolvable default,
   so "go with the defaults" is always executable. Publish the sheet immediately:
   ```bash
   python3 dashboard/hooks/sv_emit.py checklist <<'EOF'
   {"phase": "clarifying", "query": "<one line>",
    "items": [
     {"id": "rq",       "status": "inferred", "value": "descriptive + causal: how the meal mix shifts over time after a canteen price rise"},
     {"id": "form",     "status": "inferred", "value": "longitudinal · 1 step = 1 week × 8 steps"},
     {"id": "inter",    "status": "pending",  "value": "", "q": "Should students influence each other (herding / word of mouth), or decide independently?"},
     {"id": "scope",    "status": "inferred", "value": "students at one university · small tier ≤50"},
     {"id": "exp",      "status": "pending",  "value": "", "q": "Run only the price-rise line, or add a no-rise control line as a counterfactual?"},
     {"id": "evidence", "status": "inferred", "value": "news search + official statistics"},
     {"id": "success",  "status": "inferred", "value": "canteen share / delivery share / monthly food spend · a report"}
    ]}
   EOF
   ```
   Write every `value` and `q` in the language of the user's query (the language rule above; the example happens to be English).
   Re-send the WHOLE payload every time any item changes state — the cockpit always renders
   the latest copy. Fail-silent, never blocks.
2. **Ask ONE round.** Take the `pending` items plus any `inferred` item whose wrong reading
   would restructure the study (`form`/`inter`/`exp` are structural; `rq`/`success` are the
   point; `scope`/`evidence` are usually safe to infer) — cap at 3–4 questions. Use
   AskUserQuestion when the tool is available (defaults as the FIRST option, recommended);
   in a chat UI without that tool put the SAME questions as a compact numbered list, each with its default
   stated and "unanswered questions take their defaults" spelled out. **Never re-ask what the message already pins —
   extract, don't interrogate.** A second round is allowed ONLY if a first-round answer
   opens a genuinely blocking ambiguity; otherwise proceed on defaults.
3. **Settle statuses.** Each user answer flips its item to `answered` (record the answer as
   value). A skipped question, or an explicit "just start / use the defaults / anything is fine", flips the rest to
   `default` with the default written into value. Re-emit the checklist.
4. **The intent brief + confirmation.** Reply with a compact **research brief** — 5–8 lines
   restating the checklist's settled values (research question & claim type, step semantics
   × n_steps, interaction mode, population scale & who, comparison plan, evidence sources,
   metrics — flag anything filled by default) — and ask for confirmation in the same message
   ("once you confirm I'll set up the study; to change any item, just say so"). On confirmation (or an explicit go), re-emit
   with `"phase": "confirmed"` and proceed to Step 0. If the user skipped Step −1 entirely
   ("just start" up front), you still fill the checklist yourself (all `inferred`/`default`),
   emit it, and fold the brief into your first summary instead of a separate stop.
5. **Archive on scaffold.** Right after the workspace exists (build-new step 3 / Path A
   fork), re-emit with `--study <study_id>`: this writes `studies/<id>/intent.json`, the
   durable confirmation sheet the overview tab renders forever (forks and version snapshots
   carry it automatically).

The confirmed checklist is the source of truth for `study.yaml` (`research_question` /
`hypothesis` / `study_type` / `n_steps` / metrics fields / population sizing), for the
comparison plan (`exp` → which branches / versions to offer after the main run), and for which
capabilities the later stages consult (`evidence`) — record deviations from defaults in the
spec's discovery fields rather than silently deciding.

## First action — surface the run dashboard (only now, as a study begins)
The dashboard is launched **by this workflow**, not on session start. So the very first
thing to do when sv-init runs — BEFORE the Step −1 questioning (its checklist renders on
this dashboard, and this emit resets any stale checklist from a previous session) — is
bring it up and register the user's research need:
```bash
python3 dashboard/hooks/sv_emit.py session --query "<the user's research need, one line>"
```
This opens/wakes the dashboard and shows the query **only when a sv-* study actually
begins** — plain workspace chat or unrelated conversation never pops it. The command
prints the dashboard URL; relay it to the user. Fail-silent; skip in headless/offline runs.

## Strict contract
- **Route first (Step 0).** Match the query against already-adapted studies *before* building anything.
- **Every query becomes its OWN study workspace — never edit an existing study in place.** Whichever path you pick, the user's run lands in a *fresh* `studies/<new_id>/`. Reuse (Path A) means **forking** a matched study into a new `study_id`; build-new (Path B/C) scaffolds a new one. Writing into an existing study's directory happens ONLY through **`/sv-iterate`** (its version gate decides new version / branch / in-place) — never from here.
- **Reference studies are READ-ONLY baselines — never write into them.** Any study whose `study.yaml` carries `reference: true` (the bundled templates), and any study you did not create in this session, is a validated baseline. A new query must NOT mutate its `environment.json` / `population.json` / `simulation.json` / `study.yaml`. Fork it. (The flag — not a name list — defines the set, so the shipped demos can change without editing this skill.)
- **Build-new (Path B/C) — Write** `studies/<study_id>/study.yaml` validated as `socioverse.schemas.StudySpec` (fill the discovery fields `domain / tags / legacy_simulator / provider_refs / adjustable_params / status` so future routing can find it — plus `demonstrates` / `teaches` when the study shows a reusable pattern worth copying) **and** `studies/<study_id>/resources.json` validated as `socioverse.schemas.ResourceManifest` (declare any user-supplied datasets, MCP servers, or tools mentioned in the query — scenario 3).
- **Path A (reuse/adjust) — fork, don't edit.** `fork_study(...)` copies the matched study into a new `study_id` (still **no new code**); then point the user at the *fork's* artifacts to edit. The matched study is left untouched.
- Never write half-formed artifacts: construct the pydantic model, then `write_artifact`.
- **Ground before you invent.** Every new study gets `grounding/grounding.json` (see the
  grounding-bootstrap section; helper `skills/sv_grounding.py`) — real-world anchors with
  sources, or explicitly declared assumptions. A study with zero grounding entries and no
  `method_notes="stylized"` is incomplete.

## Step 0 — consult the catalog (route reuse vs build-new)
List what has already been adapted and decide whether this query is just a *variant* of an existing study:

```python
from skills.sv_workspace import catalog_view
for c in catalog_view("studies"):      # globs studies/*/study.yaml — the runtime catalog
    gate = ("" if c["available"] else "NEEDS " + ", ".join(c["missing"]) + " | ") + \
           ("" if c["rerunnable"] else "IMPORTED (view/template only) | ")
    print(("REF " if c["reference"] else "") + c["study_id"], "|", gate + c["domain"],
          "|", c["legacy_simulator"], "| metrics:", c["metrics"],
          "| adjustable:", c["adjustable_params"], "|", c["status"],
          "| demonstrates:", c["demonstrates"])
```

**Availability gate — check it before offering Path A.** Every catalog row carries
`requires` / `available` / `missing` / `setup` / `rerunnable`. Offer a Path-A fork (or a run)
ONLY for a study with `available and rerunnable`:
- **Not available** (a companion repo it wraps is not on disk, or the Python extra its seam
  imports is not installed) → show it as **"needs <X>"** with its `setup` command, e.g. `git clone https://github.com/Lishi905/SocioVerse-ABM
  ../SocioVerse-ABM` then `pip install -e ".[abm]"` (abm_* studies) or `".[chicago]"`
  (chicago_schelling). The user can install it and come back; otherwise proceed with Path B.
  Never fork it and let `/sv-run` fail later.
- **`rerunnable: false`** (an imported reference: a published trajectory brought in by a
  script, not a run of this loop) → it can be viewed and read as a template for Path B, but
  is never forked or re-run.

**Iteration, not a new study?** Decide this FIRST: if the query modifies or extends a study
that already exists — especially the one just built/run in this session ("add a policy at the
next step", "run one more round", "change n_steps / the broadcast text") — do NOT fork and do
NOT scaffold. **Hand off to `/sv-iterate`** (version gate + re-entry at the affected stage).
Fork (Path A) is for a *new research question* that borrows an existing study as its baseline;
`/sv-iterate` is for *continuing the same research thread* on the same study.
**Vocabulary — "fork" is study-level only**: deriving a new `study_id` from a reference study.
Iterations INSIDE one study are **versions** or **branches** and belong to `/sv-iterate`; never call one
of those a fork.
**Carve-out — a `reference: true` target is fork-only even when phrased as "modify"** ("change
consumer_confidence to 500 / run it with a real LLM"): it's a committed baseline, so it can't be iterated in
place. Either fork it here (Path A) or hand to `/sv-iterate` — its reference guard forks it too; both
land the change on a new `study_id`, never on the template.

Otherwise judge each candidate on: same `domain` / `legacy_simulator`, overlapping `metrics`, and whether the query's *deltas* fall within its `adjustable_params`. Then pick exactly one of three paths:

- **Path A — reuse/adjust** (strong match; every delta is artifact-level, same dynamics/simulator). **Fork the matched study into a NEW `study_id` — never edit it in place.** This keeps the baseline / reference template pristine and gives the user's run its own workspace. The fork reuses the matched study's registered providers + parity guarantees with **no new code** (its bundles still reference the source's `provider_refs`; `sv-run` imports the source package to register them). Then point the user at the *fork's* artifact(s) to edit (`environment/environment.json`, `population/population.json`, `simulation/simulation.json`) and which skill re-runs them (`/sv-build-environment` → … → `/sv-run`).

  ```python
  from skills.sv_workspace import fork_study, init_manifest, study_paths
  fork = fork_study("studies", "chicago_schelling", "chicago_sez")   # matched_id -> new_id; refuses to overwrite
  init_manifest(fork)                                                # the fork starts its own version line at v1
  print("edit:", study_paths(fork)["environment"])                   # then /sv-build-environment on the FORK
  ```

- **Path B — build from scratch on Core** (no match, and the user has NO existing simulator to wrap — the default for an end-user query). Write the artifacts below with `legacy_simulator="from_scratch"`, then the **next skill is `/sv-build-model`**, which implements the four abc natively on Core (no seam). This is the high-freedom, from-zero path; `CLAUDE-dev.md` is NOT needed.
- **Path C — adapt an existing legacy simulator** (no match, but the user/collaborator HAS their own simulator to wrap — a mesa/NetLogo model, a published research codebase, etc.). Write the artifacts, then point them at **`CLAUDE-dev.md`** to build the engine-seam + adapter that reuses their validated dynamics. This is the collaborator pre-loading path; its output later becomes a Path-A reuse target.
- **Ambiguous → present the top 1–2 candidates** with your path recommendation and **ask before proceeding**. When unsure between A and B, prefer building a new study (Path B) over reaching into an existing one — a fresh workspace is always safe; an in-place edit is not.

## Steps (build-new — Path B or C)
1. Extract from the query: a short `study_id` (kebab-case), `title`, `research_question`, `hypothesis`, whether it is `longitudinal` (tracking the same population over time — the default and the point of SocioVerse2) or `cross_sectional`, the time horizon `n_steps`, and the `metrics` of interest. **Every metric gets a one-line meaning in `metric_descriptions`** (what it measures + unit/direction) — the dashboard shows these on the model/run cards and as timeline tooltips; a curve without its definition is unreadable. **Also pick `display_metrics`**: the 3–5 metrics whose trajectories tell the study's story — the dashboard timeline plots ONLY these, so leave out bookkeeping/derived/constant metrics and mixed-scale outliers that would flatten the shared axis.
   **Write the three display fields bilingually**: write `title` / `research_question` / `hypothesis` in the language of the user's query (the language rule above — an English query gets English plain fields, never Chinese ones), and ALSO fill `title_i18n` / `research_question_i18n` / `hypothesis_i18n` with BOTH `en` and `zh` variants (translate yourself — it costs nothing at authoring time); when the query is in English or Chinese, that variant is identical to the plain field. The dashboard renders the viewer's language and falls back to the plain field; forks inherit and must keep these in sync when the framing changes.
2. Note any external resources the user mentions: "use my population pool MCP", "here's a GeoJSON at /path", "use tool X" → put them in `ResourceManifest.{mcp_servers, datasets, tools}`. **Then consult the capability registry** — `capability_view()` from `skills.sv_workspace` (all stages; backed by `resources/capabilities.yaml`) — and pin every entry whose `use_when` matches this study into `resources.json` as `McpServerDecl(name=<entry name>, transport=…)`, so the build stages know to apply it. **Pin by NAME only** — endpoints resolve at use time through `.mcp.json`/`.env`; a private/dev url must never land in a committed study artifact. An entry with `confirm: true` is a user decision: surface it in this stage's summary ("I suggest attaching service X — use it?") rather than silently pinning. Build stages re-check the registry at their own gates, so a capability can still join later — pinning here records the intent up front.
3. Scaffold + write — **set the discovery fields** so this study joins the catalog (example shows a **Path B from-scratch** study; for Path C set `legacy_simulator` to the wrapped simulator path):

```python
from skills.sv_workspace import init_manifest, scaffold, study_paths, save_study_yaml
from socioverse.schemas import StudySpec, ResourceManifest
from socioverse.validation import write_artifact

study = StudySpec(
    study_id="rumor_spread",
    title="Rumor spread on a social network under a fact-check broadcast",
    research_question="Does a step-3 fact-check broadcast slow belief in a rumor over time?",
    hypothesis="Local peer contagion raises belief; the macro fact-check broadcast bends the curve down after step 3.",
    study_type="longitudinal", n_steps=6, seed=42,
    metrics=["mean_belief", "believer_fraction"],
    metric_descriptions={"mean_belief": "Mean belief in the rumor across all agents (0–1, lower is better)",
                         "believer_fraction": "Share of agents who believe the rumor (belief > 0.5)"},
    # --- discovery fields (so Step 0 of a future run can find this study) ---
    domain="information-diffusion",
    tags=["opinion-dynamics", "network", "from-scratch"],
    legacy_simulator="from_scratch",          # Path C would put the wrapped simulator path here
    provider_refs=["rumor.env", "rumor.pop", "rumor.decision", "rumor.collector"],
    adjustable_params=["n_agents", "n_steps", "fact-check step & reach", "contagion rate"],
    status="draft",
)
root = scaffold("studies", study.study_id)
save_study_yaml(study_paths(root)["study"], study)
write_artifact(study_paths(root)["resources"], ResourceManifest(study_id=study.study_id))
init_manifest(root)   # register the study as v1 — the dashboard's version box shows it from day one
```

Then archive the confirmed intent checklist into the new workspace (Step −1 protocol
step 5) — same for a Path A fork, right after `fork_study`:

```bash
python3 dashboard/hooks/sv_emit.py checklist --study <study_id> <<'EOF'
{"phase": "confirmed", "query": "<one line>", "items": [ ...final statuses, all answered/default/inferred... ]}
EOF
```

4. Report to the user: the chosen **path**, the `study_id`, the study type + horizon, and the next step:
   - **Path B** → `/sv-build-model` (write the four abc natively on Core). It reasons from the WHOLE reference set as mechanism precedents — the 11 `abm-benchmark-seam` classics (by family), the `legacy-seam` adapted domains (chicago / consumer), and the `from-scratch-core` skeletons — then copies the code shape from the closest `from-scratch-core` template. Path B is NOT "fork opinion_diffusion": that is just one of several skeletons.
   - **Path C** → follow `CLAUDE-dev.md` to build the engine-seam + adapter around the legacy simulator.
   If the query is ambiguous about horizon or metrics, ask before writing.

## Grounding bootstrap (all paths — right after the workspace exists)

Anchor the study in reality BEFORE later stages invent values: seed
`studies/<id>/grounding/grounding.json` (helper `skills/sv_grounding.py` — a sidecar,
not a pydantic handoff; later skills merge into it, the dashboard renders it as the
"Grounding & sources" card, `sv-report` cites it).

1. Derive 3–5 groundable questions from the query, two kinds:
   - **how** similar phenomena are modeled (papers / ABM precedents) → `implementation_refs`
     — feeds this stage's framing and `/sv-build-model`'s mechanism choice;
   - **what** the load-bearing magnitudes are (baseline prices/rates/shares for E and P)
     → `facts` (load-bearing = changing it could change the conclusion).
2. Retrieve, per question:
   - **always run a quick live-search pass** (1–2 queries; WebFetch the 1–2 load-bearing
     pages) — it covers what the structured sources don't (local-language news, policy and prices).
     The default route is the built-in **WebSearch** — record `via="web_search"` + `url` +
     `accessed`. **Optional upgrade:** when the Event service is configured and its
     in-session **`search_web` MCP tool** is visible, route news/event/public-opinion queries through
     it (multilingual news search, `lang` matching the study's region, e.g. `"eng"` or `"zho"`) and record `via="event_service"`;
     keep WebSearch for general-web needs (docs, PDF, full policy texts);
     **search-outage discipline**: if WebSearch fails (403/"No links found"), do NOT retry
     it — use `search_web` if it is available, else WebFetch a known official source
     (national statistics offices such as BLS, Eurostat or NBS; sector bodies such as JNTO or CNNIC), then an honest `assumptions` entry. Tell the user
     once ("model-side search is temporarily unavailable; used the fallback retrieval") and move on — never stall the stage;
   - a fact matching the Event service's structured sources (fred / census / monthly news)
     that E needs anyway → defer to `/sv-build-environment`'s `materialize_external_events`
     step (recorded there with `via="event_service"`);
   - nothing usable / offline → an `assumptions` entry with a rationale (honest > plausible).
   Budget ≤5 searches total; retrieval failures never block the pipeline.
3. Write it:
   ```python
   from skills import sv_grounding
   sv_grounding.merge("studies/<id>", query="<the user's query>",
       implementation_refs=[{"title": "…", "url": "https://…", "takeaway": "…", "accessed": "2026-07-06"}],
       facts=[{"id": "f-base-price", "claim": "Average campus cafeteria meal price", "value": 8.8, "unit": "USD/meal",
               "as_of": "2026-05", "basis": "sourced",   # sourced | proxy | assumed
               "source": {"title": "…", "url": "https://…", "via": "web_search", "accessed": "2026-07-06"},
               "applies_to": ["environment.provider_args.base"]}],
       assumptions=[{"id": "a-delivery-share", "claim": "Delivery share of weekday lunches ~15%", "rationale": "No public data; a conservative estimate"}])
   ```
   If a search result overturns a `study.yaml` field (metric units, a realistic horizon),
   fix it now — it is still this stage's artifact.
4. **Path A — make an explicit re-grounding decision.** `fork_study` already copied the
   source's grounding.json; before touching it, judge: **do the fork's deltas need external
   data the inherited grounding doesn't already cover?**
   - **Search** — the delta introduces a new real-world anchor (a new magnitude/rate/price
     whose realistic size matters, a new population/region/time window, a named policy or
     event) → run a fresh *delta-scoped* search pass (same budget rules as step 2) and merge
     the new facts/refs by id; inherited entries that still apply stay.
   - **Inherit** — a pure parameter-level variant (every delta stays inside the source's
     `adjustable_params` and rests on anchors the source already sourced) → adapt only the
     inherited entries the deltas touch (merge by id; never rewrite wholesale), no new search.
   Either way, **record the decision** in the merge call, e.g.
   `sv_grounding.merge("studies/<id>", method_notes="fork re-grounding: searched — a one-off +20% shock size needs a real price-change case behind it")`
   (or `"… inherited — pure parameter-level fork, anchors carried over from the source study"`), so the dashboard's "Grounding & sources" card shows
   whether the fork re-searched or inherited, and why. Never skip the judgment silently.
5. A deliberately stylized/abstract study records
   `sv_grounding.merge("studies/<id>", method_notes="stylized")` instead of fake facts —
   the dashboard then shows "Stylized model — no real-world anchors" explicitly.

## Pause & confirm (default: stop between stages)
Pausing here is the **default**, and it yields to an explicit user instruction about the flow.
1. **By default, stop and wait.** After routing + writing (or forking), don't invoke any later skill (`/sv-build-model`, `/sv-build-environment`, …) on your own. Advance only on an explicit go-ahead; silence or an ambiguous reply is not confirmation.
2. **Follow the user's flow when they've set one.** If the user said how far to run or where to pause (e.g. "build everything, prompt me before the run", "do the whole pipeline"), honor it — chain the stages to the point they named instead of stopping here.
3. **Either way, show what this step produced:** the chosen **path**, the `study_id` (and, for Path A, the source it was forked from), the study type + horizon + metrics, and the artifact path(s) — so nothing happens off-screen.
4. **Be rollback-ready.** If the user asks for changes — including ones that revise this study's framing or undo a choice you just made — redo THIS step (re-fork or re-write `study.yaml`), re-summarize, and stop again. Treat a change request as "redo this step", never "skip ahead".

## Hand-off
- **Path B** → `/sv-build-model` reads `study.yaml` and writes the study's `model.py` (the four abc), then `/sv-build-environment` onward author the artifacts.
- **Path C** → `CLAUDE-dev.md` (engine-seam + adapter), then `/sv-build-environment` onward.
- **Path A** → re-enters `/sv-build-environment` directly on the **fork's** `study.yaml` (the source study is never modified).

All downstream skills read `study.yaml` via `validate_handoff(path, StudySpec)`.

## Dashboard narrative (optional, non-blocking — L2)
If the local run dashboard is up, after writing the artifact post a 1–2 sentence
plain-language summary of *what you decided and why*. It shows on this stage's card
+ event feed (files already carry the state; this is the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-init \
  --text "Routed to Path B (no catalog match); wrote study.yaml — 6 steps, metrics mean_belief/believer_fraction. Grounding: 4 facts: 3 sourced / 0 proxy / 1 assumed · 2 refs."
```
Exits 0 / prints nothing, so it never blocks; skip in headless or offline runs.
