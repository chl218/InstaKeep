"""instakeep.py's run(): a short message for Ctrl+C, full tracebacks for bugs."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "instakeep.py"


@pytest.fixture
def program():
    # Loaded by path: a plain `import instakeep` gives the package in src/, not this script.
    spec = importlib.util.spec_from_file_location("instakeep_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unexpected_error_keeps_its_traceback(program, monkeypatch):
    def broken(argv):
        raise PermissionError("data folder is read-only")

    monkeypatch.setattr(program, "main", broken)
    with pytest.raises(PermissionError):  # Python prints the traceback
        program.run(["--list"])


def test_run_mode_also_logs_the_traceback(program, monkeypatch):
    logged = []

    def broken(argv):
        raise PermissionError("data folder is read-only")

    monkeypatch.setattr(program, "main", broken)
    monkeypatch.setattr(program, "_write_log_line", logged.append)
    with pytest.raises(PermissionError):
        program.run(["--run"])
    assert logged[0].startswith("error: unexpected error (PermissionError): data folder is read-only")
    assert "Traceback (most recent call last)" in logged[0]


def test_ctrl_c_is_a_short_message(program, monkeypatch, capsys):
    def interrupted(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(program, "main", interrupted)
    assert program.run(["--run"]) == 130
    assert "Traceback" not in capsys.readouterr().err


@pytest.fixture
def ready(program, monkeypatch):
    """Skip the setup check: the test's Python already has everything."""
    monkeypatch.setattr(program.bootstrap, "ensure_ready", lambda *a, **k: None)
    return program


def test_rescan_marks_users(ready, capsys):
    from instakeep import paths
    from instakeep.store import Store

    store = Store(paths.STORE_FILE, paths.DEFAULT_OUTPUT)
    store.add_user("natgeo")
    store.record_result("natgeo", "ok", ok=True, full_scan=True)
    assert ready.main(["--rescan", "natgeo"]) == 0
    store.reload()
    assert store.users[0]["full_scan_done"] is False
    assert ready.main(["--rescan", "natgeo", "nobody"]) == 2  # one name isn't listed


def test_list_commands_refuse_a_newer_data_file(ready, capsys):
    import json

    from instakeep import paths

    paths.STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    paths.STORE_FILE.write_text(json.dumps({"version": 99, "users": [{"username": "natgeo"}]}),
                                encoding="utf-8")
    before = paths.STORE_FILE.read_text(encoding="utf-8")
    assert ready.main(["--add", "nasa"]) == 3
    assert "newer version of InstaKeep" in capsys.readouterr().err
    assert paths.STORE_FILE.read_text(encoding="utf-8") == before
    assert ready.main(["--list"]) == 0  # reading is fine
    assert "natgeo" in capsys.readouterr().out
