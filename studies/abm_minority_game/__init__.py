"""abm_minority_game — Challet-Zhang minority game, wrapped via the umbrella."""
from studies._abm_common import make_abm_bundles  # noqa: F401  (registers abm.* providers)


def make_bundles(*, n_steps: int = 30, seed: int = 42, mode: str = "rule", **overrides):
    return make_abm_bundles(
        "minority_game",
        study_id="abm_minority_game",
        n_steps=n_steps, seed=seed, mode=mode,
        title="Minority Game / Challet-Zhang (SocioVerse-ABM)",
        research_question="Does inductive strategy play coordinate the population, and does an LLM agent reproduce it?",
        hypothesis="Volatility sigma^2/N settles to a level set by the memory/population ratio.",
        domain="game-theory",
        tags=["abm", "minority_game", "game-theory", "market", "umbrella"],
        **overrides,
    )
