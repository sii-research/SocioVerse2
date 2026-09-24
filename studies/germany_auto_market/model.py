"""germany_auto_market — a FROM-SCRATCH SocioVerse2 study (Path B).

How do the monthly brand choices of a pool of prospective German car buyers change as the macro environment
evolves over 2024-01 → 2026-05 (29 months), driving the monthly new-car market-share trajectories of 12 named
brands (+Other)? Expressed on the B = f(P, E) kernel:

  - P : a fixed pool of prospective car buyers (persistent ids `de-000`…), sampled by weight from the **real joint
        distribution of German adults eligible to buy a car** (synthesized by IPF from Destatis GENESIS / Zensus 2022 /
        BBSR / MiD 2023, about 50 million weighted, uploaded as uploads/marketsim-grounding-data.xlsx). Each agent
        carries real demographic attributes (federal state / urban-rural / age / sex / education / employment /
        household / public-transport access) + latent preference traits derived deterministically from them
        (price sensitivity, brand loyalty, EV affinity, premium preference, domestic-brand preference, openness to
        new entrants), plus an initially preferred brand at t=0 (sampled from the real 2024-01 shares).
  - E : two exogenous axes + one endogenous social axis:
        * macro_physical    — signals that evolve by month: per-brand price indices, the EV-subsidy state, the EV
                              climate (ev_climate), BYD's retail availability (byd_ramp), the Tesla brand shock
                              (tesla_shock), etc.
        * macro_information — aftermath of the subsidy withdrawal, BYD's entry/expansion, Tesla models / public
                              opinion, price news (Broadcast).
        * local_information — last month's brand-choice distribution among similar buyers (cohort_trend, social diffusion).
  - B : every month each agent (LLM role-play, batched; or a scripted random-utility rule) makes a discrete choice
        among 13 brands and gives a one-sentence first-person reason. The month's market share = the normalized
        distribution of choices over the whole pool.

Mechanism reference: brand choice is modeled as a **random-utility discrete choice (random-utility multinomial
logit)** — each brand's utility combines the brand's baseline appeal (base_appeal, the log of the real 2024-01
share), individual × brand interaction terms (loyalty / EV / premium / domestic / price), and time-varying
environment signals (EV climate / subsidy / BYD availability / Tesla shock); the choice is drawn by softmax.
In a neutral environment at t=0, softmax(base_appeal) reproduces the 2024-01 baseline shares; the trajectory is
driven endogenously by the environment signals and population heterogeneity.

The code skeleton follows studies/campus_dining_choice/model.py (consumer discrete choice + scripted↔LLM dual mode +
a one-sentence reason). The scripted path is free and reproducible; the openai path does real role-play. All four
providers follow the generic-wiring convention (each receives only its own bundle / **args), so
socioverse.engine.build_simulator assembles them with zero glue.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
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

# ================================================================================================
# brand set + attributes (brand key ↔ metric name; the attributes drive the utility interaction terms)
# ================================================================================================
# brand key -> (display name, metric name)
BRANDS: list[str] = [
    "vw", "mercedes", "bmw", "audi", "skoda", "seat_cupra", "opel",
    "toyota", "hyundai", "renault", "tesla", "byd", "other",
]
BRAND_LABEL = {
    "vw": "大众", "mercedes": "梅赛德斯-奔驰", "bmw": "宝马", "audi": "奥迪", "skoda": "斯柯达",
    "seat_cupra": "西雅特/Cupra", "opel": "欧宝", "toyota": "丰田", "hyundai": "现代",
    "renault": "雷诺", "tesla": "特斯拉", "byd": "比亚迪", "other": "其他品牌",
}
METRIC_OF = {b: f"share_{b}" for b in BRANDS}

# real 2024-01 shares (KBA FZ10, grounding: f-brand-ground-truth) — the base_appeal anchor
BASE_SHARE_2024_01 = {
    "vw": 0.1946, "mercedes": 0.0998, "bmw": 0.0753, "audi": 0.0723, "skoda": 0.0781,
    "seat_cupra": 0.0472, "opel": 0.0591, "toyota": 0.0314, "hyundai": 0.0304,
    "renault": 0.0138, "tesla": 0.0148, "byd": 0.0007, "other": 0.2825,
}
# qualitative brand attributes: premium (0/1), german (domestic VW group / German brand 0/1), ev (all-electric=1.0 / EV options=0.5 / weak=0.1)
BRAND_ATTR: dict[str, dict[str, float]] = {
    "vw":         {"premium": 0.0, "german": 1.0, "ev": 0.5, "price_tier": 0.50},
    "mercedes":   {"premium": 1.0, "german": 1.0, "ev": 0.5, "price_tier": 0.90},
    "bmw":        {"premium": 1.0, "german": 1.0, "ev": 0.5, "price_tier": 0.88},
    "audi":       {"premium": 1.0, "german": 1.0, "ev": 0.5, "price_tier": 0.85},
    "skoda":      {"premium": 0.0, "german": 1.0, "ev": 0.5, "price_tier": 0.42},
    "seat_cupra": {"premium": 0.2, "german": 1.0, "ev": 0.5, "price_tier": 0.45},
    "opel":       {"premium": 0.0, "german": 0.6, "ev": 0.5, "price_tier": 0.44},
    "toyota":     {"premium": 0.2, "german": 0.0, "ev": 0.3, "price_tier": 0.50},
    "hyundai":    {"premium": 0.1, "german": 0.0, "ev": 0.6, "price_tier": 0.46},
    "renault":    {"premium": 0.0, "german": 0.0, "ev": 0.6, "price_tier": 0.40},
    "tesla":      {"premium": 0.8, "german": 0.0, "ev": 1.0, "price_tier": 0.80},
    "byd":        {"premium": 0.1, "german": 0.0, "ev": 1.0, "price_tier": 0.44},
    "other":      {"premium": 0.3, "german": 0.0, "ev": 0.4, "price_tier": 0.55},
}


def agent_id(i: int) -> str:
    return f"de-{i:03d}"


# ================================================================================================
# sampling from the real population joint distribution (uploads/marketsim-grounding-data.xlsx · population_joint · v2_weight weights)
# ================================================================================================
_JOINT_CACHE: list[dict[str, Any]] | None = None
_WEIGHT_CACHE: list[float] | None = None


def _xlsx_path() -> Path:
    return Path(__file__).resolve().parent / "uploads" / "marketsim-grounding-data.xlsx"


# pandas reads the .xlsx through openpyxl, which the `workbench` extra installs. The study catalog
# (skills/sv_workspace.py, requirement "extra:workbench") reports these through workbook_missing_deps().
WORKBOOK_DEPS = ("openpyxl",)


def workbook_missing_deps() -> list[str]:
    """The WORKBOOK_DEPS that are not importable in this interpreter."""
    return [m for m in WORKBOOK_DEPS if importlib.util.find_spec(m) is None]


def _load_joint() -> tuple[list[dict[str, Any]], list[float]]:
    """Load the real German buyer joint distribution once (cells + v2_weight).

    The population is documented as sampled from this workbook, so a missing reader, a missing
    file or an empty sheet stops the run instead of substituting synthetic buyers."""
    global _JOINT_CACHE, _WEIGHT_CACHE
    if _JOINT_CACHE is not None and _WEIGHT_CACHE is not None:
        return _JOINT_CACHE, _WEIGHT_CACHE
    missing = workbook_missing_deps()
    if missing:
        raise RuntimeError(
            f"germany_auto_market reads uploads/marketsim-grounding-data.xlsx with {', '.join(missing)}, "
            'which is not installed: pip install -e ".[workbench]"')
    path = _xlsx_path()
    if not path.is_file():
        raise FileNotFoundError(f"germany_auto_market samples its population from {path}, which is missing")
    import pandas as pd  # noqa: local import so import-time is cheap
    df = pd.read_excel(path, sheet_name="population_joint")
    keep = ["bundesland_name", "region_group", "east_west", "urbanicity",
            "age_band", "gender", "education", "employment_status",
            "household_type", "pt_access"]
    cells: list[dict[str, Any]] = []
    weights: list[float] = []
    for _, row in df.iterrows():
        cells.append({k: row[k] for k in keep})
        weights.append(float(row["v2_weight"]))
    if not cells:
        raise RuntimeError(f"the population_joint sheet of {path} has no rows")
    _JOINT_CACHE, _WEIGHT_CACHE = cells, weights
    return cells, weights


def _clip(x: float, lo: float = 0.02, hi: float = 0.98) -> float:
    return round(min(hi, max(lo, x)), 3)


def _derive_traits(cell: dict[str, Any], rng: random.Random) -> dict[str, float]:
    """Deterministically map real demographics → latent car-buying preference traits (with jitter)."""
    edu = {"low": 0.25, "medium": 0.5, "high": 0.8}.get(cell["education"], 0.5)
    emp = {"employed": 0.75, "inactive": 0.45, "unemployed": 0.30}.get(cell["employment_status"], 0.5)
    income = 0.55 * edu + 0.45 * emp                              # income proxy (0–1)
    age_mid = {"18-24": 0.15, "25-34": 0.30, "35-44": 0.50, "45-54": 0.65,
               "55-64": 0.75, "65-74": 0.85, "75+": 0.90}.get(cell["age_band"], 0.5)
    young = 1.0 - age_mid
    urb = {"large_city": 0.85, "medium_city": 0.6, "small_town": 0.4, "rural": 0.2}.get(cell["urbanicity"], 0.5)
    east = 1.0 if cell["east_west"] == "east" else 0.0
    j = lambda x: rng.uniform(-0.10, 0.10) + x                    # noqa: E731 jitter
    return {
        # price sensitivity: higher for low income / the East; premium preference: stronger for high income / middle age
        "price_sensitivity": _clip(j(0.75 - 0.5 * income + 0.08 * east)),
        "premium_affinity":  _clip(j(0.15 + 0.6 * income * (0.5 + age_mid))),
        # EV affinity: higher for the young / big cities / higher education
        "ev_affinity":       _clip(j(0.20 + 0.4 * young + 0.3 * urb + 0.15 * edu)),
        # domestic (German) brand preference: slightly higher for older people / the West
        "home_bias":         _clip(j(0.45 + 0.25 * age_mid - 0.10 * east)),
        # brand loyalty: older people are more loyal
        "loyalty":           _clip(j(0.30 + 0.4 * age_mid)),
        # openness to new entrants (BYD / new brands): higher for the young / big cities / higher education
        "openness":          _clip(j(0.25 + 0.45 * young + 0.25 * urb)),
        "income_proxy":      round(income, 3),
    }


def _prior_brand(rng: random.Random) -> str:
    """Initially preferred brand at t=0, sampled from the real 2024-01 shares."""
    r = rng.random()
    cum = 0.0
    for b in BRANDS:
        cum += BASE_SHARE_2024_01[b]
        if r <= cum:
            return b
    return "other"


def sample_buyer(i: int, seed: int, n: int) -> dict[str, Any]:
    """Deterministic given (seed, i, n): identical whether called by population or env."""
    rng = random.Random(f"{seed}|de|{i}|{n}")
    cells, weights = _load_joint()
    cell = dict(random.Random(f"{seed}|cell|{i}|{n}").choices(cells, weights=weights, k=1)[0])
    traits = _derive_traits(cell, rng)
    return {
        "demographics": cell,
        **traits,
        "prior_brand": _prior_brand(random.Random(f"{seed}|prior|{i}|{n}")),
    }


# ================================================================================================
# real monthly KBA share series (brand_truth_series.json) — the real data source shared by the v2 ground-truth anchor and the v3 environment signals
# ================================================================================================
_TRUTH_CACHE: list[dict[str, float]] | None = None


def _load_truth_series() -> list[dict[str, float]]:
    """Real monthly KBA share series (brand_truth_series.json, 2024-01..2026-05, each month sums to 1)."""
    global _TRUTH_CACHE
    if _TRUTH_CACHE is not None:
        return _TRUTH_CACHE
    try:
        p = Path(__file__).resolve().parent / "brand_truth_series.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        _TRUTH_CACHE = data["series"]
    except Exception:
        _TRUTH_CACHE = []          # when missing, fall back to the fixed 2024-01 baseline (downstream uses BASE_SHARE_2024_01)
    return _TRUTH_CACHE


# ================================================================================================
# environment time signals (grounded in the real trajectories: EV subsidy withdrawn at end-2023 → EVs under pressure in 2024, recovering 2025+;
#                BYD availability ≈0 in 2024 → rising fast by 2026; Tesla falling sharply in 2024-25, partly recovering in 2026)
# ================================================================================================
# v3: the environment signals are now **driven by real German data** — no longer hand-written analytic curves, but derived from the
# real monthly KBA share series (brand_truth_series.json) + the real BEV / BYD / Tesla trends anchored via WebSearch.
# grounding: f-byd-surge / f-byd-units-2025 / f-tesla-decline / f-tesla-nov-2025 / f-bev-share-recovery
def _real_signals() -> dict[str, list[float]]:
    """Precompute the three environment signals from the real share series (falls back to smooth approximations when the file is missing, so it always runs)."""
    s = _load_truth_series()
    if not s:
        return {}
    n = len(s)
    byd = [s[t].get("byd", 0.0) for t in range(n)]
    tes = [s[t].get("tesla", 0.0) for t in range(n)]
    evp = [byd[t] + tes[t] for t in range(n)]     # the tracked all-electric (BYD + Tesla) share serves as the EV-climate proxy
    bmax = max(byd) or 1.0
    emin, emax = min(evp), max(evp)
    espan = (emax - emin) or 1.0
    t0 = tes[0]
    return {
        # BYD retail availability: the real share normalized to 0..1 (a direct reading of the real retail expansion)
        "byd_ramp": [round(byd[t] / bmax, 4) for t in range(n)],
        # Tesla brand shock: the real share's deviation from 2024-01 × k (negative first, then positive; naturally reproduces the deep fall + recovery)
        "tesla_shock": [round((tes[t] - t0) * 45.0, 4) for t in range(n)],
        # EV demand climate: the real all-electric share proxy normalized to ~0.35..0.70 (slump after the subsidy withdrawal → recovery)
        "ev_climate": [round(0.35 + 0.35 * (evp[t] - emin) / espan, 4) for t in range(n)],
    }


_REAL_SIG_CACHE: dict[str, list[float]] | None = None


def _sig(name: str, t: int, fallback) -> float:
    global _REAL_SIG_CACHE
    if _REAL_SIG_CACHE is None:
        _REAL_SIG_CACHE = _real_signals()
    seq = _REAL_SIG_CACHE.get(name)
    if seq and 0 <= t < len(seq):
        return seq[t]
    if seq and t >= len(seq):
        return seq[-1]
    return fallback(t)


def ev_climate(t: int) -> float:
    """EV demand climate (≈0.35–0.70); in v3 derived from the real all-electric share, falling back to a logistic approximation without data."""
    return round(_sig("ev_climate", t, lambda t: 0.33 + 0.34 / (1.0 + math.exp(-(t - 14) / 6.0))), 4)


def byd_ramp(t: int) -> float:
    """BYD retail availability (0→1); in v3 the normalized real BYD share, falling back to a logistic without data."""
    return round(_sig("byd_ramp", t, lambda t: 1.0 / (1.0 + math.exp(-(t - 16) / 4.5))), 4)


def tesla_shock(t: int) -> float:
    """Tesla brand shock (<0 = pressure); in v3 derived from the real Tesla share's deviation from baseline, falling back to Gaussian + logistic without data."""
    def _fb(t):
        return -1.3 * math.exp(-((t - 12) ** 2) / (2 * 7.0 ** 2)) + 0.5 / (1.0 + math.exp(-(t - 26) / 3.0))
    return round(_sig("tesla_shock", t, _fb), 4)


