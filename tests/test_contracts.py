"""P0 contract tests: schema validators + validate_handoff + registry."""

from __future__ import annotations

import json

import pytest

from socioverse import HandoffError, available, register, resolve, validate_handoff, write_artifact
from socioverse.engine import registry as reg
from socioverse.schemas import (
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    Modality,
    Observation,
    Persona,
    PopulationBundle,
    ScheduledEvent,
    Scope,
    StudySpec,
)


def test_environment_layer_two_axis_tags():
    layer = EnvironmentLayer(name="tract_local", modality="physical", scope="local")
    assert layer.modality is Modality.PHYSICAL
    assert layer.scope is Scope.LOCAL


def test_scheduled_event_must_reference_real_layer():
    with pytest.raises(ValueError, match="unknown layer"):
        EnvironmentBundle(
            study_id="s",
            provider_ref="x",
            layers=[EnvironmentLayer(name="a", modality="physical", scope="macro")],
            scheduled_events=[ScheduledEvent(at_step=1, target_layer="DOES_NOT_EXIST", op="set")],
        )


def test_broadcast_requires_information_layer():
    # broadcasts but no information layer -> reject
    with pytest.raises(ValueError, match="information-modality layer"):
        EnvironmentBundle(
            study_id="s",
            provider_ref="x",
            layers=[EnvironmentLayer(name="phys", modality="physical", scope="macro")],
            information_program=InformationProgram(
                broadcasts=[Broadcast(message_id="m1", content="hi", at_step=1)]
            ),
        )


def test_broadcast_audience_macro_vs_local():
    macro = Broadcast(message_id="A", content="policy A", audience="all")
    local = Broadcast(message_id="B", content="policy B", audience={"geoid_list": ["17031"]})
    assert macro.is_macro is True
    assert local.is_macro is False


def test_population_unique_id_invariant():
    with pytest.raises(ValueError, match="unique"):
        PopulationBundle(
            study_id="s",
            provider_ref="x",
            personas=[Persona(agent_id="dup"), Persona(agent_id="dup")],
        )


def test_observation_quadrants():
    ob = Observation(
        agent_id="a", step=3,
        macro_physical={"city_race_share": {"w": 0.3}},
        local_information={"inbox": ["x"]},
    )
    q = ob.quadrants_nonempty()
    assert q["macro_physical"] and q["local_information"]
    assert not q["local_physical"] and not q["macro_information"]


def test_validate_handoff_roundtrip(tmp_path):
    spec = StudySpec(study_id="demo", title="t", n_steps=3)
    path = tmp_path / "study.json"
    write_artifact(path, spec)
    loaded = validate_handoff(path, StudySpec)
    assert loaded.study_id == "demo" and loaded.n_steps == 3


def test_validate_handoff_rejects_offcontract(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not": "a study"}), encoding="utf-8")
    with pytest.raises(HandoffError):
        validate_handoff(path, StudySpec)


def test_validate_handoff_missing(tmp_path):
    with pytest.raises(HandoffError, match="missing"):
        validate_handoff(tmp_path / "nope.json", StudySpec)


def test_registry():
    # Snapshot/restore: other tests rely on import-time registrations (chicago.*, opinion.*),
    # so this destructive test must not leak a cleared registry into the rest of the suite.
    snapshot = {k: dict(v) for k, v in reg._REGISTRY.items()}
    try:
        reg.clear()

        @register("decision", "toy")
        class Toy:  # noqa: D401
            pass

        assert resolve("decision", "toy") is Toy
        assert "toy" in available("decision")
        with pytest.raises(KeyError, match="No decision registered"):
            resolve("decision", "missing")
    finally:
        for k in reg._REGISTRY:
            reg._REGISTRY[k].clear()
            reg._REGISTRY[k].update(snapshot.get(k, {}))
