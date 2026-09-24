"""germany_auto_market: the population is sampled from the uploaded workbook or not at all.

The study documents P as a weighted sample of the real German buyer joint distribution in
uploads/marketsim-grounding-data.xlsx. Reading it needs openpyxl (the `workbench` extra); without
it the run must stop with the install command, never swap in synthetic buyers.
"""

from __future__ import annotations

import importlib.util

import pytest

import studies.germany_auto_market  # noqa: F401  (side effect: registers germany_auto.*)
from skills.sv_workspace import study_paths
from socioverse.engine import build_simulator
from socioverse.schemas import (
    EnvironmentBundle,
    PopulationBundle,
    SimulationConfig,
    StudySpec,
)
from socioverse.validation import validate_handoff
from studies.germany_auto_market import model as germany


def test_missing_workbook_reader_stops_instead_of_faking(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == "openpyxl" else real(name, *a, **k))
    monkeypatch.setattr(germany, "_JOINT_CACHE", None)
    monkeypatch.setattr(germany, "_WEIGHT_CACHE", None)
    assert germany.workbook_missing_deps() == ["openpyxl"]
    with pytest.raises(RuntimeError, match=r'pip install -e "\.\[workbench\]"'):
        germany.sample_buyer(0, seed=42, n=10)


def test_missing_workbook_file_stops_instead_of_faking(monkeypatch, tmp_path):
    monkeypatch.setattr(germany, "_JOINT_CACHE", None)
    monkeypatch.setattr(germany, "_WEIGHT_CACHE", None)
    monkeypatch.setattr(germany, "workbook_missing_deps", lambda: [])
    monkeypatch.setattr(germany, "_xlsx_path", lambda: tmp_path / "absent.xlsx")
    with pytest.raises(FileNotFoundError, match="absent.xlsx"):
        germany.sample_buyer(0, seed=42, n=10)


def test_shipped_artifacts_assemble_and_run(tmp_path):
    """The committed bundles validate and run on the generic path, with P drawn from the workbook."""
    pytest.importorskip("openpyxl", reason='germany_auto_market needs the workbench extra: pip install -e ".[workbench]"')
    p = study_paths("studies/germany_auto_market")
    study = validate_handoff(p["study"], StudySpec)
    env_b = validate_handoff(p["environment"], EnvironmentBundle)
    pop_b = validate_handoff(p["population"], PopulationBundle)
    sim_c = validate_handoff(p["simulation"], SimulationConfig)
    assert study.legacy_simulator == "from_scratch"
    for bundle in (pop_b, env_b):                                        # keep the test small;
        bundle.provider_args = {**bundle.provider_args, "n_agents": 40}  # P and E sample the same pool
    sim_c.n_steps = 3
    sim_c.decision_args = {**sim_c.decision_args, "llm_kind": "scripted"}  # never spend tokens in tests
    cells, weights = germany._load_joint()
    assert len(cells) == len(weights) == 40320                           # the population_joint sheet
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "germany.duckdb")
    hist = sim.run()
    assert hist.covers(study.metrics) == []
    personas = sim.population.build(seed=sim_c.seed)
    assert [pa.agent_id for pa in personas] == [germany.agent_id(i) for i in range(40)]
    real_states = {c["bundesland_name"] for c in cells}
    assert all(pa.attributes["demographics"]["bundesland_name"] in real_states for pa in personas)
