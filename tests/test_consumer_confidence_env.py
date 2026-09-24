"""consumer_confidence: the predictor's key and endpoint follow the documented `.env` lookup.

Hermetic: the ConsumerSim modules the seam imports are replaced by small stand-ins, so this
runs without the ConsumerSim checkout and never opens a connection. The adapter tests that
need the real checkout live in test_consumer_confidence_adapter.py.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

from socioverse import external_events
from studies.consumer_confidence.adapter.engine_seam import ConsumerSimEngine

CONFIG_ENDPOINT = "https://api.openai.com/v1/chat/completions"


class _Predictor:
    def __init__(self, profile, endpoint, model, api_key, timeout=60):
        if not api_key:
            raise ValueError("Configured credential environment variable is empty")
        self.endpoint, self.model, self.api_key, self.timeout = endpoint, model, api_key, timeout


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A ConsumerSimEngine over stand-in ConsumerSim modules, with every `.env` location
    pointed into tmp_path and SV_LLM_* removed from the process env for the test."""
    pkg = types.ModuleType("consumer_pipeline")
    pkg.__path__ = []
    config = types.ModuleType("consumer_pipeline.config")

    def read_secret_env(cfg, key):                     # ConsumerSim's version: a plain getenv
        variable = cfg.get("credentials", {}).get(key)
        return os.getenv(variable) if variable else None

    config.read_secret_env = read_secret_env
    prediction = types.ModuleType("consumer_pipeline.prediction")
    prediction.OpenAICompatibleCorePredictor = _Predictor
    prediction.ProbabilisticCorePredictor = object
    for name, mod in (("consumer_pipeline", pkg), ("consumer_pipeline.config", config),
                      ("consumer_pipeline.prediction", prediction)):
        monkeypatch.setitem(sys.modules, name, mod)

    for name in ("SV_LLM_API_KEY", "SV_LLM_BASE_URL"):
        monkeypatch.setenv(name, "unset-by-test")    # recorded, so the teardown restores it
        monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SV_HOME", str(home))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(external_events, "_REPO_ROOT", tmp_path / "not-a-checkout")

    eng = ConsumerSimEngine(consumersim_root=tmp_path)
    eng.config = {
        "prediction": {"provider": "openai_compatible", "endpoint": CONFIG_ENDPOINT,
                       "model": "test-model", "timeout_seconds": 5},
        "credentials": {"model_api_key": "SV_LLM_API_KEY"},
    }
    eng.home, eng.work = home, work
    return eng


def test_key_and_base_url_only_in_sv_home_dotenv(engine):
    (engine.home / ".env").write_text(
        "SV_LLM_API_KEY=sk-home\nSV_LLM_BASE_URL=http://127.0.0.1:18791/v1/\n", encoding="utf-8")
    predictor = engine._build_predictor()
    assert predictor.api_key == "sk-home"
    assert predictor.endpoint == "http://127.0.0.1:18791/v1/chat/completions"


def test_exported_key_with_base_url_only_in_dotenv_never_goes_to_openai(engine, monkeypatch):
    monkeypatch.setenv("SV_LLM_API_KEY", "sk-exported")
    (engine.work / ".env").write_text("SV_LLM_BASE_URL=http://127.0.0.1:18792/v1\n",
                                      encoding="utf-8")
    predictor = engine._build_predictor()
    assert predictor.api_key == "sk-exported"
    assert predictor.endpoint == "http://127.0.0.1:18792/v1/chat/completions"


def test_process_env_wins_and_empty_values_are_unset(engine, monkeypatch):
    monkeypatch.setenv("SV_LLM_BASE_URL", "http://127.0.0.1:18793/v1")
    (engine.home / ".env").write_text("SV_LLM_API_KEY=\nSV_LLM_BASE_URL=http://127.0.0.1:1/v1\n",
                                      encoding="utf-8")
    (engine.work / ".env").write_text("SV_LLM_API_KEY=sk-cwd\n", encoding="utf-8")
    predictor = engine._build_predictor()
    assert predictor.api_key == "sk-cwd"                # the empty SV_HOME value hides nothing
    assert predictor.endpoint == "http://127.0.0.1:18793/v1/chat/completions"


def test_without_a_base_url_the_configured_endpoint_is_used(engine):
    (engine.home / ".env").write_text("SV_LLM_API_KEY=sk-home\n", encoding="utf-8")
    predictor = engine._build_predictor()
    assert predictor.endpoint == CONFIG_ENDPOINT


def test_a_key_from_another_variable_keeps_its_configured_endpoint(engine, monkeypatch):
    """SV_LLM_BASE_URL belongs to the SV_LLM channel only: a key the config reads from a
    different variable is never redirected to it, from the process env or from `.env`."""
    other = "https://api.other-provider.example/v1/chat/completions"
    engine.config["credentials"] = {"model_api_key": "OTHER_PROVIDER_KEY"}
    engine.config["prediction"]["endpoint"] = other
    monkeypatch.setenv("OTHER_PROVIDER_KEY", "sk-other")
    (engine.home / ".env").write_text("SV_LLM_BASE_URL=http://127.0.0.1:18791/v1\n",
                                      encoding="utf-8")
    predictor = engine._build_predictor()
    assert predictor.api_key == "sk-other"
    assert predictor.endpoint == other

    monkeypatch.setenv("SV_LLM_BASE_URL", "http://127.0.0.1:18792/v1")
    predictor = engine._build_predictor()
    assert predictor.endpoint == other


def test_missing_key_still_fails_loudly(engine):
    with pytest.raises(ValueError, match="credential"):
        engine._build_predictor()
