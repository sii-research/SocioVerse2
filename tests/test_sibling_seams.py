"""Skip-guard contracts for the companion-repo seams (no companion repo needed).

The abm_* and Chicago tests must SKIP, never fail, when the SocioVerse-ABM sibling is present
but the Python deps its code imports are not installed (a plain `pip install -e .` next to a
sibling clone). These tests pin that the guards look at both the files AND the deps.
"""

from __future__ import annotations

import importlib.util

from studies._abm_common import seam as abm_seam
from studies.chicago_schelling.adapter import engine_seam as chi_seam


def _fake_abm(tmp_path):
    root = tmp_path / "SocioVerse-ABM"
    (root / "socioverse_abm").mkdir(parents=True)
    (root / "tasks").mkdir()
    return root


def _hide(monkeypatch, module, hidden: set[str]):
    real = importlib.util.find_spec
    monkeypatch.setattr(module.importlib.util, "find_spec",
                        lambda name, *a, **k: None if name in hidden else real(name, *a, **k))


def test_abm_available_needs_the_sibling(tmp_path, monkeypatch):
    monkeypatch.setenv("SV_ABM_ROOT", str(tmp_path / "absent"))
    assert abm_seam.abm_present() is False and abm_seam.abm_available() is False


def test_abm_available_needs_numpy_and_networkx(tmp_path, monkeypatch):
    monkeypatch.setenv("SV_ABM_ROOT", str(_fake_abm(tmp_path)))
    assert abm_seam.abm_present() is True
    _hide(monkeypatch, abm_seam, {"numpy"})
    assert "numpy" in abm_seam.abm_missing_deps()
    assert abm_seam.abm_available() is False          # sibling present, deps missing -> skip


def test_chicago_missing_reports_data_and_deps(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    (legacy / "processed_data").mkdir(parents=True)
    missing = chi_seam.chicago_missing(legacy)
    assert missing and missing[0].startswith("legacy data")
    (legacy / "processed_data" / "chicago_tracts.geojson").write_text("{}", encoding="utf-8")
    _hide(monkeypatch, chi_seam, {"mesa"})
    missing = chi_seam.chicago_missing(legacy)
    assert "mesa" in missing and not any(m.startswith("legacy data") for m in missing)
    assert chi_seam.chicago_available(legacy) is False
