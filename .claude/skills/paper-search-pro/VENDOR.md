# Vendored skill — provenance

| | |
|---|---|
| upstream | https://github.com/O0000-code/paper-search-pro |
| commit | `d60dc10110e9efda934d3bb50796a01eab6f2fed` (2026-07-12), skill version 2.3.0 |
| license | Apache-2.0 — `LICENSE.txt` / `NOTICE.md` / `THIRD_PARTY.md` kept verbatim |
| vendored on | 2026-08-17 |

Multi-source literature discovery: OpenAlex · Semantic Scholar · CrossRef · PubMed ·
arXiv, plus native-Chinese retrieval (NSSD 国家哲社文献中心, yiigle 中华医学期刊).
It is the retrieval engine behind `/sv-lit` — that skill owns what the papers *mean*
for a given study; this one owns *finding* them.

Picked over the alternatives for one reason above all: **it has a documented
agent/headless channel**, `references/agent_mode.md`, so it can be driven from
inside another skill instead of only producing an HTML report for a human. Also
evaluated: `imbad0202/academic-research-skills` (42.8k★ — but **CC BY-NC 4.0**, a
non-commercial licence we cannot redistribute under this repo's Apache-2.0), ARIS
`wanshuiyin/Auto-claude-code-research-in-sleep` (14.8k★, MIT, excellent
`openalex`/`semantic-scholar`/`citation-audit` skills — but each cross-references a
dozen sibling skills we would not vendor, so the parts do not travel alone), and
`lingzhi227/agent-research-skills` (281★, **no licence file** = all rights reserved).

## Local modifications

One line in two files: the User-Agent URL in `scripts/crossref_helper.py` and
`scripts/journal_rank.py` points at the real upstream,
`https://github.com/O0000-code/paper-search-pro`. Upstream's User-Agent names a
`github.com/<org>/paper-search-pro` repository that does not exist.
Otherwise the tree is byte-identical to upstream except that `docs/` (9.9 MB of
generated HTML) and `assets/` images (14 MB) were not copied — nothing references
them from the agent path. Everything SocioVerse-specific lives in
`.claude/skills/sv-lit/SKILL.md`. Keep it that way so a re-sync stays a plain `cp`
followed by re-applying the User-Agent line.

## Runtime dependencies (this is the part that bites)

Unlike the other vendored skill, this one is **not** markdown-only — it needs:

    pyalex  semanticscholar  arxiv  biopython  requests  PyYAML  Jinja2

They are declared as this repo's `lit` extra (versions follow `scripts/requirements.txt`),
so install them into the environment the agent runs with:

```bash
pip install -e ".[lit]"
```

No API key is required — OpenAlex and CrossRef are open, and the Semantic Scholar
anonymous pool is used opportunistically. `~/.paper-search-pro/config.yaml` is
created on first run; we set nothing in it.

`/sv-lit` degrades gracefully: if `agent_search` is unavailable for any reason it
falls back to the zero-dependency stdlib path in `skills/sv_lit.py`, so a broken
install costs retrieval breadth, not the stage.

## Re-syncing

```bash
git clone --depth 1 https://github.com/O0000-code/paper-search-pro /tmp/psp
D=.claude/skills/paper-search-pro
cp /tmp/psp/{SKILL.md,LICENSE.txt,NOTICE.md,THIRD_PARTY.md} $D/
rm -rf $D/scripts $D/references && cp -r /tmp/psp/{scripts,references} $D/
cp /tmp/psp/assets/default_config.yaml $D/assets/
sed -i -E 's#github\.com/[a-z]+/paper-search-pro#github.com/O0000-code/paper-search-pro#' \
    $D/scripts/crossref_helper.py $D/scripts/journal_rank.py      # the local modification above
# then update the commit hash above, and re-check requirements.txt against the list here
```
