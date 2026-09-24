"""Trajectory + metrics output contracts (the longitudinal panel data)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrajectoryRecord(BaseModel):
    """One panel row. (agent_id, step) is the longitudinal primary key."""

    agent_id: str
    step: int
    state: dict[str, Any] = Field(default_factory=dict)   # tract_id, satisfaction, ...
    action_kind: str | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)


class MetricsHistory(BaseModel):
    """Per-step aggregate metrics; one flat dict per step (must contain 'step')."""

    study_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    schema_columns: list[str] = Field(default_factory=list)

    def covers(self, required: list[str]) -> list[str]:
        """Return required metric names NOT present in schema_columns (contract check)."""
        present = set(self.schema_columns)
        return [m for m in required if m not in present]
