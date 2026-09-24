"""SegregationMetricCollector — reuses the model's metric methods; manages the
len(metrics_history) step-counter coupling so the 3-step cascade stays in lockstep
with legacy (risk #4 in the plan)."""

from __future__ import annotations

from typing import Any

from socioverse.abc import MetricCollector
from socioverse.schemas import Action


class SegregationMetricCollector(MetricCollector):
    def __init__(self, engine):
        self.engine = engine

    def collect(self, env, actions: list[Action], t: int) -> dict[str, Any]:
        m = self.engine.model
        if t == 0:
            # The model's __init__ already appended the step-0 (initial-state) metrics.
            # Return it verbatim and DO NOT append again, so len(metrics_history) stays at 1
            # and the first move-step sees current_step==1 exactly like legacy.
            return dict(m.metrics_history[0]) if m.metrics_history else {}

        metrics = m._compute_metrics()
        movers = [a for a in m.agents if a.moved_this_step]
        n_agents = len(list(m.agents))
        total_pop = sum(a.pop_count for a in m.agents) or 1
        metrics["n_movers"] = len(movers)
        metrics["pct_movers"] = len(movers) / n_agents if n_agents else 0
        metrics["pop_moved"] = sum(a.pop_count for a in movers)
        metrics["pct_pop_moved"] = metrics["pop_moved"] / total_pop

        prev = getattr(env, "_prev_race_df", None)
        if prev is not None:
            metrics.update(m._compute_direction_metrics(prev, movers))

        # Advance the model's own history so the cascade modulo (current_step % 3) and
        # any len()-based logic stay identical to legacy. step == len before append.
        metrics["step"] = len(m.metrics_history)
        m.metrics_history.append(metrics)
        return metrics

    def columns(self) -> list[str]:
        m = self.engine.model
        if m is not None and m.metrics_history:
            return list(m.metrics_history[0].keys())
        return []
