#!/usr/bin/env python3
"""Dashboard launch/emit helper — invoked from INSIDE the /sv-* skills.

Stdlib only, always exits 0, fail-silent when the dashboard is offline. It is driven
by the skills themselves (NOT by Claude Code lifecycle hooks), so the dashboard is
brought up only when a sv-* study actually begins — never on plain session start or
unrelated conversation.

Subcommands
-----------
  session --query "..."   bring up + open the dashboard and register the run's query.
                          Called once at the very start of sv-init (the workflow entry).
  narrative --study ID --stage NAME [--text "..."]
                          POST an L2 reasoning summary for a stage; also brings the
                          dashboard up if a flow was entered mid-stream. Every /sv-* stage.
  checklist [--json '...'] [--study ID]
                          publish the sv-init intent checklist (Step −1). Payload is a JSON
                          object {phase, query, items:[{id,status,value,...}]}; omit --json
                          to read it from stdin (heredoc-friendly). Re-send the WHOLE payload
                          on every status change — the dashboard renders the latest copy.
                          With --study (once the workspace exists) it is also archived to
                          studies/<id>/intent.json so the study keeps its confirmation sheet.
  awaiting | resumed      lifecycle hooks (.claude/settings.json): toggle the "waiting for
                          you" banner. Never launch the dashboard, never post query text.

Environment: SV_DASH_PORT (default 8787), SV_DASH_OPEN=0 (print the URL but don't open a
browser tab), SV_DASH_DISABLE=1 (never start, open, announce or contact the dashboard; stage
narratives and the intent sheet are still written into the study), SV_DASH_PYTHON (interpreter
that runs the server; default: the one running this helper). See dashboard/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve()
DASH = HERE.parents[1]             # dashboard/
REPO_ROOT = HERE.parents[2]        # the repo root (this checkout)
APP = DASH / "server" / "app.py"
PORT = int(os.environ.get("SV_DASH_PORT", "8787"))
BASE = f"http://127.0.0.1:{PORT}"
# The interpreter that launches the server: SV_DASH_PYTHON, else the one running this helper
# (the `python3` on PATH when the skills/hooks call it). The UI is stdlib-only, but the
# Dataset/Experiments tables read DuckDB, so launch Claude Code from the env where SocioVerse2
# is installed, or point SV_DASH_PYTHON at that env's python.
DASH_PYTHON = os.environ.get("SV_DASH_PYTHON") or sys.executable


def server_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def post(path: str, obj: dict) -> None:
    if os.environ.get("SV_DASH_DISABLE"):
        return  # disabled: no network traffic at all, not even to a server someone else runs
    try:
        req = urllib.request.Request(
            BASE + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=0.8).read()
    except Exception:
        pass  # fail silent — dashboard may not be running


def write_narrative_file(study: str, stage: str, text: str) -> None:
    """Persist a stage's L2 reasoning to ``studies/<study>/narrative/<stage>.json`` (the LIVE
    dir = the current version). Durable + version-scoped: it rides ``create_version`` snapshots
    and branch restores like every other artifact, so the dashboard renders each version's own
    reasoning (archived versions included) and a carried stage never shows a sibling version's
    text. Fail-silent; the live POST above still drives the banner/feed refresh."""
    try:
        d = REPO_ROOT / "studies" / study / "narrative"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"stage": stage, "narrative": (text or "").strip()[:1200], "ts": time.time()}
        tmp = d / (stage + ".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / (stage + ".json"))   # atomic — the poller must never read a torn file
    except Exception:
        pass


def write_intent_file(study: str, payload: dict) -> None:
    """Archive the confirmed intent checklist to ``studies/<study>/intent.json`` (atomic,
    fail-silent — same discipline as narratives). It rides version snapshots/forks like any
    other study file, so the overview tab can always show what was agreed before building."""
    try:
        d = REPO_ROOT / "studies" / study
        if not d.is_dir():
            return
        tmp = d / "intent.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(d / "intent.json")
    except Exception:
        pass


def server_src_current() -> bool:
    """True when the listening server was built from the CURRENT app.py source.

    The server is a long-lived shared process; after app.py changes, a running instance
    keeps serving stale logic while it hands out the fresh index.html — the UI then lacks
    the fields it expects (this is how a created v2 once rendered as an overwritten v1).
    New servers report their startup source mtime in /api/state; an old/wedged server
    (missing field, bad read) counts as stale.
    """
    try:
        with urllib.request.urlopen(BASE + "/api/state", timeout=1.5) as r:
            return json.load(r).get("dash_src_mtime") == APP.stat().st_mtime
    except Exception:
        return False


def runs_this_checkouts_app(cmdline: str) -> bool:
    """True when a process command line runs THIS checkout's server (the absolute ``APP`` path
    ``ensure_up`` launches, as a whole argument). Another checkout's dashboard, or any other
    program that happens to listen on the port, never matches."""
    return re.search(r"(?:^|\s)" + re.escape(str(APP)) + r"(?:\s|$)", cmdline or "") is not None


def kill_stale_server() -> None:
    """SIGTERM only processes on our port that run this checkout's app.py — never anything else."""
    try:
        pids = subprocess.run(["lsof", "-ti", f"tcp:{PORT}"],
                              capture_output=True, text=True, timeout=3).stdout.split()
        for pid in pids:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", pid],
                                 capture_output=True, text=True, timeout=3).stdout
            if runs_this_checkouts_app(cmd.strip()):
                os.kill(int(pid), signal.SIGTERM)
        for _ in range(20):                # give the port up to ~2s to free
            if not server_up():
                return
            time.sleep(0.1)
    except Exception:
        pass


