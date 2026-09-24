---
name: sv-report
description: Render the displayable time-step change for a SocioVerse2 study — per-step maps, a metric timeline (with intervention markers), and report.md, all queried from the DuckDB trajectory store. Use after sv-run.
---

# sv-report — display the time-step change

Read the DuckDB trajectory store and produce the human-facing outputs. Everything is reconstructed via SQL, so the same store also serves later real-time interactive querying.

## Strict contract
- **Read** `trajectory/study.duckdb` (tables: `panel`, `metrics`, `events`, optional `messages`) and `study.yaml`.
- **Write** `reports/report.md` + `reports/figures/*.png`.
- **Write the report in the study's language** — take it from the plain `title` /
  `research_question` in `study.yaml`. sv-init writes those in the language of the user's query (its
  language rule) and rewrites them when a Path-A fork's source was in another language, so they
  carry the language; the `*_i18n` fields are translations, never the signal. If the plain fields
  are still in another language than the one the user writes in (an older fork that kept its
  source's Chinese text), write in the user's language and tell them the fields are stale. Never
  default to Chinese: the reference studies' shipped reports are Chinese, but that says nothing
  about this user. Text quoted from a source (grounding claims, news) may stay in its own language.
- **Every figure the report references must actually be written this pass** — and on a
  version-iterated re-run remember that `/sv-iterate` WIPED the live `reports/` (the old
  figures live only in the `versions/vN` snapshot): regenerate the full figure set this
  version's story needs, not just the delta figure. Downstream `/sv-paper` cites from
  `reports/figures/`, so a shrunken set here becomes dangling citations there.
- **`report.md` is analytical, not a data dump — and it follows a general–specific–general arc** (overview → evidence →
  restated + deepened conclusion). In order:
  - **Opening · Headline conclusions (Overview)** — lead with the 2–4 headline conclusions of the whole run, one line
    each, stated as claims (not "we simulated X" but "X happened because Y"). This is the thesis the body
    then proves.
  - trajectory tables/figures (the descriptive backbone).
  - **Body · Findings and interpretation (Findings)** — the body, where **every conclusion is bound to the data that produced
    it**: each finding = a claim **immediately paired with the specific numbers/figure it reads off**
    (cite the actual value(s) or `figures/x.png`, e.g. "satisfaction fell from 0.74 to 0.61 (after the step-2 policy, see
    figures/satisfaction.png)") **AND the mechanism** (*why*, read off the panel/cohorts). The reader must
    be able to trace each conclusion back to its evidence — no claim without its number, no number without
    the claim it supports. Roughly one finding per key result; merge/split as the data warrants.
  - **Deeper insights** — non-obvious cross-metric / cross-cohort conclusions the raw tables
    don't state (who is insulated vs exposed and why, a threshold/tipping effect, a divergence between two
    metrics), each still tied to the data that reveals it.
  - **Controls and comparisons (Comparison)** — only when this study has a sibling run to read against, and the two
    kinds are never conflated:
    - **Branch comparison** — a branch and its parent share the same individuals, the same
      seed and the same history up to the fork step, and differ only in E afterwards, so
      **Δ_t = Y(E′) − Y(E)** is a paired per-step effect of the intervention. Name the two arms
      **control branch / treatment branch** and mark the fork step on the timeline.
    - **Version comparison** — two versions that differ in the population, the behaviour
      function, the run settings, or in E before the fork step are **different research designs** with no
      pairing between them. Report the gap as a design difference, never as the effect of an
      intervention.
  - **Closing · Restate and dig deeper (Conclusion)** — close by **restating the headline conclusions** (now earned by the
    body) and **digging one level deeper**: what they mean for the research question, the mechanism that
    unifies them, what remains uncertain. This is the closing "general" part of the arc — it must echo the headline conclusions, not introduce
    unsupported new claims.
  - **Recommendations and next steps** — actionable suggestions + what the next
    `/sv-iterate` round should test (a policy to try, a parameter to sweep, a cohort to probe).
  - **Data basis and sources** — last (see Step 2).
  The per-study `reporting.py` emits these section skeletons; fill the interpretation from the DuckDB
  trajectory (query it directly — you have the store open). Reference figures with normal
  `![alt](figures/x.png)` markdown — the dashboard renders them as clickable thumbnails.

