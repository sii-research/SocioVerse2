"""TrajectoryStore + MetricCollector ABCs (the longitudinal panel + metrics)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..schemas.runtime import Action
from ..schemas.trajectory import TrajectoryRecord


class TrajectoryStore(ABC):
    """Database-like store for panel rows, metrics, events, and messages.

    Implemented over DuckDB (default) so the same file supports later real-time
    interactive querying via SQL.
    """

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def record(self, records: list[TrajectoryRecord]) -> None:
        """Append panel rows (one per agent per step)."""

    @abstractmethod
    def record_metrics(self, row: dict[str, Any]) -> None:
        """Append one per-step aggregate metrics row (must contain 'step')."""

    def record_events(self, step: int, notes: list[str]) -> None:
        """Optional: log fired scheduled events / activated broadcasts at a step."""

    def record_messages(self, messages: list[dict[str, Any]]) -> None:
        """Optional: log inter-agent messages (scenario 2)."""

    @abstractmethod
    def finalize(self) -> None:
        """Flush, export parquet, close."""


class MetricCollector(ABC):
    @abstractmethod
    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        """Return a flat per-step metrics dict (the collector sets/overrides 'step')."""

    def columns(self) -> list[str]:
        """Declared metric column names (contract for the reporter). Optional."""
        return []
