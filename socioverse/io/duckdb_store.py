"""DuckDbTrajectoryStore — database-like panel/metrics/events/messages store.

One DuckDB file per study (`trajectory/study.duckdb`) with tables:
  - panel(agent_id, step, state JSON, action_kind, action_payload JSON)  -- longitudinal panel
  - metrics(step, <one column per metric>)                               -- per-step aggregates
  - events(step, note)                                                   -- fired interventions
  - messages(author_id, step, round, channel, content, audience)         -- inter-agent (scenario 2)

Panel rows + events + messages stream in per step (so a reader can attach mid-run);
each batch is written in ONE transaction (DuckDB commits every statement separately in
autocommit mode, which costs one fsync per agent row). The wide metrics table is
materialized at finalize(). Parquet copies are exported for
portability. The reporter (and any later real-time viewer) just opens the same file and
runs SQL — e.g. `SELECT step, state->>'tract_id' FROM panel WHERE agent_id = ?`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import duckdb

from ..abc.trajectory import TrajectoryStore
from ..schemas.trajectory import TrajectoryRecord


class DuckDbTrajectoryStore(TrajectoryStore):
    def __init__(self, db_path: str | Path, study_id: str = "study", export_parquet: bool = True):
        self.db_path = Path(db_path)
        self.study_id = study_id
        self.export_parquet = export_parquet
        self._con: duckdb.DuckDBPyConnection | None = None
        self._metrics_rows: list[dict[str, Any]] = []
        self._messages_created = False

    # --- lifecycle ---
    def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()  # fresh run; baselines are cached elsewhere
        self._con = duckdb.connect(str(self.db_path))
        self._con.execute(
            "CREATE TABLE panel("
            "agent_id VARCHAR, step INTEGER, state JSON, "
            "action_kind VARCHAR, action_payload JSON)"
        )
        self._con.execute("CREATE TABLE events(step INTEGER, note VARCHAR)")

    # --- streaming writes ---
    def _insert_batch(self, sql: str, rows: Sequence[tuple]) -> None:
        """Insert ``rows`` in a single transaction: one commit per batch (per step), not per
        row. A failed batch is rolled back whole, so a reader never sees half a step."""
        con = self._con
        con.execute("BEGIN TRANSACTION")
        try:
            con.executemany(sql, rows)
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")

    def record(self, records: list[TrajectoryRecord]) -> None:
        if not records:
            return
        rows = [
            (r.agent_id, r.step, json.dumps(r.state, ensure_ascii=False),
             r.action_kind, json.dumps(r.action_payload, ensure_ascii=False))
            for r in records
        ]
        self._insert_batch("INSERT INTO panel VALUES (?, ?, ?::JSON, ?, ?::JSON)", rows)

    def record_metrics(self, row: dict[str, Any]) -> None:
        self._metrics_rows.append(dict(row))

    def record_events(self, step: int, notes: list[str]) -> None:
        if notes:
            self._insert_batch("INSERT INTO events VALUES (?, ?)", [(step, n) for n in notes])

    def record_messages(self, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        if not self._messages_created:
            self._con.execute(
                "CREATE TABLE messages("
                "author_id VARCHAR, step INTEGER, round INTEGER, "
                "channel VARCHAR, content VARCHAR, audience VARCHAR)"
            )
            self._messages_created = True
        rows = [
            (m.get("author_id"), m.get("step"), int(m.get("round", 0)),
             m.get("channel", "chat"), m.get("content", ""),
             json.dumps(m.get("audience", "all"), ensure_ascii=False))
            for m in messages
        ]
        self._insert_batch("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)", rows)

    # --- finalize ---
    def finalize(self) -> None:
        self._materialize_metrics()
        if self.export_parquet:
            out = self.db_path.parent
            self._con.execute(
                "COPY (SELECT agent_id, step, CAST(state AS VARCHAR) AS state, "
                "action_kind, CAST(action_payload AS VARCHAR) AS action_payload "
                f"FROM panel) TO '{out / 'panel.parquet'}' (FORMAT PARQUET)"
            )
            if self._metrics_rows:
                self._con.execute(
                    f"COPY (SELECT * FROM metrics) TO '{out / 'metrics.parquet'}' (FORMAT PARQUET)"
                )
        self._con.close()
        self._con = None

    def _materialize_metrics(self) -> None:
        if not self._metrics_rows:
            return
        cols: list[str] = []
        for r in self._metrics_rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        if "step" in cols:
            cols = ["step"] + [c for c in cols if c != "step"]
        import pandas as pd

        df = pd.DataFrame(self._metrics_rows, columns=cols)
        self._con.register("metrics_df", df)
        self._con.execute("CREATE TABLE metrics AS SELECT * FROM metrics_df")
        self._con.unregister("metrics_df")


def open_readonly(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open a finalized study store for querying (reporter / interactive viewer)."""
    return duckdb.connect(str(db_path), read_only=True)
