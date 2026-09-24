---
name: sv-lit
description: Survey real related work for a SocioVerse2 study. Two tiers — a fast default across OpenAlex / Semantic Scholar / CrossRef / PubMed / arXiv (+ Chinese-native sources) via the vendored paper-search-pro engine, and an opt-in deep tier (deep-research lit-review) that adds multi-agent synthesis and per-reference verification but is markedly slower and more expensive, so ask first. Either way, write per-paper relevance notes tied to THIS study and produce literature/literature.json + references.bib for the dashboard's Literature tab and /sv-paper's Related Work. Usable any time after sv-init; /sv-paper REQUIRES it to have run.
---

# sv-lit — survey related work (real papers, per-paper relevance)

Ground the study in the actual literature: retrieve REAL papers, judge each one's
relevance **to this study specifically**, and leave a citable trail.

## Strict contract
- **Read** `study.yaml` (+ `grounding/grounding.json`, `reports/report.md` if present).
- **Write** `literature/literature.json` + `literature/references.bib` (helpers: `skills/sv_lit.py`).
- **NEVER fabricate a reference.** Every paper in the output must come from a retrieval call in
  this session. If retrieval fails entirely, report that and stop — an empty honest result beats
  an invented bibliography. Do not "recall" papers from memory into the artifact; memory may only
  help you choose *search queries*.

## Two tiers — pick one, and let the user pick when it matters

| | **Fast tier (default)** | **Deep tier (on request)** |
|---|---|---|
| Engine | `paper-search-pro` (5 sources searched together) | `deep-research` in `lit-review` mode |
| What it does | retrieve → federated dedup → heuristic ranking; you write the judgments and notes | adds: multi-agent division of labor, per-reference verification (Semantic Scholar match / DOI resolution / WebSearch spot checks), cross-paper synthesis |
| Time | **about 8 minutes** (measured: 4 queries, 18 tool calls, about 460 candidates after dedup) | **still not finished after 13 minutes** (measured, then interrupted; 90 tool calls, 5 retrieval sub-agents) |
| Cost | **about $1.0** (same measured run, with the candidate-screening discipline below already applied) | **$4.93 and unfinished** (measured). This is not a ceiling; it is the floor of an interrupted run |
| When to use | almost always; it is enough for `/sv-paper`'s prerequisite gate | the user explicitly wants "more complete / more rigorous", a systematic review, or a pass that checks every citation before the paper is submitted |

> Both tiers' numbers are **measured**, not estimates. Do not treat the fast tier as "nearly free" — it is also on the order of $1:
> the retrieval subprocess itself is cheap; what costs money is the agent reading abstracts, making judgments, and writing a dozen or so relevance notes specific to this study.
> The screening discipline below keeps it near $1 instead of $3–5, but it cannot bring it to zero. And `/sv-paper` hard-requires this stage to have run first,
> so **every paper pays this cost at least once** — state it at this order of magnitude to the user at the spending gate.

**Default to the fast tier; do not upgrade on your own initiative.** Ask before the deep tier: tell the user it is slower, more expensive, and where the cost comes from
("several agents split the work, and every citation is checked back against a database"), and run it only after they agree.
When the user proactively says "go deeper / be more comprehensive / check the citations for me", go straight to the deep tier.

**How to run the deep tier**: read `.claude/skills/deep-research/SKILL.md` and drive it in `lit-review` mode,
with this study's `research_question` and the themes already chosen as input. It produces an annotated bibliography + review prose;
**the output must still land in this skill's format** (`literature/literature.json` + `references.bib`, see step 5) —
do not leave a copy in its own report format inside the study; the dashboard only reads this one.
Its source-verification verdicts (`S2_VERIFIED` / `DOI_VERIFIED` / `PLAUSIBLE`) are worth writing into each paper's `note`:
that is exactly what the deep tier's extra cost buys.

⚠️ **Check that it exists before deciding whether to offer it.** The deep tier is not distributed with this repository (its upstream license is CC BY-NC, which is incompatible with this repository's
Apache-2.0); only environments that installed it themselves into `.claude/skills/deep-research/` have it. So:

```bash
test -f .claude/skills/deep-research/SKILL.md && echo deep-tier-available
```

**If it does not exist, treat the tier as nonexistent and do not mention it to the user** — offering it and then being unable to run it is worse than not having it.
The fast tier must always be able to complete the whole stage on its own: the deep tier is an enhancement, not a prerequisite.

## The fast tier's two layers
Finding the papers is delegated to the vendored **`paper-search-pro`** skill
(`.claude/skills/paper-search-pro/`, Apache-2.0 — see its `VENDOR.md`): OpenAlex ·
Semantic Scholar · CrossRef · PubMed · arXiv, plus native-Chinese sources (NSSD,
yiigle), with federated dedup and a saturation signal. This skill owns what the
papers **mean for this study** — selection, the per-paper relevance note, themes,
and the artifact the dashboard and `/sv-paper` consume.

Drive it through its **agent channel**, not the human 14-step recipe. Read
`.claude/skills/paper-search-pro/references/agent_mode.md` once before your first
call — it is the contract for the JSON envelope, the flags, and the error codes.
Its own north star applies here verbatim: the heuristic score it returns is a
**floor, not a verdict**. Ranking by it and stopping is the failure mode; you read
the abstracts and judge relevance yourself (step 3).

## Steps
1. **Derive 2–4 search queries** from `research_question` / `domain` / key mechanisms —
   English keyword style (e.g. "cafeteria price increase food choice students",
   "LLM agent social simulation"). Cover: ① the substantive phenomenon, ② the closest
   empirical/experimental literature, ③ the method (LLM/ABM social simulation).
   For a China-context study also run one Chinese query with `--lang zh` — the
   English indexes will not surface CSSCI / Chinese core-journal work.
