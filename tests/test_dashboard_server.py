"""Unit tests for the pure functions of dashboard/server/app.py (no server started, real studies/ untouched).

app.py is a script-style module: main() is only called under __main__, and importing it has no side effects
(it only stats its own file + computes path constants), so it is imported directly after a sys.path.insert.
Every input is built fresh with pytest tmp_path and has nothing to do with the real studies in the repo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "server"))
import app  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────────
def write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def attr_of(dist: dict, name: str) -> dict | None:
    return next((a for a in dist["attrs"] if a["attr"] == name), None)


# ── population_distribution ─────────────────────────────────────────────────
def make_roster(path: Path, n: int = 30) -> None:
    """One attribute each: numeric / categorical / constant / high-cardinality (>25 categories) / mixed with nulls."""
    rows = []
    for i in range(n):
        rows.append({
            "agent_id": f"u{i}",
            "state": {
                "income": i,                                    # numeric: 0..29
                "group": "a" if i < 15 else ("b" if i < 25 else "c"),  # categorical 15/10/5
                "const": 5,                                     # constant numeric
                "uid": f"uid-{i}",                              # high cardinality: 30 categories > 25 → skipped
                "opt": None if i < 10 else float(i),            # mixed with nulls: only non-null values are counted
            },
        })
    write_jsonl(path, rows)


def test_population_distribution_numeric_and_categorical(tmp_path):
    roster = tmp_path / "roster.jsonl"
    make_roster(roster)
    dist = app.population_distribution(roster)
    assert dist is not None and dist["n_agents"] == 30

    income = attr_of(dist, "income")
    assert income["kind"] == "num"
    assert income["min"] == 0.0 and income["max"] == 29.0
    assert income["median"] == 14.5
    assert len(income["hist"]) == 10 and sum(income["hist"]) == 30

    group = attr_of(dist, "group")
    assert group["kind"] == "cat" and group["distinct"] == 3
    assert group["top"][0] == {"v": "a", "n": 15, "pct": 0.5}
    assert [t["v"] for t in group["top"]] == ["a", "b", "c"]
    assert abs(sum(t["pct"] for t in group["top"]) - 1.0) < 1e-9


def test_population_distribution_constant_high_card_and_nulls(tmp_path):
    roster = tmp_path / "roster.jsonl"
    make_roster(roster)
    dist = app.population_distribution(roster)

    const = attr_of(dist, "const")
    assert const["min"] == const["max"] == 5.0
    assert const["hist"] == [30]           # degenerate histogram: one bucket holds everything

    assert attr_of(dist, "uid") is None    # a high-cardinality attribute with >25 categories is skipped

    opt = attr_of(dist, "opt")             # None is not counted, leaving 20 non-null values
    assert opt is not None and opt["n"] == 20 and opt["min"] == 10.0


def test_population_distribution_mtime_cache_and_missing(tmp_path):
    roster = tmp_path / "roster.jsonl"
    make_roster(roster)
    first = app.population_distribution(roster)
    second = app.population_distribution(roster)
    assert second is first                 # same mtime → cache hit, same object
    assert app.population_distribution(tmp_path / "nope.jsonl") is None


# ── agents_summary / agent_detail (roster as the fallback source) ─────────────────
def make_panel_study(d: Path) -> None:
    """No panel_live / duckdb: read_panel falls back to population/roster.jsonl (two agents, several steps)."""
    write_jsonl(d / "population" / "roster.jsonl", [
        {"agent_id": "a1", "step": 0, "state": {"x": 1}, "action_kind": "stay"},
        {"agent_id": "a1", "step": 2, "state": {"x": 3, "y": 9}, "action_kind": "move"},
        {"agent_id": "a2", "step": 0, "state": {"x": 7}, "action_kind": "stay"},
        {"agent_id": "a2", "step": 1, "state": {"x": 8}, "action_kind": "move"},
    ])


def test_agents_summary_from_roster(tmp_path):
    make_panel_study(tmp_path)
    s = app.agents_summary(tmp_path)
    assert s["count"] == 2 and s["phase"] == "initial" and s["live"] is False
    assert s["dims"] == ["x", "y"]
    assert s["steps"] == [0, 1, 2]
    a1 = next(a for a in s["agents"] if a["agent_id"] == "a1")
    assert a1["latest_step"] == 2          # takes the row with the largest step
    assert a1["state"] == {"x": 3, "y": 9} and a1["last_action"] == "move"
    a2 = next(a for a in s["agents"] if a["agent_id"] == "a2")
    assert a2["latest_step"] == 1 and a2["state"] == {"x": 8}


def test_agent_detail_from_roster(tmp_path):
    make_panel_study(tmp_path)
    det = app.agent_detail(tmp_path, "a1")
    assert det["agent_id"] == "a1" and det["phase"] == "initial"
    assert [r["step"] for r in det["rows"]] == [0, 2]   # ascending by step
    assert all(r["agent_id"] == "a1" for r in det["rows"])


# ── pop_summary ─────────────────────────────────────────────────────────────
def test_pop_summary_prefers_materialized_count(tmp_path):
    p = tmp_path / "population" / "population.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "provider_ref": "census", "propagation": "none",
        "interaction": {"kind": "network"},
        "personas": [{"id": 1}, {"id": 2}],
        "materialized_count": 5,
    }))
    s = app.pop_summary(p)
    assert s["persona_count"] == 5         # materialized_count takes precedence over len(personas)
    assert s["provider_ref"] == "census" and s["interaction_kind"] == "network"
    assert "distribution" in s and s["distribution"] is None   # no roster.jsonl


def test_pop_summary_fallback_count_and_distribution(tmp_path):
    p = tmp_path / "population" / "population.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"personas": [{"id": 1}, {"id": 2}]}))
    make_roster(p.parent / "roster.jsonl", n=4)
    s = app.pop_summary(p)
    assert s["persona_count"] == 2         # no materialized_count → falls back to len(personas)
    assert s["distribution"]["n_agents"] == 4


def test_pop_summary_missing_file(tmp_path):
    assert app.pop_summary(tmp_path / "population.json") is None


# ── stage_mtimes / build_detail / build_state (a minimal study with only study.yaml) ──
def make_min_study(root: Path, sid: str, *, path_b: bool) -> Path:
    d = root / sid
    d.mkdir(parents=True)
    spec = {"study_id": sid, "title": f"T-{sid}"}
    if path_b:
        spec["legacy_simulator"] = "from_scratch"
    (d / "study.yaml").write_text(json.dumps(spec))    # study.yaml is JSON-in-.yaml
    return d


def test_stage_mtimes_only_study_yaml(tmp_path):
    d = make_min_study(tmp_path, "t1", path_b=True)
    mts = app.stage_mtimes(app.study_paths(d))
    assert set(mts) == {s for s, _ in app.STAGES}
    assert mts["sv-init"] > 0
    assert all(mts[k] == 0.0 for k in mts if k != "sv-init")


def test_build_detail_minimal_path_b(tmp_path):
    d = make_min_study(tmp_path, "t1", path_b=True)
    det = app.build_detail(d)
    assert det["study_id"] == "t1" and det["is_path_b"] is True
    assert det["path_label"].startswith("Path B")
    status = {s["name"]: s["status"] for s in det["stages"]}
    assert status["sv-init"] == "done"
    assert all(status[n] == "pending" for n in status if n != "sv-init")
    active = [s["name"] for s in det["stages"] if s["active"]]
    assert active == ["sv-build-model"]    # the pointer stops at the first unfinished stage
    # no manifest → an implicit single v1
    assert det["current_version"] == det["viewing_version"] == "v1"
    assert det["archived"] is False
    assert det["figures"] == [] and det["report_md"] is None
    assert det["progress"] is None and det["metrics_rows"] == []
    # the event log contains at least sv-init's stage event
    assert any(e["kind"] == "stage" and e["stage"] == "sv-init" for e in det["events"])


def test_build_detail_minimal_path_a_skips_model(tmp_path):
    d = make_min_study(tmp_path, "t2", path_b=False)
    det = app.build_detail(d)
    status = {s["name"]: s["status"] for s in det["stages"]}
    assert status["sv-build-model"] == "skipped"
    active = [s["name"] for s in det["stages"] if s["active"]]
    assert active == ["sv-build-environment"]


def test_build_state_progress_counts(tmp_path, monkeypatch):
    root = tmp_path / "studies"
    make_min_study(root, "t_a", path_b=False)      # model skipped → total 5
    make_min_study(root, "t_b", path_b=True)       # all 6 stages count → total 6
    monkeypatch.setattr(app, "STUDIES_ROOT", root)
    state = app.build_state()
    items = {it["study_id"]: it for it in state["studies"]}
    assert set(items) == {"t_a", "t_b"}
    assert items["t_a"]["progress"] == {"done": 1, "total": 5}
    assert items["t_b"]["progress"] == {"done": 1, "total": 6}
    assert items["t_a"]["active_stage"] == "sv-build-environment"
    assert items["t_b"]["active_stage"] == "sv-build-model"
    assert items["t_a"]["version"] == {"current": "v1", "count": 1}
    assert state["current_id"] in {"t_a", "t_b"}   # the most recent mtime; both are created in the same second, so no strict assertion


# ── intent checklist (sv-init Step −1) ────────────────────────────────────────
def _cl(phase="clarifying", n=2):
    return {"phase": phase, "query": "q",
            "items": [{"id": "rq", "status": "inferred", "value": "v"} for _ in range(n)]}


def test_intent_checklist_ingest_and_state(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STUDIES_ROOT", tmp_path / "studies")
    monkeypatch.setattr(app, "INTENT", None)
    app.apply_ingest({"type": "intent_checklist", "checklist": _cl()})
    state = app.build_state()
    assert state["intent"]["phase"] == "clarifying"
    assert len(state["intent"]["items"]) == 2
    # a full resend replaces the old copy
    app.apply_ingest({"type": "intent_checklist", "checklist": _cl(phase="confirmed", n=3)})
    assert app.build_state()["intent"]["phase"] == "confirmed"


def test_intent_checklist_rejects_malformed(monkeypatch):
    monkeypatch.setattr(app, "INTENT", _cl())
    app.apply_ingest({"type": "intent_checklist", "checklist": {"items": []}})   # empty items → cleared
    assert app.INTENT is None
    monkeypatch.setattr(app, "INTENT", _cl())
    app.apply_ingest({"type": "intent_checklist", "checklist": "not-a-dict"})
    assert app.INTENT is None


def test_user_query_resets_stale_intent(monkeypatch):
    monkeypatch.setattr(app, "INTENT", _cl())
    app.apply_ingest({"type": "user_query", "prompt": "new study"})
    assert app.INTENT is None                       # a new session clears the previous session's leftovers
    assert app.SESSION_ACTIVE is True
    # other lifecycle events leave the checklist alone
    monkeypatch.setattr(app, "INTENT", _cl())
    app.apply_ingest({"type": "stage_summary", "study_id": "s", "stage": "sv-init"})
    assert app.INTENT is not None


def test_build_detail_includes_archived_intent(tmp_path):
    d = make_min_study(tmp_path, "t_ic", path_b=True)
    assert app.build_detail(d)["intent"] is None    # not archived → None
    (d / "intent.json").write_text(json.dumps(_cl(phase="confirmed")))
    det = app.build_detail(d)
    assert det["intent"]["phase"] == "confirmed" and len(det["intent"]["items"]) == 2


# ── published UI = v2 cockpit (the v1 index.html left the repo on 2026-08-07) ──
def _ui_tree(tmp_path: Path, v1: bool = False, v2: bool = True) -> Path:
    web = tmp_path / "web"
    if v2:
        (web / "v2" / "tabs").mkdir(parents=True)
        (web / "v2" / "index.html").write_text("<html>v2</html>")
        (web / "v2" / "app.js").write_text("// app")
        (web / "v2" / "tabs" / "paper.js").write_text("// tab")
    if v1:
        web.mkdir(exist_ok=True)
        (web / "index.html").write_text("<html>v1</html>")
    (tmp_path / "secret.txt").write_text("nope")
    return web


def test_ui_index_prefers_v2_and_falls_back_to_v1(tmp_path, monkeypatch):
    web = _ui_tree(tmp_path, v1=True)
    monkeypatch.setattr(app, "WEB_DIR", web)
    monkeypatch.setattr(app, "V2_DIR", web / "v2")
    assert app.ui_index().read_text() == "<html>v2</html>"          # fresh clone: v2 only → v2
    (web / "v2" / "index.html").unlink()
    assert app.ui_index().read_text() == "<html>v1</html>"          # old checkout with only v1
    (web / "index.html").unlink()
    assert app.ui_index() is None


def test_ui_static_serves_v2_files_and_blocks_traversal(tmp_path, monkeypatch):
    web = _ui_tree(tmp_path)
    monkeypatch.setattr(app, "V2_DIR", web / "v2")
    assert app.ui_static("/app.js").name == "app.js"
    assert app.ui_static("/tabs/paper.js").name == "paper.js"
    assert app.ui_static("/v2/tabs/paper.js").name == "paper.js"    # /v2/... deep links
    assert app.ui_static("/") is None and app.ui_static("/missing.js") is None
    assert app.ui_static("/../../secret.txt") is None               # never escapes dashboard/web/v2
    assert app.ui_static("/v2/../../secret.txt") is None


def test_ui_static_serves_app_v2_prefix(tmp_path, monkeypatch):
    """The hosted workbench's /app/v2/... address works on the local server too."""
    web = _ui_tree(tmp_path)
    monkeypatch.setattr(app, "V2_DIR", web / "v2")
    assert app.ui_static("/app/v2/app.js").name == "app.js"
    assert app.ui_static("/app/v2/tabs/paper.js").name == "paper.js"
    assert app.ui_static("/app/v2/") is None
    assert app.ui_static("/app/v2/../../secret.txt") is None
    assert "/app/v2/" in app.UI_INDEX_PATHS and "/app/v2/index.html" in app.UI_INDEX_PATHS


