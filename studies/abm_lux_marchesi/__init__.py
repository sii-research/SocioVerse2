"""abm_lux_marchesi — interacting-agents financial market, wrapped via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 50, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "lux_marchesi",
        study_id="abm_lux_marchesi",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Lux-Marchesi interacting-agents market (SocioVerse-ABM)",
        research_question="Does noise-trader herding generate price fluctuations, and does an LLM trader reproduce the rule?",
        hypothesis="Optimist/pessimist herding drives the price away from and back to the fundamental anchor.",
        domain="finance",
        tags=["abm", "lux_marchesi", "finance", "market", "umbrella"],
        **overrides,
    )
