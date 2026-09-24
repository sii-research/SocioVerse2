"""ExternalEventsClient — build-time retrieval of external event/macro data for E.

The runtime loop NEVER fetches external data: skills call this at build time
(sv-build-environment) and materialize the evidence to
`studies/<id>/environment/external_events.json`; broadcasts/layers are then
authored from that file. Priority chain, dropping one tier per failure:

  1. "remote"      — the production Event MCP (streamable HTTP, stateless JSON
                     mode), configured via SV_EVENT_API_URL (the FULL MCP
                     endpoint, e.g. http://host:9997/event_mcp) + SV_EVENT_API_KEY
                     (bearer). Speaks plain JSON-RPC POSTs (`tools/call get_data`)
                     — no MCP SDK needed. The server has no query parser (the
                     agent layer was deliberately dropped), so this tier needs
                     explicit months= + sources=; `query` is provenance only.
                     Returns structured SourceResults only — web evidence is the
                     calling skill's WebSearch job (grounding), never the service's.
                     Ops health lives at `<scheme>://<host>/healthz` (root, off
                     the MCP path).
  2. "local_cache" — an optional local dir of cached per-source payloads
                     (SV_EVENT_LOCAL_CACHE → `<dir>/<source>/<YYYY-MM>.json`),
                     for offline/dev runs. Plain file reads; requires explicit
                     months + sources since no query parser lives here.
  3. "unavailable" — both tiers down: the bundle says so, and the calling skill
                     falls back to Claude WebSearch + hand-authored broadcasts.

Attribution rule (B = f(P, E)): author broadcasts from `bundle.results` (typed
per-source data) or `bundle.web_evidence` (title/link/date records), never from
`bundle.summary` — that field is another LLM's prose, kept for reference only;
injecting it into E would confound behavior attribution.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .schemas.resources import ResourceManifest
from .validation import write_artifact

# Directory above the package. In a git checkout this is the repo root (where `.env` lives);
# in a wheel install it is site-packages, which is never searched for a `.env`.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _is_checkout(root: Path) -> bool:
    """True when `root` looks like a source checkout of this repo (not site-packages)."""
    return (root / "pyproject.toml").is_file() and (root / "socioverse").is_dir()


def dotenv_candidates() -> list[Path]:
    """The `.env` files searched, highest priority first (existing or not):

      1. ``$SV_HOME/.env`` — an explicit workspace home;
      2. ``./.env`` — the current working directory;
      3. ``<repo root>/.env`` — only when running from a source checkout.

    Duplicates (e.g. running from the checkout root) are listed once.
    """
    out: list[Path] = []
    home = os.environ.get("SV_HOME")
    if home:
        out.append(Path(home).expanduser() / ".env")
    out.append(Path.cwd() / ".env")
    if _is_checkout(_REPO_ROOT):
        out.append(_REPO_ROOT / ".env")
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        key = p.resolve() if p.exists() else p.absolute()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _parse_dotenv(p: Path) -> dict[str, str]:
    """KEY=VALUE pairs of one `.env` file (comments skipped, quotes stripped; the first
    assignment of a key in the file wins)."""
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return out


def _read_dotenv(p: Path) -> None:
    # An empty value (e.g. an unedited `SV_LLM_API_KEY=` copied from .env.example) counts as
    # unset, as in env_setting(): it neither exports "" nor hides a lower-priority file's value.
    for k, v in _parse_dotenv(p).items():
        if v:
            os.environ.setdefault(k, v)


def env_setting(name: str) -> str | None:
    """One setting with the same precedence as ``_load_dotenv()``: the process environment,
    else the first file in ``dotenv_candidates()`` that sets it; None when unset or empty.

    Read-only: unlike ``_load_dotenv()`` it never copies the other keys of a `.env` into
    ``os.environ``. The companion-repo locations (SV_ABM_ROOT, SV_CHICAGO_LEGACY,
    SV_CONSUMERSIM_ROOT, SV_HISIM_ROOT) are resolved through it, so they work from `.env`
    as `.env.example` documents."""
    v = os.environ.get(name)
    if v:
        return v
    for p in dotenv_candidates():
        if p.is_file():
            v = _parse_dotenv(p).get(name)
            if v:
                return v
    return None


def _load_dotenv(root: Path | None = None) -> None:
    """Minimal, dependency-free .env loader. Only sets keys not already in the env.

    With ``root`` given, reads ``root/.env`` only. Otherwise reads every existing file in
    ``dotenv_candidates()`` in priority order; since a key is only set when absent, the
    first file that gives it a non-empty value wins (and the process environment beats all
    files).
    """
    paths = [root / ".env"] if root is not None else dotenv_candidates()
    for p in paths:
        if p.is_file():
            _read_dotenv(p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def month_range(start: str, end: str) -> list[str]:
    """Inclusive "YYYY-MM" range helper for fetch(months=...)."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
        if len(out) > 48:
            break
    return out


