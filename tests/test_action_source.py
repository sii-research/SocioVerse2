"""The panel keeps each action's ``Action.source``; a branch's inherited steps read ``replay``.

The column is written by the engine, so a study's model never has to copy the tag itself, and the
replayed prefix stays identical to the parent's state / action / payload.
"""

from __future__ import annotations

import json

import duckdb

import studies.opinion_diffusion  # noqa: F401 — registers opinion.* refs
from socioverse.engine import build_simulator
from socioverse.io.duckdb_store import open_readonly
from socioverse.schemas import SimulationConfig, WarmStartSpec
from studies.opinion_diffusion.model import make_opinion_bundles


def _cfg(n_steps, *, warm_start=None):
    return SimulationConfig(
        study_id="opinion_diffusion", n_steps=n_steps, seed=7,
        decision_ref="opinion.decision", decision_args={"confidence": 0.3},
        collector_ref="opinion.collector", interaction_rounds=1, warm_start=warm_start)


def _rows(db):
    con = open_readonly(str(db))
    try:
        return con.execute("SELECT agent_id, step, state, action_kind, action_payload, action_source "
                           "FROM panel ORDER BY step, agent_id").fetchall()
    finally:
        con.close()


def _run(env_b, pop_b, db, n_steps, warm_start=None):
    build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=_cfg(n_steps, warm_start=warm_start),
                    store_path=db).run()


def test_panel_records_source_and_branch_prefix_reads_replay(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=10, n_steps=6)
    parent = tmp_path / "parent.duckdb"
    _run(env_b, pop_b, parent, 6)
    p_rows = _rows(parent)

    # step 0 has no action; every decided step carries the model's own tag (never "replay")
    assert {r[5] for r in p_rows if r[1] == 0} == {None}
    p_sources = {r[5] for r in p_rows if r[1] > 0}
    assert p_sources and None not in p_sources and "replay" not in p_sources

    child = tmp_path / "child.duckdb"
    ws = WarmStartSpec(source_version="v1", source_trajectory=str(parent), resume_from=3)
    _run(env_b, pop_b, child, 6, warm_start=ws)
    c_rows = _rows(child)

    inherited = [r for r in c_rows if 1 <= r[1] <= 3]
    assert inherited and {r[5] for r in inherited} == {"replay"}
    # the replayed prefix is identical to the parent apart from the source column
    assert [r[:5] for r in c_rows if r[1] <= 3] == [r[:5] for r in p_rows if r[1] <= 3]
    # steps after the fork were decided again, so they carry the model's tags
    assert {r[5] for r in c_rows if r[1] >= 4} <= p_sources


def test_replay_accepts_a_parent_store_without_the_column(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=8, n_steps=4)
    parent = tmp_path / "parent.duckdb"
    _run(env_b, pop_b, parent, 4)
    con = duckdb.connect(str(parent))
    con.execute("ALTER TABLE panel DROP COLUMN action_source")   # a store written before the column
    old = con.execute("SELECT agent_id, step, state, action_kind, action_payload "
                      "FROM panel ORDER BY step, agent_id").fetchall()
    con.close()

    child = tmp_path / "child.duckdb"
    ws = WarmStartSpec(source_version="v1", source_trajectory=str(parent), resume_from=2)
    _run(env_b, pop_b, child, 4, warm_start=ws)
    c_rows = _rows(child)
    assert [r[:5] for r in c_rows if r[1] <= 2] == [r for r in old if r[1] <= 2]
    assert {r[5] for r in c_rows if 1 <= r[1] <= 2} == {"replay"}


def test_live_stream_and_parquet_carry_the_column(tmp_path):
    _, env_b, pop_b, _ = make_opinion_bundles(n_agents=6, n_steps=3)
    db = tmp_path / "trajectory" / "study.duckdb"
    _run(env_b, pop_b, db, 3)

    live = [json.loads(line) for line in (db.parent / "panel_live.jsonl").read_text().splitlines() if line]
    assert all("action_source" in r for r in live)
    assert {r["action_source"] for r in live if r["step"] > 0} - {None}

    pq = db.parent / "panel.parquet"
    if pq.exists():
        cols = [c[0] for c in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{pq}')").fetchall()]
        assert "action_source" in cols
