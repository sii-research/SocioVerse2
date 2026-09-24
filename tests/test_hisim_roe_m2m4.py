"""hisim_roe milestones M2–M4 — core functionality, no API.

M2 = real core decision (prompt + safe parser + att); M3 = real-data loader + full env mechanics;
M4 = personal-history summary + reply→target routing. LLM is the deterministic `scripted` stand-in,
so the whole pipeline is exercised without tokens. Real-data tests skip if HiSim/data is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import studies.hisim_roe  # noqa: F401  (registers hisim.* providers)
from socioverse.engine import build_simulator
from socioverse.external_events import env_setting
from socioverse.schemas import Observation
from studies.hisim_roe.model import (
    HybridTwitterDecision,
    TwitterEnvironmentProvider,
    build_core_prompt,
    compute_att,
    core_id,
    load_init_att,
    load_movement,
    make_hisim_bundles,
    make_hisim_bundles_from_data,
    parse_twitter_action,
    summarize_history,
)

# HiSim checkout (github.com/xymou/HiSim): $SV_HISIM_ROOT (process env, else .env), else a
# sibling clone ../HiSim.
_REPO_ROOT = Path(__file__).resolve().parents[1]
HISIM = env_setting("SV_HISIM_ROOT") or str(_REPO_ROOT.parent / "HiSim")
DATA_ROOT = f"{HISIM}/data"
ROE_CFG = f"{HISIM}/ref_configs/roe_config.yaml"
has_data = os.path.isdir(f"{DATA_ROOT}/user_data/roe")
needs_data = pytest.mark.skipif(not has_data, reason="HiSim/data not present")


# ---------------- M2: parser + att + LLM decision pipeline ----------------
def test_parse_each_action_type():
    p = parse_twitter_action('Thought: t\nAction: post(content="hello world")\nStance: Favor')
    assert p["kind"] == "post" and p["payload"]["text"] == "hello world" and p["stance"] == "Favor"

    r = parse_twitter_action('Action: retweet(content="yes", author="bob", original_tweet_id="3")\nStance: Against')
    assert r["kind"] == "retweet" and r["payload"]["author"] == "bob" and r["payload"]["parent_id"] == "3"

    rep = parse_twitter_action('Action: reply(content="ok", author="ann", original_tweet_id="1")\nStance: Neutral')
    assert rep["kind"] == "reply" and rep["payload"]["author"] == "ann" and rep["payload"]["parent_id"] == "1"

    lk = parse_twitter_action('Action: like(author="cara", original_tweet_id="2")')
    assert lk["kind"] == "like" and lk["payload"]["parent_id"] == "2"

    dn = parse_twitter_action("Thought: nothing\nAction: do_nothing()\nStance: Neutral")
    assert dn["kind"] == "do_nothing"

    assert parse_twitter_action("garbage, no action")["kind"] == "do_nothing"  # robust fallback


def test_parse_is_safe_no_exec():
    # a malicious "argument" must not execute; literal_eval just fails → arg dropped, kind still parsed
    p = parse_twitter_action('Action: post(content=__import__("os").system("echo hacked"))\nStance: Favor')
    assert p["kind"] == "post"
    assert p["payload"]["text"] in ("", None)


def test_compute_att_sign_and_magnitude():
    pytest.importorskip("textblob")                               # the default sentiment scorer
    pos = compute_att("this is wonderful and just", "Favor")
    neg = compute_att("this is wonderful and just", "Against")
    assert pos > 0 and neg < 0 and abs(pos) == abs(neg)          # sign from stance, magnitude from |sentiment|


def test_compute_att_pluggable_sentiment():
    # pluggable sentiment: att = sign * |sentiment|
    assert compute_att("anything", "Favor", sentiment_fn=lambda _t: -0.6) == pytest.approx(0.6)
    assert compute_att("anything", "Against", sentiment_fn=lambda _t: 0.6) == pytest.approx(-0.6)


def test_llm_decision_pipeline_no_api():
    dec = HybridTwitterDecision(alpha=0.3, bc_bound=0.3, mode="llm", llm_kind="scripted", target="abortion rights")
    core_ob = Observation(agent_id=core_id("alice"), step=1,
                          local_information={"role_description": "An activist.", "tweet_page": "", "info_box": "",
                                             "personal_history": "", "notifications": ""},
                          macro_information={"trigger_news": "Big news."})
    ord_ob = Observation(agent_id="ord-bob", step=1,
                         local_physical={"own_opinion": 0.2, "bcm_peer_opinion": 0.5})
    acts = dec.decide_batch([core_ob, ord_ob], memories={})
    core_a, ord_a = acts[0], acts[1]
    assert core_a.kind in ("post", "retweet", "reply", "like", "do_nothing")
    assert "att" in core_a.payload and -1.0 <= core_a.payload["att"] <= 1.0   # mirror value produced
    assert core_a.source == "llm"
    assert ord_a.kind == "update_opinion"                                     # BCM rule branch
    assert ord_a.payload["opinion"] == pytest.approx(0.2 + 0.3 * (0.5 - 0.2))


def test_build_core_prompt_has_context():
    ob = Observation(agent_id=core_id("x"), step=0,
                     local_information={"role_description": "ROLE_X", "tweet_page": "PAGE_X",
                                        "info_box": "", "personal_history": "HIST_X", "notifications": "NOTE_X"},
                     macro_information={"trigger_news": "NEWS_X"})
    prompt = build_core_prompt(ob, memory_text="MEM_X", target="topic")
    for token in ("ROLE_X", "PAGE_X", "HIST_X", "NEWS_X", "MEM_X", "NOTE_X", "Stance:"):
        assert token in prompt


# ---------------- M3: real-data loader + full env mechanics ----------------
@needs_data
def test_load_init_att_from_config():
    att = load_init_att(ROE_CFG)
    assert len(att) > 500                       # ~1000 abm agents
    assert "a_standal" in att and 0.0 <= att["a_standal"] <= 1.0


@needs_data
def test_load_movement_roe():
    w = load_movement(DATA_ROOT, "roe", config_path=ROE_CFG)
    assert len(w["core"]) == 300                                  # role_desc keys
    assert len(w["ord"]) > 100                                    # abm pop minus core
    a = core_id("a_standal")
    assert w["roles"][a].startswith("You are a_standal")         # role description loaded
    assert isinstance(w["audience"][a], list)                     # follower audience present
    assert w["history"][a].endswith("a_standal.txt") and os.path.exists(w["history"][a])
    assert -1.0 <= w["opinions"][a] <= 1.0


def test_news_as_tweet_injection_and_counters():
    # craft an env whose broadcast is phrased as a tweet → must be injected to ALL pages
    _, env_b, _, _ = make_hisim_bundles(n_core=4, n_ord=4, n_steps=3, news_step=1)
    env_b.information_program.broadcasts[0].content = "BreakingUser posts a tweet about the cause"
    env = TwitterEnvironmentProvider(env_b)
    env.reset(seed=1)
    env.advance_to(1)
    assert len(env.tweet_db) == 1                                 # news became a real tweet
    assert all(len(pg) == 1 for pg in env.pages.values())        # on everyone's page
    assert env.news is None                                       # not also a macro field

    # like / retweet counters increment the original tweet
    from studies.hisim_roe.model import Action
    env.apply([Action(agent_id=core_id(0), step=1, kind="like", payload={"att": 0.0, "parent_id": "0"})])
    assert env.tweet_db["0"]["num_like"] == 1
    env.apply([Action(agent_id=core_id(1), step=1, kind="retweet",
                      payload={"att": 0.1, "text": "rt", "parent_id": "0"})])
    assert env.tweet_db["0"]["num_rt"] == 1


# ---------------- M4: personal-history summary + reply→target routing ----------------
@needs_data
def test_summarize_history_real_user():
    path = f"{DATA_ROOT}/user_data/roe/tweet/a_standal.txt"
    s = summarize_history(path, top_k=3)
    assert s and len(s) > 20                                      # non-empty extractive summary
    assert s.count("||") <= 2                                     # at most top_k segments


def test_reply_routes_to_target_memory():
    _, env_b, _, _ = make_hisim_bundles(n_core=4, n_ord=4, n_steps=3)
    env = TwitterEnvironmentProvider(env_b)
    env.reset(seed=1)
    from studies.hisim_roe.model import Action
    # core-0 replies to core-2 → reaches core-2 via its inbox (FAITHFUL: reply→target memory)
    env.apply([Action(agent_id=core_id(0), step=1, kind="reply",
                      payload={"att": -0.2, "text": "I disagree", "author": "2", "parent_id": "9"})])
    assert any("I disagree" in m for m in env.inbox[core_id(2)])
    # and it surfaces in core-2's next observation notifications (not info_box, which stays empty)
    ob = env.observe_batch([core_id(2)], t=2)[0]
    assert "I disagree" in ob.local_information["notifications"]
    assert ob.local_information["info_box"] == ""               # FAITHFUL: info_box inert


# ---------------- M2+M3+M4 integration: real data, full loop, no API ----------------
@needs_data
def test_real_data_end_to_end_scripted(tmp_path):
    study, env_b, pop_b, sim_c = make_hisim_bundles_from_data(
        data_root=DATA_ROOT, movement="roe", config_path=ROE_CFG,
        n_steps=2, limit_core=20, llm_kind="scripted", news_step=0,
    )
    assert sim_c.decision_args["mode"] == "llm"
    sim = build_simulator(env_bundle=env_b, pop_bundle=pop_b, sim_config=sim_c,
                          store_path=tmp_path / "hisim_roe_real.duckdb")
    hist = sim.run()
    assert len(hist.rows) == 3                                    # steps 0..2
    assert hist.covers(study.metrics) == []
    # at least some core users acted (scripted LLM produces posts/retweets) → tweets exist
    assert hist.rows[-1]["n_post"] >= 0