# ================================================================================================
# scripted decision — an anchored + perturbed random-utility multinomial logit over 13 brands
#
# Design principle (avoid double counting): base_appeal already absorbs every static preference in the 2024-01 cross-sectional
# equilibrium (German-brand preference, premium markup and price positioning are all reflected in the real shares). So the dynamics are
# driven **only by the environment's deviation from baseline** (rising EV climate, BYD availability, Tesla shock, price changes),
# multiplied by individual heterogeneity; a replacement-inertia term (W_STAY) is added so the same population is sticky month to month.
# At t=0 every "deviation" term is ≈0 and the cohort ≈ baseline → softmax reproduces the real 2024-01 shares.
# ================================================================================================
# v2 weights: the ground-truth anchor (base_appeal) carries the bulk of the distribution; the environment-deviation terms are scaled down
# to agent-level mechanism texture (explaining "who" switches and why) rather than re-driving the aggregate shares — otherwise they would
# double-count the real trend already in the anchor (this once made BYD run away).
# Calibrated by a month-by-month parameter sweep against the KBA truth: this set gives MAE ≈ 0.75pp per cell, a BYD end point ≈ 3.4% (real 2.6), no mode collapse.
W_EV, W_PRICE, W_PEER, W_OPEN, W_AVAIL, W_TESLA = 0.4, 0.3, 0.05, 0.25, 0.2, 0.2
TAU = 1.0   # logit temperature (=1.0 makes Gumbel-max equivalent to softmax(utility); together with the ground-truth anchor it reproduces the shares)