def ensure_up() -> bool:
    """Start the dashboard server if it isn't already listening — and hot-upgrade it when
    the running instance predates the current app.py. Silent unless the port is held by a
    server this checkout did not start. Returns True if up."""
    if os.environ.get("SV_DASH_DISABLE"):
        return False
    if server_up():
        if server_src_current():
            return True
        kill_stale_server()                # stale code → recycle (SSE clients auto-reconnect)
        if server_up():                    # not ours / refused to die — keep the working one
            print(f"[sv-dashboard] Port {PORT} is held by a server this checkout did not start "
                  f"(another checkout's dashboard, or one launched by hand); leaving it running. "
                  f"Set SV_DASH_PORT to a free port to get this checkout's dashboard.")
            return True
    py = DASH_PYTHON if Path(DASH_PYTHON).exists() else sys.executable
    log = open(DASH / ".server.log", "a")
    subprocess.Popen([py, str(APP), "--port", str(PORT)],
                     stdout=log, stderr=log, start_new_session=True, cwd=str(REPO_ROOT))
    for _ in range(15):            # give it ~1.5s to bind
        if server_up():
            return True
        time.sleep(0.1)
    return server_up()


def announce_and_open() -> None:
    """Pop the browser (unless SV_DASH_OPEN=0) and print the URL so Claude reports it.

    Run from inside a skill's Bash step → stdout is tool output Claude relays to the user.
    """
    url = f"http://127.0.0.1:{PORT}"
    if os.environ.get("SV_DASH_OPEN", "1") != "0":
        try:
            webbrowser.open(url, new=0)
        except Exception:
            pass
    print(f"[sv-dashboard] The SocioVerse2 run dashboard is live at {url}. "
          f"Tell the user they can open it to watch the /sv-* run.")


def in_repo_workspace() -> bool:
    """Only this repo's workspace drives the waiting banner. The Stop/UserPromptSubmit hooks
    live in this repo's .claude/settings.json (so already per-project), but double-check the
    active project dir so a stray/global hook config can't flip the banner from another workspace."""
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if not proj:
        return True                       # manual run / no project env — don't block
    try:
        return Path(proj).resolve() == REPO_ROOT
    except Exception:
        return True


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("session")          # sv-init only: launch + open + register the query
    s.add_argument("--query", default=None)
    n = sub.add_parser("narrative")        # every sv-* stage: post the reasoning summary
    n.add_argument("--study", required=True)
    n.add_argument("--stage", required=True)
    n.add_argument("--text", default=None)
    c = sub.add_parser("checklist")        # sv-init Step −1: intent checklist state (full resend)
    c.add_argument("--json", dest="payload", default=None)
    c.add_argument("--study", default=None)
    sub.add_parser("awaiting")             # Stop hook: CC is waiting for the user (never launches)
    sub.add_parser("resumed")              # UserPromptSubmit hook: user replied (never launches, no query)
    args = ap.parse_args()

    if args.cmd == "session":
        if ensure_up():
            announce_and_open()
            q = (args.query or "").strip()
            if q:
                post("/ingest", {"type": "user_query", "prompt": q[:2000]})
    elif args.cmd == "narrative":
        ensure_up()                        # bring the dashboard up if a flow was entered mid-stream
        text = args.text if args.text is not None else sys.stdin.read()
        write_narrative_file(args.study, args.stage, text or "")   # durable, version-scoped
        post("/ingest", {"type": "stage_summary", "study_id": args.study,
                         "stage": args.stage, "narrative": (text or "").strip()[:1200]})
    elif args.cmd == "checklist":
        ensure_up()
        raw = args.payload if args.payload is not None else sys.stdin.read()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("items"):
            payload["ts"] = time.time()
            if args.study:
                payload["study_id"] = args.study
                write_intent_file(args.study, payload)
            post("/ingest", {"type": "intent_checklist", "checklist": payload})
    elif args.cmd == "awaiting":
        if in_repo_workspace():
            post("/ingest", {"type": "awaiting_input"})   # only this workspace drives the banner; no-op if dashboard down
    elif args.cmd == "resumed":
        if in_repo_workspace():
            post("/ingest", {"type": "resumed"})          # clears the waiting banner; posts no query text


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass          # argparse errors must not propagate
    except Exception:
        pass
    sys.exit(0)
