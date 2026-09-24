"""dashboard/hooks/sv_emit.py: interpreter default and the checkout-scoped server recycle.

Nothing here starts a server or binds a port: process lookups, signals and Popen are faked.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HOOK = Path(__file__).resolve().parents[1] / "dashboard" / "hooks" / "sv_emit.py"


def load_hook(monkeypatch, **env):
    for k in ("SV_DASH_PYTHON", "SV_DASH_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("sv_emit_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # belt and braces: a test must never launch a real dashboard
    monkeypatch.setattr(mod.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("test tried to launch a dashboard server"))
    return mod


def test_server_interpreter_defaults_to_the_running_python(monkeypatch):
    assert load_hook(monkeypatch).DASH_PYTHON == sys.executable
    assert load_hook(monkeypatch, SV_DASH_PYTHON="/opt/env/bin/python").DASH_PYTHON == "/opt/env/bin/python"


def test_only_this_checkouts_server_matches(monkeypatch):
    m = load_hook(monkeypatch)
    app = str(m.APP)
    assert app.endswith("dashboard/server/app.py") and Path(app).is_absolute()
    assert m.runs_this_checkouts_app(f"/usr/bin/python3 {app} --port 8787")
    assert m.runs_this_checkouts_app(app)
    # another checkout, a relative launch, or a lookalike path never matches
    assert not m.runs_this_checkouts_app("/usr/bin/python3 /elsewhere/SocioVerse2/dashboard/server/app.py --port 8787")
    assert not m.runs_this_checkouts_app("python dashboard/server/app.py --port 8787")
    assert not m.runs_this_checkouts_app(f"python /copy{app} --port 8787")
    assert not m.runs_this_checkouts_app(f"python {app}.bak")
    assert not m.runs_this_checkouts_app("")


def test_kill_stale_server_spares_other_checkouts(monkeypatch):
    m = load_hook(monkeypatch)
    cmdlines = {"111": f"/usr/bin/python3 {m.APP} --port 8787",
                "222": "/usr/bin/python3 /srv/other/dashboard/server/app.py --port 8787",
                "333": "nginx: worker process"}

    def fake_run(cmd, **kw):
        if cmd[0] == "lsof":
            return SimpleNamespace(stdout="111\n222\n333\n")
        return SimpleNamespace(stdout=cmdlines[cmd[-1]] + "\n")

    killed = []
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(m, "server_up", lambda: False)
    m.kill_stale_server()
    assert killed == [111]


def test_foreign_server_on_the_port_is_kept_with_a_hint(monkeypatch, capsys):
    m = load_hook(monkeypatch)
    monkeypatch.delenv("SV_DASH_DISABLE", raising=False)
    monkeypatch.setattr(m, "server_up", lambda: True)             # port busy …
    monkeypatch.setattr(m, "server_src_current", lambda: False)   # … not by this checkout's code
    monkeypatch.setattr(m, "kill_stale_server", lambda: None)     # … and it is not ours to stop
    assert m.ensure_up() is True
    assert "SV_DASH_PORT" in capsys.readouterr().out


def test_disabled_hook_does_nothing(monkeypatch):
    m = load_hook(monkeypatch, SV_DASH_DISABLE="1")
    monkeypatch.setattr(m, "server_up", lambda: pytest.fail("probed the port while disabled"))
    assert m.ensure_up() is False


@pytest.mark.parametrize("argv", [
    ["awaiting"],
    ["resumed"],
    ["session", "--query", "a private research question"],
    ["narrative", "--study", "zz_probe", "--stage", "sv-run", "--text", "stage reasoning"],
    ["checklist", "--study", "zz_probe", "--json",
     '{"phase": "confirm", "query": "a private research question", "items": [{"id": "q"}]}'],
])
def test_disabled_hook_never_contacts_a_server(monkeypatch, tmp_path, argv):
    m = load_hook(monkeypatch, SV_DASH_DISABLE="1", SV_DASH_PORT="18791")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)                  # study files land in tmp
    (tmp_path / "studies" / "zz_probe").mkdir(parents=True)
    monkeypatch.setattr(m.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail(f"contacted the dashboard while disabled: {argv[0]}"))
    monkeypatch.setattr(m.socket, "create_connection",
                        lambda *a, **k: pytest.fail("probed the port while disabled"))
    monkeypatch.setattr(m.webbrowser, "open", lambda *a, **k: pytest.fail("opened a browser while disabled"))
    monkeypatch.setattr(sys, "argv", ["sv_emit.py", *argv])
    m.main()
    # the durable, study-scoped records are still written (dashboard/README.md documents this)
    if argv[0] == "narrative":
        assert (tmp_path / "studies" / "zz_probe" / "narrative" / "sv-run.json").is_file()
    if argv[0] == "checklist":
        assert (tmp_path / "studies" / "zz_probe" / "intent.json").is_file()
