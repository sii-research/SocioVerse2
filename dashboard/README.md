# SocioVerse2 dashboard

A local, read-only web view over the `/sv-*` pipeline of every study under `studies/`: the
**v2 research cockpit** (`web/v2/`). It condenses a Claude Code session into the key steps:
each stage's status, the artifact it produced, the live metric curve, and the report / paper.

```
┌ rail ─────────────────┬─ study title · version picker · compare ────────────────────────┐
│ study switcher        │                                                                 │
│ Overview              │  active tab: research question + pipeline + key results /       │
│ Environment           │  environment layers + interventions / population roster /       │
│ Population            │  DuckDB tables / experiments & metric curves / report & paper   │
│ Dataset               │  (markdown with figures and KaTeX math) / literature            │
│ Experiments           │                                                                 │
│ Paper                 │                                                                 │
│ Literature            │                                                                 │
│ theme · EN/ZH · tour  │                                                                 │
└───────────────────────┴─────────────────────────────────────────────────────────────────┘
```

The UI is bilingual (English / Chinese, toggled in the rail; the default follows the browser
language). Math in reports and papers renders with a vendored KaTeX (`web/v2/vendor/katex`,
MIT). The only external request is the Google Fonts stylesheet; offline, the page falls back
to system fonts.

## Run

```bash
python dashboard/server/app.py --port 8787 --open      # --open launches the browser
# then visit http://127.0.0.1:8787   (also served at /v2/ and /app/v2/)
```

You rarely need to start it by hand: `/sv-init` brings it up (see *Lifecycle*).

**Dependencies.** The server and the UI are stdlib-only; any Python 3.11+ serves every page.
The DuckDB-backed views need `duckdb` in the interpreter that launches the server: the
Dataset tab's simulation tables, and the Experiments tab's per-agent drill-down when a run
left no `trajectory/panel_live.jsonl`. Without `duckdb` those tables stay empty (the API
reports `No module named 'duckdb'`) and everything else still works. `pip install -e .`
installs `duckdb`, so the simplest setup is to **launch Claude Code from the activated
environment** where you installed SocioVerse2. The skills call `python3 dashboard/hooks/sv_emit.py`,
and that helper starts the server with the same interpreter. Otherwise, point `SV_DASH_PYTHON`
at that environment's python.

The view auto-selects the most recently touched study; use the switcher at the top of the
left rail to inspect any `studies/<id>/`. It refreshes live over SSE whenever a skill writes
a new artifact. The switcher lists the reference studies and your own runs but **hides the
bare `abm_*` template shells** (`created_by="abm-umbrella"`, nothing built yet); set
`SV_DASH_SHOW_TEMPLATES=1` to show them too.

## Local vs hosted

The same cockpit files also power the hosted SocioVerse2 workbench, which adds a chat dock,
account quota, notices and a "new study" flow on its own backend. Served by this local
server, the page is marked `<body class="sv-local">` and `/api/state` reports
`"mode": "local"`. The cockpit then hides that hosted-only UI (the chat dock, the
**New study** / **All studies** links, the quota chip) and never calls the endpoints only the
hosted service provides (`/api/chat/*`, `/api/me`, `/api/notices`). Locally you drive the
workflow from Claude Code (`/sv-init`, `/sv-iterate`, …) and the dashboard follows along.

Local-only extras: the Dataset tab can open a study file with your system's default app or
reveal it in a folder (`POST /api/study/<id>/open-file`, `"local_open": true` in
`/api/state`). The hosted workbench sets `SV_DASH_HOSTED=1` in its containers, which turns the
local marker and these actions off; do not set it on your machine.

## Environment variables

These are read from the process environment, **not from `.env`**. `sv_emit.py` runs inside
the Claude Code session, so export them in the shell you launch Claude Code from, or put them
under `"env"` in `.claude/settings.local.json`. The server inherits them from `sv_emit.py`
(or from your shell when you start it by hand).

