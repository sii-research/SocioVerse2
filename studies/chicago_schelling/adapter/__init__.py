"""Chicago Schelling adapter: migrates the legacy SegregationModel into SocioVerse2."""

from __future__ import annotations

from .build import build_chicago_simulator, make_chicago_bundles, materialize_chicago_initial
from .decision import SchellingDecisionModel
from .engine_seam import ChicagoEngine, default_llm_config, patched_paths
from .fake_llm import DeterministicLLMClient
from .metrics import SegregationMetricCollector
from .providers import (
    ChicagoEnvironmentProvider,
    ChicagoPopulationProvider,
    chicago_audience_matcher,
)

__all__ = [
    "ChicagoEngine",
    "patched_paths",
    "default_llm_config",
    "ChicagoEnvironmentProvider",
    "ChicagoPopulationProvider",
    "chicago_audience_matcher",
    "SchellingDecisionModel",
    "SegregationMetricCollector",
    "DeterministicLLMClient",
    "build_chicago_simulator",
    "make_chicago_bundles",
    "materialize_chicago_initial",
]