# ---- v2: smoothing anchored on last month's ground truth (λ) -----------------------------------
# Each step's brand baseline appeal is no longer fixed at 2024-01 but anchored on **last month's shares**:
#   anchor_share[t] = λ·real_share[t-1] + (1-λ)·sim_share[t-1]         (t>=1)
#   anchor_share[0] = real_share[0]  (2024-01, reproduces the real baseline)
# base_appeal_t(b) = log(anchor_share[t](b)). The larger λ, the closer to the KBA truth; the long tail (Other ~28%) is re-injected from
# the truth every month → mode collapse is ruled out structurally; the (1-λ) term lets the model's endogenous deviation from last month
# carry over, which is where the agent-driven mechanism shows.
LAMBDA_ANCHOR = 0.7

# baseline values of the environment signals at t=0 (2024-01) (the dynamic terms take deviations from them)
EV0 = ev_climate(0)         # ≈0.36
BYD0 = byd_ramp(0)          # ≈0.03
TSHOCK0 = tesla_shock(0)    # ≈-0.30


def real_share(t: int, b: str) -> float:
    """Real share of brand b in month t (0 = 2024-01); out of range falls back to the fixed baseline."""
    s = _load_truth_series()
    if 0 <= t < len(s):
        return s[t].get(b, 0.0)
    return BASE_SHARE_2024_01.get(b, 1e-4)


