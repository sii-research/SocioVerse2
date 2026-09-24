"""abm_sir — SIR rumor spreading on a network, wrapped from SocioVerse-ABM via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 30, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "sir",
        study_id="abm_sir",
        n_steps=n_steps, seed=seed, mode=mode,
        title="SIR rumor spreading on a network (SocioVerse-ABM)",
        research_question="Does a rumor cascade through the network, and does an LLM agent reproduce the contact rule?",
        hypothesis="The ignorant fraction falls as the rumor spreads to a sizeable reach.",
        domain="epidemics",
        tags=["abm", "sir", "diffusion", "epidemics", "umbrella"],
        **overrides,
    )
