"""SocioVerse2 run dashboard — local sidecar (stdlib only).

A passive, read-only viewer over a study's standardized artifacts. It scans
``studies/<id>/`` (the same file layout every ``/sv-*`` skill writes into),
reconstructs the pipeline state, and serves a single-page UI with live refresh
over Server-Sent Events.

Design notes
------------
* **File = authoritative state.** Stage status, the bound config, and the metric
  curve are all derived from the artifacts on disk, so the view survives a CC
  restart and reflects hand-edits too.
* **Reasoning comes through ``/ingest`` (L2).** The skills self-report a short
  ``narrative`` per stage via ``dashboard/hooks/sv_emit.py``; it is persisted as
  ``studies/<id>/narrative/<stage>.json`` and merged onto the matching stage.
* **Zero third-party deps for the UI.** Pure stdlib, so any Python 3.11+ can serve it.
  The DuckDB-backed views (the Dataset tab's simulation tables, and the Experiments tab's
  per-agent drill-down when a run left no ``panel_live.jsonl``) read
  ``trajectory/study.duckdb`` and therefore need ``duckdb`` in the interpreter that launches
  this server; without it those tables stay empty and everything else still works.
* **Local vs hosted.** Run from a checkout this is the *local* form: the page it serves
  is marked ``<body class="sv-local">`` and ``/api/state`` reports ``mode: "local"``, so
  the cockpit hides UI that only the hosted workbench backs (chat dock, "new study" /
  "all studies" links, quota, notices). ``SV_DASH_HOSTED=1`` switches that off.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# server/app.py -> dashboard -> repo root
REPO = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
# The published UI is the v2 cockpit (dashboard/web/v2/). The classic v1 index.html left the
# repo on 2026-08-07; an old checkout that still has only v1 on disk falls back to it.
V2_DIR = WEB_DIR / "v2"
STATIC_CT = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
             ".json": "application/json", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


def ui_index() -> Path | None:
    for f in (V2_DIR / "index.html", WEB_DIR / "index.html"):
        if f.is_file():
            return f
    return None


# URLs that serve the cockpit page. ``/app/v2/`` is the hosted workbench's address for the same
# page; the cockpit links there (tour redirect, study adoption), so the local server answers it too.
UI_INDEX_PATHS = ("/", "/index.html", "/v2", "/v2/", "/v2/index.html", "/app/v2/", "/app/v2/index.html")
# Prefixes a static cockpit file may be addressed under (besides the site root).
UI_STATIC_PREFIXES = ("app/v2/", "v2/")
LOCAL_MARKER = "sv-local"   # body class the local server stamps on the page (see ui_page)


def is_hosted() -> bool:
    """True inside the hosted workbench's per-user container (it sets SV_DASH_HOSTED=1)."""
    return bool(os.environ.get("SV_DASH_HOSTED"))


def ui_page(f: Path) -> bytes:
    """The cockpit page as served by THIS server. Locally the ``<body>`` gets the ``sv-local``
    class, so hosted-only UI is hidden from the first paint (no flash, no request to endpoints
    only the hosted service has). The hosted service and the static gallery serve index.html
    by other means and never carry the marker."""
    html = f.read_bytes()
    if is_hosted():
        return html
    return html.replace(b"<body>", b'<body class="' + LOCAL_MARKER.encode() + b'">', 1)


def ui_static(path: str) -> Path | None:
    """A file of the v2 cockpit, addressed from the site root (``/app.js``, ``/tabs/x.js``,
    ``/vendor/katex/...``) or under ``/v2/`` / ``/app/v2/``. Never escapes V2_DIR."""
    rel = path.lstrip("/")
    for prefix in UI_STATIC_PREFIXES:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    if not rel:
        return None
    root = V2_DIR.resolve()
    fp = (root / rel).resolve()
    if fp != root and root not in fp.parents:
        return None
    return fp if fp.is_file() else None
STUDIES_ROOT = REPO / "studies"
# Source fingerprint at startup. The server is a long-lived shared process, so after this
# file is edited a running instance serves STALE logic while index.html (read from disk per
# request) is already new — the exact mismatch that made the version box fall back to a
# disabled "v1". /api/state exposes it (sv_emit handshakes) and the poller self-recycles.
APP_SRC_MTIME = Path(__file__).stat().st_mtime

# The six pipeline stages, in order. ``model`` only applies to Path B
# (from-scratch) studies; for adapter/reuse studies it is reported as skipped.
STAGES = [
    ("sv-init", "study.yaml"),
    ("sv-build-model", "model.py"),
    ("sv-build-environment", "environment.json"),
    ("sv-build-population", "population.json"),
    ("sv-run", "study.duckdb"),
    ("sv-report", "report.md"),
]

# L2 narratives are now DURABLE, version-scoped files: ``studies/<id>/narrative/<stage>.json``
# (written by dashboard/hooks/sv_emit.py). They ride version snapshots + branch restores like
# every other artifact, so the dashboard reads each version's own reasoning from the dir it
# renders — no in-memory per-(study,stage) store that bled a sibling version's text onto a
# carried stage or vanished on an archived view. See read_narratives().
LATEST_QUERY: dict | None = None     # set by UserPromptSubmit hook (the originating research need)
# Intent checklist (the sv-init Step −1 clarification checklist). Before setup it exists only in the session: the agent resends
# the whole thing on every state change (intent_checklist ingest); the latest copy is kept here and sent with /api/state for
# the newmode center pane to render. A new query (user_query) clears it — leftovers from the previous session must not pollute a new study.
# After setup, sv_emit archives it as studies/<id>/intent.json, which goes through the regular build_detail path.
INTENT: dict | None = None
SESSION_ACTIVE: bool = False         # toggled by user_query / run_idle lifecycle events
AWAITING: bool = False               # True while Claude Code is waiting for the user (Stop hook)
AWAITING_TS: float = 0.0             # when the waiting signal arrived (for TTL auto-expire)
AWAIT_TTL: float = float(os.environ.get("SV_DASH_AWAIT_TTL", "300"))  # banner auto-clears after this many s
LAST_ACTIVITY: float = time.time()   # for the opt-in idle reaper (SV_DASH_IDLE); off by default
_lock = threading.Lock()
_subscribers: list[queue.Queue] = []


# ── artifact helpers ────────────────────────────────────────────────────────
def study_paths(d: Path) -> dict[str, Path]:
    return {
        "study": d / "study.yaml",
        "manifest": d / "versions.json",   # version manifest — live study root only
        "resources": d / "resources.json",
        "model": d / "model.py",
        "environment": d / "environment" / "environment.json",
        "population": d / "population" / "population.json",
        "simulation": d / "simulation" / "simulation.json",
        "duckdb": d / "trajectory" / "study.duckdb",
        "metrics": d / "trajectory" / "metrics_history.json",
        "progress": d / "trajectory" / "progress.jsonl",
        "panel_live": d / "trajectory" / "panel_live.jsonl",
        "report": d / "reports" / "report.md",
        "figures": d / "reports" / "figures",
        "grounding": d / "grounding" / "grounding.json",   # sidecar metadata — NOT a stage
        "intent": d / "intent.json",    # archived intent checklist (sv-init Step −1) — sidecar
        "narrative": d / "narrative",   # per-stage L2 reasoning files — sidecar, version-scoped by dir
    }


