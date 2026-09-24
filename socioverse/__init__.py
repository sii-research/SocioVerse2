"""SocioVerse2: a longitudinal, LLM-native social-simulation runtime.

B = f(P, E): a fixed population pool P (persistent ids) under a dynamic environment E
(two axes: physical/information x macro/local), driven step-by-step so the SAME agents
are tracked over time (panel data) — the differentiator vs cross-sectional platforms.

Public surface:
  socioverse.schemas  — typed inter-skill contracts
  socioverse.abc      — abstract base classes a study implements
  socioverse.engine   — registry + LongitudinalSimulator (P1)
  socioverse.validation.validate_handoff — the strict skill-boundary guard
"""

from __future__ import annotations

__version__ = "0.2.0"

from . import abc, schemas
from .engine.registry import available, register, resolve
from .external_events import (
    ExternalEventsBundle,
    ExternalEventsClient,
    materialize_external_events,
    month_range,
)
from .validation import HandoffError, validate_handoff, write_artifact

__all__ = [
    "__version__",
    "schemas",
    "abc",
    "register",
    "resolve",
    "available",
    "validate_handoff",
    "write_artifact",
    "HandoffError",
    "ExternalEventsClient",
    "ExternalEventsBundle",
    "materialize_external_events",
    "month_range",
]
