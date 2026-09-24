"""P1 smoke test: a deterministic (no-LLM) toy study end-to-end through the engine.

Exercises: persistent ids, the longitudinal loop, all 4 Observation quadrants,
scheduled events, macro+local broadcasts (audience routing), AgentMemory, and the
DuckDB store (panel/metrics/events tables + parquet export).
"""

from __future__ import annotations

from statistics import mean, pvariance

import pytest

from socioverse.abc import (
    DecisionModel,
    EnvironmentProvider,
    MetricCollector,
    PopulationProvider,
)
from socioverse.engine import LongitudinalSimulator
from socioverse.io import DuckDbTrajectoryStore, open_readonly
from socioverse.schemas import (
    Action,
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    Observation,
    Persona,
    PopulationBundle,
    ScheduledEvent,
)

N = 8
BROADCAST_STEP = 2


def _idx(agent_id: str) -> int:
    return int(agent_id.split("-")[1])


class ToyEnv(EnvironmentProvider):
    """Ring of N agents each holding a binary opinion. Demonstrates the 4 quadrants."""

    def __init__(self, bundle: EnvironmentBundle, n: int = N):
        self.bundle = bundle
        self.n = n

    def reset(self, seed: int) -> None:
        self.opinion = [i % 2 for i in range(self.n)]   # alternating
        self.flip_bias = 0.0
        self._fired: set[int] = set()
        self._active: list[Broadcast] = []

    def advance_to(self, t: int):
        fired = []
        for i, ev in enumerate(self.bundle.scheduled_events):
            if ev.at_step <= t and i not in self._fired:
                if ev.property_name == "flip_bias" and ev.op == "set":
                    self.flip_bias = float(ev.value)
                self._fired.add(i)
                fired.append(ev)
        # activate/expire information broadcasts
        for b in self.bundle.information_program.broadcasts:
            if b.at_step == t:
                self._active.append(b)
        self._active = [b for b in self._active if b.at_step + b.ttl > t]
        return fired

    def apply(self, actions) -> None:
        for a in actions:
            if a.kind == "flip":
                i = _idx(a.agent_id)
                self.opinion[i] = 1 - self.opinion[i]

    def observe_batch(self, agent_ids, t, round_idx: int = 0):
        mp = {"mean_opinion": round(mean(self.opinion), 4)}
        macro_info = {b.channel: b.content for b in self._active if b.is_macro}
        out = []
        for aid in agent_ids:
            i = _idx(aid)
            local_info = {}
            for b in self._active:
                if isinstance(b.audience, dict) and i < b.audience.get("index_below", -1):
                    local_info[b.channel] = b.content
            out.append(
                Observation(
                    agent_id=aid,
                    step=t,
                    macro_physical=mp,
                    local_physical={
                        "left": self.opinion[(i - 1) % self.n],
                        "right": self.opinion[(i + 1) % self.n],
                    },
                    macro_information=dict(macro_info),
                    local_information=local_info,
                )
            )
        return out

    def agent_state(self, agent_id: str) -> dict:
        i = _idx(agent_id)
        return {"index": i, "opinion": self.opinion[i]}

    def snapshot(self) -> dict:
        return {"opinion": list(self.opinion)}


class ToyDecision(DecisionModel):
    def decide_batch(self, obs, memories):
        actions = []
        for ob in obs:
            mem = memories.get(ob.agent_id)
            flipped_last = mem is not None and mem.last_action_kind() == "flip"
            nbr_sum = ob.local_physical["left"] + ob.local_physical["right"]
            wants_flip = nbr_sum == 2 or bool(ob.macro_information) or bool(ob.local_information)
            kind = "flip" if (wants_flip and not flipped_last) else "hold"
            actions.append(Action(agent_id=ob.agent_id, step=ob.step, kind=kind, source="rule"))
        return actions


class ToyPop(PopulationProvider):
    def __init__(self, bundle: PopulationBundle, n: int = N):
        self.bundle = bundle
        self.n = n

    def build(self, seed: int):
        return [
            Persona(agent_id=f"ag-{i}", group_key=f"parity_{i % 2}", init_state={"index": i})
            for i in range(self.n)
        ]


class ToyCollector(MetricCollector):
    def collect(self, env, actions, t) -> dict:
        op = env.snapshot()["opinion"]
        return {
            "mean_opinion": round(mean(op), 4),
            "polarization": round(pvariance(op), 4),
            "n_flips": sum(1 for a in actions if a.kind == "flip"),
        }