| env var | read by | default | effect |
|---|---|---|---|
| `SV_DASH_PORT` | `sv_emit.py` | `8787` | port the hooks start / talk to (for a manual start use `--port`) |
| `SV_DASH_OPEN` | `sv_emit.py` | `1` | `0` = don't open a browser tab (the URL is still printed) |
| `SV_DASH_DISABLE` | `sv_emit.py` | unset | set to anything = never start, open, announce or send events to the dashboard (stage narratives and the intent sheet are still written into the study) |
| `SV_DASH_PYTHON` | `sv_emit.py` | the interpreter running `sv_emit.py` | python that launches the server; point it at an env with `duckdb` |
| `SV_DASH_IDLE` | server | `0` (off) | seconds without a connected browser or any study-file change before the server shuts itself down |
| `SV_DASH_AWAIT_TTL` | server | `300` | seconds after which the "waiting for you" signal expires on its own |
| `SV_DASH_SHOW_TEMPLATES` | server | unset | set to anything = also list the bare `abm_*` template shells |

## Lifecycle, ports & concurrency

- **Launched by the workflow, not on session start.** `sv-init` runs
  `python3 dashboard/hooks/sv_emit.py session --query "…"` as its first action: it starts the
  server if needed, opens a browser tab (unless `SV_DASH_OPEN=0`), prints the URL and
  marks the session active. So the dashboard appears **only when a `/sv-*` study actually
  begins**; plain chat in the workspace never pops it. Every later stage calls
  `sv_emit.py narrative …`, which silently makes sure the server is up and records the
  stage's reasoning.
- **One shared server per checkout.** If the port already serves this checkout's dashboard,
  every session and every `/sv-*` run reuses it (the session-active dot and the waiting
  signal are shared; the most recent session wins). Two checkouts need two ports: `sv_emit.py` only ever
  stops a server whose command line runs **this checkout's** `dashboard/server/app.py`. When the
  port is held by anything else (another checkout's dashboard, a server you started by hand,
  an unrelated program), it leaves that process alone and prints a hint to set
  `SV_DASH_PORT`.
- **Hot upgrade on code change.** A long-lived server keeps its old Python logic in memory
  while it serves the new `index.html` from disk, so the UI could miss fields it expects.
  Two guards close that gap: the server reports its startup source mtime in `/api/state`
  (`dash_src_mtime`) and **restarts itself** (its poller exits) as soon as `server/app.py`
  changes on disk; and `sv_emit.ensure_up()` compares that mtime, stops a mismatching
  instance of this checkout and starts the current code. Responses carry
  `Cache-Control: no-store`, and SSE clients reconnect across the restart.
- **"Waiting for you" signal.** Claude Code lifecycle hooks in `.claude/settings.json` flag
  when the session waits on you: `Stop` → `sv_emit.py awaiting`, `UserPromptSubmit` →
  `sv_emit.py resumed`, plus `PreToolUse` / `PostToolUse` on **AskUserQuestion** (answering a
  question by clicking an option fires no `UserPromptSubmit`, so `PostToolUse` clears it).
  The browser tab title then flips to "⏳ waiting for you". The hooks only set a flag: they
  never launch the dashboard, never post your query, and do nothing when no dashboard is up.
  The flag also clears on any study-file change (files moving means Claude is working), on
  any stage narrative, after `SV_DASH_AWAIT_TTL` seconds, and the UI re-checks every 15 s.
- **No idle shutdown by default.** Once launched, the server holds its port for the whole
  session, so a backgrounded tab or a paused run never loses it. Set `SV_DASH_IDLE=<seconds>`
  to have an abandoned server (no browser connected, no study-file changes) shut itself down.

## How sync works

Two channels, by design:

