"""Every shipped study's handoff artifacts satisfy their schemas.

A study is forked, copied as a template or re-validated by /sv-iterate's verify-and-skip
through ``validate_handoff``, so each artifact a shipped ``studies/*/study.yaml`` points at
(study, environment, population, simulation, resources) must pass it. Artifacts a study does
not ship (e.g. an imported reference with no simulation.json) are skipped, not invented.

Only the shipped studies are checked. The set is the repository's own declaration of what
ships: the ``!studies/<id>/`` whitelist in ``.gitignore`` (every other study dir is local
scratch), so it is the same with or without ``.git`` or the git binary. A study a user is
still building (or a demo copy such as ``opinion_diffusion_demo``) is never in it, so a
half-built local study cannot fail the suite. A copy without ``.gitignore`` falls back to
the ``reference: true`` flag, which marks the shipped templates (forks and new studies are
written with ``reference: false``).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from socioverse.schemas import (
    EnvironmentBundle,
    PopulationBundle,
    ResourceManifest,
    SimulationConfig,
    StudySpec,
)
from socioverse.validation import validate_handoff

REPO = Path(__file__).resolve().parents[1]

ARTIFACTS = (
    ("environment_ref", EnvironmentBundle),
    ("population_ref", PopulationBundle),
    ("simulation_ref", SimulationConfig),
    ("resources_ref", ResourceManifest),
)


_WHITELIST = re.compile(r"^!studies/([^/\s*?\[\]]+)/?\s*$", re.MULTILINE)


def _whitelisted_study_ids(repo: Path) -> set[str] | None:
    """Study ids un-ignored by ``.gitignore`` (``!studies/<id>/``); None without the file."""
    gitignore = repo / ".gitignore"
    if not gitignore.is_file():
        return None
    return set(_WHITELIST.findall(gitignore.read_text(encoding="utf-8")))


def _is_reference(study_yaml: Path) -> bool:
    try:
        data = yaml.safe_load(study_yaml.read_text(encoding="utf-8"))
    except Exception:          # a half-written file is not a shipped study
        return False
    return isinstance(data, dict) and data.get("reference") is True


def _shipped_study_files(repo: Path = REPO) -> list[Path]:
    found = sorted((repo / "studies").glob("*/study.yaml"))
    ids = _whitelisted_study_ids(repo)
    if ids is None:
        return [p for p in found if _is_reference(p)]
    return [p for p in found if p.parent.name in ids]


STUDY_FILES = _shipped_study_files()


def test_there_are_shipped_studies():
    assert len(STUDY_FILES) >= 10


@pytest.mark.parametrize("study_yaml", STUDY_FILES, ids=lambda p: p.parent.name)
def test_shipped_study_artifacts_validate(study_yaml):
    study_dir = study_yaml.parent
    spec = validate_handoff(study_yaml, StudySpec)
    assert spec.study_id == study_dir.name
    for field, schema in ARTIFACTS:
        rel = getattr(spec, field)
        if not rel:
            continue
        path = study_dir / rel
        if not path.exists():
            continue
        bundle = validate_handoff(path, schema)
        sid = getattr(bundle, "study_id", None)
        assert sid in (None, "", spec.study_id), f"{path} carries study_id {sid!r}"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_local_studies_are_not_treated_as_shipped(tmp_path):
    shipped = _write(tmp_path / "studies/shipped_one/study.yaml", '{"reference": true}')
    _write(tmp_path / "studies/my_draft/study.yaml", "study_id: my_draft\ntitle: [unclosed")
    _write(tmp_path / "studies/my_fork/study.yaml", '{"reference": false}')
    _write(tmp_path / ".gitignore", "studies/*/\n!studies/_abm_common/\n!studies/shipped_one/\n")
    assert _shipped_study_files(tmp_path) == [shipped]


def test_without_gitignore_the_reference_flag_decides(tmp_path):
    shipped = _write(tmp_path / "studies/shipped_one/study.yaml", '{"reference": true}')
    _write(tmp_path / "studies/my_draft/study.yaml", "study_id: my_draft\ntitle: [unclosed")
    _write(tmp_path / "studies/my_fork/study.yaml", '{"reference": false}')
    assert _shipped_study_files(tmp_path) == [shipped]
