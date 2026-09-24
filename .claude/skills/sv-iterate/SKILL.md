---
name: sv-iterate
description: The ONLY entry point for changing an EXISTING SocioVerse2 study — especially one that already ran. Use whenever the user asks to modify, extend, adjust, tune, or iterate a study, add another round/step, add or change a policy/broadcast/intervention, change parameters (n_steps, seed, scale), swap population or decision logic, or open a counterfactual branch that keeps an earlier run's history. It runs the mandatory version gate (new version vs counterfactual branch vs modify-in-place — always asked, never assumed), then re-enters the standard sv-* pipeline at the earliest affected stage. NEVER ad-hoc edit + re-run an existing study outside this skill.
---

# sv-iterate — post-run iteration: version gate + pipeline re-entry

SocioVerse2 studies are longitudinal and long-lived: after the first run the user keeps sending
change queries ("now add a housing policy at the next step and run one more round").
Every such query re-enters the **same** `query → environment → population → run → report`
pipeline through here — an ad-hoc edit+run outside the skills leaves the dashboard blind,
silently overwrites the previous results, and produces untrackable artifacts.

## Strict contract
- **Locate the target study first; nothing is touched before the version gate.**
- **A `reference: true` study is FORK-ONLY.** The version gate (new version / branch / in-place —
  all mutate the *same* committed `study_id`) does NOT apply to a baseline template. Step 1's
  reference guard forks it to a new `study_id` first; editing the template itself is a rare,
  explicitly-warned choice, never the default. This is the same "never edit a reference in place"
  rule sv-init enforces — it must hold here too, because "modify an existing study" routes here.
- **The version gate is a SENSITIVE operation — always `AskUserQuestion`, never a silent
  default.** Creating a version preserves history; modifying in place destroys it.
- **Without `AskUserQuestion`** (a headless `claude -p` run, Codex, or a chat UI without that
  tool), every ask in this skill — the reference guard in step 1 and the version gate in step 3 —
  falls back the same way:
  - the user's request **explicitly names the option** ("open a counterfactual branch from step 2",
    "keep the old run and save this as a new version", "fork it", "change it in place") → proceed
    with that option, provided step 2 allows it, and record the choice and the reason in the
    version note (e.g. `branch, named in request: denial day 3→2`, still ≤ 50 chars; a fork has
    no version note, so say it in your summary);
  - otherwise **stop**: put the SAME options as a compact numbered list — the recommended one
    first, each with its consequence stated — and wait for the user's pick. Unlike sv-init's
    checklist, nothing here takes a default: you never pick a gate option yourself.
  - A named option that step 2 rules out ("branch" for a population change, "in place" for a
    mode switch) is not an answer: say why it is not available and print the options that are.
- **The vocabulary is fixed.** A **version** is any change that re-runs cold. A
  **branch** is the special case that changes only the environment from its fork step on and
  inherits the parent's earlier steps by replay. **fork** means exactly one thing — deriving a
  new *study* from a reference study (step 1). Never call a version or a branch a fork.
- This skill **routes and versions; it does not author bundles.** Artifact changes happen
  in the stage skills (`/sv-build-model` / `/sv-build-environment` / `/sv-build-population`
  / `/sv-run` / `/sv-report`), each under its own contract.
- Dashboard sync is file-driven: `create_version` / `create_branch` write `versions.json`; the
  dashboard's version box follows it automatically (auto-jumps to the new current). No extra emits.

## Steps

### 1. Locate the target + refuse a live run
Target = the study the user names > the study just built/run in this session > ask.
First action once known (registers the iteration query, wakes the dashboard):
```bash
python3 dashboard/hooks/sv_emit.py session --query "<the iteration request, one line>"
```
Then check nothing is mid-run: a fresh `trajectory/progress.jsonl` while
`trajectory/metrics_history.json` is absent = a run in flight → wait for it (or get an
explicit instruction to abandon it) before iterating.

