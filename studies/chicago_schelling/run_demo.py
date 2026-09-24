"""Live end-to-end demo: small Chicago Schelling under SocioVerse2 with a real LLM.

Demonstrates the full workflow: build P (persistent households) + E (physical + information),
run the longitudinal loop with a step-N subway intervention + audience-scoped policy
broadcasts, persist the panel to DuckDB, and render the time-step report.

    python studies/chicago_schelling/run_demo.py --steps 3 --intervention-step 2
    python studies/chicago_schelling/run_demo.py --no-intervention      # baseline
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from socioverse.schemas import Broadcast, ScheduledEvent, SimulationConfig  # noqa: E402
from studies.chicago_schelling.adapter import (  # noqa: E402
    build_chicago_simulator,
    make_chicago_bundles,
)
from studies.chicago_schelling.adapter.engine_seam import (  # noqa: E402
    CHICAGO_LEGACY_DEFAULT,
    ChicagoEngine,
    chicago_missing,
    default_llm_config,
)
from studies.chicago_schelling.reporting import generate_report  # noqa: E402

MODEL_KWARGS = dict(max_archetypes=241)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--scale", default="small", choices=["small", "middle", "full"])
    ap.add_argument("--intervention-step", type=int, default=2)
    ap.add_argument("--no-intervention", action="store_true")
    ap.add_argument("--out", default=str(HERE / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")))
    args = ap.parse_args()

    missing = chicago_missing()
    if missing:
        raise SystemExit(
            "Chicago legacy model not available (missing: " + ", ".join(missing) + ").\n"
            "Clone the companion repo next to this one and install the chicago extra:\n"
            "  git clone https://github.com/Lishi905/SocioVerse-ABM ../SocioVerse-ABM\n"
            '  pip install -e ".[chicago]"\n'
            "or point SV_CHICAGO_LEGACY at the legacy dir (see .env.example).")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if str(CHICAGO_LEGACY_DEFAULT) not in sys.path:
        sys.path.insert(0, str(CHICAGO_LEGACY_DEFAULT))
    from run_prototype import select_prototype_tracts

    tract_ids = None if args.scale == "full" else select_prototype_tracts(scale=args.scale)

    events: list[ScheduledEvent] = []
    broadcasts: list[Broadcast] = []
    target = None
    if not args.no_intervention:
        # Probe build (no LLM calls) to pick a populous tract for the intervention.
        probe = ChicagoEngine(scale=args.scale, tract_ids=tract_ids, seed=42,
                              model_kwargs=MODEL_KWARGS, llm_config=default_llm_config())
        probe.ensure_built()
        target = Counter(a.tract_id for a in probe.model.agents).most_common(1)[0][0]
        s = args.intervention_step
        events = [ScheduledEvent(
            at_step=s, target_layer="tract_local", op="add", property_name="cta_stations",
            value=2, selector={"geoid_list": [target]},
            note=f"open CTA rail station in tract {target} at step {s}")]
        broadcasts = [
            Broadcast(message_id="A", channel="news", at_step=s, ttl=args.steps, audience="all",
                      content="City announces a major transit expansion improving commute access."),
            Broadcast(message_id="B", channel="ward_notice", at_step=s, ttl=args.steps,
                      audience={"geoid_list": [target]},
                      content="Your neighborhood is getting a new CTA rail station with direct downtown access."),
        ]

    study, env_bundle, pop_bundle = make_chicago_bundles(
        scale=args.scale, scheduled_events=events, broadcasts=broadcasts)
    sim_cfg = SimulationConfig(study_id="chicago_schelling", n_steps=args.steps,
                               decision_ref="chicago.schelling")
    db = out_dir / "study.duckdb"

    def on_step(t, m):
        print(f"  [step {t}] D_bw={m.get('D_black_white', 0):.4f} "
              f"D_hw={m.get('D_hispanic_white', 0):.4f} "
              f"movers={m.get('n_movers', '-')} {m.get('events', '')}", flush=True)

    sim, engine = build_chicago_simulator(
        env_bundle=env_bundle, pop_bundle=pop_bundle, sim_config=sim_cfg, store_path=db,
        scale=args.scale, tract_ids=tract_ids, seed=42, model_kwargs=MODEL_KWARGS,
        llm_config=default_llm_config(), on_step=on_step)

    intervention = "off" if args.no_intervention else f"subway@step{args.intervention_step} in tract {target}"
    print(f"Running Chicago Schelling | scale={args.scale} steps={args.steps} "
          f"agents={len(engine._agent_by_id) if engine.model else '?'} intervention={intervention}",
          flush=True)
    hist = sim.run()

    geojson = CHICAGO_LEGACY_DEFAULT / "processed_data" / "chicago_tracts.geojson"
    report = generate_report(
        db, out_dir, geojson_path=geojson, study_title="Chicago Schelling (SocioVerse2)",
        event_steps=[] if args.no_intervention else [args.intervention_step])
    print("\nTrajectory D_bw:", [round(r.get("D_black_white", 0), 4) for r in hist.rows], flush=True)
    print(f"DuckDB: {db}", flush=True)
    print(f"Report: {report}", flush=True)


if __name__ == "__main__":
    main()
