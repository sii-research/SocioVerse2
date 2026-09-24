"""abm_social_force — Helbing pedestrian evacuation, wrapped via the umbrella.

Continuous-field crowd dynamics; pedestrians that reach the exit leave the simulation
(disappearing agents handled by the umbrella, like sugarscape).
"""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 50, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "social_force",
        study_id="abm_social_force",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Helbing Social Force evacuation (SocioVerse-ABM)",
        research_question="Does the crowd flow toward the exit under social forces, and does an LLM agent reproduce it?",
        hypothesis="Pedestrians steadily close the distance to the exit and begin evacuating.",
        domain="crowd-dynamics",
        tags=["abm", "social_force", "crowd-dynamics", "flow", "umbrella"],
        **overrides,
    )
