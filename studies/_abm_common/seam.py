"""Engine-seam for the SocioVerse-ABM umbrella.

Locates the sibling SocioVerse-ABM project, puts it on sys.path, and loads a task by
name through its own registry. The ABM kernel package is `socioverse_abm` (renamed
from `socioverse` precisely so it does not clash with this repo's own `socioverse`), so this
import is safe. Core never calls this module — only the umbrella providers do.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

# studies/_abm_common/seam.py -> repo root is two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Third-party packages the SocioVerse-ABM kernel and tasks import (the `abm` extra).
ABM_DEPS = ("numpy", "networkx")


def abm_root() -> Path:
    """Locate the SocioVerse-ABM repo root: $SV_ABM_ROOT (process env, else `.env`), else the
    sibling clone ../SocioVerse-ABM next to this repo (https://github.com/Lishi905/SocioVerse-ABM)."""
    from socioverse.external_events import env_setting

    env = env_setting("SV_ABM_ROOT")
    return Path(env) if env else _REPO_ROOT.parent / "SocioVerse-ABM"


def abm_present() -> bool:
    """True when the SocioVerse-ABM checkout is on disk (its kernel + tasks dirs exist)."""
    root = abm_root()
    return (root / "socioverse_abm").is_dir() and (root / "tasks").is_dir()


def abm_missing_deps() -> list[str]:
    """The ABM_DEPS that are not importable in this interpreter."""
    return [m for m in ABM_DEPS if importlib.util.find_spec(m) is None]


def abm_available() -> bool:
    """True when the abm_* studies can run: the SocioVerse-ABM sibling is present AND its
    Python deps (numpy, networkx — `pip install -e ".[abm]"`) are importable.

    A fresh clone with no SV_ABM_ROOT and no sibling checkout has neither. Tests gate on this
    so they skip (not error) when either is missing — the same contract as the chicago
    "legacy not available" skip guard.
    """
    return abm_present() and not abm_missing_deps()


def _ensure_path() -> None:
    import sys
    root = str(abm_root())
    if root not in sys.path:
        sys.path.insert(0, root)


_TASKS_IMPORTED = False


def load_task(name: str):
    """Return the socioverse_abm registry TaskSpec for `name` (importing tasks once)."""
    global _TASKS_IMPORTED
    _ensure_path()
    from socioverse_abm.scenario_engine import registry

    if not _TASKS_IMPORTED:
        importlib.import_module("tasks")          # triggers every task's @register
        _TASKS_IMPORTED = True
    return registry.get(name)


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def task_config(name: str, overrides: dict | None = None, seed: int | None = None) -> dict:
    """The task's default config.yaml, with optional overrides and seed applied."""
    spec = load_task(name)
    model_mod = importlib.import_module(spec.run.__module__)   # tasks/<…>/model.py
    cfg = model_mod.load_config()
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    if seed is not None:
        cfg["seed"] = seed
    return cfg


def seed_decision(spec: Any, seed: int) -> None:
    """Seed the task's rule_f module RNG (if it has one) for deterministic parity."""
    mod = importlib.import_module(spec.rule_f.__module__)
    if hasattr(mod, "seed"):
        mod.seed(seed)


def configure_llm(spec: Any, cfg: dict) -> str | None:
    """Set up the task's LLM behavior function from its config, as the native ``model.run``
    does for llm and hybrid mode: ``llm_f.configure(behavior.llm_model)``, plus
    ``behavior.llm_behavior`` for tasks whose configure accepts it (schelling, civil_violence).

    Returns the model name passed on, or None when the task has no ``configure`` or its config
    names no model (the llm_f module then keeps its own default)."""
    import inspect

    mod = importlib.import_module(spec.llm_f.__module__)
    configure = getattr(mod, "configure", None)
    behavior = (cfg or {}).get("behavior") or {}
    model = behavior.get("llm_model")
    if configure is None or not model:
        return None
    if "llm_behavior" in inspect.signature(configure).parameters:
        configure(model, behavior.get("llm_behavior", "tbf"))
    else:
        configure(model)
    return model
