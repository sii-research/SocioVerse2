"""scripts/sync_agent_surfaces.py — the Codex surface is a generated mirror of the
Claude surface. The repo-level check IS the drift test: editing .claude/ or CLAUDE*.md
without re-running the sync script fails here."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "sync_agent_surfaces", REPO / "scripts" / "sync_agent_surfaces.py")
sas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sas)


def test_repo_codex_surface_in_sync():
    drift = sas.check(REPO)
    assert drift == [], (
        "Codex mirror out of sync — run `python scripts/sync_agent_surfaces.py` "
        "(source of truth is the .claude side):\n  " + "\n  ".join(drift))


def _seed(root: Path) -> None:
    (root / ".claude" / "skills" / "sv-x").mkdir(parents=True)
    (root / ".codex" / "skills").mkdir(parents=True)
    (root / "studies" / "demo").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("usage v1\n", encoding="utf-8")
    (root / "CLAUDE-dev.md").write_text("dev v1\n", encoding="utf-8")
    (root / ".claude" / "skills" / "sv-x" / "SKILL.md").write_text("skill v1\n", encoding="utf-8")
    (root / "studies" / "demo" / "CLAUDE.md").write_text("case rules\n", encoding="utf-8")


def test_sync_then_check_roundtrip(tmp_path):
    _seed(tmp_path)
    assert sas.check(tmp_path) != []                       # nothing mirrored yet
    actions = sas.sync(tmp_path)
    assert actions and sas.check(tmp_path) == []

    # verbatim copies + a pointer stub for the study
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "usage v1\n"
    assert (tmp_path / ".codex" / "skills" / "sv-x" / "SKILL.md").read_text(encoding="utf-8") == "skill v1\n"
    stub = (tmp_path / "studies" / "demo" / "AGENTS.md").read_text(encoding="utf-8")
    assert "CLAUDE.md" in stub and "demo" in stub

    # editing the SOURCE reintroduces drift; sync clears it
    (tmp_path / ".claude" / "skills" / "sv-x" / "SKILL.md").write_text("skill v2\n", encoding="utf-8")
    assert any("stale mirror" in d for d in sas.check(tmp_path))
    sas.sync(tmp_path)
    assert sas.check(tmp_path) == []


def test_sync_prunes_deleted_skills_but_keeps_hand_written_pointer(tmp_path):
    _seed(tmp_path)
    sas.sync(tmp_path)

    # a hand-written per-study pointer must survive future syncs untouched
    custom = "# demo — custom pointer\nsee CLAUDE.md\n"
    (tmp_path / "studies" / "demo" / "AGENTS.md").write_text(custom, encoding="utf-8")
    sas.sync(tmp_path)
    assert (tmp_path / "studies" / "demo" / "AGENTS.md").read_text(encoding="utf-8") == custom

    # deleting a skill on the .claude side prunes its codex mirror
    (tmp_path / ".claude" / "skills" / "sv-x" / "SKILL.md").unlink()
    (tmp_path / ".claude" / "skills" / "sv-x").rmdir()
    assert any("stale skill" in d for d in sas.check(tmp_path))
    sas.sync(tmp_path)
    assert not (tmp_path / ".codex" / "skills" / "sv-x").exists()
    assert sas.check(tmp_path) == []