**Reference guard — do this BEFORE the version gate.** Read the target's `study.yaml` and check
`reference: true`. A reference study is a **committed baseline template** (a bundled demo or an
adapted reference); the version gate does NOT apply to it — new version / branch / in-place all
mutate the same committed `study_id`. So a "change consumer_confidence to 500 / run it with real
LLM"-type request on a reference study is a **fork (a study-level derivation)**, not an in-place iteration — even
when the user phrased it as "modify". **First check availability** (`catalog_view()` row of the
reference, same gate as `/sv-init` Step 0): if `available` is false, tell the user it needs
`missing` and give its `setup` command(s) instead of forking; if `rerunnable` is false it is an
imported reference — offer a new study that uses it as a template, not a fork. Otherwise
`AskUserQuestion` (never assume; without the tool, the fallback in the strict contract):
- **(a) Fork into a new study, then change it (recommended)** — fork it so the template stays pristine, then iterate the FORK:
  ```python
  from skills.sv_workspace import fork_study, init_manifest, study_paths
  fork = fork_study("studies", "<reference_id>", "<new_id>")   # rewrites study_id in ALL artifacts + sets reference=false
  init_manifest(fork)                                          # the fork starts its own v1 line
  print("iterate on:", study_paths(fork)["study"])
  ```
  A fresh fork has **no history to version → SKIP the version gate (step 3)**: go straight to step 2
  (classify) and re-enter the affected stage on the fork (Path-A style). The dashboard renders it with
  a "forked from `<reference_id>`" badge + inherited stepper automatically.
- **(b) Change this baseline template itself (use with caution)** — edit the reference template in place. **You MUST warn the user
  first, verbatim in spirit:** ⚠️ "This changes a baseline template shared across the whole SocioVerse2 framework. It affects
  every Path-A reuse built on it, build-model's template selection, and future routing, **and may affect the behavior of
  SocioVerse2 simulations as a whole — proceed with great care**." Only pick this
  to deliberately MAINTAIN the demo/template. If chosen, proceed with the normal flow on the template
  (the user has accepted the risk); the study stays `reference: true`.

A non-reference (working) study skips this guard entirely and goes to the normal version gate.

### 2. Classify the deltas → affected stages
| the query changes… | affected stage / artifact | → version or branch (`t*` = the fork step, see the end of this section) |
|---|---|---|
| policies, scheduled events, broadcasts, real-world macro context (mortgage rates, price indices, news — retrieve via `materialize_external_events` + WebSearch fallback) | `/sv-build-environment` → `environment/environment.json` | **branch** when every new or changed entry sits at `at_step >= t*` and nothing else moves; **version** if it rewrites an entry at `at_step < t*` |
| personas, population scale, interaction structure, propagation | `/sv-build-population` → `population/population.json` | **version** (P changed, so the whole trajectory changes) |
| decision rules / from-scratch dynamics code | `/sv-build-model` → `model.py` (Path B) or the study's adapter | **version** (f changed) |
| time horizon (`n_steps`), `seed`, `interaction_rounds` | **both** `study.yaml` **and** `simulation/simulation.json` (sv-run rebinds) | **version**; exception: only lengthening `n_steps`, with everything else left untouched, can be a degenerate **branch** with `t* = the parent version's n_steps + 1` (`n_steps` is the only run setting a branch may change) |
| decision/run **MODE or provider** switch (scripted↔LLM, local↔real-LLM, deterministic↔stochastic) | `/sv-run` → `simulation/simulation.json` `decision_args`/provider — **comparison-worthy: new-version only, see step 3** | **version only** (f is swapped, so it can never be a branch) |
| the research question itself | that is a NEW study — recommend `/sv-init` (a study-level fork) | neither a version nor a branch |

