"""ExternalEventsClient: tier priority, normalization, fallback, materialization.

The remote tier speaks the production Event MCP protocol: GET <root>/healthz,
then plain JSON-RPC POSTs to the MCP endpoint (tools/call get_source_detail per
explicit source, get_data sources="default" otherwise). Fake transports below
mirror that wire shape.
"""

from __future__ import annotations

import json

import pytest

from socioverse import (
    ExternalEventsBundle,
    ExternalEventsClient,
    materialize_external_events,
    month_range,
)
from socioverse.schemas.resources import McpServerDecl, ResourceManifest

MCP_URL = "http://example.test:9997/event_mcp"


def _source_result(source: str, ym: str, data: dict, status: str = "ok") -> dict:
    return {
        "source_name": source, "category": "macro_market", "description": "",
        "target_date": ym, "fetched_at": "2026-07-07T00:00:00Z",
        "from_cache": True, "status": status,
        "error_message": "upstream boom" if status == "error" else None,
        "data": data,
    }


def _rpc_result(payload_id, body: dict) -> dict:
    return {"jsonrpc": "2.0", "id": payload_id,
            "result": {"content": [{"type": "text", "text": json.dumps(body)}],
                       "isError": False}}


def _ok_transport(method, url, payload, timeout):
    """fred serves data; nyt_archive reports a server-side collector error."""
    if url.endswith("/healthz"):
        assert method == "GET" and payload is None
        return {"status": "ok", "service": "event_mcp"}
    assert method == "POST" and url == MCP_URL
    assert payload["method"] == "tools/call"
    args = payload["params"]["arguments"]
    assert (args["year"], args["month"]) == (2025, 4)
    assert payload["params"]["name"] == "get_source_detail"
    src = args["source"]
    body = (_source_result(src, "2025-04", {"UNRATE": 4.2}) if src == "fred"
            else _source_result(src, "2025-04", {}, status="error"))
    return _rpc_result(payload["id"], body)


def _default_sources_transport(method, url, payload, timeout):
    """The sources=[] path: one get_data("default") call per month."""
    if url.endswith("/healthz"):
        return {"status": "ok"}
    assert payload["params"]["name"] == "get_data"
    assert payload["params"]["arguments"]["sources"] == "default"
    body = {
        "requested_sources": ["fred", "nyt_archive"],
        "results": [_source_result("fred", "2025-04", {"UNRATE": 4.2})],
        "errors": [_source_result("nyt_archive", "2025-04", {}, status="error")],
        "fetched_count": 1, "error_count": 1,
    }
    return _rpc_result(payload["id"], body)


def _dead_transport(method, url, payload, timeout):
    raise OSError("connection refused")


def _client(**kw) -> ExternalEventsClient:
    kw.setdefault("api_url", MCP_URL)
    kw.setdefault("api_key", "sk-test")
    return ExternalEventsClient(**kw)


def test_remote_tier_normalizes_per_source_results():
    bundle = _client(transport=_ok_transport).fetch(
        "tariff impact", months=["2025-04"], sources=["fred", "nyt_archive"])
    assert bundle.provider == "remote" and bundle.available
    assert bundle.endpoint == MCP_URL
    assert bundle.results["fred_2025-04"]["data"] == {"UNRATE": 4.2}
    assert bundle.availability["sources_used"] == ["fred"]
    assert bundle.availability["sources_unavailable"] == ["nyt_archive"]
    assert {e["source_name"] for e in bundle.errors} == {"nyt_archive"}
    # the MCP returns structured data only — no service prose, no service web search
    assert bundle.summary is None and bundle.web_evidence == []


def test_remote_default_sources_uses_get_data():
    bundle = _client(transport=_default_sources_transport).fetch(
        "tariff impact", months=["2025-04"])
    assert bundle.provider == "remote"
    assert bundle.results["fred_2025-04"]["data"] == {"UNRATE": 4.2}
    assert bundle.availability["source_status"]["nyt_archive_2025-04"] == "error"


def test_one_hanging_source_does_not_kill_the_tier():
    def nyt_hangs(method, url, payload, timeout):
        if url.endswith("/healthz"):
            return {"status": "ok"}
        if payload["params"]["arguments"]["source"] == "nyt_archive":
            raise TimeoutError("timed out")
        return _ok_transport(method, url, payload, timeout)

    bundle = _client(transport=nyt_hangs).fetch(
        "q", months=["2025-04"], sources=["fred", "nyt_archive"])
    assert bundle.provider == "remote"
    assert "fred_2025-04" in bundle.results
    nyt_err = next(e for e in bundle.errors if e["source_name"] == "nyt_archive")
    assert "TimeoutError" in nyt_err["error_message"]


def test_remote_needs_months_falls_back(tmp_path):
    # no query parser server-side: months=[] must drop the remote tier
    bundle = _client(transport=_ok_transport, local_cache_dir=tmp_path).fetch(
        "tariff impact", sources=["fred"])
    assert bundle.provider == "unavailable"
    assert any("months" in e.get("error", "") for e in bundle.errors)


def test_auth_rejection_is_fatal_for_the_tier(tmp_path):
    def rejects(method, url, payload, timeout):
        if url.endswith("/healthz"):
            return {"status": "ok"}   # /healthz is auth-exempt on the server
        err = OSError("HTTP Error 401: Unauthorized")
        err.code = 401
        raise err

    (tmp_path / "fred").mkdir()
    (tmp_path / "fred" / "2025-04.json").write_text("{}")
    bundle = _client(transport=rejects, local_cache_dir=tmp_path).fetch(
        "q", months=["2025-04"], sources=["fred"])
    assert bundle.provider == "local_cache"   # fell through, not 20 retries
    assert any("SV_EVENT_API_KEY" in e.get("error", "") for e in bundle.errors)


