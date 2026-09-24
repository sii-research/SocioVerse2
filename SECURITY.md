# Security policy

## Reporting a vulnerability

Please report security issues privately by email to
**contact@socioverse.fudan-disc.com**, not in a public issue. Include the affected
version or commit, the steps to reproduce, and the impact you observed. We will
acknowledge the report, keep you informed while we work on a fix, and credit you in
the release notes unless you prefer otherwise.

Security fixes are made on the latest release. Older releases are not patched.

## What runs on your machine

Opening this repository in a coding agent runs code from it, so review these points
before you start a session:

- **Session hooks.** `.claude/settings.json` (Claude Code) and `.codex/hooks.json`
  (Codex) register hooks that run `python3 dashboard/hooks/sv_emit.py awaiting` or
  `resumed` on session events (the agent stops, you submit a prompt, and, in Claude
  Code, before and after a question to you). These calls only toggle the
  dashboard's "waiting for you" banner and never start a process.
- **The local dashboard.** When a `/sv-*` workflow starts, the skills run
  `dashboard/hooks/sv_emit.py`, which starts `dashboard/server/app.py` on
  `127.0.0.1:8787` (set `SV_DASH_PORT` to change it) and opens a browser tab (set
  `SV_DASH_OPEN=0` to only print the URL). The server has no authentication: it binds
  to `127.0.0.1` by default, serves the dashboard and the files of your studies, accepts
  progress events from the skills, and can open a file inside `studies/` with your
  system's default application when you click "open" in the UI. Do not expose it on a
  shared network (for example with `--host 0.0.0.0`).
- **Turning it off.** Set `SV_DASH_DISABLE=1` in the environment the coding agent is
  launched from (or under `"env"` in `.claude/settings.local.json`) and the hook script
  never starts, opens or contacts a dashboard server; it only keeps writing stage notes
  into the study folder. You can also remove the hooks from the two files above.

## Keys and credentials

- Keys live only in a `.env` file. The runtime, `scripts/demo_offline.py` and
  `scripts/gen_mcp_json.py` read the first of these that sets a key: `$SV_HOME/.env`,
  `./.env` in the current directory, then the repository-root `.env` (the process
  environment beats all three, and an empty value counts as unset). The repository's
  `.env` is gitignored; if you keep one elsewhere, keep it out of version control too.
  `.env.example` lists the variables. The generated `.mcp.json` that registers optional
  data services is gitignored too.
- Never commit `.env`, `.mcp.json` or any key, and never paste a key into a study
  artifact: study files are meant to be shared.
- An LLM key is sent only to `SV_LLM_BASE_URL` (the official OpenAI API when unset).
  Check that variable before you run a study against a third-party endpoint.
  `consumer_confidence` follows it only when its config reads the key from
  `SV_LLM_API_KEY`; a key it reads from any other variable goes only to the
  `prediction.endpoint` configured next to it.
- If you believe a key was exposed through this repository, revoke it with its
  provider first, then tell us at the address above.
