"""main-program.py's run(): a short message for Ctrl+C, full tracebacks for bugs."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "main-program.py"


@pytest.fixture
def program():
    # The file name has a dash, so it can't be imported with a plain `import`.
    spec = importlib.util.spec_from_file_location("main_program", SCRIPT)
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