**A mode/provider switch is a comparison-worthy change — preserve the baseline.** scripted-f vs
LLM-f (and probabilistic/local vs real-LLM) is itself a scientific result: the earlier run is the
comparison point, so it must survive. Such a change is therefore **new-version-only** — step 3 does
NOT offer in-place for it (overwriting would destroy the very baseline you'd compare against). Even a
"let me first see a scripted dry-run of the pipeline" is kept as its own version, not overwritten by the real run.

**Grounding refresh:** when the classified change touches real-world context or magnitudes
(a policy with real numbers, a different city/period, updated rates), the re-entered stage
also refreshes the affected `grounding/grounding.json` entries via `sv_grounding.merge`
(merge by id — never a wholesale rewrite; a superseded anchor gets updated
`value`/`as_of`/`source`). Unaffected stages leave grounding.json untouched — the same
hygiene rule as the artifacts. Grounding is NOT cleared on a version bump: it carries into
the new version, and each `versions/vN/` snapshot keeps that version's own frozen copy.

**Settle the branch eligibility while classifying** — it decides whether step 3 may offer (b) at all.
The change is a **branch** only when it adds one or more interventions (a `ScheduledEvent` or a
`Broadcast`) to the environment bundle at `at_step >= t*` and leaves everything else at the parent's
values — or, in the degenerate case, adds nothing but a longer `n_steps`, with `t*` = the parent version's
`n_steps` + 1. `t*` is the fork step, the first step the new intervention can bite. It is **NOT** a
branch — so do **not** offer (b) — when the edit touches the population `P`, the study's code /
decision logic `f`, the `seed`, or any environment entry at `at_step < t*`: those change the whole
trajectory and must re-run cold as a version. A branch additionally needs a **from-scratch /
Path-B** study with `interaction_rounds == 1` (chicago's legacy wrap and multi-round studies always
re-run from 0).

**Moving an intervention in time keeps its duration.** When the change shifts an existing
`Broadcast` or `ScheduledEvent` to another step ("announce the denial on day 2 instead of day 3"),
move its `at_step` and keep the original duration unless the user asked to change it. For a
`Broadcast` the duration is the number of steps it is actually visible: steps `at_step ..
at_step + ttl - 1`, clipped at `n_steps`. Keep that count, not blindly the `ttl` value: a
broadcast at step 3 with `ttl=3` in a 5-step run is visible on steps 3–5; moved to step 2 it keeps
`ttl=3` (steps 2–4) and no longer covers step 5, whereas a `ttl` stretched to reach the horizon
would make it one step longer as well as earlier. A `ScheduledEvent`'s change persists until
something reverses it, so firing it earlier also lengthens the exposure. Point out any such change
in duration or exposure in the gate question and the version note, so the comparison does not
silently test "earlier **and** longer" at once; change `ttl`, or add a reversing event, only when
the user asks for it.

### 3. The version gate (mandatory ask)
**Skip this step for a brand-new fork's first change** (step 1 chose (a) fork): a fresh fork has no
history to version — go straight to step 4/5 and build on it.

Draft a one-line version `note` (≤ 50 chars, e.g. "subway news + step-4 home-buying incentive, run 4 steps"), then
`AskUserQuestion` (without the tool: the fallback in the strict contract) with these three exits:
- **(a) New version (recommended)** — snapshot the current version as `v<N>` (artifacts, code, AND
  results all preserved, viewable forever in the dashboard), then iterate as `v<N+1>`. This is the exit
  for any change to the population `P`, the behaviour function `f`, the run settings `Θ`, or an
  environment entry that bites before the fork step. The run is **cold, from step 0**. Ask the starting
  point as a sub-question of this option — **which version to start from: the current version / historical version v<X>** — but only when
  the query references an earlier version (or the user picks it); a historical start restores that
  version's artifacts as the new version's starting point, with `parent` recording where it came from.
  That is a starting point, **not** a branch.
- **(b) Branch (counterfactual)** — the new version adds interventions at `at_step >= t*` to the
  environment bundle (or only stretches `n_steps`) and changes nothing else. It **inherits steps
  `0..t*-1` from the parent by replaying that run's stored actions** (exact, no LLM, no budget) and
  only computes `t*..n_steps`, so it pairs with its parent as control / treatment on the *same* individuals.
  Offer it **only when step 2 classified the change as a branch** (environment-only at
  `at_step >= t*`, or a pure `n_steps` extension) and the study is from-scratch / Path-B with
  `interaction_rounds == 1`. chicago (legacy wrap) and multi-round studies are not eligible — the
  engine cannot replay them — so drop the option and say why: "studies of this kind can only re-run cold from step 0 via (a)."
- **(c) Modify in place** — no new version. The current artifacts are edited in place and the
  existing outputs are **overwritten on re-run and unrecoverable** (the classic
  stale/rollback flow). Spell this consequence out in the option description. **Do NOT offer this
  option when step 2 classified the change as a mode/provider switch** — overwriting would destroy the
  comparison baseline (scripted vs LLM, local vs real-LLM). A mode/provider switch changes `f`, so (b)
  is out too: for those, offer only (a), with its current / historical-version starting-point sub-question.
Confirm the `note` in the same question.

### 4. Create the version or the branch — ALWAYS set the re-entry stage
The gate's answer decides both the call and `resume_from_stage`, the stage the dashboard parks its
pointer on and **reviews forward from**. Pick it by the VERSION CHOICE:
- **(b) Branch** → `create_branch(...)` with `fork_step = J`, the step the new intervention lands on.
  It already defaults `resume_from_stage="sv-build-environment"` (the environment bundle is the only
  artifact a branch re-authors) — **don't pass it again**. There is no separate "inherit the steps already run or not?"
  question any more: picking (b) *is* the decision to inherit `0..J-1`.
- **(a) New version, starting from the current version** → `resume_from_stage = <the earliest affected stage from step 2>`.
- **(a) New version, starting from historical version v<X>** → `base="v<X>"` + `resume_from_stage="sv-init"` — starting from an
  old design is a big context switch, so re-review EVERY stage from the start.
- **(c) Modify in place** → call nothing; go straight to the stage skills.
```python
from skills.sv_workspace import create_branch, create_version, current_version
current_version("studies/<id>")            # the parent version id, for the note / later review
# (b) branch: only adds interventions at at_step >= J; 0..J-1 are inherited by replaying the parent
new_id = create_branch("studies/<id>", note="<one-line note>", fork_step=J)
# (a) new version from the current version — re-enter at the earliest affected stage:
new_id = create_version("studies/<id>", note="<...>", resume_from_stage="<earliest affected stage>")
# (a) new version from historical version v<X> — re-review every stage from the start:
new_id = create_version("studies/<id>", note="<...>", base="v1", resume_from_stage="sv-init")
```
`resume_from_stage` drives the dashboard's **review gate**: every carried stage from it forward
shows **needs review** until you handle it in step 5, so the version can't look finished with the parent's
unreviewed artifacts. (Belt-and-braces: the dashboard fails safe to the first carried stage if it's
ever missing — but set it explicitly.) Both calls freeze the live dir into `versions/v<N>/` (the
parent's `study.duckdb` is preserved there — that's what a branch replays), restore the base when
starting from a historical version, clear the live run outputs, and move `current`. `sv-run` picks up
the branch's replay spec through `resolve_warm_start` (`warm_start` is the on-disk name of that spec);
**do not** edit `simulation.json` here.

**Branch-downgrade fallback — if the branch is downgraded automatically, tell the user plainly.** Before any run, `resolve_warm_start` calls
`check_branch_invariant`, which re-compares the live workspace against the parent's snapshot:
`population.json` + `roster.jsonl`, the study's own `*.py` / `adapter/*.py`, `simulation.json`'s
`seed` / decision / collector / store / engine args / `interaction_rounds` (note `n_steps` is exempt —
a branch may run longer), the provider and every environment entry at `at_step < fork_step`, and the
parent's environment layers (a branch may **add** a layer to carry its broadcast, never rewrite or
delete one the parent already had). If a later edit broke the environment-only claim, the branch is
**downgraded to a plain version, not rejected**: `kind` becomes `"version"`, the replay spec is
dropped, the run goes cold from step 0, and `downgraded_from_branch` (source, fork step, and one
violation line per offending artifact) stays on the manifest entry as the audit trail. Never let that
pass silently — tell the user **which artifact broke the branch**, that steps `0..t*-1` will now be
recomputed by the LLM instead of replayed, and roughly what that adds to the bill. The downgrade is
**not undone in place** — the entry is a version now — so if they'd rather keep the branch, revert the
offending artifact to the parent's copy and open a fresh branch with `create_branch`. You can
pre-check at any time without touching the manifest:
```python
from skills.sv_workspace import check_branch_invariant
check_branch_invariant("studies/<id>", downgrade=False)   # {kind, ok, violations, source, fork_step}
```

