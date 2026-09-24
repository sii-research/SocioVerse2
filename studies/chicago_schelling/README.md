# Chicago Schelling — first SocioVerse2 study

Migrates the legacy Chicago 2010 racial-segregation Schelling model into SocioVerse2
**without editing the legacy `src/`**. It is the reference template for migrating any
existing simulator.

## Requirements

The legacy model code and its census data are vendored in the companion repo
[SocioVerse-ABM](https://github.com/Lishi905/SocioVerse-ABM) under
`tasks/organization/chicago_segregation/legacy/`. Clone it next to this repo and install the
`chicago` extra:

```bash
git clone https://github.com/Lishi905/SocioVerse-ABM ../SocioVerse-ABM
pip install -e ".[chicago]"
```

For another layout, set `SV_CHICAGO_LEGACY` (the legacy dir itself) or `SV_ABM_ROOT` (the
SocioVerse-ABM root); see `.env.example`. Without it the Chicago tests skip.

## How it maps to B = f(P, E)

| SocioVerse2 concept | Chicago binding |
|---|---|
| **P** (persistent population) | one persona per `HouseholdAgent`; id `chi-{archetype}-{init_tract}-{clone_idx}` |
| **E** macro-physical | `model.city_race_share` |
| **E** local-physical | `describe_tract_with_context_for_llm` + 1-hop Queen `get_surrounding_area_summary` |
| **E** macro/local-information | audience-scoped `Broadcast`s, spliced into the tract description |
| scheduled intervention | `ScheduledEvent` mutates `gdf` (e.g. `cta_stations += 2`) at step N |
| **B** (behaviour) | reused `_assess_archetype_satisfaction` + `_evaluate_move_candidates` (batched LLM) |
| E_{t+1} | reused `_apply_move_budget` + `agents.shuffle_do("step")` |
| metrics | reused `compute_all_metrics` + `_compute_direction_metrics` → DuckDB |

## Run

```bash
PY=python
# live (real LLM): subway opens at step 2 + policy broadcasts (policy A citywide, policy B to that tract)
$PY studies/chicago_schelling/run_demo.py --steps 3 --intervention-step 2
$PY studies/chicago_schelling/run_demo.py --no-intervention            # baseline comparison
```
Outputs land in `studies/chicago_schelling/runs/<id>/`: `study.duckdb`, `report.md`, `figures/`.

## Files

- `adapter/engine_seam.py` — `ChicagoEngine` + the CONFIG_DIR/DATA_DIR monkey-patch (the only code that touches `src/`).
- `adapter/providers.py` — `ChicagoEnvironmentProvider`, `ChicagoPopulationProvider`, audience matcher, scheduled-event application.
- `adapter/decision.py` / `metrics.py` — reuse the model's validated phases / metric methods.
- `adapter/fake_llm.py` — `DeterministicLLMClient` for no-token parity tests.
- `adapter/build.py` — `make_chicago_bundles` + `build_chicago_simulator` (one shared engine).
- `reporting.py` — DuckDB → per-step maps + metric timeline + `report.md`.

## Validation

- `tests/test_chicago_parity.py` — adapter vs legacy `model.step()` produce **identical** trajectories (deterministic LLM).
- `tests/test_chicago_intervention.py` — scheduled subway + scenario-1 audience-scoped broadcasts.
- `tests/test_extensibility.py::test_bring_your_own_geojson` — initialize the env from a user-supplied GeoJSON dir.
