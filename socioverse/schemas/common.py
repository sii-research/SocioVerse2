"""Common enums and type aliases shared across SocioVerse2 schemas.

The two orthogonal axes of the environment E (Lewin B=f(P,E)) live here:
  - Modality:  physical  vs  information
  - Scope:     macro (broadcast to all)  vs  local (filtered per agent)
A 3rd tag, DynamicsTag, says HOW a layer changes over time.
"""

from __future__ import annotations

from enum import Enum

# --- Persistent identity / time aliases (longitudinal keys) ---
AgentId = str
StepIndex = int


class Modality(str, Enum):
    """First axis of E: what kind of environment a layer represents."""

    PHYSICAL = "physical"          # geography / grid / network
    INFORMATION = "information"    # news / social media / broadcast


class Scope(str, Enum):
    """Second axis of E: how widely a layer is perceived."""

    MACRO = "macro"   # global; broadcast identically to every agent
    LOCAL = "local"   # filtered by agent position / network / vision


class DynamicsTag(str, Enum):
    """How a layer evolves over time."""

    STATIC = "static"           # never changes after t=0
    ENDOGENOUS = "endogenous"   # changes via apply(actions): E_{t+1}=f(E_t,B_t)
    SCHEDULED = "scheduled"     # changes via advance_to(t): exogenous shocks / interventions