## Capability check (external services — stable hook)
```python
from skills.sv_workspace import capability_view
for c in capability_view(stage="sv-report"):   # resources/capabilities.yaml
    print(c["name"], "| available:", c["available"], "| use_when:", c["use_when"])
```
A capability here typically contributes a comparison or baseline (e.g. a cross-sectional
poll rendered next to the panel trajectory) — it never alters the trajectory data. For a
matching entry: probe `health`, honor `confirm: true` (ask before spending/sending),
materialize what it returns under `reports/` with provenance in `grounding/grounding.json`,
pin by NAME in `resources.json`; unavailable → its `fallback`. Per-service how-to lives in
the registry entry, not here.

## Steps
1. Build the metric timeline + per-step maps + report:
```python
from skills.sv_workspace import study_paths, load_study_yaml
from studies.chicago_schelling.adapter.engine_seam import CHICAGO_LEGACY_DEFAULT
from studies.chicago_schelling.reporting import generate_report

p = study_paths("studies/chicago_schelling")
study = load_study_yaml(p["study"])
generate_report(
    p["duckdb"], p["report"].parent,
    # the tract geometry ships with the legacy model in the SocioVerse-ABM sibling clone
    geojson_path=CHICAGO_LEGACY_DEFAULT / "processed_data" / "chicago_tracts.geojson",
    event_steps=[2],                 # mark intervention steps
    study_title=study.title,
)
```
2. Append a **"Data basis and sources"** section to `report.md` from `grounding/grounding.json`:
   ```python
   from skills import sv_grounding
   g = sv_grounding.load("studies/<id>")   # None → skip the section silently (older studies stay renderable)
   ```
   - a pipe-table of the facts — `| Fact | Value | Basis | Source |` — with basis rendered as
     sourced/proxy/assumed and the source as plain "title (url)" text (report.md's minimal
     markdown renders no links; clickable sources live on the dashboard's "Grounding & sources" card);
   - `implementation_refs` as a short bullet list (Modeling references);
   - `assumptions` as a bullet list (Declared assumptions);
   - `method_notes == "stylized"` → the single line "Stylized model; no real-world anchors.";
   - **forked studies — say where the grounding came from.** If `study.yaml` has `forked_from`,
     open the section with one line: "This study was forked from `<forked_from>`; the anchors below are inherited from the source study"
     (plus ", and were supplemented for this study's changes" when facts were added after the fork — compare fact
     ids/`added_at` against the source if present). Readers must not mistake inherited anchors
     for evidence gathered specifically for this variant.
3. Summarize for the user: the metric trajectory (e.g. did `D_black_white` bend after the intervention step?), the number of persistent households tracked, and where the figures live.

## Pause & confirm (terminal stage)
1. **Runs on an explicit trigger or as the tail of the user's flow.** `sv-run` doesn't chain into reporting on its own — produce the report when the user triggers `/sv-report` or when their stated flow includes it.
2. **After rendering: present, don't proceed.** Show the metric trajectory, the count of persistent agents tracked, and where the figures live — then stop.
3. **Be rollback-ready.** If the user wants different `event_steps`, a metrics subset, or different framing, re-render `report.md` / figures in place and present again. Treat a change request as "redo the report".
4. **Changes to the STUDY itself → `/sv-iterate`.** A follow-up that changes the experiment (a new intervention, more steps, a different population — not just the report's rendering) must go through `/sv-iterate`'s version gate and pipeline re-entry — never an ad-hoc artifact edit + re-run.

## Ad-hoc / interactive querying
The store is a plain DuckDB file — answer follow-up questions directly with SQL, e.g.:
```sql
-- one household's tract trajectory over time
SELECT step, state->>'tract_id' AS tract, state->>'satisfaction' AS sat
FROM panel WHERE agent_id = 'chi-...' ORDER BY step;
-- per-step movement volume
SELECT step, n_movers, pct_pop_moved FROM metrics ORDER BY step;
```

This closes the workflow: `query → environment → population → run → report`.

## Dashboard narrative (optional, non-blocking — L2)
If the local run dashboard is up, after rendering post a 1–2 sentence plain-language
summary of *what the report shows*. It shows on this stage's card + event feed
(files already carry the state; this is the reasoning):
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-report \
  --text "Rendered report.md + 5 figures; D_bw bends down post-intervention, matching the hypothesis."
```
Exits 0 / prints nothing, so it never blocks; skip in headless or offline runs.
