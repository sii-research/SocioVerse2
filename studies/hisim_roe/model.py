"""hisim_roe — HiSim hybrid social-movement simulation as a from-scratch SocioVerse2 study (Path B).

Native re-implementation of HiSim's macro *hybrid* mode (xymou, ACL2024-Findings) on SocioVerse2 Core,
with NO AgentVerse dependency. Population = LLM "core" users (post/retweet/reply/like) + ABM
"ordinary" users (Bounded-Confidence opinion dynamics), coupled by the **mirror**: a core user's
opinion each step = the signed sentiment of the tweet it just produced (HiSim `att2score`).

Faithful-to-source decisions are flagged `# FAITHFUL:`.

Milestones implemented here:
  M1  four abc wired on Core + synthetic no-API smoke (core decision `mode="fake"`).
  M2  real core decision (`mode="llm"`): prompt build + safe Thought/Action/Stance parser +
      att = sign(stance)·|sentiment|  (accelerated scheme: stance comes from the generation call).
  M3  real-data loader (`load_movement`) replacing `_synth` + full env mechanics
      (news-as-tweet injection, like/retweet counters, reply→target routing).
  M4  per-core personal-history summary + running event memory + reply→target inbox.
  M5  full 300×14 pilot + parity — deferred.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import re
from pathlib import Path
from statistics import mean, pvariance
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

NEUTRAL = 0.0  # FAITHFUL: HiSim get_measures uses ne_att=0 → bias = mean(att) - 0
HISIM_METRICS = ["bias", "diversity", "mean_core", "mean_ordinary", "n_active", "n_post"]


# ================================================================================================
# ids — group encoded in the id so a stateless decide_batch can route core vs ordinary
# ================================================================================================
def core_id(key: Any) -> str:
    return f"core-{key}"


def ord_id(key: Any) -> str:
    return f"ord-{key}"


def is_core(aid: str) -> bool:
    return aid.startswith("core-")


def _uname(aid: str) -> str:
    return aid.split("-", 1)[1]


def _h(s: str) -> int:
    """Stable hash (PYTHONHASHSEED-independent), like the deterministic fake LLM client."""
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")


# ================================================================================================
# M2 — stance/sentiment → att (the BCM "mirror" value), and the safe action parser
# ================================================================================================
def _default_sentiment(text: str) -> float:
    """TextBlob polarity in [-1, 1]; pluggable so the att pipeline never hard-fails on import."""
    try:
        from textblob import TextBlob

        return float(TextBlob(text).sentiment.polarity)
    except Exception:
        return 0.0


def _stance_sign(stance: str | None) -> int:
    # FAITHFUL: HiSim att2score sets sign=-1 only for 'Oppose'/'Against', else +1 (incl. Neutral).
    return -1 if (stance or "").strip().lower() in ("against", "oppose", "con") else 1


def compute_att(text: str, stance: str | None, sentiment_fn: Callable[[str], float] = _default_sentiment) -> float:
    """FAITHFUL att2score: sign(stance) · |sentiment polarity|."""
    return round(_stance_sign(stance) * abs(sentiment_fn(text or "")), 4)


_ACTION_RE = re.compile(r"Action:\s*([A-Za-z_]\w*)\s*\((.*?)\)\s*(?:$|\n)", re.S)
_STANCE_RE = re.compile(r"Stance:\s*([A-Za-z]+)", re.I)
_THOUGHT_RE = re.compile(r"Thought:\s*(.+)", re.I)


def _parse_kwargs(arg_str: str) -> dict[str, Any]:
    """Parse `content="x", author="y", original_tweet_id="0"` SAFELY (ast.literal_eval, no exec)."""
    try:
        call = ast.parse(f"_f({arg_str})", mode="eval").body  # type: ignore[attr-defined]
        out: dict[str, Any] = {}
        for kw in call.keywords:  # type: ignore[attr-defined]
            if kw.arg is None:
                continue
            try:
                out[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                out[kw.arg] = None
        return out
    except Exception:
        return {}


def _sid(v: Any) -> str | None:
    return None if v is None else str(v)


def parse_twitter_action(text: str) -> dict[str, Any]:
    """Parse a HiSim-style 'Thought:/Action: fn(...)/Stance:' block into a structured dict.

    Replaces HiSim's `eval("self._" + output)` with a safe regex + ast.literal_eval parse.
    Returns {kind, payload, stance, thought}. Unrecognised/blank → do_nothing.
    """
    text = text or ""
    stance_m = _STANCE_RE.search(text)
    thought_m = _THOUGHT_RE.search(text)
    stance = stance_m.group(1) if stance_m else "Neutral"
    thought = thought_m.group(1).strip() if thought_m else ""

    m = _ACTION_RE.search(text)
    if not m:
        return {"kind": "do_nothing", "payload": {}, "stance": stance, "thought": thought}
    fn = m.group(1).strip().lower()
    a = _parse_kwargs(m.group(2))

    if fn == "post":
        payload = {"text": a.get("content", "") or ""}
    elif fn == "retweet":
        payload = {"text": a.get("content") or "", "author": a.get("author"),
                   "parent_id": _sid(a.get("original_tweet_id"))}
    elif fn == "reply":
        payload = {"text": a.get("content", "") or "", "author": a.get("author"),
                   "parent_id": _sid(a.get("original_tweet_id"))}
    elif fn == "like":
        payload = {"author": a.get("author"), "parent_id": _sid(a.get("original_tweet_id"))}
    else:
        fn = "do_nothing"
        payload = {}
    return {"kind": fn, "payload": payload, "stance": stance, "thought": thought}


# ================================================================================================
# M2 — the core-user prompt (mirrors HiSim agent._fill_prompt_template + the Stance request)
# ================================================================================================
_PROMPT_TEMPLATE = """You are {name} on Twitter. React to what you observe.
(1) Your description: {role}
(2) The news you got: {news}
(3) Your history: {history}
(4) Your recent memory: {memory}
(5) The tweet page you can see:
{tweet_page}
(6) Notifications: {notifications}

