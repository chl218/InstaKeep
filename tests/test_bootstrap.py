import sys
from pathlib import Path

from instakeep import bootstrap


def test_venv_python_paths():
    v = Path("/x/.venv")
    assert bootstrap.venv_python(v, platform="win32") == v / "Scripts" / "python.exe"
    assert bootstrap.venv_python(v, platform="linux") == v / "bin" / "python"


def test_in_venv(tmp_path):
    assert bootstrap.in_venv(tmp_path, prefix=str(tmp_path))
    assert not bootstrap.in_venv(tmp_path / "other", prefix=str(tmp_path))


def test_missing_modules():
    assert bootstrap.missing_modules(["json", "surely_not_a_module_xyz"]) == ["surely_not_a_module_xyz"]


def test_ready_when_everything_installed(monkeypatch):
    # Running the tests means igdl's dependencies are importable; with no other venv to switch to, continue.
    monkeypatch.setattr(bootstrap.paths, "VENV", Path(sys.prefix))
    assert bootstrap.ensure_ready([], ask=None, need_tk=False, say=lambda _m: None) is None


def test_headless_never_asks(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.paths, "VENV", tmp_path / "no-venv")
    monkeypatch.setattr(bootstrap, "missing_modules", lambda names=None: ["instaloader"])
    asked = []
    monkeypatch.setattr(bootstrap, "_ask_gui", lambda q: asked.append(q))
    monkeypatch.setattr(bootstrap, "_ask_console", lambda q: asked.append(q))
    messages = []
    assert bootstrap.ensure_ready(["--run"], ask=None, need_tk=False, say=messages.append) == bootstrap.EXIT_SETUP
    assert asked == [] and "instaloader" in messages[0]
