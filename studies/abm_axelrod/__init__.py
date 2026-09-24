"""abm_axelrod — iterated Prisoner's Dilemma tournament, wrapped via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 20, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "axelrod",
        study_id="abm_axelrod",
        n_steps=n_steps, seed=seed, mode=mode,
        group_field="strategy",
        title="Axelrod iterated Prisoner's Dilemma (SocioVerse-ABM)",
        research_question="Does cooperation pay in a round-robin of strategies, and does an LLM agent reproduce them?",
        hypothesis="Cooperative/retaliatory strategies accumulate competitive payoff; cooperation persists.",
        domain="game-theory",
        tags=["abm", "axelrod", "game-theory", "market", "umbrella"],
        **overrides,
    )
