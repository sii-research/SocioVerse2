"""Abstract base classes — the strict interface layer.

A study migrates into SocioVerse2 by implementing (at minimum):
  EnvironmentProvider, PopulationProvider, DecisionModel, MetricCollector.
The engine supplies Simulator + TrajectoryStore; Reporter + MessageBus are optional.
"""

from __future__ import annotations

from .decision import DecisionModel
from .environment import EnvironmentProvider
from .messaging import MessageBus
from .population import PopulationProvider
from .reporter import Reporter
from .simulator import Simulator
from .trajectory import MetricCollector, TrajectoryStore

__all__ = [
    "EnvironmentProvider",
    "PopulationProvider",
    "DecisionModel",
    "MetricCollector",
    "TrajectoryStore",
    "Simulator",
    "Reporter",
    "MessageBus",
]
