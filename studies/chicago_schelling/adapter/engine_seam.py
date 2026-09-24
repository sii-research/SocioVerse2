"""ChicagoEngine — owns the legacy SegregationModel and the monkey-patch seam.

This is the ONLY place that touches the legacy Chicago model code, which is vendored in
the SocioVerse-ABM companion repo under tasks/organization/chicago_segregation/legacy/
(https://github.com/Lishi905/SocioVerse-ABM, cloned as a sibling of this repo). It lifts
the legacy CONFIG_DIR/DATA_DIR monkey-patch, builds the validated SegregationModel once,
assigns deterministic persistent agent ids, and (optionally) wraps the env's
LLM-description method to splice in active information broadcasts.

Zero edits to the legacy src/ are required.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Repo root (studies/chicago_schelling/adapter/engine_seam.py -> three parents up) — used for
# .env and to find the sibling SocioVerse-ABM clone.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Where the legacy model lives inside a SocioVerse-ABM checkout.
_LEGACY_SUBDIR = Path("tasks") / "organization" / "chicago_segregation" / "legacy"

# Third-party packages the legacy model imports (the `chicago` extra).
CHICAGO_DEPS = ("geopandas", "mesa", "openai")


def _load_dotenv(root: Path | None = None) -> None:
    """Hydrate SV_LLM_* from `.env` without overriding the process env: `root/.env` when
    given, else the documented lookup order ($SV_HOME/.env, ./.env, then the repo root)."""
    from socioverse.external_events import _load_dotenv as load

    load(root)


def resolve_chicago_legacy() -> Path:
    """Locate the legacy Chicago code (a dir containing src/ + config/ + processed_data/).

    Priority (each variable from the process env, else from `.env`):
      1. $SV_CHICAGO_LEGACY — the legacy dir itself (explicit override);
      2. $SV_ABM_ROOT/tasks/organization/chicago_segregation/legacy — SV_ABM_ROOT is the
         SocioVerse-ABM repo root, the same meaning it has in studies/_abm_common/seam.py;
      3. ../SocioVerse-ABM/tasks/organization/chicago_segregation/legacy — the recommended
         sibling-clone layout.
    """
    from socioverse.external_events import env_setting   # process env, else .env

    env = env_setting("SV_CHICAGO_LEGACY")
    if env:
        return Path(env)
    abm = env_setting("SV_ABM_ROOT")
    abm_root = Path(abm) if abm else _REPO_ROOT.parent / "SocioVerse-ABM"
    return abm_root / _LEGACY_SUBDIR


# Default location of the legacy Chicago project (the data + validated dynamics).
CHICAGO_LEGACY_DEFAULT = resolve_chicago_legacy()


def chicago_data_present(legacy: Path | None = None) -> bool:
    """True when the legacy Chicago model's census data is on disk at `legacy`
    (default: CHICAGO_LEGACY_DEFAULT)."""
    root = Path(legacy) if legacy is not None else CHICAGO_LEGACY_DEFAULT
    return (root / "processed_data" / "chicago_tracts.geojson").exists()


def chicago_missing_deps() -> list[str]:
    """The CHICAGO_DEPS that are not importable in this interpreter."""
    return [m for m in CHICAGO_DEPS if importlib.util.find_spec(m) is None]


def chicago_missing(legacy: Path | None = None) -> list[str]:
    """What is missing for a Chicago run: the legacy data file and/or the CHICAGO_DEPS
    packages. Empty list = ready. Tests skip on a non-empty list instead of failing."""
    root = Path(legacy) if legacy is not None else CHICAGO_LEGACY_DEFAULT
    out = [] if chicago_data_present(root) else [f"legacy data ({root})"]
    return out + chicago_missing_deps()


def chicago_available(legacy: Path | None = None) -> bool:
    return not chicago_missing(legacy)


@contextlib.contextmanager
def patched_paths(abm_root: Path, config_dir: Path | None, data_dir: Path | None):
    """Temporarily point src.model.CONFIG_DIR/DATA_DIR at workspace dirs (or leave
    them at the originals when None). The legacy model reads its inputs through these globals."""
    if str(abm_root) not in sys.path:
        sys.path.insert(0, str(abm_root))
    import src.model as _m

    old_c, old_d = _m.CONFIG_DIR, _m.DATA_DIR
    if config_dir is not None:
        _m.CONFIG_DIR = Path(config_dir)
    if data_dir is not None:
        _m.DATA_DIR = Path(data_dir)
    try:
        yield
    finally:
        _m.CONFIG_DIR, _m.DATA_DIR = old_c, old_d


def default_llm_config(model: str | None = None, **overrides: Any):
    """Build the live LLM config from the ENVIRONMENT (never hard-code secrets).

    Required: SV_LLM_API_KEY (or OPENAI_API_KEY). Optional: SV_LLM_BASE_URL, SV_LLM_MODEL.
    Values can live in the repo-root .env (gitignored) — see .env.example.
    """
    from src.llm_client import LLMConfig

    _load_dotenv()
    api_key = os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No LLM API key found. Set SV_LLM_API_KEY (or OPENAI_API_KEY) in your "
            "environment or in the repo-root .env (gitignored). See .env.example. "
            "For a no-token run, pass llm_client=DeterministicLLMClient() instead."
        )
    params = dict(
        api_key=api_key,
        base_url=os.environ.get("SV_LLM_BASE_URL", "https://api.openai.com/v1"),
        model=model or os.environ.get("SV_LLM_MODEL", "gpt-4o-2024-08-06"),
        temperature=0.7,
        max_tokens=512,
    )
    params.update(overrides)
    return LLMConfig(**params)


class ChicagoEngine:
    """Holds the SegregationModel + the agent-id index, shared by all four adapters."""

    def __init__(
        self,
        *,
        scale: str = "small",
        tract_ids: list[str] | None = None,
        init_mode: str = "census",
        seed: int = 42,
        model_kwargs: dict | None = None,
        llm_client: Any = None,        # injected fake client (parity) — swapped in after build
        llm_config: Any = None,        # real LLMConfig (live runs)
        abm_root: str | Path | None = None,
        config_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        information_env: Any = None,   # env_layers.InformationEnvironment (info injection)
    ):
        self.scale = scale
        self._tract_ids_arg = tract_ids
        self.init_mode = init_mode
        self.seed = seed
        self.model_kwargs = dict(model_kwargs or {})
        self._llm_client = llm_client
        self._llm_config = llm_config
        self.abm_root = Path(abm_root) if abm_root else CHICAGO_LEGACY_DEFAULT
        self.config_dir = Path(config_dir) if config_dir else None
        self.data_dir = Path(data_dir) if data_dir else None
        self.information_env = information_env

        self.model = None
        self._agent_by_id: dict[str, Any] = {}

    # --- build (idempotent so env.reset / pop.build can both trigger it) ---
    def ensure_built(self):
        if self.model is not None:
            return self.model
        if str(self.abm_root) not in sys.path:
            sys.path.insert(0, str(self.abm_root))

        tract_ids = self._resolve_tract_ids()
        with patched_paths(self.abm_root, self.config_dir, self.data_dir):
            from src.model import SegregationModel

            if self._llm_config is not None:
                llm_config = self._llm_config
            elif self._llm_client is not None:
                # A fake client is swapped in below, so no real key is needed to construct.
                from src.llm_client import LLMConfig

                llm_config = LLMConfig(api_key="unused-with-fake-client",
                                       base_url="http://localhost", model="fake")
            else:
                llm_config = default_llm_config()
            self.model = SegregationModel(
                llm_config=llm_config,
                tract_ids=tract_ids,
                seed=self.seed,
                init_mode=self.init_mode,
                **self.model_kwargs,
            )
        if self._llm_client is not None:
            # __init__ never calls the LLM (assess/evaluate happen in step()), so
            # swapping the client in after construction is safe and total.
            self.model.llm = self._llm_client

        self._index_agents()
        self._install_info_wrap()
        return self.model

    def _resolve_tract_ids(self) -> list[str] | None:
        if self._tract_ids_arg is not None:
            return list(self._tract_ids_arg)
        if self.scale == "full":
            return None
        from run_prototype import select_prototype_tracts

        return select_prototype_tracts(scale=self.scale)

    def _index_agents(self) -> None:
        """Assign deterministic persistent ids: chi-{archetype}-{init_tract}-{clone_idx}.
        Order is creation order (deterministic given seed), so ids are stable across
        legacy/adapter builds and resumes."""
        self._agent_by_id = {}
        clone = defaultdict(int)
        for agent in self.model.agents:
            key = (agent.archetype_key, agent.tract_id)
            idx = clone[key]
            clone[key] += 1
            aid = f"chi-{agent.archetype_key}-{agent.tract_id}-{idx}"
            agent._sv_id = aid
            self._agent_by_id[aid] = agent

    def agent(self, agent_id: str):
        return self._agent_by_id[agent_id]

    # --- information injection (P4) ---
    def _install_info_wrap(self) -> None:
        """Wrap describe_tract_with_context_for_llm at the instance level so the reused
        LLM phases naturally read active broadcasts. No src edit; same philosophy as the
        CONFIG_DIR monkey-patch."""
        if self.information_env is None:
            return
        env = self.model.environment
        if getattr(env, "_sv_info_wrapped", False):
            return
        orig = env.describe_tract_with_context_for_llm
        info_env = self.information_env
        ctx_fn = self.tract_ctx

        def wrapped(geoid, *args, **kwargs):
            base = orig(geoid, *args, **kwargs)
            lines = info_env.rendered_lines(ctx_fn(geoid))
            if lines:
                return base + "\n  Recent news / notices:\n    " + "\n    ".join(lines)
            return base

        env.describe_tract_with_context_for_llm = wrapped
        env._sv_info_wrapped = True

    def tract_ctx(self, geoid: str) -> dict[str, Any]:
        """Audience-matching context for a tract (used by broadcast selectors)."""
        env = self.model.environment
        try:
            row = env.gdf.loc[geoid]
            info = env.get_tract_info(geoid)
            race_cols = ["nh_white", "nh_black", "nh_asian", "hispanic", "nh_other"]
            dom = max(race_cols, key=lambda r: info.get(f"pct_{r}", 0.0))
            dom_short = {"nh_white": "white", "nh_black": "black", "nh_asian": "asian",
                         "hispanic": "hispanic", "nh_other": "other"}[dom]
            return {
                "tract_id": geoid,
                "geoid": geoid,
                "community_area": int(row.get("community_area_num", -1)),
                "dominant_race": dom_short if info.get(f"pct_{dom}", 0) >= 50 else None,
                "hardship": float(row.get("hardship_index", 0) or 0),
                "income": float(row.get("per_capita_income", 0) or 0),
            }
        except Exception:
            return {"tract_id": geoid, "geoid": geoid}