def load_json(p: Path):
    """study.yaml is written as JSON-in-.yaml, so json.load covers every artifact."""
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def fmt_ts(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else ""


def is_study_dir(d: Path) -> bool:
    return d.is_dir() and (d / "study.yaml").exists() and not d.name.startswith((".", "_"))


# ── per-artifact summaries (feed the stage cards) ───────────────────────────
def env_summary(p: Path) -> dict | None:
    e = load_json(p)
    if not e:
        return None
    layers = [
        {"name": L.get("name"), "axis": f"{L.get('modality')}/{L.get('scope')}",
         "dynamics": L.get("dynamics")}
        for L in e.get("layers", [])
    ]
    events = [
        {"at_step": ev.get("at_step"), "note": ev.get("note") or ev.get("op")}
        for ev in e.get("scheduled_events", [])
    ]
    broadcasts = [
        {"at_step": b.get("at_step"),
         "audience": "all" if b.get("audience") == "all" else "targeted",
         "channel": b.get("channel"),
         "content": (b.get("content") or "")[:160]}
        for b in e.get("information_program", {}).get("broadcasts", [])
    ]
    return {"layers": layers, "scheduled_events": events, "broadcasts": broadcasts}


_DIST_CACHE: dict[str, tuple] = {}   # roster_path → (mtime, result); the 1 Hz SSE refresh during a run does not recompute the static population


def population_distribution(roster: Path, *, max_rows: int = 8000,
                           top_cat: int = 6, nbins: int = 10) -> dict | None:
    """Aggregate the roster written by build-population (each agent's t=0 state) into per-attribute distributions,
    so the card shows the population's overall profile: numeric attributes → min/median/max/mean + histogram;
    categorical attributes → share per category (high-cardinality fields such as ids / free text are skipped).
    Cached by roster mtime — once materialized the population is static, so the frequent SSE refreshes during a run hit the cache at zero cost."""
    if not roster.exists():
        return None
    key = str(roster)
    mt = roster.stat().st_mtime
    hit = _DIST_CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    cols: dict[str, list] = {}
    n = 0
    try:
        with roster.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    st = (json.loads(line).get("state")) or {}
                except ValueError:
                    continue
                n += 1
                for k, v in st.items():
                    if v is not None:
                        cols.setdefault(k, []).append(v)
                if n >= max_rows:
                    break
    except OSError:
        return None
    if not n:
        return None
    import statistics
    attrs = []
    for k, vals in cols.items():
        if k in ("reason", "rationale"):
            continue                    # a decision output, not a population attribute
        if any(isinstance(v, (dict, list)) for v in vals):
            continue                    # non-scalar attributes (e.g. reports:{}) are not distributions; skip them — otherwise str(v) produces noise
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)
        if numeric:
            xs = sorted(float(v) for v in vals)
            lo, hi = xs[0], xs[-1]
            hist = [0] * nbins
            if hi > lo:
                w = (hi - lo) / nbins
                for x in xs:
                    hist[min(int((x - lo) / w), nbins - 1)] += 1
            else:
                hist = [len(xs)]
            attrs.append({"attr": k, "kind": "num", "n": len(xs), "min": lo, "max": hi,
                          "median": statistics.median(xs), "mean": sum(xs) / len(xs), "hist": hist})
        else:
            counts: dict[str, int] = {}
            for v in vals:
                s = str(v)
                counts[s] = counts.get(s, 0) + 1
            if len(counts) > 25:          # ids / free text: nothing worth showing, skip
                continue
            ordered = sorted(counts.items(), key=lambda kv: -kv[1])
            top = [{"v": vv, "n": cc, "pct": cc / len(vals)} for vv, cc in ordered[:top_cat]]
            attrs.append({"attr": k, "kind": "cat", "n": len(vals), "distinct": len(counts),
                          "top": top, "other": sum(cc for _, cc in ordered[top_cat:])})
    result = {"n_agents": n, "attrs": attrs}
    _DIST_CACHE[key] = (mt, result)
    return result


def pop_summary(p: Path) -> dict | None:
    pop = load_json(p)
    if not pop:
        return None
    personas = pop.get("personas") or []
    inter = pop.get("interaction") or {}
    count = pop.get("materialized_count")     # authoritative once sv-build-population instantiates
    if count is None:
        count = len(personas)
    return {
        "provider_ref": pop.get("provider_ref"),
        "propagation": pop.get("propagation"),
        "interaction_kind": inter.get("kind"),
        "persona_count": count,
        "provider_args": pop.get("provider_args") or {},
        "distribution": population_distribution(p.parent / "roster.jsonl"),   # the population's overall profile (per-attribute distributions)
    }


def sim_summary(p: Path) -> dict | None:
    s = load_json(p)
    if not s:
        return None
    return {k: s.get(k) for k in
            ("n_steps", "seed", "decision_ref", "collector_ref", "interaction_rounds")}


def grounding_summary(p: Path) -> dict | None:
    """grounding/grounding.json → the study-level references card. Sidecar written by the
    sv-* skills via skills/sv_grounding.py; entry caps keep the detail payload bounded."""
    g = load_json(p)
    if not g:
        return None
    facts = g.get("facts") or []
    counts = {"sourced": 0, "proxy": 0, "assumed": 0}
    for f in facts:
        if f.get("basis") in counts:
            counts[f["basis"]] += 1
    counts["assumed"] += len(g.get("assumptions") or [])   # declared assumptions count too (previously only facts with basis=assumed were counted → it showed 0)

    def src(f):
        s = f.get("source") or {}
        return {k: s.get(k) for k in ("title", "url", "via", "accessed", "local_path")}

    return {
        "method_notes": g.get("method_notes"),
        "updated_at": g.get("updated_at"),
        "counts": counts,
        "facts": [{"id": f.get("id"), "claim": (f.get("claim") or "")[:200],
                   "value": f.get("value"), "unit": f.get("unit"), "as_of": f.get("as_of"),
                   "basis": f.get("basis"), "source": src(f),
                   "note": (f.get("note") or "")[:200] or None}
                  for f in facts[:40]],
        "implementation_refs": [{"title": (r.get("title") or "")[:160], "url": r.get("url"),
                                 "takeaway": (r.get("takeaway") or "")[:200] or None}
                                for r in (g.get("implementation_refs") or [])[:12]],
        "assumptions": [{"id": a.get("id"), "claim": (a.get("claim") or "")[:200],
                         "rationale": (a.get("rationale") or "")[:200] or None}
                        for a in (g.get("assumptions") or [])[:20]],
    }