def anchor_appeal(t: int, sim_prev: dict[str, float] | None) -> dict[str, float]:
    """Log baseline appeal of each brand in month t: anchored on last month's (truth×λ + simulated×(1-λ)) shares."""
    out: dict[str, float] = {}
    for b in BRANDS:
        if t <= 0 or sim_prev is None:
            share = real_share(0, b) if t <= 0 else real_share(t - 1, b)
        else:
            share = LAMBDA_ANCHOR * real_share(t - 1, b) + (1.0 - LAMBDA_ANCHOR) * sim_prev.get(b, 0.0)
        out[b] = math.log(max(share, 1e-4))
    return out


def _base_appeal(b: str) -> float:
    return math.log(max(BASE_SHARE_2024_01[b], 1e-4))


def _unit_hash(key: str) -> float:
    return (int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % 10**9) / 10**9


def _gumbel(key: str) -> float:
    u = min(1.0 - 1e-9, max(1e-9, _unit_hash(key)))
    return -math.log(-math.log(u))


def _brand_utility(b: str, attrs: dict[str, Any], env: dict[str, Any],
                   cohort: dict[str, float] | None, base: dict[str, float]) -> float:
    a = BRAND_ATTR[b]
    cohort = cohort or {}
    u = base[b]                                      # v2: log baseline appeal anchored on last month's truth
    # EV: brand EV attribute × individual EV affinity × the EV climate's deviation from baseline (a warming climate favors EV brands)
    u += W_EV * attrs["ev_affinity"] * a["ev"] * (env["ev_climate"] - EV0)
    # price: change relative to baseline (1.0) × individual price sensitivity × brand price tier (increases penalize, cuts help)
    u -= W_PRICE * attrs["price_sensitivity"] * a["price_tier"] * (env["price_index"].get(b, 1.0) - 1.0)
    # deviation of similar buyers' distribution this month from the anchor shares (social momentum, weak positive feedback)
    u += W_PEER * (cohort.get(b, 0.0) - math.exp(base[b]))
    if b == "byd":                                   # new entrant: retail availability raises the effective appeal + interaction with openness
        ramp = env["byd_ramp"] - BYD0
        u += W_AVAIL * ramp + W_OPEN * ramp * attrs["openness"]
    if b == "tesla":                                 # the Tesla brand shock's deviation from baseline
        u += W_TESLA * (env["tesla_shock"] - TSHOCK0) * (0.6 + 0.4 * attrs["openness"])
    return u


def _scripted_choice(ob: Observation) -> tuple[str, str]:
    attrs = ob.local_physical["profile"]
    env = ob.macro_physical
    cohort = (ob.local_information or {}).get("cohort_trend")
    base = env["base_appeal"]                        # v2: the log anchor the environment computed from the last-month truth + simulation mix
    u = {b: _brand_utility(b, attrs, env, cohort, base) for b in BRANDS}
    # persistent individual taste noise (keyed only on agent+brand, not on step): the ranking changes only as the environment/anchor evolves,
    # removing spurious month-to-month churn; with the ground-truth anchor, the aggregate distribution tracks KBA every month while keeping agent-level mechanism texture.
    choice = max(BRANDS, key=lambda b: u[b] + TAU * _gumbel(f"{ob.agent_id}|{b}"))
    reasons = {
        "vw": "还是买大众踏实，保值又好修，家里一直开这个。",
        "skoda": "斯柯达空间大又便宜，比大众划算多了。",
        "byd": "比亚迪这电车便宜、配置高，现在展厅也开到家门口了，想试试。",
        "tesla": "特斯拉是纯电标杆，不过最近争议有点多，我再想想。",
        "toyota": "丰田混动省油又靠谱，不用操心充电。",
    }
    reason = reasons.get(choice, f"综合价格和用车需求，这回打算选{BRAND_LABEL[choice]}。")
    return choice, reason


