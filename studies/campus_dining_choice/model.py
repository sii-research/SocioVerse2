"""campus_dining_choice — a FROM-SCRATCH SocioVerse2 study (Path B).

How do the main dining mode (canteen / food delivery / cooking for oneself) and consumer satisfaction of about
150 students in a university town evolve in an information environment where the campus canteen raises prices
month by month and local food delivery gets more expensive over the same period? Expressed in the B = f(P, E) kernel:

  - P : a FIXED pool of ~150 students with persistent ids `stu-000`… — 5 archetypes (canteen regulars /
        delivery regulars / budget savers / off-campus home cooks / variety-seeking foodies), each with a monthly
        food budget, price sensitivity, ability/willingness to cook, time pressure and a habitual dining mode.
        Optionally assigned to **dorm-style random groups** (mixed across archetypes) for in-group discussion.
  - E : two exogenous information axes + an endogenous social axis:
        * macro_physical    — this month's per-meal price of the three dining modes, raised by a monthly ScheduledEvent.
        * macro_information — the canteen price-increase notice / price-cap notice + delivery price news (Broadcast).
        * local_information — last month's dining distribution among similar classmates (cohort_trend) + **this month's
          dorm discussion** (dorm_chat: roommates' "leaning + one-sentence reason" in the current round, passed between
          rounds via the MessageBus).
  - B : every month each student (LLM role-play, one call per student, sent concurrently) picks one of canteen / delivery / cook + a 0–1 satisfaction.
        When `interaction_rounds > 1`, each month has several rounds: everyone states a position first, then adjusts
        round by round after seeing **their roommates' leanings and reasons**; the last round's choice is recorded
        (decide after the group deliberates). `apply()` folds back into the environment and posts each person's
        "leaning + reason" to the MessageBus so the same dorm sees it in the next round.

The DecisionModel calls GPT for real (`llm_kind="openai"`); a deterministic `scripted` stand-in
(random-utility + a dorm conformity term) exercises the same prompt→parse→apply pipeline for free. Wiring is
generic: each provider takes only its bundle, so `socioverse.engine.build_simulator` assembles it
with zero glue. Factory defaults give a single-round study; multi-round discussion and a
mid-course "price cap" intervention are opt-in factory parameters (the shipped run uses both).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import re
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from socioverse.abc import (
    DecisionModel,
    EnvironmentProvider,
    MetricCollector,
    PopulationProvider,
)
from socioverse.engine import register
from socioverse.engine.messaging import InMemoryMessageBus
from socioverse.schemas import (
    Action,
    Broadcast,
    EnvironmentBundle,
    EnvironmentLayer,
    InformationProgram,
    InteractionStructure,
    Observation,
    Persona,
    PopulationBundle,
    PropagationMode,
    ScheduledEvent,
    SimulationConfig,
    StudySpec,
)

MODES = ("canteen", "delivery", "cook")
MODE_LABEL = {"canteen": "食堂就餐", "delivery": "点外卖", "cook": "自己做饭"}
MODE_PRICE_KEY = {"canteen": "canteen", "delivery": "delivery", "cook": "cook"}

# ================================================================================================
# P — student archetypes (shares sum to 1; indices are assigned by cumulative share and scale with n)
# ================================================================================================
ARCHETYPES: list[dict[str, Any]] = [
    {"key": "canteen_regular", "label": "食堂党（常规校内就餐）", "share": 0.42,
     "budget": 750, "price_sens": 0.55, "cook_feas": 0.35, "cook_skill": 0.35, "time_press": 0.50,
     "pref": {"canteen": 0.60, "delivery": 0.30, "cook": 0.10}, "base_choice": "canteen"},
    {"key": "delivery_lover", "label": "外卖党（重度外卖、图省事）", "share": 0.24,
     "budget": 950, "price_sens": 0.35, "cook_feas": 0.25, "cook_skill": 0.25, "time_press": 0.70,
     "pref": {"canteen": 0.30, "delivery": 0.60, "cook": 0.10}, "base_choice": "delivery"},
    {"key": "budget_saver", "label": "省钱型（预算紧、价格敏感）", "share": 0.16,
     "budget": 520, "price_sens": 0.82, "cook_feas": 0.50, "cook_skill": 0.50, "time_press": 0.45,
     "pref": {"canteen": 0.50, "delivery": 0.15, "cook": 0.35}, "base_choice": "canteen"},
    {"key": "off_campus_cook", "label": "校外自炊（有厨房、会做饭）", "share": 0.11,
     "budget": 820, "price_sens": 0.50, "cook_feas": 0.90, "cook_skill": 0.75, "time_press": 0.40,
     "pref": {"canteen": 0.25, "delivery": 0.20, "cook": 0.55}, "base_choice": "cook"},
    {"key": "foodie", "label": "吃货多样（重口味、追求多样）", "share": 0.07,
     "budget": 1150, "price_sens": 0.25, "cook_feas": 0.30, "cook_skill": 0.35, "time_press": 0.55,
     "pref": {"canteen": 0.30, "delivery": 0.55, "cook": 0.15}, "base_choice": "delivery"},
]
ARCH_BY_KEY = {a["key"]: a for a in ARCHETYPES}


def agent_id(i: int) -> str:
    return f"stu-{i:03d}"


def archetype_of(i: int, n: int) -> dict[str, Any]:
    cum = 0.0
    for a in ARCHETYPES:
        cum += a["share"]
        if i < round(cum * n):
            return a
    return ARCHETYPES[-1]


def _jitter(rng: random.Random, x: float, lo: float, hi: float, spread: float = 0.12) -> float:
    return round(min(hi, max(lo, x + rng.uniform(-spread, spread))), 3)


def sample_student(i: int, seed: int, n: int) -> dict[str, Any]:
    """Deterministic given (seed, i, n): identical whether called by population or env."""
    rng = random.Random(f"{seed}|stu|{i}|{n}")
    a = archetype_of(i, n)
    return {
        "archetype": a["key"], "archetype_label": a["label"],
        "monthly_food_budget": int(a["budget"] + rng.randint(-90, 90)),   # grounding: f-monthly-food-budget
        "price_sensitivity": _jitter(rng, a["price_sens"], 0.05, 0.98),   # grounding: f-fafh-elasticity
        "cook_feasibility": _jitter(rng, a["cook_feas"], 0.10, 0.98),
        "cook_skill": _jitter(rng, a["cook_skill"], 0.05, 0.95),
        "time_pressure": _jitter(rng, a["time_press"], 0.10, 0.95),
        "meals_per_month": rng.randint(26, 34),
        "pref": dict(a["pref"]), "base_choice": a["base_choice"],
    }


# ================================================================================================
# dorm-style random groups (deterministic random partition) — each group is a discussion/propagation network
# ================================================================================================
DORM_SIZE = 6


def dorm_assignment(n: int, seed: int) -> dict[int, int]:
    rng = random.Random(f"{seed}|dorm|{n}")
    idx = list(range(n))
    rng.shuffle(idx)
    return {i: pos // DORM_SIZE for pos, i in enumerate(idx)}


def dorm_members(n: int, seed: int) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for i, d in dorm_assignment(n, seed).items():
        out.setdefault(d, []).append(i)
    return out


def dorm_edges(n: int, seed: int) -> list[tuple[str, str]]:
    """Within-dorm undirected edges (each dorm a small clique) — the interaction structure."""
    edges = []
    for members in dorm_members(n, seed).values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                edges.append((agent_id(members[a]), agent_id(members[b])))
    return edges


def dorm_neighbors(n: int, seed: int) -> dict[str, list[str]]:
    """aid -> its dorm-mates (excluding self) — how discussion messages are routed."""
    members, assign, out = dorm_members(n, seed), dorm_assignment(n, seed), {}
    for i in range(n):
        out[agent_id(i)] = [agent_id(j) for j in members[assign[i]] if j != i]
    return out


# ================================================================================================
# scripted decision — random-utility over {canteen, delivery, cook} + a dorm conformity term
# ================================================================================================
W_PREF, W_AFFORD, W_EFFORT, W_PEER = 1.0, 1.25, 0.55, 0.22
W_DORM = 0.6        # dorm-discussion conformity weight (scripted path; the more concentrated the group's leaning, the stronger the pull)
TAU = 0.45          # logit temperature (fixed per agent+step → stable across rounds; discussion converges through the conformity term)


def _unit_hash(key: str) -> float:
    return (int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % 10**9) / 10**9


def _gumbel(key: str) -> float:
    u = min(1.0 - 1e-9, max(1e-9, _unit_hash(key)))
    return -math.log(-math.log(u))


def _affordability(price: float, meals: int, budget: float) -> float:
    return max(-1.0, min(1.0, 1.0 - (price * meals) / max(budget, 1.0)))


def _effort(mode: str, attrs: dict[str, Any]) -> float:
    tp = attrs["time_pressure"]
    if mode == "cook":
        return (1.0 - attrs["cook_skill"]) * (0.4 + 0.6 * tp) + (1.0 - attrs["cook_feasibility"]) * 0.8
    if mode == "canteen":
        return 0.15 + 0.20 * tp
    return 0.10


def _dorm_lean(dorm_chat: list[dict] | None) -> dict[str, float]:
    """Fraction of dorm-mates currently leaning each mode (from their posted messages)."""
    lean = {m: 0.0 for m in MODES}
    if not dorm_chat:
        return lean
    for d in dorm_chat:
        if d.get("lean") in lean:
            lean[d["lean"]] += 1.0
    tot = sum(lean.values()) or 1.0
    return {m: lean[m] / tot for m in MODES}


def _utilities(attrs: dict[str, Any], prices: dict[str, float],
               cohort: dict[str, float] | None, dorm: dict[str, float] | None = None) -> dict[str, float]:
    meals, budget = attrs["meals_per_month"], attrs["monthly_food_budget"]
    afford_w = 0.6 + attrs["price_sensitivity"]
    cohort = cohort or {m: 0.0 for m in MODES}
    dorm = dorm or {m: 0.0 for m in MODES}
    u: dict[str, float] = {}
    for m in MODES:
        price = prices[MODE_PRICE_KEY[m]]
        u[m] = (W_PREF * attrs["pref"][m]
                + W_AFFORD * afford_w * _affordability(price, meals, budget)
                - W_EFFORT * _effort(m, attrs)
                + W_PEER * cohort.get(m, 0.0)
                + W_DORM * dorm.get(m, 0.0))       # dorm-discussion conformity
    return u


def _satisfaction(attrs: dict[str, Any], mode: str, prices: dict[str, float]) -> float:
    price = prices[MODE_PRICE_KEY[mode]]
    afford = _affordability(price, attrs["meals_per_month"], attrs["monthly_food_budget"])
    s = 0.38 + 0.34 * attrs["pref"][mode] + 0.34 * afford - 0.20 * _effort(mode, attrs)
    return round(max(0.0, min(1.0, s)), 3)


def _scripted_reply(ob: Observation) -> str:
    attrs = ob.local_physical["profile"]
    prices = ob.macro_physical["prices"]
    li = ob.local_information or {}
    dorm = _dorm_lean(li.get("dorm_chat"))
    u = _utilities(attrs, prices, li.get("cohort_trend"), dorm)
    # intrinsic taste noise fixed within a month (keyed agent+step) → discussion converges round by round through the dorm conformity term
    mode = max(MODES, key=lambda m: u[m] + TAU * _gumbel(f"{ob.agent_id}|{ob.step}|{m}"))
    reason = {
        "canteen": "食堂虽然涨了但仍比外卖划算，先保食堂",
        "delivery": "还是习惯点外卖，图个省事和口味",
        "cook": "外卖食堂都在涨，自己做饭最省钱",
    }[mode]
    return json.dumps({"choice": mode, "satisfaction": _satisfaction(attrs, mode, prices),
                       "reason": reason}, ensure_ascii=False)


# ================================================================================================
# LLM prompt + parser (the real simulation path)
# ================================================================================================
def build_student_prompt(ob: Observation) -> str:
    a = ob.local_physical["profile"]
    st = ob.local_physical["state"]
    p = ob.macro_physical["prices"]
    li = ob.local_information or {}
    meals = a["meals_per_month"]
    info_lines = []
    if ob.macro_information.get("canteen_notice"):
        info_lines.append(f"- 食堂公告：{ob.macro_information['canteen_notice']}")
    if ob.macro_information.get("delivery_news"):
        info_lines.append(f"- 外卖行情：{ob.macro_information['delivery_news']}")
    info_block = "\n".join(info_lines) if info_lines else "-（本月无特别消息）"
    cohort = li.get("cohort_trend")
    cohort_line = ""
    if cohort:
        trend = "、".join(f"{MODE_LABEL[m]}{cohort.get(m, 0) * 100:.0f}%" for m in MODES)
        cohort_line = f"\n【身边同学（{li.get('cohort_label', '同类')}）上月就餐分布】\n- {trend}"
    # dorm-discussion section (multi-round)
    r = int(li.get("round", 0))
    dorm_chat = li.get("dorm_chat") or []
    if r == 0:
        dorm_block = ("\n【本月宿舍讨论 · 第1轮】\n- 讨论刚开始，先说说你此刻倾向哪种就餐方式、为什么"
                      "（你的这句话会分享给同宿舍同学）。")
    elif dorm_chat:
        says = "\n".join(f"- 舍友{i + 1}：倾向{MODE_LABEL.get(d.get('lean'), '?')}——{d.get('reason', '')}"
                         for i, d in enumerate(dorm_chat))
        dorm_block = (f"\n【本月宿舍讨论 · 第{r + 1}轮】你的舍友们目前的想法：\n{says}\n"
                      "- 综合舍友的看法，给出你本轮的倾向（可坚持，也可被说服改变）。")
    else:
        dorm_block = f"\n【本月宿舍讨论 · 第{r + 1}轮】（暂无舍友发言）"
    last = st.get("choice")
    last_line = (f"- 上月你的主要就餐方式：{MODE_LABEL.get(last, last)}"
                 f"（满意度 {st.get('satisfaction', '—')}）" if last else "-（本月为首次记录）")
    return (
        "你是一名大学生。请完全代入以下身份，只依据给出的信息，决定你【本月主要的就餐方式】，不要跳出角色。\n\n"
        "【你的情况】\n"
        f"- 画像：{a['archetype_label']}\n"
        f"- 每月餐饮预算：约 {a['monthly_food_budget']} 元\n"
        f"- 价格敏感度：{a['price_sensitivity']:.2f}（0–1，越高越在意价格）\n"
        f"- 做饭可行性/意愿：宿舍/住处做饭方便度 {a['cook_feasibility']:.2f}、做饭能力 {a['cook_skill']:.2f}\n"
        f"- 时间压力：{a['time_pressure']:.2f}（越高越没空排队/做饭）\n\n"
        "【本月三种就餐方式的单餐花费】（按每月约 %d 顿主餐估算月支出）\n"
        "- 食堂就餐：约 %.1f 元/餐\n- 点外卖：约 %.1f 元/单\n- 自己做饭：约 %.1f 元/餐（食材，另需时间精力）\n\n"
        "【本月信息环境】\n%s%s%s\n\n"
        "【你的近况】\n%s\n\n"
        "【本月决策】在下面三选一，并给出你对本月就餐的满意度（0–1）：\n"
        "1. canteen（以食堂为主）  2. delivery（以点外卖为主）  3. cook（以自己做饭为主）\n"
        "请综合：价格与预算、口味与省事、做饭是否现实、以及舍友们的讨论。\n"
        "严格输出如下 JSON，不要包含多余文字（reason 会作为你分享给舍友的一句话）：\n"
        '{"choice": "canteen"|"delivery"|"cook", "satisfaction": <0~1的数>, "reason": "<一句话理由>"}'
    ) % (meals, p["canteen"], p["delivery"], p["cook"], info_block, cohort_line, dorm_block, last_line)


# The reason recorded when a reply does not parse is written in the prompt's language, so an
# English study's panel never gets a Chinese filler line. The shipped build_student_prompt is
# Chinese, so this template records the "zh" text; a copy whose prompt is English gets "en".
_FALLBACK_REASON = {
    "zh": "（作答未解析，维持上月选择）",
    "en": "(reply not parsed; kept last month's choice)",
}


def _prompt_lang(prompt: str) -> str:
    """'zh' when the prompt contains CJK characters, otherwise 'en'."""
    return "zh" if re.search(r"[\u4e00-\u9fff]", prompt) else "en"


_CHOICE_SYNONYMS = {
    "canteen": ["canteen", "食堂"], "delivery": ["delivery", "外卖", "点外卖"],
    "cook": ["cook", "自己做", "做饭", "自炊", "自己做饭"],
}


def parse_decision(resp: str) -> dict[str, Any] | None:
    if not resp:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", resp.strip(), flags=re.M).strip()
    obj: dict[str, Any] = {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
        except Exception:
            obj = {}
    raw = str(obj.get("choice", "")).strip().lower()
    choice = None
    for mode, syns in _CHOICE_SYNONYMS.items():          # prefer the JSON choice field
        if any(s in raw for s in syns):
            choice = mode
            break
    if choice is None:                                    # fall back to the full text only when the field is missing
        for mode, syns in _CHOICE_SYNONYMS.items():
            if any(s in text for s in syns):
                choice = mode
                break
    if choice is None:
        return None
    try:
        sat = float(obj.get("satisfaction"))
    except (TypeError, ValueError):
        sat = 0.5
    return {"choice": choice, "satisfaction": round(max(0.0, min(1.0, sat)), 3),
            "reason": str(obj.get("reason", "")).strip()[:80]}


# ================================================================================================
# P — the fixed student pool
# ================================================================================================
@register("population", "campus_dining_choice.pop")
class DiningPopulationProvider(PopulationProvider):
    def __init__(self, bundle: PopulationBundle):
        self.bundle = bundle
        self.n = int(bundle.provider_args.get("n_agents", 150))

    def build(self, seed: int) -> list[Persona]:
        out = []
        for i in range(self.n):
            attrs = sample_student(i, seed, self.n)
            out.append(Persona(
                agent_id=agent_id(i), group_key=attrs["archetype"], attributes=attrs,
                init_state={"choice": attrs["base_choice"], "satisfaction": None, "monthly_spend": None},
            ))
        return out

    def interaction_structure(self) -> InteractionStructure:
        return self.bundle.interaction


# ================================================================================================
# E — the dining environment (prices + per-student state + the dorm-discussion MessageBus)
# ================================================================================================
@register("environment", "campus_dining_choice.env")
class DiningEnvironmentProvider(EnvironmentProvider):
    def __init__(self, bundle: EnvironmentBundle):
        self.bundle = bundle
        pa = bundle.provider_args
        self.n = int(pa.get("n_agents", 150))
        self.seed = 42
        self.base_prices = {
            "canteen": float(pa.get("base_canteen", 12.0)),     # grounding: f-canteen-meal
            "delivery": float(pa.get("base_delivery", 25.0)),   # grounding: f-delivery-order
            "cook": float(pa.get("base_cook", 7.0)),            # grounding: a-cook-cost
        }
        self.prices: dict[str, float] = {}
        self.students: dict[str, dict[str, Any]] = {}
        self.choice: dict[str, str] = {}
        self.satis: dict[str, float] = {}
        self.spend: dict[str, float] = {}
        self.cohort_shares: dict[str, dict[str, float]] = {}
        self.canteen_notice: str | None = None
        self.delivery_news: str | None = None
        self.dorm_mates: dict[str, list[str]] = {}
        self.bus: InMemoryMessageBus | None = None
        self._round = 0
        self._fired: set[int] = set()
        self._t = 0

    def reset(self, seed: int) -> None:
        self.seed = seed
        self.prices = dict(self.base_prices)
        self.students = {agent_id(i): sample_student(i, seed, self.n) for i in range(self.n)}
        self.choice = {aid: a["base_choice"] for aid, a in self.students.items()}
        self.satis = {aid: _satisfaction(a, a["base_choice"], self.prices) for aid, a in self.students.items()}
        self.spend = {aid: round(self.prices[MODE_PRICE_KEY[a["base_choice"]]] * a["meals_per_month"])
                      for aid, a in self.students.items()}
        self.cohort_shares = {}
        self.canteen_notice = self.delivery_news = None
        self.dorm_mates = dorm_neighbors(self.n, seed)
        self.bus = InMemoryMessageBus(carry_previous_step=False)
        self._round = 0
        self._fired = set()
        self._t = 0

    def _apply_price_event(self, ev: ScheduledEvent) -> None:
        key = ev.target_layer.replace("_price", "").replace("_cost", "")
        if key not in self.prices:               # e.g. "canteen_cap" marker → no-op (just recorded)
            return
        v = float(ev.value) if ev.value is not None else 0.0
        if ev.op == "multiply":
            self.prices[key] = round(self.prices[key] * v, 3)
        elif ev.op == "add":
            self.prices[key] = round(self.prices[key] + v, 3)
        elif ev.op == "add_pct":
            self.prices[key] = round(self.prices[key] * (1.0 + v / 100.0), 3)
        elif ev.op == "set":
            self.prices[key] = round(v, 3)

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        self._t = t
        self._round = 0
        self.bus = InMemoryMessageBus(carry_previous_step=False)   # a fresh discussion every month
        self.cohort_shares = self._compute_cohort_shares()
        fired: list[ScheduledEvent] = []
        for ev in self.bundle.scheduled_events:
            if ev.at_step == t and id(ev) not in self._fired:
                self._apply_price_event(ev)
                self._fired.add(id(ev))
                fired.append(ev)

        def _active(channel: str) -> str | None:
            act = [b.content for b in self.bundle.information_program.broadcasts
                   if b.channel == channel and b.at_step <= t < b.at_step + b.ttl]
            return act[-1] if act else None                        # the latest effective entry overrides older ones
        self.canteen_notice = _active("canteen_notice")
        self.delivery_news = _active("delivery_news")
        return fired

    def _compute_cohort_shares(self) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[str]] = {}
        for aid, a in self.students.items():
            buckets.setdefault(a["archetype"], []).append(self.choice[aid])
        return {k: {m: round(sum(c == m for c in cs) / (len(cs) or 1), 3) for m in MODES}
                for k, cs in buckets.items()}

    def _dorm_chat(self, aid: str, t: int, r: int) -> list[dict]:
        """Latest post per dorm-mate from earlier rounds of this month."""
        if self.bus is None or r == 0:
            return []
        msgs = self.bus.visible_to(aid, self.dorm_mates.get(aid, []), step=t, round_idx=r)
        latest: dict[str, dict] = {}
        for m in msgs:
            au = m.get("author_id")
            if au and (au not in latest or m.get("round", 0) > latest[au].get("round", 0)):
                latest[au] = m
        return [{"lean": m.get("lean"), "reason": m.get("content", "")} for m in latest.values()]

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        self._round = round_idx
        macro_info: dict[str, Any] = {}
        if self.canteen_notice:
            macro_info["canteen_notice"] = self.canteen_notice
        if self.delivery_news:
            macro_info["delivery_news"] = self.delivery_news
        out = []
        for aid in agent_ids:
            a = self.students[aid]
            local_info = {"cohort_trend": self.cohort_shares.get(a["archetype"]),
                          "cohort_label": ARCH_BY_KEY[a["archetype"]]["label"],
                          "round": round_idx, "dorm_chat": self._dorm_chat(aid, t, round_idx)}
            out.append(Observation(
                agent_id=aid, step=t,
                local_physical={"profile": a,
                                "state": {"choice": self.choice[aid], "satisfaction": self.satis[aid]}},
                macro_physical={"prices": dict(self.prices)},
                macro_information=dict(macro_info), local_information=local_info,
            ))
        return out

    def apply(self, actions: list[Action]) -> None:
        for act in actions:
            aid = act.agent_id
            a = self.students.get(aid)
            if a is None:
                continue
            mode = (act.payload or {}).get("choice")
            if mode not in MODES:
                continue
            self.choice[aid] = mode                          # provisional this round; last round = final
            sat = (act.payload or {}).get("satisfaction")
            self.satis[aid] = float(sat) if sat is not None else self.satis[aid]
            self.spend[aid] = round(self.prices[MODE_PRICE_KEY[mode]] * a["meals_per_month"])
            if self.bus is not None:                         # post the "leaning + reason" so the same dorm sees it next round
                self.bus.post({"author_id": aid, "step": self._t, "round": self._round,
                               "lean": mode, "content": (act.payload or {}).get("reason", "")})

    def agent_state(self, aid: str) -> dict:
        a = self.students.get(aid, {})
        return {"archetype": a.get("archetype"), "monthly_food_budget": a.get("monthly_food_budget"),
                "price_sensitivity": a.get("price_sensitivity"), "choice": self.choice.get(aid),
                "choice_label": MODE_LABEL.get(self.choice.get(aid, "")),
                "satisfaction": self.satis.get(aid), "monthly_spend": self.spend.get(aid)}

    def snapshot(self) -> dict:
        n = len(self.choice) or 1
        return {"prices": dict(self.prices),
                "shares": {m: round(sum(c == m for c in self.choice.values()) / n, 3) for m in MODES},
                "mean_satisfaction": round(mean(self.satis.values()), 3) if self.satis else None}


# ================================================================================================
# B — the decision model (GPT role-play; scripted stand-in); called once per round by the loop
# ================================================================================================
_log = logging.getLogger(__name__)


def _load_dotenv(root: Path | None = None) -> None:
    """Hydrate SV_LLM_* from `.env` without overriding the process env: `root/.env` when
    given, else the documented lookup order ($SV_HOME/.env, ./.env, then the repo root)."""
    from socioverse.external_events import _load_dotenv as load

    load(root)


class _OpenAILLM:
    def __init__(self, model: str | None = None, temperature: float = 0.6, max_tokens: int = 220):
        _load_dotenv()
        self.model = model or os.environ.get("SV_LLM_MODEL", "gpt-4o")
        self.temperature, self.max_tokens = temperature, max_tokens
        self._client = None

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("SV_LLM_BASE_URL", "https://api.openai.com/v1"))
        return self._client

    def __call__(self, prompt: str) -> str:
        resp = self._ensure().chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""


def _make_llm(kind: str, **kw) -> Callable[[str], str] | None:
    if kind == "scripted":
        return None
    if kind == "openai":
        return _OpenAILLM(**kw)
    raise ValueError(f"unknown llm_kind: {kind!r}")


@register("decision", "campus_dining_choice.decision")
class DiningDecision(DecisionModel):
    def __init__(self, llm_kind: str = "scripted", model: str | None = None,
                 temperature: float = 0.6, max_tokens: int = 220, max_workers: int = 8):
        self.llm_kind = llm_kind
        self.max_workers = max(1, int(max_workers))
        self.llm = _make_llm(llm_kind, model=model, temperature=temperature, max_tokens=max_tokens)

    def _ask(self, ob: Observation) -> tuple[Observation, str]:
        if self.llm is None:
            return ob, _scripted_reply(ob)
        try:
            return ob, self.llm(build_student_prompt(ob))
        except Exception as exc:
            _log.warning("LLM call failed for %s: %s", ob.agent_id, exc)
            return ob, ""

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        if self.llm_kind == "openai" and len(obs) > 1:
            from concurrent.futures import ThreadPoolExecutor
            if hasattr(self.llm, "_ensure"):
                self.llm._ensure()
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(obs))) as ex:
                results = list(ex.map(self._ask, obs))
        else:
            results = [self._ask(ob) for ob in obs]

        actions: list[Action] = []
        for ob, resp in results:
            dec = parse_decision(resp)
            if dec is None:
                _log.warning("unparsed reply from %s, keeping last month's choice: %r",
                             ob.agent_id, resp[:300])
                keep = ob.local_physical["state"].get("choice") or "canteen"
                dec = {"choice": keep, "satisfaction": ob.local_physical["state"].get("satisfaction") or 0.5,
                       "reason": _FALLBACK_REASON[_prompt_lang(build_student_prompt(ob))]}
                source = "fallback"
            else:
                source = "llm" if self.llm_kind == "openai" else "rule"
            actions.append(Action(
                agent_id=ob.agent_id, step=ob.step, kind="choose_meal",
                payload={"choice": dec["choice"], "satisfaction": dec["satisfaction"],
                         "reason": dec.get("reason", "")},
                source=source, rationale=[dec.get("reason") or ""]))
        return actions


# ================================================================================================
# metrics
# ================================================================================================
@register("collector", "campus_dining_choice.collector")
class DiningMetricCollector(MetricCollector):
    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        choices = list(env.choice.values())
        n = len(choices) or 1
        return {
            "share_canteen": round(sum(c == "canteen" for c in choices) / n, 4),
            "share_delivery": round(sum(c == "delivery" for c in choices) / n, 4),
            "share_cook": round(sum(c == "cook" for c in choices) / n, 4),
            "mean_satisfaction": round(mean(env.satis.values()), 4) if env.satis else 0.0,
            "mean_food_spend": round(mean(env.spend.values()), 1) if env.spend else 0.0,
        }

    def columns(self) -> list[str]:
        return ["share_canteen", "share_delivery", "share_cook", "mean_satisfaction", "mean_food_spend"]


# ================================================================================================
# artifact factory
# ================================================================================================
CD_METRICS = ["share_canteen", "share_delivery", "share_cook", "mean_satisfaction", "mean_food_spend"]
CD_METRIC_DESC = {
    "share_canteen": "当月以食堂为主要就餐方式的学生占比(0–1)",
    "share_delivery": "当月以点外卖为主要就餐方式的学生占比(0–1)",
    "share_cook": "当月以自己做饭为主要就餐方式的学生占比(0–1)",
    "mean_satisfaction": "全体学生对当月就餐的平均消费满意度(0–1,越高越满意)",
    "mean_food_spend": "人均当月餐饮支出(元/月,按当月主要就餐方式×主餐数估算),反映价格环境对钱包的压力",
}


def make_campus_dining_choice_bundles(
    study_id: str = "campus_dining_choice",
    *,
    n_agents: int = 150,
    n_steps: int = 4,
    seed: int = 42,
    base_canteen: float = 12.0,
    base_delivery: float = 25.0,
    base_cook: float = 7.0,
    canteen_monthly: float = 1.08,       # grounding: a-price-schedule
    delivery_monthly: float = 1.06,
    cook_monthly: float = 1.02,
    canteen_cap_step: int | None = None,  # if set: the canteen raises prices only for t<=cap and is capped afterwards (a mid-course intervention)
    interaction_rounds: int = 1,          # >1 = decide after several rounds of dorm discussion each month
    llm_kind: str = "scripted",
    model: str = "gpt-4o",
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    discuss = interaction_rounds > 1
    study = StudySpec(
        study_id=study_id,
        title="大学城学生在食堂逐月涨价与外卖同步涨价下的就餐选择与满意度演化",
        research_question=("当校园食堂逐月上调餐价、本地外卖同期也在涨价时,约150名大学生的主要就餐方式"
                           "(食堂/点外卖/自己做饭)与消费满意度将如何逐月演变?"),
        hypothesis=("随食堂与外卖价格逐月上涨,学生逐步从外卖转向食堂、再部分转向自己做饭以控制餐饮支出;"
                    "平均满意度随可选项性价比下降而走低,低预算/价格敏感者转移与满意度下滑最明显。"),
        study_type="longitudinal", n_steps=n_steps, seed=seed,
        metrics=CD_METRICS, metric_descriptions=CD_METRIC_DESC,
        domain="consumer-behavior",
        tags=["dining-choice", "price-response", "student-consumption", "longitudinal", "from-scratch"]
             + (["multi-round-discussion"] if discuss else []),
        legacy_simulator="from_scratch",
        provider_refs=["campus_dining_choice.env", "campus_dining_choice.pop",
                       "campus_dining_choice.decision", "campus_dining_choice.collector"],
        adjustable_params=["n_students (~150)", "n_steps (月份数)", "食堂/外卖/自炊月度涨幅",
                           "食堂涨价封顶step (canteen_cap_step)", "宿舍讨论轮数 (interaction_rounds)",
                           "基线价格", "价格敏感度/预算分布", "seed"],
        status="draft",
    )
    # monthly price events: the canteen rises only for t<=cap (capped afterwards); delivery / home cooking rise every month
    price_events: list[ScheduledEvent] = []
    for t in range(1, n_steps + 1):
        if canteen_cap_step is None or t <= canteen_cap_step:
            price_events.append(ScheduledEvent(at_step=t, target_layer="canteen_price", op="multiply",
                                property_name="price", value=canteen_monthly,
                                note=f"第{t}月：食堂餐价上调（×{canteen_monthly}）"))
        price_events.append(ScheduledEvent(at_step=t, target_layer="delivery_price", op="multiply",
                            property_name="price", value=delivery_monthly,
                            note=f"第{t}月：本地外卖客单价上调（×{delivery_monthly}）"))
        price_events.append(ScheduledEvent(at_step=t, target_layer="cook_cost", op="multiply",
                            property_name="price", value=cook_monthly,
                            note=f"第{t}月：自炊食材价格小幅上涨（×{cook_monthly}）"))
    if canteen_cap_step is not None:                 # mid-course intervention marker: ×1.0 has no price effect, it only enters the event stream
        price_events.append(ScheduledEvent(at_step=canteen_cap_step, target_layer="canteen_price",
                            op="multiply", property_name="price", value=1.0,
                            note=f"第{canteen_cap_step}月：食堂宣布餐价封顶，后续不再上调（干预）"))

    layers = [
        EnvironmentLayer(name="canteen_price", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:f-canteen-meal", description="食堂单餐价格（元/餐），逐月上调至封顶"),
        EnvironmentLayer(name="delivery_price", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:f-delivery-order", description="本地外卖客单价（元/单），同期上涨"),
        EnvironmentLayer(name="cook_cost", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:a-cook-cost", description="自己做饭单餐食材成本（元/餐），小幅上涨"),
        EnvironmentLayer(name="canteen_notice", modality="information", scope="macro", dynamics="scheduled",
                         source="grounding:a-price-schedule", description="食堂公告（逐月上调 / 涨价封顶）"),
        EnvironmentLayer(name="delivery_news", modality="information", scope="macro", dynamics="scheduled",
                         source="grounding:a-price-schedule", description="本地外卖涨价新闻"),
        EnvironmentLayer(name="cohort_trend", modality="information", scope="local", dynamics="endogenous",
                         description="同类同学上月各就餐方式占比（社交扩散）"),
    ]
    if discuss:
        layers.append(EnvironmentLayer(name="dorm_chat", modality="information", scope="local",
                      dynamics="endogenous", description="本月宿舍小组讨论：舍友当轮的倾向+理由（多轮传递）"))

    # canteen notice: "monthly increase" before the cap, replaced by the "price cap" notice from the cap month on (same channel, latest wins)
    broadcasts = []
    if canteen_cap_step is None:
        broadcasts.append(Broadcast(message_id="CANTEEN_NOTICE", channel="canteen_notice", at_step=0,
                          ttl=n_steps + 1, audience="all",
                          content="校园食堂公告：受成本上涨影响，未来数月将逐月上调餐价（每月约+8%），请同学们理解。"))
    else:
        broadcasts.append(Broadcast(message_id="CANTEEN_NOTICE", channel="canteen_notice", at_step=0,
                          ttl=canteen_cap_step, audience="all",
                          content="校园食堂公告：受成本上涨影响，未来数月将逐月上调餐价（每月约+8%），请同学们理解。"))
        broadcasts.append(Broadcast(message_id="CANTEEN_CAP", channel="canteen_notice", at_step=canteen_cap_step,
                          ttl=n_steps + 1 - canteen_cap_step, audience="all",
                          content="校园食堂公告：餐价即日起封顶，后续不再上调，请同学们放心就餐。"))
    broadcasts.append(Broadcast(message_id="DELIVERY_NEWS", channel="delivery_news", at_step=0,
                      ttl=n_steps + 1, audience="all",
                      content="本地外卖：近期平台配送费与商家客单价持续上涨（环比约+6%/月），满减力度也有所收缩。"))

    env_bundle = EnvironmentBundle(
        study_id=study_id, provider_ref="campus_dining_choice.env",
        provider_args={"n_agents": n_agents, "base_canteen": base_canteen,
                       "base_delivery": base_delivery, "base_cook": base_cook},
        layers=layers, scheduled_events=price_events,
        information_program=InformationProgram(broadcasts=broadcasts),
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="campus_dining_choice.pop",
        provider_args={"n_agents": n_agents},
        interaction=(InteractionStructure(kind="explicit_network", edges=dorm_edges(n_agents, seed))
                     if discuss else InteractionStructure(kind="none")),
        propagation=PropagationMode.BROADCAST_THEN_LOCAL if discuss else PropagationMode.INDEPENDENT,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed,
        decision_ref="campus_dining_choice.decision",
        decision_args={"llm_kind": llm_kind, "model": model},
        collector_ref="campus_dining_choice.collector", interaction_rounds=interaction_rounds,
    )
    return study, env_bundle, pop_bundle, sim_config
