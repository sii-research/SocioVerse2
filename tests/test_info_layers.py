"""P2 tests: InformationEnvironment audience routing + ttl, match_selector, NeighborFeed."""

from __future__ import annotations

from socioverse.env_layers import (
    InformationEnvironment,
    NeighborFeed,
    local_notice,
    macro_news,
    match_selector,
)
from socioverse.schemas import Action, InformationProgram


def test_match_selector_variants():
    assert match_selector({"race": "nh_black"}, {"race": "nh_black"})
    assert not match_selector({"race": "nh_black"}, {"race": "nh_white"})
    assert match_selector({"geoid_list": ["17031"]}, {"tract_id": "17031"})
    assert match_selector({"income_below": 20000}, {"income": 15000})
    assert not match_selector({"income_below": 20000}, {"income": 30000})
    assert match_selector({"hardship_above": 60}, {"hardship": 70})
    assert not match_selector({}, {"anything": 1})  # empty selector matches nobody


def test_information_environment_scenario1():
    """Policy A to all + policy B to a tract at step n — the two-Broadcast pattern."""
    program = InformationProgram(broadcasts=[
        macro_news("A", "Policy A: citywide", at_step=2, ttl=2),
        local_notice("B", "Policy B: ward only", at_step=2, audience={"geoid_list": ["T1"]}, ttl=1),
    ])
    info = InformationEnvironment(program)
    info.reset()

    # before activation
    info.advance_to(1)
    assert info.macro() == {} and info.local_for({"tract_id": "T1"}) == {}

    # at step 2 both fire
    info.advance_to(2)
    assert info.macro() == {"news": "Policy A: citywide"}
    assert info.local_for({"tract_id": "T1"}) == {"neighbor_feed": "Policy B: ward only"}
    assert info.local_for({"tract_id": "T2"}) == {}   # other tract sees no local notice
    # an out-of-tract agent still sees the macro policy via rendered_lines
    assert any("Policy A" in ln for ln in info.rendered_lines({"tract_id": "T2"}))
    assert not any("Policy B" in ln for ln in info.rendered_lines({"tract_id": "T2"}))

    # step 3: local notice (ttl=1) expired; macro (ttl=2) still active
    info.advance_to(3)
    assert info.macro() == {"news": "Policy A: citywide"}
    assert info.local_for({"tract_id": "T1"}) == {}

    # step 4: macro expired too
    info.advance_to(4)
    assert info.macro() == {}


def test_neighbor_feed_mediated_messaging():
    graph = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
    feed = NeighborFeed(neighbors_fn=lambda x: graph.get(x, []))
    posts = feed.ingest(
        [Action(agent_id="a", step=1, kind="post", payload={"content": "hello from a"}, source="rule")],
        step=1, round_idx=0,
    )
    assert len(posts) == 1
    # b is a's neighbour -> sees the post next step; c is not a's neighbour -> doesn't
    assert feed.local_for("b", t=2) == {"feed": [{"from": "a", "content": "hello from a"}]}
    assert feed.local_for("c", t=2) == {}
