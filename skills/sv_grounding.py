"""Grounding sidecar for SocioVerse2 studies (stdlib only — no socioverse import).

``studies/<id>/grounding/grounding.json`` records the study's real-world anchors:
**facts** with provenance, **implementation_refs** (how similar phenomena are modeled),
and declared **assumptions**. Deliberately NOT a pydantic handoff artifact — a flat,
merge-friendly JSON the sv-* stages append to ("ground before you invent") and the
dashboard renders read-only. Downloaded reference tables (small, MB-scale) live next
to it under ``grounding/data/`` and are pointed at by ``source.local_path``.

Document shape (convention, not schema):

    {"study_id": "...", "query": "...", "updated_at": "...", "method_notes": "...",
     "implementation_refs": [{"title", "url", "takeaway", "accessed"}],
     "facts": [{"id", "claim", "value", "unit", "as_of",
                "basis": "sourced" | "proxy" | "assumed",
                "source": {"title", "url",
                           "via": "event_service" | "web_search" | "provider" | "user",
                           "accessed", "local_path"?},
                "applies_to": ["environment.provider_args.base", ...], "note"}],
     "assumptions": [{"id", "claim", "rationale"}]}

``method_notes="stylized"`` + empty facts records the *decision* that a study has no
real-world anchors (abstract/toy models) — distinct from grounding merely missing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FILENAME = "grounding.json"
SUBDIR = "grounding"
BASES = ("sourced", "proxy", "assumed")


def grounding_path(study_dir: str | Path) -> Path:
    return Path(study_dir) / SUBDIR / FILENAME


def load(study_dir: str | Path) -> dict | None:
    """Parsed grounding.json, or None when missing/corrupt (callers treat as empty)."""
    p = grounding_path(study_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _skeleton(study_dir: str | Path) -> dict:
    return {"study_id": Path(study_dir).name, "query": None, "updated_at": None,
            "method_notes": None, "implementation_refs": [], "facts": [], "assumptions": []}


def _merge_by_id(cur: list, new, prefix: str) -> list:
    """Upsert by ``id`` preserving list order; entries without an id get ``<prefix><N>``."""
    idx = {e.get("id"): i for i, e in enumerate(cur) if e.get("id")}
    n = 0
    for e in new:
        e = dict(e)
        if not e.get("id"):
            n += 1
            while f"{prefix}{n}" in idx:
                n += 1
            e["id"] = f"{prefix}{n}"
        if e["id"] in idx:
            cur[idx[e["id"]]] = e
        else:
            idx[e["id"]] = len(cur)
            cur.append(e)
    return cur


def _merge_refs(cur: list, new) -> list:
    """Dedupe implementation_refs by url (falling back to title): same key replaces."""
    key = lambda r: r.get("url") or r.get("title")
    idx = {key(r): i for i, r in enumerate(cur) if key(r)}
    for r in new:
        r = dict(r)
        k = key(r)
        if k and k in idx:
            cur[idx[k]] = r
        else:
            if k:
                idx[k] = len(cur)
            cur.append(r)
    return cur


def merge(study_dir: str | Path, *, facts=(), implementation_refs=(), assumptions=(),
          method_notes: str | None = None, query: str | None = None) -> Path:
    """Merge entries into grounding.json (creating it, and ``grounding/``, if absent).

    Facts/assumptions upsert by ``id`` (order preserved; missing ids assigned ``f<N>``/
    ``a<N>`` past collisions); refs dedupe by url; ``method_notes``/``query`` overwrite
    only when not None. ``updated_at`` bumps on every merge. Write is atomic (tmp +
    rename, like sv_workspace._write_manifest) — the dashboard poller must never read
    a torn file. Returns the file path.
    """
    doc = load(study_dir) or _skeleton(study_dir)
    doc["facts"] = _merge_by_id(doc.get("facts") or [], facts, "f")
    doc["assumptions"] = _merge_by_id(doc.get("assumptions") or [], assumptions, "a")
    doc["implementation_refs"] = _merge_refs(doc.get("implementation_refs") or [],
                                             implementation_refs)
    if method_notes is not None:
        doc["method_notes"] = method_notes
    if query is not None:
        doc["query"] = query
    doc["updated_at"] = _now_iso()

    p = grounding_path(study_dir)
    p.parent.mkdir(parents=True, exist_ok=True)  # tolerate pre-grounding scaffolds
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def summary(study_dir: str | Path) -> str:
    """One-liner for sv_emit narratives / stage reports.

    '12 facts: 8 sourced / 2 proxy / 2 assumed · 3 refs · 2 assumptions'
    'stylized model, no real-world anchors'  (method_notes=="stylized", no facts)
    'no grounding recorded'                  (file missing/corrupt)
    """
    doc = load(study_dir)
    if doc is None:
        return "no grounding recorded"
    facts = doc.get("facts") or []
    if not facts and doc.get("method_notes") == "stylized":
        return "stylized model, no real-world anchors"
    counts = {b: 0 for b in BASES}
    for f in facts:
        if f.get("basis") in counts:
            counts[f["basis"]] += 1
    parts = [f"{len(facts)} facts: " + " / ".join(f"{counts[b]} {b}" for b in BASES)]
    if doc.get("implementation_refs"):
        parts.append(f"{len(doc['implementation_refs'])} refs")
    if doc.get("assumptions"):
        parts.append(f"{len(doc['assumptions'])} assumptions")
    return " · ".join(parts)
