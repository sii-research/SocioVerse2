"""abm_sugarscape — Epstein-Axtell wealth dynamics, wrapped via the umbrella.

Citizens can starve and leave the grid; the umbrella returns an empty Observation for
a departed agent and the decision model skips it, so the runtime's fixed persona pool stays
consistent while the active set shrinks.
"""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 30, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "sugarscape",
        study_id="abm_sugarscape",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Sugarscape wealth dynamics (SocioVerse-ABM)",
        research_question="Does foraging on an uneven sugar field produce wealth inequality, and does an LLM agent reproduce it?",
        hypothesis="Survivors concentrate wealth (Gini rises) while low-vision/high-metabolism agents starve.",
        domain="economics",
        tags=["abm", "sugarscape", "economics", "market", "umbrella"],
        **overrides,
    )
