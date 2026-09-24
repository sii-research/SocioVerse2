# SocioVerse2 — usage guide for Claude

> **Building a NEW study / compatible component** (e.g. migrating HiSim, ElectionSim, or writing
> new providers)? Read **`CLAUDE-dev.md`** + **`README-dev.md`** instead — this file is for *using*
> the framework to run studies, not extending it.

A **longitudinal, LLM-native social-simulation runtime**. Core idea = Lewin's field theory
**B = f(P, E)**: a FIXED population pool `P` (persistent agent ids) under a DYNAMIC environment
`E` (two axes: physical/information × macro/local), driven step-by-step so the *same* agents are
tracked over time (panel data) — the differentiator vs AgentSociety / OneSim.

## Environment & how to run

ALWAYS use the Python environment SocioVerse2 is installed in (Python 3.11+; see `README.md`):

```bash
PY=python
$PY -m pip install -e ".[dev,viz]"      # from the repository root; add extras as needed (llm, workbench, lit, abm, chicago)
$PY -m pytest tests -q                  # all tests; studies that wrap a companion repo skip when it is absent
$PY scripts/demo_offline.py             # opinion_diffusion end to end as the local study opinion_diffusion_demo, no key (llm_kind scripted)
$PY studies/chicago_schelling/run_demo.py --steps 3 --intervention-step 2   # live Chicago demo (needs the SocioVerse-ABM sibling + [chicago])
```

- **Secrets**: the LLM key is read from env `SV_LLM_API_KEY` (or `OPENAI_API_KEY`), with a gitignored
  `.env` here as fallback (see `.env.example`). NEVER hard-code keys.
- **No-token mode**: set `llm_kind: "scripted"` in a from-scratch study's `simulation.json` decision_args;
  for chicago, pass `llm_client=DeterministicLLMClient()` to `build_chicago_simulator` to dry-run
  the plumbing without spending API.

## The workflow you run — `init · build-model · build-environment · build-population · run · report · iterate`

