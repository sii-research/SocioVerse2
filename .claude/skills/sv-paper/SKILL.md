---
name: sv-paper
description: Draft the full academic paper for a SocioVerse2 study — abstract/intro/related work/methods/results/discussion — from the study's own artifacts (report, DuckDB trajectory, grounding, literature). Writes paper/paper.md for the dashboard's Paper tab. Use after sv-report. REQUIRES a literature survey: if literature/literature.json is missing, run /sv-lit first and finish it before drafting.
---

# sv-paper — draft the paper (from study to paper)

Turn a completed study into a submission-shaped draft. The paper is **evidence-bound**:
every number in it must be traceable to the study's own data.

## Two layers — read this first
This skill owns **what goes in the paper** (which artifacts, which numbers, which figures,
where the file lives). It does NOT own **how the prose reads**. That is the vendored
`research-paper-writing` skill (`.claude/skills/research-paper-writing/`, MIT, from
Master-cai/Research-Paper-Writing-Skills — see its `VENDOR.md`).

**Load it before you write a word of prose**, and load only the section guide you need
right now (its own rule — loading all six at once blows the context for no gain):

| writing this section | load |
|---|---|
| Abstract | `.claude/skills/research-paper-writing/references/abstract.md` |
| Introduction | `.claude/skills/research-paper-writing/references/introduction.md` |
| Related Work | `.claude/skills/research-paper-writing/references/related-work.md` |
| Methods | `.claude/skills/research-paper-writing/references/method.md` |
| Results / Experiments | `.claude/skills/research-paper-writing/references/experiments.md` |
| Conclusion | `.claude/skills/research-paper-writing/references/conclusion.md` |
| final self-review | `.claude/skills/research-paper-writing/references/paper-review.md` |

Its vocabulary is ML/CV-flavored; the translation for a SocioVerse2 study is one-to-one:

- **"Method"** = **B = f(P, E)** made concrete — P (population bundle), E (environment
  bundle), f (the decision protocol), and the metric definitions. Its rule "each subsection
  states motivation → design → technical advantage" maps onto "why this population/
  environment/decision rule is the right one for the research question".
- **"Experiments"** = the longitudinal run(s): the trajectory, the intervention windows, the
  forked counterfactual versions. Its baseline/ablation framing maps onto **version
  comparison** (v1 factual vs v2 counterfactual, scripted-f vs LLM-f).
- **"claim-evidence alignment"** is not optional here — it is the same rule as this skill's
  no-invented-numbers contract, just stated from the reviewer's side.

Two of its habits are worth naming because they are exactly what a simulation paper gets
wrong: **one paragraph = one message with the message in the first sentence**, and **reverse
outlining after each section** (write down the thesis, then each paragraph's topic sentence,
then check every paragraph maps to the thesis — cut what doesn't).

## Literature gate — run BEFORE anything else, no exceptions
**If `literature/literature.json` does not exist, run `/sv-lit` first and finish it.**
Not "suggest it", not "offer to" — run it, then come back and draft. A paper whose
Related Work was written from the model's memory is the exact artifact this pipeline
exists to prevent: the citations look right, the bibkeys resolve to nothing, and the
positioning claims ("unlike prior work, we…") are unfalsifiable.

Two follow-on rules:
- **Stale survey → refresh it.** If `literature.json` predates the current `study.yaml`
  (the research question moved since the survey), re-enter `/sv-lit` with queries derived
  from the *current* question rather than writing against a survey of a different study.
- **The only way to skip is an explicit user instruction in this conversation**
  ("skip the literature, just give me a draft first"). Then say so in the draft — one line under Related Work
  stating that the section is unsourced — instead of quietly shipping a paper that
  looks referenced and is not.

## Strict contract
- **Read** `study.yaml`, `reports/report.md` (+ `reports/figures/`), `trajectory/study.duckdb`
  (query for exact values), `grounding/grounding.json`, `literature/literature.json` +
  `references.bib` (guaranteed present by the gate above).
- **Write** `paper/paper.md` (+ `paper/paper.json`: `{"title", "language", "updated_at"}`).
- **No invented numbers, no invented citations.** Quantitative claims come from the DuckDB
  store / report; citations come ONLY from `references.bib` bibkeys or grounding sources.

## Outline gate (before writing)
Unless the user already specified a structure, confirm the skeleton first via a quick
AskUserQuestion (this is a taste decision, not yours to assume): the standard empirical structure
(Abstract / Introduction / Related Work / Methods / Results / Discussion / Conclusion) vs
expanding along the report's storyline vs a user-defined structure. Also confirm the LANGUAGE (default = the language the user
has been speaking; a Chinese paper with Chinese section names plus an English Abstract is a common combination, so ask).

## Writing rules
- `# title` once, then `##` numbered sections (the dashboard outline nav reads `#`/`##`).
- **Methods = B = f(P, E) made explicit**: P from `population.json` (size, stratification,
  real-data alignment), E from `environment.json` (layers, events, broadcasts), the decision
  protocol from `simulation.json`, metrics with their definitions from `study.yaml`.