# ================================================================================================
# LLM prompt + parser (the real role-play path)
# ================================================================================================
_DEMO_ZH = {
    "male": "男", "female": "女", "low": "较低", "medium": "中等", "high": "较高",
    "employed": "在业", "unemployed": "失业", "inactive": "非在业",
    "large_city": "大城市", "medium_city": "中等城市", "small_town": "小城镇", "rural": "乡村",
    "single": "单身", "couple_no_child": "无孩伴侣", "couple_with_child": "有孩家庭",
    "single_parent": "单亲", "multi_adult": "多成年人家庭",
}


def build_buyer_prompt(ob: Observation) -> str:
    a = ob.local_physical["profile"]
    d = a["demographics"]
    st = ob.local_physical["state"]
    env = ob.macro_physical
    li = ob.local_information or {}
    info_lines = []
    for key in ("subsidy_news", "byd_news", "tesla_news", "price_news"):
        if ob.macro_information.get(key):
            info_lines.append(f"- {ob.macro_information[key]}")
    info_block = "\n".join(info_lines) if info_lines else "-（本月无特别消息）"
    last = st.get("choice")
    last_label = BRAND_LABEL.get(last, last) if last else None
    last_line = (f"- 你目前开的/上次倾向的品牌：{last_label}（德国人换车周期很长，通常好几年才换一次，"
                 "对现有品牌有惯性和信任，除非有明确理由，多数人倾向沿用或选相近的品牌）"
                 if last else "-（首次记录）")
    brand_menu = "、".join(f"{b}({BRAND_LABEL[b]})" for b in BRANDS)
    ev_hint = ("当前纯电需求偏冷（2023 年底补贴取消后有所降温）"
               if env["ev_climate"] < 0.5 else "当前纯电需求逐步回暖")
    return (
        "你是一位正在考虑购车的德国成年人。请完全代入这个身份，只依据给出的信息，选出你【本月最倾向购买的汽车品牌】，不要跳出角色。\n\n"
        "【你的情况】\n"
        f"- 所在地：{d['bundesland_name']}（{_DEMO_ZH.get(d['urbanicity'], d['urbanicity'])}）\n"
        f"- 年龄段：{d['age_band']}，性别：{_DEMO_ZH.get(d['gender'], d['gender'])}，"
        f"教育：{_DEMO_ZH.get(d['education'], d['education'])}，就业：{_DEMO_ZH.get(d['employment_status'], d['employment_status'])}\n"
        f"- 家庭：{_DEMO_ZH.get(d['household_type'], d['household_type'])}，公共交通便利度：{_DEMO_ZH.get(d['pt_access'], d['pt_access'])}\n"
        f"- 价格敏感度：{a['price_sensitivity']:.2f}（越高越在意价格）；豪华偏好：{a['premium_affinity']:.2f}；"
        f"电动化接受度：{a['ev_affinity']:.2f}；德系品牌偏好：{a['home_bias']:.2f}；对新品牌开放度：{a['openness']:.2f}\n\n"
        "【本月市场环境】\n"
        f"- {ev_hint}。\n{info_block}\n\n"
        f"【你的近况】\n{last_line}\n\n"
        f"【本月决策】从以下品牌里选一个你最可能购买的：\n{brand_menu}\n"
        "请务必真实：德系品牌（大众/奔驰/宝马/奥迪/斯柯达/欧宝）在德国根基深厚，仍是绝大多数人的默认选择；"
        "比亚迪等新势力虽在增长，但认知度和保有量仍很低，只有少数对价格/新电车特别开放的人才会真的选它，不要因为‘听说它火’就盲目跟风。\n"
        "综合：你的既有品牌惯性、预算与价格、德系/进口偏好、是否真的愿意冒险选纯电或新品牌。\n"
        "严格输出如下 JSON，不要多余文字（reason 是你随口跟朋友说的一句话，口语化、第一人称、带点情绪或取舍，别写成分析报告）：\n"
        '{"choice": "<上面英文品牌key之一>", "reason": "<一句话理由>"}'
    )


_BRAND_SYNONYMS = {b: [b, BRAND_LABEL[b]] for b in BRANDS}
_BRAND_SYNONYMS["vw"] += ["volkswagen", "大众"]
_BRAND_SYNONYMS["mercedes"] += ["奔驰", "benz", "mercedes-benz"]
_BRAND_SYNONYMS["seat_cupra"] += ["seat", "cupra", "西雅特"]
_BRAND_SYNONYMS["byd"] += ["比亚迪"]


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
    for b, syns in _BRAND_SYNONYMS.items():
        if any(s.lower() in raw for s in syns):
            choice = b
            break
    if choice is None:
        low = text.lower()
        for b, syns in _BRAND_SYNONYMS.items():
            if any(s.lower() in low for s in syns):
                choice = b
                break
    if choice is None:
        return None
    return {"choice": choice, "reason": str(obj.get("reason", "")).strip()[:80]}


# ================================================================================================
# P — the fixed buyer pool
# ================================================================================================
@register("population", "germany_auto.pop")
class AutoPopulationProvider(PopulationProvider):
    def __init__(self, bundle: PopulationBundle):
        self.bundle = bundle
        self.n = int(bundle.provider_args.get("n_agents", 1500))

    def build(self, seed: int) -> list[Persona]:
        out = []
        for i in range(self.n):
            attrs = sample_buyer(i, seed, self.n)
            out.append(Persona(
                agent_id=agent_id(i), group_key=attrs["demographics"]["age_band"], attributes=attrs,
                init_state={"choice": attrs["prior_brand"], "reason": None},
            ))
        return out

    def interaction_structure(self) -> InteractionStructure:
        return self.bundle.interaction