def _bundles():
    env_bundle = EnvironmentBundle(
        study_id="toy",
        provider_ref="toy.env",
        layers=[
            EnvironmentLayer(name="ring", modality="physical", scope="local"),
            EnvironmentLayer(name="city_avg", modality="physical", scope="macro"),
            EnvironmentLayer(name="news", modality="information", scope="macro"),
            EnvironmentLayer(name="ward_notice", modality="information", scope="local"),
        ],
        scheduled_events=[
            ScheduledEvent(at_step=BROADCAST_STEP, target_layer="city_avg", op="set",
                           property_name="flip_bias", value=1.0, note="policy shock at step 2"),
        ],
        information_program=InformationProgram(broadcasts=[
            Broadcast(message_id="A", channel="news", content="CITY: flip day",
                      at_step=BROADCAST_STEP, ttl=2, audience="all"),
            Broadcast(message_id="B", channel="ward_notice", content="LOCAL: ward notice",
                      at_step=BROADCAST_STEP, ttl=1, audience={"index_below": 3}),
        ]),
    )
    pop_bundle = PopulationBundle(study_id="toy", provider_ref="toy.pop")
    return env_bundle, pop_bundle


def test_four_quadrants_and_audience_routing():
    env_bundle, _ = _bundles()
    env = ToyEnv(env_bundle)
    env.reset(0)
    env.advance_to(BROADCAST_STEP)
    obs = env.observe_batch([f"ag-{i}" for i in range(N)], BROADCAST_STEP)
    for ob in obs:
        q = ob.quadrants_nonempty()
        assert q["macro_physical"] and q["local_physical"]
        assert q["macro_information"], "macro broadcast should reach everyone"
    # local broadcast only reaches index < 3
    assert obs[0].local_information and obs[1].local_information and obs[2].local_information
    assert not obs[3].local_information and not obs[7].local_information


def test_smoke_run(tmp_path):
    env_bundle, pop_bundle = _bundles()
    n_steps = 4
    db = tmp_path / "study.duckdb"
    store = DuckDbTrajectoryStore(db, study_id="toy")
    sim = LongitudinalSimulator(
        env=ToyEnv(env_bundle),
        population=ToyPop(pop_bundle),
        decision=ToyDecision(),
        store=store,
        collector=ToyCollector(),
        n_steps=n_steps,
        interaction_rounds=1,
        study_id="toy",
    )
    hist = sim.run()

    # metrics history: steps 0..n_steps
    assert [r["step"] for r in hist.rows] == list(range(n_steps + 1))
    assert "mean_opinion" in hist.schema_columns and "n_flips" in hist.schema_columns

    con = open_readonly(db)
    panel_rows = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    assert panel_rows == (n_steps + 1) * N
    metrics_rows = con.execute("SELECT count(*) FROM metrics").fetchone()[0]
    assert metrics_rows == n_steps + 1
    ev = con.execute("SELECT note FROM events").fetchall()
    assert any("policy shock" in r[0] for r in ev)
    # panel JSON is queryable per-field (database-like)
    opinions = con.execute(
        "SELECT DISTINCT state->>'opinion' AS o FROM panel ORDER BY o"
    ).fetchall()
    assert {r[0] for r in opinions} <= {"0", "1"}
    # a specific agent's longitudinal trajectory is recoverable
    traj = con.execute(
        "SELECT step, state->>'opinion' FROM panel WHERE agent_id='ag-0' ORDER BY step"
    ).fetchall()
    assert len(traj) == n_steps + 1
    con.close()
    assert (tmp_path / "panel.parquet").exists()
    assert (tmp_path / "metrics.parquet").exists()


def test_store_writes_each_batch_in_one_transaction(tmp_path):
    """A step's rows land together or not at all, and no transaction is left open."""
    from socioverse.schemas.trajectory import TrajectoryRecord

    store = DuckDbTrajectoryStore(tmp_path / "t.duckdb", study_id="toy", export_parquet=False)
    store.open()
    store.record([TrajectoryRecord(agent_id=f"ag-{i}", step=0, state={"x": i}) for i in range(50)])
    store.record_events(0, ["shock"])
    store.record_messages([{"author_id": "ag-0", "step": 0, "content": "hi"}])
    # a batch that fails part-way is rolled back whole ...
    with pytest.raises(Exception):
        store._insert_batch("INSERT INTO events VALUES (?, ?)", [(1, "ok"), ("not-a-step", "bad")])
    # ... and the connection is usable again (a dangling transaction would make BEGIN fail)
    store.record([TrajectoryRecord(agent_id="ag-0", step=1)])
    con = store._con
    assert con.execute("SELECT count(*) FROM panel").fetchone()[0] == 51
    assert con.execute("SELECT note FROM events ORDER BY step").fetchall() == [("shock",)]
    assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    store.finalize()
