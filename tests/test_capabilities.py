"""Capability registry tests: resources/capabilities.yaml + capability_view.

These back the skills' generic "capability check" hook: the registry is the single place an
external service is declared (what / when / confirm / fallback), and
``capability_view(stage=...)`` is the per-stage projection with availability resolved from
local config (.mcp.json registration / env vars). Adding a service must be a registry edit
only — so the SHIPPED registry itself is under test (entries well-formed, anchored to real
sv-* stages, no private endpoints), alongside the resolution logic on tmp fixtures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from skills.sv_workspace import capability_view, load_capabilities

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_STAGES = {"sv-init", "sv-build-model", "sv-build-environment",
                "sv-build-population", "sv-run", "sv-report", "sv-iterate"}


# ── the shipped registry ───────────────────────────────────────────────────────

def test_shipped_registry_entries_well_formed():
    entries = load_capabilities()
    names = [e["name"] for e in entries]
    assert len(names) == len(set(names)), "duplicate capability names"
    assert {"event_tool", "user_pool_survey_mcp"} <= set(names)
    for e in entries:
        for key in ("kind", "provides", "stages", "use_when", "confirm",
                    "howto", "fallback", "attach"):
            assert key in e, f"{e['name']} missing {key!r}"
        assert e["kind"] in {"mcp", "http_client", "builtin"}
        assert isinstance(e["confirm"], bool)
        assert set(e["stages"]) <= KNOWN_STAGES, f"{e['name']} anchors to an unknown stage"


def test_shipped_registry_stage_anchors():
    pop = {c["name"] for c in capability_view(stage="sv-build-population")}
    env = {c["name"] for c in capability_view(stage="sv-build-environment")}
    assert "user_pool_survey_mcp" in pop and "event_tool" not in pop
    assert "event_tool" in env and "user_pool_survey_mcp" not in env


def test_confirm_flags_match_spend_semantics():
    by_name = {e["name"]: e for e in load_capabilities()}
    assert by_name["user_pool_survey_mcp"]["confirm"] is True   # spends collaborator LLM budget
    assert by_name["event_tool"]["confirm"] is False            # read-only retrieval


def test_registry_never_contains_endpoints():
    """Public entries, private endpoints: no url may appear in the committed registry —
    kind=mcp resolves via the gitignored .mcp.json, kind=http_client via env/.env."""
    text = (REPO_ROOT / "resources" / "capabilities.yaml").read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text)   # no numeric IP endpoints either


# ── availability resolution (tmp fixtures) ─────────────────────────────────────

REGISTRY = """
- name: pool_mcp
  kind: mcp
  stages: [sv-build-population]
  available_when: {mcp_server: pool_mcp}
- name: events_http
  kind: http_client
  stages: [sv-build-environment]
  available_when: {env: [CAPTEST_URL]}
- name: unconditional
  kind: builtin
  stages: [sv-report]
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_mcp_availability_follows_mcp_json(tmp_path):
    reg = _write(tmp_path, "caps.yaml", REGISTRY)
    mj = _write(tmp_path, "mcp.json", json.dumps({"mcpServers": {"pool_mcp": {"url": "x"}}}))
    row = capability_view(stage="sv-build-population", path=reg, mcp_json=mj)[0]
    assert row["available"] is True

    mj2 = _write(tmp_path, "empty.json", json.dumps({"mcpServers": {}}))
    row = capability_view(stage="sv-build-population", path=reg, mcp_json=mj2)[0]
    assert row["available"] is False
    assert "pool_mcp" in row["availability_note"]


def test_mcp_availability_survives_missing_mcp_json(tmp_path):
    reg = _write(tmp_path, "caps.yaml", REGISTRY)
    row = capability_view(stage="sv-build-population", path=reg,
                          mcp_json=tmp_path / "nope.json")[0]
    assert row["available"] is False   # absent config = not registered, never a crash


def test_env_availability(tmp_path, monkeypatch):
    reg = _write(tmp_path, "caps.yaml", REGISTRY)
    monkeypatch.delenv("CAPTEST_URL", raising=False)
    row = capability_view(stage="sv-build-environment", path=reg, mcp_json=tmp_path / "x")[0]
    assert row["available"] is False and "CAPTEST_URL" in row["availability_note"]

    monkeypatch.setenv("CAPTEST_URL", "http://example.org")
    row = capability_view(stage="sv-build-environment", path=reg, mcp_json=tmp_path / "x")[0]
    assert row["available"] is True


def test_no_condition_defaults_available(tmp_path):
    reg = _write(tmp_path, "caps.yaml", REGISTRY)
    row = capability_view(stage="sv-report", path=reg, mcp_json=tmp_path / "x")[0]
    assert row["available"] is True


def test_missing_registry_is_empty_not_error(tmp_path):
    assert load_capabilities(tmp_path / "ghost.yaml") == []
    assert capability_view(path=tmp_path / "ghost.yaml") == []


def test_stage_none_returns_all(tmp_path):
    reg = _write(tmp_path, "caps.yaml", REGISTRY)
    assert len(capability_view(path=reg, mcp_json=tmp_path / "x")) == 3