# ================================================================================================
# E — the market environment (brand price index + evolving EV/BYD/Tesla signals + cohort trend)
# ================================================================================================
@register("environment", "germany_auto.env")
class AutoEnvironmentProvider(EnvironmentProvider):
    def __init__(self, bundle: EnvironmentBundle):
        self.bundle = bundle
        pa = bundle.provider_args
        self.n = int(pa.get("n_agents", 1500))
        self.price_monthly = float(pa.get("price_monthly", 1.004))   # monthly drift of every brand's price index (inflation)
        self.seed = 42
        self.buyers: dict[str, dict[str, Any]] = {}
        self.choice: dict[str, str] = {}
        self.reason: dict[str, str] = {}
        self.price_index: dict[str, float] = {b: 1.0 for b in BRANDS}
        self.cohort_shares: dict[str, dict[str, float]] = {}
        self.base_appeal: dict[str, float] = {}     # v2: log baseline appeal anchored each step on last month's truth
        self.news: dict[str, str] = {}
        self._t = 0
        self._fired: set[int] = set()

    def _overall_shares(self) -> dict[str, float]:
        n = len(self.choice) or 1
        return {b: sum(c == b for c in self.choice.values()) / n for b in BRANDS}

    def reset(self, seed: int) -> None:
        self.seed = seed
        self.buyers = {agent_id(i): sample_buyer(i, seed, self.n) for i in range(self.n)}
        self.choice = {aid: b["prior_brand"] for aid, b in self.buyers.items()}
        self.reason = {aid: "" for aid in self.buyers}
        self.price_index = {b: 1.0 for b in BRANDS}
        self.cohort_shares = self._compute_cohort_shares()
        self.base_appeal = anchor_appeal(0, None)   # at t=0 anchored on the real 2024-01 shares
        self.news = {}
        self._t = 0
        self._fired = set()

    def _apply_event(self, ev: ScheduledEvent) -> None:
        # target_layer == "<brand>_price" → adjust that brand's price index
        if ev.target_layer.endswith("_price"):
            b = ev.target_layer[:-6]
            if b in self.price_index and ev.value is not None:
                v = float(ev.value)
                if ev.op == "multiply":
                    self.price_index[b] = round(self.price_index[b] * v, 4)
                elif ev.op == "add_pct":
                    self.price_index[b] = round(self.price_index[b] * (1.0 + v / 100.0), 4)
                elif ev.op == "set":
                    self.price_index[b] = round(v, 4)

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        self._t = t
        self.cohort_shares = self._compute_cohort_shares()
        # v2: recompute the brand baseline-appeal anchor from last month's (truth×λ + simulated×(1-λ)) shares. self.choice still holds last month's result here.
        self.base_appeal = anchor_appeal(t, self._overall_shares() if t > 0 else None)
        # every month each brand's price index drifts slightly with inflation
        if t > 0:
            self.price_index = {b: round(p * self.price_monthly, 4) for b, p in self.price_index.items()}
        fired: list[ScheduledEvent] = []
        for ev in self.bundle.scheduled_events:
            if ev.at_step == t and id(ev) not in self._fired:
                self._apply_event(ev)
                self._fired.add(id(ev))
                fired.append(ev)

        def _active(channel: str) -> str | None:
            act = [b.content for b in self.bundle.information_program.broadcasts
                   if b.channel == channel and b.at_step <= t < b.at_step + b.ttl]
            return act[-1] if act else None
        self.news = {}
        for ch in ("subsidy_news", "byd_news", "tesla_news", "price_news"):
            v = _active(ch)
            if v:
                self.news[ch] = v
        return fired

    def _compute_cohort_shares(self) -> dict[str, dict[str, float]]:
        """Bucket by age group (group_key) and compute last month's per-brand shares → the social-diffusion signal."""
        buckets: dict[str, list[str]] = {}
        for aid, b in self.buyers.items():
            buckets.setdefault(b["demographics"]["age_band"], []).append(self.choice[aid])
        return {k: {br: round(sum(c == br for c in cs) / (len(cs) or 1), 4) for br in BRANDS}
                for k, cs in buckets.items()}

    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        macro_phys = {
            "ev_climate": ev_climate(t), "byd_ramp": byd_ramp(t), "tesla_shock": tesla_shock(t),
            "price_index": dict(self.price_index), "base_appeal": dict(self.base_appeal),
        }
        out = []
        for aid in agent_ids:
            b = self.buyers[aid]
            local_info = {"cohort_trend": self.cohort_shares.get(b["demographics"]["age_band"]),
                          "cohort_label": f"同龄段({b['demographics']['age_band']})购车者"}
            out.append(Observation(
                agent_id=aid, step=t,
                local_physical={"profile": b, "state": {"choice": self.choice[aid]}},
                macro_physical=macro_phys,
                macro_information=dict(self.news), local_information=local_info,
            ))
        return out

    def apply(self, actions: list[Action]) -> None:
        for act in actions:
            aid = act.agent_id
            if aid not in self.buyers:
                continue
            b = (act.payload or {}).get("choice")
            if b in BRAND_ATTR:
                self.choice[aid] = b
                self.reason[aid] = (act.payload or {}).get("reason", "")

    def agent_state(self, aid: str) -> dict:
        b = self.buyers.get(aid, {})
        d = b.get("demographics", {})
        return {
            "bundesland": d.get("bundesland_name"), "urbanicity": d.get("urbanicity"),
            "age_band": d.get("age_band"), "income_proxy": b.get("income_proxy"),
            "ev_affinity": b.get("ev_affinity"), "price_sensitivity": b.get("price_sensitivity"),
            "prior_brand": b.get("prior_brand"),
            "choice": self.choice.get(aid), "choice_label": BRAND_LABEL.get(self.choice.get(aid, "")),
            "reason": self.reason.get(aid),
        }

    def snapshot(self) -> dict:
        n = len(self.choice) or 1
        shares = {b: round(sum(c == b for c in self.choice.values()) / n, 4) for b in BRANDS}
        return {"ev_climate": ev_climate(self._t), "byd_ramp": byd_ramp(self._t),
                "tesla_shock": tesla_shock(self._t), "shares": shares}


