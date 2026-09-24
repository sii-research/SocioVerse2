"""SimulationConfig — binds population + environment + decision model + schedule.

Written by `sv-run` (preflight) after the env/population bundles exist. The
`*_ref` strings are resolved against the registry to concrete classes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WarmStartSpec(BaseModel):
    """A **branch**'s replay spec: inherit a parent version's already-run steps instead of
    re-running from step 0. (The class name predates the branch/version vocabulary and is kept
    so manifests and simulation.json files written by earlier versions still load.)

    The engine REPLAYS the parent's stored actions for steps ``1..resume_from`` (no LLM — this
    reproduces the parent trajectory exactly AND rehydrates env state to E_K), then runs
    ``resume_from+1..n_steps`` with real decisions, so only the genuinely new steps spend budget.
    Requires a study whose ``env.apply(actions)`` is a pure function of the passed actions
    (from-scratch / Path-B) and ``interaction_rounds == 1``; legacy-wrap studies (chicago) are
    not supported (their move-intent lives on hidden legacy agents set during decide_batch).
    """

    source_version: str        # parent version id (provenance, shown in the dashboard)
    source_trajectory: str     # path to the parent's versions/<v>/trajectory/study.duckdb
    resume_from: int           # inherit steps 0..resume_from; run real decisions from resume_from+1

    @property
    def fork_step(self) -> int:
        """The first step this branch computes for itself — where it departs from its parent.
        The manifest records the same number as ``fork_step`` on the version entry."""
        return int(self.resume_from) + 1


class SimulationConfig(BaseModel):
    study_id: str
    n_steps: int = 5
    seed: int = 42
    # Set by /sv-iterate when the study is branched from a parent version. None = cold run
    # (a new version, or a branch whose invariant check failed and was downgraded).
    warm_start: WarmStartSpec | None = None

    decision_ref: str                                   # registry key -> DecisionModel subclass
    decision_args: dict[str, Any] = Field(default_factory=dict)

    # registry key -> MetricCollector subclass. Used by the generic Core assembler
    # (engine.build_simulator) for from-scratch studies; legacy-wrap studies that build their
    # own simulator (e.g. chicago) construct the collector directly and may leave this empty.
    collector_ref: str = ""
    collector_args: dict[str, Any] = Field(default_factory=dict)

    # interaction_rounds=1 for Schelling (one move/step); K>1 for HiSim-style message exchange.
    interaction_rounds: int = 1

    engine_args: dict[str, Any] = Field(default_factory=dict)  # memory_window, metric_columns, parallelism
    store_ref: str = "duckdb"                           # registry key -> TrajectoryStore
    store_args: dict[str, Any] = Field(default_factory=dict)
