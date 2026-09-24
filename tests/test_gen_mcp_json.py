"""scripts/gen_mcp_json.py — .env is the single source for MCP endpoints/keys;
.mcp.json is a gitignored render of it. Also guards that no private endpoint
leaks into the tracked setup files."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("gen_mcp_json", REPO / "scripts" / "gen_mcp_json.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_build_config_full_and_keyless_entries():
    env = {
        "SV_EVENT_API_URL": "http://host-a:9997/event_mcp",
        "SV_EVENT_API_KEY": "secret-a",
        "SV_USER_POOL_MCP_URL": "http://host-b:9998/user_pool_mcp",
        # no user-pool key: the service has no auth yet — entry must still register, header-free
    }
    cfg = gen.build_config(env)
    assert set(cfg["mcpServers"]) == {"event_tool", "user_pool_survey_mcp"}
    ev = cfg["mcpServers"]["event_tool"]
    assert ev == {"type": "http", "url": "http://host-a:9997/event_mcp",
                  "headers": {"Authorization": "Bearer secret-a"}}
    assert "headers" not in cfg["mcpServers"]["user_pool_survey_mcp"]


def test_build_config_skips_unset_and_blank_urls():
    assert gen.build_config({})["mcpServers"] == {}
    assert gen.build_config({"SV_EVENT_API_URL": "  "})["mcpServers"] == {}
    only_key = gen.build_config({"SV_EVENT_API_KEY": "orphan-key"})   # key without URL = nothing
    assert only_key["mcpServers"] == {}


def test_load_env_process_env_wins_over_file(tmp_path):
    envf = tmp_path / ".env"
    envf.write_text('SV_EVENT_API_URL=http://from-file:1/x\nSV_EVENT_API_KEY="quoted"\n# c\n',
                    encoding="utf-8")
    env = gen.load_env(envf, base={"SV_EVENT_API_URL": "http://from-process:2/y"})
    assert env["SV_EVENT_API_URL"] == "http://from-process:2/y"   # same setdefault semantics
    assert env["SV_EVENT_API_KEY"] == "quoted"                     # as socioverse._load_dotenv


def _clean_service_env(monkeypatch):
    """Other tests may have _load_dotenv'd the real repo .env into os.environ
    (it setdefaults globally); main() must see only the tmp .env here."""
    for url_var, key_var in gen.SERVICES.values():
        monkeypatch.delenv(url_var, raising=False)
        monkeypatch.delenv(key_var, raising=False)


def test_main_writes_then_is_idempotent_then_refuses_hand_edits(tmp_path, monkeypatch):
    _clean_service_env(monkeypatch)
    envf = tmp_path / ".env"
    envf.write_text("SV_EVENT_API_URL=http://h:9997/event_mcp\nSV_EVENT_API_KEY=k\n",
                    encoding="utf-8")
    out = tmp_path / ".mcp.json"
    argv = ["--env-file", str(envf), "--out", str(out)]

    assert gen.main(argv) == 0 and out.exists()
    rendered = out.read_text(encoding="utf-8")
    assert gen.main(argv) == 0                       # unchanged render → up-to-date, exit 0
    assert out.read_text(encoding="utf-8") == rendered

    out.write_text(rendered.replace("9997", "1111"), encoding="utf-8")   # a hand edit
    assert gen.main(argv) == 1                       # refuses to clobber without --force
    assert "1111" in out.read_text(encoding="utf-8")
    assert gen.main(argv + ["--force"]) == 0
    assert out.read_text(encoding="utf-8") == rendered


def test_main_no_urls_writes_nothing(tmp_path, monkeypatch):
    _clean_service_env(monkeypatch)
    envf = tmp_path / ".env"
    envf.write_text("SV_LLM_API_KEY=sk-x\n", encoding="utf-8")
    out = tmp_path / ".mcp.json"
    assert gen.main(["--env-file", str(envf), "--out", str(out)]) == 0
    assert not out.exists()


def test_no_private_endpoint_in_tracked_setup_files():
    """Endpoints live ONLY in the gitignored .env/.mcp.json (same rule as the
    capabilities-registry leak guard) — the tracked setup surface must never
    carry a numeric-IP URL."""
    ip_url = re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}")
    for rel in ("scripts/gen_mcp_json.py", "scripts/sync_agent_surfaces.py", ".env.example"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert not ip_url.search(text), f"numeric-IP endpoint leaked into tracked file {rel}"


def _isolate_lookup(tmp_path, monkeypatch):
    """Point every .env location of the runtime lookup into tmp_path."""
    from socioverse import external_events

    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("SV_HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(external_events, "_REPO_ROOT", tmp_path / "not-a-checkout")
    return home, work


def test_default_lookup_reads_sv_home_then_cwd(tmp_path, monkeypatch):
    _clean_service_env(monkeypatch)
    home, work = _isolate_lookup(tmp_path, monkeypatch)
    (home / ".env").write_text("SV_EVENT_API_URL=http://home-host/event_mcp\nSV_EVENT_API_KEY=\n",
                               encoding="utf-8")
    (work / ".env").write_text("SV_EVENT_API_URL=http://cwd-host/event_mcp\nSV_EVENT_API_KEY=k-cwd\n"
                               "SV_USER_POOL_MCP_URL=http://cwd-host/user_pool_mcp\n", encoding="utf-8")
    env = gen.load_env(base={})
    assert env["SV_EVENT_API_URL"] == "http://home-host/event_mcp"      # $SV_HOME/.env first
    assert env["SV_EVENT_API_KEY"] == "k-cwd"                           # empty = unset, falls through
    assert env["SV_USER_POOL_MCP_URL"] == "http://cwd-host/user_pool_mcp"

    out = tmp_path / ".mcp.json"
    assert gen.main(["--out", str(out)]) == 0                           # no --env-file: the lookup
    servers = json.loads(out.read_text(encoding="utf-8"))["mcpServers"]
    assert servers["event_tool"]["url"] == "http://home-host/event_mcp"
    assert servers["event_tool"]["headers"] == {"Authorization": "Bearer k-cwd"}


def test_process_env_wins_and_env_file_overrides_the_lookup(tmp_path, monkeypatch):
    _clean_service_env(monkeypatch)
    home, _ = _isolate_lookup(tmp_path, monkeypatch)
    (home / ".env").write_text("SV_EVENT_API_URL=http://home-host/event_mcp\n", encoding="utf-8")
    other = tmp_path / "other.env"
    other.write_text("SV_USER_POOL_MCP_URL=http://file-host/user_pool_mcp\n", encoding="utf-8")

    only_file = gen.load_env(other, base={})
    assert "SV_EVENT_API_URL" not in only_file                          # --env-file replaces the lookup
    assert only_file["SV_USER_POOL_MCP_URL"] == "http://file-host/user_pool_mcp"

    monkeypatch.setenv("SV_EVENT_API_URL", "http://process-host/event_mcp")
    assert gen.load_env()["SV_EVENT_API_URL"] == "http://process-host/event_mcp"
    monkeypatch.setenv("SV_EVENT_API_URL", "")                          # empty process value = unset
    assert gen.load_env()["SV_EVENT_API_URL"] == "http://home-host/event_mcp"