def read_narratives(narr_dir: Path) -> dict[str, dict]:
    """Per-stage L2 reasoning from ``narrative/<stage>.json`` (written by sv_emit). Keyed by stage
    name; each value carries {narrative, ts}. Version-scoped by LOCATION: the dir passed in is the
    version being rendered (live root or an archived ``versions/vN`` snapshot), so a carried stage
    shows the reasoning of the version whose file it actually is — never a sibling's, never blank."""
    out: dict[str, dict] = {}
    if not narr_dir.is_dir():
        return out
    for f in narr_dir.glob("*.json"):
        o = load_json(f)
        if o and o.get("narrative"):
            out[f.stem] = {"narrative": o.get("narrative"), "ts": o.get("ts") or mtime(f)}
    return out


def read_progress(p: Path):
    """Tail trajectory/progress.jsonl: (summary {step,n_steps,ts}, flattened rows for the live chart)."""
    if not p.exists():
        return None, []
    rows, last = [], None
    try:
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            last = o
            row = dict(o.get("metrics") or {})
            row["step"] = o.get("step")
            rows.append(row)
    except Exception:
        pass
    summary = {"step": last.get("step"), "n_steps": last.get("n_steps"),
               "ts": last.get("ts")} if last else None
    return summary, rows


def interventions_of(env: dict | None) -> list[int]:
    if not env:
        return []
    steps = {ev["at_step"] for ev in env["scheduled_events"] if ev.get("at_step") is not None}
    steps |= {b["at_step"] for b in env["broadcasts"] if b.get("at_step") is not None}
    return sorted(steps)


# ── stage / state reconstruction ────────────────────────────────────────────
INHERITABLE = {"sv-build-model", "sv-build-environment", "sv-build-population"}

# Upstream dependencies per stage — a done stage built BEFORE one of these (or downstream of a
# stale one) is STALE: it no longer reflects the rebuilt upstream. Two deliberate choices:
#   • study.yaml (sv-init) is NOT a dependency — it is mostly metadata and gets touched for benign
#     reasons (re-saves, discovery fields, being forked), which would cascade-flag everything.
#   • population does NOT depend on environment — both are independent inputs; only sv-run binds them.
# So staleness keys off the build artifacts that actually feed downstream (env/pop/model → run → report).
STAGE_DEPS = {
    "sv-init": [],
    "sv-build-model": [],
    "sv-build-environment": [],
    "sv-build-population": [],
    "sv-run": ["sv-build-model", "sv-build-environment", "sv-build-population"],
    "sv-report": ["sv-run"],
}


def fork_source(study: dict) -> str | None:
    """If this study was forked (Path A), return the source study_id from created_by, else None."""
    m = re.search(r"fork of ([\w\-]+)", study.get("created_by") or "")
    return m.group(1) if m else None


# ── study versioning (versions.json: live dir = current version, versions/vN = archive) ──
def study_manifest(study_root: Path) -> dict | None:
    return load_json(study_root / "versions.json")


def version_kind(entry: dict) -> str:
    """``"branch"`` (inherits its parent's realized history and changes only E from the fork step
    on) or ``"version"`` (any other change, cold run). Manifests written before ``kind`` existed
    are classified by their warm-start provenance, so old studies render correctly unmigrated."""
    kind = (entry or {}).get("kind")
    if kind in ("branch", "version"):
        return kind
    return "branch" if ((entry or {}).get("warm_start") or {}).get("source") else "version"


def version_fork_step(entry: dict) -> int | None:
    """The first step a branch computes itself; derived from ``warm_start`` on old manifests."""
    fs = (entry or {}).get("fork_step")
    if isinstance(fs, int):
        return fs
    ws = (entry or {}).get("warm_start") or {}
    if ws.get("source") is None:
        return None
    try:
        return int(ws.get("resume_from", 0)) + 1
    except (TypeError, ValueError):
        return None


def versions_view(study_root: Path) -> tuple[list[dict], str]:
    """(versions projection for the UI, current id). Implicit single v1 when no manifest —
    pre-versioning studies still show a (disabled) default version box."""
    man = study_manifest(study_root)
    if not man or not man.get("versions"):
        return [{"id": "v1", "parent": None, "note": "", "created_at": None,
                 "ts": "", "current": True, "kind": "version", "fork_step": None,
                 "branch_of": None, "downgraded": False}], "v1"
    cur = man.get("current") or man["versions"][-1].get("id", "v1")
    out = [{"id": v.get("id"), "parent": v.get("parent"), "note": v.get("note") or "",
            "created_at": v.get("created_at"), "ts": fmt_ts(v.get("created_at") or 0),
            "current": v.get("id") == cur,
            # branch vs version: the UI labels them differently and pairs a branch with its
            # source for control/treatment comparison.
            "kind": version_kind(v), "fork_step": version_fork_step(v),
            "branch_of": (v.get("warm_start") or {}).get("source"),
            "downgraded": bool(v.get("downgraded_from_branch")),
            "resume_from_stage": v.get("resume_from_stage")} for v in man["versions"]]
    return out, cur


def version_dir(study_root: Path, vid: str) -> tuple[Path | None, bool]:
    """Resolve a version id to a renderable dir: (live root, False) for the current
    version, (snapshot dir, True) for an archived one, (None, _) when unknown."""
    _, cur = versions_view(study_root)
    if vid == cur:
        return study_root, False
    man = study_manifest(study_root) or {}
    e = next((v for v in man.get("versions", []) if v.get("id") == vid), None)
    snap = (e or {}).get("snapshot")
    p = study_root / snap if snap else None
    return (p if p and p.is_dir() else None), True


def stage_mtimes(paths: dict[str, Path]) -> dict[str, float]:
    """Per-stage artifact mtimes — shared by stage status AND the event log."""
    return {
        "sv-init": mtime(paths["study"]),
        "sv-build-model": mtime(paths["model"]),
        "sv-build-environment": mtime(paths["environment"]),
        "sv-build-population": mtime(paths["population"]),
        "sv-run": max(mtime(paths["metrics"]), mtime(paths["duckdb"]), mtime(paths["progress"])),
        "sv-report": mtime(paths["report"]),
    }


