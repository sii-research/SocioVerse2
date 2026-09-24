"""Environment E schemas: the two-axis layer system + dynamics channels.

- EnvironmentLayer carries (modality, scope, dynamics) tags — the routing rules
  that EnvironmentProvider.observe_batch uses to assemble each agent's Observation.
- ScheduledEvent = exogenous NUMERIC environment change at a step (subway/crime/income).
- Broadcast / InformationProgram = exogenous INFORMATION content, audience-scoped
  (audience="all" -> macro_information; audience=selector -> local_information).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .common import DynamicsTag, Modality, Scope


class EnvironmentLayer(BaseModel):
    """One tagged slice of the environment. The (modality, scope) pair places it in
    one of the 4 quadrants: macro/local x physical/information."""

    name: str
    modality: Modality
    scope: Scope
    dynamics: DynamicsTag = DynamicsTag.STATIC
    source: str | None = None       # path/URI to backing data (geojson, csv, retriever id)
    schema_ref: str | None = None   # optional id of a payload schema
    description: str = ""


class ScheduledEvent(BaseModel):
    """A numeric, exogenous mutation of a physical layer fired at `at_step`.
    (Reframes one-shot policy geo-modifications as time-scheduled mutations.)"""

    at_step: int
    target_layer: str
    op: Literal["set", "add", "multiply", "add_pct", "replace_source"]
    selector: dict[str, Any] = Field(default_factory=dict)  # provider-interpreted (e.g. TractSelector)
    property_name: str | None = None
    value: Any = None
    note: str = ""


class Broadcast(BaseModel):
    """A piece of information injected into the environment at a step, delivered to a
    scoped audience. audience='all' -> macro_information (everyone); audience=dict
    selector -> local_information (only matching agents)."""

    message_id: str
    content: str
    channel: str = "news"
    at_step: int = 0
    ttl: int = 1                       # number of steps it stays visible (>=1)
    audience: str | dict[str, Any] = "all"
    note: str = ""

    @property
    def is_macro(self) -> bool:
        return self.audience == "all"


class InformationProgram(BaseModel):
    """The full timeline of information broadcasts for a study (scenario 1)."""

    broadcasts: list[Broadcast] = Field(default_factory=list)


class EnvironmentBundle(BaseModel):
    """The validated artifact written by `sv-build-environment`."""

    study_id: str
    layers: list[EnvironmentLayer] = Field(default_factory=list)
    scheduled_events: list[ScheduledEvent] = Field(default_factory=list)
    information_program: InformationProgram = Field(default_factory=InformationProgram)
    provider_ref: str
    provider_args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _events_reference_real_layers(self) -> "EnvironmentBundle":
        names = {layer.name for layer in self.layers}
        for ev in self.scheduled_events:
            if ev.target_layer not in names:
                raise ValueError(
                    f"ScheduledEvent targets unknown layer '{ev.target_layer}'. "
                    f"Declared layers: {sorted(names)}"
                )
        if self.information_program.broadcasts:
            has_info_layer = any(l.modality == Modality.INFORMATION for l in self.layers)
            if not has_info_layer:
                raise ValueError(
                    "InformationProgram has broadcasts but no information-modality layer "
                    "is declared. Add at least one layer with modality='information'."
                )
        return self