# ── local vs hosted form ────────────────────────────────────────────────────
def test_state_reports_local_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STUDIES_ROOT", tmp_path / "studies")
    monkeypatch.delenv("SV_DASH_HOSTED", raising=False)
    state = app.build_state()
    assert state["mode"] == "local" and state["local_open"] is True
    monkeypatch.setenv("SV_DASH_HOSTED", "1")
    state = app.build_state()
    assert state["mode"] == "hosted" and state["local_open"] is False


def test_ui_page_marks_only_the_local_form(tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    page.write_text("<html><body>\n<div id=shell></div></body></html>")
    monkeypatch.delenv("SV_DASH_HOSTED", raising=False)
    assert b'<body class="sv-local">' in app.ui_page(page)
    monkeypatch.setenv("SV_DASH_HOSTED", "1")
    assert app.ui_page(page) == page.read_bytes()


def test_shipped_index_carries_a_markable_body_tag():
    """ui_page stamps the marker onto a bare <body>; keep index.html's tag markable."""
    html = (app.V2_DIR / "index.html").read_text(encoding="utf-8")
    assert html.count("<body>") == 1


# ── live server: routes over real HTTP (ephemeral port, the shipped cockpit files) ──
def _get(port: int, path: str):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)   # no proxy involved
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def _serve(monkeypatch, studies_root: Path):
    import threading
    from http.server import ThreadingHTTPServer
    monkeypatch.setattr(app, "STUDIES_ROOT", studies_root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_live_server_serves_app_v2_alias_and_local_state(tmp_path, monkeypatch):
    monkeypatch.delenv("SV_DASH_HOSTED", raising=False)
    root = tmp_path / "studies"
    make_min_study(root, "t_live", path_b=True)
    srv = _serve(monkeypatch, root)
    port = srv.server_address[1]
    try:
        pages = {}
        for path in ("/", "/v2/", "/app/v2/", "/app/v2/?study=t_live", "/app/v2/index.html"):
            code, headers, body = _get(port, path)
            assert code == 200 and headers["Content-Type"].startswith("text/html"), path
            assert b'<body class="sv-local">' in body, path
            pages[path] = body
        assert len(set(pages.values())) == 1                      # one page, every alias

        code, headers, _ = _get(port, "/app/v2?study=t_live")     # no slash → add it, keep query
        assert code == 301 and headers["Location"] == "/app/v2/?study=t_live"

        for path in ("/app.js", "/app/v2/app.js", "/v2/app.js", "/app/v2/tabs/overview.js"):
            code, headers, _ = _get(port, path)
            assert code == 200 and headers["Content-Type"].startswith("text/javascript"), path
        for path in ("/vendor/katex/katex.min.css", "/app/v2/vendor/katex/katex.min.css"):
            code, headers, _ = _get(port, path)
            assert code == 200 and headers["Content-Type"].startswith("text/css"), path

        code, _, body = _get(port, "/api/state")
        state = json.loads(body)
        assert code == 200 and state["mode"] == "local" and state["local_open"] is True
        assert [s["study_id"] for s in state["studies"]] == ["t_live"]

        # hosted-only endpoints do not exist on the local server (the cockpit never calls them there)
        for path in ("/api/chat/ping", "/api/me", "/api/notices", "/app/v2/../../server/app.py"):
            assert _get(port, path)[0] == 404, path
    finally:
        srv.shutdown()
        srv.server_close()


def test_live_server_hosted_form_has_no_local_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("SV_DASH_HOSTED", "1")
    srv = _serve(monkeypatch, tmp_path / "studies")
    port = srv.server_address[1]
    try:
        code, _, body = _get(port, "/app/v2/")
        assert code == 200 and b"<body>" in body and b'<body class="sv-local">' not in body
        state = json.loads(_get(port, "/api/state")[2])
        assert state["mode"] == "hosted" and state["local_open"] is False
    finally:
        srv.shutdown()
        srv.server_close()