def compute_stages(paths: dict[str, Path], is_path_b: bool, study_id: str,
                   forked_at: float | None = None, version_ts: float | None = None,
                   version_parent: str | None = None,
                   resume_from_stage: str | None = None, archived: bool = False) -> list[dict]:
    exists = {
        "sv-init": paths["study"].exists(),
        "sv-build-model": paths["model"].exists(),
        "sv-build-environment": paths["environment"].exists(),
        "sv-build-population": paths["population"].exists(),
        "sv-run": paths["metrics"].exists(),   # done only when final metrics land; duckdb alone = mid-run
        "sv-report": paths["report"].exists(),
    }
    mtimes = stage_mtimes(paths)
    # L2 narratives are durable, version-scoped files under the dir being rendered — so an
    # archived snapshot shows ITS reasoning and a carried stage never inherits a sibling's text.
    narr = read_narratives(paths["narrative"])
    stages = []
    for name, artifact in STAGES:
        if name == "sv-build-model" and not is_path_b:
            status = "skipped"
        elif exists[name]:
            status = "done"
            # Path-A fork: a copied bundle older than the fork's study.yaml was inherited
            # from the source, NOT re-authored here — don't show it as this study's own.
            if forked_at and name in INHERITABLE and mtimes[name] < forked_at:
                status = "inherited"
        elif forked_at and name == "sv-build-model":
            status = "inherited"   # forked Path-B study reuses the source's model (model.py not copied)
        else:
            status = "pending"
        stages.append({
            "name": name, "artifact": artifact, "status": status,
            "ts": fmt_ts(mtimes[name]), "mtime": mtimes[name],
            "narrative": narr.get(name, {}).get("narrative"),
        })
    # staleness: a done stage built before an upstream dep (or downstream of a stale one) no
    # longer reflects it — e.g. re-running sv-build-environment leaves the old run/report stale.
    smt = {s["name"]: s["mtime"] for s in stages}
    stale: set = set()
    for s in stages:
        if s["status"] != "done":
            continue
        deps = STAGE_DEPS.get(s["name"], [])
        dep_mt = [smt[d] for d in deps if smt[d] > 0]
        if (dep_mt and s["mtime"] < max(dep_mt)) or any(d in stale for d in deps):
            s["status"] = "stale"
            stale.add(s["name"])
    # version-carried + iterate REVIEW GATE. In a v>1 version (live or archived snapshot) a done
    # artifact older than the version's creation was carried from the parent. On an ITERATED
    # version every carried stage from the re-entry point forward must be explicitly handled THIS
    # version — either re-authored (mtime >= version_ts, already "done") or verify+skipped, which
    # /sv-iterate records by posting that stage's narrative. A carried stage that is NEITHER shows
    # "review" (needs review) and holds the pointer, so the pipeline can never look finished with an
    # unreviewed carried artifact and the dashboard walks every stage from the re-entry point.
    # resume_from_stage = the recorded re-entry (a branch re-authors only E → sv-build-environment;
    # a version started from an OLDER version defaults to sv-init = review from the start); if it is
    # missing/unknown, fail safe to the FIRST carried stage — NEVER the run pointer.
    if version_ts and version_parent:
        for s in stages:
            if s["status"] == "done" and 0 < s["mtime"] < version_ts:
                s["carried_from"] = version_parent   # neutral reuse tag (vs a fork's amber "inherited")
        # The review gate applies ONLY to the LIVE current version (work in progress). An archived
        # snapshot is frozen history — never mark its carried stages "review" (older versions predate
        # narrative files and would ALL flag review; a finished version's carried stages are settled).
        if not archived:
            order = [s["name"] for s in stages]
            carried = [i for i, s in enumerate(stages) if s.get("carried_from")]
            resume = resume_from_stage if resume_from_stage in order else (order[carried[0]] if carried else None)
            if resume in order:
                ri = order.index(resume)
                for i, s in enumerate(stages):
                    # carried, at/after the re-entry, and lacking a THIS-version narrative → not reviewed
                    if i >= ri and s.get("carried_from") and ((narr.get(s["name"], {}) or {}).get("ts") or 0) < version_ts:
                        s["status"] = "review"
    # pointer: an unreviewed carried stage (review gate) wins; else first not-yet-done stage after
    # the last completed one, so an inherited bundle a later done stage consumed isn't the resume point.
    review_first = next((s["name"] for s in stages if s["status"] == "review"), None)
    if review_first:
        active_name = review_first
    else:
        last_done = max((i for i, s in enumerate(stages) if s["status"] == "done"), default=-1)
        active_name = next((s["name"] for i, s in enumerate(stages)
                            if i > last_done and s["status"] in ("inherited", "pending", "stale")), None)
    for s in stages:
        s["active"] = (s["name"] == active_name)
    return stages


def build_events(study_root: Path, study_id: str) -> list[dict]:
    """The study's append-only activity log, reconstructed from disk on every request.

    History survives iterations because version snapshots preserve artifact mtimes
    (``create_version`` copies with ``copy2``): each archived version still carries the
    timestamps of the stages authored IN it, so a stage appears once per version that
    (re)built it — log semantics, not latest-state semantics. Stages carried from an
    ancestor (mtime < the version's created_at) are reported by the ancestor only. Stage
    narratives are read the same way — from each version's own ``narrative/<stage>.json``
    (durable + snapshotted), so the feed is version-tagged with no in-memory bleed. Version
    creations come from the manifest. Newest first, capped.
    """
    man = study_manifest(study_root) or {}
    versions = man.get("versions") or []
    cur = man.get("current")
    events: list[dict] = []

    def add_stage_events(d: Path, vid: str, floor: float | None) -> None:
        mts = stage_mtimes(study_paths(d))
        for name, artifact in STAGES:
            t = mts[name]
            if t <= 0 or (floor and t < floor):
                continue                     # absent, or carried from an ancestor
            events.append({"ts": t, "t": fmt_ts(t), "kind": "stage",
                           "version": vid, "stage": name, "label": artifact})
        for stage, n in read_narratives(study_paths(d)["narrative"]).items():
            nt = n.get("ts") or 0
            if nt <= 0 or (floor and nt < floor):
                continue                     # carried narrative → reported by the ancestor
            events.append({"ts": nt, "t": fmt_ts(nt), "kind": "narrative",
                           "version": vid, "stage": stage, "label": n.get("narrative") or ""})

    if versions:
        for v in versions:
            vid = v.get("id")
            d = study_root if vid == cur else (study_root / v["snapshot"] if v.get("snapshot") else None)
            if not d or not d.is_dir():
                continue
            add_stage_events(d, vid, v.get("created_at") if v.get("parent") else None)
            if v.get("created_at"):
                events.append({"ts": v["created_at"], "t": fmt_ts(v["created_at"]),
                               "kind": "version", "version": vid, "label": v.get("note") or ""})
    else:
        add_stage_events(study_root, "v1", None)

    events.sort(key=lambda e: -(e.get("ts") or 0))
    return events[:120]


