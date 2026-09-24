"""LongitudinalSimulator — the E_t -> B_t -> E_{t+1} loop (the heart of SocioVerse2).

Persistent population P built once; environment E evolves via two channels
(advance_to = exogenous/scheduled, apply = endogenous feedback); each step records a
panel row per agent + an aggregate metrics row. interaction_rounds>1 hosts intra-step
agent-to-agent message exchange (scenario 2); =1 for Schelling.

Every step runs the same five phases, in this order:
  1. exogenous update — ``env.advance_to(t)`` fires the events and broadcasts scheduled for t
     (an intervention enters here, before anyone observes, so a round is decided on one state)
  2. observe        — ``env.observe_batch`` projects E_t onto each agent (modality x scope)
  3. decide         — ``decision.decide_batch`` computes B_t = f(P, E_t, memory), one typed action
  4. apply          — ``env.apply(actions)`` folds the behaviours back in: E_{t+1} = g(E_t, B_t)
  5. record         — memory window + one panel row per agent + one metrics row, to the store
A branch replays phases 1, 4 and 5 from a parent version's stored actions (``_replay_inherited``)
and only starts calling the decision model at its fork step.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..abc.decision import DecisionModel
from ..abc.environment import EnvironmentProvider
from ..abc.population import PopulationProvider
from ..abc.simulator import Simulator
from ..abc.trajectory import MetricCollector, TrajectoryStore
from ..schemas.population import Persona
from ..schemas.runtime import Action
from ..schemas.trajectory import MetricsHistory, TrajectoryRecord
from .memory import AgentMemory


def build_panel_rows(env: EnvironmentProvider, personas: list[Persona], actions, t: int
                     ) -> list[TrajectoryRecord]:
    """One panel row per persona = its current env state + (optional) action at step t.

    Free function so both the loop and the pre-run materializer (engine.materialize_initial)
    build identically shaped rows the store + dashboard already understand.
    """
    act = {a.agent_id: a for a in (actions or [])}
    out = []
    for p in personas:
        a = act.get(p.agent_id)
        out.append(
            TrajectoryRecord(
                agent_id=p.agent_id,
                step=t,
                state=env.agent_state(p.agent_id),
                action_kind=a.kind if a else None,
                action_payload=a.payload if a else {},
            )
        )
    return out


class LongitudinalSimulator(Simulator):
    def __init__(
        self,
        *,
        env: EnvironmentProvider,
        population: PopulationProvider,
        decision: DecisionModel,
        store: TrajectoryStore,
        collector: MetricCollector,
        n_steps: int,
        seed: int = 42,
        interaction_rounds: int = 1,
        memory_window: int = 8,
        metric_columns: list[str] | None = None,
        study_id: str = "study",
        on_step: Any = None,  # optional callback(t, metrics_dict) for progress/streaming
        warm_start: Any = None,  # WarmStartSpec | None — inherit a parent version's steps 0..K
    ):
        self.env = env
        self.population = population
        self.decision = decision
        self.store = store
        self.collector = collector
        self.n_steps = n_steps
        self.seed = seed
        self.interaction_rounds = max(1, interaction_rounds)
        self.memory_window = memory_window
        self.metric_columns = metric_columns
        self.study_id = study_id
        self.on_step = on_step
        self.warm_start = warm_start
        self.memories: dict[str, AgentMemory] = {}

    def materialize_initial(self) -> tuple[list[Persona], list[TrajectoryRecord]]:
        """Instantiate the fixed population P (persistent ids) and the initial environment
        E_0, returning the personas and the t=0 panel rows — WITHOUT opening the store or
        running any step. This is the "instantiate the agents" moment: shared by run() (its
        t=0 setup) and sv-build-population (which materializes the roster before any run).
        Idempotent for deterministic providers (a pure function of the seed)."""
        personas = self.population.build(self.seed)
        self.env.reset(self.seed)
        panel0 = self._panel_rows(personas, actions=None, t=0)
        return personas, panel0

    def run(self) -> MetricsHistory:
        # ---- t=0: fixed P (persistent ids) + initial E_0 ----
        personas, panel0 = self.materialize_initial()
        agent_ids = [p.agent_id for p in personas]
        self.memories = {pid: AgentMemory(pid, self.memory_window) for pid in agent_ids}

        self.store.open()
        rows: list[dict[str, Any]] = []

        m0 = self._collect(personas, actions=[], t=0)
        rows.append(m0)
        self.store.record(panel0)
        self._emit_panel(panel0, 0)

        # ---- branch: inherit steps 1..K from a parent version by replay (no LLM) ----
        start = 1
        if self.warm_start is not None:
            start = self._replay_inherited(personas, agent_ids, rows) + 1

        # ---- longitudinal loop (real decisions from `start`) ----
        for t in range(start, self.n_steps + 1):
            fired = self.env.advance_to(t)                     # ① exogenous update (events + broadcasts)
            if fired:
                self.store.record_events(t, [self._event_note(e) for e in fired])

            last_actions: list[Action] = []
            for r in range(self.interaction_rounds):           # (intra-step interaction rounds)
                obs = self.env.observe_batch(agent_ids, t, r)  # ② observe
                actions = self.decision.decide_batch(obs, self.memories)   # ③ decide: B_t = f(P, E_t)
                self.env.apply(actions)                        # ④ apply: E_{t+1} = g(E_t, B_t)
                last_actions = actions

            for a in last_actions:                             # ⑤ record — memory window first
                self.memories[a.agent_id].push(t, a)

            panel_t = self._panel_rows(personas, last_actions, t)
            self.store.record(panel_t)
            self._emit_panel(panel_t, t)
            m = self._collect(personas, last_actions, t, fired_notes=[self._event_note(e) for e in fired])
            rows.append(m)

        self.store.finalize()
        cols = self.metric_columns or self._infer_columns(rows)
        return MetricsHistory(study_id=self.study_id, rows=rows, schema_columns=cols)

    # --- branch replay (re-derive the parent version's steps, no LLM) ---
    def _replay_inherited(self, personas: list[Persona], agent_ids: list[str],
                          rows: list[dict[str, Any]]) -> int:
        """Re-derive steps 1..K from the parent version's STORED actions (no decide_batch, no
        LLM). Because a Path-B ``env.apply(actions)`` is a pure function of the actions, replaying
        them (a) reproduces the parent trajectory exactly and (b) rehydrates env state to E_K so
        the real loop can continue at K+1. Re-records the panel/metrics/events into the fresh
        store just like a normal step. Returns K (the last inherited step)."""
        ws = self.warm_start
        if self.interaction_rounds != 1:
            raise ValueError(
                f"branch replay supports interaction_rounds == 1 only (study has "
                f"{self.interaction_rounds}); the parent panel keeps only the final round's "
                "actions, so multi-round steps can't be replayed exactly — re-run from step 0.")
        parent_by_step = self._load_parent_panel(ws.source_trajectory, ws.resume_from)
        k = min(int(ws.resume_from), self.n_steps)
        for t in range(1, k + 1):
            fired = self.env.advance_to(t)                     # same events as parent (E unchanged ≤K)
            if fired:
                self.store.record_events(t, [self._event_note(e) for e in fired])
            actions = self._reconstruct_actions(t, parent_by_step.get(t, []))
            self.env.apply(actions)                            # pure replay -> E_t == parent's E_t
            for a in actions:
                self.memories[a.agent_id].push(t, a)
            panel_t = self._panel_rows(personas, actions, t)
            self.store.record(panel_t)
            self._emit_panel(panel_t, t)
            m = self._collect(personas, actions, t,
                              fired_notes=[self._event_note(e) for e in fired])
            rows.append(m)
        return k

    def _reconstruct_actions(self, t: int, parent_rows: list[dict[str, Any]]) -> list[Action]:
        """Rebuild Action objects from a parent step's stored panel rows (kind + payload).
        Rows with no action that step (baseline/idle) are skipped, matching the original run."""
        out = []
        for r in parent_rows:
            kind = r.get("action_kind")
            if kind is None:
                continue
            out.append(Action(agent_id=r["agent_id"], step=t, kind=kind,
                              payload=dict(r.get("action_payload") or {}), source="replay"))
        return out

    @staticmethod
    def _load_parent_panel(db_path: str, upto: int) -> dict[int, list[dict[str, Any]]]:
        """Read the parent trajectory's panel actions for steps 1..upto, grouped by step.

        Source is normally a completed run's ``study.duckdb``; a ``panel_live.jsonl`` path is
        also accepted — that is the per-step stream an INTERRUPTED run leaves behind (budget ran
        out / crash), so pointing warm_start at it resumes the same run from the last completed
        step without re-spending the finished steps.
        """
        if str(db_path).endswith(".jsonl"):
            by_j: dict[int, list[dict[str, Any]]] = {}
            with open(db_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    step = int(r.get("step", -1))
                    if 1 <= step <= int(upto):
                        by_j.setdefault(step, []).append(
                            {"agent_id": r.get("agent_id"), "action_kind": r.get("action_kind"),
                             "action_payload": r.get("action_payload") or {}})
            return by_j
        from ..io.duckdb_store import open_readonly

        con = open_readonly(db_path)
        try:
            rows = con.execute(
                "SELECT agent_id, step, action_kind, action_payload FROM panel "
                "WHERE step >= 1 AND step <= ? ORDER BY step, agent_id", [int(upto)]).fetchall()
        finally:
            con.close()
        by: dict[int, list[dict[str, Any]]] = {}
        for aid, step, ak, ap in rows:
            by.setdefault(int(step), []).append(
                {"agent_id": aid, "action_kind": ak,
                 "action_payload": json.loads(ap) if ap else {}})
        return by

    # --- helpers ---
    def _collect(self, personas, actions, t, fired_notes=None) -> dict[str, Any]:
        m = dict(self.collector.collect(self.env, actions, t))
        m["step"] = t
        if fired_notes:
            note = "; ".join(n for n in fired_notes if n)
            if note:
                m["events"] = note
        self.store.record_metrics(m)
        self._emit_progress(t, m)                          # per-step heartbeat for the dashboard
        if self.on_step:
            self.on_step(t, m)
        return m

    def _emit_progress(self, t: int, metrics: dict[str, Any]) -> None:
        """Best-effort per-step heartbeat for the run dashboard (trajectory/progress.jsonl).

        Fresh file at t=0, one JSONL line per step afterwards; never breaks the run.
        """
        db_path = getattr(self.store, "db_path", None)
        if not db_path:
            return
        try:
            line = json.dumps({"study_id": self.study_id, "step": t, "n_steps": self.n_steps,
                               "ts": time.time(), "metrics": metrics})
            with open(Path(db_path).parent / "progress.jsonl", "w" if t == 0 else "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _emit_panel(self, rows: list[TrajectoryRecord], t: int) -> None:
        """Lock-free per-step agent snapshot for the live dashboard (trajectory/panel_live.jsonl).

        Same rows as the DuckDB panel, appended to a plain file so the dashboard can read each
        agent's state/action mid-run (DuckDB is single-writer-locked while the run is open).
        """
        db_path = getattr(self.store, "db_path", None)
        if not db_path:
            return
        try:
            with open(Path(db_path).parent / "panel_live.jsonl", "w" if t == 0 else "a") as f:
                for r in rows:
                    f.write(json.dumps({"agent_id": r.agent_id, "step": r.step, "state": r.state,
                                        "action_kind": r.action_kind, "action_payload": r.action_payload},
                                       ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _panel_rows(self, personas: list[Persona], actions, t) -> list[TrajectoryRecord]:
        return build_panel_rows(self.env, personas, actions, t)

    @staticmethod
    def _event_note(ev) -> str:
        return ev.note or f"{ev.op} {ev.property_name or ''}".strip()

    @staticmethod
    def _infer_columns(rows: list[dict[str, Any]]) -> list[str]:
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        if "step" in cols:
            cols = ["step"] + [c for c in cols if c != "step"]
        return cols