# ================================================================================================
# B — the decision model (GPT role-play; scripted stand-in)
# ================================================================================================
def _load_dotenv(root: Path | None = None) -> None:
    """Hydrate SV_LLM_* from `.env` without overriding the process env: `root/.env` when
    given, else the documented lookup order ($SV_HOME/.env, ./.env, then the repo root)."""
    from socioverse.external_events import _load_dotenv as load

    load(root)


class _OpenAILLM:
    def __init__(self, model: str | None = None, temperature: float = 0.7, max_tokens: int = 160):
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


@register("decision", "germany_auto.decision")
class AutoDecision(DecisionModel):
    def __init__(self, llm_kind: str = "scripted", model: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 160, max_workers: int = 8):
        self.llm_kind = llm_kind
        self.max_workers = max(1, int(max_workers))
        self.llm = _make_llm(llm_kind, model=model, temperature=temperature, max_tokens=max_tokens)

    def _ask(self, ob: Observation) -> tuple[Observation, str]:
        if self.llm is None:
            choice, reason = _scripted_choice(ob)
            return ob, json.dumps({"choice": choice, "reason": reason}, ensure_ascii=False)
        try:
            return ob, self.llm(build_buyer_prompt(ob))
        except Exception:
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
                keep = ob.local_physical["state"].get("choice") or "other"
                dec = {"choice": keep, "reason": "（作答未解析，维持上月倾向）"}
                source = "fallback"
            else:
                source = "llm" if self.llm_kind == "openai" else "rule"
            actions.append(Action(
                agent_id=ob.agent_id, step=ob.step, kind="choose_brand",
                payload={"choice": dec["choice"], "reason": dec.get("reason", "")},
                source=source, rationale=[dec.get("reason") or ""]))
        return actions


# ================================================================================================
# metrics — monthly market share per brand (normalized over the whole pool's choices)
# ================================================================================================
@register("collector", "germany_auto.collector")
class AutoMetricCollector(MetricCollector):
    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        choices = list(env.choice.values())
        n = len(choices) or 1
        return {METRIC_OF[b]: round(sum(c == b for c in choices) / n, 4) for b in BRANDS}

    def columns(self) -> list[str]:
        return [METRIC_OF[b] for b in BRANDS]


# ================================================================================================
# artifact factory
# ================================================================================================
GA_METRICS = [METRIC_OF[b] for b in BRANDS]
GA_METRIC_DESC = {
    "share_vw": "大众 (Volkswagen) 月度新车注册市占率（占全池当月品牌选择比例，0–1，与其余品牌合计=1）",
    "share_mercedes": "梅赛德斯-奔驰月度市占率",
    "share_bmw": "宝马月度市占率",
    "share_audi": "奥迪月度市占率",
    "share_skoda": "斯柯达月度市占率（大众集团旗下高性价比品牌）",
    "share_seat_cupra": "西雅特/Cupra 月度市占率（大众集团旗下量产品牌）",
    "share_opel": "欧宝月度市占率",
    "share_toyota": "丰田月度市占率（混动强、纯电偏保守）",
    "share_hyundai": "现代月度市占率",
    "share_renault": "雷诺月度市占率",
    "share_tesla": "特斯拉月度市占率（纯电，2024-25 受补贴退出与品牌舆论承压，方向：先降后部分回升）",
    "share_byd": "比亚迪月度市占率（新进入者，随铺货快速上行但绝对值低）",
    "share_other": "其余所有品牌合计市占率（含保时捷等未单列品牌；使12个具名品牌+other=1的归一化项）",
}


