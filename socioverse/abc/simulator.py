"""Simulator ABC — the longitudinal driver."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas.trajectory import MetricsHistory


class Simulator(ABC):
    @abstractmethod
    def run(self) -> MetricsHistory:
        """Execute the E_t -> B_t -> E_{t+1} loop over the study horizon and return
        the per-step metrics history. Side effect: writes the panel/metrics store."""
