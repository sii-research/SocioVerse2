"""abm_schelling — Schelling segregation, wrapped from SocioVerse-ABM via the umbrella.

A thin study: importing it registers the shared umbrella providers (abm.*); `make_bundles`
just calls the generic factory with this task's name. No per-study adapter code — the
whole behavior lives in SocioVerse-ABM's `tasks/organization/schelling/`.
"""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 12, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "schelling",
        study_id="abm_schelling",
        n_steps=n_steps, seed=seed, mode=mode,
        group_field="group",
        title="Schelling residential segregation (SocioVerse-ABM)",
        research_question="Does mild same-group preference drive macro segregation, and does an LLM agent reproduce the rule?",
        hypothesis="Segregation index rises well above the 50/50 baseline under the homophily rule.",
        domain="segregation",
        tags=["abm", "schelling", "segregation", "organization", "umbrella"],
        **overrides,
    )