Claude-Code skills (in `.claude/skills/`). Each writes ONE validated artifact into
`studies/<id>/`, then **by default pauses for you to inspect / edit / redo before the next** — so you
can change course or roll back at any gate. Tell it how far to run (e.g. "build everything, prompt me
before `/sv-run`", or "do the whole pipeline") and it follows your flow, chaining the stages while
still surfacing each artifact as it passes.

| skill | what it does | writes |
|---|---|---|
| `sv-init` | **intent checklist first** (Step −1 intent checklist: seven fixed dimensions to align on what the task is, rendered live in the cockpit; the user may delegate and take the defaults), then **route the query** against already-adapted studies (reuse vs build-new) and parse it into a study **+ grounding bootstrap** (real-world anchors via search) | `intent.json` + `study.yaml` + `grounding/grounding.json` |
| `sv-build-model` | *(Path B only)* implement a from-scratch study's four abc natively on Core | `model.py` |
| `sv-build-environment` | build E (layers + interventions + broadcasts) | `environment/environment.json` |
| `sv-build-population` | build P **and instantiate the agents** (materialize the pool now, not at run start) | `population/population.json` + `population/roster.jsonl` |
| `sv-run` | run the longitudinal simulation | `trajectory/study.duckdb` + `metrics_history.json` |
| `sv-report` | render the time-step change | `reports/report.md` + figures |
| `sv-lit` | **survey real related work** (multi-source retrieval via the vendored `paper-search-pro` engine, per-paper relevance notes; never fabricates a reference) — any point after sv-init; **`sv-paper` requires it** | `literature/literature.json` + `references.bib` |
| `sv-paper` | **draft the full academic paper** from the study's own artifacts (report/DuckDB/grounding/literature) — after sv-report. Prose craft is delegated to the vendored `research-paper-writing` skill (see below) | `paper/paper.md` |
| `sv-iterate` | **change an EXISTING study** (the only post-run entry): the version / branch gate → re-enter at the affected stage | `versions.json` + `versions/vN/` snapshots |

To run a skill, read its `.claude/skills/<name>/SKILL.md` and follow it. Skills are discovered at
**session start**, so open the repository root as the project and use a fresh session.

**Literature search engine**: `.claude/skills/paper-search-pro/` is also a vendored third-party skill (Apache-2.0,
O0000-code/paper-search-pro) — a joint search over five sources (OpenAlex / Semantic Scholar / CrossRef / PubMed / arXiv)
plus native-Chinese sources (NSSD, yiigle), with federated dedup and a saturation signal. `sv-lit` drives retrieval through its **agent channel**
(`references/agent_mode.md`) and itself only owns "what these papers mean for this study". It **needs pip dependencies**
(pyalex etc., `pip install -e ".[lit]"`); when they cannot be installed, `sv-lit` automatically falls back to the zero-dependency
OpenAlex path in `skills/sv_lit.py` — details in its `VENDOR.md`. **`/sv-paper` now hard-requires `/sv-lit` to have run first**:
without `literature/literature.json`, run it first; writing related work from memory is exactly what this pipeline exists to prevent.

**The paper-writing "craft layer"**: `.claude/skills/research-paper-writing/` is a third-party skill vendored from GitHub
(MIT, Master-cai/Research-Paper-Writing-Skills, derived from Prof. Peng Sida's open paper-writing notes). It **only owns how the prose
is written** — per-section writing guides, "one idea per paragraph / lead with the point" paragraphs, the reverse outline, and the adversarial
pre-submission self-review with a claim–evidence check. `sv-paper` only owns **what to write** (which artifacts to read, where the numbers come from,
that every figure must actually exist, which file it lands in) and loads the matching `references/<section>.md` on demand while writing. The two layers are
deliberately separate: upgrading the third-party skill is a plain `cp` over it, and SocioVerse2's evidence contract is not overwritten (details in its `VENDOR.md`).

**Grounding (real-world anchoring)**: every study carries a sidecar `grounding/grounding.json` — facts
with sources (`basis`: sourced/proxy/assumed), modeling references, and declared assumptions
(helper: `skills/sv_grounding.py`; not a pydantic handoff). `sv-init` bootstraps it — a quick
native **WebSearch always runs**, the Event service adds structured data when reachable, and
what can't be sourced is declared an assumption (never silently invented). The build stages
consult + extend it ("ground before you invent": load-bearing E/P values cite a fact id or an
assumption), `sv-report` renders it as the report's data-basis-and-sources section, the dashboard shows it as the
"Grounding & sources" card, and it rides along with forks and version snapshots automatically.

**What `sv-init` decides first — the three paths:** Step 0 globs every `studies/*/study.yaml` (the
catalog — `skills.sv_workspace.catalog_view()`) and matches your query against each study's
`domain / legacy_simulator / metrics / adjustable_params`:
- **Path A — reuse/adjust:** a study already covers it and your changes are artifact-level → **fork it to a
  new `study_id`** (`fork_study(...)`, leaving the matched/reference study untouched) and edit the *fork's*
  `environment.json` / `population.json` / `simulation.json`, then re-run (**no new code**). Never edit a
  reference study (`reference: true` in its `study.yaml`) or any existing study in place.
- **Path B — build from scratch on Core:** nothing matches and you have no existing simulator → `sv-build-model`
  writes the four abc natively (no seam), assembled by `socioverse.engine.build_simulator`. Template: pick
  from the catalog — `reference: true` + `"from-scratch-core"` in `demonstrates` (each entry's `teaches`
  line says what it exemplifies). This is the default for an end-user query.
- **Path C — adapt a legacy simulator:** nothing matches but you have your own simulator to wrap →
  follow `CLAUDE-dev.md` (engine-seam + adapter). Collaborator pre-loading path; its output later
  becomes a Path-A reuse target.

`catalog_view()` is also your one-stop view of *everything adapted so far*.

**Capabilities (external service registry)**: `resources/capabilities.yaml` is the committed, PUBLIC index
of attachable external services — currently the Event service (structured macro/news context
for E) and the user-pool survey MCP (real X / Xiaohongshu (RED) personas + questionnaire answering for
P/report). Each entry says what it provides, which sv-* stage it anchors to, when to use it
(`use_when`), whether to ask before calling (`confirm: true` = spends money / sends data out),
and its `fallback` when unreachable. Endpoints & keys are NOT in the registry — they live in the
gitignored `.env` / `.mcp.json`; a study pins what it actually used **by name** in its
`resources.json`. Every build skill runs a stable generic "capability check" hook via
`skills.sv_workspace.capability_view(stage=...)`, so attaching a new service = one registry
entry, zero skill edits. The runtime loop never fetches — everything is materialized at build
time with provenance in `grounding/grounding.json`.

## Iterating an existing study — the /sv-iterate hard rule + versions & branches

**Any change to an already-built study — especially after a run — goes through `/sv-iterate`.
Never ad-hoc edit artifacts + re-run an existing study outside the skills**: the dashboard goes
blind and the previous results get silently overwritten. ("add a policy and run one more round" = `/sv-iterate`,
not a hand edit.)

**Exception — a `reference: true` study is FORK-ONLY**, even when the request is phrased as "modify"
("change consumer_confidence's population to 500 / run it once with a real LLM"). It's a committed baseline template, so
the version / branch gate (which mutates the same `study_id`) does not apply — `/sv-iterate`'s reference guard
forks it to a new `study_id` first (`fork_study`, which also rewrites the embedded `study_id` in every
artifact + clears `reference`), then iterates the fork. Editing the template itself is a rare,
explicitly-warned choice. **A run-mode/provider switch** (scripted↔LLM, local↔real-LLM) is
**new-version-only** — the earlier run is a comparison baseline (scripted-f vs LLM-f), never overwrite it.

`/sv-iterate` runs the **version / branch gate** — three exits, mutually exclusive (a sensitive
choice: always asked, never assumed):

- **(a) new version** (recommended default) — the edit touches the population `P`, the behaviour
  function `f`, the run settings `Θ`, or an environment entry *before* the fork step. The live dir is
  snapshotted to `studies/<id>/versions/v<N>/` (artifacts + code + results, viewable in the dashboard
  forever), then the study iterates as `v<N+1>` and **runs cold from step 0**. A sub-question picks
  the starting point — the current version, or an older `v<X>` whose artifacts are restored first
  (that is a starting point, not a branch).
- **(b) branch** (the counterfactual) — the edit **only adds interventions at `at_step >= t*`** to
  the environment bundle; `P`, `f`, the seed and every environment entry before `t*` must match the
  source version exactly (only the horizon `n_steps` may grow). Steps `0..t*-1` are **replayed from
  the source run's stored actions (no LLM, no budget, reproduced exactly)** and only `t*..T` is paid
  for, so a branch pairs with its parent as treatment vs control. **Eligible:** from-scratch / Path-B
  studies with `interaction_rounds == 1` (their `env.apply` is a pure function of the actions).
  **Not offered** for legacy-wrap (chicago) or multi-round studies — the engine refuses to replay
  them, so those iterate as a new version instead.
- **(c) in-place** — no snapshot; the classic stale/rollback flow, the current outputs are lost and
  cannot be recovered. Never offered for a run-mode / provider switch.

In code: `create_version(study_dir, note, base=...)` for (a), `create_branch(study_dir, note,
fork_step=t*, source=...)` for (b). Each `versions.json` entry carries `kind` (`"version"` /
`"branch"`) and `fork_step`, so the dashboard can label the two apart. Before spending, `sv-run`
re-checks the branch constraint (`check_branch_invariant`): a branch that turns out to have changed
`P` / `f` / the seed / an environment entry before `t*` is **automatically downgraded to a version and run
cold from step 0** — no error, the reason is reported to the user and the downgrade is recorded in
the manifest (`downgraded_from_branch`) for audit.

It then re-enters the pipeline at the **earliest affected stage** (e.g. a new policy broadcast →
`/sv-build-environment`; unchanged stages are validated + skipped, **not rewritten**), and
`/sv-run` confirms before spending as always.

The dashboard's **version box** (top-right, under the study switcher) lists every version with
its one-line note, auto-jumps to a newly created version, and renders archived versions
read-only from their snapshots. `studies/*/versions/` is gitignored (local history, like `runs/`).

## Inspecting each step (what got produced)

Every step's output is a file under `studies/<id>/` — `cat` it to see (and edit) that step:

```bash
S=studies/chicago_schelling
cat $S/study.yaml                       # the StudySpec (research question / n_steps / metrics)
cat $S/environment/environment.json     # layers + scheduled events + broadcasts
cat $S/population/population.json        # materialized personas + count + interaction + propagation
cat $S/population/roster.jsonl          # the instantiated agents' t=0 state (what the dashboard shows pre-run)
cat $S/reports/report.md                # trajectory table + intervention notes
```

The run output is a queryable DuckDB store (answer follow-ups with SQL directly):
```sql
SELECT step, state->>'tract_id' FROM panel WHERE agent_id = 'chi-...' ORDER BY step;  -- one household over time
SELECT step, D_black_white, n_movers FROM metrics ORDER BY step;                        -- the trajectory
SELECT step, note FROM events ORDER BY step;                                            -- interventions fired
```

## Conventions when using

- Run in the env SocioVerse2 is installed in; open **the repository root as the project** (so skills + imports resolve).
- **Don't commit** `.env`, `studies/*/runs/`, `*.duckdb`/`*.parquet` (all gitignored).
- **One study per process** (the legacy wrap's globals aren't parallel-safe).
- To change an experiment that already exists, go through **`/sv-iterate`** (the version / branch gate, then the affected stage skill re-authors its artifact) — don't bypass the skills with a hand edit + re-run.

## Where to go next
- Run / inspect studies → this file + `README.md`.
- **Develop a new study or component → `CLAUDE-dev.md` + `README-dev.md`.**