1. **Files are the authoritative state.** The server watches `studies/<id>/` and rebuilds
   stage status, config and metrics from the artifacts the skills already write
   (`study.yaml`, `model.py`, `environment/environment.json`, `population/population.json`
   + `roster.jsonl`, `simulation/simulation.json`, `trajectory/`, `reports/`, `paper/`,
   `literature/`). This survives Claude Code restarts, subprocess writes and hand edits.
   - **Live run progress:** the engine appends `trajectory/progress.jsonl` every step and
     writes a lock-free per-agent snapshot to `trajectory/panel_live.jsonl` (DuckDB is
     write-locked mid-run), so the step bar, the metric chart and the per-agent inspector
     update during a run. `sv-run` counts as active until `metrics_history.json` lands.
   - **Path-A forks:** a fork copies the source's bundles, so a copied artifact older than
     the fork's `study.yaml` (detected via `created_by = "… fork of <source>"`) shows as
     *inherited from <source>*, not *done*, until you edit and re-run it.
   - **Stale detection:** re-running a mid-pipeline skill never deletes downstream artifacts;
     they stay on disk, now outdated. A done stage that predates a rebuilt artifact it
     depends on (`env / pop / model → run → report`) is flagged *stale*. `study.yaml` is
     excluded (metadata re-saves and forks should not cascade), and `population` does not
     depend on `environment`. The resume pointer lands on the first stale stage.
   - **Versions and branches (`/sv-iterate`):** `studies/<id>/versions.json` is the manifest.
     The live dir is always the *current* version; `versions/vN/` are frozen snapshots of
     earlier ones. The version box (top right) lists `id · note` per version, renders an
     archived version read-only from its snapshot, and jumps to a newly created version
     unless you are deliberately inspecting an older one. Each entry carries `kind`
     (`version` / `branch`) and, for a branch, its `fork_step`. Artifacts a version reuses
     from its parent show a neutral *from v<parent>* tag; on the live version, a reused stage
     at or after the re-entry point shows *review* until this iteration handles it.
   - **Event feed = a log:** rebuilt from disk on every request. Version snapshots keep
     artifact mtimes, so a stage appears once per version that (re)built it, and earlier
     lines never disappear when a later iteration reruns the same skill.
2. **Reasoning (L2) goes through `sv_emit.py`.** Each skill reports a short narrative per
   stage. `sv_emit.py narrative` writes it to `studies/<id>/narrative/<stage>.json` (durable
   and version-scoped: it rides version snapshots, so an archived version shows its own
   reasoning) and then `POST /ingest`s a nudge so open tabs refresh:

   ```bash
   python3 dashboard/hooks/sv_emit.py narrative --study opinion_diffusion --stage sv-init \
     --text "Routed to Path B; no existing study covers this question."
   ```

## Endpoints

| route | purpose |
|---|---|
| `GET /` (also `/v2/`, `/app/v2/`) | the cockpit (`web/v2/index.html`); `GET /app/v2` redirects to `/app/v2/`. Static files are served from the site root (`/app.js`, `/tabs/…`, `/vendor/katex/…`) and under `/v2/…` and `/app/v2/…` |
| `GET /api/state` | study list + progress + current selection; `mode` (`local` / `hosted`), `local_open`, `awaiting`, `dash_src_mtime` |
| `GET /api/stream` | SSE; pushes a `changed` nudge on any artifact write and an `ingest` nudge per narrative |
| `GET /api/study/<id>` | full reconstructed detail of one study (its *current* version) |
| `GET /api/study/<id>/agents` · `…/agent/<aid>` | per-agent latest state + dims · one agent's per-step state and decision |
| `GET /api/study/<id>/figure/<name>` | a report or paper figure (PNG) |
| `GET /api/study/<id>/files` · `…/file/<rel>` | the study's data-asset inventory · one whitelisted file |
| `GET /api/study/<id>/data/tables` · `…/data/table/<name>[.csv]` | DuckDB tables with columns and row counts · paged rows or a CSV download (needs `duckdb`) |
| `GET /api/study/<id>/paper` · `…/literature` | `paper/paper.md` with its outline · `literature/literature.json` + `references.bib` |
| `GET /api/study/<id>/version/<v>[/…]` | the same views for an archived version, rendered from its `versions/<v>/` snapshot |
| `POST /api/study/<id>/open-file` | local only: open a study file with the system default app, or reveal it |
| `POST /ingest` | lifecycle signals and stage nudges from `sv_emit.py` |

`scripts/export_dashboard_static.py` bakes these JSON views for selected studies into a
self-contained static gallery that any static host can serve.
