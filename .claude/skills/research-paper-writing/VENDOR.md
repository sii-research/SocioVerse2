# Vendored skill — provenance

| | |
|---|---|
| upstream | https://github.com/Master-cai/Research-Paper-Writing-Skills |
| path in upstream | `research-paper-writing/` |
| commit | `77e7c2c1ba06f7d71844873147665437a03aac1b` (2026-06-23) |
| license | MIT — see `LICENSE` (kept verbatim) |
| vendored on | 2026-08-17 |

Curated and adapted upstream from Prof. Peng Sida's (彭思达) open paper-writing notes.
It was picked over the other candidates because it is **pure guidance** — no scripts, no
dependencies, no API keys — so it drops into `.claude/skills/` and works offline, and
because its section guides are the most concrete of the lot (408 lines on the introduction
alone). Also evaluated: `K-Dense-AI/claude-scientific-writer` (2.2k★, but a whole plugin
with a Python package + its own API surface), `lishix520/academic-paper-skills` (1.2k★,
philosophy/preprint-platform planning — overlaps `/sv-init` and `/sv-lit` rather than the
writing stage) and `SNL-UCSB/paper-writing-skill` (164★, systems/networking venues).

## Local modifications

**One line, on purpose** — everything else is byte-identical to upstream so a re-sync is a
plain `cp`:

- `SKILL.md` frontmatter `description`: widened from "ML/CV/NLP-style papers" to also name
  computational social science, and pointed at `/sv-paper`. Without this the skill does not
  reliably surface for a SocioVerse2 study, whose papers are social-science shaped even though
  the section skeleton is identical.

Everything SocioVerse-specific (what to read, where to write, the no-invented-numbers rule,
figure existence gating) lives in `.claude/skills/sv-paper/SKILL.md`, NOT here. Keep it that
way — this directory should stay a drop-in replacement for upstream.

## Re-syncing

```bash
git clone --depth 1 https://github.com/Master-cai/Research-Paper-Writing-Skills /tmp/rpw
cp -r /tmp/rpw/research-paper-writing/{SKILL.md,references} .claude/skills/research-paper-writing/
# then re-apply the description edit above and update the commit hash in this file
```