def build_detail(d: Path, *, study_root: Path | None = None, viewing: str | None = None,
                 archived: bool = False) -> dict:
    """Reconstruct one version's view. ``d`` is the dir to render (live root, or an
    archived ``versions/vN`` snapshot); the manifest is always read from the live
    ``study_root`` (snapshots don't carry one)."""
    root = study_root or d
    paths = study_paths(d)
    study = load_json(paths["study"]) or {"study_id": d.name}
    legacy = study.get("legacy_simulator", "")
    is_path_b = legacy == "from_scratch"
    path_label = "Path B · from scratch" if is_path_b else f"Path A/C · wraps {legacy or 'legacy'}"
    forked_from = fork_source(study)
    forked_at = mtime(paths["study"]) if forked_from else None

    versions, cur_version = versions_view(root)
    viewing = viewing or cur_version
    ventry = next((v for v in versions if v["id"] == viewing), None) or {}

    env = env_summary(paths["environment"])
    metrics = load_json(paths["metrics"]) or {}
    progress, progress_rows = read_progress(paths["progress"])
    figures = []
    if paths["figures"].is_dir():
        figures = sorted(p.name for p in paths["figures"].glob("*.png"))

    stages = compute_stages(paths, is_path_b, study.get("study_id", d.name), forked_at,
                            version_ts=ventry.get("created_at"),
                            version_parent=ventry.get("parent"),
                            resume_from_stage=ventry.get("resume_from_stage"),
                            archived=archived)
    paper_info, literature_info = _paper_lit_info(d)
    return {
        "paper_info": paper_info,
        "literature_info": literature_info,
        "study_id": study.get("study_id", d.name),
        "title": study.get("title", d.name),
        "research_question": study.get("research_question"),
        "hypothesis": study.get("hypothesis"),
        # per-language display variants (optional StudySpec fields; the web UI picks by LANG)
        "title_i18n": study.get("title_i18n") or {},
        "research_question_i18n": study.get("research_question_i18n") or {},
        "hypothesis_i18n": study.get("hypothesis_i18n") or {},
        "study_type": study.get("study_type"),
        "n_steps": study.get("n_steps"),
        "seed": study.get("seed"),
        "metrics": study.get("metrics", []),
        "metric_descriptions": study.get("metric_descriptions") or {},
        "display_metrics": study.get("display_metrics") or [],
        "key_attributes": study.get("key_attributes") or [],
        "run_note": study.get("run_note") or {},
        "domain": study.get("domain"),
        "tags": study.get("tags", []),
        "path_label": path_label,
        "is_path_b": is_path_b,
        "forked_from": forked_from,
        "versions": versions,
        "current_version": cur_version,
        "viewing_version": viewing,
        "archived": archived,
        "version_note": ventry.get("note") or "",
        "stages": stages,
        "environment": env,
        "population": pop_summary(paths["population"]),
        "simulation": sim_summary(paths["simulation"]),
        "grounding": grounding_summary(paths["grounding"]),
        "intent": load_json(paths["intent"]),
        "metrics_rows": metrics.get("rows", []),
        "final_metrics": metrics.get("final_metrics") or None,
        "metrics_downsampled": metrics.get("downsampled") or None,
        "progress": progress,
        "progress_rows": progress_rows,
        "interventions": interventions_of(env),
        "figures": figures,
        "report_md": paths["report"].read_text() if paths["report"].exists() else None,
        "events": build_events(root, study.get("study_id", d.name)),   # study-level log (all versions)
    }


def list_studies() -> list[Path]:
    if not STUDIES_ROOT.is_dir():
        return []
    return sorted((d for d in STUDIES_ROOT.iterdir() if is_study_dir(d)), key=lambda p: p.name)


def is_hidden_template(d: Path, study: dict) -> bool:
    """Category-1 pure template shell → hidden from the dashboard list. These are the abm_* benchmark
    scaffolds (created_by='abm-umbrella') with nothing built yet. Reference studies (cat 2) and user /
    test studies (cat 3) — including user *forks* of an abm template (created_by='sv-init (fork …)') —
    are always shown. Override with SV_DASH_SHOW_TEMPLATES=1."""
    if os.environ.get("SV_DASH_SHOW_TEMPLATES"):
        return False
    if study.get("created_by") != "abm-umbrella":
        return False
    p = study_paths(d)
    built = any(p[k].exists() for k in ("environment", "population", "metrics", "duckdb", "report"))
    return not built


def build_state() -> dict:
    items, newest, newest_t = [], None, -1.0
    for d in list_studies():
        paths = study_paths(d)
        m = max(mtime(p) for p in paths.values() if p.suffix or p.name == "study.yaml")
        sy = load_json(paths["study"]) or {}
        if is_hidden_template(d, sy):
            continue                       # category-1 template shell — hidden from the list
        fa = mtime(paths["study"]) if fork_source(sy) else None
        versions, cur_version = versions_view(d)
        cve = next((v for v in versions if v["id"] == cur_version), {})   # the live/current version entry
        stages = compute_stages(paths, sy.get("legacy_simulator") == "from_scratch", d.name, fa,
                                version_ts=cve.get("created_at"), version_parent=cve.get("parent"),
                                resume_from_stage=cve.get("resume_from_stage"), archived=False)
        done = sum(1 for s in stages if s["status"] == "done")
        total = sum(1 for s in stages if s["status"] != "skipped")
        active = next((s["name"] for s in stages if s.get("active")), None)
        items.append({"study_id": d.name, "title": sy.get("title", d.name),
                      "title_i18n": sy.get("title_i18n") or {},
                      "reference": bool(sy.get("reference")),
                      "domain": sy.get("domain") or "",
                      "mtime": m, "progress": {"done": done, "total": total}, "active_stage": active,
                      "version": {"current": cur_version, "count": len(versions)}})
        if m > newest_t:
            newest_t, newest = m, d.name
    items.sort(key=lambda x: -(x.get("mtime") or 0))   # sorted by activity time (most recent change) descending
    return {"studies": items, "current_id": newest, "generated_at": time.time(),
            "dash_src_mtime": APP_SRC_MTIME,   # handshake: which app.py this process runs
            "latest_query": LATEST_QUERY, "session_active": SESSION_ACTIVE,
            "intent": INTENT,
            # "local" = served from a checkout by this stdlib server; the cockpit hides hosted-only
            # UI in that mode. local_open: only the local form can open a study file with the
            # system's default app / reveal it in a folder (always False in a hosted container).
            "mode": "hosted" if is_hosted() else "local",
            "local_open": not is_hosted(),
            "awaiting": AWAITING and (time.time() - AWAITING_TS) < AWAIT_TTL}


# ── per-agent panel (roster pre-run, live via panel_live.jsonl, DuckDB post-run) ──
def _read_panel_jsonl(p: Path) -> list:
    rows = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def read_panel(d: Path):
    """Per-agent rows (agent_id, step, state, action_kind, action_payload) + a source tag.

    Priority: the lock-free panel_live.jsonl (readable mid-run) → the finalized DuckDB store
    (read-only, safe once the run released its lock) → the pre-run population/roster.jsonl that
    sv-build-population materializes (so the agent inspector shows every initialized agent BEFORE
    any run). Source tag is one of "live" | "duckdb" | "roster" | None (empty).
    """
    live_file = d / "trajectory" / "panel_live.jsonl"
    if live_file.exists():
        return _read_panel_jsonl(live_file), "live"
    db = d / "trajectory" / "study.duckdb"
    if db.exists():
        try:
            import duckdb
            con = duckdb.connect(str(db), read_only=True)
            rows = [{"agent_id": a, "step": s, "state": json.loads(st),
                     "action_kind": ak, "action_payload": json.loads(ap or "{}")}
                    for a, s, st, ak, ap in con.execute(
                        "SELECT agent_id, step, state, action_kind, action_payload "
                        "FROM panel ORDER BY step, agent_id").fetchall()]
            con.close()
            return rows, "duckdb"
        except Exception:
            return [], None
    roster = d / "population" / "roster.jsonl"
    if roster.exists():
        return _read_panel_jsonl(roster), "roster"
    return [], None


_PHASE = {"live": "live", "duckdb": "post_run", "roster": "initial"}


