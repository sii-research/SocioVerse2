"""ConsumerSimEngine - wraps the ConsumerSim monthly confidence pipeline.

This seam imports ConsumerSim from an external checkout, but keeps population ownership
inside SocioVerse: Personas are converted to ConsumerSim Consumer rows and the legacy
synthetic population builder is not called.
"""

from __future__ import annotations

import csv
import os
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from socioverse.schemas import Persona

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_consumersim_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root)
    from socioverse.external_events import env_setting   # process env, else .env

    env = env_setting("SV_CONSUMERSIM_ROOT")
    if env:
        return Path(env)
    return _REPO_ROOT.parent / "ConsumerSim-Consumer-Confidence-Forecast"


def _ensure_on_path(root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _copy_config(config: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(config)


class ConsumerSimEngine:
    """Shared adapter state for one ConsumerSim study run."""

    def __init__(
        self,
        *,
        region: str = "US",
        target_months: list[str] | None = None,
        as_of_dates: list[str] | None = None,
        consumersim_root: str | Path | None = None,
        config_path: str | Path | None = None,
        config_overrides: dict[str, Any] | None = None,
        seed: int = 42,
    ) -> None:
        self.root = _resolve_consumersim_root(consumersim_root)
        self.region = region.upper()
        self.target_months = list(target_months or ["2026-06"])
        self.as_of_dates = list(as_of_dates or [])
        self.seed = seed
        self.config_path = Path(config_path) if config_path else None
        self.config_overrides = dict(config_overrides or {})

        self.config: dict[str, Any] | None = None
        self.profile = None
        self.population: list[Any] = []
        self.core: list[Any] = []
        self.population_by_id: dict[str, Any] = {}
        self.group_fields: tuple[str, ...] = ()
        self.current_step = 0
        self.current_month: str | None = None
        self.current_as_of: str | None = None
        self.current_environment = None
        self.last_result: dict[str, Any] | None = None
        self.results: dict[int, dict[str, Any]] = {}

    def ensure_loaded(self) -> None:
        if self.config is not None:
            return
        if not self.root.exists():
            raise FileNotFoundError(
                "ConsumerSim checkout not found. Set SV_CONSUMERSIM_ROOT or pass "
                f"consumersim_root. Tried: {self.root}"
            )
        _ensure_on_path(self.root)
        from consumer_pipeline.config import load_config
        from consumer_pipeline.regions import get_region_profile

        cfg_path = self.config_path or self.root / "configs" / f"{self.region.lower()}.yaml"
        config = load_config(cfg_path)
        self._deep_update(config, self.config_overrides)
        config["region"] = self.region
        config["seed"] = self.seed
        self.config = config
        self.profile = get_region_profile(self.region)
        self.group_fields = tuple(
            config["population"].get(
                "group_fields",
                ["age_group", "income_group", "education_group", "location_group"],
            )
        )

    def load_personas(self, personas: list[Persona]) -> list[Any]:
        """Convert SocioVerse Personas to ConsumerSim Consumers and select the core sample."""
        self.ensure_loaded()
        from consumer_pipeline.population import PopulationSampler

        self.population = [self._persona_to_consumer(p) for p in personas]
        self.population_by_id = {c.consumer_id: c for c in self.population}

        ratio = float(self.config["population"].get("core_ratio", 0.1))
        sampler = PopulationSampler(self.profile, self.seed)
        self.core = sampler.select_core(self.population, ratio, self.group_fields)
        return self.population

    def read_personas_csv(self, path: str | Path) -> list[Persona]:
        self.ensure_loaded()
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        with p.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [self._row_to_persona(row) for row in rows]

    def begin_step(self, step: int) -> None:
        self.ensure_loaded()
        if not self.population:
            raise RuntimeError("ConsumerSim population has not been loaded from SocioVerse personas")
        for consumer in self.population:
            consumer.response = None
        self.current_step = step
        self.current_month = self.month_for_step(step)
        self.current_as_of = self.as_of_for_step(step)
        self.last_result = None
        if self.current_month is None or self.current_as_of is None:
            self.current_environment = None
            return

        from consumer_pipeline.config import resolve_path
        from consumer_pipeline.information import InformationEnvironmentBuilder

        information = self.config["information"]
        self.current_environment = InformationEnvironmentBuilder().build(
            as_of=self.current_as_of,
            news_path=resolve_path(self.config, information.get("news_jsonl")),
            indicators_path=resolve_path(self.config, information.get("indicators_csv")),
            news_weight=float(information.get("news_weight", 0.5)),
            indicator_weight=float(information.get("indicator_weight", 0.5)),
        )

    def predict_core(self) -> None:
        self.ensure_loaded()
        if self.current_environment is None:
            return
        predictor = self._build_predictor()
        predictor.predict(self.core, self.current_environment)

    def finalize_step(self, actions: list[Any]) -> dict[str, Any]:
        self.ensure_loaded()
        if self.current_environment is None or self.current_month is None or self.current_as_of is None:
            return self.initial_metrics()

        # Treat the SocioVerse Action payload as the hand-off contract from B_t.
        for action in actions:
            consumer = self.population_by_id.get(action.agent_id)
            if consumer is not None and action.kind == "survey_response":
                consumer.response = dict(action.payload.get("response") or {})

        from consumer_pipeline.bayesian import BayesianAggregator
        from consumer_pipeline.config import resolve_path
        from consumer_pipeline.debias import PreviousMonthCorrector

        bayesian = self.config["bayesian"]
        aggregator = BayesianAggregator(
            self.profile,
            prior_strength=float(bayesian.get("prior_strength", 20.0)),
            seed=self.seed + 1,
        )
        posteriors = aggregator.update_and_expand(self.population, self.core, self.group_fields)
        raw_score, question_scores = aggregator.aggregate(self.population)

        correction_config = self.config["correction"]
        corrected_score, correction = PreviousMonthCorrector(
            weight=float(correction_config.get("weight", 0.5)),
            max_absolute_adjustment=float(correction_config.get("max_absolute_adjustment", 10.0)),
        ).apply(
            raw_score,
            self.current_month,
            resolve_path(self.config, correction_config.get("history_csv")),
        )

        result = {
            "region": self.profile.region.value,
            "target_month": self.current_month,
            "as_of": self.current_as_of,
            "population_size": len(self.population),
            "core_size": len(self.core),
            "raw_score": raw_score,
            "corrected_score": corrected_score,
            "question_scores": question_scores,
            "environment": {
                "news_score": self.current_environment.news_score,
                "indicator_score": self.current_environment.indicator_score,
                "combined_score": self.current_environment.combined_score,
                "news_count": len(self.current_environment.news_items),
                "indicator_count": len(self.current_environment.indicators),
            },
            "correction": asdict(correction),
            "group_posteriors": posteriors,
        }
        self.last_result = result
        self.results[self.current_step] = result
        return result

    def month_for_step(self, step: int) -> str | None:
        if step <= 0 or step > len(self.target_months):
            return None
        return self.target_months[step - 1]

    def as_of_for_step(self, step: int) -> str | None:
        if step <= 0:
            return None
        if self.as_of_dates:
            if step > len(self.as_of_dates):
                return self.as_of_dates[-1]
            return self.as_of_dates[step - 1]
        month = self.month_for_step(step)
        return f"{month}-20" if month else None

    def initial_metrics(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "target_month": "",
            "as_of": "",
            "population_size": len(self.population),
            "core_size": len(self.core),
            "raw_score": None,
            "corrected_score": None,
            "news_score": None,
            "indicator_score": None,
            "combined_score": None,
            "news_count": 0,
            "indicator_count": 0,
            "correction_residual": None,
            "correction_adjustment": None,
        }

    def metric_row(self, t: int) -> dict[str, Any]:
        if t == 0 or not self.last_result:
            return self.initial_metrics()
        result = self.last_result
        row = {
            "region": result["region"],
            "target_month": result["target_month"],
            "as_of": result["as_of"],
            "population_size": result["population_size"],
            "core_size": result["core_size"],
            "raw_score": result["raw_score"],
            "corrected_score": result["corrected_score"],
            "news_score": result["environment"]["news_score"],
            "indicator_score": result["environment"]["indicator_score"],
            "combined_score": result["environment"]["combined_score"],
            "news_count": result["environment"]["news_count"],
            "indicator_count": result["environment"]["indicator_count"],
            "correction_residual": result["correction"]["residual"],
            "correction_adjustment": result["correction"]["applied_adjustment"],
        }
        for question, score in result["question_scores"].items():
            row[f"score_{question}"] = score
        return row

    def agent_state(self, agent_id: str) -> dict[str, Any]:
        consumer = self.population_by_id[agent_id]
        response = consumer.response or {}
        return {
            "region": consumer.region.value,
            "age_group": consumer.age_group,
            "income_group": consumer.income_group,
            "education_group": consumer.education_group,
            "location_group": consumer.location_group,
            "weight": consumer.weight,
            "is_core": consumer.is_core,
            "target_month": self.current_month,
            **response,
        }

    def _build_predictor(self):
        from consumer_pipeline.config import read_secret_env
        from consumer_pipeline.prediction import OpenAICompatibleCorePredictor, ProbabilisticCorePredictor

        prediction = self.config["prediction"]
        provider = str(prediction.get("provider", "local")).lower()
        if provider == "local":
            return ProbabilisticCorePredictor(
                self.profile,
                self.seed,
                signal_strength=float(prediction.get("signal_strength", 0.08)),
            )
        if provider == "openai_compatible":
            # Hydrate the process env from the documented `.env` lookup ($SV_HOME/.env, ./.env,
            # the repo root; the process env wins, empty values count as unset) before reading
            # the key or the endpoint, as the other studies' LLM clients do. ConsumerSim's
            # read_secret_env is a plain os.getenv and would not see a key kept only in `.env`.
            from socioverse.external_events import _load_dotenv

            _load_dotenv()
            api_key = read_secret_env(self.config, "model_api_key")
            # SV_LLM_BASE_URL belongs to the SV_LLM channel. Only when the config reads the key
            # from SV_LLM_API_KEY does the endpoint follow it (set in the process env or in
            # `.env`). A key read from any other variable goes only to the prediction.endpoint
            # configured next to it, never to SV_LLM_BASE_URL.
            key_variable = (self.config.get("credentials") or {}).get("model_api_key")
            base = ""
            if key_variable == "SV_LLM_API_KEY":
                base = os.environ.get("SV_LLM_BASE_URL", "").strip()
            endpoint = f"{base.rstrip('/')}/chat/completions" if base else str(prediction["endpoint"])
            return OpenAICompatibleCorePredictor(
                self.profile,
                endpoint=endpoint,
                model=str(prediction["model"]),
                api_key=api_key or "",
                timeout=int(prediction.get("timeout_seconds", 60)),
            )
        raise ValueError("prediction.provider must be local or openai_compatible")

    def _persona_to_consumer(self, persona: Persona):
        self.ensure_loaded()
        from consumer_pipeline.models import Consumer

        attrs = {**persona.init_state, **persona.attributes}
        return Consumer(
            consumer_id=persona.agent_id,
            region=self.profile.region,
            age_group=str(attrs["age_group"]),
            income_group=str(attrs["income_group"]),
            education_group=str(attrs["education_group"]),
            location_group=str(attrs["location_group"]),
            weight=float(persona.weight),
        )

    def _row_to_persona(self, row: dict[str, str]) -> Persona:
        attrs = {
            "region": row.get("region", self.region),
            "age_group": row["age_group"],
            "income_group": row["income_group"],
            "education_group": row["education_group"],
            "location_group": row["location_group"],
        }
        group_key = "|".join(str(attrs[field]) for field in self.group_fields)
        return Persona(
            agent_id=row.get("agent_id") or row["consumer_id"],
            group_key=group_key,
            weight=float(row.get("weight") or 1.0),
            attributes=attrs,
            init_state={"source": "csv"},
        )

    @staticmethod
    def _deep_update(base: dict[str, Any], updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                ConsumerSimEngine._deep_update(base[key], value)
            else:
                base[key] = _copy_config(value) if isinstance(value, dict) else value
