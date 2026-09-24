"""Metrics collector for ConsumerSim confidence forecasts."""

from __future__ import annotations

from typing import Any

from socioverse.abc import MetricCollector
from socioverse.schemas import Action


CONSUMER_CONFIDENCE_METRICS = [
    "region",
    "target_month",
    "as_of",
    "population_size",
    "core_size",
    "raw_score",
    "corrected_score",
    "score_current_finance",
    "score_durable_buying",
    "score_future_finance",
    "score_business_12m",
    "score_business_5y",
    "news_score",
    "indicator_score",
    "combined_score",
    "news_count",
    "indicator_count",
    "correction_residual",
    "correction_adjustment",
]


class ConsumerConfidenceMetricCollector(MetricCollector):
    def __init__(self, engine):
        self.engine = engine

    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        return self.engine.metric_row(t)

    def columns(self) -> list[str]:
        return list(CONSUMER_CONFIDENCE_METRICS)
