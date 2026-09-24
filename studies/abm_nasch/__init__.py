"""abm_nasch — Nagel-Schreckenberg traffic, wrapped from SocioVerse-ABM via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 20, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "nasch",
        study_id="abm_nasch",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Nagel-Schreckenberg single-lane traffic (SocioVerse-ABM)",
        research_question="Does the fundamental flow-density relation emerge, and does an LLM driver reproduce the rule?",
        hypothesis="Mean speed and flow settle to the congested-branch values for the chosen density.",
        domain="traffic",
        tags=["abm", "nasch", "traffic", "flow", "umbrella"],
        **overrides,
    )