### 5. Re-enter the pipeline — review EVERY stage from the re-entry point forward
The dashboard parks its pointer at `resume_from_stage` (a branch → `sv-build-environment`; a new
version from the current one → the earliest affected stage; a new version from a historical version →
`sv-init`) and shows every carried stage from there as **needs review** until you handle it. Walk the stages
**in pipeline order from the re-entry point** and handle EACH one explicitly —
don't stop after only the "obviously affected" one:
- **Affected stage → invoke its skill** (`/sv-build-environment`, …): re-author the artifact, post
  its narrative, pause.
- **Unaffected stage → verify + skip:** `validate_handoff(path, Model)`, confirm it still fits the
  new intent, then **post its narrative** ("population.json unchanged, validation passed, rebuild skipped"). That narrative
  is what marks the stage **reviewed this version** and clears its needs-review flag — **do NOT rewrite the
  file** (an identical rewrite bumps mtime and corrupts carried/stale detection).

A carried stage you neither re-author nor verify+skip stays **needs review** and holds the pointer — the
pipeline can never look finished with an unreviewed stage. (This is why a new version from an old
base re-reviews from `sv-init`: the earlier stages carried from an old base are the easiest to leave
silently wrong. A branch is the opposite case — everything but the environment is provably the
parent's, so the environment bundle is the only stage it has to re-author.)

### 6. The run gate is unchanged — and say what a re-run means
`/sv-run` confirms before spending, as always. When the horizon was extended or an intervention
was added, state the run shape before the user confirms:
- **branch** → steps `0..t*-1` are inherited from v<parent> by replaying its stored actions
  (reproduced exactly, **no LLM, no cost**); only `t*..n_steps` spend budget;
- **cold run** (a new version, chicago, a multi-round study, or a branch that `check_branch_invariant`
  downgraded) → the **FULL horizon re-runs from step 0**; earlier steps won't exactly reproduce the
  parent under a real LLM (same seed included) and their cost is paid again.

### 7. Wrap up
Summarize: the version decision (`v<N+1>`, version or branch, note, parent, and a branch's fork step),
which stages were rebuilt vs verified-skipped, and that the dashboard has jumped to the new version
(archived versions stay selectable in the version box). Don't chain into `/sv-report` unless the
user's flow asked for it.

## Pause & confirm (default: stop between stages)
Same default as every stage: after the version gate + each re-entered stage, stop and
wait unless the user set a flow ("run it right after the change"). The version gate itself can never be
skipped by a flow instruction — it is always asked. (Without `AskUserQuestion`, a request that
explicitly names the option is the answer to the gate, not a skip — see the strict contract.)

## Dashboard narrative
This skill posts **no stage narrative of its own** — the version `note` in
`versions.json` is its record (it appears in the version box and the event feed).
The re-entered stage skills post their own narratives as usual.