def agents_summary(d: Path) -> dict:
    rows, source = read_panel(d)
    by: dict[str, dict] = {}
    dims: list[str] = []
    steps: set = set()
    for r in rows:
        steps.add(r.get("step"))
        st = r.get("state") or {}
        for k in st:
            if k not in dims:
                dims.append(k)
        a = by.setdefault(r["agent_id"], {"agent_id": r["agent_id"], "latest_step": -1,
                                          "state": {}, "last_action": None})
        if r.get("step", -1) >= a["latest_step"]:
            a["latest_step"], a["state"], a["last_action"] = r.get("step", -1), st, r.get("action_kind")
    return {"agents": sorted(by.values(), key=lambda a: a["agent_id"]), "dims": dims,
            "steps": sorted(s for s in steps if s is not None), "count": len(by),
            "live": source == "live", "phase": _PHASE.get(source)}


def find_figure(d: Path, name: str) -> Path | None:
    """Resolve a cited figure name: reports/figures first, then paper/figures
    (sv-paper's own visualizations). Plain names only — no separators."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    for base in (study_paths(d)["figures"], d / "paper" / "figures"):
        fp = base / name
        if fp.is_file():
            return fp
    return None


def agent_detail(d: Path, aid: str, *, max_rows: int = 1500) -> dict:
    rows, source = read_panel(d)
    arows = sorted([r for r in rows if r.get("agent_id") == aid], key=lambda r: r.get("step", 0))
    total = len(arows)
    if total > max_rows:   # trajectories with tens of thousands of steps (e.g. a 10k-episode training-style simulation): sample evenly, keep the first and last, so the frontend stays responsive
        stride = -(-total // max_rows)
        arows = arows[::stride] + ([arows[-1]] if (total - 1) % stride else [])
    return {"agent_id": aid, "rows": arows, "total_rows": total,
            "live": source == "live", "phase": _PHASE.get(source)}


# ── v2 cockpit endpoints (additive, read-only; the v1 UI ignores them) ──────
# Whitelisted browse roots inside a study dir. Everything else (runs/, versions/,
# __pycache__, dotfiles) is invisible to the file API.
V2_BROWSE_DIRS = ("uploads", "grounding", "environment", "population", "simulation",
                  "trajectory", "reports", "narrative", "literature", "paper")
V2_TOP_FILES = ("study.yaml", "versions.json", "resources.json", "model.py")
# Extensions the raw file reader will serve (as text unless noted). Binary science
# stores (duckdb/parquet) go through the /data endpoints instead of raw reads.
V2_TEXT_EXT = {".csv": "text/csv", ".tsv": "text/tab-separated-values",
               ".json": "application/json", ".jsonl": "application/json",
               ".txt": "text/plain", ".md": "text/markdown", ".yaml": "text/plain",
               ".yml": "text/plain", ".py": "text/plain", ".bib": "text/plain",
               ".tex": "text/plain", ".html": "text/plain"}
V2_IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".svg": "image/svg+xml"}
V2_FILE_MAX = 5 * 1024 * 1024      # raw text read cap
V2_LIST_MAX = 400                  # total entries cap for the browse listing


def _file_kind(p: Path) -> str:
    e = p.suffix.lower()
    if e in (".duckdb",):
        return "db"
    if e in (".parquet",):
        return "parquet"
    if e in V2_IMG_EXT:
        return "image"
    if e in (".csv", ".tsv"):
        return "table"
    if e in (".json", ".jsonl", ".yaml", ".yml"):
        return "data"
    if e in (".md", ".txt", ".tex", ".bib"):
        return "doc"
    if e in (".py",):
        return "code"
    return "file"


def files_view(d: Path) -> dict:
    """The study's data-asset inventory: whitelisted dirs walked (depth-capped),
    plus the top-level artifacts. Read-only metadata; contents come via /file/."""
    groups, total = [], 0
    top = []
    for fn in V2_TOP_FILES:
        p = d / fn
        if p.is_file():
            top.append({"rel": fn, "name": fn, "size": p.stat().st_size,
                        "mtime": mtime(p), "ts": fmt_ts(mtime(p)), "kind": _file_kind(p)})
    if top:
        groups.append({"dir": ".", "files": top})
        total += len(top)
    for dn in V2_BROWSE_DIRS:
        root = d / dn
        if not root.is_dir():
            continue
        entries = []
        for p in sorted(root.rglob("*")):
            if total + len(entries) >= V2_LIST_MAX:
                break
            if not p.is_file() or p.name.startswith("."):
                continue
            rel = p.relative_to(d).as_posix()
            if any(seg in ("runs", "versions", "__pycache__") for seg in p.relative_to(d).parts):
                continue
            entries.append({"rel": rel, "name": p.name, "size": p.stat().st_size,
                            "mtime": mtime(p), "ts": fmt_ts(mtime(p)), "kind": _file_kind(p)})
        if entries:
            groups.append({"dir": dn, "files": entries})
            total += len(entries)
    return {"groups": groups, "total": total, "truncated": total >= V2_LIST_MAX}


def resolve_study_file(d: Path, rel: str) -> Path | None:
    """Traversal-safe resolve of a whitelisted study-relative path; None = refuse."""
    rel = unquote(rel).lstrip("/")
    if not rel or rel.startswith("."):
        return None
    first = rel.split("/", 1)[0]
    if not (first in V2_BROWSE_DIRS or (rel in V2_TOP_FILES and "/" not in rel)):
        return None
    try:
        p = (d / rel).resolve()
    except OSError:
        return None
    if not str(p).startswith(str(d.resolve()) + os.sep):
        return None
    if any(seg.startswith(".") or seg in ("runs", "versions", "__pycache__")
           for seg in p.relative_to(d.resolve()).parts[:-1]):
        return None
    return p if p.is_file() else None


def _jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def _duck(d: Path):
    db = d / "trajectory" / "study.duckdb"
    if not db.exists():
        return None
    import duckdb
    return duckdb.connect(str(db), read_only=True)


def data_tables(d: Path) -> dict:
    """DuckDB store overview: tables with columns + row counts (read-only)."""
    try:
        con = _duck(d)
    except Exception as e:
        return {"tables": [], "error": str(e)[:120]}
    if con is None:
        return {"tables": [], "error": None}
    out = []
    try:
        names = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name").fetchall()]
        for t in names[:24]:
            cols = [{"name": c[0], "type": c[1]} for c in con.execute(
                f'DESCRIBE "{t}"').fetchall()]
            n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            out.append({"name": t, "rows": n, "columns": cols})
    except Exception as e:
        return {"tables": out, "error": str(e)[:120]}
    finally:
        con.close()
    return {"tables": out, "error": None}


def data_table_rows(d: Path, name: str, limit: int, offset: int) -> dict:
    """Paged rows from one DuckDB table (JSON-safe values)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name or ""):
        return {"error": "bad table"}
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    try:
        con = _duck(d)
        if con is None:
            return {"error": "no duckdb"}
        cols = [c[0] for c in con.execute(f'DESCRIBE "{name}"').fetchall()]
        total = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        rows = con.execute(
            f'SELECT * FROM "{name}" LIMIT {limit} OFFSET {offset}').fetchall()
        con.close()
    except Exception as e:
        return {"error": str(e)[:160]}
    return {"name": name, "columns": cols, "total": total, "offset": offset,
            "rows": [[_jsonable(v) for v in r] for r in rows]}