def test_falls_back_to_local_cache_when_remote_dead(tmp_path):
    (tmp_path / "fred").mkdir()
    (tmp_path / "fred" / "2025-04.json").write_text(json.dumps({"UNRATE": 4.2}))
    bundle = _client(transport=_dead_transport, local_cache_dir=tmp_path).fetch(
        "tariff impact", months=["2025-04", "2025-05"], sources=["fred"])
    assert bundle.provider == "local_cache" and bundle.available
    assert bundle.results["fred_2025-04"]["from_cache"] is True
    assert bundle.availability["source_status"]["fred_2025-05"] == "missing"
    assert any(e["tier"] == "remote" for e in bundle.errors)  # remote failure recorded


def test_unavailable_when_all_tiers_down(tmp_path):
    bundle = _client(transport=_dead_transport, local_cache_dir=tmp_path).fetch(
        "q", months=["2025-04"], sources=["fred"])
    assert bundle.provider == "unavailable" and not bundle.available
    tiers = {e["tier"] for e in bundle.errors}
    assert tiers == {"remote"}  # cache dir exists but is empty -> only remote error kept
    assert bundle.results == {}


def test_unavailable_when_nothing_configured(monkeypatch):
    import socioverse.external_events as ee
    monkeypatch.setattr(ee, "_load_dotenv", lambda *a, **k: None)  # ignore dev .env
    for var in ("SV_EVENT_API_URL", "SV_EVENT_API_KEY", "SV_EVENT_LOCAL_CACHE"):
        monkeypatch.delenv(var, raising=False)
    bundle = ExternalEventsClient(api_url="", local_cache_dir=None).fetch("q")
    assert bundle.provider == "unavailable"
    msgs = " ".join(e["error"] for e in bundle.errors)
    assert "SV_EVENT_API_URL" in msgs and "SV_EVENT_LOCAL_CACHE" in msgs


def test_unhealthy_endpoint_falls_through(tmp_path):
    def sick(method, url, payload, timeout):
        assert url.endswith("/healthz")   # never reaches the MCP endpoint
        return {"status": "down"}
    (tmp_path / "fred").mkdir()
    (tmp_path / "fred" / "2025-04.json").write_text("{}")
    bundle = _client(transport=sick, local_cache_dir=tmp_path).fetch(
        "q", months=["2025-04"], sources=["fred"])
    assert bundle.provider == "local_cache"


def test_from_manifest_takes_url_not_key():
    manifest = ResourceManifest(study_id="s", mcp_servers=[
        McpServerDecl(name="event_tool", transport="http",
                      url="http://m.test:9997/event_mcp/")])
    client = ExternalEventsClient.from_manifest(manifest, api_key="sk-env")
    assert client.api_url == "http://m.test:9997/event_mcp"
    assert client.api_key == "sk-env"


def test_materialize_writes_validated_artifact(tmp_path):
    path, bundle = materialize_external_events(
        tmp_path, "tariff impact", months=["2025-04"], sources=["fred"],
        client=_client(transport=_ok_transport))
    assert path == tmp_path / "environment" / "external_events.json"
    reloaded = ExternalEventsBundle.model_validate_json(path.read_text())
    assert reloaded.provider == "remote"
    assert reloaded.results.keys() == bundle.results.keys()


def test_month_range():
    assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert month_range("2025-04", "2025-04") == ["2025-04"]


# ── .env discovery: $SV_HOME, then the cwd, then the repo root (checkout only) ──

def test_dotenv_candidates_order(tmp_path, monkeypatch):
    import socioverse.external_events as ee
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("SV_HOME", str(home))
    monkeypatch.chdir(work)
    cands = ee.dotenv_candidates()
    assert cands[0] == home / ".env" and cands[1] == work / ".env"
    # running from a checkout, the repo root is the last resort
    assert cands[-1] == ee._REPO_ROOT / ".env" and ee._is_checkout(ee._REPO_ROOT)


def test_dotenv_repo_root_skipped_outside_a_checkout(tmp_path, monkeypatch):
    import socioverse.external_events as ee
    monkeypatch.delenv("SV_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ee, "_REPO_ROOT", tmp_path / "site-packages")   # a wheel install
    assert ee.dotenv_candidates() == [tmp_path / ".env"]


def test_load_dotenv_first_file_wins_env_beats_files(tmp_path, monkeypatch):
    import socioverse.external_events as ee
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    (home / ".env").write_text("SVT_A=from_home\nSVT_D=\n", encoding="utf-8")
    (work / ".env").write_text("SVT_A=from_cwd\nSVT_B='from_cwd'\nSVT_C=from_cwd\n"
                               "SVT_D=from_cwd\nSVT_E=\n", encoding="utf-8")
    monkeypatch.setenv("SV_HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(ee, "_REPO_ROOT", tmp_path / "site-packages")
    monkeypatch.setenv("SVT_C", "from_process")
    import os
    try:
        for k in ("SVT_A", "SVT_B", "SVT_D", "SVT_E"):
            os.environ.pop(k, None)
        ee._load_dotenv()
        assert os.environ["SVT_A"] == "from_home"       # $SV_HOME beats the cwd
        assert os.environ["SVT_B"] == "from_cwd"        # keys missing upstream still resolve
        assert os.environ["SVT_C"] == "from_process"    # the process env beats every file
        assert os.environ["SVT_D"] == "from_cwd"        # an empty value upstream hides nothing
        assert "SVT_E" not in os.environ                # and is never exported as ""
        assert ee.env_setting("SVT_D") == "from_cwd" and ee.env_setting("SVT_E") is None
    finally:
        for k in ("SVT_A", "SVT_B", "SVT_D", "SVT_E"):
            os.environ.pop(k, None)