Choose ONE action and give a thought first, in EXACTLY this format:
Thought: <your reasoning>
Action: <one of post(content="..."), retweet(content="...", author="...", original_tweet_id="..."), reply(content="...", author="...", original_tweet_id="..."), like(author="...", original_tweet_id="..."), do_nothing()>
Stance: <Favor|Against|Neutral toward {target}>
"""


def build_core_prompt(ob: Observation, memory_text: str = "", target: str = "the movement") -> str:
    li = ob.local_information or {}
    mi = ob.macro_information or {}
    return _PROMPT_TEMPLATE.format(
        name=ob.agent_id,
        role=li.get("role_description", ""),
        news=mi.get("trigger_news", "") or "(no news)",
        history=li.get("personal_history", "") or "(none)",
        memory=memory_text or "(none)",
        tweet_page=li.get("tweet_page", "") or "(empty)",
        notifications=li.get("notifications", "") or "(none)",
        target=target,
    )


def _memory_text(memory: Any) -> str:
    """Render the SocioVerse2 AgentMemory.recent() into a short string for the prompt."""
    if memory is None:
        return ""
    try:
        items = memory.recent(5)
    except Exception:
        return ""
    return " | ".join(f"t{it['t']}:{it.get('action_kind')}" for it in items)


# ================================================================================================
# M4 — per-core personal-history summary (extractive; LLM summary is an optional upgrade)
# ================================================================================================
def summarize_history(tweet_path: str | None, top_k: int = 5) -> str:
    """Extractive summary of a user's historical tweets (newline-JSON snscrape). Deterministic,
    no LLM. FAITHFUL role: seeds the agent's `personal_history` prompt field (HiSim PersonalMemory)."""
    if not tweet_path or not os.path.exists(tweet_path):
        return ""
    texts: list[str] = []
    with open(tweet_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            c = (t.get("rawContent") or t.get("content") or "").replace("\n", " ").strip()
            if c:
                texts.append(c)
            if len(texts) >= top_k:
                break
    return " || ".join(texts)


# ================================================================================================
# world builders — both produce the SAME id-keyed shape consumed by population + environment
#   keys: core[ids], ord[ids], opinions{id:float}, audience{core_id:[core_id]},
#         roles{core_id:str}, history{core_id:path|None}
# ================================================================================================
def _synth(seed: int, n_core: int, n_ord: int) -> dict[str, Any]:
    """Deterministic synthetic world (M1 smoke / CI). Replaced by load_movement for real runs."""
    rng = random.Random(seed)
    core = [core_id(i) for i in range(n_core)]
    ordn = [ord_id(i) for i in range(n_ord)]
    opinions = {aid: round(rng.uniform(-1.0, 1.0), 4) for aid in core + ordn}
    # FAITHFUL: follower_dict[A] = A's AUDIENCE (who sees A). Synthetic ring among core.
    audience = ({core[i]: [core[(i + 1) % n_core], core[(i - 1) % n_core]] for i in range(n_core)}
                if n_core > 1 else {c: [] for c in core})
    roles = {aid: f"Synthetic core user {aid}." for aid in core}
    history = {aid: None for aid in core}
    return {"core": core, "ord": ordn, "opinions": opinions, "audience": audience,
            "roles": roles, "history": history}


def load_init_att(config_path: str | Path) -> dict[str, float]:
    """Extract {username: init_att} from a HiSim ref config's abm_model block (regex, fast).
    Config order per entry is `init_att:` then `name:`, so we pair them; the later agents
    section has `name:` with no preceding init_att and is ignored."""
    out: dict[str, float] = {}
    pend: float | None = None
    for line in Path(config_path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*init_att:\s*([-\d.]+)", line)
        if m:
            try:
                pend = float(m.group(1))
            except ValueError:
                pend = None
            continue
        m = re.match(r"\s*name:\s*(\S+)", line)
        if m and pend is not None:
            out[m.group(1)] = pend
            pend = None
    return out


def load_movement(data_root: str | Path, movement: str, config_path: str | Path | None = None,
                  limit_core: int | None = None, limit_ord: int | None = None) -> dict[str, Any]:
    """Load a real HiSim movement (roe/metoo/blm) into the id-keyed world shape.

    Reads role_desc_v2_clean.json (core users + descriptions), follower_dict.json (audience),
    tweet/<user>.txt (personal history), and init_att from the ref config's abm_model block.
    """
    root = Path(data_root) / "user_data" / movement
    roles_raw: dict[str, str] = json.loads((root / "role_desc_v2_clean.json").read_text(encoding="utf-8"))
    followers: dict[str, list[str]] = json.loads((root / "follower_dict.json").read_text(encoding="utf-8"))

    core_users = list(roles_raw.keys())
    if limit_core is not None:
        core_users = core_users[:limit_core]
    core_set = set(core_users)

    init_att = load_init_att(config_path) if config_path else {}
    # ordinary = abm population names that are not core (only when we have the full config)
    ord_users = [u for u in init_att.keys() if u not in core_set]
    if limit_ord is not None:
        ord_users = ord_users[:limit_ord]

    def op_of(u: str) -> float:
        return float(init_att.get(u, round((_h(u) % 2000) / 1000.0 - 1.0, 4)))  # fallback if no config

    core = [core_id(u) for u in core_users]
    ordn = [ord_id(u) for u in ord_users]
    opinions = {core_id(u): op_of(u) for u in core_users}
    opinions.update({ord_id(u): op_of(u) for u in ord_users})
    audience = {core_id(u): [core_id(a) for a in followers.get(u, []) if a in core_set] for u in core_users}
    roles = {core_id(u): roles_raw[u] for u in core_users}
    history = {core_id(u): str(root / "tweet" / f"{u}.txt") for u in core_users}
    return {"core": core, "ord": ordn, "opinions": opinions, "audience": audience,
            "roles": roles, "history": history}


def _build_world(args: dict[str, Any]) -> dict[str, Any]:
    """Shared by population + environment so they agree. Real data when `data_root` is given."""
    if args.get("data_root"):
        return load_movement(args["data_root"], args.get("movement", "roe"),
                             config_path=args.get("config_path"), limit_core=args.get("limit_core"),
                             limit_ord=args.get("limit_ord"))
    return _synth(int(args.get("seed", 42)), int(args.get("n_core", 8)), int(args.get("n_ord", 12)))


# ================================================================================================
# P — fixed population pool (core LLM users + ordinary ABM users)
# ================================================================================================
@register("population", "hisim.pop")
class HiSimPopulationProvider(PopulationProvider):
    def __init__(self, bundle: PopulationBundle):
        self.bundle = bundle
        self._w = _build_world(bundle.provider_args)

    def build(self, seed: int) -> list[Persona]:
        w = self._w
        out: list[Persona] = []
        for aid in w["core"]:
            out.append(Persona(
                agent_id=aid, group_key="core",
                attributes={"username": _uname(aid), "role_description": w["roles"].get(aid, "")},
                init_state={"opinion": w["opinions"][aid]},
            ))
        for aid in w["ord"]:
            out.append(Persona(
                agent_id=aid, group_key="ordinary",
                attributes={"username": _uname(aid)},
                init_state={"opinion": w["opinions"][aid]},
            ))
        return out

    def neighbors(self, aid: str) -> list[str]:
        # A's audience = where A's tweets propagate (env.apply pushes to these). Outbound.
        return self._w["audience"].get(aid, [])


# ================================================================================================
# E — the Twitter world (owns tweet_db / pages / inbox / the global opinion field)
# ================================================================================================
@register("environment", "hisim.twitter_env")
class TwitterEnvironmentProvider(EnvironmentProvider):
    def __init__(self, bundle: EnvironmentBundle):
        self.bundle = bundle
        a = bundle.provider_args
        self.alpha = float(a.get("alpha", 0.3))        # BCM social-influence strength
        self.bc_bound = float(a.get("bc_bound", 0.1))  # BCM confidence bound
        self.target = a.get("target", "the movement")
        self.top_k = int(a.get("history_top_k", 5))
        self.seed = int(a.get("seed", 42))
        self._w = _build_world(a)
        self._hist_summary: dict[str, str] = {}        # lazy cache of personal_history summaries
        # mutable state (set in reset)
        self.opinions: dict[str, float] = {}
        self.pages: dict[str, list[dict]] = {}
        self.inbox: dict[str, list[str]] = {}          # FAITHFUL: replies reach a target's memory
        self.tweet_db: dict[str, dict] = {}
        self.news: str | None = None
        self._fired: set[int] = set()
        self._last_kind: dict[str, str] = {}
        self.rng = random.Random(self.seed)

    # --- lifecycle ---
    def reset(self, seed: int) -> None:
        w = self._w
        self.opinions = dict(w["opinions"])
        self.pages = {aid: [] for aid in w["core"]}    # only core have timelines
        self.inbox = {aid: [] for aid in w["core"]}
        self.tweet_db = {}
        self.news = None
        self._fired = set()
        self._last_kind = {}
        self.rng = random.Random(seed)

    def advance_to(self, t: int) -> list[ScheduledEvent]:
        fired: list[ScheduledEvent] = []
        for ev in self.bundle.scheduled_events:
            if ev.at_step == t and id(ev) not in self._fired:
                self._fired.add(id(ev))
                fired.append(ev)
        # FAITHFUL: trigger_news — activate the macro-information broadcast within its ttl window.
        active = [b for b in self.bundle.information_program.broadcasts
                  if b.at_step <= t < b.at_step + b.ttl]
        content = active[-1].content if active else None
        # FAITHFUL: if the news is phrased "<author> posts a tweet ..." inject it as a real post to
        # everyone's page (HiSim check_tweet); otherwise it stays a macro-information field.
        if content and "posts a tweet" in content:
            author = content.split("posts a tweet")[0].strip() or "News"
            self._inject_tweet(author, content, to_all=True)
            self.news = None
        else:
            self.news = content
        return fired

    # --- observation (E_t materialized per agent) ---
    def observe_batch(self, agent_ids: list[str], t: int, round_idx: int = 0) -> list[Observation]:
        out: list[Observation] = []
        ops = self.opinions
        for aid in agent_ids:
            if is_core(aid):
                page = "\n".join(
                    f"tweet id: {m['id']} [{m['sender']}]: {m['content']}"
                    for m in self.pages.get(aid, [])
                )
                out.append(Observation(
                    agent_id=aid, step=t,
                    local_information={
                        "role_description": self._w["roles"].get(aid, ""),
                        "personal_history": self._history(aid),
                        "tweet_page": page,
                        "info_box": "",                      # FAITHFUL: info_box inert (latent bug)
                        "notifications": " || ".join(self.inbox.get(aid, [])[-self.top_k:]),
                    },
                    macro_information={"trigger_news": self.news} if self.news else {},
                ))
            else:
                x = ops[aid]
                # FAITHFUL: BCM peer = a random agent within the GLOBAL confidence band
                # (|Δopinion| < bc_bound), NOT a follower-graph neighbor.
                cands = [op for bid, op in ops.items() if bid != aid and abs(op - x) < self.bc_bound]
                peer = self.rng.choice(cands) if cands else None
                out.append(Observation(
                    agent_id=aid, step=t,
                    local_physical={"own_opinion": x, "bcm_peer_opinion": peer},
                ))
        return out

    # --- endogenous feedback E_{t+1} = f(E_t, B_t) ---
    def apply(self, actions: list[Action]) -> None:
        for a in actions:
            aid = a.agent_id
            if a.kind == "update_opinion":                  # ordinary BCM result
                self.opinions[aid] = float(a.payload["opinion"])
                continue
            # --- core actions ---
            self._last_kind[aid] = a.kind
            if "att" in a.payload:                          # mirror: opinion = tweet stance (incl. 0 on silence)
                self.opinions[aid] = float(a.payload["att"])
            parent = a.payload.get("parent_id")
            if a.kind == "post":
                self._inject_tweet(aid, a.payload.get("text", ""))
            elif a.kind == "retweet":
                self._inject_tweet(aid, a.payload.get("text", ""))
                if parent in self.tweet_db:                  # FAITHFUL: num_rt++ on the original
                    self.tweet_db[parent]["num_rt"] += 1
            elif a.kind == "reply":
                # FAITHFUL: reply does NOT touch tweet_page / info_box / num_cmt (latent 'comment' bug);
                # it reaches the original author only via their memory → route to that author's inbox.
                tgt = self._author_to_id(a.payload.get("author"))
                if tgt and tgt in self.inbox:
                    self.inbox[tgt].append(f"[{_uname(aid)} replied]: {a.payload.get('text','')}")
            elif a.kind == "like":
                if parent in self.tweet_db:                  # FAITHFUL: num_like++ only
                    self.tweet_db[parent]["num_like"] += 1
            # do_nothing: only the mirror (att=0) applies

    # --- helpers ---
    def _inject_tweet(self, sender: str, content: str, to_all: bool = False) -> str:
        tid = str(len(self.tweet_db))
        tweet = {"id": tid, "sender": _uname(sender) if is_core(sender) else sender,
                 "content": content, "num_rt": 0, "num_cmt": 0, "num_like": 0}
        self.tweet_db[tid] = tweet
        # FAITHFUL: propagate to the sender's audience (+sender); news-as-tweet → everyone.
        targets = list(self.pages.keys()) if to_all else (self._w["audience"].get(sender, []) + [sender])
        for u in targets:
            if u in self.pages:
                self.pages[u].insert(0, tweet)
                self.pages[u] = self.pages[u][:5]          # most-recent 5
        return tid

    def _author_to_id(self, author: str | None) -> str | None:
        if not author:
            return None
        cid = core_id(author)
        return cid if cid in self.pages else None

    def _history(self, aid: str) -> str:
        if aid not in self._hist_summary:
            self._hist_summary[aid] = summarize_history(self._w["history"].get(aid), self.top_k)
        return self._hist_summary[aid]

    def agent_state(self, aid: str) -> dict:
        return {
            "opinion": self.opinions.get(aid),
            "group": "core" if is_core(aid) else "ordinary",
            "last_action": self._last_kind.get(aid),
        }

    def snapshot(self) -> dict:
        return {"n_tweets": len(self.tweet_db), "news_active": self.news is not None}


# ================================================================================================
# B — hybrid decision: core via LLM (M2) / faked (M1); ordinary via BCM rule
# ================================================================================================
def _scripted_llm(prompt: str) -> str:
    """Deterministic stand-in for a real LLM: returns a valid Thought/Action/Stance block derived
    from the prompt hash, so M2's parse+att pipeline is exercised end-to-end without API."""
    h = _h(prompt)
    kind = ["post", "retweet", "reply", "like", "do_nothing"][h % 5]
    stance = ["Favor", "Against", "Neutral"][(h >> 3) % 3]
    body = {"Favor": "I strongly support this, it is wonderful and just.",
            "Against": "This is terrible and unjust, I oppose it.",
            "Neutral": "I am noting this development."}[stance]
    if kind == "post":
        act = f'post(content="{body}")'
    elif kind == "retweet":
        act = f'retweet(content="agreed", author="someone", original_tweet_id="0")'
    elif kind == "reply":
        act = f'reply(content="{body}", author="someone", original_tweet_id="0")'
    elif kind == "like":
        act = 'like(author="someone", original_tweet_id="0")'
    else:
        return "Thought: nothing to add.\nAction: do_nothing()\nStance: Neutral"
    return f"Thought: reacting.\nAction: {act}\nStance: {stance}"


def _load_dotenv(root: Path | None = None) -> None:
    """Hydrate SV_LLM_* from `.env` without overriding the process env: `root/.env` when
    given, else the documented lookup order ($SV_HOME/.env, ./.env, then the repo root)."""
    from socioverse.external_events import _load_dotenv as load

    load(root)


class _OpenAILLM:
    """Thin openai>=2 adapter (prod path). Reads SV_LLM_API_KEY/OPENAI_API_KEY + SV_LLM_BASE_URL
    (default the official OpenAI API) + SV_LLM_MODEL, from env or the repo-root .env."""

    def __init__(self, model: str | None = None, temperature: float = 1.0, max_tokens: int = 256):
        _load_dotenv()
        self.model = model or os.environ.get("SV_LLM_MODEL", "gpt-4o-mini")
        self.temperature, self.max_tokens = temperature, max_tokens
        self._client = None

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=os.environ.get("SV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("SV_LLM_BASE_URL", "https://api.openai.com/v1"),
            )
        return self._client

    def __call__(self, prompt: str) -> str:
        resp = self._ensure().chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


def _make_llm(kind: str, **kw) -> Callable[[str], str]:
    if kind == "scripted":
        return _scripted_llm
    if kind == "openai":
        return _OpenAILLM(**kw)
    raise ValueError(f"unknown llm_kind: {kind!r}")


@register("decision", "hisim.hybrid_decision")
class HybridTwitterDecision(DecisionModel):
    def __init__(self, alpha: float = 0.3, bc_bound: float = 0.1, mode: str = "fake",
                 llm_kind: str = "scripted", target: str = "the movement", model: str | None = None):
        self.alpha = alpha
        self.bc_bound = bc_bound
        self.mode = mode                  # "fake" (M1, hash stub) | "llm" (M2)
        self.target = target
        self.sentiment_fn: Callable[[str], float] = _default_sentiment
        self.llm: Callable[[str], str] | None = _make_llm(llm_kind, model=model) if mode == "llm" else None

    def decide_batch(self, obs: list[Observation], memories: dict[str, Any]) -> list[Action]:
        return [
            self._decide_core(ob, memories.get(ob.agent_id)) if is_core(ob.agent_id)
            else self._decide_ordinary(ob)
            for ob in obs
        ]

    def _decide_ordinary(self, ob: Observation) -> Action:
        x = ob.local_physical["own_opinion"]
        peer = ob.local_physical.get("bcm_peer_opinion")
        # FAITHFUL: assimilate toward the like-minded peer within the confidence bound (Deffuant).
        new = x + self.alpha * (peer - x) if peer is not None else x
        new = round(max(-1.0, min(1.0, new)), 4)
        return Action(agent_id=ob.agent_id, step=ob.step, kind="update_opinion",
                      payload={"opinion": new}, source="rule", rationale=[f"peer={peer}"])

    def _decide_core(self, ob: Observation, memory: Any) -> Action:
        if self.mode == "fake":
            return self._decide_core_fake(ob)
        # --- mode == "llm": build prompt → call LLM → parse → att (mirror) ---
        prompt = build_core_prompt(ob, _memory_text(memory), target=self.target)
        try:
            resp = self.llm(prompt)  # type: ignore[misc]
        except Exception:
            resp = ""
        parsed = parse_twitter_action(resp)
        kind, payload = parsed["kind"], dict(parsed["payload"])
        if kind == "do_nothing":
            payload["att"] = 0.0          # FAITHFUL: silence → att 0 (mirror writes neutral)
        else:
            text = payload.get("text") or f"{kind} a tweet"
            payload["att"] = compute_att(text, parsed["stance"], self.sentiment_fn)
        return Action(agent_id=ob.agent_id, step=ob.step, kind=kind, payload=payload,
                      source="llm", rationale=[parsed.get("thought", "")])

    def _decide_core_fake(self, ob: Observation) -> Action:
        """M1 deterministic stand-in (no prompt/parse) — keeps the no-API smoke + CI cheap."""
        h = _h(f"{ob.agent_id}|{ob.step}")
        if h % 3 == 0:
            return Action(agent_id=ob.agent_id, step=ob.step, kind="do_nothing",
                          payload={"att": 0.0}, source="fallback", rationale=["fake:silence"])
        att = round(((h % 1000) / 500.0) - 1.0, 4)
        return Action(agent_id=ob.agent_id, step=ob.step, kind="post",
                      payload={"text": f"[{ob.agent_id}@{ob.step}] stance {att}", "att": att},
                      source="fallback", rationale=["fake:post"])


# ================================================================================================
# metrics — HiSim get_measures (bias/diversity) + behavioral counts
# ================================================================================================
@register("collector", "hisim.metrics")
class MovementMetricCollector(MetricCollector):
    def collect(self, env: Any, actions: list[Action], t: int) -> dict[str, Any]:
        ops = list(env.opinions.values())
        core = [op for aid, op in env.opinions.items() if is_core(aid)]
        ordn = [op for aid, op in env.opinions.items() if not is_core(aid)]
        n_active = sum(1 for a in actions if is_core(a.agent_id) and a.kind != "do_nothing")
        n_post = sum(1 for a in actions if a.kind in ("post", "retweet"))
        return {
            "bias": round(mean(ops) - NEUTRAL, 4),          # FAITHFUL: mean attitude − neutral(0)
            "diversity": round(pvariance(ops), 6),          # FAITHFUL: variance of attitudes
            "mean_core": round(mean(core), 4) if core else 0.0,
            "mean_ordinary": round(mean(ordn), 4) if ordn else 0.0,
            "n_active": n_active,
            "n_post": n_post,
        }

    def columns(self) -> list[str]:
        return list(HISIM_METRICS)


# ================================================================================================
# artifact factories
# ================================================================================================
def _news_program(target: str, n_steps: int, news_step: int) -> tuple[list[ScheduledEvent], InformationProgram]:
    return (
        [ScheduledEvent(at_step=news_step, target_layer="trigger_news", op="set",
                        property_name="content", value=1.0, note="trigger news fires")],
        InformationProgram(broadcasts=[
            Broadcast(message_id="N1", channel="trigger_news", at_step=news_step, ttl=n_steps,
                      audience="all", content=f"News- a major event concerning {target} occurs."),
        ]),
    )


def _layers() -> list[EnvironmentLayer]:
    return [
        EnvironmentLayer(name="tweet_feed", modality="information", scope="local",
                         dynamics="endogenous", description="audience timeline of recent tweets"),
        EnvironmentLayer(name="trigger_news", modality="information", scope="macro",
                         dynamics="scheduled", description="offline event news broadcast"),
        EnvironmentLayer(name="peer_opinion", modality="physical", scope="macro",
                         dynamics="endogenous", description="global confidence-band peer opinions (BCM)"),
    ]


def _study_spec(study_id, n_steps, seed, target) -> StudySpec:
    return StudySpec(
        study_id=study_id,
        title="HiSim hybrid social-movement opinion dynamics (from-scratch port)",
        research_question="How do core (LLM) + ordinary (ABM) users' opinions evolve after trigger news?",
        hypothesis="Bounded-confidence assimilation plus a trigger-news shock shift the population's "
                   "bias and shrink its diversity over turns.",
        study_type="longitudinal", n_steps=n_steps, seed=seed, metrics=list(HISIM_METRICS),
        domain="social-movement/opinion-dynamics",
        tags=["hisim", "opinion-dynamics", "hybrid", "twitter", "from-scratch"],
        legacy_simulator="from_scratch",
        provider_refs=["hisim.twitter_env", "hisim.pop", "hisim.hybrid_decision", "hisim.metrics"],
        adjustable_params=["n_core", "n_ord", "alpha", "bc_bound", "news schedule", "target", "movement"],
        status="demo-only",
    )


def make_hisim_bundles(
    study_id: str = "hisim_roe", *, n_core: int = 8, n_ord: int = 12, n_steps: int = 4, seed: int = 42,
    alpha: float = 0.3, bc_bound: float = 0.1, target: str = "the protection of Abortion Rights",
    news_step: int = 2,
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    """Synthetic, no-API bundles (M1 smoke / committed artifacts; core decision mode='fake')."""
    w = _synth(seed, n_core, n_ord)
    args = {"n_core": n_core, "n_ord": n_ord, "seed": seed}
    events, info = _news_program(target, n_steps, news_step)
    env_bundle = EnvironmentBundle(
        study_id=study_id, provider_ref="hisim.twitter_env",
        provider_args={**args, "alpha": alpha, "bc_bound": bc_bound, "target": target},
        layers=_layers(), scheduled_events=events, information_program=info,
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="hisim.pop", provider_args=args,
        interaction=InteractionStructure(kind="explicit_network",
                                         edges=[(a, u) for a, us in w["audience"].items() for u in us]),
        propagation=PropagationMode.CONTAGION,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed, decision_ref="hisim.hybrid_decision",
        decision_args={"alpha": alpha, "bc_bound": bc_bound, "mode": "fake"},
        collector_ref="hisim.metrics", interaction_rounds=1,
    )
    return _study_spec(study_id, n_steps, seed, target), env_bundle, pop_bundle, sim_config


def make_hisim_bundles_from_data(
    study_id: str = "hisim_roe", *, data_root: str, movement: str = "roe", config_path: str | None = None,
    n_steps: int = 14, seed: int = 42, alpha: float = 0.3, bc_bound: float = 0.1,
    target: str = "the protection of Abortion Rights", news_step: int = 0,
    limit_core: int | None = None, limit_ord: int | None = None,
    llm_kind: str = "scripted", model: str = "gpt-4o-mini",
) -> tuple[StudySpec, EnvironmentBundle, PopulationBundle, SimulationConfig]:
    """Real-data bundles: population/environment load from HiSim/data/user_data/<movement>/ and the
    ref config's init_att. Core decision runs `mode='llm'` (llm_kind default 'scripted' = no API;
    'openai' = live gpt-4o-mini via SV_LLM_* env)."""
    args = {"data_root": data_root, "movement": movement, "config_path": config_path,
            "limit_core": limit_core, "limit_ord": limit_ord, "seed": seed}
    w = load_movement(data_root, movement, config_path=config_path, limit_core=limit_core)
    events, info = _news_program(target, n_steps, news_step)
    env_bundle = EnvironmentBundle(
        study_id=study_id, provider_ref="hisim.twitter_env",
        provider_args={**args, "alpha": alpha, "bc_bound": bc_bound, "target": target},
        layers=_layers(), scheduled_events=events, information_program=info,
    )
    pop_bundle = PopulationBundle(
        study_id=study_id, provider_ref="hisim.pop", provider_args=args,
        interaction=InteractionStructure(kind="explicit_network",
                                         edges=[(a, u) for a, us in w["audience"].items() for u in us]),
        propagation=PropagationMode.CONTAGION,
    )
    sim_config = SimulationConfig(
        study_id=study_id, n_steps=n_steps, seed=seed, decision_ref="hisim.hybrid_decision",
        decision_args={"alpha": alpha, "bc_bound": bc_bound, "mode": "llm", "llm_kind": llm_kind,
                        "target": target, "model": model},
        collector_ref="hisim.metrics", interaction_rounds=1,
    )
    return _study_spec(study_id, n_steps, seed, target), env_bundle, pop_bundle, sim_config
