"""Consumer confidence adapter: wraps ConsumerSim into SocioVerse2."""

from __future__ import annotations

from .build import build_consumer_confidence_simulator, make_consumer_confidence_bundles
from .decision import ConsumerConfidenceDecisionModel
from .engine_seam import ConsumerSimEngine
from .metrics import CONSUMER_CONFIDENCE_METRICS, ConsumerConfidenceMetricCollector
from .providers import ConsumerConfidenceEnvironmentProvider, ConsumerConfidencePopulationProvider

__all__ = [
    "CONSUMER_CONFIDENCE_METRICS",
    "ConsumerSimEngine",
    "ConsumerConfidencePopulationProvider",
    "ConsumerConfidenceEnvironmentProvider",
    "ConsumerConfidenceDecisionModel",
    "ConsumerConfidenceMetricCollector",
    "build_consumer_confidence_simulator",
    "make_consumer_confidence_bundles",
]
