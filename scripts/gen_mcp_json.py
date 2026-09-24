#!/usr/bin/env python3
"""Generate the gitignored .mcp.json (in-session MCP registration) from .env.

The gitignored .env is the SINGLE place for service endpoints and keys — the same
variables the Python clients read (see .env.example). This script renders the
Claude Code / Codex MCP registration file from it, so collaborator setup is:

    cp .env.example .env          # fill in the endpoints/keys you were given
    python scripts/gen_mcp_json.py

Registered services (an entry is emitted only when its *_URL variable is set):

    event_tool            <- SV_EVENT_API_URL      (+ SV_EVENT_API_KEY as Authorization: Bearer)
    user_pool_survey_mcp  <- SV_USER_POOL_MCP_URL  (+ SV_USER_POOL_MCP_KEY as Authorization: Bearer)

The variables are read with the runtime's lookup (socioverse.external_events): the
process environment first, then $SV_HOME/.env, ./.env and the repo-root .env, the first
non-empty value winning (an empty value counts as unset). --env-file reads that one file
instead of the lookup; the process environment still wins.

.mcp.json itself stays gitignored (it holds your endpoints and keys — see .gitignore);
never commit it or paste its contents into tracked files. Re-run after editing .env;
pass --force to overwrite an existing, differing .mcp.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from socioverse.external_events import _parse_dotenv, dotenv_candidates  # noqa: E402

# capability name (resources/capabilities.yaml) -> (URL env var, key env var)
SERVICES: dict[str, tuple[str, str]] = {
    "event_tool": ("SV_EVENT_API_URL", "SV_EVENT_API_KEY"),
    "user_pool_survey_mcp": ("SV_USER_POOL_MCP_URL", "SV_USER_POOL_MCP_KEY"),
}


def env_files(env_file: Path | None = None) -> list[Path]:
    """The .env files read, highest priority first: just ``env_file`` when given, else the
    runtime's lookup ($SV_HOME/.env, ./.env, the repo-root .env)."""
    return [env_file] if env_file is not None else dotenv_candidates()


def load_env(path: Path | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
    """The settings as socioverse resolves them: the process env (``base``) wins, then each
    .env file in priority order fills the gaps (``path`` alone when given, else the runtime's
    lookup). An empty value counts as unset everywhere, so an unedited ``KEY=`` copied from
    .env.example never hides a value from a lower-priority file."""
    env = {k: v for k, v in (base if base is not None else os.environ).items() if v}
    for p in env_files(path):
        if p.is_file():
            for k, v in _parse_dotenv(p).items():
                if v:
                    env.setdefault(k, v)
    return env


def build_config(env: dict[str, str]) -> dict:
    """Render the mcpServers mapping for every service whose URL is configured."""
    servers: dict[str, dict] = {}
    for name, (url_var, key_var) in SERVICES.items():
        url = (env.get(url_var) or "").strip()
        if not url:
            continue
        entry: dict = {"type": "http", "url": url}
        key = (env.get(key_var) or "").strip()
        if key:
            entry["headers"] = {"Authorization": f"Bearer {key}"}
        servers[name] = entry
    return {"mcpServers": servers}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env-file", type=Path, default=None,
                    help="read this one .env file instead of the $SV_HOME/.env, ./.env, "
                         "repo-root .env lookup (the process environment still wins)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / ".mcp.json")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing .mcp.json that differs from the render")
    args = ap.parse_args(argv)

    config = build_config(load_env(args.env_file))
    files = env_files(args.env_file)
    found = [str(p) for p in files if p.is_file()]
    sources = (f"the environment or {', '.join(found)}" if found else
               f"the environment (no .env file at {', '.join(str(p) for p in files)})")
    if not config["mcpServers"]:
        print(f"no service URLs set in {sources} "
              f"({', '.join(url for url, _ in SERVICES.values())}) — nothing to register.\n"
              f"MCP services are optional: skills fall back per resources/capabilities.yaml.")
        return 0

    rendered = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    if args.out.exists():
        current = args.out.read_text(encoding="utf-8")
        if current == rendered:
            print(f"{args.out} already up to date ({len(config['mcpServers'])} servers).")
            return 0
        if not args.force:
            print(f"{args.out} exists and differs from the render — rerun with --force "
                  f"to overwrite (it is generated from .env; hand edits will be lost).",
                  file=sys.stderr)
            return 1
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out}: {', '.join(sorted(config['mcpServers']))} "
          f"(read from {sources}; keep .env and .mcp.json gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