class ExternalEventsBundle(BaseModel):
    """Materialized external-event evidence for one study environment build."""

    query: str
    requested_months: list[str] = Field(default_factory=list)   # "YYYY-MM"
    requested_sources: list[str] = Field(default_factory=list)
    provider: Literal["remote", "local_cache", "unavailable"]
    endpoint: str | None = None
    fetched_at: str = Field(default_factory=_now_iso)
    # "<source>_<YYYY-MM>" -> SourceResult-shaped dict (status/target_date/data...)
    results: dict[str, Any] = Field(default_factory=dict)
    availability: dict[str, Any] = Field(default_factory=dict)
    web_evidence: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None    # remote LLM prose — reference only, never inject into E
    errors: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.provider != "unavailable"


class ExternalEventsClient:
    """Tiered fetcher: remote Event MCP > local cache dir > unavailable.

    Config resolution: explicit ctor args > environment (SV_EVENT_API_URL,
    SV_EVENT_API_KEY, SV_EVENT_LOCAL_CACHE) > `.env` (see `dotenv_candidates()`). The auth key
    never lives in study artifacts — a ResourceManifest declares the *url*, the
    key stays in the environment.

    `timeout` is PER SOURCE-MONTH call: the remote tier fetches source by source
    (get_source_detail) so one slow upstream (e.g. NYT from a CN-hosted server)
    can't stall the whole batch — it just becomes an error entry for its key.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        local_cache_dir: str | Path | None = None,
        timeout: float = 120.0,
        health_timeout: float = 10.0,
        transport: Callable[..., dict] | None = None,
    ):
        _load_dotenv()
        self.api_url = (api_url or os.environ.get("SV_EVENT_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("SV_EVENT_API_KEY", "")
        cache = local_cache_dir or os.environ.get("SV_EVENT_LOCAL_CACHE", "")
        self.local_cache_dir = Path(cache) if cache else None
        self.timeout = timeout
        self.health_timeout = health_timeout
        self._transport = transport or self._http_json

    @classmethod
    def from_manifest(
        cls, manifest: ResourceManifest, name: str = "event_tool", **kwargs: Any
    ) -> "ExternalEventsClient":
        """Take the endpoint url from a study's ResourceManifest.mcp_servers entry
        (transport="http"); the key still comes from the environment."""
        decl = next((s for s in manifest.mcp_servers if s.name == name), None)
        if decl is not None and decl.url:
            kwargs.setdefault("api_url", decl.url)
        return cls(**kwargs)

    # -- tiers ------------------------------------------------------------

    def fetch(
        self,
        query: str,
        months: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> ExternalEventsBundle:
        """Run the priority chain and return a normalized bundle (never raises)."""
        months = list(months or [])
        sources = list(sources or [])
        errors: list[dict[str, Any]] = []

        if self.api_url:
            try:
                bundle = self._fetch_remote(query, months, sources)
                bundle.errors = errors + bundle.errors
                return bundle
            except Exception as exc:
                errors.append({"tier": "remote", "endpoint": self.api_url,
                               "error": f"{type(exc).__name__}: {exc}"})
        else:
            errors.append({"tier": "remote", "error": "SV_EVENT_API_URL not configured"})

        if self.local_cache_dir:
            try:
                bundle = self._fetch_local_cache(query, months, sources)
                bundle.errors = errors + bundle.errors
                if bundle.results:
                    return bundle
                errors = bundle.errors
            except Exception as exc:
                errors.append({"tier": "local_cache", "dir": str(self.local_cache_dir),
                               "error": f"{type(exc).__name__}: {exc}"})
        else:
            errors.append({"tier": "local_cache", "error": "SV_EVENT_LOCAL_CACHE not configured"})

        return ExternalEventsBundle(
            query=query, requested_months=months, requested_sources=sources,
            provider="unavailable", errors=errors,
        )

    def _fetch_remote(
        self, query: str, months: list[str], sources: list[str]
    ) -> ExternalEventsBundle:
        # api_url is the full MCP endpoint (…/event_mcp); ops health sits at the
        # host root. Fail fast on a dead server before per-source fetching.
        parts = urllib.parse.urlsplit(self.api_url)
        health = self._transport(
            "GET", f"{parts.scheme}://{parts.netloc}/healthz", None, self.health_timeout
        )
        if health.get("status") != "ok":
            raise RuntimeError(f"event service unhealthy: {health}")
        if not months:
            raise ValueError(
                "remote Event MCP has no query parser — pass explicit months= "
                "(and ideally sources=)"
            )

        results: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        status: dict[str, str] = {}
        rpc_id = 0

        def call_tool(name: str, arguments: dict) -> dict:
            nonlocal rpc_id
            rpc_id += 1
            resp = self._transport(
                "POST", self.api_url,
                {"jsonrpc": "2.0", "id": rpc_id, "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}},
                self.timeout,
            )
            if resp.get("error"):
                raise RuntimeError(f"MCP error: {resp['error']}")
            result = resp.get("result") or {}
            content = result.get("content") or []
            text = content[0].get("text", "") if content else ""
            if result.get("isError"):
                raise RuntimeError(f"tool error: {text[:200]}")
            return json.loads(text)

        def auth_fatal(exc: Exception) -> None:
            if getattr(exc, "code", None) in (401, 403):
                raise RuntimeError(
                    f"event MCP rejected the key (HTTP {exc.code}) — check SV_EVENT_API_KEY"
                ) from exc

        def record(r: dict, ym: str) -> None:
            key = f"{r.get('source_name', 'unknown')}_{r.get('target_date') or ym}"
            if r.get("status") == "error":
                status[key] = "error"
                errors.append(r)
            else:
                results[key] = r
                status[key] = r.get("status", "ok")

        for ym in months:
            year, month = (int(x) for x in ym.split("-"))
            if sources:
                # one call per source so a hanging upstream only loses its own key
                for src in sources:
                    try:
                        record(call_tool("get_source_detail",
                                         {"source": src, "year": year, "month": month}), ym)
                    except Exception as exc:
                        auth_fatal(exc)
                        status[f"{src}_{ym}"] = "error"
                        errors.append({"source_name": src, "target_date": ym,
                                       "status": "error",
                                       "error_message": f"{type(exc).__name__}: {exc}"})
            else:
                try:
                    multi = call_tool("get_data",
                                      {"sources": "default", "year": year, "month": month})
                    for r in multi.get("results") or []:
                        record(r, ym)
                    for e in multi.get("errors") or []:
                        record(e, ym)
                except Exception as exc:
                    auth_fatal(exc)
                    errors.append({"target_date": ym, "status": "error",
                                   "error_message": f"{type(exc).__name__}: {exc}"})

        if not results:
            raise RuntimeError(
                f"remote Event MCP returned no data for {months}: {errors[:3]}"
            )

        used = sorted({k.rsplit("_", 1)[0] for k, v in status.items() if v == "ok"})
        unavailable = sorted(
            {k.rsplit("_", 1)[0] for k, v in status.items() if v != "ok"} - set(used)
        )
        return ExternalEventsBundle(
            query=query, requested_months=months, requested_sources=sources,
            provider="remote", endpoint=self.api_url,
            results=results,
            availability={"sources_used": used, "sources_unavailable": unavailable,
                          "source_status": status},
            errors=errors,
        )

    def _fetch_local_cache(
        self, query: str, months: list[str], sources: list[str]
    ) -> ExternalEventsBundle:
        errors: list[dict[str, Any]] = []
        results: dict[str, Any] = {}
        if not months or not sources:
            errors.append({"tier": "local_cache",
                           "error": "local cache needs explicit months= and sources="})
        status: dict[str, str] = {}
        for src in sources:
            for ym in months or []:
                key = f"{src}_{ym}"
                path = self.local_cache_dir / src / f"{ym}.json"  # type: ignore[operator]
                if not path.exists():
                    status[key] = "missing"
                    continue
                results[key] = {
                    "source_name": src, "target_date": ym, "status": "ok",
                    "from_cache": True, "data": json.loads(path.read_text(encoding="utf-8")),
                }
                status[key] = "ok"
        used = sorted({k.rsplit("_", 1)[0] for k, v in status.items() if v == "ok"})
        missing = sorted({k.rsplit("_", 1)[0] for k, v in status.items() if v != "ok"} - set(used))
        return ExternalEventsBundle(
            query=query, requested_months=months, requested_sources=sources,
            provider="local_cache", endpoint=str(self.local_cache_dir),
            results=results,
            availability={"sources_used": used, "sources_unavailable": missing,
                          "source_status": status},
            errors=errors,
        )

    # -- transport ---------------------------------------------------------

    def _http_json(
        self, method: str, url: str, payload: dict | None, timeout: float
    ) -> dict:
        # the MCP endpoint requires both types in Accept; harmless elsewhere
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


def materialize_external_events(
    study_dir: str | Path,
    query: str,
    months: list[str] | None = None,
    sources: list[str] | None = None,
    client: ExternalEventsClient | None = None,
    filename: str = "external_events.json",
) -> tuple[Path, ExternalEventsBundle]:
    """Fetch through the priority chain and persist the evidence bundle into the
    study's environment/ dir. Returns (path, bundle) so the caller can author
    broadcasts immediately; check `bundle.available` to know whether to fall back
    to Claude WebSearch."""
    client = client or ExternalEventsClient()
    bundle = client.fetch(query, months=months, sources=sources)
    path = Path(study_dir) / "environment" / filename
    write_artifact(path, bundle)
    return path, bundle