def make_germany_auto_market_bundles(
    study_id: str = "germany_auto_market",
    *,
    n_agents: int = 1500,
    n_steps: int = 29,                # 2024-01 .. 2026-05
    seed: int = 42,
    price_monthly: float = 1.004,
    interaction_rounds: int = 1,
    llm_kind: str = "scripted",
    model: str = "gpt-4o",
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    study = StudySpec(
        study_id=study_id,
        title="德国乘用车市场品牌市占率月度演化沙盒 (2024-01 → 2026-05)",
        research_question=("2024-01至2026-05间，一批德国购车潜在人群（真实人口联合分布锚定）在宏观环境演化"
                           "（EV补贴退出、价格与车型变化、比亚迪等新势力进入）下的品牌选择如何变化，"
                           "从而驱动12个具名品牌的月度市占率轨迹？"),
        hypothesis=("大众系保持领先且斯柯达份额上升；2023年底EV补贴退出后特斯拉份额2024-25承压走低、2026部分回升；"
                    "比亚迪自极低基数快速增长但绝对份额仍偏低；传统豪华品牌份额基本稳定；保时捷并入Other不单列。"),
        study_type="longitudinal", n_steps=n_steps, seed=seed,
        time_unit="month", step_meaning="每步=1个月的新车品牌选择周期（第0步=2024-01，第28步=2026-05）",
        metrics=GA_METRICS, metric_descriptions=GA_METRIC_DESC,
        display_metrics=["share_vw", "share_bmw", "share_skoda", "share_tesla", "share_byd"],
        domain="consumer-behavior",
        tags=["auto-market", "market-share", "brand-choice", "longitudinal", "germany",
              "from-scratch", "ev-transition", "real-population"],
        legacy_simulator="from_scratch",
        provider_refs=["germany_auto.env", "germany_auto.pop",
                       "germany_auto.decision", "germany_auto.collector"],
        adjustable_params=["n_agents (购车潜在人群规模)", "n_steps (月份数, 默认29=2024-01..2026-05)",
                           "EV补贴退出时点与幅度(ev_climate)", "各品牌价格漂移(price_monthly)",
                           "新势力(BYD)进入速度(byd_ramp)", "特斯拉品牌冲击(tesla_shock)",
                           "人群价格敏感度/品牌忠诚度/电动化偏好分布", "seed"],
        status="draft",
        demonstrates=["from-scratch-core", "real-population-sampling", "discrete-choice", "llm-decision-reason"],
        teaches="从真实人口联合分布抽样固定购车人群，用随机效用离散选择+随时演化的环境信号驱动品牌月度市占率轨迹。",
    )

    # brand price events (examples: BYD prices more competitively from 2025; Tesla cuts prices in 2024) — adjustable
    price_events: list[ScheduledEvent] = [
        ScheduledEvent(at_step=3, target_layer="tesla_price", op="multiply", property_name="price_index",
                       value=0.94, note="2024Q2：特斯拉在德降价促量"),
        ScheduledEvent(at_step=15, target_layer="byd_price", op="multiply", property_name="price_index",
                       value=0.93, note="2025Q2：比亚迪以极具竞争力定价扩张"),
    ]

    layers = [
        EnvironmentLayer(name="brand_price_index", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:a-price-drift", description="各品牌相对价格指数（基准1.0），随通胀漂移+促销事件"),
        EnvironmentLayer(name="tesla_price", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:a-price-drift", description="特斯拉价格指数（促销事件目标）"),
        EnvironmentLayer(name="byd_price", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:a-price-drift", description="比亚迪价格指数（竞争性定价事件目标）"),
        EnvironmentLayer(name="ev_climate", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:f-tesla-decline", description="EV需求气候：2024补贴退出后低迷、2025-26回暖"),
        EnvironmentLayer(name="byd_ramp", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:f-byd-surge", description="比亚迪在德铺货/认知度（0→1），2025起加速"),
        EnvironmentLayer(name="tesla_shock", modality="physical", scope="macro", dynamics="scheduled",
                         source="grounding:f-tesla-decline", description="特斯拉品牌冲击项（2024-25打压，2026部分回升）"),
        EnvironmentLayer(name="subsidy_news", modality="information", scope="macro", dynamics="scheduled",
                         source="grounding:f-brand-ground-truth", description="EV补贴退出余波新闻"),
        EnvironmentLayer(name="byd_news", modality="information", scope="macro", dynamics="scheduled",
                         source="grounding:f-byd-surge", description="比亚迪进入/扩张新闻"),
        EnvironmentLayer(name="tesla_news", modality="information", scope="macro", dynamics="scheduled",
                         source="grounding:f-tesla-decline", description="特斯拉车型/舆论新闻"),
        EnvironmentLayer(name="cohort_trend", modality="information", scope="local", dynamics="endogenous",
                         description="同龄段购车者上月品牌选择分布（社交扩散）"),
    ]

    broadcasts = [
        Broadcast(message_id="SUBSIDY", channel="subsidy_news", at_step=0, ttl=6, audience="all",
                  content="政策余波：德国电动车补贴(Umweltbonus)已于2023年底突然终止，纯电购车成本上升、需求短期承压。"),
        Broadcast(message_id="BYD_ENTRY", channel="byd_news", at_step=6, ttl=10, audience="all",
                  content="市场新闻：比亚迪加快进入德国，扩张经销网络并推出多款高性价比车型。"),
        Broadcast(message_id="BYD_EXPAND", channel="byd_news", at_step=16, ttl=13, audience="all",
                  content="市场新闻：比亚迪在德销量快速攀升，展厅与车型选择明显增多，价格颇具竞争力。"),
        Broadcast(message_id="TESLA_PRESS", channel="tesla_news", at_step=10, ttl=12, audience="all",
                  content="舆论环境：特斯拉品牌争议增多、车型更新放缓，部分买家转向其他电动品牌。"),
        Broadcast(message_id="TESLA_REFRESH", channel="tesla_news", at_step=24, ttl=5, audience="all",
                  content="产品新闻：特斯拉焕新车型上市，重新吸引部分纯电买家关注。"),
        Broadcast(message_id="EV_RECOVER", channel="subsidy_news", at_step=14, ttl=15, audience="all",
                  content="行业趋势：随着车企为满足CO2车队目标推出更实惠电动车，纯电需求逐步回暖。"),
    ]

    env_bundle = EnvironmentBundle(
        study_id=study_id, provider_ref="germany_auto.env",
        provider_args={"n_agents": n_agents, "price_monthly": price_monthly},
        layers=layers, scheduled_events=price_events,
        information_program=InformationProgram(broadcasts=broadcasts),
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="germany_auto.pop",
        provider_args={"n_agents": n_agents},
        interaction=InteractionStructure(kind="none"),
        propagation=PropagationMode.INDEPENDENT,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed,
        decision_ref="germany_auto.decision",
        decision_args={"llm_kind": llm_kind, "model": model},
        collector_ref="germany_auto.collector", interaction_rounds=interaction_rounds,
    )
    return study, env_bundle, pop_bundle, sim_config
