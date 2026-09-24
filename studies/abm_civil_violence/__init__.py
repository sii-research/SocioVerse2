"""abm_civil_violence — Epstein civil violence, wrapped via the umbrella.

Citizens may rebel; cops arrest active rebels who then sit in jail (disappearing from
the grid until released). The umbrella handles the shrinking active set against the runtime's
fixed persona pool.
"""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 30, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "civil_violence",
        study_id="abm_civil_violence",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Epstein civil violence (SocioVerse-ABM)",
        research_question="Do bursts of rebellion erupt under low legitimacy, and does an LLM agent reproduce the rule?",
        hypothesis="Rebellion is punctuated: long quiet spells broken by sudden active peaks, with arrests filling jail.",
        domain="collective-action",
        tags=["abm", "civil_violence", "collective-action", "organization", "umbrella"],
        **overrides,
    )