def data_table_csv(d: Path, name: str, *, max_rows: int = 100_000) -> bytes | None:
    """One table as CSV bytes for download (row-capped)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name or ""):
        return None
    try:
        con = _duck(d)
        if con is None:
            return None
        cols = [c[0] for c in con.execute(f'DESCRIBE "{name}"').fetchall()]
        rows = con.execute(f'SELECT * FROM "{name}" LIMIT {max_rows}').fetchall()
        con.close()
    except Exception:
        return None
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_jsonable(v) for v in r])
    return buf.getvalue().encode("utf-8-sig")   # BOM: so Excel opens non-ASCII (e.g. Chinese) text without mojibake


def paper_view(d: Path) -> dict:
    """paper/paper.md (sv-paper's sectioned paper draft) → full text + outline (## heading anchors)."""
    p = d / "paper" / "paper.md"
    if not p.exists():
        return {"exists": False}
    try:
        txt = p.read_text()[:2_000_000]
    except OSError:
        return {"exists": False}
    sections = [{"level": len(m.group(1)), "title": m.group(2).strip()}
                for m in re.finditer(r"^(#{1,3})\s+(.+)$", txt, re.M)]
    meta = load_json(d / "paper" / "paper.json") or {}
    return {"exists": True, "md": txt, "sections": sections, "mtime": mtime(p),
            "ts": fmt_ts(mtime(p)), "meta": meta}


def literature_view(d: Path) -> dict:
    """literature/literature.json (sv-lit's retrieval / close-reading output) + references.bib."""
    j = load_json(d / "literature" / "literature.json")
    bib = None
    bp = d / "literature" / "references.bib"
    if bp.exists():
        try:
            bib = bp.read_text()[:400_000]
        except OSError:
            bib = None
    if not j and not bib:
        return {"exists": False}
    return {"exists": True, "data": j, "bib": bib,
            "ts": fmt_ts(max(mtime(d / "literature" / "literature.json"), mtime(bp)))}


def _paper_lit_info(d: Path) -> tuple[dict, dict]:
    """Cheap presence probes for the detail payload (no full reads)."""
    pp = d / "paper" / "paper.md"
    lj = d / "literature" / "literature.json"
    pinfo = {"exists": pp.exists(), "ts": fmt_ts(mtime(pp))}
    n = None
    if lj.exists():
        o = load_json(lj) or {}
        try:
            n = len(o.get("papers") or [])
        except Exception:
            n = None
    linfo = {"exists": lj.exists() or (d / "literature" / "references.bib").exists(),
             "n_papers": n, "ts": fmt_ts(mtime(lj))}
    return pinfo, linfo


def apply_ingest(evt: dict) -> tuple[str | None, str | None]:
    """Pure-ish state transition for one /ingest event (extracted from the handler so the
    lifecycle logic is unit-testable). Returns (study_id, stage) for the SSE broadcast."""
    global LATEST_QUERY, SESSION_ACTIVE, AWAITING, AWAITING_TS, INTENT
    etype, sid, stage = evt.get("type"), evt.get("study_id"), evt.get("stage")
    with _lock:
        if etype == "awaiting_input":
            AWAITING, AWAITING_TS = True, time.time()   # Claude Code paused, waiting for the user
        else:
            AWAITING = False                     # any other signal = working again / user replied
            if etype == "user_query":
                LATEST_QUERY = {"prompt": evt.get("prompt"), "ts": time.time()}
                SESSION_ACTIVE = True
                INTENT = None                    # a new study opens → clear the checklist left over from the previous session
            elif etype == "intent_checklist":
                cl = evt.get("checklist")
                INTENT = cl if isinstance(cl, dict) and cl.get("items") else None
                SESSION_ACTIVE = True
            elif etype == "run_idle":
                SESSION_ACTIVE = False
            elif sid and stage:
                # The narrative itself is now a durable file (sv_emit wrote narrative/<stage>.json
                # before POSTing); this signal just marks the session live + triggers the SSE
                # nudge below so the UI re-reads that file for the version it is showing.
                SESSION_ACTIVE = True
    return sid, stage


# ── SSE pub/sub ─────────────────────────────────────────────────────────────
def touch_activity() -> None:
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.time()


def broadcast(evt: dict) -> None:
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(evt)
        except queue.Full:
            pass


def poller(interval: float = 1.0, srv=None) -> None:
    """Cheap mtime-signature poll; push a 'changed' nudge so the UI re-fetches.

    Also self-recycles when this file's source changes on disk: a stale in-memory server
    can't serve fields the (freshly-read-from-disk) UI expects, so exit and let the next
    ``ensure_up()`` / launch start the current code.
    """
    global AWAITING
    last = None
    while True:
        if srv is not None and mtime(Path(__file__)) != APP_SRC_MTIME:
            print("dashboard source changed on disk — self-recycling (next launch serves the new code)")
            srv.shutdown()
            return
        sig = []
        for d in list_studies():
            for p in study_paths(d).values():
                if p.exists() and p.is_file():
                    sig.append((str(p), p.stat().st_mtime))
        sig = tuple(sorted(sig))
        if sig != last:
            first = last is None
            last = sig
            touch_activity()                       # a study file changed → keep alive (live run)
            if not first:
                # files moving = Claude is WORKING, not waiting — clears a banner that has no
                # explicit `resumed` (e.g. the user answered an AskUserQuestion, which fires
                # no UserPromptSubmit hook), instead of letting it stick until the TTL.
                with _lock:
                    AWAITING = False
            broadcast({"type": "changed", "ts": time.time()})
        time.sleep(interval)


def idle_reaper(srv, timeout: float) -> None:
    """OPT-IN self-shutdown (only runs when SV_DASH_IDLE=<seconds> is set): quit when abandoned
    — no SSE client connected AND no activity for `timeout`s.

    OFF by default so that once launched the dashboard holds :8787 for the whole session (a
    backgrounded tab / paused run never loses it). Enable it only if you'd rather an idle
    server go away and let a later launch re-start a fresh one.
    """
    interval = min(30, max(1, int(timeout)))
    while True:
        time.sleep(interval)
        with _lock:
            no_clients = len(_subscribers) == 0
        if no_clients and (time.time() - LAST_ACTIVITY) > timeout:
            srv.shutdown()
            return


# ── HTTP handler ────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")   # UI/state must never outlive a code upgrade
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _redirect(self, location: str, code: int = 301):
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _study_extra(self, d: Path, tail: str) -> bool:
        """v2 cockpit tails shared by the live and version-scoped study routes.
        True = request handled (response already sent); False = not one of ours."""
        from urllib.parse import parse_qs
        q = parse_qs(urlparse(self.path).query)
        if tail == "files":
            self._json(files_view(d)); return True
        if tail.startswith("file/"):
            p = resolve_study_file(d, tail[len("file/"):])
            if p is None:
                self._json({"error": "not found"}, 404); return True
            ext = p.suffix.lower()
            if ext in V2_IMG_EXT:
                self._send(200, p.read_bytes(), V2_IMG_EXT[ext]); return True
            ct = V2_TEXT_EXT.get(ext)
            if ct is None or p.stat().st_size > V2_FILE_MAX:
                self._json({"error": "unsupported_or_too_large",
                            "size": p.stat().st_size}, 415); return True
            self._send(200, p.read_bytes(), ct + "; charset=utf-8"); return True
        if tail == "data/tables":
            self._json(data_tables(d)); return True
        if tail.startswith("data/table/"):
            name = tail[len("data/table/"):]
            if name.endswith(".csv"):
                csvb = data_table_csv(d, name[:-4])
                if csvb is None:
                    self._json({"error": "not found"}, 404); return True
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(csvb)))
                self.end_headers()
                try:
                    self.wfile.write(csvb)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return True
            try:
                limit = int((q.get("limit") or ["50"])[0])
                offset = int((q.get("offset") or ["0"])[0])
            except ValueError:
                limit, offset = 50, 0
            self._json(data_table_rows(d, name, limit, offset)); return True
        if tail == "paper":
            self._json(paper_view(d)); return True
        if tail == "literature":
            self._json(literature_view(d)); return True
        return False

    def do_GET(self):
        touch_activity()
        url = urlparse(self.path)
        path = unquote(url.path)
        if path == "/app/v2":
            # relative assets resolve against the directory URL, so add the slash (keep the query)
            return self._redirect("/app/v2/" + (f"?{url.query}" if url.query else ""))
        if path in UI_INDEX_PATHS:
            f = ui_index()
            if f is None:
                return self._json({"error": "dashboard UI missing: expected dashboard/web/v2/"}, 404)
            return self._send(200, ui_page(f), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json(build_state())
        if path == "/api/stream":
            return self._stream()
        if path.startswith("/api/study/"):
            rest = path[len("/api/study/"):]
            # version-scoped views FIRST — "<sid>/version/<v>[/agents|/agent/…|/figure/…]"
            # would otherwise be swallowed by the /agent/ / /figure/ splits below.
            if "/version/" in rest:
                sid, vrest = rest.split("/version/", 1)
                vid, _, tail = vrest.partition("/")
                root = STUDIES_ROOT / sid
                if not is_study_dir(root):
                    return self._json({"error": "unknown study"}, 404)
                vd, arch = version_dir(root, vid)
                if vd is None:
                    return self._json({"error": "unknown version"}, 404)
                if tail == "agents":
                    return self._json(agents_summary(vd))
                if tail.startswith("agent/"):
                    return self._json(agent_detail(vd, tail[len("agent/"):]))
                if tail.startswith("figure/"):
                    fp = find_figure(vd, tail[len("figure/"):])
                    if fp is not None:
                        return self._send(200, fp.read_bytes(), "image/png")
                    return self._json({"error": "not found"}, 404)
                if self._study_extra(vd, tail):
                    return
                if tail == "":
                    return self._json(build_detail(vd, study_root=root, viewing=vid, archived=arch))
                return self._json({"error": "not found"}, 404)
            if rest.endswith("/agents"):
                return self._json(agents_summary(STUDIES_ROOT / rest[:-len("/agents")]))
            if "/agent/" in rest:
                sid, aid = rest.split("/agent/", 1)
                return self._json(agent_detail(STUDIES_ROOT / sid, aid))
            if "/figure/" in rest:
                sid, fname = rest.split("/figure/", 1)
                fp = find_figure(STUDIES_ROOT / sid, fname)
                if fp is not None:
                    return self._send(200, fp.read_bytes(), "image/png")
                return self._json({"error": "not found"}, 404)
            if "/" in rest:
                sid, tail = rest.split("/", 1)
                d2 = STUDIES_ROOT / sid
                if is_study_dir(d2) and self._study_extra(d2, tail):
                    return
            d = STUDIES_ROOT / rest
            if is_study_dir(d):
                return self._json(build_detail(d))
            return self._json({"error": "unknown study"}, 404)
        if not path.startswith("/api/"):
            fp = ui_static(path)
            if fp is not None:
                return self._send(200, fp.read_bytes(),
                                  STATIC_CT.get(fp.suffix.lower(), "application/octet-stream"))
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        touch_activity()
        path = unquote(urlparse(self.path).path)
        # ── local form only: open a study file with the system's default app / reveal it in a
        #    folder. A hosted container (SV_DASH_HOSTED=1) always refuses: no desktop there.
        if path.startswith("/api/study/") and path.endswith("/open-file"):
            if is_hosted():
                return self._json({"error": "hosted"}, 403)
            sid = path[len("/api/study/"):-len("/open-file")].strip("/")
            d = STUDIES_ROOT / sid
            if not is_study_dir(d):
                return self._json({"error": "unknown study"}, 404)
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            fp = resolve_study_file(d, str(body.get("rel") or ""))
            if fp is None:
                return self._json({"error": "not found"}, 404)
            mode = body.get("mode") or "open"
            import platform
            import subprocess
            sysname = platform.system()
            try:
                if sysname == "Darwin":
                    cmd = ["open", "-R", str(fp)] if mode == "reveal" else ["open", str(fp)]
                elif sysname == "Windows":
                    cmd = (["explorer", f"/select,{fp}"] if mode == "reveal"
                           else ["cmd", "/c", "start", "", str(fp)])
                else:   # linux: no generic reveal, open the containing directory
                    cmd = ["xdg-open", str(fp.parent if mode == "reveal" else fp)]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                return self._json({"error": "launch_failed", "detail": str(e)[:120]}, 500)
            return self._json({"ok": True, "path": str(fp)})
        if path != "/ingest":
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length", 0))
        try:
            evt = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        sid, stage = apply_ingest(evt)
        broadcast({"type": "ingest", "study_id": sid, "stage": stage, "ts": time.time()})
        self._json({"ok": True})

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=64)
        with _lock:
            _subscribers.append(q)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # heartbeat
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)


def main():
    ap = argparse.ArgumentParser(description="SocioVerse2 run dashboard")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", type=str, default="127.0.0.1",
                    help="bind address (0.0.0.0 for containerized serving)")
    ap.add_argument("--root", type=str, default=None, help="override studies/ dir")
    ap.add_argument("--open", action="store_true", help="open browser on start")
    args = ap.parse_args()

    global STUDIES_ROOT
    if args.root:
        STUDIES_ROOT = Path(args.root).resolve()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=poller, kwargs={"srv": srv}, daemon=True).start()
    # Idle self-reap is OFF by default: once launched the dashboard holds :8787 for the whole
    # session, so a backgrounded tab or paused run never loses the port. Opt back in with
    # SV_DASH_IDLE=<seconds> to restore the old "quit after N idle seconds" behavior.
    idle = int(os.environ.get("SV_DASH_IDLE", "0"))
    if idle > 0:
        threading.Thread(target=idle_reaper, args=(srv, idle), daemon=True).start()
    url = f"http://127.0.0.1:{args.port}"
    reap = f"idle-reap {idle}s" if idle > 0 else "idle-reap off (holds the port)"
    print(f"SocioVerse2 dashboard → {url}   (studies: {STUDIES_ROOT}; {reap})", flush=True)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
