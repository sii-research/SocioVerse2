"""Literature-retrieval helpers for /sv-lit (stdlib only).

Primary source: OpenAlex. Optional enrichment: Semantic Scholar (skipped silently
on 429 — its anonymous pool is often dry).

**OpenAlex needs a key since 2026-02.** Set `OPENALEX_API_KEY` (free, self-service
at openalex.org/settings/api). Without it you get a small demo allowance that a
couple of studies will exhaust, and then every query returns 429 for the rest of
the day — which looks exactly like "no results for this topic". The old
`mailto=` polite-pool trick no longer raises any limit; it is kept only because
OpenAlex still asks callers to identify themselves.
HARD RULE for callers: papers come ONLY from these APIs — never invent or
"remember" a reference. If retrieval fails entirely, say so; do not fabricate.

Artifacts written (read by the dashboard's Literature tab):
  literature/literature.json   {summary, themes[], papers[], queries[], retrieved_at}
  literature/references.bib    valid BibTeX, keys = <firstauthor><year><firstword>
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from socioverse import __version__ as _SV_VERSION
except Exception:  # pragma: no cover - the helper also works without the package installed
    _SV_VERSION = "0"
# Identify the tool to the scholarly APIs; set SV_CONTACT_EMAIL to your own address.
CONTACT = os.environ.get("SV_CONTACT_EMAIL", "contact@socioverse.fudan-disc.com")
UA = {"User-Agent": f"SocioVerse2/{_SV_VERSION} (research; mailto:{CONTACT})"}
OA = "https://api.openalex.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"


def oa_key() -> str:
    return (os.environ.get("OPENALEX_API_KEY") or os.environ.get("SV_OPENALEX_API_KEY") or "").strip()


def _get(url: str, timeout: int = 25, retries: int = 3, backoff: float = 2.0):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — includes HTTP 429/5xx; retry with backoff
            last = e
            time.sleep(backoff * (i + 1))
    raise RuntimeError(f"retrieval failed after {retries} tries: {last}")


def _abstract(inv: dict | None) -> str:
    """OpenAlex stores abstracts as an inverted index — reconstruct plain text."""
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))[:1200]


def oa_search(query: str, n: int = 10) -> list[dict]:
    """OpenAlex search → normalized paper dicts (title/authors/year/venue/citations/url/doi/abstract)."""
    q = urllib.parse.quote(query)
    key = oa_key()
    auth = f"&api_key={urllib.parse.quote(key)}" if key else ""
    d = _get(f"{OA}?search={q}&per-page={min(n, 25)}&mailto={CONTACT}{auth}")
    out = []
    for w in d.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {})
        authors = [(a.get("author") or {}).get("display_name") or "" for a in (w.get("authorships") or [])]
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        out.append({
            "id": w.get("id"), "title": w.get("display_name") or "",
            "authors": [a for a in authors if a][:8],
            "year": w.get("publication_year"),
            "venue": src.get("display_name") or (w.get("type") or ""),
            "citations": w.get("cited_by_count"),
            "doi": doi,
            "url": (w.get("doi") or w.get("id") or ""),
            "abstract": _abstract(w.get("abstract_inverted_index")),
        })
    return out


def s2_search(query: str, n: int = 10) -> list[dict]:
    """Semantic Scholar (optional; raises on persistent 429 — callers should catch & skip)."""
    q = urllib.parse.quote(query)
    d = _get(f"{S2}?query={q}&limit={min(n, 20)}&fields=title,abstract,year,venue,citationCount,authors,externalIds,url")
    out = []
    for p in d.get("data", []):
        out.append({
            "id": p.get("paperId"), "title": p.get("title") or "",
            "authors": [a.get("name") or "" for a in (p.get("authors") or [])][:8],
            "year": p.get("year"), "venue": p.get("venue") or "",
            "citations": p.get("citationCount"),
            "doi": (p.get("externalIds") or {}).get("DOI"),
            "url": p.get("url") or "", "abstract": (p.get("abstract") or "")[:1200],
        })
    return out


def dedupe(papers: list[dict]) -> list[dict]:
    """Merge by normalized title (keeps the first / most complete entry)."""
    seen: dict[str, dict] = {}
    for p in papers:
        k = re.sub(r"[^a-z0-9]+", "", (p.get("title") or "").lower())[:80]
        if not k:
            continue
        if k not in seen or (p.get("citations") or 0) > (seen[k].get("citations") or 0):
            prev = seen.get(k, {})
            merged = {**prev, **{kk: vv for kk, vv in p.items() if vv not in (None, "", [])}}
            seen[k] = merged
    return list(seen.values())


def bib_key(p: dict) -> str:
    fam = (p.get("authors") or ["anon"])[0].split()[-1].lower()
    fam = re.sub(r"[^a-z]", "", fam) or "anon"
    w = re.sub(r"[^a-z]", "", (p.get("title") or "x").lower().split()[0]) or "x"
    return f"{fam}{p.get('year') or ''}{w}"


def to_bibtex(papers: list[dict]) -> str:
    ents = []
    for p in papers:
        key = p.get("bibkey") or bib_key(p)
        auth = " and ".join(p.get("authors") or [])
        fields = [f"  title={{{p.get('title', '')}}}", f"  author={{{auth}}}"]
        if p.get("year"):
            fields.append(f"  year={{{p['year']}}}")
        if p.get("venue"):
            fields.append(f"  journal={{{p['venue']}}}")
        if p.get("doi"):
            fields.append(f"  doi={{{p['doi']}}}")
        if p.get("url"):
            fields.append(f"  url={{{p['url']}}}")
        ents.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n".join(ents) + "\n"


def save(study_dir: str | Path, data: dict, papers_for_bib: list[dict] | None = None) -> Path:
    """Write literature.json (+ references.bib from data['papers'] unless overridden)."""
    d = Path(study_dir) / "literature"
    d.mkdir(parents=True, exist_ok=True)
    data.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for p in data.get("papers", []):
        p.setdefault("bibkey", bib_key(p))
    (d / "literature.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    (d / "references.bib").write_text(to_bibtex(papers_for_bib or data.get("papers", [])))
    return d