- **Results re-derive from data, not vibes**: pull exact values with SQL from
  `trajectory/study.duckdb`; reference figures with `![](figures/<name>.png)`. Reuse the
  report's findings but WRITE UP, don't copy-paste: a paper argues, a report presents.

## Figures — cite only what exists; draw what you need
The #1 real-world failure of this stage is a paper citing figures that are not on disk.
Two known traps: after `/sv-iterate` the live `reports/` was WIPED and rebuilt (an earlier
version's figure now exists only in its `versions/vN/` snapshot), and it is easy to "remember"
a figure into existence while writing. The rules:

1. **Existence is a hard gate.** Every `![](figures/<name>)` must resolve to a real file in
   `reports/figures/` or `paper/figures/`. Before presenting, run the audit and make it clean:
   ```python
   from skills import sv_paper
   sv_paper.check("studies/<id>")        # must end True — else draw or drop each MISS
   ```
2. **A needed figure that doesn't exist → draw it NOW from the CURRENT trajectory** (this is
   expected and encouraged — the paper may well want views the report never rendered:
   a cohort breakdown, a zoom on the intervention window, a two-metric scatter):
   ```python
   from skills import sv_paper
   plt = sv_paper.mpl_setup()            # headless + CJK fonts preconfigured
   import duckdb
   con = duckdb.connect("studies/<id>/trajectory/study.duckdb", read_only=True)
   # ... query panel/metrics, plot ...
   plt.savefig(sv_paper.fig_dir("studies/<id>") / "<name>.png")   # → paper/figures/
   ```
   The dashboard and the Word/LaTeX export (hosted, or the pandoc command under Export) resolve `figures/<name>` against BOTH
   `reports/figures/` and `paper/figures/` — no other wiring needed.
3. **Never copy a figure out of a `versions/vN/` snapshot to depict the current version** —
   it renders THAT version's data. The one legitimate case: a section that explicitly
   discusses that historical version (e.g. factual v1 vs counterfactual v2) may use its snapshot
   figure, copied into `paper/figures/` and clearly labeled with the version in the
   caption/alt text.
4. **Revision requests can add visualizations at any time** — same recipe, then cite the new
   file. Delete a reference rather than ship it dangling.
- **Related Work**: 1–2 paragraphs organized by the literature themes; cite as `[bibkey]`
  (e.g. `[zhang2019cafeteria]`); position this study against the closest empirical work.
  Every key must exist in `references.bib` — grep for it before you write the sentence,
  and drop the claim rather than invent the support.
- **Discussion must carry the honesty section**: simulation-not-survey caveat, LLM-agent
  behavioral validity, and the declared assumptions from grounding (name the stylized / proxy anchors).
  Limitations that the grounding sidecar declares are not optional to mention.
- **References section**: list the cited bibkeys in readable form (author, year, title, venue).
  Never cite a key that is not in `references.bib`.
- Length: substantial but tight — typically 1,500–3,000 words.

## Self-review before presenting (not optional)
Load `.claude/skills/research-paper-writing/references/paper-review.md` and run its adversarial pass over
the finished draft — read as a skeptical reviewer across contribution / clarity / experimental
strength / evaluation completeness / method soundness, and **fix what it surfaces before you
show the user**, don't hand them a list of known problems.

Produce a **claim–evidence map** for every headline claim, in that skill's format:

```
Claim: <the sentence as it appears in the Abstract/Intro>
Evidence: <the exact figure/table/SQL result it rests on>
Status: supported | needs evidence
```

Anything that lands on `needs evidence` gets weakened or cut — a simulation paper that
overclaims is the single most common reason this stage produces something unusable.

## Pause & confirm (terminal stage)
Present: the outline actually written, the 2–3 headline claims **with their claim–evidence
map**, the figure manifest (each cited figure: pre-existing from the report vs newly drawn
this pass — and confirm the `sv_paper.check` audit passed), and where the draft lives
(`paper/paper.md`, visible in the dashboard's Paper tab). Then stop.
Section-level revision requests ("rewrite the Discussion section, strengthen the mechanism explanation") edit `paper/paper.md` in place —
on the hosted workbench they can come from the Paper tab's per-section rewrite buttons; in the local
dashboard there are no such buttons, so the user asks you in the session —
load that section's guide from `.claude/skills/research-paper-writing/references/` first, rewrite
paragraph-by-paragraph, then re-run the reverse outline on the section you touched. Update
`paper/paper.json.updated_at` each time.

## Export
Write clean markdown: pipe tables and `![](figures/...)` convert cleanly. On the hosted workbench
the Paper tab exports Word/LaTeX (pandoc, server-side). The local dashboard has no export button;
when the user wants a file, give them the pandoc command (pandoc must be installed; run it from
the study directory so `figures/<name>` resolves against `paper/figures/` and `reports/figures/`):

```bash
cd studies/<study_id>
pandoc paper/paper.md -o paper.docx --resource-path=paper:reports                          # Word
pandoc paper/paper.md -s -o paper.tex --resource-path=paper:reports --extract-media=paper_media  # LaTeX + its figures
```

## Dashboard narrative (optional, non-blocking — L2)
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-paper \
  --text "Drafted the paper: 7 sections, 3 figures, 9 references; headline claim = ..."
```
