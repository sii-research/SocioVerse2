#!/usr/bin/env python3
"""Sync the Codex agent surface from the Claude Code surface (single source of truth).

`.claude/` + `CLAUDE*.md` are the AUTHORED surface. The Codex mirror is GENERATED —
never hand-edit it; edit the Claude side and run:

    python scripts/sync_agent_surfaces.py            # write the mirror
    python scripts/sync_agent_surfaces.py --check    # report drift, write nothing (CI/pytest)

What is synced (verbatim copies):

    CLAUDE.md                       -> AGENTS.md
    CLAUDE-dev.md                   -> AGENTS-dev.md
    .claude/skills/<s>/SKILL.md     -> .codex/skills/<s>/SKILL.md   (stale skills pruned)
    studies/<id>/CLAUDE.md          -> studies/<id>/AGENTS.md        (pointer stub; only
                                       created when missing — existing hand-written
                                       pointers are left alone)

NOT synced (format-specific, maintained by hand): `.claude/settings.json` vs
`.codex/hooks.json` (hook wiring), and `.claude/worktrees/` (session checkouts, ignored).
A future Copilot target (.github/copilot-instructions.md / prompt files) can be added as a
third mirror here.

`tests/test_agent_surface_sync.py` runs --check, so an out-of-sync mirror fails the suite.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

STUDY_POINTER = """# {study_id} — agent rules

The case-local operating rules for this study live in [`CLAUDE.md`](CLAUDE.md) in this
directory — read it before any work on this study or its Path-A forks. Single source of
truth; do not duplicate its content here.
"""


def _pairs(root: Path) -> list[tuple[Path, Path]]:
    """(source, mirror) pairs whose mirror must equal the source byte-for-byte."""
    pairs = [
        (root / "CLAUDE.md", root / "AGENTS.md"),
        (root / "CLAUDE-dev.md", root / "AGENTS-dev.md"),
    ]
    for skill_md in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        pairs.append((skill_md, root / ".codex" / "skills" / skill_md.parent.name / "SKILL.md"))
    return [(s, m) for s, m in pairs if s.exists()]


def _stale_codex_skills(root: Path) -> list[Path]:
    """Codex skill dirs with no .claude counterpart (deleted/renamed skills)."""
    claude_names = {p.parent.name for p in (root / ".claude" / "skills").glob("*/SKILL.md")}
    codex_root = root / ".codex" / "skills"
    if not codex_root.is_dir():
        return []
    return [d for d in sorted(codex_root.iterdir()) if d.is_dir() and d.name not in claude_names]


def _missing_study_pointers(root: Path) -> list[Path]:
    """studies/<id>/AGENTS.md stubs that should exist because the study has a CLAUDE.md."""
    missing = []
    for claude_md in sorted((root / "studies").glob("*/CLAUDE.md")):
        if not (claude_md.parent / "AGENTS.md").exists():
            missing.append(claude_md.parent / "AGENTS.md")
    return missing


def check(root: Path = REPO_ROOT) -> list[str]:
    """Return a list of human-readable drift findings (empty = in sync)."""
    drift: list[str] = []
    for src, dst in _pairs(root):
        if not dst.exists():
            drift.append(f"missing mirror: {dst.relative_to(root)} (from {src.relative_to(root)})")
        elif dst.read_bytes() != src.read_bytes():
            drift.append(f"stale mirror:   {dst.relative_to(root)} != {src.relative_to(root)}")
    for d in _stale_codex_skills(root):
        drift.append(f"stale skill:    {d.relative_to(root)} has no .claude/skills counterpart")
    for p in _missing_study_pointers(root):
        drift.append(f"missing stub:   {p.relative_to(root)} (study has a CLAUDE.md)")
    return drift


def sync(root: Path = REPO_ROOT) -> list[str]:
    """Write the mirror; return a list of actions taken."""
    actions: list[str] = []
    for src, dst in _pairs(root):
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            actions.append(f"wrote {dst.relative_to(root)}")
    for d in _stale_codex_skills(root):
        for f in sorted(d.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
        d.rmdir()
        actions.append(f"pruned {d.relative_to(root)}")
    for p in _missing_study_pointers(root):
        p.write_text(STUDY_POINTER.format(study_id=p.parent.name), encoding="utf-8")
        actions.append(f"wrote {p.relative_to(root)} (pointer stub)")
    return actions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 if any; write nothing")
    args = ap.parse_args(argv)

    if args.check:
        drift = check()
        if drift:
            print("Codex surface is out of sync (edit the .claude side, then run "
                  "scripts/sync_agent_surfaces.py):", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1
        print("Codex surface in sync with the Claude surface.")
        return 0

    actions = sync()
    if actions:
        for a in actions:
            print(a)
    else:
        print("already in sync — nothing to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
