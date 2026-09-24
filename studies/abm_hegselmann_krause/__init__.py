"""abm_hegselmann_krause — bounded-confidence opinion dynamics, wrapped via the umbrella.

The SocioVerse-ABM HK task. Kept separate from SocioVerse2's native `opinion_diffusion` template
(do not edit that template); this is the umbrella-wrapped SocioVerse-ABM version.
"""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 10, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "hegselmann_krause",
        study_id="abm_hegselmann_krause",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Hegselmann-Krause bounded-confidence opinion dynamics (SocioVerse-ABM)",
        research_question="Does bounded-confidence averaging coalesce opinions into clusters, and does an LLM agent reproduce it?",
        hypothesis="The number of opinion clusters drops from the dispersed start toward consensus/polarization.",
        domain="opinion-dynamics",
        tags=["abm", "hegselmann_krause", "opinion-dynamics", "diffusion", "umbrella"],
        **overrides,
    )
