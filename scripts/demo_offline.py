#!/usr/bin/env python3
"""Run the opinion_diffusion template end to end, as a local demo study, and render its report.

The shipped reference study ``studies/opinion_diffusion`` is never written to. The script
forks it into a local scratch study, ``studies/opinion_diffusion_demo`` (gitignored like every
study you create), and runs and reports there, so the dashboard shows the demo as a study of
its own whose tables, curves and report all come from the same run.

By default this needs no API key and makes no network call: the forked artifacts are
validated, the decision model runs with ``llm_kind="scripted"`` (the deterministic
bounded-confidence rule), the run is written to a DuckDB store, and the report is rendered
from that store, in English.

    python scripts/demo_offline.py                 # offline, about a second
    python scripts/demo_offline.py --llm openai    # the same study on a real LLM (12 agents x 4 steps)
    python scripts/demo_offline.py --llm openai --prompt-lang en   # ... with the English prompt

``--llm openai`` needs the ``llm`` extra (``pip install -e ".[llm]"``) and ``SV_LLM_API_KEY``;
``SV_LLM_BASE_URL`` (any OpenAI-compatible endpoint, default the official API) and
``SV_LLM_MODEL`` are optional. They are read from the environment or from a ``.env`` file,
with the same lookup as the runtime (see .env.example). The endpoint is probed once before
the run starts.

Outputs, all inside ``studies/opinion_diffusion_demo/`` (the places ``/sv-run`` and
``/sv-report`` write to):

    trajectory/study.duckdb             panel, metrics and events tables
    trajectory/metrics_history.json     per-step metrics
    reports/report.md                   the rendered report, and its figures in reports/figures/

Each run starts the demo study afresh from the reference study (a previous demo run, and
anything changed in it, is replaced). The script refuses to replace a
``studies/opinion_diffusion_demo`` that it did not create. Rendering the report needs
matplotlib (the ``viz`` extra); ``--no-report`` skips it. ``--report-lang zh`` (or
``SV_REPORT_LANG=zh``) renders the report in Chinese, like the shipped reference report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDIES_ROOT = REPO_ROOT / "studies"
SOURCE_ID = "opinion_diffusion"
DEMO_ID = "opinion_diffusion_demo"
# created_by of the demo study: marks it as this script's (safe to replace) and, through the
# "fork of <id>" form, shows the dashboard where it came from.
DEMO_MARK = f"scripts/demo_offline.py (fork of {SOURCE_ID})"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_env_files() -> None:
    """Fill SV_LLM_* (and friends) from the documented .env lookup: $SV_HOME/.env, ./.env,
    then the repo root; the process environment wins and empty values count as unset."""
    from socioverse.external_events import _load_dotenv

    _load_dotenv()


def _probe_llm(model: str) -> None:
    """One tiny completion through the configured endpoint; exit with a hint if it fails."""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit('--llm openai needs the openai client: pip install -e ".[llm]"')
    key = os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("--llm openai needs SV_LLM_API_KEY (copy .env.example to .env and set it, "
                 "or export it in your shell)")
    base_url = os.environ.get("SV_LLM_BASE_URL") or "https://api.openai.com/v1"
    try:
        OpenAI(api_key=key, base_url=base_url).chat.completions.create(
            model=model, max_tokens=4, messages=[{"role": "user", "content": "Reply with OK."}])
    except Exception as exc:  # noqa: BLE001 - relay whatever the provider said
        sys.exit(f"LLM probe failed ({base_url}, model {model}): {exc}")
    print(f"LLM endpoint OK: {base_url} (model {model})")


def _base_title(title: str) -> str:
    """The title without a trailing parenthetical such as "(from-scratch template)"."""
    return re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", title) or title


def fork_demo_study(studies_root: Path = STUDIES_ROOT) -> Path:
    """(Re)create ``<studies_root>/opinion_diffusion_demo`` as a fresh fork of the reference
    study: its own study_id, ``reference: false``, status ``local-demo``. Returns its path."""
    from skills.sv_workspace import (
        fork_study,
        init_manifest,
        load_study_yaml,
        save_study_yaml,
        study_paths,
    )

    dst = studies_root / DEMO_ID
    if dst.exists():
        try:
            spec = json.loads((dst / "study.yaml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            spec = {}
        ours = (spec.get("status") == "local-demo"
                and str(spec.get("created_by", "")).endswith(f"(fork of {SOURCE_ID})"))
        if not ours:
            sys.exit(f"{dst} exists and was not created by this script; move it away first.")
        shutil.rmtree(dst)

    fork = fork_study(studies_root, SOURCE_ID, DEMO_ID, status="local-demo")
    src_roster = studies_root / SOURCE_ID / "population" / "roster.jsonl"
    if src_roster.exists():                     # the materialized t=0 agents, for the dashboard
        shutil.copy2(src_roster, fork / "population" / "roster.jsonl")
    # fork_study rewrites the copied artifacts' study_id, which gives them a fresh mtime. Give
    # them back the source's mtime so they are always older than the fork's study.yaml, and the
    # dashboard consistently marks the stages this demo did not build as forked.
    src_paths, dst_paths = study_paths(studies_root / SOURCE_ID), study_paths(fork)
    for key in ("resources", "environment", "population", "roster", "simulation", "grounding"):
        if src_paths[key].exists() and dst_paths[key].exists():
            st = src_paths[key].stat()
            os.utime(dst_paths[key], ns=(st.st_atime_ns, st.st_mtime_ns))

    spec = load_study_yaml(fork / "study.yaml")
    spec.created_by = DEMO_MARK
    spec.title = f"{_base_title(spec.title)} (local demo)"
    if spec.title_i18n.get("en"):
        spec.title_i18n["en"] = f"{_base_title(spec.title_i18n['en'])} (local demo)"
    if spec.title_i18n.get("zh"):
        spec.title_i18n["zh"] = f"{_base_title(spec.title_i18n['zh'])}（本地演示）"
    spec.tags = [*spec.tags, "local-demo"]
    spec.demonstrates = []
    spec.teaches = (f"a local demo copy of {SOURCE_ID}, made by scripts/demo_offline.py and "
                    f"replaced on its next run; fork {SOURCE_ID} to start a study of your own")
    save_study_yaml(fork / "study.yaml", spec)
    init_manifest(fork, note="demo run of scripts/demo_offline.py")
    return fork


def main(argv: list[str] | None = None, *, studies_root: Path | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the opinion_diffusion template as a local demo study and render its report.")
    ap.add_argument("--llm", choices=["scripted", "openai"], default="scripted",
                    help="decision mode: the deterministic rule (default, offline) or a real LLM")
    ap.add_argument("--model", default=None,
                    help="LLM model for --llm openai (default: $SV_LLM_MODEL, else the study's "
                         "simulation.json setting)")
    ap.add_argument("--prompt-lang", choices=["en", "zh"], default=None,
                    help="language of the LLM prompt for --llm openai (default: the study's "
                         "simulation.json setting, which is zh for the shipped run)")
    ap.add_argument("--report-lang", choices=["en", "zh"], default=None,
                    help="language of the rendered report (default: $SV_REPORT_LANG, else en)")
    ap.add_argument("--no-report", action="store_true", help="skip rendering the report")
    args = ap.parse_args(argv)
    studies_root = Path(studies_root) if studies_root is not None else STUDIES_ROOT

    import studies.opinion_diffusion  # noqa: F401  (registers the opinion.* providers)
    from skills.sv_workspace import study_paths
    from socioverse.engine import build_simulator
    from socioverse.schemas import EnvironmentBundle, PopulationBundle, SimulationConfig, StudySpec
    from socioverse.validation import validate_handoff, write_artifact

    model = None
    if args.llm == "openai":                    # check the endpoint before touching studies/
        _load_env_files()
        src_sim = validate_handoff(study_paths(studies_root / SOURCE_ID)["simulation"],
                                   SimulationConfig)
        model = (args.model or os.environ.get("SV_LLM_MODEL")
                 or src_sim.decision_args.get("model", "gpt-4o"))
        _probe_llm(model)

    demo_dir = fork_demo_study(studies_root)
    p = study_paths(demo_dir)
    study = validate_handoff(p["study"], StudySpec)
    env_b = validate_handoff(p["environment"], EnvironmentBundle)
    pop_b = validate_handoff(p["population"], PopulationBundle)
    sim_c = validate_handoff(p["simulation"], SimulationConfig)

    decision_args = {**sim_c.decision_args, "llm_kind": args.llm}
    run_mode = ""
    if args.llm == "openai":
        if args.prompt_lang:
            decision_args["prompt_lang"] = args.prompt_lang
        decision_args["model"] = model
        run_mode = f"LLM ({model}, llm_kind=openai, prompt_lang={decision_args.get('prompt_lang', 'en')})"
    sim_c.decision_args = decision_args
    # The demo study records how it actually ran, so its simulation.json matches its trajectory.
    write_artifact(p["simulation"], sim_c)

    store_path = p["duckdb"]
    store_path.parent.mkdir(parents=True, exist_ok=True)
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=store_path)

    sources: Counter[str] = Counter()
    decide = sim.decision.decide_batch

    def counted(obs, memories):
        actions = decide(obs, memories)
        sources.update(a.source for a in actions)
        return actions

    sim.decision.decide_batch = counted

    print(f"Running {study.study_id} (a local copy of {SOURCE_ID}): "
          f"{pop_b.provider_args.get('n_agents')} agents, {sim_c.n_steps} steps, "
          f"llm_kind={args.llm}")
    t0 = time.perf_counter()
    hist = sim.run()
    elapsed = time.perf_counter() - t0
    write_artifact(p["metrics"], hist)
    missing = hist.covers(study.metrics)
    if missing:
        sys.exit(f"run finished but metrics are missing: {missing}")

    print(f"\n{'step':>4}  {'mean_opinion':>12}  {'opinion_std':>11}  {'frac_above_0_5':>14}")
    for row in hist.rows:
        print(f"{row['step']:>4}  {row['mean_opinion']:>12.3f}  {row['opinion_std']:>11.3f}  "
              f"{row['frac_above_0_5']:>14.2f}")
    print(f"\nDecisions by source: {dict(sources)}  ({elapsed:.1f} s)")
    if args.llm == "openai" and sources.get("fallback"):
        print("Note: 'fallback' decisions are LLM replies that did not parse and used the rule.")
    print(f"Study: {demo_dir}")
    print(f"Trajectory store: {store_path}")

    if not args.no_report:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            print('Report skipped: install matplotlib with pip install -e ".[viz]"')
            return 0
        from studies.opinion_diffusion.reporting import cjk_font, generate_report, resolve_lang

        lang = resolve_lang(args.report_lang)
        if lang == "zh" and cjk_font() is None:
            # matplotlib would warn once per missing glyph; say it once, with the fix, instead.
            warnings.filterwarnings("ignore", message=r"Glyph .* missing from")
            print("Note: matplotlib has no CJK font, so the Chinese figure labels render as boxes; "
                  "install one (e.g. apt install fonts-noto-cjk) and re-run.")
        title = (study.title_i18n.get("zh") or study.title) if lang == "zh" else study.title
        report = generate_report(
            store_path, p["report"].parent, study_dir=demo_dir, study_title=title,
            run_mode=run_mode,
            version="" if run_mode else "offline demo, llm_kind=scripted",
            lang=lang, llm_kind=args.llm,
        )
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
