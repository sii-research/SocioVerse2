"""StudySpec — the top-level contract produced from a user query by `sv-init`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StudySpec(BaseModel):
    """One study = one research question over a fixed population and a dynamic environment.

    `study_type=longitudinal` is the SocioVerse2 differentiator: the same
    persistent population is tracked across n_steps (panel data), not re-sampled
    per round.
    """

    study_id: str
    title: str = ""
    research_question: str = ""
    hypothesis: str = ""
    # Optional per-language variants of the three display fields above, keyed by BCP-47-ish
    # short codes ("zh" / "en"). The dashboard picks the viewer's language and falls back to
    # the plain field; absent on older studies, so both directions stay compatible.
    title_i18n: dict[str, str] = Field(default_factory=dict)
    research_question_i18n: dict[str, str] = Field(default_factory=dict)
    hypothesis_i18n: dict[str, str] = Field(default_factory=dict)
    study_type: Literal["longitudinal", "cross_sectional"] = "longitudinal"

    n_steps: int = 5
    seed: int = 42
    # What ONE step means in the real world, so a trajectory reads as time, not abstract ticks.
    # `time_unit`: the wall-clock a step advances — "day"/"week"/"month"/"quarter"/"year", or
    # "abstract" when no calendar mapping fits (the step is just a decision round). `step_meaning`:
    # one human line tying a step to the research question (e.g. "each step = one monthly consumption-decision cycle").
    # sv-build-model sets these while modelling the loop; the dashboard shows them on the run card.
    time_unit: str = "abstract"
    step_meaning: str = ""
    # The 1-3 per-agent state attributes MOST tied to the research question (subset of the
    # panel state keys). The dashboard's agent list shows them beside each agent id, so a
    # glance over the roster reads as "who stands where" on the study's core variable.
    # sv-build-population sets these when materializing the pool.
    key_attributes: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    # One-line human meaning per metric (what it measures + unit/direction), keyed by the
    # names in `metrics`. Shown on the dashboard's sv-build-model / sv-run cards and as
    # timeline-legend tooltips — a metric curve is unreadable without its definition.
    metric_descriptions: dict[str, str] = Field(default_factory=dict)
    # The 3–5 metrics worth WATCHING over time (subset of `metrics`) — the dashboard's
    # metric timeline plots only these, so bookkeeping/derived metrics don't drown the
    # story. Empty → the timeline falls back to the first five of `metrics`.
    display_metrics: list[str] = Field(default_factory=list)
    # Optional: for adapter studies whose run happens in an external/heavy pipeline
    # (e.g. a MARL trainer), a short note the dashboard shows on the sv-run card
    # telling users how to run it (e.g. locally, with the external pipeline) instead of in the workbench.
    run_note: dict[str, str] = Field(default_factory=dict)   # {zh, en}

    # Relative artifact paths inside the study workspace (strict-contract handoffs).
    environment_ref: str = "environment/environment.json"
    population_ref: str = "population/population.json"
    simulation_ref: str = "simulation/simulation.json"
    resources_ref: str | None = "resources.json"

    # --- Discovery / catalog metadata ---------------------------------------------------
    # These let `sv-init` Step 0 route a new query: it globs every studies/*/study.yaml
    # (see skills.sv_workspace.discover_studies) and matches against these fields to decide
    # Path A (reuse/adjust an existing study) vs Path B (build a new study from Core).
    # Fill them when authoring a study so future routing can find it. All optional.
    domain: str = ""                                    # primary domain, e.g. "urban-segregation"
    tags: list[str] = Field(default_factory=list)       # e.g. ["ABM", "Schelling", "geography"]
    # Wrapped legacy engine (path or name), or "from_scratch" for a Core-native study, or "" if N/A.
    legacy_simulator: str = ""
    provider_refs: list[str] = Field(default_factory=list)  # registry keys this study registers
    # What you can vary by editing artifacts only (no code) — the Path-A "adjustable" surface.
    adjustable_params: list[str] = Field(default_factory=list)
    status: str = "draft"               # conventional: "draft" | "demo-only" | "parity-tested"
    maintainer: str = ""                # who adapted / owns this study

    # --- Reference / teaching metadata (what routing + build stages copy) ----------------
    # `demonstrates`: which reusable patterns this study shows — controlled kebab-case vocab,
    # matched by exact string (extend deliberately): legacy-seam | from-scratch-core |
    # external-events | real-user-pool | cross-sectional-survey | branch-replay |
    # multi-round-messaging | geo-spatial | policy-intervention | info-broadcast.
    # `reference: true` marks a read-only baseline: sv-init may FORK it, build skills may READ
    # it as a template, nothing edits it in place. The flag replaces hard-coded template names
    # in skill text, so the shipped demo set can change without touching the skills.
    demonstrates: list[str] = Field(default_factory=list)
    teaches: str = ""                   # one line: what you'd copy this study to learn
    reference: bool = False

    # --- Availability metadata (what a fresh clone needs before this study can run) --------
    # `requires`: what must be present besides this repo, e.g. "sibling:SocioVerse-ABM" (a
    # companion repo cloned next to this one, or located via its SV_*_ROOT variable),
    # "extra:abm" (the Python packages its seam imports, `pip install -e ".[abm]"`) or
    # "legacy:chicago" (the legacy Chicago model data, located as the chicago seam does).
    # `catalog_view()` resolves each entry and reports `available` / `missing`; sv-init only
    # offers Path-A forks and runs of available studies. None = nothing extra needed.
    # `rerunnable: false` marks an imported reference (a published trajectory brought in by a
    # script, not produced by this workbench's loop): viewable and usable as a template, but
    # never forked or re-run as-is.
    requires: list[str] | None = None
    rerunnable: bool = True

    created_by: str = "sv-init"
