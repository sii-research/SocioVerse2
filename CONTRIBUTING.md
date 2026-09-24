# Contributing to SocioVerse2

Thank you for your interest. Bug reports, questions, new studies and pull requests are
welcome. No contributor license agreement is required: contributions are accepted under
the repository's [Apache License 2.0](LICENSE).

## How this repository is maintained

This public repository is the release mirror of the maintainers' development tree.
Pull requests are reviewed here as usual. When one is accepted, the maintainers port the
change to the development tree with you as its author, and it ships in the next release.
Contributors are credited in the release notes.

## Set up and run the tests

```bash
git clone https://github.com/sii-research/SocioVerse2.git
cd SocioVerse2
python3.11 -m venv .venv && source .venv/bin/activate   # or a conda env with Python 3.11+
pip install -e ".[dev,viz]"
pytest -q
```

The suite needs no API key and no network. Tests for studies that wrap a companion
repository (SocioVerse-ABM, ConsumerSim, HiSim) skip when it is absent; see the
"Companion repositories" section of the [README](README.md) to run them too. Tests that
need an optional extra (`chicago`, `workbench`) skip when it is not installed. Tests that
call a real LLM are marked `llm` and run only with `SV_RUN_LLM_TESTS=1` and a key in
`.env`. Set `SV_DASH_DISABLE=1` while testing if you do not want the dashboard to start.
If you scan the tree with [gitleaks](https://github.com/gitleaks/gitleaks), it picks up
`.gitleaks.toml`, which only exempts citation keys and documented placeholder keys.

## Guidelines

- **Scope.** Keep a pull request to one change, and add or update tests for it.
- **Style.** Python 3.11+, type hints on public functions, and the formatting of the
  surrounding code. Docstrings and comments are in English.
- **Skills.** `.claude/skills/` is the source of truth. After editing a skill, `CLAUDE.md`
  or `CLAUDE-dev.md`, regenerate the Codex mirrors with
  `python scripts/sync_agent_surfaces.py` and commit both sides (the test suite checks
  that they are in sync).
- **Studies.** A shipped study follows the standard layout (`study.yaml`, `environment/`,
  `population/`, `simulation/`, `grounding/`, `reports/`) and is whitelisted in
  `.gitignore`. Never commit run outputs (`trajectory/`, `runs/`, `versions/`, `*.duckdb`,
  `*.parquet`), keys, or data you may not redistribute; record data sources in the study's
  grounding ledger and, for bundled data files, in [`NOTICE`](NOTICE).
- **Vendored code.** `.claude/skills/paper-search-pro/`, `.claude/skills/research-paper-writing/`
  and `dashboard/web/v2/vendor/` track upstream projects. Send fixes for them upstream.

## Reporting issues

Open a GitHub issue with the command you ran, what you expected and what happened
(include the Python version and the output of `pip show socioverse2`). Report security
problems privately as described in [SECURITY.md](SECURITY.md).