2. **Retrieve.** **First check the engine's dependencies** — with the same interpreter you would
   run the engine with — before any engine call:
   ```bash
   python - <<'EOF'
   import importlib.util
   deps = ("pyalex", "semanticscholar", "requests", "arxiv", "Bio")   # the [lit] extra's search clients
   print("lit deps missing:", [m for m in deps if importlib.util.find_spec(m) is None] or "none")
   EOF
   ```
   **Anything missing → do not run the engine** (it would only fail on import). Tell the user once
   that the multi-source engine needs `pip install -e ".[lit]"` in this environment, and go
   straight to the stdlib fallback below. If they install the extra later, re-run the survey
   with the engine.
   Preferred path, when nothing is missing — the multi-source engine (its Python deps come with the
   `lit` extra: `pip install -e ".[lit]"`; use the interpreter of that environment):
   ```bash
   PSP=.claude/skills/paper-search-pro
   PYTHONPATH=$PSP python -m scripts.agent_search \
       "<query>" > /tmp/psp_<n>.json          # one call per query
   ```
   `data` is the deduped paper list; each entry carries doi / openalex_id / title /
   abstract / authors(+affiliation) / year / venue / citation_count / topics /
   `relevance.score`. `meta.counts` reports retrieved→dedup→returned, and
   `meta.saturation` tells you whether another query is still finding new work —
   **iterate until it flattens**, don't stop at one call.
   Fallback (engine unavailable — the dependency check above found something missing, or
   the engine errors at run time): the zero-dependency stdlib path, which is OpenAlex-only
   and thinner:
   ```python
   from skills import sv_lit
   found = []
   for q in queries:
       found += sv_lit.oa_search(q, n=8)
   try:
       found += sv_lit.s2_search(queries[0], n=8)
   except Exception:
       pass                                        # S2 anonymous pool is often 429 — skip silently
   papers = sv_lit.dedupe(found)
   ```
   Say which path you used in the summary — a fallback run is a narrower survey and
   the user should know.

   ⚠️ **Do not dump the retrieval results into the conversation context — this is the single biggest cost of this stage.**
   One `agent_search` call returns 100+ papers, each with its full abstract; a single `cat` is tens of thousands of tokens,
   while only a dozen or so actually need your reading. So: **write the results to files, then use a script to screen them down to one screenful**,
   and when you need full abstracts, read only the few papers on the shortlist.
   ```bash
   python3 - <<'EOF'
   import json, glob
   seen, rows = set(), []
   for f in sorted(glob.glob("/tmp/psp_*.json")):
       d = json.load(open(f))
       for p in (d.get("data") or []):
           k = (p.get("doi") or p.get("openalex_id") or p["title"]).lower()
           if k in seen: continue
           seen.add(k); rows.append(p)
   rows.sort(key=lambda x: -(x.get("relevance", {}).get("score") or 0))
   for p in rows[:25]:                       # look at the top 25 only, abstracts cut to 160 chars
       print(f'{p.get("year")} | {p.get("citation_count"):>5} | {p.get("doi")}')
       print(f'  {p["title"][:95]}')
       print(f'  {(p.get("abstract") or "")[:160]}')
   EOF
   ```
   Likewise: when `sv_lit.save` writes to disk, do not stuff all candidates into `papers` — only the 6–12 you decided to keep.
3. **Select 6–12 papers** worth keeping: prefer directly-comparable empirical work, then
   mechanism/theory anchors, then method references. Recency and citations are tie-breakers,
   not the criterion. Read the abstracts you retrieved — selection must be justified by them.
4. **Write a relevance note per kept paper** (`note`, 1–3 sentences, study-specific): WHICH
   parameter / mechanism / comparison in THIS study the paper anchors — e.g. "price-elasticity range
   -0.6 to -1.1, the empirical anchor for this study's P-side sensitivity parameter", never a generic abstract paraphrase.
   Set `relevance` (0–1, your judgment). Group into 2–4 `themes`.
5. **Save**:
   ```python
   sv_lit.save("studies/<id>", {
     "summary": "<one paragraph: what was searched, what the three main threads are, which 1-2 papers matter most for this study>",
     "themes": [{"name": "...", "n": 3}, ...],
     "papers": papers_kept,        # each: title/authors/year/venue/citations/url/doi/abstract + note + relevance
     "queries": queries,
   })
   ```
   `references.bib` is generated from the kept papers automatically (`bibkey` = first-author+year+word;
   /sv-paper cites these keys).
6. *(Optional, when a paper anchors a load-bearing modeling choice)* add it to
   `grounding/grounding.json` as an `implementation_ref` via `skills/sv_grounding.py` — the
   grounding card then shows it too.

## Pause & confirm
Present the themes + the kept papers (one line each: title · year · note), then **stop** for the
user's direction — they may prune, redirect ("find more from a Chinese context"), or extend ("add a methodology thread").
A follow-up request re-enters at step 1 with the new queries and MERGES (dedupe) into the
existing artifact — don't discard previously-kept papers unless asked.

## Failure honesty
- Retrieval engine unavailable → try the stdlib fallback (step 2); if that also fails, write
  NOTHING and tell the user retrieval is unavailable right now.
- Sparse results for a niche topic → say so; a 4-paper honest survey is fine.
- Never pad a thin result with papers you "know" — `/sv-paper` cites these bibkeys, and a
  fabricated entry there is the single worst failure this pipeline can produce.

## Dashboard narrative (optional, non-blocking — L2)
```bash
python3 dashboard/hooks/sv_emit.py narrative --study <study_id> --stage sv-lit \
  --text "Surveyed related work: 8 papers across 3 themes; Zhang & Kumar (2019) is the closest natural experiment."
```
