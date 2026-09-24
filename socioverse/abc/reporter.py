"""Reporter ABC — turns the trajectory store into figures + report.md."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.study import StudySpec
from ..schemas.trajectory import MetricsHistory


class Reporter(ABC):
    @abstractmethod
    def render(
        self,
        study: StudySpec,
        metrics: MetricsHistory,
        store_path: Path,
        out_dir: Path,
    ) -> None:
        """Read the (DuckDB) store + metrics and write figures + report.md to out_dir."""
