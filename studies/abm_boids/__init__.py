"""abm_boids — Reynolds flocking on a continuous field, wrapped via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 30, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "boids",
        study_id="abm_boids",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Reynolds Boids flocking (SocioVerse-ABM)",
        research_question="Does local steering produce global flocking order, and does an LLM agent reproduce it?",
        hypothesis="Polarization (order parameter) rises from a near-random start as a coherent flock forms.",
        domain="collective-behavior",
        tags=["abm", "boids", "collective-behavior", "flow", "umbrella"],
        **overrides,
    )
