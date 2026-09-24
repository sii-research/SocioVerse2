"""SocioVerse2 typed contracts (pure pydantic, no heavy deps).

These are the artifacts that pass between workflow skills. Every skill boundary is
guarded by socioverse.validation.validate_handoff against one of these models.
"""

from __future__ import annotations

from .common import AgentId, DynamicsTag, Modality, Scope, StepIndex
from .environment import (
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    ScheduledEvent,
)
from .population import (
    InteractionStructure,
    Persona,
    PopulationBundle,
    PropagationMode,
)
from .resources import DatasetDecl, McpServerDecl, ResourceManifest, ToolDecl
from .runtime import Action, Observation
from .simulation import SimulationConfig, WarmStartSpec
from .study import StudySpec
from .trajectory import MetricsHistory, TrajectoryRecord

__all__ = [
    "AgentId",
    "StepIndex",
    "Modality",
    "Scope",
    "DynamicsTag",
    "StudySpec",
    "EnvironmentLayer",
    "ScheduledEvent",
    "Broadcast",
    "InformationProgram",
    "EnvironmentBundle",
    "Persona",
    "InteractionStructure",
    "PropagationMode",
    "PopulationBundle",
    "Observation",
    "Action",
    "SimulationConfig",
    "WarmStartSpec",
    "TrajectoryRecord",
    "MetricsHistory",
    "ResourceManifest",
    "McpServerDecl",
    "DatasetDecl",
    "ToolDecl",
]
